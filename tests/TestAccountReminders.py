import unittest

from src.account_reminders import (REMINDERS, get_reminder_note, get_reminders,
                                   set_reminder_note, set_reminders)


class TestAccountReminders(unittest.TestCase):
    def test_manual_three_states_reset_at_boundary_without_early_reset(self):
        from src.account_reminders import manual_reminder_state
        for state in ('completed', 'blocked'):
            row = dict(enabled=True, rule='custom', reset_at='2026-10-07T04:00:00+08:00',
                       status=state, marked_at='2026-10-06T12:00:00+08:00')
            self.assertEqual(state, manual_reminder_state(row, {}, '2026-10-07T03:59:59+08:00'))
            self.assertEqual('pending', manual_reminder_state(row, {}, '2026-10-07T04:00:00+08:00'))
            row['reset_at'] = '2026-10-08T04:00:00+08:00'
            self.assertEqual(state, manual_reminder_state(row, {}, '2026-10-07T04:00:00+08:00'))

    def test_tower_manual_mark_does_not_modify_floor_ledger(self):
        import tempfile
        from tests.fixture_support import make_account_environment
        from src.account_reminders import mark_manual_reminder, manual_reminder_state
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            identity = env.repository.list_profiles()[0].profile_id
            key = 'abyss_cycles:' + identity
            original = {'current': 'cycle', 'cycles': {'cycle': {'floors': {'left:4': {'status': 'completed'}}}}}
            env.integrity.set_progress(key, original)
            row = dict(enabled=True, rule='none')
            mark_manual_reminder(env.integrity, identity, 'adversity_tower', row, state='blocked')
            mark = env.integrity.get_progress('manual_task_marks:' + identity)['adversity_tower']
            self.assertEqual('blocked', manual_reminder_state(row, mark))
            self.assertEqual(original, env.integrity.get_progress(key))

    def test_task_policy_upgrade_is_idempotent_preserves_goal_and_disables_merge(self):
        from src.account_task_policy import migrate_task_policy
        from tests.TestForgeryQuotaPlan import goal
        row = goal()
        master = {'profiles': {'one': {'task_config': {'Merge Echo on Sunday': True,
                  'Forgery Material Goals': [row], 'Which to Farm': 'Forgery Challenge'}, 'extensions': {}}}}
        migrated, changed = migrate_task_policy(master)
        self.assertTrue(changed)
        tasks = migrated['profiles']['one']['task_config']
        self.assertEqual([row], tasks['Forgery Material Goals'])
        self.assertEqual('materials', tasks['Forgery Limit Mode'])
        self.assertFalse(tasks['Merge Echo on Sunday'])
        self.assertFalse(migrate_task_policy(migrated)[1])
        master['extensions'] = {'new_profile_template': {'Merge Echo on Sunday': True}}
        migrated, _ = migrate_task_policy(master)
        self.assertFalse(migrated['extensions']['new_profile_template']['Merge Echo on Sunday'])

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
