import unittest

from src.account_field_metadata import (account_field_metadata, localize_account_value,
                                        restore_account_value)


class TestAccountFieldMetadata(unittest.TestCase):
    def test_weekday_storage_and_chinese_display(self):
        from src.account_field_metadata import normalize_weekday
        days = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        for english, chinese in zip(days, '一二三四五六日'):
            for value in (english, '星期' + chinese, '周' + chinese):
                self.assertEqual(normalize_weekday(value), english)
        self.assertEqual(normalize_weekday('星期天'), 'Sunday')
        self.assertEqual(normalize_weekday(None), '无')
        with self.assertRaises(ValueError):
            normalize_weekday('invalid')
        field = account_field_metadata({'Weekly Garden Check Day': 'Monday'})[0]
        self.assertEqual(field.options, ('无', *days))
        self.assertEqual(field.option_labels[1], '星期一')

    def test_common_fields_have_chinese_help_and_identity_is_read_only(self):
        fields = {field.key: field for field in account_field_metadata({
            "Which to Farm": "Tacet Suppression", "备用识别名称": "无",
            "备用识别名称内容": "hidden",
            "Farm Nightmare Nest for Daily Echo": True,
        })}
        self.assertEqual(fields["Which to Farm"].label, "体力用途")
        self.assertTrue(fields["Which to Farm"].help_text)
        self.assertEqual(fields["Farm Nightmare Nest for Daily Echo"].editor_type, "bool")
        self.assertFalse(fields["备用识别名称内容"].read_only)
        self.assertEqual(fields["备用识别名称"].options, ("无", "使用"))

    def test_english_storage_values_round_trip_through_chinese_display(self):
        stored = ["Nightmare Purification", "Tacet Discord Nest"]
        displayed = localize_account_value(stored)
        self.assertEqual(displayed, ["梦魇拔除", "残像聚落"])
        self.assertEqual(restore_account_value(displayed), stored)
        self.assertEqual(localize_account_value("Shell Credit"), "贝币")

    def test_dropdown_keeps_english_data_and_exposes_chinese_labels(self):
        fields = {field.key: field for field in account_field_metadata({
            "Which to Farm": "Tacet Suppression", "Material Selection": "Shell Credit",
        })}
        self.assertEqual(fields["Which to Farm"].option_labels,
                         ("无音区", "凝素领域", "模拟领域"))
        self.assertEqual(fields["Material Selection"].options,
                         ("Resonator EXP", "Weapon EXP", "Shell Credit"))
        self.assertEqual(fields["Material Selection"].option_labels,
                         ("共鸣者经验", "武器经验", "贝币"))


if __name__ == "__main__":
    unittest.main()
