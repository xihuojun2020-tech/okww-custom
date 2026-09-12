import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import cv2
import numpy as np
from src.materials.repository import MaterialRepository
from src.materials.model import Settlement, Drop


class TestMaterialRepository(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = MaterialRepository(Path(self.temp.name)/'data')
        self.profile = str(uuid4())
        self.claim = self.repo.begin_claim(self.profile,'t','a')
        self.png = cv2.imencode('.png',np.zeros((10,10,3),np.uint8))[1].tobytes()
        self.sample = Settlement(self.claim,self.profile,'t','a',40,True,
                                 (Drop((0,0),'g','a','green',7),),1)

    def test_evidence_and_idempotency(self):
        with self.assertRaises(ValueError):
            self.repo.append_settlement(self.sample,'1')
        self.repo.save_frame(self.claim,0,self.png)
        self.assertEqual(self.repo.append_settlement(self.sample,'1'),1)
        self.assertEqual(self.repo.append_settlement(self.sample,'1'),1)
        self.assertEqual(len(self.repo.list_settlements(self.profile)),1)
        self.assertEqual(self.repo.pending_claims(self.profile),[])
        with self.assertRaises(ValueError):
            self.repo.save_frame('../escape',0,self.png)

    def test_revisions_preserve_original_and_identity(self):
        self.repo.save_frame(self.claim,0,self.png)
        self.repo.append_settlement(self.sample,'1')
        self.assertEqual(self.repo.append_settlement(replace(self.sample,stamina=80),'2'),2)
        with self.repo.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM parses').fetchone()[0],2)
        self.assertEqual(self.repo.list_settlements(self.profile)[0].stamina,80)
        with self.assertRaises(ValueError):
            self.repo.append_settlement(replace(self.sample,profile_id=str(uuid4())),'2')

    def test_partial_scan_and_account_isolation(self):
        self.repo.save_snapshot(self.profile,'inventory',{'a':8},complete=True)
        self.repo.save_snapshot(self.profile,'inventory',{'a':0},complete=False)
        self.assertEqual(self.repo.latest_complete_snapshot(self.profile,'inventory')['payload'],{'a':8})
        self.assertIsNone(self.repo.latest_complete_snapshot(str(uuid4()),'inventory'))

    def test_distinct_identical_claims_and_backup(self):
        self.repo.save_frame(self.claim,0,self.png)
        self.repo.append_settlement(self.sample,'1')
        another = self.repo.begin_claim(self.profile,'t','a')
        self.repo.save_frame(another,0,self.png)
        self.repo.append_settlement(replace(self.sample,claim_id=another),'1')
        self.assertEqual(len(self.repo.list_settlements(self.profile)),2)
        backup = self.repo.backup(Path(self.temp.name)/'backup')
        self.assertEqual(len(MaterialRepository(backup).list_settlements(self.profile)),2)
