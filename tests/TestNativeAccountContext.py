"""Production context selection without a device, GUI or model."""
import json
from pathlib import Path
import unittest


class TestNativeAccountContext(unittest.TestCase):
    def probe(self, body, *, fresh=False):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        setup = '''
            import json
            from types import SimpleNamespace
            from tests.TestNativeWWOneTime import BlockApplicationImports
            blocker=BlockApplicationImports();sys.meta_path.insert(0,blocker)
            from tests.fixture_support import make_account_environment
            data=root/'data'
        '''
        setup += "\n            environment=make_account_environment(data)\n"
        setup += '''
            data.mkdir(parents=True,exist_ok=True)
            (data/'configs').mkdir(exist_ok=True)
            (data/'configs/Language.json').write_text('{"Language":"en_US"}',encoding='utf-8')
            from src.runtime.native_configuration import create_configuration_host
            from src.runtime.native_account_context import NativeAccountContext
            manifest=Path(sys.argv[1])/'gamepacks/wuthering_waves_native/manifest.json'
            host=create_configuration_host(data,'context-test',manifest,lambda event:None)
            from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE,CURRENT_ACCOUNT,UNREGISTERED_ACCOUNT
            reader=SimpleNamespace(reload=lambda:None,owners=lambda:[])
            context=NativeAccountContext(host,live_reader=reader)
            owner=context._owner()
        '''
        if not fresh:
            setup += "\n            context.set(sequence='S1')\n"
        else:
            setup += '''
            # Model the context service's uninitialized-store boundary only;
            # full fresh production host startup has its own integrity gate.
            owner.integrity_service.paths.master.unlink()
            owner.integrity_service.paths.working.unlink()
            '''
        import textwrap
        TestAccountManagementEntry().run_probe(textwrap.dedent(setup) + textwrap.dedent(body) + '''
assert not any(name.split('.')[0] in ('ok','PySide6','qfluentwidgets','onnxocr') for name in sys.modules)
''')

    def test_selection_roundtrip_membership_and_no_sequence(self):
        self.probe('''
            value=context.snapshot()
            assert value['available'] and not value['readonly']
            assert [item['value'] for item in value['accounts']]==['','无序列','A1','A3','A4']
            assert all('1991000000' not in item['label'] for item in value['accounts'])
            chosen=context.set(account='A3')
            assert chosen['account']=='A3' and chosen['saved_account']=='A3'
            assert owner.config[CURRENT_ACCOUNT]=='A3'
            stored=json.loads(owner.config.config_file.read_text(encoding='utf-8'))
            assert stored[CURRENT_ACCOUNT]=='A3'
            before=owner.config.config_file.read_bytes()
            for values in ({'account':'A10'},{'sequence':'unknown'},{'account':True},{'other':'A1'},{}):
                try:context.set(**values)
                except ValueError:pass
                else:raise AssertionError('invalid external selection accepted')
                assert owner.config.config_file.read_bytes()==before
            sequence2=environment.repository.load_sequence('序列2')
            environment.repository.publish_sequence('序列2',[],expected_revision=sequence2.revision)
            value=context.set(sequence='序列2')
            assert value['account']=='' and owner.config[CURRENT_ACCOUNT]==''
            value=context.set(account='无序列')
            assert value['unregistered'] and '每日、海墟、深塔及多账号任务除外' in value['summary']
            value=context.set(sequence='序列1')
            assert value['account']=='无序列'
            context.set(sequence='S1')
            # A separate configuration owner sees disk selection and preserves
            # a different config field changed externally before context save.
            disk=json.loads(owner.config.config_file.read_text(encoding='utf-8'))
            disk[CURRENT_ACCOUNT]='A4';disk['Exit After Task']=True
            owner.config.config_file.write_text(json.dumps(disk),encoding='utf-8')
            assert context.snapshot()['account']=='A4'
            context.set(account='A1')
            assert owner.config['Exit After Task'] is True
            reply=host.configuration_request({'command':'get-context','request_id':'context'})
            assert reply['ok'] and reply['result']['account']=='A1',reply
            reply=host.configuration_request({'command':'set-context','request_id':'context','account':'A3'})
            assert reply['ok'] and reply['result']['account']=='A3',reply
            writes=[]
            from unittest.mock import patch
            from src.runtime.native_config import Config
            original_save=Config.save_file
            def saved(config):
                if config.config_file==owner.config.config_file:writes.append(dict(config))
                return original_save(config)
            with patch.object(Config,'save_file',saved):
                reply=host.configuration_request({'command':'set-config','request_id':'generic',
                    'scope':'task','id':'MultiAccountDailyTask',
                    'values':{CURRENT_ACCOUNT:'A1','Exit After Task':False}})
            assert reply['ok'] and len(writes)==1,reply
            assert writes[0][CURRENT_ACCOUNT]=='A1' and writes[0]['Exit After Task'] is False
            before=owner.config.config_file.read_bytes()
            for values in ({CURRENT_ACCOUNT:'A4','Exit After Task':'wrong-type'},
                           {CURRENT_ACCOUNT:'not-member','Exit After Task':True}):
                reply=host.configuration_request({'command':'set-config','request_id':'invalid',
                    'scope':'task','id':'MultiAccountDailyTask','values':values})
                assert not reply['ok'] and owner.config.config_file.read_bytes()==before,reply
        ''')

    def test_foreground_verification_and_other_owner_lock(self):
        self.probe('''
            from src.task.DailyTask import DailyTask
            task=host.tasks[DailyTask]
            task.running=True
            owner.config[CURRENT_ACCOUNT]='A1'
            profile=context._owner()._load_profiles()['A3']
            host.executor._account_feature_run=SimpleNamespace(profile_id=profile['profile_id'],current=task)
            before=owner.config.config_file.read_bytes()
            value=context.snapshot()
            assert value['readonly'] and value['saved_account']=='A1' and value['account']=='A3'
            assert value['verified_account']['profile_id']==profile['profile_id']
            assert owner.config.config_file.read_bytes()==before
            host.executor._account_feature_run.current=owner
            assert context.snapshot()['verified_account'] is None
            host.executor._account_feature_run.current=task
            try:context.set(account='A4')
            except RuntimeError as error:assert '只读' in str(error)
            else:raise AssertionError('foreground selection changed')
            reply=host.configuration_request({'command':'set-config','request_id':'bypass',
                'scope':'task','id':'MultiAccountDailyTask',
                'values':{CURRENT_ACCOUNT:'A4','Exit After Task':True}})
            assert not reply['ok'] and reply['error']['type']=='RuntimeError',reply
            assert owner.config.config_file.read_bytes()==before
            task.running=False
            value=context.snapshot()
            assert value['verified_account'] is None and not value['readonly']
            reader.owners=lambda:[{'running':True,'foreground_task_id':'DailyTask',
                'live':{'profile_id':profile['profile_id']}}]
            value=context.snapshot()
            assert value['readonly'] and value['running_account']['value']=='A3'
            assert value['verified_account'] is None
            try:context.set(account='A4')
            except RuntimeError:pass
            else:raise AssertionError('another foreground owner selection changed')
            assert owner.config.config_file.read_bytes()==before
        ''')

    def test_uninitialized_store_is_unavailable_without_fake_accounts(self):
        self.probe('''
            value=context.snapshot()
            assert not value['available'] and value['readonly']
            assert value['sequences']==[] and value['accounts']==[]
            assert '首账号' in value['reason']
            reply=host.configuration_request({'command':'set-context','request_id':'fresh','account':'A1'})
            assert not reply['ok'] and reply['error']['type']=='RuntimeError'
        ''',fresh=True)

    def test_navigation_keeps_registry_and_legacy_hidden_tasks(self):
        manifest=json.loads((Path(__file__).resolve().parents[1]/
            'gamepacks/wuthering_waves_native/manifest.json').read_text(encoding='utf-8'))
        tasks=manifest['tasks']
        from scripts.build_native_gamepack import native_metadata
        built={task['id']:task for task in native_metadata()['tasks']}
        self.assertEqual(set(built),{task['id'] for task in tasks})
        for task in tasks:
            self.assertEqual({key:built[task['id']][key] for key in ('visible','category','order')},
                             {key:task[key] for key in ('visible','category','order')},task['id'])
        self.assertEqual(len(tasks),29)
        by_class={task['class']:task for task in tasks}
        for name in ('PianoTeachingTask','SecondSolTask','EchoesRemainTask','TestAccountSwitchTask',
                     'NightmareNestTask','TacetTask','ForgeryTask','MaterialPlannerTask','SimulationTask'):
            self.assertFalse(by_class[name]['visible'],name)
        self.assertTrue(all(isinstance(task['order'],int) and task['category'] for task in tasks))
        self.assertEqual(by_class['CharacterTrialTask']['category'],'活动')
        self.assertLess(by_class['CharacterTrialTask']['order'],by_class['TiangongTreasureTask']['order'])
        self.assertEqual(by_class['AutoPickTask']['category'],'战斗与拾取')


if __name__=='__main__':
    unittest.main()
