import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from src.config_integrity import ConfigIntegrityService
from src.task.world_boss_material_plan import MATERIAL_TARGETS, material_plan, choose_material_target
from src.task.world_boss_material_progress import WorldBossMaterialProgress, preserve_material_progress
from src.task.world_boss_materials import WORLD_BOSS_TARGETS

A, B, C = [target.key for target in WORLD_BOSS_TARGETS[:3]]


class TestWorldBossMaterialPlan(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = ConfigIntegrityService(self.temp.name)
        self.progress = WorldBossMaterialProgress(self.service, 'profile-a')

    def rows(self):
        return [{'boss': boss, 'limit': limit} for boss, limit in zip((A, B, C), (3, 2, 1))]

    def test_default_disabled_priority_and_completion(self):
        self.assertIsNone(choose_material_target(material_plan({}), {}))
        self.assertEqual((A, 1), choose_material_target(self.rows(), {A: 2}))
        self.assertEqual((B, 2), choose_material_target(self.rows(), {A: 3}))
        self.assertIsNone(choose_material_target(self.rows(), {A: 3, B: 2, C: 1}))

    def test_invalid_plans_do_not_authorize_consumption(self):
        for rows in ([{'boss': A, 'limit': 1}], [{'boss': A, 'limit': 1}] * 3,
                     [{'boss': boss, 'limit': cap} for boss, cap in zip((A, B, C), (True, 2, 1))],
                     [{'boss': boss, 'limit': cap} for boss, cap in zip((A, B, C), (-1, 2, 1))]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                material_plan({MATERIAL_TARGETS: rows})

    def test_corrupt_ledger_is_blocked_instead_of_treated_as_zero(self):
        self.service.set_progress(self.progress.key, {'counts': {}, 'events': {'missing': {'boss': A, 'state': 'pending'}}})
        with self.assertRaises(ValueError):
            self.progress.read()

    def test_old_account_defaults_disabled_without_replacing_saved_targets(self):
        from pathlib import Path
        from tests.fixture_support import make_account_environment
        env = make_account_environment(Path(self.temp.name) / 'old-account')
        profile_id = env.repository.list_profiles()[0].profile_id
        saved = env.repository.load_profile(profile_id)
        self.assertEqual([], saved.tasks[MATERIAL_TARGETS])
        from src.account_config_editor import AccountConfigEditor
        editor = AccountConfigEditor(env.repository)
        draft = editor.load_draft(profile_id)
        draft.tasks[MATERIAL_TARGETS] = self.rows()
        editor.save_draft(draft.scope, draft, confirmed_account_label=draft.account['display_name'])
        self.assertEqual(self.rows(), env.repository.load_profile(profile_id).tasks[MATERIAL_TARGETS])

    def test_atomic_idempotence_restart_and_account_isolation(self):
        event = self.progress.begin(A, 60, 'rev')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.progress.resolve(event, True), range(4)))
        self.assertEqual({A: 1}, self.progress.counts())
        restarted = WorldBossMaterialProgress(ConfigIntegrityService(self.temp.name), 'profile-a')
        self.assertEqual({A: 1}, restarted.counts())
        self.assertEqual({}, WorldBossMaterialProgress(self.service, 'profile-b').counts())

    def test_unknown_claim_blocks_then_explicit_reconciliation(self):
        event = self.progress.begin(A, 60, 'rev')
        with self.assertRaises(RuntimeError):
            self.progress.begin(B, 60, 'new')
        with self.assertRaises(RuntimeError):
            self.progress.correct(A, 2)
        self.progress.resolve(event, False)
        self.assertEqual({}, self.progress.counts())
        self.progress.correct(A, 8)
        rows = self.rows()
        rows[0]['limit'] = 11
        self.assertEqual((A, 3), choose_material_target(rows, self.progress.counts()))

    def test_write_failure_keeps_pending(self):
        event = self.progress.begin(A, 60, 'rev')
        with patch('src.config_integrity.atomic_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.progress.resolve(event, True)
        self.assertIn(event, self.progress.pending())
        self.assertEqual({}, self.progress.counts())

    def test_restore_preserves_local_counts_pending_and_corrections(self):
        self.progress.correct(A, 8)
        event = self.progress.begin(B, 60, 'rev')
        current = {'progress': {self.progress.key: self.progress.read()}}
        incoming = {'progress': {self.progress.key: {'counts': {A: 1}, 'events': {}}}}
        value = preserve_material_progress(incoming, copy.deepcopy(current))['progress'][self.progress.key]
        self.assertEqual(8, value['counts'][A])
        self.assertIn(event, value['events'])
        self.assertEqual(1, len(value['corrections']))
