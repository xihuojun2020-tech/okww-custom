import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID
import numpy as np

from ok import TaskDisabledException
from src.account_identity import match_profile_identity, AccountIdentityError
from src.task.account_feature_verification import (parse_feature_code, observe, resolve, Observation,
                                                   FeatureRun, region, expected_profile)
from src.evidence.repository import EvidenceRepository
from src.evidence.service import EvidenceService
from tests import TestCharacterTrial as trial_tests
from src.task.WWOneTimeTask import WWOneTimeTask


def record(number, code):
    return SimpleNamespace(profile_id=str(UUID(int=number, version=4)), revision='1',
                           account={'game_feature_code': code, 'display_name': f'A{number}'})


class TestAccountFeatureVerification(unittest.TestCase):
    def test_parser_preserves_zero_and_rejects_guessing(self):
        self.assertEqual(parse_feature_code('特征码：001234'), '001234')
        self.assertEqual(parse_feature_code('特徵碼:１２３４'), '1234')
        for text in ('001234', '昵称001234', '特征码:12O34', '特征码:12 34', '特征码:12345 UID:6789'):
            self.assertIsNone(parse_feature_code(text))

    def test_strict_match_never_falls_back_to_phone(self):
        profiles = {'A3': {'game_feature_code': '00123', 'phone': '19910000003'}}
        self.assertIsNone(match_profile_identity('19910000003', profiles, strict_feature_code=True))
        self.assertEqual(match_profile_identity('00123', profiles, strict_feature_code=True), 'A3')
        self.assertIsNone(match_profile_identity('123', profiles, strict_feature_code=True))
        profiles['A4'] = profiles['A3']
        with self.assertRaises(AccountIdentityError):
            match_profile_identity('00123', profiles, strict_feature_code=True)

    def observations(self, codes, *, duplicate=False, size=(1080, 1920)):
        now = [0.]
        count = [0]
        def capture():
            count[0] += 1
            frame = np.zeros((*size, 3), np.uint8)
            frame[0, 0, 0] = 1 if duplicate else count[0]
            return frame
        values = iter(codes)
        return observe(capture, lambda _: next(values, None), lambda: None,
                       lambda delay: now.__setitem__(0, now[0] + delay), timeout=.9, clock=lambda: now[0])

    def test_three_fresh_frames_at_both_resolutions(self):
        for size in ((1080,1920), (1440,2560)):
            found = self.observations(['00123']*3, size=size)
            self.assertEqual(found.status, 'verified')
            self.assertEqual(len(set(found.hashes)), 3)
            self.assertEqual(found.code, '00123')
            self.assertNotIn('00123', json.dumps(found.metadata()))
            self.assertEqual(found.crop, region(found.frame))

    def test_duplicate_cache_cannot_count_as_three(self):
        self.assertEqual(self.observations(['00123']*10, duplicate=True).status, 'unreadable')

    def test_conflict_or_missing_resets_stability(self):
        self.assertEqual(self.observations(['1','1',None,'1','2','1','1','1']).status, 'verified')
        self.assertEqual(self.observations(['1','2']*10).status, 'unreadable')

    def test_stop_propagates_without_retry(self):
        with self.assertRaises(TaskDisabledException):
            observe(Mock(), Mock(), Mock(side_effect=TaskDisabledException()), Mock())

    def test_raw_ocr_does_not_apply_text_fix_or_log_private_crop(self):
        from src.task.account_feature_verification import read_code
        frame=np.zeros((1080,1920,3),np.uint8)
        engine=Mock()
        engine.ocr.return_value=[[[[[0,0],[100,0],[100,20],[0,20]],('特征码:00123',.99)]]]
        task=SimpleNamespace(executor=SimpleNamespace(config={'ocr':{'default':{'lib':'onnxocr'}}},
                             ocr_lib=Mock(return_value=engine)))
        self.assertEqual(read_code(task,frame),'00123')
        engine.ocr.side_effect=RuntimeError('private crop content')
        with self.assertRaisesRegex(RuntimeError,'特征码 OCR 读取失败') as raised:
            read_code(task,frame)
        self.assertNotIn('private',str(raised.exception))

    def test_expected_account_is_selected_daily_uuid_or_multi_child(self):
        daily=Mock(); daily._profile_run_active=False
        daily.get_active_profile_name.return_value='A3'
        daily.load_daily_profiles.return_value={'A3':{'profile_id':'id-three'}}
        task=SimpleNamespace(executor=SimpleNamespace(current_task=None), get_task_by_class=Mock(return_value=daily))
        self.assertEqual(expected_profile(task),'id-three')
        daily.get_active_profile_name.return_value='默认'
        self.assertIsNone(expected_profile(task))
        parent=type('MultiAccountDailyTask',(),{})()
        parent._current_profile_id='id-four'
        task.executor.current_task=parent
        self.assertEqual(expected_profile(task),'id-four')
        parent._current_profile_id=None
        with self.assertRaises(RuntimeError): expected_profile(task)

    def test_duplicate_rebind_is_rejected_by_real_repository(self):
        from tests.fixture_support import make_account_environment
        from src.account_rebind_service import AccountRebindService
        with tempfile.TemporaryDirectory() as folder:
            env=make_account_environment(Path(folder))
            accounts=env.repository.list_profiles()
            service=AccountRebindService(env.repository, Mock())
            with self.assertRaises(AccountIdentityError):
                service.preview(accounts[0].profile_id, {'game_feature_code':accounts[1].account['game_feature_code']})

    def test_binding_capture_is_executor_owned_and_rejects_running_task(self):
        from src.evidence.service import request_capture, process_capture
        import threading
        frames=[]
        for number in range(3):
            frame=np.zeros((720,1280,3),np.uint8); frame[0,0,0]=number
            frames.append(frame)
        executor=SimpleNamespace(current_task=None, exit_event=threading.Event(),
            device_manager=SimpleNamespace(hwnd_window=SimpleNamespace(hwnd=12,exists=True)),
            method=SimpleNamespace(get_frame=Mock(side_effect=frames)),
            get_task_by_class=Mock(return_value=object()))
        future=request_capture(executor,feature_code=True)
        with patch('src.task.account_feature_verification.read_code',return_value='00123'):
            process_capture(executor)
        self.assertEqual(future.result()['code'],'00123')
        self.assertEqual(executor.method.get_frame.call_count,3)
        executor.current_task=SimpleNamespace(running=True)
        future=request_capture(executor,feature_code=True)
        process_capture(executor)
        with self.assertRaisesRegex(RuntimeError,'停止当前任务'): future.result()

    def test_resolution_statuses(self):
        a, b = record(3,'123'), record(4,'456')
        self.assertEqual(resolve(Observation('verified','123'),[a,b],a.profile_id)[0], 'verified')
        self.assertEqual(resolve(Observation('verified','123'),[a,b],b.profile_id)[0], 'mismatch')
        self.assertEqual(resolve(Observation('verified','999'),[a,b])[0], 'unbound')
        self.assertEqual(resolve(Observation('verified','123'),[a,record(5,'123')])[0], 'ambiguous')
        self.assertEqual(resolve(Observation('unreadable'),[a])[0], 'unreadable')

    def test_binding_and_window_change_invalidate_context(self):
        a = record(3,'123')
        window = SimpleNamespace(hwnd=12,exists=True)
        task = SimpleNamespace(executor=SimpleNamespace(current_task=None, check_enabled=Mock(),
                               device_manager=SimpleNamespace(hwnd_window=window)))
        repo = Mock(); repo.load_profile.return_value = a; repo.list_profiles.return_value = [a]
        run = FeatureRun(task,repo,a.profile_id)
        run.record, run.profile_id, run.binding = a, a.profile_id, '123'
        run.guard()
        a.account['game_feature_code'] = '456'
        with self.assertRaises(RuntimeError): run.guard()
        a.account['game_feature_code'] = '123'; window.hwnd = 13
        with self.assertRaises(RuntimeError): run.guard()

    def test_metadata_image_failure_is_recoverable_and_never_record_only_success(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=EvidenceRepository(directory)
            metadata=dict(profile_id=record(3,'1').profile_id,project_id='character_trial',
                          source='automatic',completion_status='completed',require_image=True,event_id='run-one')
            frame=np.zeros((100,200,3),np.uint8)
            service=EvidenceService(repo)
            try:
                with patch.object(repo,'_save_record',side_effect=OSError('index unavailable')):
                    with self.assertRaises(OSError): service.submit(metadata,frame).result(5)
                self.assertEqual(repo.list_records(metadata['profile_id']),[])
                recovered=repo.recover_required()
                self.assertEqual(len(recovered),1)
                self.assertEqual(recovered[0]['asset_status'],'available')
                self.assertEqual(len(repo.recover_required()),1)  # no diagnostic session yet: retry NAS handoff
                self.assertEqual(repo.save(metadata,frame)['evidence_id'],recovered[0]['evidence_id'])
            finally: service.close()

    def test_nas_is_queued_after_local_commit_without_network_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); repo=EvidenceRepository(root/'evidence')
            metadata=dict(profile_id=record(3,'1').profile_id,project_id='character_trial',
                          source='automatic',completion_status='completed',require_image=True,event_id='nas-run')
            frame=np.zeros((100,200,3),np.uint8)
            session=SimpleNamespace(closed_session=False,run=root/'diagnostics'/'session')
            batch=session.run/'batches'/'batch'
            with patch('src.runtime.diagnostic_lifecycle._session',session), \
                 patch('src.runtime.diagnostic_session.seal_run',return_value=batch) as seal:
                saved=repo.save(metadata,frame)
                repo.save(metadata,frame)
                seal.assert_called_once()
                self.assertEqual(saved['completion_status'],'completed')
                self.assertIn('待上传',repo._nas_status(saved))
                state=session.run.parent/'states'/'session--batch.json'
                state.parent.mkdir(parents=True)
                state.write_text(json.dumps({'status':'uploaded'}))
                self.assertEqual(repo._nas_status(saved),'NAS 已上传')

    def run_trial(self, end='verified', save_error=None, stop=False, final_state='complete'):
        task=trial_tests.TestTrialFlow().task()
        task._open=Mock(); task._scan=Mock(return_value=list(range(5)))
        task._process=Mock(return_value='already_complete'); task._select=Mock()
        task._state=Mock(return_value=final_state); task._release=Mock()
        task.require_game_frame=Mock(return_value=np.zeros((1080,1920,3),np.uint8))
        verify=Mock(); verify.begin.return_value=verify; verify.finish.return_value=end
        verify.save.return_value={'evidence_id':'saved'}
        if save_error: verify.save.side_effect=save_error
        if stop: task._process.side_effect=TaskDisabledException()
        with patch.object(WWOneTimeTask,'run'), patch('src.account_repository.get_default_repository',return_value=Mock()), \
             patch('src.task.account_feature_verification.expected_profile',return_value='expected'), \
             patch('src.task.account_feature_verification.FeatureRun',return_value=verify):
            if stop or final_state!='complete':
                with self.assertRaises(TaskDisabledException if stop else RuntimeError): task.run()
            else: task.run()
        return task,verify

    def test_trial_success_only_after_image_saved(self):
        task,verify=self.run_trial()
        self.assertTrue(task.last_result['complete'])
        self.assertEqual(task.last_result['configured_count'],5)
        self.assertEqual(len(task.last_result['positions']),5)
        self.assertEqual(verify.save.call_args.args[2],'completed')

    def test_end_mismatch_is_game_complete_but_unknown_evidence(self):
        task,verify=self.run_trial(end='mismatch')
        self.assertTrue(task.last_result['game_complete'])
        self.assertFalse(task.last_result['complete'])
        self.assertEqual(task.last_result['failed'],0)
        self.assertEqual(verify.save.call_args.args[2],'unknown')

    def test_save_failure_does_not_mark_complete(self):
        task,_=self.run_trial(save_error=OSError('disk'))
        self.assertTrue(task.last_result['evidence_pending'])
        self.assertFalse(task.last_result['complete'])

    def test_stop_and_final_reward_failure_never_complete(self):
        for kwargs in ({'stop':True},{'final_state':'pending'}):
            task,verify=self.run_trial(**kwargs)
            self.assertFalse(task.last_result['complete'])
            verify.finish.assert_not_called()


if __name__=='__main__': unittest.main()
