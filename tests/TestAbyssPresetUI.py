import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.Labels import Labels
from src.task.AutoAbyssTask import (
    AVAILABLE, UNKNOWN, AbyssSavedPreset, AbyssTeamUnavailable, AutoAbyssTask, CharacterScanRecord,
    current_preset_energy,
)
from src.task.abyss_allocation import current_season_rules, allocate, ElementRule, FloorRequest


class TestAbyssPresetUI(unittest.TestCase):
    def test_current_energy_is_left_of_arrow(self):
        self.assertEqual(current_preset_energy('10 » 9'), 10)
        self.assertEqual(current_preset_energy('10 → 6'), 10)
        self.assertEqual(current_preset_energy('￥10'), 10)
        self.assertEqual(current_preset_energy('410'), 10)
        self.assertEqual(current_preset_energy('410>15'), 10)
        self.assertEqual(current_preset_energy('110》45'), 10)
        self.assertEqual(current_preset_energy('0 > 0'), 0)
        self.assertIsNone(current_preset_energy('10 5'))
        self.assertIsNone(current_preset_energy('19 > 5'))
        self.assertIsNone(current_preset_energy('M0 > 5'))
        self.assertIsNone(current_preset_energy('19'))

    def test_season_elements(self):
        rules = current_season_rules()
        self.assertEqual((rules['Left'].favored, rules['Left'].soft), (('气动',), '导电'))
        self.assertEqual((rules['Right'].favored, rules['Right'].soft), (('湮灭',), '冷凝'))
        self.assertEqual((rules['Center Lower'].favored, rules['Center Lower'].hard,
                          rules['Center Lower'].soft), (('导电', '热熔'), '冷凝', '湮灭'))
        self.assertEqual((rules['Center Upper'].favored, rules['Center Upper'].hard), ((), '衍射'))

    def test_numbered_rows_ignore_clipped_bottom_card(self):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._executor = SimpleNamespace(method=SimpleNamespace(height=1152))
        task.ocr = lambda *_args, **_kwargs: [
            SimpleNamespace(name=str(n), y=int(y * 1152), height=40)
            for n, y in ((1, .26), (2, .455), (3, .65), (4, .845))
        ]
        rows = task._preset_page_rows(None)
        self.assertEqual([number for number, _ in rows], [1, 2, 3])

    def test_allocation_only_uses_scanned_real_preset(self):
        preset = AbyssSavedPreset(7, (Labels.char_qingxiao, Labels.char_denia,
                                       Labels.char_verina), (10, 10, 10))
        records = [CharacterScanRecord(member, str(member), 10, None, 1., 0, 0)
                   for member in preset.members]
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._preset_mode = True
        task._saved_presets = {7: preset}
        task._abyss_rules = current_season_rules()
        task._allocation_context = ('残响之塔', 0, {'残响之塔': (AVAILABLE,)}, '两侧塔优先')
        task.sleep = lambda *_: None
        task.info_set = lambda *_: None
        task.log_info = lambda *_: None
        plan = task._allocate_remaining(records)
        self.assertEqual(plan.preset.queue, 7)
        self.assertEqual(plan.members, preset.members)

    def test_no_scanned_preset_never_creates_a_synthetic_team(self):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._preset_mode = True
        task._saved_presets = {}
        task._preset_scan_incomplete = False
        task._abyss_rules = current_season_rules()
        task._allocation_context = ('残响之塔', 0, {'残响之塔': (AVAILABLE,)}, '两侧塔优先')
        task.sleep = lambda *_: None
        task.info_set = lambda *_: None
        task.log_info = lambda *_: None
        records = [CharacterScanRecord(x, str(x), 10, None, 1., 0, 0) for x in
                   (Labels.char_qingxiao, Labels.char_denia, Labels.char_verina)]
        with self.assertRaises(AbyssTeamUnavailable):
            task._allocate_remaining(records)

    def test_allocator_skips_preset_with_member_missing_from_energy_ledger(self):
        bad = AbyssSavedPreset(1, (Labels.char_qingxiao, Labels.char_denia, Labels.char_verina),
                               (10, 0, 10))
        good = AbyssSavedPreset(2, (Labels.char_jiyan, Labels.char_mortefi, Labels.char_shorekeeper),
                                (10, 10, 10))
        floors = [FloorRequest('残响之塔', 0, 1, ElementRule(), True)]
        for energy in (0, None):
            with self.subTest(energy=energy):
                records = [CharacterScanRecord(m, str(m), energy if m == Labels.char_denia else 10,
                                              None, 1., 0, 0) for m in bad.members + good.members]
                result = allocate(records, floors, candidates=(bad.plan, good.plan), require_level=False)
                self.assertEqual(result.assignments[0][1].preset.queue, 2)

    def test_preset_ledger_lists_level_unknown_and_excludes_deferred_center(self):
        preset = AbyssSavedPreset(7, (Labels.char_qingxiao, Labels.char_denia, Labels.char_verina),
                                 (10, 10, 10))
        records = [CharacterScanRecord(m, str(m), 10, None, 1., 0, 0) for m in preset.members]
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._preset_mode = True
        task._saved_presets = {7: preset}
        task._abyss_rules = current_season_rules()
        task._allocation_context = ('残响之塔', 0, {'残响之塔': (AVAILABLE,),
                                   '回音之塔': (UNKNOWN,), '深境之塔': (AVAILABLE,)}, '两侧塔优先')
        task.sleep = Mock()
        task.info_set = Mock()
        task.log_info = Mock()
        self.assertEqual(task._allocate_remaining(records).preset.queue, 7)
        self.assertNotIn(('深境之塔', 0), task._scheduled_teams)
        ledger = next(c.args[1] for c in task.info_set.call_args_list if c.args[0] == '角色体力账本')
        self.assertIn(str(Labels.char_denia) + '=10', ledger)
        self.assertNotIn('无可核对角色', ledger)

    def test_preset_energy_needs_two_arrow_readings_and_rejects_conflicts(self):
        import numpy as np
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        frame = np.zeros((1152, 2048, 3), np.uint8)
        for texts, expected in ((('10>15', '0 5', '110>45'), 10),
                                (('10>5', '', ''), None),
                                (('10>5', '0>0', '10>5'), None),
                                (('0>0', '0>0', '0>0'), 0)):
            with self.subTest(texts=texts):
                task.ocr = Mock(side_effect=[[SimpleNamespace(name=t)] if t else [] for t in texts] + [[], [], []])
                self.assertEqual(task._preset_energy(frame, .207, .185), expected)

    def test_challenge_start_opens_preset_tab_without_old_quick_formation(self):
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._open_tower = Mock()
        task._set_status = Mock()
        task.click_relative = Mock()
        task.click_box = Mock()
        task._wait_exact_text = Mock(return_value=SimpleNamespace(name='挑战开始'))
        task._wait_exact_text_or_fail = Mock(side_effect=lambda text, *_args: SimpleNamespace(name=text))
        task._scan_saved_presets = Mock(return_value=['scanned'])
        result = task._enter_and_scan_characters('残响之塔', (AVAILABLE,))
        self.assertEqual(result, ['scanned'])
        self.assertTrue(task._preset_mode)
        self.assertEqual(task.click_box.call_count, 2)
        texts = [call.args[0] for call in task._wait_exact_text_or_fail.call_args_list]
        self.assertEqual(texts, ['角色列表', '预设编队', '开启挑战'])

    def test_missing_arrow_uses_current_box_position_and_excludes_projected_number(self):
        import numpy as np
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        frame = np.zeros((720, 1280, 3), np.uint8)
        task.ocr = Mock(side_effect=[
            [SimpleNamespace(name=text, x=75, width=100),
             SimpleNamespace(name='10', x=350, width=70)] for text in ('4', '14', '4')])
        self.assertEqual(task._preset_energy(frame, .207, .185), 4)

    def test_color_recheck_never_promotes_clipped_zero_to_usable_energy(self):
        import numpy as np
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        frame = np.zeros((720, 1280, 3), np.uint8)
        task.ocr = Mock(return_value=[SimpleNamespace(name='0', x=0, width=50)])
        self.assertIsNone(task._preset_energy(frame, .207, .185))

    def test_apply_preset_checks_page_again_before_click(self):
        preset = AbyssSavedPreset(7, (Labels.char_qingxiao, Labels.char_denia,
                                       Labels.char_verina), (10, 10, 10))
        task = AutoAbyssTask.__new__(AutoAbyssTask)
        task._saved_presets = {7: preset}
        task.scroll_relative = Mock()
        task.sleep = Mock()
        task._wait_stable_preset_frame = Mock(return_value='frame')
        task._preset_page_rows = Mock(return_value=[(7, .2)])
        task._preset_on_row = Mock(return_value=preset)
        task.click_relative = Mock()
        task.wait_until = Mock(return_value=True)
        task.log_info = Mock()
        task._apply_saved_preset(preset.plan)
        task.click_relative.assert_called_once()
        self.assertEqual(task._active_preset_plan.members, preset.members)


if __name__ == '__main__':
    unittest.main()
