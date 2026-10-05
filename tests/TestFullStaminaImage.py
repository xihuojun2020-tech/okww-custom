from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.DailyTask import DailyTask
from types import SimpleNamespace


class TestFullStaminaImage(TaskTestCase):
    task_class = DailyTask
    config = config

    def test_full_current_value_without_fraction(self):
        self.set_image('tests/images/stamina_full_240.png')
        self.assertEqual((240, 480, 720), self.task.get_stamina(screenshot_on_failure=False))

    def test_victory_animation_is_not_reward_proof(self):
        self.set_image('tests/images/challenge_success_animation.png')
        self.assertTrue(self.task.has_challenge_success())
        self.assertFalse(self.task.has_claim_stamina())

    def test_actual_revival_cooldown_banner_blocks_failed_switch_temporarily(self):
        self.set_image('tests/images/revive_cooldown.png')
        char = SimpleNamespace(index=1, has_intro=True, has_sub_dps_intro=True)
        self.assertTrue(self.task._switch_rejected_by_death(char))
        self.assertGreater(char._switch_cooldown_until, 0)
        self.assertFalse(char.__dict__.get('_switch_unrevivable', False))
