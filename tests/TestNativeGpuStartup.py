"""Real worker/package GPU startup boundaries with fake devices and leases."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class TestNativeGpuStartup(unittest.TestCase):
    def run_probe(self,body,*,source_root=ROOT,core_root=None,package_root=None):
        from tests.TestAccountManagementEntry import TestAccountManagementEntry
        package_root=Path(package_root) if package_root is not None else Path(source_root)/'gamepacks/wuthering_waves_native'
        prefix='package_root=Path('+repr(str(package_root))+')\n'
        return TestAccountManagementEntry().run_probe(prefix+body,source_root=source_root,core_root=core_root)

    def test_worker_real_package_once_skip_unknown_and_cleanup_order(self):
        self.run_probe('''
import ctypes,sys
from contextlib import contextmanager,ExitStack
from types import SimpleNamespace
from unittest.mock import Mock,patch
from gameframe import worker
from gameframe.packages import PackageManifest
from src.runtime import native_gpu_advisory as advisory
from src.runtime.vendor.gpu_driver_settings import GpuDriverPostProcessing
source_root=Path(sys.argv[1]).resolve()
core_root=Path(sys.argv[3]).resolve() if len(sys.argv)>3 else source_root
assert Path(worker.__file__).resolve().is_relative_to(core_root)
assert Path(advisory.__file__).resolve().is_relative_to(source_root)
manifest=PackageManifest.read(package_root)
service=next(task for task in manifest.tasks if task.kind=='service')
real_advisory=advisory.NativeGpuAdvisory

def forbidden(*args,**kwargs):raise AssertionError('Real GPU/DLL/process/file-log access forbidden')
for mode in ('warning','replay','detector-error','process-error','observer-error','runtime-error'):
 order=[];events=[];enabled_writes=[]
 package=manifest.load()
 assert Path(sys.modules[type(package).__module__].__file__).resolve()==(package_root/'plugin.py').resolve()
 task_state=SimpleNamespace(_enabled=True)
 class Device:
  capabilities=frozenset({'frames'}) if mode=='replay' else frozenset({'frames','desktop-handoff'})
  window=SimpleNamespace(hwnd=42,_pid=123,_process_created=12.5)
  prepared=False
  def prepare(self,stop):self.prepared=True;order.append('device.prepare')
  def _check_target_identity(self):
   assert self.prepared;order.append('identity')
  def close(self):order.append('device.close')
 device=Device()
 process=Mock(create_time=Mock(return_value=12.5),exe=Mock(return_value='fixture/Client.exe'))
 process_factory=Mock(return_value=process)
 feature=GpuDriverPostProcessing('NVIDIA','Image Sharpening',True,'fixture')
 detector=Mock(return_value={'enabled':[feature],'checks':[feature]})
 if mode in ('detector-error','runtime-error'):detector.side_effect=OSError('fixture detector unavailable')
 if mode=='process-error':process.exe.side_effect=PermissionError('fixture process denied')
 instance=real_advisory(detector=detector,process_factory=process_factory)
 constructor=Mock(return_value=instance)
 package.prepare_data=lambda data:order.append('package.prepare_data')
 package.prepare=lambda task,data:order.append('package.prepare')
 package.close=lambda:order.append('package.close')
 original_ready=package.device_ready
 def ready(device,data,emit):
  order.append('package.device_ready');assert device.prepared
  return original_ready(device,data,emit)
 package.device_ready=ready
 class Store:
  def __init__(self,path):order.append('store.create')
  def set_enabled(self,pack,task,enabled):enabled_writes.append(enabled)
  def close(self):order.append('store.close')
 class Runtime:
  def __init__(self,store,emit):self.emit=emit
  def run_service(self,manifest,pack,task,device,data,**kwargs):
   order.append('runtime.run_service')
   # Repeated callers use the same real package advisory for this lifetime.
   assert pack.device_ready(device,data,self.emit) is None
   assert pack.device_ready(device,data,self.emit) is None
   assert task_state._enabled is True
   if mode=='runtime-error':raise RuntimeError('fixture task failure')
 @contextmanager
 def lease(name):
  order.append(name+'.enter')
  try:yield
  finally:order.append(name+'.exit')
 def emit(event):
  events.append(event)
  if mode=='observer-error' and event.get('advisory')=='gpu-driver':raise BrokenPipeError('fixture observer')
 logger=Mock()
 with ExitStack() as guards:
  for name in ('WinDLL','CDLL'):guards.enter_context(patch.object(ctypes,name,side_effect=forbidden))
  guards.enter_context(patch('psutil.Process',side_effect=forbidden))
  guards.enter_context(patch.object(advisory,'logger',logger))
  guards.enter_context(patch.object(advisory,'NativeGpuAdvisory',constructor))
  guards.enter_context(patch('src.runtime.native_language.load_language',return_value=SimpleNamespace(translate=str)))
  guards.enter_context(patch.object(worker.threading,'Thread'))
  guards.enter_context(patch.object(worker.PackageManifest,'read',return_value=manifest))
  guards.enter_context(patch.object(type(manifest),'load',return_value=package))
  guards.enter_context(patch.object(worker,'create_device',return_value=device))
  guards.enter_context(patch.object(worker,'RunStore',Store))
  guards.enter_context(patch.object(worker,'Runtime',Runtime))
  guards.enter_context(patch.object(worker,'emit',side_effect=emit))
  guards.enter_context(patch.object(worker,'package_lease',side_effect=lambda path:lease('package-lease')))
  guards.enter_context(patch.object(worker,'data_lease',side_effect=lambda path:lease('data-lease')))
  guards.enter_context(patch.object(worker,'device_input_lease',side_effect=lambda config:lease('device-lease')))
  result=worker.main(['--package',str(package_root),'--task',service.id,'--data-dir',str(root/'data'),'--device','{"type":"replay","frames":[]}'])
 assert result==(1 if mode=='runtime-error' else 0)
 assert task_state._enabled is True and enabled_writes==[True]
 assert order.index('device.prepare')<order.index('package.device_ready')<order.index('store.create')<order.index('runtime.run_service')
 assert order[-6:]==['device.close','package.close','store.close','device-lease.exit','data-lease.exit','package-lease.exit']
 constructor.assert_called_once()
 notices=[event for event in events if event.get('advisory')=='gpu-driver']
 assert len(notices)==1
 if mode=='replay':
  assert notices[0]['status']=='skipped';process_factory.assert_not_called();detector.assert_not_called()
 elif mode=='process-error':
  assert notices[0]['status']=='unknown';assert notices[0]['failure']=='PermissionError';detector.assert_not_called();logger.error.assert_called_once()
 elif mode in ('detector-error','runtime-error'):
  assert notices[0]['status']=='unknown';assert notices[0]['failure']=='OSError';detector.assert_called_once_with('fixture/Client.exe',42);logger.error.assert_called_once()
 else:
  assert notices[0]['status']=='warning' and notices[0]['notify'] is True
  detector.assert_called_once_with('fixture/Client.exe',42)
  if mode=='observer-error':logger.error.assert_called_once()
  else:logger.error.assert_not_called()
# Packages predating the optional hook keep their original startup route.
order=[];enabled_writes=[]
package=SimpleNamespace(close=lambda:order.append('package.close'))
class OldRuntime:
 def __init__(self,store,emit):pass
 def run_service(self,*args,**kwargs):order.append('runtime.run_service')
with ExitStack() as guards:
 guards.enter_context(patch.object(worker.threading,'Thread'))
 guards.enter_context(patch.object(worker.PackageManifest,'read',return_value=manifest))
 guards.enter_context(patch.object(type(manifest),'load',return_value=package))
 guards.enter_context(patch.object(worker,'create_device',return_value=device))
 guards.enter_context(patch.object(worker,'RunStore',Store))
 guards.enter_context(patch.object(worker,'Runtime',OldRuntime))
 guards.enter_context(patch.object(worker,'emit',side_effect=forbidden))
 guards.enter_context(patch.object(advisory,'NativeGpuAdvisory',side_effect=forbidden))
 guards.enter_context(patch.object(worker,'package_lease',side_effect=lambda path:lease('package-lease')))
 guards.enter_context(patch.object(worker,'data_lease',side_effect=lambda path:lease('data-lease')))
 guards.enter_context(patch.object(worker,'device_input_lease',side_effect=lambda config:lease('device-lease')))
 assert worker.main(['--package',str(package_root),'--task',service.id,'--data-dir',str(root/'old-data'),'--device','{"type":"replay","frames":[]}'])==0
assert enabled_writes==[True] and 'runtime.run_service' in order
assert order[-6:]==['device.close','package.close','store.close','device-lease.exit','data-lease.exit','package-lease.exit']
''')

if __name__=='__main__':unittest.main()
