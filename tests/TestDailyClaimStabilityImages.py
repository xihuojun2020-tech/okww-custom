from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask


class TestDailyClaimStabilityImages(TaskTestCase):
    task_class = DailyTask
    config = dict(config, debug=True)

    def test_nas_before_and_after_error_still_show_daily_page(self):
        for name in ('before_scroll', 'after_error'):
            with self.subTest(frame=name):
                self.set_image('tests/images/daily_claim_stability/'+name+'.png')
                self.assertTrue(self.task._daily_page_ready(self.task.frame))
                self.assertEqual(self.task._daily_objective_claim_buttons(), [])

    def test_world_is_never_accepted_as_daily_page(self):
        self.set_image('tests/images/daily_claim_stability/world.png')
        self.assertFalse(self.task._daily_page_ready(self.task.frame))
