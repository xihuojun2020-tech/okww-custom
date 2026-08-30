import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from src.config_integrity import ConfigIntegrityBlocked, ConfigIntegrityService
from src.task.MultiAccountDailyTask import MultiAccountDailyTask


def _task_config():
    return {"Which to Farm": "Tacet Suppression", "备用识别名称": "无",
            "备用识别名称内容": ""}


class TestAccountRepositoryMigrationScenario(unittest.TestCase):
    """A production-shaped twelve-account legacy migration acceptance test."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "configs").mkdir()
        self.ids = {name: str(uuid.uuid5(uuid.NAMESPACE_URL, "migration:" + name))
                    for name in (f"A{i}" for i in range(1, 13))}
        profiles = {}
        for name, profile_id in self.ids.items():
            phone = f"1530000{int(name[1:]):04d}"
            profiles[name] = {"profile_id": profile_id, "display_name": name,
                              # Keep both legacy full-phone and the OCR form;
                              # migration must retain both identities.
                              "account_aliases": [name, phone, phone[:3] + "****" + phone[-4:]],
                              "task_config": _task_config(), "schedule": {},
                              "extensions": {"account": name}}
        # The task file is the real legacy source: sequence one has four,
        # sequence two has eight, and later explicitly empty sequences survive.
        working = {"profiles": profiles, "sequences": {}, "active_profile": "A1",
                   "extensions": {"stale-draft": "must-survive"}}
        task = {"序列 1 账号": ["A1", "A2", "A3", "A4"],
                "序列 2 账号": [f"A{i}" for i in range(5, 13)],
                "序列 3 账号": [], "序列 4 账号": [], "序列 5 账号": []}
        self.paths = ConfigIntegrityService(self.root).paths
        self.paths.working.write_text(json.dumps(working, ensure_ascii=False), encoding="utf-8")
        self.paths.multi_account_task.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
        self.service = ConfigIntegrityService(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_twelve_accounts_migrate_with_order_and_explicit_empty_sequences(self):
        result = self.service.bootstrap_master_from_working(confirm=True)
        self.assertTrue(result.ok)
        master = json.loads(self.paths.master.read_text(encoding="utf-8"))
        self.assertEqual(master["sequences"]["序列1"], [self.ids[f"A{i}"] for i in range(1, 5)])
        self.assertEqual(master["sequences"]["序列2"], [self.ids[f"A{i}"] for i in range(5, 13)])
        self.assertEqual([master["sequences"][f"序列{i}"] for i in range(3, 6)], [[], [], []])
        self.assertEqual(len(master["profiles"]), 12)

    def test_full_phone_alias_matches_masked_ocr_without_a1_a10_collision(self):
        self.service.bootstrap_master_from_working(confirm=True)
        working = json.loads(self.paths.working.read_text(encoding="utf-8"))
        task = object.__new__(MultiAccountDailyTask)
        task.get_profile_names = lambda: list(working["profiles"])
        task._load_profiles = lambda: working["profiles"]
        self.assertEqual(task.match_profile_from_login("199****0011"), "A4")
        self.assertEqual(task.match_profile_from_login("199****0012"), "A10")
        self.assertIsNone(task.match_profile_from_login("199****0013"))
        self.assertIsNone(task.match_profile_from_login("A1-extra"))

    def test_interrupted_migration_rolls_back_and_can_resume(self):
        before_working = self.paths.working.read_bytes()
        original_write = __import__("src.config_integrity", fromlist=["atomic_write_json"]).atomic_write_json
        calls = [0]

        def interrupt_once(path, payload):
            calls[0] += 1
            if calls[0] == 1:
                raise OSError("simulated interrupted migration")
            return original_write(path, payload)

        with patch("src.config_integrity.atomic_write_json", side_effect=interrupt_once):
            with self.assertRaises(OSError):
                self.service.bootstrap_master_from_working(confirm=True)
        self.assertFalse(self.paths.master.exists())
        self.assertEqual(self.paths.working.read_bytes(), before_working)
        self.assertTrue(self.service.bootstrap_master_from_working(confirm=True).ok)

    def test_stale_draft_does_not_cross_contaminate_accounts(self):
        self.service.bootstrap_master_from_working(confirm=True)
        accepted = self.service.check()
        self.service.accept_master_change(result=accepted)
        stale = json.loads(self.paths.working.read_text(encoding="utf-8"))
        stale["profiles"]["A1"]["Which to Farm"] = "stale draft"
        stale["profiles"]["A1"]["task_config"]["Which to Farm"] = "stale draft"
        self.paths.working.write_text(json.dumps(stale), encoding="utf-8")
        self.assertFalse(self.service.check().ok)
        restored = self.service.restore_working_from_master()
        self.assertTrue(restored.ok)
        current = json.loads(self.paths.working.read_text(encoding="utf-8"))
        self.assertEqual(current["profiles"]["A1"]["Which to Farm"], "Tacet Suppression")
        self.assertEqual(current["profiles"]["A10"]["Which to Farm"], "Tacet Suppression")
        self.assertEqual(current["profiles"]["A10"]["extensions"], {"account": "A10"})


if __name__ == "__main__":
    unittest.main()
