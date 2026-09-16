from pathlib import Path
import cv2
from config import config
from ok.test.TaskTestCase import TaskTestCase
from src.task.ResonanceSimulationTask import ResonanceSimulationTask
from src.task.resonance_simulation import DEFAULT_RULES, rules_from_text, resized


class TestResonanceSimulationImages(TaskTestCase):
    task_class=ResonanceSimulationTask
    config=config

    def test_real_ocr_targets_and_phases(self):
        self.task._rules=rules_from_text(DEFAULT_RULES)
        self.task.config['Exact Text Match']=False
        cases={'marker':('前往',None),'combat':('战斗',None),
               'reward_far':('奖励',None),'factor':('下一关','共鸣因子'),
               'portal':('下一关','战斗区域'),'currency':('奖励','行动资金'),
               'treasure':('下一关','藏宝地')}
        for name,(expected,word) in cases.items():
            with self.subTest(name=name):
                path=Path('tests/fixtures/resonance_simulation')/(name+'.png')
                self.set_image(str(path));frame=cv2.imread(str(path))
                phase=self.task._phase(frame)
                self.assertEqual(phase,expected)
                targets=self.task._objects(frame,phase,None,True)
                print('RESONANCE',name,phase,targets)
                if word:
                    self.assertTrue(any(word in t.name for t in targets),targets)
                    for target in targets:
                        self.assertGreater(target.point[1],target.label[3])

    def test_reduced_frame_ocr_with_full_resolution_executor(self):
        import tempfile
        self.task._rules=rules_from_text(DEFAULT_RULES)
        source=cv2.imread('tests/fixtures/resonance_simulation/portal.png')
        with tempfile.TemporaryDirectory() as temp:
            for height in (1080,1440,2160):
                with self.subTest(height=height):
                    path=Path(temp)/'page.png'
                    frame=cv2.resize(source,(height*16//9,height))
                    cv2.imwrite(str(path),frame);self.set_image(str(path))
                    reduced=resized(frame)
                    self.assertEqual(self.task._phase(reduced),'下一关')
                    targets=self.task._objects(reduced,'下一关',None,True)
                    self.assertTrue(any(t.name=='战斗区域' for t in targets))
