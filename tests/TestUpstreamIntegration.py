import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
from src.char.BaseChar import BaseChar
from src.char.CharFactory import char_dict, get_char_by_pos
from src.char.Lucy import Lucy
from src.char.Rebecca import Rebecca
from src.char.Mornye import Mornye
from src.char.TrialGenericChar import TrialGenericChar
from src.task.BaseCombatTask import BaseCombatTask
from src.task.CharacterTrialTask import CharacterTrialTask
from src.task.MouseResetTask import MouseResetTask


class TestUpstreamIntegration(unittest.TestCase):
    def test_portrait_registration_preserves_generic_trial_identity(self):
        for label in ('char_aalto', 'char_lingyang', 'char_lumi', 'char_yangyang'):
            task = Mock()
            task.find_best_match_in_box.return_value = SimpleNamespace(name=label, confidence=.95)
            char = get_char_by_pos(task, None, 0, None)
            self.assertIs(type(char), BaseChar)
            self.assertEqual(char.char_name, label)
            trial = object.__new__(CharacterTrialTask)
            trial.chars = [char]
            trial.log_info = Mock()
            with patch.object(BaseCombatTask, 'load_chars', return_value=True):
                trial.load_chars()
            self.assertIsInstance(trial.chars[0], TrialGenericChar)
            self.assertEqual(trial.chars[0].char_name, label)
            self.assertEqual(trial.chars[0].ring_index, char.ring_index)
        self.assertIsNot(char_dict['char_yangyang']['cls'], char_dict['yangyang_sp']['cls'])

    def test_portrait_assets_have_unique_ids_and_nonempty_crops(self):
        data = json.loads(Path('assets/coco_annotations.json').read_text(encoding='utf8'))
        for key in ('images', 'categories', 'annotations'):
            ids = [i['id'] for i in data[key]]
            self.assertEqual(len(ids), len(set(ids)))
        images = {i['id']: i for i in data['images']}
        for label in ('char_aalto', 'char_lingyang', 'char_lumi', 'char_yangyang'):
            categories = [c for c in data['categories'] if c['name'] == label]
            self.assertEqual(len(categories), 1)
            annotations = [a for a in data['annotations'] if a['category_id'] == categories[0]['id']]
            self.assertEqual(len(annotations), 1)
            a = annotations[0]
            image = cv2.imread(str(Path('assets') / images[a['image_id']]['file_name']))
            x, y, w, h = map(round, a['bbox'])
            self.assertGreater(image[y:y+h, x:x+w].std(), 10)

    def test_mouse_scheduler_deduplicates_and_respects_disabled(self):
        task = Mock(enabled=True)
        task.is_browser.return_value = False
        task.post_mouse_reset = lambda delay: MouseResetTask.post_mouse_reset(task, delay)
        MouseResetTask.run(task)
        task.handler.post.assert_called_once_with(task.mouse_reset, .01, remove_existing=True)
        task.enabled = False
        with patch('src.task.MouseResetTask.win32api.GetCursorPos') as cursor:
            MouseResetTask.mouse_reset(task)
            cursor.assert_not_called()

    def test_mouse_exception_does_not_prevent_later_reschedule(self):
        task = Mock(enabled=True, mouse_pos=None)
        task.is_browser.return_value = False
        task.post_mouse_reset = lambda delay: MouseResetTask.post_mouse_reset(task, delay)
        with patch('src.task.MouseResetTask.win32api.GetCursorPos', side_effect=RuntimeError('fake')):
            MouseResetTask.mouse_reset(task)
        MouseResetTask.run(task)
        task.handler.post.assert_called_once_with(task.mouse_reset, .01, remove_existing=True)

    def test_mouse_keeps_20hz_polling(self):
        task = Mock(enabled=True, mouse_pos=None)
        task.is_browser.return_value = False
        with patch('src.task.MouseResetTask.win32api.GetCursorPos', return_value=(100, 100)):
            MouseResetTask.mouse_reset(task)
        task.post_mouse_reset.assert_called_once_with(.05)

    def test_lucy_hold_releases_on_stop(self):
        task = Mock()
        char = Lucy(task, 0)
        char.check_combat = Mock()
        char.sleep = Mock(side_effect=RuntimeError('stopped'))
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            char.heavy_attack(2.5)
        task.mouse_up.assert_called_once()

    def test_lucy_unavailable_forte_wait_is_bounded_and_stop_propagates(self):
        char = Lucy(Mock(), 0)
        char.logger = Mock()
        for name in ('f_break', 'perform_enhanced_heavy', 'click', 'sleep'):
            setattr(char, name, Mock())
        char.resonance_available = char.echo_available = char.liberation_available = Mock(return_value=False)
        char.is_mouse_forte_full = Mock(return_value=False)
        with patch('src.char.Lucy.time.time', side_effect=[0, 1, 7]):
            char.perform_liberation()
        char.click.assert_called_once()
        char.sleep.side_effect = RuntimeError('stopped')
        with patch('src.char.Lucy.time.time', side_effect=[0, 1]), self.assertRaises(RuntimeError):
            char.perform_liberation()

    def test_rebecca_failed_cast_does_not_start_cooldown_window(self):
        char = Rebecca(Mock(), 0)
        char.click_liberation = Mock(return_value=False)
        self.assertFalse(char.perform_hmg_mode())
        self.assertFalse(char._in_reenter_window())
        char.click_liberation.assert_called_once_with(send_click=True, click_f=False)

    def test_rebecca_cooldown_uses_freeze_adjusted_time(self):
        char = Rebecca(Mock(), 0)
        char._last_liberation_at = 10
        char.time_elapsed_accounting_for_freeze = Mock(return_value=16)
        self.assertTrue(char._in_reenter_window())
        char.time_elapsed_accounting_for_freeze.return_value = 17
        self.assertFalse(char._in_reenter_window())
        self.assertFalse(char.check_f_on_switch)

    def test_rebecca_charged_hold_releases_and_skips_later_skills_on_stop(self):
        char = Rebecca(Mock(), 0)
        for name in ('continues_normal_attack', 'click_resonance', 'check_combat'):
            setattr(char, name, Mock())
        char.resonance_available = char.is_mouse_forte_full = Mock(return_value=True)
        char.sleep = Mock(side_effect=RuntimeError('stopped'))
        char.click_echo = Mock()
        with self.assertRaises(RuntimeError):
            char._build_forte_sequence()
        char.task.mouse_up.assert_called_once()
        char.click_echo.assert_not_called()

    def test_mornye_builds_concerto_before_echo(self):
        char = Mornye(Mock(), 0)
        for name in ('echo_available', 'on_air', 'is_mouse_forte_full', 'heavy_click_forte'):
            setattr(char, name, Mock(return_value=True))
        char.detect_elbow_strike = Mock(return_value=False)
        char.click_liberation = Mock()
        char.task.wait_until.return_value = False
        char.is_con_full = Mock(side_effect=[False, True, True])
        char.continues_normal_attack = Mock()
        char.click_echo = Mock()
        char.on_air_actions()
        char.continues_normal_attack.assert_called_once_with(.5)
        char.click_echo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
