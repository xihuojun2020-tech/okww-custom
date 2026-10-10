"""Strict owner character replacement with real native tasks and Replay."""
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestNativeCharacterHost(unittest.TestCase):
    def test_session_reload_preempts_character_and_releases_before_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            script = r'''
                import sys, threading, json
                from pathlib import Path
                sys.path.insert(0, ROOT)
                from src.runtime import combat_api
                combat_api.configure(native=True,data_dir=DATA)
                from gameframe.api import TaskContext, Cancelled
                from gameframe.devices.replay import ReplayDevice
                from src.combat.settings import COMBAT_GLOBAL_DEFAULTS,TEMPLATE_MATCHING_DEFAULTS
                from src.combat.roster_context import roster_context
                from src.combat.rotation_state import RotationState
                from src.runtime.native_combat_host import NativeCombatHost
                from src.runtime.native_task import NativeTriggerTask
                from src.task.BaseCombatTask import BaseCombatTask
                from src.char.BaseChar import BaseChar
                from src.char.CharFactory import char_dict
                order=[]
                class Device(ReplayDevice):
                    def release_all(self):
                        order.append('release-all')
                        super().release_all()
                class Service(BaseCombatTask,NativeTriggerTask):
                    def run(self):
                        try: self.chars[0].perform()
                        finally:
                            self._release_combat_inputs()
                            order.append('task-released')
                        order.append('old-run-resumed')
                        return True
                class OldChar(BaseChar):
                    def do_perform(self):
                        self.task.send_key_down('x')
                        order.append('down')
                        self.task.executor.context.requests.put({'command':'reload-character-code'})
                        self.task.sleep(.01)
                        order.append('old-character-resumed')
                stop=threading.Event(); device=Device([])
                def observe(event):
                    if event['event']=='character-code-reloaded':
                        order.append('committed')
                        assert not device.held and not host.task._combat_held_keys
                        stop.set()
                context=TaskContext(device,{},Path(DATA),stop,'chars',observe)
                host=NativeCombatHost(context,coco_path=Path(ROOT)/'assets/coco_annotations.json',
                    global_options=COMBAT_GLOBAL_DEFAULTS,ocr_engine=None,
                    template_matching=TEMPLATE_MATCHING_DEFAULTS,task_entry=Service)
                info=next(i for i in char_dict.values() if i['cls'].__name__=='Mortefi')
                task=host.task; old=OldChar(task,0,char_name=info['canonical_name'])
                task.chars=[old]; task._char_context=roster_context(task)
                task._battle_roster_confirmed=False; task._rotation_roster_recheck=False
                task._rotation_state=RotationState(task.chars)
                custom=Path(DATA)/'configs/custom_chars'; custom.mkdir(parents=True,exist_ok=True)
                (custom/'Mortefi.py').write_text('from src.char.BaseChar import BaseChar\nclass Mortefi(BaseChar):\n    marker=71\n')
                (custom/'custom_chars.json').write_text(json.dumps({'Mortefi':{'use_custom':True}}))
                try: host.run_session('Service')
                except Cancelled: pass
                else: raise AssertionError('session did not stop')
                assert order.index('down') < order.index('task-released') < order.index('committed'),order
                assert 'release-all' in order[order.index('task-released'):order.index('committed')],order
                assert 'old-run-resumed' not in order and 'old-character-resumed' not in order,order
                assert [a.kind for a in device.actions]==['key_down','key_up'],device.actions
                assert task.chars[0] is not old and task.chars[0].marker==71
                assert task.enabled and json.loads(task.config.config_file.read_text())['_enabled']
                assert not device.held and not task._combat_held_keys
            '''
            script = textwrap.dedent(script).replace('ROOT', repr(str(ROOT))).replace('DATA', repr(directory))
            result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', script],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_candidate_commit_failure_and_paused_state(self):
        with tempfile.TemporaryDirectory() as directory:
            script = r'''
                import sys, threading, json
                from pathlib import Path
                from types import SimpleNamespace
                sys.path.insert(0, ROOT)
                from src.runtime import combat_api
                combat_api.configure(native=True,data_dir=DATA)
                from gameframe.api import TaskContext
                from gameframe.devices.replay import ReplayDevice
                from src.combat.settings import COMBAT_GLOBAL_DEFAULTS,TEMPLATE_MATCHING_DEFAULTS
                from src.runtime.native_combat_host import NativeCombatHost
                from src.char.CustomCharLoader import get_native_character_classes
                from src.char.CharFactory import char_dict
                from src.char.BaseChar import BaseChar
                from src.combat.rotation_state import RotationState
                device=ReplayDevice([])
                pause=threading.Event(); pause.set()
                context=TaskContext(device,{},Path(DATA),threading.Event(),'chars',lambda event:None,pause)
                host=NativeCombatHost(context,coco_path=Path(ROOT)/'assets/coco_annotations.json',
                    global_options=COMBAT_GLOBAL_DEFAULTS,ocr_engine=None,
                    template_matching=TEMPLATE_MATCHING_DEFAULTS)
                task=host.task
                info=next(i for i in char_dict.values() if i['cls'].__name__=='Mortefi')
                builtin=info['cls']
                old=builtin(task,0,char_name=info['canonical_name'])
                unaffected=BaseChar(task,1,char_name='unknown')
                fields=('is_current_char','has_intro','has_sub_dps_intro','last_switch_time',
                    'last_switch_in_time','last_res','last_echo','last_liberation','last_buff_time',
                    'last_full_con_switch_time','last_perform','last_outro_time')
                for index,key in enumerate(fields): setattr(old,key,index+10)
                old._switch_unrevivable=True; old._switch_cooldown_until=123
                task.chars=[old,unaffected]; task._battle_roster_confirmed=True
                task._rotation_state=RotationState(task.chars); previous_rotation=task._rotation_state
                custom=Path(DATA)/'configs/custom_chars'; custom.mkdir(parents=True,exist_ok=True)
                (custom/'Mortefi.py').write_text('from src.char.BaseChar import BaseChar\nclass Mortefi(BaseChar):\n    marker=2\n')
                (custom/'custom_chars.json').write_text(json.dumps({'Mortefi':{'use_custom':True}}))
                result=host.reload_character_code()
                current=task.chars[0]
                assert current is not old and current.marker==2
                assert task.chars[1] is unaffected
                assert all(getattr(current,key)==getattr(old,key) for key in fields)
                assert current._switch_unrevivable and current._switch_cooldown_until==123
                assert not task._battle_roster_confirmed and task._rotation_roster_recheck
                assert task._rotation_state is not previous_rotation
                assert task.enabled and task.config['_enabled'] and not device.actions
                classes=get_native_character_classes(); revision=host.applied_character_revision
                chars=task.chars; rotation=task._rotation_state
                (custom/'Mortefi.py').write_text('from src.char.BaseChar import BaseChar\nclass Mortefi(BaseChar):\n'
                    '    def __init__(self,*args,**kwargs):\n        raise ValueError("broken ctor")\n')
                try: host.reload_character_code()
                except ValueError as error: assert 'broken ctor' in str(error)
                else: raise AssertionError('failed candidate applied')
                assert get_native_character_classes()==classes and host.applied_character_revision==revision
                assert task.chars is chars and task._rotation_state is rotation
                (custom/'Mortefi.py').write_text('from src.char.BaseChar import BaseChar\nclass Mortefi(BaseChar):\n    marker=3\n')
                def failed_release(**kwargs): raise OSError('release failed')
                task._combat_held_keys['x']=SimpleNamespace(send_key_up=failed_release)
                try: host.reload_character_code()
                except RuntimeError as error: assert 'released task input' in str(error)
                else: raise AssertionError('held input applied')
                assert get_native_character_classes()==classes and task.chars is chars
                assert task._rotation_state is rotation and host.applied_character_revision==revision
                assert task.enabled and json.loads(task.config.config_file.read_text())['_enabled']
                assert not device.actions
                assert not any(name.split('.')[0] in ('ok','PySide6','onnxocr') for name in sys.modules)
            '''
            script = textwrap.dedent(script).replace('ROOT', repr(str(ROOT))).replace('DATA', repr(directory))
            result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', script],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
