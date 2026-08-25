import unittest

from src.account_directory_assessment import (
    assess_account_directory_migration, project_account_layout, round_trip_projection,
)


class TestAccountDirectoryAssessment(unittest.TestCase):
    def setUp(self):
        self.master = {
            "schema_version": 1,
            "profiles": {
                "id-1": {"display_name": "A1", "account_aliases": ["U1"], "task_config": {"x": 1}},
                "id-3": {"display_name": "A3", "account_aliases": ["U3"], "task_config": {"x": 3}},
            },
            "sequences": {"默认": ["id-1", "id-3"]},
            "extensions": {},
        }

    def test_projection_is_one_json_per_account_and_round_trips(self):
        layout = project_account_layout(self.master)
        self.assertEqual(set(layout["accounts"]), {"id-1.json", "id-3.json"})
        self.assertEqual(round_trip_projection(self.master), self.master)
        assessment = assess_account_directory_migration(self.master)
        self.assertEqual(assessment["decision"], "NO-GO")
        self.assertFalse(assessment["writes_performed"])

    def test_duplicate_identity_and_unknown_fields_are_reported(self):
        self.master["profiles"]["id-3"]["account_aliases"] = ["U1"]
        self.master["future"] = {"keep": True}
        assessment = assess_account_directory_migration(self.master)
        self.assertTrue(any("重复账号身份" in item for item in assessment["blockers"]))
        self.assertTrue(any("future" in item for item in assessment["warnings"]))


if __name__ == "__main__":
    unittest.main()
