import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.WeeklyBossTask import WeeklyBossTask
from src.task.weekly_boss import WEEKLY_BOSSES, weekly_title_rows, boss_title, match_target_button
from src.task.tacet_targets import TACET_NAMES


class TestNewBookEntryImages(TaskTestCase):
    config = config
    task_class = WeeklyBossTask

    def test_tacet_new_rows_and_direct_challenge_buttons(self):
        self.set_image('tests/images/new_book_entries/tacet.png')
        for value, expected in ((20, '前往'), (21, '前往'), (1, '直接挑战'), (2, '直接挑战')):
            buttons = self.task._book_target_buttons(self.task.frame, ('前往', '直接挑战'), TACET_NAMES[value])
            self.assertEqual(1, len(buttons), TACET_NAMES[value])
            self.assertEqual(expected, buttons[0].name)
        self.assertEqual([], self.task._book_target_buttons(self.task.frame,
                         ('直接挑战',), TACET_NAMES[20]))

    def test_weekly_limited_first_row_and_zero_allowance(self):
        self.set_image('tests/images/new_book_entries/weekly.png')
        boxes = self.task._ocr(self.task.LIST)
        target = next(boss for boss in WEEKLY_BOSSES if boss.key == 'weekly_order_law')
        self.assertEqual(target.name, boss_title(weekly_title_rows(boxes, self.task.height)[0].name))
        self.assertIsNotNone(match_target_button(boxes, target.name, self.task.height))
        self.assertEqual(0, self.task._weekly_book_remaining())
        self.assertFalse(self.task._story_entry_warning(self.task.frame))

    def test_story_warning_confirmation(self):
        self.set_image('tests/images/new_book_entries/story.png')
        self.assertTrue(self.task._story_entry_warning(self.task.frame))
        button = self.task._story_entry_confirmation(self.task.frame)
        self.assertIsNotNone(button)
        self.assertEqual('确认', button.name)


if __name__ == '__main__': unittest.main()
