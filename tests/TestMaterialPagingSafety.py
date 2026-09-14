import unittest
from unittest.mock import Mock
import numpy as np
from src.task.MaterialPlannerTask import MaterialPlannerTask

class TestMaterialPagingSafety(unittest.TestCase):
    def task(self):
        task=MaterialPlannerTask.__new__(MaterialPlannerTask)
        task.next_frame=Mock();task.require_game_frame=Mock(return_value=np.zeros((1080,1920,3),dtype=np.uint8))
        task.scroll_relative=Mock();task.sleep=Mock();task.catalog=None;task._save_frame=Mock()
        return task
    def page(self,scene='target',identity='A'):
        return dict(scene=scene,target_identity=identity,cells=[dict(item_id='m',amount=1)],errors=[])
    def test_unknown_initial_page_does_not_scroll(self):
        task=self.task()
        with self.assertRaises(RuntimeError):
            task._pages(lambda *a:dict(scene='unknown',cells=[]),'scan',(0,0,100,100),(.5,.5))
        task.scroll_relative.assert_not_called()
    def test_changed_target_stops_after_first_scroll(self):
        task=self.task();parser=Mock(side_effect=[self.page(),self.page(identity='B')])
        with self.assertRaisesRegex(RuntimeError,'培养目标变化'):
            task._pages(parser,'scan',(0,0,100,100),(.5,.5))
        task.scroll_relative.assert_called_once()
    def test_same_pixels_changed_material_is_not_boundary(self):
        first=self.page();second=self.page();second['cells'][0]['amount']=2
        self.assertNotEqual(MaterialPlannerTask._page_signature(first),MaterialPlannerTask._page_signature(second))

if __name__=='__main__':unittest.main()
