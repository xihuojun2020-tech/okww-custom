from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.SoloCombatTask import SoloCombatTask
from src.char.Qingxiao import Qingxiao


class TestQingxiaoSoloImages(TaskTestCase):
    task_class = SoloCombatTask
    config = config

    def test_skill_frame(self):
        self.set_image('tests/images/solo_qingxiao_combat_1440.png')
        char = Qingxiao(self.task, 0)
        char.is_current_char = True
        self.task.chars = [char]
        self.task.use_liberation = True
        self.assertTrue(char.resonance_available())
