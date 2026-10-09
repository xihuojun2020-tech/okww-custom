import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2

from src.task.TiangongTreasureTask import TiangongTreasureTask, TiangongResult
from src.task.BaseCombatTask import CharDeadException, CombatStateUnknown
from src.task.tiangong_treasure import Progress, hardest, stage_state, trial_numbers, zero_score

FIXTURES = Path(__file__).parent / 'fixtures/tiangong_treasure'
ACCOUNT = '00000000-0000-4000-8000-000000000001'


def boxes(*texts):
    return [SimpleNamespace(name=text) for text in texts]


class TestTiangongTreasure(unittest.TestCase):
    def test_scores_and_lock_are_not_missing_score_defaults(self):
        for score, status in [(0, 'pending'), (79999, 'pending'), (80000, 'completed'), (90952, 'completed')]:
            self.assertEqual(stage_state(boxes('见习札记I', '最高款项：', str(score))),
                             dict(score=score, status=status))
        self.assertEqual(stage_state(boxes('14小时54分钟后解锁该关卡'))['status'], 'locked')
        self.assertIsNone(stage_state(boxes('见习札记I', '最高款项：')))
        self.assertIsNone(stage_state(boxes('推荐等级90')))

    def test_only_recommended_90_confirms_difficulty(self):
        self.assertTrue(hardest(boxes('推荐等级', '90')))
        self.assertFalse(hardest(boxes('推荐等级70')))
        self.assertFalse(hardest(boxes('困难·款项倍率×4')))

    def test_real_trial_badges_and_border_at_two_resolutions(self):
        for name, expected in [('formation', (1, 2, 3)), ('permuted', (3, 1, 2)),
                               ('unselected', (0, 0, 0)), ('border', (0, 0, 0))]:
            original = cv2.imread(str(FIXTURES / f'{name}.png'))
            for height in (1080, 1440):
                with self.subTest(name=name, height=height):
                    self.assertEqual(trial_numbers(cv2.resize(original, (height*16//9, height))), expected)

    def test_progress_resumes_without_losing_attempt_time_and_isolates_account_period(self):
        with tempfile.TemporaryDirectory() as root:
            progress = Progress(ACCOUNT, 'first', root)
            progress.update(0, dict(status='completed', score=90952))
            progress.update(1, dict(status='pending', score=12000, challenged_at='time'))
            resumed = Progress(ACCOUNT, 'first', root)
            self.assertEqual(resumed.stages['1']['score'], 90952)
            resumed.update(1, dict(status='pending', score=12000))
            self.assertEqual(resumed.stages['2']['challenged_at'], 'time')
            self.assertEqual(Progress(ACCOUNT, 'second', root).stages, {})
            self.assertEqual(Progress('00000000-0000-4000-8000-000000000002', 'first', root).stages, {})
            self.assertEqual(json.loads(resumed.path.read_text())['periods']['first']['1']['status'], 'completed')

    def test_difficulty_opens_by_position_and_waits_for_90(self):
        task = object.__new__(TiangongTreasureTask)
        task.require_game_frame = Mock(return_value=object())
        task.ocr = Mock(return_value=boxes('推荐等级70'))
        task._selected = Mock(return_value=True)
        task._click = Mock()
        task._wait = Mock()
        task._difficulty(1)
        self.assertEqual([call.args for call in task._click.call_args_list], [(.80, .785), (.80, .697)])
        task._click.reset_mock()
        task.ocr.return_value = boxes('推荐等级90')
        task._difficulty(2)
        task._click.assert_not_called()

    def test_only_missing_trial_is_clicked(self):
        task = object.__new__(TiangongTreasureTask)
        task._wait = Mock()
        task._formation = Mock(return_value=True)
        task.next_frame = Mock(return_value=object())
        task._click = Mock()
        with patch('src.task.TiangongTreasureTask.trial_numbers', side_effect=[(3, 0, 2), (3, 0, 2), (3, 1, 2)]):
            task._choose_trials()
        task._click.assert_called_once_with(.11+.0837, .235)

    def test_gap_waits_for_observed_result_and_death_is_not_swallowed(self):
        task = object.__new__(TiangongTreasureTask)
        task.combat_once = Mock(side_effect=CombatStateUnknown('wave gap'))
        task._release_combat_inputs = Mock()
        task._wait = Mock(side_effect=TiangongResult())
        task.reset_to_false = Mock()
        task._fight()
        task._wait.assert_called_once()
        self.assertFalse(task._fighting)
        task.combat_once.side_effect = CharDeadException()
        with self.assertRaises(CharDeadException):
            task._fight()

    def test_checkpoint_rejects_changed_account_without_writing(self):
        task = object.__new__(TiangongTreasureTask)
        task._verification = SimpleNamespace(finish=Mock(return_value='mismatch'))
        task._progress = SimpleNamespace(update=Mock())
        with self.assertRaises(RuntimeError):
            task._checkpoint(0, dict(status='completed', score=90000))
        task._progress.update.assert_not_called()

    def test_start_checks_prompt_before_moving(self):
        for prompts, expected_keys in [([True], ['f']), ([False, True], ['w', 'f'])]:
            task = object.__new__(TiangongTreasureTask)
            task.next_frame = Mock(return_value=object())
            task.ocr = Mock(return_value=[])
            task.in_team_and_world = Mock(return_value=True)
            task.send_key = Mock()
            task.sleep = Mock()
            task._release_combat_inputs = Mock()
            with patch.object(TiangongTreasureTask, 'height', new=property(lambda _: 1152)), \
                    patch('src.task.TiangongTreasureTask.start_prompt', side_effect=prompts):
                task._start()
            self.assertEqual([call.args[0] for call in task.send_key.call_args_list], expected_keys)

    def test_isolated_zero_is_observed_and_not_a_missing_or_multidigit_score(self):
        image = cv2.imread(str(FIXTURES/'page.png'))
        self.assertFalse(zero_score(image, 0))
        self.assertTrue(zero_score(image, 1))
        image[342:387, 328:475] = 0
        self.assertFalse(zero_score(image, 1))

    def test_run_manually_selects_each_pending_stage_once_and_keeps_low_score(self):
        from src.evidence.cycles import seed_cycles
        complete = dict(status='completed', score=90952)
        pending = dict(status='pending', score=0)
        locked = dict(status='locked', score=None)
        task = object.__new__(TiangongTreasureTask)
        executor = SimpleNamespace(completion_evidence_service=SimpleNamespace(repository=SimpleNamespace(cycles=seed_cycles)))
        verification = SimpleNamespace(profile_id=ACCOUNT, finish=Mock(return_value='verified'))
        task._read = Mock(side_effect=[complete, pending, pending, pending, complete, locked, locked, locked,
                                     complete, pending, complete, locked, locked, locked])
        for method in ('_wait', '_select', '_enter', '_start', '_fight', '_click', 'screenshot',
                       '_evidence', 'info_set', '_release_combat_inputs'):
            setattr(task, method, Mock())
        with tempfile.TemporaryDirectory() as root, \
                patch.object(TiangongTreasureTask, 'executor', new=property(lambda _: executor)), \
                patch('src.task.WWOneTimeTask.WWOneTimeTask.run'), \
                patch('src.task.account_feature_verification.current_feature_run', return_value=verification), \
                patch('src.task.TiangongTreasureTask.Progress', side_effect=lambda identity, period: Progress(identity, period, root)):
            task.run()
            self.assertEqual([call.args[0] for call in task._select.call_args_list], [1, 2])
            self.assertEqual(task._fight.call_count, 2)
            self.assertEqual(task._progress.stages['2']['status'], 'pending')
            self.assertIn('challenged_at', task._progress.stages['2'])
            self.assertEqual(task._progress.stages['3']['status'], 'completed')
            self.assertEqual(task._evidence.call_args.args[0], 'partial')


if __name__ == '__main__':
    unittest.main()
