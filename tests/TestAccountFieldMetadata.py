import unittest

from src.account_field_metadata import account_field_metadata


class TestAccountFieldMetadata(unittest.TestCase):
    def test_common_fields_have_chinese_help_and_identity_is_read_only(self):
        fields = {field.key: field for field in account_field_metadata({
            "Which to Farm": "Tacet Suppression", "备用识别名称内容": "hidden",
            "Farm Nightmare Nest for Daily Echo": True,
        })}
        self.assertEqual(fields["Which to Farm"].label, "体力用途")
        self.assertTrue(fields["Which to Farm"].help_text)
        self.assertEqual(fields["Farm Nightmare Nest for Daily Echo"].editor_type, "bool")
        self.assertTrue(fields["备用识别名称内容"].read_only)


if __name__ == "__main__":
    unittest.main()
