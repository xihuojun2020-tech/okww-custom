"""Metadata-safe entrypoint for real production combat on the independent runtime."""

import json
import os
from pathlib import Path
import sys


class WutheringWavesNativePackage:
    def __init__(self):
        self.root = Path(__file__).resolve().parent
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        self.source = (self.root / self.manifest['source_root']).resolve()
        self.engine = None

    def _bind_source(self):
        source = str(self.source)
        if source not in sys.path:
            sys.path.insert(0, source)

    def prepare(self, task_id, data_dir):
        definition = self._definition(task_id)
        self._bind_source()
        from src.runtime.native_logging import configure_logging
        from src.runtime.native_diagnostics import start_native_diagnostics, record_native_event
        from src.runtime.account_runtime_bootstrap import prepare_native_account_runtime
        configure_logging(data_dir)
        start_native_diagnostics(data_dir, self.manifest['version'])
        try:
            prepare_native_account_runtime(data_dir, self.manifest['version'])
        except Exception as error:
            record_native_event('native_prepare', task=definition['class'], status='failed',
                                stage='account_preflight', error=error)
            raise

    def _definition(self, task_id):
        return next(task for task in self.manifest['tasks'] if task['id'] == task_id)

    def management_command(self, data_dir):
        import gameframe
        core = str(Path(gameframe.__file__).resolve().parent.parent)
        environment = os.environ.copy()
        environment['PYTHONPATH'] = os.pathsep.join(
            path for path in (str(self.source), core, environment.get('PYTHONPATH')) if path)
        return {'command': [sys.executable, '-m', 'gameframe.package_process',
                            '--package', str(self.root), '--expected-version', self.manifest['version'],
                            '--module', 'src.management', '--', '--data-dir', str(data_dir),
                            '--version', self.manifest['version'], '--package-root', str(self.root)],
                'cwd': str(self.source), 'env': environment}

    def run(self, task_id, context):
        return self._run(task_id, context, session=False)

    def close(self):
        self._bind_source()
        from src.evidence.service import close_existing_evidence_service
        from src.runtime.native_diagnostics import close_native_diagnostics
        try:
            close_existing_evidence_service()
        finally:
            close_native_diagnostics()

    def run_session(self, task_id, context):
        return self._run(task_id, context, session=True)

    def _run(self, task_id, context, *, session):
        definition = self._definition(task_id)
        self._bind_source()
        from src.runtime.native_logging import configure_logging
        from src.runtime.native_diagnostics import attach_native_executor, record_native_event
        from src.runtime.native_errors import TaskDisabledException
        from gameframe.api import Cancelled
        from src.runtime.native_combat_host import NativeCombatHost
        from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS

        data_dir = Path(context.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(data_dir)
        previous_cwd = Path.cwd()
        try:
            # The OCR dependency writes compiled model caches relative to cwd.
            # This worker owns its process; private writable data stays outside the pack.
            os.chdir(data_dir)
            if self.engine is None:
                from onnxocr.onnx_paddleocr import ONNXPaddleOcr
                self.engine = ONNXPaddleOcr(use_angle_cls=False, use_npu=False, use_openvino=True)
            host = NativeCombatHost(
                context, coco_path=self.source / 'assets/coco_annotations.json',
                global_options=COMBAT_GLOBAL_DEFAULTS, ocr_engine=self.engine,
                ocr_config={'default': {'lib': 'onnxocr'}},
                template_matching=TEMPLATE_MATCHING_DEFAULTS, native=True,
                window=getattr(context.device, 'window', None),
                task_entry=definition['module'] + ':' + definition['class'],
                registered_tasks=tuple(task['module'] + ':' + task['class']
                                       for task in self.manifest['tasks']),
                task_requirements={task['id']: frozenset(task['required_capabilities'])
                                   for task in self.manifest['tasks']},
                device_identity=type(context.device).__name__)
            attach_native_executor(host.executor)
            if session:
                return host.run_session(task_id)
            if definition['kind'] == 'service':
                return host.run_service()
            result = host.run_once()
            details = {'info': dict(host.task.info)}
            business_result = result if isinstance(result, dict) else getattr(host.task, 'last_result', None)
            if isinstance(business_result, dict):
                details['business_result'] = business_result
            return details
        except (TaskDisabledException, Cancelled) as error:
            record_native_event('native_task', task=definition['class'], status='stopped',
                                stage='execution', error=error)
            raise
        except Exception as error:
            record_native_event('native_task', task=definition['class'], status='failed',
                                stage='execution', error=error)
            raise
        finally:
            os.chdir(previous_cwd)


def create_package():
    return WutheringWavesNativePackage()
