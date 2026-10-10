"""Real account stores and production task metadata in isolated native workers."""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PRELUDE = '''
import importlib.abc
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, sys.argv[1])
root = Path(sys.argv[2]).resolve()
cwd = root / 'unrelated-cwd'
cwd.mkdir()
(cwd / 'configs').mkdir()
sentinel = cwd / 'configs' / 'daily_profiles.json'
sentinel.write_text('unrelated configuration', encoding='utf-8')
os.chdir(cwd)
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ok', 'PySide6', 'qfluentwidgets', 'config', 'main', 'custom_ok'}:
            raise ImportError('Native account path imported ' + fullname)
sys.meta_path.insert(0, BlockLegacy())
from tests.fixture_support import make_account_environment
from src.runtime.account_runtime_bootstrap import prepare_native_account_runtime
data_dir = root / 'native-data'
'''

POSTLUDE = '''
assert sentinel.read_text(encoding='utf-8') == 'unrelated configuration'
assert not any(name.split('.')[0] in {'ok', 'PySide6', 'qfluentwidgets', 'config', 'main', 'custom_ok'}
               for name in sys.modules)
from src.evidence import service
if service._service is not None:
    service._service.close()
'''

PREPARE = '''
env = make_account_environment(data_dir, names=('A1', 'A3', 'A4'))
runtime = prepare_native_account_runtime(data_dir, 'native-account-test')
'''

HOST = '''
import threading
from types import SimpleNamespace
from gameframe.api import TaskContext
from gameframe.devices.replay import ReplayDevice
from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS
from src.runtime.native_combat_host import NativeCombatHost
device = ReplayDevice([Path(sys.argv[1]) / 'tests/images/weekly_boss/list1.png'])
events = []
context = TaskContext(device, {}, data_dir, threading.Event(), 'account-test', events.append)
engine = Mock()
host = NativeCombatHost(context, coco_path=Path(sys.argv[1]) / 'assets/coco_annotations.json',
    global_options=COMBAT_GLOBAL_DEFAULTS, template_matching=TEMPLATE_MATCHING_DEFAULTS,
    ocr_engine=engine, ocr_config={'default': {'lib': 'onnxocr'}},
    task_entry='src.task.MultiAccountDailyTask:MultiAccountDailyTask',
    registered_tasks=('src.task.DailyTask:DailyTask',
                      'src.task.MultiAccountWeeklyGardenTask:MultiAccountWeeklyGardenTask'),
    window=SimpleNamespace(hwnd_title='test', exists=True, visible=True, hwnd=1))
from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_SEQUENCE, CURRENT_ACCOUNT
from src.task.DailyTask import DailyTask, PROFILE_SEQUENCE, DAILY_PROFILE
multi = host.task
daily = multi.get_task_by_class(DailyTask)
'''


class TestNativeAccountRuntime(unittest.TestCase):
    def run_native(self, body):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'account_probe.py'
            script.write_text(PRELUDE + textwrap.dedent(body) + POSTLUDE, encoding='utf-8')
            result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(script), str(ROOT), directory],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_preflight_binds_existing_services_and_paths_to_explicit_root(self):
        self.run_native(PREPARE + '''
from src.account_repository import get_default_repository
from src.config_integrity import get_default_service
from src.evidence.service import get_evidence_service
from src.runtime.account_task_support import get_relative_path, program_version
from src.storage import get_config_backup_dir, get_ok_warehouse, get_warehouse_sub
assert runtime.require_ready()
assert runtime.root == data_dir.resolve()
assert runtime.repository is get_default_repository()
assert runtime.integrity_service is get_default_service()
assert runtime.integrity_service.paths.master == data_dir / 'configs/account_master_config.json'
assert Path(get_relative_path('configs', 'daily_profiles.json')) == data_dir / 'configs/daily_profiles.json'
assert program_version() == 'native-account-test'
assert get_config_backup_dir() == data_dir / 'configs_backup'
assert Path(get_ok_warehouse()) == data_dir
assert Path(get_warehouse_sub('okww监控室')) == data_dir / 'okww监控室'
assert get_evidence_service().repository.root == data_dir / 'okww监控室/CompletionEvidence'
try:
    get_evidence_service(root=root / 'other-evidence')
except RuntimeError:
    pass
else:
    raise AssertionError('evidence root silently changed')
''')

    def test_missing_master_is_rejected_without_creating_an_accepted_master(self):
        self.run_native('''
from src.config_integrity import ConfigIntegrityBlocked
try:
    prepare_native_account_runtime(data_dir, 'test')
except ConfigIntegrityBlocked:
    pass
else:
    raise AssertionError('missing master accepted')
assert not (data_dir / 'configs/account_master_config.json').exists()
from src.evidence import service
assert service._service is None
''')

    def test_corrupt_master_is_rejected_and_preserved(self):
        self.run_native('''
make_account_environment(data_dir, names=('A1', 'A3'))
master = data_dir / 'configs/account_master_config.json'
master.write_bytes(b'{broken json')
from src.config_integrity import ConfigIntegrityBlocked
try:
    prepare_native_account_runtime(data_dir, 'test')
except ConfigIntegrityBlocked:
    pass
else:
    raise AssertionError('corrupt master accepted')
assert master.read_bytes() == b'{broken json'
from src.evidence import service
assert service._service is None
''')

    def test_config_notifies_after_commit_and_never_on_failed_save(self):
        self.run_native('''
from src.runtime.native_config import Config
config = Config('sequence', {'selected': 'first'}, folder=data_dir / 'configs')
seen = []
config.on_change = lambda key, value: seen.append(json.loads(config.config_file.read_text())[key])
config['selected'] = 'second'
assert seen == ['second']
with patch.object(config, 'save_file', side_effect=OSError('disk failure')):
    try:
        config['selected'] = 'third'
    except OSError:
        pass
    else:
        raise AssertionError('save failure swallowed')
assert seen == ['second']
assert json.loads(config.config_file.read_text())['selected'] == 'second'
''')

    def test_original_daily_classes_refresh_options_after_sequence_commit(self):
        self.run_native(PREPARE + HOST + '''
assert isinstance(multi, MultiAccountDailyTask)
assert type(multi).__name__ == 'MultiAccountDailyTask'
assert type(daily).__name__ == 'DailyTask'
multi.config[CURRENT_SEQUENCE] = 'S1'
first = list(multi.config_type[CURRENT_ACCOUNT]['options'])
assert all(name in first for name in ('A1', 'A3', 'A4')), first
multi.config[CURRENT_ACCOUNT] = 'A1'
multi.config[CURRENT_SEQUENCE] = '序列2'
assert multi.config_type[CURRENT_ACCOUNT]['options'] == ['', '无序列']
assert multi.config[CURRENT_ACCOUNT] == ''
assert json.loads(multi.config.config_file.read_text())[CURRENT_SEQUENCE] == '序列2'
daily.config[PROFILE_SEQUENCE] = 'S1'
assert all(name in daily.config_type[DAILY_PROFILE]['options'] for name in ('A1', 'A3', 'A4'))
daily.config[PROFILE_SEQUENCE] = '序列2'
assert daily.config_type[DAILY_PROFILE]['options'] == ['（该序列暂无方案）']
from src.task.MultiAccountWeeklyGardenTask import MultiAccountWeeklyGardenTask
garden = multi.get_task_by_class(MultiAccountWeeklyGardenTask)
with patch.object(garden, '_refresh_garden_status', wraps=garden._refresh_garden_status) as refresh:
    daily._refresh_weekly_garden_consumers()
    refresh.assert_called_once()
assert any(event['event'] == 'task-config-changed' for event in events)
assert not device.actions
''')

    def test_identity_ocr_uses_raw_engine_and_failure_evidence_redacts(self):
        self.run_native(PREPARE + HOST + '''
import numpy as np
import cv2
from src.task.account_feature_verification import read_code, region
frame = np.full((1080, 1920, 3), 255, dtype=np.uint8)
engine.ocr.return_value = [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ('特征码：001234', .99)]]]
with patch.object(daily, 'ocr', side_effect=AssertionError('private crop reached textfix')), \
     patch.object(daily, 'screenshot', side_effect=AssertionError('private crop screenshot')):
    assert read_code(daily, frame) == '001234'
x, y, w, h = region(frame)
assert engine.ocr.call_args.args[0].shape == (h * 3, w * 3, 3)
assert not np.shares_memory(engine.ocr.call_args.args[0], frame)
engine.ocr.return_value[0][0][1] = ('特征码：001234', .79)
assert read_code(daily, frame) is None
from src.account_switch_evidence import AccountSwitchEvidenceSession
session = AccountSwitchEvidenceSession('A1', root=data_dir / 'okww监控室/account_switch_failures')
image = session._annotate(frame)
assert not image[y:y+h, x:x+w].any()
session.clicks.append({'window_point': [10, 10]})
with patch.object(cv2, 'circle', side_effect=RuntimeError('annotation failed')):
    image = session._annotate(frame, {'click_index': 0})
assert not image[y:y+h, x:x+w].any()
assert frame[y:y+h, x:x+w].all()
assert '001234' not in repr(events)
assert not device.actions
''')

    def test_daily_before_run_enforces_identity_then_binds_verified_profile(self):
        self.run_native(PREPARE + '''
from src.account_repository import ProfileEditScope
profile_id = next(iter(env.master['profiles']))
record = runtime.repository.load_profile(profile_id)
account = dict(record.account)
account['game_feature_code'] = '001234'
runtime.repository.publish_profile(ProfileEditScope(profile_id, record.revision),
                                   {'account': account, 'tasks': dict(record.tasks)})
''' + HOST + '''
from src.config_integrity import ConfigIntegrityBlocked
host.executor.current_task = daily
daily._enabled = True
multi.config[CURRENT_ACCOUNT] = '无序列'
try:
    daily.before_run()
except ConfigIntegrityBlocked:
    pass
else:
    raise AssertionError('Daily identity requirement bypassed for unregistered account')
engine.ocr.assert_not_called()
assert not device.actions
multi.config[CURRENT_SEQUENCE] = 'S1'
multi.config[CURRENT_ACCOUNT] = 'A1'
import cv2
import numpy as np
paths = []
# Production preparation/binding also read frames around the three identity samples.
for number in range(5):
    path = root / f'identity-{number}.png'
    assert cv2.imwrite(str(path), np.full((720, 1280, 3), number + 30, np.uint8))
    paths.append(path)
device.paths = iter(paths)
# Spy engine supplies text only; production freshness, raw crop, matching,
# binding and cleanup still execute. This is not a real OCR accuracy test.
engine.ocr.return_value = [[[[[0, 0], [1, 0], [1, 1], [0, 1]], ('特征码：001234', .99)]]]
with patch.object(daily, 'ocr', side_effect=AssertionError('identity reached normal OCR')), \
     patch.object(daily, 'screenshot', side_effect=AssertionError('private identity screenshot')):
    daily.before_run()
assert engine.ocr.call_count == 3
assert host.executor._account_feature_run.profile_id == profile_id
assert daily._verified_profile_id == profile_id
assert len(host.executor._account_feature_run.start.hashes) == 3
assert '001234' not in repr(events)
assert [action.kind for action in device.actions] == ['activate']
daily.after_run()
assert daily._verified_profile_id is None
''')

    def test_stopped_login_flow_never_starts_evidence_or_foreground_sampling(self):
        self.run_native(PREPARE + HOST + '''
from src.runtime.combat_api import TaskDisabledException
multi._enabled = True
host.context.stop.set()
with patch.object(multi, '_guard_account_transition', wraps=multi._guard_account_transition) as guard, \
     patch.object(multi, '_begin_account_switch_evidence') as evidence:
    try:
        multi.switch_to_account('A3')
    except TaskDisabledException:
        pass
    else:
        raise AssertionError('stopped login entry did not propagate cancellation')
    guard.assert_not_called()
    evidence.assert_not_called()
assert not device.actions
''')


if __name__ == '__main__':
    unittest.main()
