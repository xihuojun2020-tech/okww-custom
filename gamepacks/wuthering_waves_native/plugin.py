"""Metadata-safe entrypoint for real production combat on the independent runtime."""

import json
import logging
import os
from pathlib import Path
import sys


class WutheringWavesNativePackage:
    def __init__(self):
        self.root = Path(__file__).resolve().parent
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        self.source = (self.root / self.manifest['source_root']).resolve()
        self.engine = None
        self._live_writer = None
        self._notifications = None

    def _bind_source(self):
        source = str(self.source)
        if source not in sys.path:
            sys.path.insert(0, source)

    def prepare_data(self, data_dir):
        self._bind_source()
        from src.native_maintenance import prepare_native_data
        return prepare_native_data(data_dir, self.manifest['version'])

    def prepare(self, task_id, data_dir):
        definition = self._definition(task_id, data_dir)
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

    def _definition(self, task_id, data_dir=None):
        if task_id is None:
            return {'class': 'Session', 'kind': 'session'}
        for task in self.manifest['tasks']:
            if task['id'] == task_id:
                return task
        self._bind_source()
        from src.runtime.native_user_tasks import NativeUserTaskStore
        for task in NativeUserTaskStore(data_dir).list():
            if task['id'] == task_id:
                return {**task, 'class': task['class_name']}
        raise ValueError(f'Unknown native task: {task_id}')

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

    def overview_command(self, data_dir):
        launch = self.management_command(data_dir)
        launch['command'][launch['command'].index('src.management')] = 'src.native_overview'
        return launch

    def configuration_command(self, data_dir):
        launch = self.management_command(data_dir)
        launch['command'] = [sys.executable, '-m', 'gameframe.package_process',
                            '--package', str(self.root), '--expected-version', self.manifest['version'],
                            '--module', 'src.runtime.native_configuration', '--',
                            '--data-dir', str(data_dir), '--version', self.manifest['version'],
                            '--manifest', str(self.root / 'manifest.json')]
        return launch

    def close(self):
        self._bind_source()
        from src.evidence.service import close_existing_evidence_service
        from src.runtime.native_diagnostics import close_native_diagnostics
        try:
            if self._notifications is not None:
                self._notifications.close()
                self._notifications = None
        finally:
            try:
                close_existing_evidence_service()
            finally:
                try:
                    close_native_diagnostics()
                finally:
                    if self._live_writer is not None:
                        self._live_writer.close()
                        self._live_writer = None

    def run_session(self, task_id, context):
        return self._run(task_id, context, session=True)

    def _run(self, task_id, context, *, session):
        definition = self._definition(task_id, context.data_dir)
        self._bind_source()
        from src.runtime import combat_api
        combat_api.configure(native=True, data_dir=context.data_dir)
        from src.runtime.native_logging import configure_logging
        from src.runtime.native_diagnostics import attach_native_executor, record_native_event
        from src.runtime.native_errors import TaskDisabledException
        from gameframe.api import Cancelled
        from src.runtime.native_combat_host import NativeCombatHost
        from src.runtime.native_live_status import NativeLiveWriter
        from src.runtime.native_user_tasks import NativeUserTaskStore
        from src.runtime.native_language import LANGUAGE_DEFAULTS, create_language_config, load_language
        from src.runtime.native_program_preferences import DEFAULTS, NAME, NativeProgramPreferences
        from src.combat.settings import COMBAT_GLOBAL_DEFAULTS, TEMPLATE_MATCHING_DEFAULTS

        data_dir = Path(context.data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        configure_logging(data_dir)
        create_language_config(data_dir)
        language = load_language(data_dir, pack_root=self.root)
        preferences = NativeProgramPreferences(data_dir)
        from src.runtime.native_notifications import NativeNotificationPreferences, NativeNotifications
        from src.runtime.native_notification_hub import NativeNotificationHub
        notification_preferences = NativeNotificationPreferences(data_dir)
        user_store = NativeUserTaskStore(data_dir)
        user_tasks = user_store.load_tasks()
        user = next((item for item in user_tasks if item['id'] == task_id), None)
        if user is not None:
            if user['revision'] != context.task_definition.revision:
                raise ValueError('User task definition changed before execution; start it again')
            definition = {**user, 'class': user['class_name']}
        task_entry = (user['task_class'] if user is not None else
                      'src.task.AutoCombatTask:AutoCombatTask' if task_id is None else
                      definition['module'] + ':' + definition['class'])
        writer = NativeLiveWriter(context, self.manifest['id'], self.manifest['version'])
        self._live_writer = writer
        previous_events = context.events
        def observe_event(event):
            try:
                writer.observe_event(event)
            except Exception:
                logging.getLogger(__name__).exception('Unable to observe native execution status')
            finally:
                previous_events(event)
        context.events = observe_event
        previous_cwd = Path.cwd()
        try:
            # The OCR dependency writes compiled model caches relative to cwd.
            # This worker owns its process; private writable data stays outside the pack.
            os.chdir(data_dir)
            if self.engine is None:
                from src.vision.native_ocr_factory import create_ocr
                self.engine = create_ocr(preferences.config)
            host = NativeCombatHost(
                context, coco_path=self.source / 'assets/coco_annotations.json',
                global_options={**COMBAT_GLOBAL_DEFAULTS, NAME: DEFAULTS, 'Language': LANGUAGE_DEFAULTS,
                                notification_preferences.config.config_file.stem: notification_preferences.config.default},
                ocr_engine=self.engine, translate=language.translate,
                ocr_config={'default': {'lib': 'onnxocr'}},
                template_matching=TEMPLATE_MATCHING_DEFAULTS, native=True,
                window=getattr(context.device, 'window', None),
                task_entry=task_entry,
                registered_tasks=tuple(task['module'] + ':' + task['class']
                                       for task in self.manifest['tasks']),
                task_requirements={task['id']: frozenset(task['required_capabilities'])
                                   for task in self.manifest['tasks']},
                device_identity=type(context.device).__name__, live_status=writer,
                user_tasks=user_tasks, program_preferences=preferences.config)
            host.task_metadata = {task['id']: task for task in self.manifest['tasks']}
            host.program_preferences = host.global_configs[NAME]
            from src.runtime.native_desktop_notifications import create_owner_desktop_notifications
            notification_config = host.global_configs[notification_preferences.config.config_file.stem]
            self._notifications = NativeNotificationHub(context, NativeNotifications(
                notification_config), desktop=create_owner_desktop_notifications(
                    context, self.engine, notification_config))
            host.notifications = self._notifications
            configure_preferences = getattr(context.device, 'configure_preferences', None)
            if configure_preferences is not None:
                configure_preferences(host.program_preferences, **self.manifest['window_preferences'])
            host.applied_revision = user_store.revision
            attach_native_executor(host.executor)
            if session:
                return host.run_session(task_id)
            if definition['kind'] == 'service':
                return host.run_service()
            result = host.run_once()
            while host.drain_desktop_notification():
                pass
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
            try:
                if self._notifications is not None:
                    self._notifications.close()
                    self._notifications = None
            finally:
                context.events = previous_events
                os.chdir(previous_cwd)


def create_package():
    return WutheringWavesNativePackage()
