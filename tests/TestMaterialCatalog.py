import unittest
import cv2
from src.materials.catalog import Catalog


class TestMaterialCatalog(unittest.TestCase):
    def test_all_forty_templates_have_unique_identity(self):
        catalog = Catalog()
        self.assertEqual(len(catalog.groups),10)
        for item in catalog.items.values():
            tile = cv2.imread(str(catalog.path.parent/item['template_paths'][0]))
            match,_ = catalog.match(tile)
            self.assertIsNotNone(match,item['item_id'])
            self.assertEqual(match['item_id'],item['item_id'])
