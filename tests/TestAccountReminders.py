import unittest

from src.account_reminders import get_reminders, set_reminders


class TestAccountReminders(unittest.TestCase):
    def test_reminders_are_empty_by_default(self):
        self.assertEqual(get_reminders({}), [])

    def test_reminders_do_not_mutate_execution_config_or_other_extensions(self):
        account = {'profile_id': 'synthetic-account', 'task_config': {'enabled': False},
                   'extensions': {'unrelated': {'value': 1}}}
        result = set_reminders(account, ['weekly_boss', 'daily_activity', 'weekly_boss'])
        self.assertEqual(get_reminders(result), ['daily_activity', 'weekly_boss'])
        self.assertEqual(result['task_config'], account['task_config'])
        self.assertEqual(result['profile_id'], account['profile_id'])
        self.assertEqual(result['extensions']['unrelated'], account['extensions']['unrelated'])
        self.assertNotIn('completion_reminders', account['extensions'])
        self.assertEqual(get_reminders(set_reminders(result, [])), [])

    def test_invalid_ids_are_not_silently_converted_to_tasks(self):
        for values in (['unknown'], 'weekly_boss', [None], None, False, ''):
            with self.assertRaises(ValueError):
                set_reminders({}, values)
        for invalid in (None, [], False):
            with self.assertRaises(ValueError):
                set_reminders({'extensions': invalid}, [])


if __name__ == '__main__':
    unittest.main()
