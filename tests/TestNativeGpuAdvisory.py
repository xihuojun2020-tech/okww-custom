"""Pinned vendor and advisory fixtures; no real GPU, process, file or DLL queries."""

import ctypes
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
from src.runtime.vendor import gpu_driver_settings as vendor
from src.runtime import native_gpu_advisory as advisory

def forbidden(*args, **kwargs):
    raise AssertionError('Real GPU/DLL/process/overlay file access is forbidden')

Feature = vendor.GpuDriverPostProcessing


class FakeDevice:
    capabilities = frozenset({'frames', 'keyboard', 'desktop-handoff'})

    def __init__(self):
        self.window = SimpleNamespace(hwnd=42, _pid=123, _process_created=12.5)
        self.valid = True
        self.identity_checks = 0

    def _check_target_identity(self):
        self.identity_checks += 1
        if not self.valid:
            raise RuntimeError('Selected HWND/process identity changed')


class TestNativeGpuAdvisory(unittest.TestCase):
    def setUp(self):
        for name in ('WinDLL', 'CDLL'):
            guard=patch.object(ctypes,name,side_effect=forbidden)
            guard.start()
            self.addCleanup(guard.stop)

    def fixture(self, report):
        device, emit = FakeDevice(), Mock()
        process = Mock(create_time=Mock(return_value=12.5), exe=Mock(return_value='E:/game/Client.exe'))
        detector = Mock(return_value=report)
        instance = advisory.NativeGpuAdvisory(detector=detector, process_factory=Mock(return_value=process))
        return instance, device, emit, process, detector

    def test_enabled_features_warn_once_and_use_trusted_existing_target(self):
        enabled = Feature('NVIDIA', 'Image Sharpening', True, 'fixture setting=1')
        instance, device, emit, process, detector = self.fixture({'enabled': [enabled], 'checks': [enabled]})
        translations = {'GPU Driver Warning': 'GPU 驱动警告',
                        'Image Sharpening': '图像锐化',
                        '{vendor} {feature} is enabled and may cause malfunctions!': '{vendor} {feature} 已启用，可能影响自动化。'}
        result = instance.check(device, emit, lambda text: translations.get(text, text))
        self.assertEqual(result['status'], 'warning')
        self.assertTrue(result['notify'])
        self.assertEqual(result['message'], 'NVIDIA 图像锐化 已启用，可能影响自动化。')
        self.assertEqual(result['title'], 'GPU 驱动警告')
        detector.assert_called_once_with('E:/game/Client.exe', 42)
        instance.process_factory.assert_called_once_with(123)
        process.exe.assert_called_once()
        self.assertEqual(device.identity_checks, 2)
        self.assertIsNone(instance.check(device, emit))
        emit.assert_called_once_with(result)

    def test_unknown_optional_checks_never_claim_disabled_or_notify_success(self):
        missing = Feature('AMD', 'Radeon Image Sharpening', None, 'ADLX unavailable')
        instance, device, emit, _, _ = self.fixture({'enabled': [], 'checks': [missing]})
        result = instance.check(device, emit)
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['checks'][0]['enabled'])
        self.assertFalse(result['notify'])
        self.assertIn('unknown', result['message'])
        self.assertEqual(result['features'], [])

    def test_explicit_false_observations_report_no_detected_effects(self):
        off = Feature('AMD', 'Radeon Image Sharpening', False)
        instance, device, emit, _, _ = self.fixture({'enabled': [], 'checks': [off]})
        result = instance.check(device, emit)
        self.assertEqual(result['status'], 'checked')
        self.assertFalse(result['checks'][0]['enabled'])

    def test_non_windows_device_skips_without_process_or_detector_queries(self):
        instance, _, emit, _, detector = self.fixture({'enabled': [], 'checks': []})
        device = SimpleNamespace(capabilities=frozenset({'frames', 'keyboard', 'mouse'}))
        result = instance.check(device, emit)
        self.assertEqual(result['status'], 'skipped')
        detector.assert_not_called()
        instance.process_factory.assert_not_called()

    def test_identity_reuse_and_query_failure_report_unknown_without_detection(self):
        for failure in ('hwnd', 'created', 'changed-during-exe', 'process-query'):
            with self.subTest(failure=failure), patch.object(advisory, 'logger') as logger:
                instance, device, emit, process, detector = self.fixture({'enabled': [], 'checks': []})
                if failure == 'hwnd':
                    device.valid = False
                elif failure == 'created':
                    process.create_time.return_value = 13.0
                elif failure == 'changed-during-exe':
                    def replaced():
                        device.valid = False
                        return 'E:/game/Other.exe'
                    process.exe.side_effect = replaced
                else:
                    process.exe.side_effect = PermissionError('process exe query denied')
                result = instance.check(device, emit)
                self.assertEqual(result['status'], 'unknown')
                self.assertIn(result['failure'], ('RuntimeError', 'PermissionError'))
                detector.assert_not_called()
                logger.error.assert_called_once()
                emit.assert_called_once_with(result)

    def test_detector_failure_reports_unknown_and_does_not_abort_task_startup(self):
        instance, device, emit, _, detector = self.fixture({})
        detector.side_effect = OSError('GPU API unavailable')
        with patch.object(advisory, 'logger') as logger:
            result = instance.check(device, emit)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['failure'], 'OSError')
        logger.error.assert_called_once()
        self.assertIsNone(instance.check(device, emit))

    def test_observer_failure_is_reported_without_aborting_startup(self):
        instance, device, emit, _, _ = self.fixture({'enabled': [], 'checks': []})
        emit.side_effect = BrokenPipeError('fixture observer unavailable')
        with patch.object(advisory, 'logger') as logger:
            result = instance.check(device, emit)
        self.assertEqual(result['status'], 'checked')
        logger.error.assert_called_once()

    def test_vendor_optional_nvapi_adlx_and_hdr_unknowns_are_preserved(self):
        with patch.object(vendor, '_NvApi', side_effect=vendor.NvApiUnavailable('fixture NVAPI missing')), \
             patch.object(vendor, '_read_nv_drs_db_values', return_value=[]), \
             patch.object(vendor, '_nvidia_filter_profile_in_use_state', return_value=(None, 'fixture log unavailable')), \
             patch.object(vendor, '_monitor_device_name_from_hwnd', return_value=''), \
             patch.object(vendor, '_query_active_display_paths', side_effect=forbidden), \
             patch.object(vendor.importlib.util, 'find_spec', return_value=None), \
             patch.object(vendor, '_NVAPI_INIT_UNAVAILABLE_MESSAGE', None), \
             patch.object(vendor, '_NVAPI_INIT_UNAVAILABLE_LOGGED', False), \
             patch.object(vendor, 'logger') as logger:
            report = vendor.get_gpu_driver_post_processing_report('E:/game/Client.exe', 42)
        self.assertEqual(report['enabled'], [])
        self.assertEqual(len(report['checks']), 6)
        self.assertTrue(all(result.enabled is None for result in report['checks']))
        self.assertFalse(any('enabled: False' in str(call) for call in logger.info.call_args_list))

    def test_vendor_filter_and_hdr_prerequisites_skip_only_from_observed_false(self):
        with patch.object(vendor, 'is_windows_hdr_enabled', return_value=Feature('Windows', 'HDR', False)), \
             patch.object(vendor, '_nvidia_filter_profile_in_use_state', return_value=(False, 'slot=0 fixture')), \
             patch.object(vendor, 'is_nvidia_image_sharpening_enabled', return_value=None), \
             patch.object(vendor, 'is_amd_image_sharpening_enabled', return_value=Feature('AMD', 'Radeon Image Sharpening', False)), \
             patch.object(vendor, 'is_nvidia_rtx_dynamic_vibrance_enabled', side_effect=forbidden), \
             patch.object(vendor, 'is_nvidia_rtx_hdr_enabled', side_effect=forbidden):
            report = vendor.get_gpu_driver_post_processing_report('E:/game/Client.exe', 42)
        states = {result.feature: result.enabled for result in report['checks']}
        self.assertFalse(states['RTX HDR'])
        self.assertFalse(states['RTX Dynamic Vibrance'])
        self.assertIsNone(states['Image Sharpening'])
        self.assertEqual(report['enabled'], [])

    def test_vendor_enabled_drs_and_target_overlay_fixture_match(self):
        with patch.object(vendor, '_scan_nvapi_profiles', return_value=[('Global Profile', 0x00598928, 1, 'Sharpening')]), \
             patch.object(vendor, '_read_nv_drs_db_values', side_effect=forbidden):
            result = vendor.is_nvidia_image_sharpening_enabled()
        self.assertTrue(result.enabled)
        self.assertEqual(result.feature, 'Image Sharpening')
        target = r'E:\game\Client.exe'
        text = target + '\nGameFilter applyslot index: 2'
        slot, detail = vendor._nvidia_filter_profile_slot_from_text(text, target, 'fixture')
        self.assertEqual(slot, 2)
        self.assertIn('source=fixture:2', detail)
        self.assertIsNone(vendor._nvidia_filter_profile_slot_from_text(text, r'E:\game\Other.exe')[0])

    def test_temporary_installation_import_is_headless_and_does_not_query_gpu(self):
        with tempfile.TemporaryDirectory(prefix='gameframe-v75-gpu-') as temporary:
            root = Path(temporary)
            for name in ('src/__init__.py', 'src/runtime/__init__.py', 'src/runtime/native_logging.py'):
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, destination)
            shutil.copy2(ROOT / 'src/runtime/native_gpu_advisory.py', root / 'src/runtime/native_gpu_advisory.py')
            shutil.copytree(ROOT / 'src/runtime/vendor', root / 'src/runtime/vendor',
                            ignore=shutil.ignore_patterns('__pycache__'))
            code = '''import ctypes, sys
from types import SimpleNamespace
def forbidden(*args, **kwargs): raise AssertionError('No real DLL load')
ctypes.CDLL = ctypes.WinDLL = forbidden
from src.runtime.native_gpu_advisory import NativeGpuAdvisory
from src.runtime.vendor.gpu_driver_settings import get_gpu_driver_post_processing_report
events=[]
result=NativeGpuAdvisory(detector=forbidden,process_factory=forbidden).check(
    SimpleNamespace(capabilities=frozenset()),events.append)
assert result['status']=='skipped' and len(events)==1
assert not any(name.split('.')[0] in ('ok','PySide6','qfluentwidgets','ADLXPybind') for name in sys.modules)
print('installed advisory passed')
'''
            result = subprocess.run([sys.executable, '-c', code], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('installed advisory passed', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
