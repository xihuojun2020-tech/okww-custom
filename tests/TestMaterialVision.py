"""Real, sanitized screenshots run through the production OCR engine; no game input."""
import unittest
from pathlib import Path
import cv2
from src.materials.catalog import Catalog
from src.materials.model import Counts, summarize_target, count_reward_units, equivalent
from src.materials.vision import (parse_reward_frame, stitch_reward_pages, parse_target_frame,
                                  target_totals, parse_inventory_frame, forgery_rows)


class TestMaterialVision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        cls.engine = ONNXPaddleOcr(use_angle_cls=False,use_npu=False,use_openvino=True)
        cls.catalog = Catalog()

    def ocr(self, crop):
        return ' '.join(row[1][0] for page in self.engine.ocr(crop) if page for row in page)

    def parse(self, name, parser):
        return parser(cv2.imread(str(Path(__file__).parent/'images/materials'/f'{name}.png')),self.ocr,self.catalog)

    def test_reward_stitch_and_units(self):
        pages = [self.parse(n,parse_reward_frame) for n in ('17_40_00','17_40_05')]
        self.assertFalse(stitch_reward_pages(pages)['complete'])
        pages[0]['at_top'] = True
        pages[-1]['at_bottom'] = True
        result = stitch_reward_pages(pages)
        self.assertTrue(result['complete'],result['errors'])
        self.assertEqual(len(result['drops']),22)
        self.assertEqual(summarize_target(result['drops'],'rectifier_b'),Counts(13,16,3,0))
        self.assertEqual(count_reward_units(result['drops'],'rectifier_b'),2)
        self.assertEqual(equivalent(summarize_target(result['drops'],'rectifier_b')),88)
        self.assertNotEqual(result['drops'][0].item_id,'shell_credit')  # 300 is experience.

    def test_missing_page_cannot_be_complete(self):
        page = self.parse('17_40_00',parse_reward_frame)
        page['at_top'] = True
        self.assertFalse(stitch_reward_pages([page])['complete'])

    def test_target_excludes_monsters_and_universal_credit(self):
        pages = [self.parse(n,parse_target_frame) for n in ('13_33_40','13_33_47')]
        groups, errors = target_totals(pages)
        self.assertEqual(errors,[])
        self.assertEqual(set(groups),{'pistol_a','pistol_b'})
        self.assertEqual(groups['pistol_b'],dict(stock=Counts(41,1,18,0),need=Counts(25,28,55,67)))
        self.assertEqual(groups['pistol_a'],dict(stock=Counts(20,26,0,0),need=Counts(6,8,6,20)))
        self.assertTrue(pages[1]['has_echo_boundary'])
        self.assertEqual(pages[0]['weekly'][0]['cells'][0]['need'],26)

    def test_inventory_does_not_use_stale_right_detail(self):
        page = self.parse('17_29_58',parse_inventory_frame)
        self.assertEqual(page['errors'],[])
        known = {c['item_id']:c['amount'] for c in page['cells'] if c['group_id'] in self.catalog.groups}
        self.assertEqual(known['pistol_a_blue'],26)
        self.assertEqual(known['rectifier_a_blue'],279)
        self.assertEqual(known['broadblade_a_blue'],10)
        self.assertNotIn(8,known.values())

    def test_all_ten_groups_selected_by_weapon_and_preview(self):
        groups=set()
        for stamp in ('17_02_22','17_02_46','17_03_02','17_03_16'):
            groups.update(row['group_id'] for row in self.parse(stamp,forgery_rows))
        self.assertEqual(groups,set(self.catalog.groups))


if __name__ == '__main__': unittest.main()
