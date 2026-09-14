import cv2
from pathlib import Path
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.AutoAbyssTask import AutoAbyssTask, detect_character_slots, parse_ocr_number, exact_ocr_box, TOWER_NAMES

config['debug'] = True
class TestAbyssReturnImages(TaskTestCase):
    task_class = AutoAbyssTask
    config = config

    def test_real_pages_and_low_levels(self):
        folder = Path('tests/fixtures/abyss_return')
        for height in (720, 1080, 1440, 2160):
            for name in ('failed','overview','roster'):
                frame = cv2.resize(cv2.imread(str(folder/(name+'.png'))), (height*16//9,height))
                if name == 'failed':
                    boxes = self.task.ocr(.20,.06,.82,.96,frame=frame)
                    self.assertIsNotNone(exact_ocr_box(boxes,'返回深塔'))
                    self.assertIsNotNone(exact_ocr_box(boxes,'挑战失败'))
                elif name == 'overview':
                    boxes = self.task.ocr(.02,.03,.95,.20,frame=frame)
                    self.assertTrue(all(exact_ocr_box(boxes,n) is not None for n in TOWER_NAMES))
                else:
                    slots = detect_character_slots(frame)
                    for slot in slots:
                        if slot[0] == 1 and slot[1] == 6: continue
                        expected = (40,40,1,1,1,1,1)[slot[1]] if slot[0] == 0 else 1
                        number = self.task._read_slot_level(frame,slot)
                        self.assertEqual(number,expected,(height,slot[:2],number))
