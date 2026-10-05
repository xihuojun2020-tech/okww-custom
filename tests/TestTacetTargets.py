import unittest
from unittest.mock import Mock

from src.task.TacetTask import TacetTask
from src.task.tacet_targets import TACET_IDS, TACET_OPTIONS, TACET_NAMES, TACET_BUTTON_LABELS, tacet_serial
from src.task.ui_transition import TargetUnavailable


class TestTacetTargets(unittest.TestCase):
    def test_all_old_values_keep_their_original_location(self):
        for old in range(1, 20):
            self.assertEqual(old + 2, tacet_serial(old))
        self.assertEqual(1, tacet_serial(20))
        self.assertEqual(2, tacet_serial(21))
        self.assertEqual(list(range(1, 22)), [tacet_serial(value) for value in TACET_IDS])
        self.assertEqual('方擎西峰无音区', TACET_NAMES[1])

    def test_invalid_values_do_not_choose_another_location(self):
        for value in (0, 22, -1, '1', True, None, 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tacet_serial(value)

    def test_account_choices_show_current_order_and_store_old_ids(self):
        from src.account_field_metadata import account_field_metadata
        field = account_field_metadata({'Which Tacet Suppression to Farm': 1})[0]
        self.assertEqual(TACET_IDS, field.options)
        self.assertEqual(tuple(label for _, label in TACET_OPTIONS), field.option_labels)
        self.assertEqual(21, len(TACET_NAMES))
        for value in TACET_IDS:
            self.assertEqual(TACET_NAMES[value], field.option_labels[field.options.index(value)])

    def task(self):
        task = Mock(spec=TacetTask)
        task.total_number = 21
        task.structure = [4, 5, 5, 7]
        task.game_lang = 'zh_CN'
        return task

    def test_direct_challenge_preserves_entry_flow(self):
        task = self.task()
        task.click_on_book_target.return_value = True
        self.assertTrue(TacetTask.teleport_to_tacet(task, 0))
        task.click_on_book_target.assert_called_once_with(3, 21, [4, 5, 5, 7],
            target_name='方擎西峰无音区',
            button_labels=TACET_BUTTON_LABELS)
        task.wait_click_travel.assert_not_called()

    def test_new_target_travel_requires_available_map(self):
        task = self.task()
        task.click_on_book_target.return_value = False
        TacetTask.teleport_to_tacet(task, 19)
        self.assertEqual(1, task.click_on_book_target.call_args.args[0])
        task.wait_click_travel.assert_called_once()
        task.walk_until_f.assert_called_once()

    def test_unavailable_never_enters_team_or_replaces_target(self):
        task = self.task()
        task.click_on_book_target.side_effect = TargetUnavailable('not unlocked')
        with self.assertRaises(TargetUnavailable):
            TacetTask.teleport_to_tacet(task, 20)
        task.screenshot.assert_called_once_with('tacet_target_unavailable')
        task.wait_click_travel.assert_not_called()
        task.click_team_challenge.assert_not_called()

    def test_invalid_selection_stops_before_any_input(self):
        task = self.task()
        with self.assertRaises(ValueError):
            TacetTask.teleport_to_tacet(task, 21)
        task.scroll_relative.assert_not_called()
        task.click_on_book_target.assert_not_called()

    def test_other_game_locales_keep_positional_selection(self):
        task = self.task()
        task.game_lang = 'en_US'
        task.click_on_book_target.return_value = True
        TacetTask.teleport_to_tacet(task, 0)
        self.assertEqual(3, task.click_on_book_target.call_args.args[0])
        self.assertIsNone(task.click_on_book_target.call_args.kwargs['target_name'])

    def book_task(self, title):
        from types import SimpleNamespace
        from src.task.BaseWWTask import BaseWWTask
        task = Mock(spec=BaseWWTask)
        task.width_of_screen.side_effect = lambda value: 2000 * value
        task.height_of_screen.side_effect = lambda value: 1000 * value
        task._find_book_scroll_top.return_value = .197
        task.ocr.return_value = [SimpleNamespace(name=title, x=900, y=600),
                                SimpleNamespace(name='直接挑战', x=1800, y=640)]
        task.wait_until.side_effect = lambda probe, **kw: probe()
        task.wait_book_target_state.return_value = SimpleNamespace(name='team_entry')
        task._book_target_buttons.side_effect = lambda *args: BaseWWTask._book_target_buttons(task, *args)
        return task

    def test_named_fourth_row_selects_same_row_not_button_index(self):
        from src.task.BaseWWTask import BaseWWTask
        task = self.book_task('玄幽东岳无音区')
        self.assertTrue(BaseWWTask.click_on_book_target(task, 4, 21, [4,5,5,7],
                        target_name='玄幽东岳无音区', button_labels=('前往','直接挑战')))
        task.click.assert_called_once_with(task.ocr.return_value[1], after_sleep=1)

    def test_wrong_named_row_blocks_before_click(self):
        from src.task.BaseWWTask import BaseWWTask
        task = self.book_task('方擎西峰无音区')
        with self.assertRaisesRegex(RuntimeError, '无法确认指南目标'):
            BaseWWTask.click_on_book_target(task, 4, 21, [4,5,5,7],
                        target_name='玄幽东岳无音区', button_labels=('前往','直接挑战'))
        task.click.assert_not_called()

    def test_generic_forgery_button_path_still_uses_features(self):
        from types import SimpleNamespace
        from src.task.BaseWWTask import BaseWWTask
        task = self.book_task('凝素领域')
        first = SimpleNamespace(y=200)
        second = SimpleNamespace(y=400)
        task.find_feature.return_value = [second, first]
        self.assertTrue(BaseWWTask.click_on_book_target(task, 2, 20, [5,5,5,5]))
        task.click.assert_called_once_with(second, after_sleep=1)
