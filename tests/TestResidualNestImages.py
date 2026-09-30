import re
import unittest

from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.nightmare_nests import NEST_NAMES
from src.task.NightmareNestTask import NightmareNestTask


class TestResidualNestImages(TaskTestCase):
    task_class = NightmareNestTask
    config = config

    def test_new_first_page_titles_counts_and_buttons(self):
        self.set_image('tests/images/residual_nests/five_locations_top.png')
        self.task.count_re = re.compile(r'(\d{1,2})/(\d{1,2})')
        rows = self.task._residual_rows(self.task.frame, set(NEST_NAMES[:4]), top=True)
        self.assertEqual(set(NEST_NAMES[:4]), set(rows))
        self.assertEqual([48, 41, 48, 48], [rows[name][1] for name in NEST_NAMES[:4]])
        self.assertTrue(all(current == 0 and button is not None
                            for current, total, button in rows.values()))


if __name__ == '__main__':
    unittest.main()
