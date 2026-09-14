"""Real OCR and page-negative checks on redacted user samples; no game input."""
import tempfile
from pathlib import Path
import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.EchoesRemainTask import EchoesRemainTask

config['debug'] = True


class TestEchoesRemainImages(TaskTestCase):
    task_class = EchoesRemainTask
    config = config

    def test_pages_and_disjoint_buttons_at_four_resolutions(self):
        with tempfile.TemporaryDirectory() as folder:
            for height in (720,1080,1440,2160):
                for name in ('event','stage1','stage2','formation','formation_failed','initial'):
                    with self.subTest(height=height,page=name):
                        image=cv2.imread(f'tests/fixtures/echoes_remain/{name}.png')
                        frame=cv2.resize(image,(height*16//9,height))
                        path=Path(folder)/'page.png';cv2.imwrite(str(path),frame);self.set_image(str(path))
                        if name=='event':
                            self.assertTrue(self.task._event_page(frame))
                            self.assertIsNotNone(self.task._button(frame,self.task.LIST,self.task.name))
                        elif name.startswith('stage'):
                            self.assertIsNotNone(self.task._stage_name(frame))
                            self.assertIsNotNone(self.task._button(frame,self.task.SINGLE,'单人挑战'))
                            self.assertIsNone(self.task._button(frame,self.task.SINGLE,'多人匹配'))
                        elif name.startswith('formation'):
                            self.assertIsNotNone(self.task._formation_page(frame))
                            self.assertFalse(self.task._roster_page(frame))
                            x, y = self.task._formation_page(frame).center()
                            self.assertTrue(.63 < x/frame.shape[1] < .76)
                            self.assertTrue(.89 < y/frame.shape[0] < .95)
                        else:
                            self.assertTrue(self.task._roster_page(frame), (height,
                                [b.name for b in self.task.ocr(.01,.02,.18,.11,frame=frame)],
                                [b.name for b in self.task.ocr(*self.task.DONE,frame=frame)]))
                            self.assertFalse(self.task._event_page(frame))
