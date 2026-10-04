import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.WorldBossMaterialTask import WorldBossMaterialTask


class TestWorldBossMaterialEntryImages(TaskTestCase):
    config = config
    task_class = WorldBossMaterialTask

    def test_actual_failed_frame_is_formation_without_detail_or_single(self):
        self.set_image('tests/images/material_boss_entry/direct_formation.png')
        frame = self.task.frame
        self.assertTrue(self.task._material_formation_ready(frame))
        self.assertIsNone(self.task._button(self.task.SINGLE, '单人挑战', frame))
        self.assertNotIn('海之女', self.task._text(self.task.TITLE, frame))

    def test_weekly_detail_and_guidebook_are_not_formation(self):
        for path in ('tests/images/weekly_boss/detail.png', 'tests/images/new_book_entries/weekly.png'):
            self.set_image(path)
            self.assertFalse(self.task._material_formation_ready(self.task.frame), path)


if __name__ == '__main__':
    unittest.main()
