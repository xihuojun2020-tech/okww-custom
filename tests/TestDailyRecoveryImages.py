import unittest
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.BaseWWTask import BaseWWTask


class TestDailyRecoveryImages(TaskTestCase):
    task_class = BaseWWTask
    config = config

    def test_nest_map_has_travel_not_team_action(self):
        self.set_image('tests/images/daily_recovery/nest_map.png')
        self.assertIsNone(self.task.find_one('team_start_challenge'))
        self.assertIsNotNone(self.task._travel_button(self.task.frame))
        self.assertIsNone(self.task._single_challenge_entry(self.task.frame))

    def test_tacet_disabled_reason_is_readable(self):
        self.set_image('tests/images/daily_recovery/tacet_unreachable.png')
        with self.assertRaisesRegex(RuntimeError, '无法|不可'):
            self.task._check_travel_unavailable(self.task.frame)

    def test_reward_overlay_keeps_positive_world_evidence(self):
        self.set_image('tests/images/daily_recovery/world_overlay.png')
        self.assertTrue(self.task.in_team_and_world())
        self.assertTrue(self.task.in_world())
        self.assertFalse(self.task.in_realm())

    def test_existing_weekly_formation_still_has_challenge_action(self):
        self.set_image('tests/images/weekly_boss/team.png')
        self.assertIsNotNone(self.task._team_start_button(self.task.frame))


if __name__ == '__main__':
    unittest.main()
