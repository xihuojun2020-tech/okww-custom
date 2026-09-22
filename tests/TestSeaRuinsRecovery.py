"""No game input: checkpoint, inventory and pause safety regressions."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ok import BaseTask, TaskDisabledException
from src.task.AutoSeaRuinsTask import AutoSeaRuinsTask
from src.task.sea_ruins_recovery import SeaRuinsRecovery, SeaLoadoutChanged, STAGES
from src.task.sea_ruins_tokens import CATALOG, identify_token
from src.task.sea_ruins import Preset, Token, choose_loadout, token_score
from datetime import date


class TestSeaRuinsRecovery(unittest.TestCase):
    def task(self, stage='fight_upper'):
        t = Mock()
        t._floor, t._sea_stage = 7, stage
        t._sea_replan = False
        t._token_artwork = {}
        t._wait.return_value = 7
        t.key_config = {'Resonance Key': 'e'}
        t.sleep_check_interval = .4
        t._sea_plan = SimpleNamespace(upper=Preset(1, ('a', 'b', 'c')),
                                     lower=Preset(2, ('d', 'e', 'f')))
        for name in ('_detail', '_token_page', '_map', '_result', '_upper_end'):
            getattr(t, name).return_value = False
        return t

    def test_catalogue_unique_truncation_and_ocr_separator(self):
        for rule in CATALOG:
            self.assertEqual(identify_token(rule.name.replace('-', '一')), rule)
            self.assertEqual(identify_token(rule.name[:4]+'…', rule.rarity), rule)
        lamp = next(rule for rule in CATALOG if rule.name == '那映照虚幻的燃灯')
        self.assertEqual(identify_token('那映照虛', 'gold'), lamp)
        self.assertIsNone(identify_token('那映照虛', 'purple'))
        self.assertIsNone(identify_token('那'))
        self.assertIsNone(identify_token('新信物'))
        self.assertIsNone(identify_token('狂欢者…', 'blue'))

    def test_blue_preferences_follow_actual_members(self):
        heavy = Preset(1, ('char_jiyan', 'char_mortefi', 'char_verina'))
        normal = Preset(2, ('char_camellya', 'char_sanhua', 'char_shorekeeper'))
        tokens = [Token(r.name, r.effect, -1) for r in CATALOG if r.rarity == 'blue']
        hunt = next(t for t in tokens if '游猎' in t.name)
        preach = next(t for t in tokens if '布道' in t.name)
        self.assertGreater(token_score(heavy, hunt, 7), token_score(heavy, preach, 7))
        self.assertGreater(token_score(normal, preach, 7), token_score(normal, hunt, 7))
        plan = choose_loadout([heavy, normal], tokens, 7, date(2026, 9, 20))
        self.assertEqual({plan.upper, plan.lower}, {heavy, normal})

    def test_last_finite_use_is_reserved_more_strongly(self):
        team = Preset(1, ('char_qingxiao', 'char_denia', 'char_verina'))
        one = Token('那丈量心魂的天平', '', 1)
        two = Token(one.name, '', 2)
        self.assertLess(token_score(team, one, 9), token_score(team, two, 9))
        self.assertEqual(token_score(team, one, 11), token_score(team, two, 11))

    def test_pause_releases_before_block_and_clears_combat_deadline(self):
        t = self.task()
        def paused():
            t._release.assert_called_once()
            self.assertIsNone(t._observing_half)
            self.assertIsNone(t._deadline)
            self.assertEqual(t.sleep_check_interval, -1)
        t.pause.side_effect = paused
        SeaRuinsRecovery._pause_for_sea_error(t, RuntimeError('test'))
        t.pause.assert_called_once()
        t.executor.reset_scene.assert_called_once()
        t.disable.assert_not_called()
        self.assertEqual(t.sleep_check_interval, .4)
        t.executor.interaction.send_key_up.assert_called_once()

    def test_native_pause_keeps_current_task_until_user_continue(self):
        t = self.task()
        t.executor.current_task = t
        t.executor.is_executor_thread.return_value = True
        def blocked(seconds):
            self.assertTrue(t._paused)
            self.assertIs(t.executor.current_task, t)
            t.executor.next_task.assert_not_called()
            BaseTask.unpause(t)  # existing UI continue action
        t.sleep.side_effect = blocked
        BaseTask.pause(t)
        t.sleep.assert_called_once_with(1)
        self.assertFalse(t._paused)
        t.executor.start.assert_called_once()

    def test_stop_while_paused_propagates_and_restores_sleep_checks(self):
        t = self.task()
        t.pause.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            SeaRuinsRecovery._pause_for_sea_error(t, RuntimeError('test'))
        self.assertEqual(t.sleep_check_interval, .4)
        t.executor.reset_scene.assert_not_called()

    def test_cancel_never_becomes_pause(self):
        t = self.task()
        t._sea_step.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            SeaRuinsRecovery._run_sea_stages(t)
        t._pause_for_sea_error.assert_not_called()
        t._release.assert_called_once()

    def test_start_reads_current_floor_without_navigation(self):
        t = self.task('open')
        t._wait.return_value = 8
        with patch('src.task.sea_ruins_recovery.vision.normalized'):
            self.assertEqual(SeaRuinsRecovery._sea_step(t), 'presets')
        self.assertEqual((t._floor, t._start_floor), (8, 8))
        t._open.assert_not_called()
        t.openF2Book.assert_not_called()
        t.click_relative.assert_not_called()
        t._wait.assert_called_once_with(t._detail_floor,
            '请进入再生海域7至11层的海墟详情页后继续；未确认左上角层号')

    def test_resume_start_never_chooses_floor_seven_on_map(self):
        t = self.task('open')
        t._floor = None
        t._map.return_value = True
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'open')
        t._seven_boat.assert_not_called()
        t.click_relative.assert_not_called()

    def test_expired_start_does_not_advance_after_continue(self):
        t = self.task('open')
        t._wait.return_value = 8
        with patch('src.task.sea_ruins_recovery.vision.normalized'), \
             patch('src.task.sea_ruins_recovery.season_rule', side_effect=ValueError('失效')):
            for _ in range(2):
                self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'open')
                with self.assertRaisesRegex(ValueError, '失效'):
                    SeaRuinsRecovery._sea_step(t)
        t._scan_presets.assert_not_called()

    def test_floor_parser_rejects_unknown_and_ambiguous_digits(self):
        t = self.task()
        t._button.return_value = True
        for numbers, expected in ((['10'], 10), (['11'], 11), (['CR', '8'], 8),
                                  (['1', '1'], None), (['8', '9'], None), (['12'], None)):
            t._small_text.return_value = numbers
            # Header is present, name/template fallback is not.
            t._button.side_effect = lambda frame, region, text: text == '海墟详情'
            self.assertEqual(AutoSeaRuinsTask._detail_floor(t, t.frame), expected)

    def test_start_from_eight_does_not_repeat_seven(self):
        t = self.task('open')
        t._wait.return_value = 8
        plan = SimpleNamespace(upper=Preset(1, ('a','b','c')), lower=Preset(2, ('d','e','f')),
                               tokens=(Token('a','',2), Token('b','',2)), reasons=())
        t._sea_step.side_effect = lambda: SeaRuinsRecovery._sea_step(t)
        with patch('src.task.sea_ruins_recovery.choose_loadout', return_value=plan), \
             patch('src.task.sea_ruins_recovery.vision.normalized'):
            SeaRuinsRecovery._run_sea_stages(t)
        self.assertEqual(t._scan_presets.call_count, 4)
        self.assertEqual(t._scan_tokens.call_count, 4)
        self.assertEqual(t._continue.call_count, 3)
        t._status.assert_called_with('8—11层挑战完成；未挑战无尽，未领取奖励')

    def test_error_preserves_stage_and_retries_after_resume(self):
        t = self.task()
        t._sea_step.side_effect = ['tokens', RuntimeError('ocr'), 'done']
        t._resume_sea_stage.return_value = 'tokens'
        def pause(error):
            self.assertEqual(t._sea_stage, 'tokens')
        t._pause_for_sea_error.side_effect = pause
        SeaRuinsRecovery._run_sea_stages(t)
        self.assertEqual(t._sea_step.call_count, 3)
        t._resume_sea_stage.assert_called_once()
        t._pause_for_sea_error.assert_called_once()

    def test_unknown_resume_pauses_again_not_restart_from_open(self):
        t = self.task()
        t._sea_step.side_effect = RuntimeError('first')
        t._resume_sea_stage.side_effect = [RuntimeError('unknown page'), 'done']
        SeaRuinsRecovery._run_sea_stages(t)
        self.assertEqual(t._pause_for_sea_error.call_count, 2)
        t._sea_step.assert_called_once()

    def test_detail_after_battle_invalidates_plan_and_inventory(self):
        t = self.task()
        t._detail.return_value = True
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'presets')
        self.assertIsNone(t._sea_plan)

    def test_preparation_preserves_unfinished_slot(self):
        for stage in ('team_lower', 'token_upper', 'token_lower'):
            t = self.task(stage)
            t._detail.return_value = True
            self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), stage)

    def test_changed_inventory_replans_instead_of_repeating_unavailable_target(self):
        t = self.task('token_lower')
        t._sea_replan = True
        t._detail.return_value = True
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'presets')
        self.assertFalse(t._sea_replan)
        t = self.task()
        t._sea_step.side_effect = ['token_lower', SeaLoadoutChanged('empty')]
        def resume():
            self.assertTrue(t._sea_replan)
            return 'done'
        t._resume_sea_stage.side_effect = resume
        SeaRuinsRecovery._run_sea_stages(t)
        t._pause_for_sea_error.assert_called_once()

    def test_enter_retry_does_not_rescan_completed_preparation(self):
        t = self.task('enter')
        t._sea_plan.tokens = (Token('a', '', 1), Token('b', '', 1))
        t._detail.return_value = True
        t._members_match.return_value = True
        t._token_equipped.return_value = True
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'enter')

    def test_upper_complete_skips_battle_and_lower_manual_entry_skips_exit(self):
        t = self.task()
        t._upper_end.return_value = True
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'enter_lower')
        t._upper_end.return_value = False
        t.chars = [SimpleNamespace(char_name=c) for c in ('d', 'e', 'f')]
        def load():
            t.chars = [SimpleNamespace(char_name=c) for c in ('d', 'e', 'f')]
        t.load_chars.side_effect = load
        with patch('src.task.sea_ruins_recovery.vision.sea_world', return_value=True):
            self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'start_lower')
        t._enter_lower.assert_not_called()

    def test_world_without_sea_identity_never_resumes_combat(self):
        t = self.task()
        with patch('src.task.sea_ruins_recovery.vision.sea_world', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '无法确认'):
                SeaRuinsRecovery._resume_sea_stage(t)
        t.load_chars.assert_not_called()

    def test_result_and_next_detail_do_not_repeat_challenge(self):
        t = self.task('fight_lower')
        t._result.return_value = True
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'result')
        t = self.task('next')
        t._detail.side_effect = lambda frame, floor=None: floor == 8
        self.assertEqual(SeaRuinsRecovery._resume_sea_stage(t), 'presets')
        self.assertEqual(t._floor, 8)
        t._continue.assert_not_called()

    def test_all_stages_have_an_action_and_finished_result_increments_once(self):
        for stage in STAGES[:-1]:
            t = self.task(stage)
            t._sea_presets, t._sea_tokens = [], []
            t._sea_plan.tokens = (Token('a', '', 1), Token('b', '', 1))
            with patch('src.task.sea_ruins_recovery.choose_loadout', return_value=SimpleNamespace(reasons=())), \
                 patch('src.task.sea_ruins_recovery.vision.normalized'):
                self.assertIn(SeaRuinsRecovery._sea_step(t), STAGES)
            self.assertEqual(t._floor, 8 if stage == 'next' else 7)

    def test_full_checkpoint_loop_scans_each_floor_once(self):
        t = self.task()
        plan = SimpleNamespace(upper=Preset(1, ('a','b','c')), lower=Preset(2, ('d','e','f')),
                               tokens=(Token('a','',2), Token('b','',2)), reasons=())
        t._sea_step.side_effect = lambda: SeaRuinsRecovery._sea_step(t)
        with patch('src.task.sea_ruins_recovery.choose_loadout', return_value=plan), \
             patch('src.task.sea_ruins_recovery.vision.normalized'):
            SeaRuinsRecovery._run_sea_stages(t)
        self.assertEqual(t._floor, 11)
        self.assertEqual(t._scan_presets.call_count, 5)
        self.assertEqual(t._scan_tokens.call_count, 5)
        self.assertEqual(t._equip_token.call_count, 10)
        self.assertEqual(t._enter_lower.call_count, 5)
        self.assertEqual(t._continue.call_count, 4)
        t._pause_for_sea_error.assert_not_called()

    def test_equipped_token_is_not_clicked_again(self):
        t = self.task()
        t._token_equipped.return_value = True
        AutoSeaRuinsTask._equip_token(t, 0, Token('审判-遗落令旗', '', -1))
        t._open_tokens.assert_not_called()
        t.click_relative.assert_not_called()

    def test_only_target_is_clicked_and_title_is_verified(self):
        t = self.task()
        t._token_equipped.return_value = False
        target = Token('审判-遗落令旗', '', -1)
        t._inventory_page.return_value = [(Token('布道-遗落令旗', '', -1), (1,2,3,4)),
                                       (target, (100,200,160,196))]
        with patch('src.task.AutoSeaRuinsTask.vision.token_art'):
            AutoSeaRuinsTask._equip_token(t, 0, target)
        t.click_relative.assert_called_once_with(180/2048, 298/1152, after_sleep=.25)
        self.assertIn('详细名称', t._wait.call_args_list[0].args[1])
        t.click_box.assert_called_once()
        t.scroll_relative.assert_not_called()

    def test_inventory_scan_and_missing_target_do_not_scroll_into_green_tokens(self):
        t = self.task()
        token = Token('审判-遗落令旗', '', -1)
        t._inventory_page.return_value = [(token, (100, 200, 160, 196))]
        with patch('src.task.AutoSeaRuinsTask.vision.token_art', return_value='art'):
            self.assertEqual(AutoSeaRuinsTask._scan_tokens(t), [token])
        t.scroll_relative.assert_not_called()

        t = self.task()
        t._token_equipped.return_value = False
        t._inventory_page.return_value = []
        with self.assertRaisesRegex(SeaLoadoutChanged, '未找回信物'):
            AutoSeaRuinsTask._equip_token(t, 0, token)
        t.scroll_relative.assert_not_called()

    def test_unavailable_target_never_clicked(self):
        t = self.task()
        t._token_equipped.return_value = False
        token = Token('审判-遗落令旗', '', 0)
        t._inventory_page.return_value = [(token, (100,200,160,196))]
        with self.assertRaisesRegex(RuntimeError, '不可携带'):
            AutoSeaRuinsTask._equip_token(t, 0, token)
        t.click_relative.assert_not_called()

    def test_inventory_read_retries_without_input_and_propagates_cancel(self):
        t = self.task()
        t._token_page.return_value = True
        t._page_tokens.side_effect = [RuntimeError('unknown count'), [('token', 'rect')]]
        self.assertEqual(AutoSeaRuinsTask._inventory_page(t), [('token', 'rect')])
        self.assertEqual(t.next_frame.call_count, 2)
        t.click_relative.assert_not_called()
        t._page_tokens.side_effect = RuntimeError('unknown count')
        with self.assertRaisesRegex(RuntimeError, 'unknown count'):
            AutoSeaRuinsTask._inventory_page(t)
        t._page_tokens.side_effect = TaskDisabledException()
        with self.assertRaises(TaskDisabledException):
            AutoSeaRuinsTask._inventory_page(t)

    def test_unlock_handler_is_bounded_and_never_clicks_unknown_popup(self):
        for observations, clicks, fails in (([False], 0, False), ([True, False], 1, False),
                                            ([True]*4, 3, True)):
            # Real instance needed for super().next_frame(); capture/input are mocked.
            t = object.__new__(AutoSeaRuinsTask)
            t._handling_unlock = False
            t._unlock_popup = Mock(side_effect=observations)
            t.click_relative = Mock()
            t._executor = Mock()
            with patch('src.task.BaseCombatTask.BaseCombatTask.next_frame'):
                if fails:
                    with self.assertRaisesRegex(RuntimeError, '弹窗未能关闭'):
                        t._dismiss_unlock()
                else:
                    t._dismiss_unlock()
            self.assertEqual(t.click_relative.call_count, clicks)
            self.assertFalse(t._handling_unlock)
