import copy
import tempfile
import unittest

from src.account_slots import account_slot, migrate_slots, ordered_members, SLOT_KEY
from src.account_repository import AccountRepositoryError, ProfileEditScope
from src.sequence_repository import SequenceRepository
from tests.fixture_support import make_account_environment, synthetic_identity


class TestAccountSlots(unittest.TestCase):
    def test_dropdown_orders_all_fixed_positions_without_changing_raw_keys(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from src.account_display import account_option_items, account_option_labels
        slots = [f'{prefix}{i}' for prefix in ('A', 'B') for i in range(1, 11)]
        records = [SimpleNamespace(profile_id=f'id-{slot}', account={
            'display_name': f'old-{slot}', 'nickname': '测试', 'phone': '19910000001',
            'extensions': {SLOT_KEY: {'sequence': '序列1' if slot[0] == 'A' else '序列2', 'slot': slot}}})
            for slot in slots]
        records.append(SimpleNamespace(profile_id='unassigned', account={
            'display_name': 'A1', 'extensions': {SLOT_KEY: None}}))
        repository = SimpleNamespace(list_profiles=Mock(return_value=list(reversed(records))))
        raw = ['unassigned'] + [r.profile_id for r in reversed(records[:-1])] + ['（自动识别）']
        with patch('src.account_repository.get_default_repository', return_value=repository):
            items = account_option_items(raw)
            repository.list_profiles.assert_called_once_with()
            self.assertEqual([value for value, _ in items], ['（自动识别）'] + [f'id-{s}' for s in slots] + ['unassigned'])
            self.assertEqual([label.split('-')[0] for _, label in items[1:-1]], slots)
            self.assertTrue(items[-1][1].startswith('未分配-'))
            self.assertEqual(account_option_labels(raw), [dict(items)[value] for value in raw])

    def test_b10_at_ninth_position_and_b17_b18_follow_sequence_not_names(self):
        from src.account_display import account_display_label
        from src.account_identity import match_profile_identity
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root, names=tuple(f'A{i}' for i in range(11,22)))
            raw = copy.deepcopy(env.master)
            raw['extensions'] = {'fixed_account_slots_v1': True}
            ids = list(raw['profiles'])
            raw['sequences'] = {'序列1': ids[:9], '序列2': ids[9:]}
            for n, identity in enumerate(ids):
                raw['profiles'][identity]['display_name'] = f'B{30+n}'
            for identity, label in zip(ids[8:], ('B10','B17','B18')):
                raw['profiles'][identity]['display_name'] = label
            candidate, _ = migrate_slots(raw)
            for identity, expected in zip(ids[8:], ('A9','B1','B2')):
                self.assertEqual(account_slot(candidate['profiles'][identity])['slot'], expected)
                self.assertTrue(account_display_label(candidate['profiles'][identity]).startswith(expected + '-'))
            for identity, old in raw['profiles'].items():
                new = candidate['profiles'][identity]
                self.assertEqual({k:v for k,v in new.items() if k != 'extensions'},
                                 {k:v for k,v in old.items() if k != 'extensions'})
            env.integrity.set_progress('forgery:test:' + ids[8], {'units': 50})
            env.repository._publish_master(candidate)
            self.assertEqual(SequenceRepository(env.repository).resolve_short_names(('A9','B1','B2')), ids[8:])
            self.assertEqual(env.integrity.get_progress('forgery:test:' + ids[8]), {'units': 50})
            self.assertEqual(match_profile_identity(raw['profiles'][ids[8]]['masked_phone'], candidate['profiles']), ids[8])
            self.assertEqual(match_profile_identity(raw['profiles'][ids[8]]['game_feature_code'],
                                                  candidate['profiles'], strict_feature_code=True), ids[8])
            self.assertEqual(match_profile_identity(raw['profiles'][ids[8]]['alternate_login_name'], candidate['profiles']), ids[8])
            from src.task.MultiAccountDailyTask import MultiAccountDailyTask
            from types import SimpleNamespace
            from unittest.mock import Mock, patch
            task = SimpleNamespace(integrity_service=env.integrity, run_coordinator=Mock())
            with patch('src.task.MultiAccountDailyTask.get_default_repository', return_value=env.repository):
                snapshot = MultiAccountDailyTask.create_run_snapshot(
                    task, ('A9','B1','B2'), sequence_id='账号切换测试', short_names=True)
            self.assertEqual(snapshot.profile_ids, tuple(ids[8:]))
            self.assertTrue(account_display_label(snapshot.profiles[0]['account']).startswith('A9-'))
            self.assertFalse(migrate_slots(candidate)[1])

    def test_new_account_can_take_a_position_vacated_by_legacy_name(self):
        from src.account_config_editor import AccountConfigEditor
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            identity = synthetic_identity('A3')['profile_id']
            old = env.repository.load_profile(identity)
            account = copy.deepcopy(old.account)
            account['extensions'][SLOT_KEY] = {'sequence': '序列2', 'slot': 'B1'}
            env.repository.publish_profile(ProfileEditScope(identity, old.revision), {'account': account, 'tasks': old.tasks})
            editor = AccountConfigEditor(env.repository)
            created = editor.create_profile(editor.load_template(identity), display_name='A3',
                phone='19910000999', nickname='新测试账号', sequence_ids=('序列1',))
            self.assertEqual(account_slot(created.account)['slot'], 'A3')
            self.assertNotEqual(created.account['display_name'], 'A3')
            self.assertEqual(env.repository.load_profile(identity).account['display_name'], 'A3')
            self.assertEqual(SequenceRepository(env.repository).resolve_short_names(('A3','B1')),
                             [created.profile_id, identity])

    def test_conflicting_or_overflow_positions_preserve_all_members(self):
        raw = {'profiles': {str(i): {'display_name': f'B{i}'} for i in range(11)},
               'sequences': {'序列1': [str(i) for i in range(11)], '序列2': ['0']}}
        migrated, _ = migrate_slots(raw)
        self.assertEqual(migrated['sequences'], raw['sequences'])
        self.assertIsNone(account_slot(migrated['profiles']['0']))
        self.assertIsNone(account_slot(migrated['profiles']['10']))
        self.assertEqual(len(migrated['extensions']['fixed_account_slots_migration_issues']), 2)
        with self.assertRaises(ValueError):
            ordered_members(migrated['profiles'], migrated['sequences']['序列1'], '序列1')

    def test_chinese_sequence_alias_uses_actual_order_and_preserves_enabled_setting(self):
        raw = {'profiles': {'one': {'display_name': 'B17'}, 'two': {'display_name': 'B10'}},
               'sequences': {'序列一': ['one', 'two'], '序列1': []},
               'extensions': {'pc_sequence_settings': {'序列一': {'enabled': False}}}}
        migrated, _ = migrate_slots(raw)
        self.assertEqual(migrated['sequences']['序列1'], ['one', 'two'])
        self.assertEqual(migrated['extensions']['pc_sequence_settings']['序列1'], {'enabled': False})
        self.assertEqual(account_slot(migrated['profiles']['two'])['slot'], 'A2')

    def test_migration_preserves_actual_order_and_account_records(self):
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root, names=('A1', 'A3', 'A4', 'A10'))
            ids = {n: synthetic_identity(n)['profile_id'] for n in ('A1','A3','A4','A10')}
            raw = copy.deepcopy(env.master)
            raw['extensions'].pop('fixed_account_slots_v2')
            raw['sequences']['序列1'] = [ids['A10'], ids['A4'], ids['A3']]
            candidate, changed = migrate_slots(raw)
            self.assertTrue(changed)
            self.assertEqual(candidate['sequences']['序列1'], raw['sequences']['序列1'])
            self.assertEqual([account_slot(candidate['profiles'][i])['slot'] for i in raw['sequences']['序列1']],
                             ['A1','A2','A3'])
            self.assertIsNone(account_slot(candidate['profiles'][ids['A1']]))
            self.assertNotIn(ids['A1'], candidate['sequences']['序列1'])
            self.assertEqual(candidate['sequences']['S1'], raw['sequences']['S1'])
            for identity, old in raw['profiles'].items():
                self.assertEqual(candidate['profiles'][identity]['task_config'], old['task_config'])
            self.assertFalse(migrate_slots(candidate)[1])
            env.repository._publish_master(candidate)
            snapshot = SequenceRepository(env.repository).create_run_snapshot('序列1')
            self.assertEqual(snapshot.profile_ids, (ids['A10'],ids['A4'],ids['A3']))
            draft = env.repository.load_profile(ids['A4'])
            account = copy.deepcopy(draft.account)
            account['extensions'][SLOT_KEY] = {'sequence':'序列1','slot':'A4'}
            env.repository.publish_profile(ProfileEditScope(draft.profile_id,draft.revision),
                {'account':account,'tasks':draft.tasks})
            self.assertEqual(snapshot.profile_ids, (ids['A10'],ids['A4'],ids['A3']))
            self.assertEqual(SequenceRepository(env.repository).create_run_snapshot('序列1').profile_ids,
                             (ids['A10'],ids['A3'],ids['A4']))

    def test_occupied_slot_rejects_atomic_publish_and_keeps_runtime(self):
        from src.account_repository import ProfileEditScope
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            profile = env.repository.load_profile(synthetic_identity('A4')['profile_id'])
            env.integrity.set_progress('test-retained', {'count':7})
            account = copy.deepcopy(profile.account)
            account['extensions'][SLOT_KEY] = {'sequence':'序列1','slot':'A3'}
            with self.assertRaises(AccountRepositoryError):
                env.repository.publish_profile(ProfileEditScope(profile.profile_id,profile.revision),
                                               {'account':account,'tasks':profile.tasks})
            self.assertEqual(account_slot(env.repository.load_profile(profile.profile_id).account)['slot'],'A4')
            self.assertEqual(env.integrity.get_progress('test-retained'),{'count':7})

    def test_duplicate_legacy_names_are_numbered_from_actual_positions(self):
        accounts = {'one':{'display_name':'A4'}, 'two':{'display_name':'A4'}}
        raw = {'profiles':accounts, 'sequences':{'序列1':['one','two']}, 'extensions':{}}
        migrated, _ = migrate_slots(raw)
        self.assertEqual(migrated['sequences']['序列1'], ['one','two'])
        self.assertEqual(account_slot(migrated['profiles']['one'])['slot'], 'A1')
        self.assertEqual(account_slot(migrated['profiles']['two'])['slot'], 'A2')
        self.assertEqual(ordered_members(migrated['profiles'],['two','one'],'序列1'), ['one','two'])
        self.assertEqual(ordered_members(accounts,['two','one'],'自定义'),['two','one'])

    def test_cross_sequence_move_unassign_and_bundle_restore_keep_journals(self):
        from src.account_config_bundle import AccountConfigBundleService
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            identity = synthetic_identity('A4')['profile_id']
            sequence = env.repository.load_sequence('序列1')
            env.repository.publish_sequence('序列1', [identity], expected_revision=sequence.revision)
            env.integrity.set_progress('forgery:test:' + identity, {'units': 50})
            profile = env.repository.load_profile(identity)
            account = copy.deepcopy(profile.account)
            account['extensions'][SLOT_KEY] = {'sequence': '序列2', 'slot': 'B10'}
            env.repository.publish_profile(ProfileEditScope(identity, profile.revision), {'account': account, 'tasks': profile.tasks})
            self.assertEqual(env.repository.load_sequence('序列1').profile_ids, ())
            self.assertEqual(env.repository.load_sequence('序列2').profile_ids, (identity,))
            bundle_service = AccountConfigBundleService(root, integrity_service=env.integrity)
            bundle = bundle_service.export_bundle()
            profile = env.repository.load_profile(identity)
            account = copy.deepcopy(profile.account)
            account['extensions'][SLOT_KEY] = None
            env.repository.publish_profile(ProfileEditScope(identity, profile.revision), {'account': account, 'tasks': profile.tasks})
            self.assertEqual(env.repository.load_sequence('序列2').profile_ids, ())
            bundle_service.import_bundle(bundle, confirm=True, trust_external=True, preserve_runtime_and_preferences=True)
            self.assertEqual(account_slot(env.repository.load_profile(identity).account)['slot'], 'B10')
            self.assertEqual(env.integrity.get_progress('forgery:test:' + identity), {'units': 50})

    def test_fixed_sequence_guards_and_b_numeric_order(self):
        accounts = {slot: {'display_name': slot} for slot in ('B1', 'B9', 'B10')}
        self.assertEqual(ordered_members(accounts, ['B10', 'B1', 'B9'], '序列2'), ['B1', 'B9', 'B10'])
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            sequence = env.repository.load_sequence('序列1')
            with self.assertRaises(AccountRepositoryError):
                env.repository.delete_sequence('序列1', expected_revision=sequence.revision)
            with self.assertRaises(AccountRepositoryError):
                env.repository.rename_sequence('序列1', '其他', expected_revision=sequence.revision)

    def test_actual_daily_start_does_not_rotate_fixed_order_from_current_account(self):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        with tempfile.TemporaryDirectory() as root:
            env = make_account_environment(root)
            env.repository.migrate_fixed_account_slots()
            ids = [synthetic_identity(n)['profile_id'] for n in ('A3', 'A4')]
            sequence = env.repository.load_sequence('序列1')
            env.repository.publish_sequence('序列1', ids, expected_revision=sequence.revision)
            snapshot = SequenceRepository(env.repository).create_run_snapshot('序列1')
            task = MultiAccountDailyTask.__new__(MultiAccountDailyTask)
            task._active_run_snapshot = snapshot
            task.config = {}
            task._run_profile_order = snapshot.profile_ids
            task._profile_id_for = lambda name: synthetic_identity(name)['profile_id']
            task._set_run_start('A4')
            self.assertEqual(task._run_profile_order, tuple(ids))
            self.assertEqual(task._run_return_profile_id, ids[1])

    def test_confirmed_world_start_at_a4_runs_in_place_in_fixed_sequence(self):
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_ACCOUNT
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        task = SimpleNamespace(
            config={CURRENT_ACCOUNT: 'A4'}, done_set=set(),
            _active_run_snapshot=SimpleNamespace(sequence_id='序列1'),
            _run_profile_order=('id3', 'id4'), _profile_id_for=lambda name: 'id' + name[1:],
            get_sequence_accounts=lambda: ['A3', 'A4'], _load_today_progress=lambda: [],
            _task_label=lambda: '每日任务',
            _classify_start_state=lambda: 'world', _next_target_account=lambda: 'A3',
            _same_account=lambda a, b: a == b, _is_done=lambda _: False,
            _account_start_allowed=lambda _: True,
            _require_daily_profile=Mock(),
            _switch_to_login=Mock(), _detect_current_account_from_login=Mock(return_value='A4'),
            _select_and_login_specific=Mock(), _select_and_login_account=Mock(return_value='A3'),
            _execute_account_task=Mock(return_value=(True, None)), info_set=Mock(), log_info=Mock())
        with patch.object(MultiAccountDailyTask, '_advance_after_account', return_value=True):
            MultiAccountDailyTask._run_inner(task)
        task._switch_to_login.assert_not_called()
        task._require_daily_profile.assert_called_once_with('A4')
        task._detect_current_account_from_login.assert_not_called()
        task._select_and_login_specific.assert_not_called()
        task._execute_account_task.assert_called_once_with('A4')
        self.assertEqual(task._run_profile_order, ('id4', 'id3'))


if __name__ == '__main__':
    unittest.main()
