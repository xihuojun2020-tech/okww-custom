"""Offline v76 control/CLI candidates; no source, device, pip or owner-stop calls."""
import json
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

class TestNativeUpdateControls(unittest.TestCase):
    def setUp(self):
        from gameframe import update_controls
        self.core=update_controls
        from src.runtime import native_release_cli
        self.cli=native_release_cli
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)

    def fixture(self,*,managed=False,configured=True):
        data=self.root/'user-data'/'fixture_pack';data.mkdir(parents=True,exist_ok=True)
        manifest=self.root/'manifest.json'
        manifest.write_text(json.dumps({'id':'fixture_pack','version':'1.97.75','channel':'stable','revision':0}))
        if configured:
            folder=data/'configs';folder.mkdir(exist_ok=True)
            (folder/'gamepack-update.json').write_text(json.dumps({'enabled':True,
                'manifest_url':'https://fixture.invalid/releases/fixture_pack/stable/latest.json',
                'certificate_sha256':'a'*64,'ca_file':'','channel':'stable'}))
        args=['--manifest',str(manifest),'--data-dir',str(data)]
        managed_root=None
        if managed:
            managed_root=self.root/'managed';managed_root.mkdir(exist_ok=True)
            (managed_root/'installation.json').write_text(json.dumps({'managed_root':str(managed_root.resolve()),
                'data_dir':str(data.parent),'base_python':str(self.root/'stable/python.exe')}))
            (managed_root/'active.json').write_text('active-state-sentinel')
            args+=['--managed-root',str(managed_root)]
        (data/'enabled.json').write_text('{"_enabled":true,"account":"fixture"}')
        return data,managed_root,args

    def test_policy_default_exact_legacy_and_startup_once(self):
        path=self.root/'policy.json'
        self.assertEqual(self.core.load_policy(path),'AUTO_UPDATE')
        for policy in self.core.POLICIES:self.assertEqual(self.core.load_policy(path,policy),policy)
        path.write_text('{"policy":"not-a-policy"}')
        with self.assertRaises(ValueError):self.core.load_policy(path)
        coordinator=self.core.UpdateCoordinator(data_dir=self.root,controller=Mock())
        coordinator.execute=Mock(return_value={'status':'pending'})
        self.assertEqual(coordinator.startup(Mock(),'MANUAL_UPDATE')['status'],'manual')
        coordinator.execute.assert_not_called()
        coordinator=self.core.UpdateCoordinator(data_dir=self.root,controller=Mock())
        coordinator.execute=Mock(return_value={'status':'pending'})
        self.assertEqual(coordinator.startup(Mock(),'AUTO_UPDATE_PRE_RELEASE')['status'],'pending')
        self.assertIsNone(coordinator.startup(Mock(),'AUTO_UPDATE_PRE_RELEASE'))
        coordinator.execute.assert_called_once()

    def test_coordinator_uses_indexed_metadata_hook_separate_controller_without_owner_stop(self):
        package=self.root/'installed';package.mkdir();(package/'files.json').write_text('{}')
        launch={'command':['fake-python','-m','gameframe.package_process','--','--manifest','fake.json'],
                'cwd':'fake-cwd','env':{'FIXTURE':'value'}}
        hook=Mock(return_value=launch)
        manifest=SimpleNamespace(root=package,id='fixture_pack',version='1.97.75',supports_managed_updates=True,
            load=lambda:SimpleNamespace(automatic_update_command=hook))
        process=SimpleNamespace(returncode=0,communicate=lambda:('{"event":"native-update","status":"pending"}\n',None))
        controller=Mock(spec=["assert_idle","_launch","close","stop"]);controller._launch.return_value=process
        combat_owner=Mock();combat_owner.stop.side_effect=AssertionError('owner stop forbidden')
        coordinator=self.core.UpdateCoordinator(data_dir=self.root/'user-data',managed_root=self.root/'managed',controller=controller)
        from contextlib import nullcontext
        with patch.object(self.core,'package_lease',return_value=nullcontext()),patch.object(self.core.PackageManifest,'read',return_value=manifest),patch.object(self.core,'verify_index') as index:
            result=coordinator.execute(manifest,'AUTO_UPDATE_PRE_RELEASE',action='prepare',automatic=True)
        self.assertEqual(result['status'],'pending');index.assert_called_once_with(package,required=True)
        hook.assert_called_once_with(self.root/'user-data'/'fixture_pack')
        command=controller._launch.call_args.args[0]
        self.assertIn('--automatic',command);self.assertIn('AUTO_UPDATE_PRE_RELEASE',command)
        self.assertIn('prepare',command);self.assertIn('--managed-root',command)
        combat_owner.stop.assert_not_called();controller.stop.assert_not_called()
        controller.close.assert_called_once()
        (package/'files.json').unlink()
        self.assertEqual(coordinator.execute(manifest,'AUTO_UPDATE')['status'],'source_checkout')
        self.assertEqual(hook.call_count,1)

    def test_cli_manual_unconfigured_and_unmanaged_never_query_or_download(self):
        data,_,args=self.fixture(configured=False)
        factory=Mock(side_effect=AssertionError('source access forbidden'));events=[]
        self.assertEqual(self.cli.main(args+['--policy','MANUAL_UPDATE','--automatic','prepare'],service_factory=factory,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'manual')
        self.assertEqual(self.cli.main(args+['check'],service_factory=factory,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'source_unconfigured')
        self.assertEqual(self.cli.main(args+['--automatic','prepare'],service_factory=factory,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'needs-managed-installation')
        self.assertIn('initialize',events[-1]['install_command']);factory.assert_not_called()
        self.assertEqual((data/'enabled.json').read_text(),'{"_enabled":true,"account":"fixture"}')

    def test_cli_explicit_source_pair_pending_and_failure_leave_data_active_unchanged(self):
        data,managed,args=self.fixture(managed=True)
        bundle={'version':'1.97.76','channel':'beta','revision':1}
        service=Mock(source_root='https://fixture.invalid/releases/fixture_pack')
        service.check.return_value=SimpleNamespace(status='available',release=bundle,unpublished_channels=('alpha',))
        service.download.return_value=SimpleNamespace(bundle=bundle,artifact_root=self.root/'verified-artifacts')
        factory=Mock(return_value=service);events=[]
        def prepare(root,artifacts,release,**options):
            self.assertEqual(root,managed.resolve());self.assertEqual(release,bundle)
            self.assertTrue(options['automatic']);self.assertEqual(options['base_python'],str(self.root/'stable/python.exe'))
            pointer={'environment':'versions/fixture','bundle':release,'automatic':True}
            (root/'pending.json').write_text(json.dumps(pointer));return pointer
        before=(managed/'active.json').read_bytes(),(data/'enabled.json').read_bytes()
        self.assertEqual(self.cli.main(args+['--policy','AUTO_UPDATE_PRE_RELEASE','--automatic','prepare'],service_factory=factory,prepare=prepare,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'pending');self.assertEqual(events[-1]['unpublished_channels'],['alpha'])
        self.assertEqual(factory.call_args.kwargs['source_root'],'https://fixture.invalid/releases/fixture_pack')
        service.check.assert_called_once_with({'version':'1.97.75','channel':'stable','revision':0},'AUTO_UPDATE_PRE_RELEASE',automatic=True)
        self.assertEqual(before,((managed/'active.json').read_bytes(),(data/'enabled.json').read_bytes()))
        service.check.side_effect=PermissionError('fixture source denied')
        self.assertEqual(self.cli.main(args+['check'],service_factory=factory,emit=events.append),1)
        self.assertEqual(events[-1]['status'],'failed');self.assertEqual(events[-1]['failure'],'PermissionError')
        self.assertFalse((managed/'last-update-error.json').exists());self.assertTrue((managed/'pending.json').is_file())
        self.assertEqual(before,((managed/'active.json').read_bytes(),(data/'enabled.json').read_bytes()))

    def test_managed_check_honors_explicit_launcher_data_root_change(self):
        old_data,managed,args=self.fixture(managed=True)
        new_root=self.root/'chosen-user-data';new_data=new_root/'fixture_pack';new_data.mkdir(parents=True)
        (old_data.parent/'launcher-context.json').write_text(json.dumps({'selected_package':None,
            'restore_services':True,'data_root':str(new_root)}))
        args[args.index('--data-dir')+1]=str(new_data)
        factory=Mock(side_effect=AssertionError('unconfigured source must not query'));events=[]
        before=(managed/'active.json').read_bytes(),(old_data/'enabled.json').read_bytes()
        self.assertEqual(self.cli.main(args+['check'],service_factory=factory,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'source_unconfigured');factory.assert_not_called()
        self.assertEqual(before,((managed/'active.json').read_bytes(),(old_data/'enabled.json').read_bytes()))
        with self.assertRaises(ValueError):self.cli._installation(managed,old_data,'fixture_pack')

    def test_source_failure_preserves_bootstrap_candidate_failure_marker(self):
        data,managed,args=self.fixture(managed=True)
        marker=managed/'last-update-error.json'
        marker.write_text(json.dumps({'status':'failed','phase':'precommit','message':'candidate failure',
                                    'pending':{'environment':'versions/fixture','automatic':True}}))
        before=marker.read_bytes(),(managed/'active.json').read_bytes(),(data/'enabled.json').read_bytes()
        factory=Mock(side_effect=RuntimeError('original fixture source failure'));events=[]
        self.assertEqual(self.cli.main(args+['check'],service_factory=factory,emit=events.append),1)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['failure'],'RuntimeError')
        self.assertEqual(events[0]['message'],'original fixture source failure')
        self.assertEqual(before,(marker.read_bytes(),(managed/'active.json').read_bytes(),(data/'enabled.json').read_bytes()))

    def test_explicit_manual_prepare_promotes_auto_pending_without_rebuilding(self):
        _,managed,args=self.fixture(managed=True)
        bundle={'version':'1.97.76','channel':'stable','revision':0}
        pointer={'environment':'versions/fixture','bundle':bundle,'automatic':True}
        pending=managed/'pending.json';pending.write_text(json.dumps(pointer))
        (managed/'update-policy.json').write_text('{"policy":"MANUAL_UPDATE"}')
        service=Mock(source_root='https://fixture.invalid/releases/fixture_pack')
        service.check.return_value=SimpleNamespace(status='available',release=bundle,unpublished_channels=())
        events=[];prepare=Mock(side_effect=AssertionError('Reuse must not reinstall'))
        with patch('gameframe.managed_bootstrap.check_ready'):
            self.assertEqual(self.cli.main(args+['--policy','MANUAL_UPDATE','prepare'],
                service_factory=Mock(return_value=service),prepare=prepare,emit=events.append),0)
            explicit=json.loads(pending.read_text())
            self.assertFalse(explicit['automatic'])
            from gameframe.managed_bootstrap import automatic_commit_allowed
            self.assertTrue(automatic_commit_allowed(managed,explicit))
            self.assertEqual(self.cli.main(args+['--automatic','prepare'],
                service_factory=Mock(return_value=service),prepare=prepare,emit=events.append),0)
            self.assertFalse(json.loads(pending.read_text())['automatic'])
        service.download.assert_not_called();prepare.assert_not_called()

    def test_cli_missing_channel_and_explicit_nonmanaged_prepare_have_honest_status(self):
        _,_,args=self.fixture()
        service=Mock(source_root='https://fixture.invalid/releases/fixture_pack')
        factory=Mock(return_value=service);events=[]
        service.check.return_value=SimpleNamespace(status='no_release',release=None,unpublished_channels=('stable',))
        self.assertEqual(self.cli.main(args+['check'],service_factory=factory,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'no_release')
        service.check.return_value=SimpleNamespace(status='available',release={'version':'1.97.76'},unpublished_channels=())
        self.assertEqual(self.cli.main(args+['prepare'],service_factory=factory,emit=events.append),0)
        self.assertEqual(events[-1]['status'],'needs-managed-installation');service.download.assert_not_called()

    def test_real_qt_controls_manual_policy_pending_error_once_and_explicit_checks(self):
        import os
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication,QFormLayout,QLabel,QPlainTextEdit
        app=QApplication.instance() or QApplication([])
        manifest=SimpleNamespace(supports_managed_updates=True)
        window=SimpleNamespace(_context_path=self.root/'launcher-context.json',_launcher_context={'update_policy':'MANUAL_UPDATE'},
            data_dir=self.root,_launcher_labels={},_manifest=lambda:manifest,_closing=False,_events=queue.Queue(),
            output=QPlainTextEdit(),_error=Mock())
        coordinator=Mock(startup_checked=False,data_dir=self.root)
        form=QFormLayout();bindings=self.core.attach_update_controls(window,form,coordinator=coordinator)
        self.assertEqual(bindings.policy,'MANUAL_UPDATE');self.assertEqual(self.core.load_policy(self.root/'update-policy.json'),'MANUAL_UPDATE')
        bindings.startup();coordinator.startup.assert_not_called();self.assertTrue(coordinator.startup_checked)
        window.update_policy.setCurrentIndex(2)
        self.assertEqual(self.core.load_policy(self.root/'update-policy.json'),'AUTO_UPDATE_PRE_RELEASE')
        class ImmediateThread:
            def __init__(self,*,target,daemon):self.target=target
            def start(self):self.target()
        coordinator.execute.return_value={'event':'native-update','status':'available'}
        with patch.object(self.core.threading,'Thread',ImmediateThread):bindings.submit('check')
        kind,value=window._events.get_nowait();self.assertTrue(bindings.handle(kind,value))
        coordinator.execute.assert_called_once_with(manifest,'AUTO_UPDATE_PRE_RELEASE',action='check',automatic=False)
        self.assertFalse(bindings.prepare.isEnabled())
        managed=self.root/'managed';managed.mkdir();(managed/'pending.json').write_text('{}')
        (managed/'last-update-error.json').write_text('{"phase":"precommit","message":"fixture failed"}')
        bindings.managed_root=managed;bindings.refresh();bindings.refresh()
        self.assertEqual(window.output.toPlainText().count('fixture failed'),1)
        self.assertTrue((managed/'pending.json').exists());self.assertTrue((managed/'last-update-error.json').exists())
        self.assertFalse(bindings.retry.isHidden())
        app.processEvents()

    def test_actual_gui_startup_selection_events_language_and_close_wait(self):
        import os
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication
        from gameframe import gui
        app=QApplication.instance() or QApplication([])
        packages=self.root/'packages';data=self.root/'gui-data';data.mkdir()
        for name in ('fixture_one','fixture_two'):
            root=packages/name;root.mkdir(parents=True)
            (root/'plugin.py').write_text('raise AssertionError("GUI discover must not import plugin")')
            (root/'manifest.json').write_text(json.dumps({'id':name,'title':name,'version':'1.00.00',
                'api_version':1,'entrypoint':'plugin.py:create_package','license':'MIT','platforms':['windows'],
                'execution':'native','supports_managed_updates':True,
                'tasks':[{'id':'fixture','title':'fixture','kind':'one-shot','default_config':{},'required_capabilities':[]}]}))
        sentinel=data/'battle.json';sentinel.write_text('{"_enabled":true,"account":"unchanged"}')
        before=sentinel.read_bytes();order=[]
        class Controller:
            process=None;session=False
            def close(self):order.append('owner.close')
            def assert_idle(self):pass
            def stop(self):raise AssertionError('No owner stop is permitted by updater')
        class ImmediateThread:
            def __init__(self,*,target,daemon):self.target=target
            def start(self):self.target()
            def join(self):order.append('update.join')
        coordinator=self.core.UpdateCoordinator(data_dir=data,controller=Controller())
        coordinator.execute=Mock(return_value={'event':'native-update','status':'pending'})
        with patch.object(gui,'Controller',Controller),patch.object(self.core,'UpdateCoordinator',return_value=coordinator),patch.object(self.core.threading,'Thread',ImmediateThread):
            window=gui.GameFrameWindow(packages,data,key_state=lambda key:False)
            self.addCleanup(window.timer.stop)
            self.addCleanup(lambda:setattr(window,'_cleanup_done',True))
            self.addCleanup(window.close)
            app.processEvents();window._drain_events()
            self.assertEqual(coordinator.execute.call_count,1)
            self.assertTrue(coordinator.startup_checked)
            self.assertIn('下一次正常启动',window.managed_update_bindings.status.text())
            # Selecting another package does not schedule a second automatic check.
            window.package_select.setCurrentIndex(1);window.managed_update_bindings.startup()
            self.assertEqual(coordinator.execute.call_count,1)
            bindings=window.managed_update_bindings
            bindings.set_status('完整环境更新失败：{error}',error='fixture {detail}')
            bindings.localize({'手动更新':'Manual fixture','自动更新（正式版）':'Stable fixture',
                '自动更新（含预发布）':'Prerelease fixture','检查更新':'Check fixture',
                '完整环境更新失败：{error}':'Update failed: {error}'})
            self.assertEqual(bindings.status.text(),'Update failed: fixture {detail}')
            self.assertEqual(window.update_policy.itemText(0),'Manual fixture')
            self.assertEqual(window.update_policy.itemData(0),'MANUAL_UPDATE')
            self.assertEqual(bindings.check.text(),'Check fixture')
            window.process=SimpleNamespace(poll=lambda:None)  # Active combat owner remains active.
            window.update_policy.setCurrentIndex(0)
            coordinator.execute.return_value={'event':'native-update','status':'available'}
            bindings.submit('check');window._drain_events()
            self.assertEqual(coordinator.execute.call_args.kwargs,{'action':'check','automatic':False})
            self.assertIsNotNone(window.process)
            self.assertEqual(order,[])
            self.assertEqual(sentinel.read_bytes(),before)
            window._close_worker()
            self.assertEqual(order[0],'update.join')
            self.assertIn('owner.close',order[1:])
            self.assertEqual(sentinel.read_bytes(),before)
            window.timer.stop();window._cleanup_done=True;window._closing=True;window.close()

if __name__=='__main__':unittest.main()
