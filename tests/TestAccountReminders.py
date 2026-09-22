import unittest

from src.account_reminders import (REMINDERS, get_reminder_note, get_reminders,
                                   set_reminder_note, set_reminders)


class TestAccountReminders(unittest.TestCase):
    def test_fixed_display_only_catalog_and_legacy_migration(self):
        self.assertEqual(REMINDERS, {
            'daily_activity': '活跃度', 'weekly_boss': '周本', 'weekly_garden': '每周乐园',
            'abyss': '深渊', 'activities': '活动', 'other': '其他',
        })
        account = {'extensions': {'completion_reminders': [
            'adversity_tower', 'sea_ruins', 'activity_1', 'piano_activity', 'battle_pass']}}
        self.assertEqual(get_reminders(account), ['abyss', 'activities', 'other'])
        self.assertEqual(get_reminders(set_reminders(account, get_reminders(account))),
                         ['abyss', 'activities', 'other'])

    def test_reminders_and_note_are_empty_by_default(self):
        self.assertEqual(get_reminders({}), [])
        self.assertEqual(get_reminder_note({}), '')

    def test_reminders_and_note_preserve_tasks_and_other_extensions(self):
        account = {'profile_id': 'synthetic-account', 'task_config': {'enabled': False},
                   'extensions': {'unrelated': {'value': 1}}}
        result = set_reminder_note(
            set_reminders(account, ['weekly_boss', 'daily_activity', 'weekly_boss']), '下周检查')
        self.assertEqual(get_reminders(result), ['daily_activity', 'weekly_boss'])
        self.assertEqual(get_reminder_note(result), '下周检查')
        self.assertEqual(result['task_config'], account['task_config'])
        self.assertEqual(result['extensions']['unrelated'], account['extensions']['unrelated'])
        self.assertNotIn('completion_reminders', account['extensions'])

    def test_invalid_ids_and_oversized_note_are_rejected(self):
        for values in (['unknown'], 'weekly_boss', [None], None, False, ''):
            with self.assertRaises(ValueError):
                set_reminders({}, values)
        with self.assertRaises(ValueError):
            set_reminder_note({}, 'x' * 2001)


if __name__ == '__main__':
    unittest.main()
