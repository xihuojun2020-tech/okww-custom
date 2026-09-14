import unittest
from pathlib import Path
import cv2
import numpy as np
from src.materials.vision import scrollbar_edges
from src.task.MaterialPlannerTask import MaterialPlannerTask
from unittest.mock import Mock

class TestMaterialScrollEdges(unittest.TestCase):
    def image(self,name):return cv2.imread(str(Path(__file__).parent/'images/materials'/f'{name}.png'))
    def test_real_top_middle_bottom_at_supported_resolutions(self):
        cases=[('17_29_48','inventory',(True,False)),('17_29_58','inventory',(False,False)),
               ('17_30_02','inventory',(False,True)),('13_33_40','target',(True,False)),
               ('13_33_50','target',(False,True))]
        for name,scene,expected in cases:
            for width,height in ((1280,720),(1920,1080),(2560,1440)):
                with self.subTest(name=name,width=width):
                    self.assertEqual(scrollbar_edges(cv2.resize(self.image(name),(width,height)),scene),expected)
    def test_missing_and_wrong_geometry_do_not_prove_boundary(self):
        self.assertIsNone(scrollbar_edges(np.zeros((720,1280,3),np.uint8),'inventory'))
        self.assertIsNone(scrollbar_edges(np.zeros((720,1000,3),np.uint8),'target'))
        self.assertIsNone(scrollbar_edges(self.image('17_30_02'),'reward'))
    def test_lost_scroll_in_middle_does_not_become_top(self):
        task=MaterialPlannerTask.__new__(MaterialPlannerTask)
        task.next_frame=Mock();task.require_game_frame=Mock(return_value=self.image('17_29_58'))
        task.scroll_relative=Mock();task.sleep=Mock();task.catalog=None;task._save_frame=Mock()
        parser=lambda *args:dict(scene='inventory',cells=[dict(item_id='m',amount=1)])
        with self.assertRaisesRegex(RuntimeError,'未确认顶部'):
            task._pages(parser,'scan',(180,140,1290,968),(.5,.65))
        self.assertEqual(task.scroll_relative.call_count,2)

    def test_lost_scroll_in_middle_does_not_become_bottom(self):
        task=MaterialPlannerTask.__new__(MaterialPlannerTask)
        top=self.image('17_29_48');middle=self.image('17_29_58')
        task.next_frame=Mock();task.require_game_frame=Mock(side_effect=[top,top,top,middle,middle,middle])
        task.scroll_relative=Mock();task.sleep=Mock();task.catalog=None;task._save_frame=Mock()
        parser=lambda *args:dict(scene='inventory',cells=[dict(item_id='m',amount=1)])
        with self.assertRaisesRegex(RuntimeError,'未确认底部'):
            task._pages(parser,'scan',(180,140,1290,968),(.5,.65))
        self.assertEqual(task.scroll_relative.call_count,5)


if __name__=='__main__':unittest.main()
