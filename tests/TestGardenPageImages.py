import unittest
from unittest.mock import patch
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.GardenTask import GardenTask
from src.task.weekly_garden import garden_weekly_page


class TestGardenPageImages(TaskTestCase):
    task_class = GardenTask
    config = config

    def test_zero_current_value_is_not_the_six_thousand_reward_scale(self):
        self.set_image('tests/images/garden_page/zero.png')
        self.assertTrue(garden_weekly_page(self.task.ocr(frame=self.task.frame)))
        self.assertEqual(0, self.task.read_weekly_garden_points())
        self.assertFalse(self.task.is_weekly_garden_completed())

    def test_completed_current_value_is_read_without_a_fraction(self):
        self.set_image('tests/images/garden_page/completed.png')
        self.assertEqual(6000, self.task.read_weekly_garden_points())

    def test_partial_or_missing_header_still_reads_anchored_current_value(self):
        for image, expected in (('zero.png', 0), ('completed.png', 6000)):
            for missing_header in (False, True):
                with self.subTest(image=image, missing_header=missing_header):
                    self.set_image('tests/images/garden_page/' + image)
                    original_ocr = self.task.ocr

                    def ocr(*args, **kwargs):
                        boxes = original_ocr(*args, **kwargs)
                        if args[:4] == (.02, .03, .45, .17):
                            return [] if missing_header else [box for box in boxes if '周度游历' not in box.name]
                        return boxes

                    with patch.object(self.task, 'ocr', side_effect=ocr):
                        self.assertEqual(expected, self.task.read_weekly_garden_points())

    def test_named_garden_entry_belongs_to_left_card(self):
        self.set_image('tests/images/garden_page/zero.png')
        boxes = self.task.ocr(.11, .18, .39, .79, frame=self.task.frame)
        matches = [b for b in boxes if '幻梦游园' in b.name and '狂想' in b.name]
        self.assertEqual(1, len(matches))
        self.assertLess(matches[0].center()[0], self.task.width * .39)


if __name__ == '__main__':
    unittest.main()
