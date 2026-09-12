"""Real OCR of sanitized supplied UI; never sends game input."""
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.CharacterTrialTask import CharacterTrialTask
from src.task.character_trial import reward_state, start_prompt
import cv2
import tempfile
from pathlib import Path

config['debug']=True


class TestCharacterTrialImages(TaskTestCase):
    task_class=CharacterTrialTask
    config=config

    def load(self,name):
        self.set_image(f'tests/fixtures/character_trial/{name}.png')

    def test_three_reward_states(self):
        for name,state in [('pending','pending'),('claim','claim'),('complete','complete')]:
            self.load(name)
            self.assertEqual(reward_state(self.task._ocr(self.task.REWARD)),state)
            self.assertTrue(self.task._page())
            self.assertFalse(self.task._intro())
        self.load('complete')
        self.assertIsNotNone(self.task._button(self.task.ENTER,'前往试用'))

    def test_current_intro_at_both_resolutions(self):
        with tempfile.TemporaryDirectory() as folder:
            source=cv2.imread('tests/fixtures/character_trial/current_intro.png')
            for width,height in ((1920,1080),(2560,1440)):
                path=Path(folder)/f'{width}.png'
                cv2.imwrite(str(path),cv2.resize(source,(width,height)))
                self.set_image(str(path))
                self.assertIsNotNone(self.task._button(self.task.NEXT,'下一页'))
                self.assertTrue(self.task._intro())

    def test_wrong_activity_is_rejected_at_both_resolutions(self):
        with tempfile.TemporaryDirectory() as folder:
            source=cv2.imread('tests/fixtures/character_trial/wrong_activity.png')
            for width,height in ((1920,1080),(2560,1440)):
                path=Path(folder)/f'{width}.png'
                cv2.imwrite(str(path),cv2.resize(source,(width,height)))
                self.set_image(str(path))
                self.assertFalse(self.task._page())
                self.assertFalse(self.task._intro())
                self.assertIsNotNone(self.task._activity_title(self.task._ocr(self.task.LIST)))

    def test_current_page_at_both_resolutions(self):
        with tempfile.TemporaryDirectory() as folder:
            source=cv2.imread('tests/fixtures/character_trial/current_page.png')
            for width,height in ((1920,1080),(2560,1440)):
                path=Path(folder)/f'{width}.png'
                cv2.imwrite(str(path),cv2.resize(source,(width,height)))
                self.set_image(str(path))
                title=[b.name for b in self.task._ocr(self.task.TITLE)]
                enter=[b.name for b in self.task._ocr(self.task.ENTER)]
                print('CURRENT PAGE OCR',width,title,enter)
                self.assertTrue(self.task._page(),(width,title,enter))

    def test_start_key_is_distinct_from_left_objective(self):
        self.load('start')
        self.assertTrue(start_prompt(self.task._ocr(self.task.INTERACT),self.task.height))
        self.assertFalse(start_prompt(self.task._ocr(self.task.HINT),self.task.height))

    def test_name_and_state_at_1080p(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('pending','claim','complete'):
                self.load(name)
                expected = [b.name for b in self.task._ocr(self.task.NAME)]
                self.assertEqual(len(expected),1)
                source = cv2.imread(f'tests/fixtures/character_trial/{name}.png')
                path = Path(folder)/f'{name}.png'
                cv2.imwrite(str(path),cv2.resize(source,(1920,1080)))
                self.set_image(str(path))
                self.assertEqual([b.name for b in self.task._ocr(self.task.NAME)],expected)
                self.assertTrue(self.task._page())
                self.assertIsNotNone(reward_state(self.task._ocr(self.task.REWARD)))

    def test_intro_obtain_finish_and_exit(self):
        for name,region,text in [('intro','INTRO','战斗特色'),('intro','NEXT','下一页'),
                                 ('obtained','OBTAIN','获得'),('obtained','DISMISS','点击空白处继续'),
                                 ('finished','HINT','离开模拟领域'),('exit','EXIT_MESSAGE','确认离开'),
                                 ('exit','EXIT_CONFIRM','确认')]:
            self.load(name)
            self.assertIsNotNone(self.task._button(getattr(self.task,region),text),(name,text))
        self.assertIsNone(self.task._button(self.task.EXIT_MESSAGE,'确认'))
