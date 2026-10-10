"""Small desktop launcher; package selection reads manifest metadata only."""

from __future__ import annotations

import json
import hashlib
import queue
import threading
import zipfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from gameframe.controller import Controller
from gameframe.packages import discover, install_archive
from gameframe.launcher_options import load_options, save_options
from gameframe.package_updates import apply_update, prepare_update, recover_updates


class GameFrameWindow(QWidget):
    def __init__(self, packages_dir: Path | str, data_dir: Path | str, *, controller=None):
        super().__init__()
        self.setWindowTitle("GameFrame")
        self.resize(760, 680)
        self.packages_dir = Path(packages_dir)
        self.data_dir = Path(data_dir)
        self.controller = controller if controller is not None else Controller()
        self.management_controller = Controller()
        self.overview_controller = Controller()
        self._overview_thread = None
        self._overview_starting = False
        recover_updates(self.packages_dir, ensure_idle=self._assert_owners_idle)
        self.packages = discover(self.packages_dir)
        self._management_thread = None
        self._management_process = None
        self._managing = False
        self.process = None
        self._events = queue.Queue()
        self._reader = None
        self._start_thread = None
        self._install_thread = None
        self._starting = False
        self._installing = False
        self._updating = False
        self._update_thread = None
        self._pending_update = None
        self._update_management_error = None
        self._stopping = False
        self._closing = False
        self._cleanup_done = False
        self._paused = False
        self._exit_requested = False

        self.package_select = QComboBox()
        for manifest in self.packages:
            self.package_select.addItem(f"{manifest.title}  {manifest.version}")
        self.task_list = QListWidget()
        self._visible_tasks = ()
        self.mode_label = QLabel()
        self.config_edit = QPlainTextEdit()
        self.config_label = QLabel('Task config JSON')
        self.device_edit = QPlainTextEdit()
        self.device_edit.setPlainText('{"type": "replay", "frames": []}')
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.status_label = QLabel("Ready")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.install_button = QPushButton("Install gamepack")
        self.update_button = QPushButton('Update gamepack')
        self.disable_button = QPushButton('Disable selected service')
        self.disable_button.setEnabled(False)
        self.manage_button = QPushButton('Manage gamepack')
        self.overview_button = QPushButton('Read-only overview')
        self.refresh_tasks_button = QPushButton('Refresh tasks')
        self.reload_tasks_button = QPushButton('Apply user task reload')
        self.reload_tasks_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Package", self.package_select)
        form.addRow("Execution mode", self.mode_label)
        form.addRow("Tasks", self.task_list)
        form.addRow(self.config_label, self.config_edit)
        form.addRow("Device JSON", self.device_edit)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.update_button)
        buttons.addWidget(self.disable_button)
        buttons.addWidget(self.manage_button)
        buttons.addWidget(self.overview_button)
        buttons.addWidget(self.refresh_tasks_button)
        buttons.addWidget(self.reload_tasks_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Worker output"))
        layout.addWidget(self.output)

        self.package_select.currentIndexChanged.connect(self._select_package)
        self.task_list.currentRowChanged.connect(self._select_task)
        self.start_button.clicked.connect(self.start_selected)
        self.stop_button.clicked.connect(self.stop_selected)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.install_button.clicked.connect(self.install_selected)
        self.update_button.clicked.connect(self.update_selected)
        self.disable_button.clicked.connect(self.disable_selected)
        self.manage_button.clicked.connect(self.manage_selected)
        self.overview_button.clicked.connect(self.overview_selected)
        self.refresh_tasks_button.clicked.connect(self.refresh_tasks)
        self.reload_tasks_button.clicked.connect(self.reload_user_tasks)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start(50)
        self._select_package(0)

    def _manifest(self):
        index = self.package_select.currentIndex()
        return self.packages[index] if index >= 0 else None

    def _select_package(self, index):
        manifest = self._manifest()
        self.overview_button.setEnabled(manifest is not None and manifest.overview
                                        and not self._closing and not self._updating
                                        and not self._installing and not self._overview_starting
                                        and (self.overview_controller.process is None
                                             or self.overview_controller.process.poll() is not None))
        self._visible_tasks = ()
        self.task_list.clear()
        if manifest is None:
            self.mode_label.setText("No installed packages")
            self.start_button.setEnabled(False)
            self.manage_button.setEnabled(False)
            self.update_button.setEnabled(False)
            return
        try:
            self._visible_tasks = tuple(task for task in manifest.available_tasks(self.data_dir / manifest.id)
                                        if task.visible)
        except (OSError, ValueError) as error:
            self.start_button.setEnabled(False)
            self.disable_button.setEnabled(False)
            self.config_edit.clear()
            self._error(error)
            return
        legacy = manifest.execution == "legacy-application"
        self.manage_button.setEnabled(manifest.management and self.process is None and not self._managing
                                      and not self._starting and not self._installing and not self._closing
                                      and not self._updating)
        self.update_button.setEnabled(self.process is None and not self._managing and not self._starting
                                      and not self._stopping and not self._installing and not self._closing
                                      and not self._updating and self._is_installed(manifest))
        self.mode_label.setText(
            "Compatibility: original application, dependencies and production configuration"
            if legacy else "Native GameFrame worker")
        self.config_edit.setEnabled(not legacy)
        self.config_label.setText('本次运行覆盖配置（长期设置在管理窗口保存）'
                                  if self._managed_config(manifest) else 'Task config JSON')
        self.device_edit.setEnabled(not legacy)
        if legacy:
            self.config_edit.setPlainText("Production application configuration is used; this editor does not apply.")
            self.device_edit.setPlainText("Production application device selection is used; this editor does not apply.")
        else:
            options = load_options(self.data_dir / manifest.id / 'launcher.json')
            self.device_edit.setPlainText(json.dumps(options['device'], ensure_ascii=False, indent=2))
        for task in self._visible_tasks:
            self.task_list.addItem(f"{task.title}  [{task.kind}]  ({task.id})")
        if self._visible_tasks:
            row = next((i for i, task in enumerate(self._visible_tasks)
                        if not legacy and task.id == options.get('selected_task')), 0)
            self.task_list.setCurrentRow(row)
        self.start_button.setEnabled(bool(self._visible_tasks) and self.process is None
                                     and not self._starting and not self._installing and not self._closing
                                     and not self._managing and not self._updating)

    def refresh_tasks(self):
        manifest = self._manifest()
        if manifest is None:
            return
        row = self.task_list.currentRow()
        selected = self._visible_tasks[row].id if 0 <= row < len(self._visible_tasks) else None
        try:
            tasks = tuple(task for task in manifest.available_tasks(self.data_dir / manifest.id) if task.visible)
        except Exception as error:
            self._error(error)
            return
        self._visible_tasks = tasks
        self.task_list.clear()
        for task in tasks:
            self.task_list.addItem(f'{task.title}  [{task.kind}]  ({task.id})')
        if tasks:
            self.task_list.setCurrentRow(next((index for index, task in enumerate(tasks) if task.id == selected), 0))

    def reload_user_tasks(self):
        if self.process is None or self._stopping or self._closing or self._updating:
            return
        try:
            self.controller.request_user_task_reload()
        except Exception as error:
            self._error(error)
        else:
            self.status_label.setText('User task reload requested; waiting for the execution owner')

    def _select_task(self, row):
        manifest = self._manifest()
        if manifest is not None and 0 <= row < len(self._visible_tasks) and manifest.execution == "native":
            task = self._visible_tasks[row]
            options = load_options(self.data_dir / manifest.id / 'launcher.json')
            config = {} if self._managed_config(manifest) else options['tasks'].get(task.id, task.default_config)
            self.config_edit.setPlainText(json.dumps(config,
                                                      ensure_ascii=False, indent=2))
            self.disable_button.setEnabled(self.process is not None and manifest.supports_session
                                           and task.kind == 'service' and not self._stopping)

    def _managed_config(self, manifest):
        return manifest.execution == 'native' and manifest.supports_session and manifest.management

    def _native_options(self):
        config = json.loads(self.config_edit.toPlainText())
        device = json.loads(self.device_edit.toPlainText())
        if not isinstance(config, dict) or not isinstance(device, dict) or "type" not in device:
            raise ValueError("Native config and device must be JSON objects; device needs a type")
        return config, device

    def _error(self, error):
        message = f"{type(error).__name__}: {error}"
        self.status_label.setText(message)
        self.output.appendPlainText(message)

    def start_selected(self):
        manifest = self._manifest()
        row = self.task_list.currentRow()
        if (manifest is None or row < 0
                or self._starting or self._installing or self._closing or self._managing or self._updating
                or (self.process is not None and not manifest.supports_session)):
            return
        task = self._visible_tasks[row]
        try:
            config, device = self._native_options() if manifest.execution == "native" else (None, None)
            if manifest.execution == 'native':
                path = self.data_dir / manifest.id / 'launcher.json'
                options = load_options(path)
                if self._managed_config(manifest):
                    options['tasks'] = {}
                else:
                    options['tasks'][task.id] = config
                options['device'] = device
                options['selected_task'] = task.id
                save_options(path, options)
            if self.process is not None:
                if not manifest.supports_session or self._stopping:
                    return
                if task.kind == 'service':
                    self.controller.set_service(task.id, True, config)
                else:
                    self.controller.request_task(task.id, config)
                self.status_label.setText(f'Requested {task.title}')
                return
        except Exception as error:
            self._error(error)
            return
        self.output.clear()
        self._exit_requested = False
        self._starting = True
        self.package_select.setEnabled(False)
        self.status_label.setText(f"Starting {manifest.id}/{task.id} ({manifest.execution})")
        self.start_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self._start_thread = threading.Thread(target=self._start_worker,
                                              args=(manifest, task.id, config, device), daemon=True)
        self._start_thread.start()

    def _start_worker(self, manifest, task_id, config, device):
        try:
            process = self.controller.start(manifest, task_id, data_dir=self.data_dir / manifest.id,
                                            config=config, device=device,
                                            session=manifest.supports_session)
        except Exception as error:
            self._events.put(("start-error", error))
        else:
            self._events.put(("started", (manifest, task_id, process)))

    def _read_output(self, process):
        try:
            for line in process.stdout:
                self._events.put(("line", line.rstrip("\r\n")))
            self._events.put(("exit", process.wait()))
        except Exception as error:
            self._events.put(("error", error))

    def install_selected(self):
        if (self.process is not None or self._starting or self._installing or self._closing
                or self._managing or self._stopping or self._updating):
            return
        filename, _filter = QFileDialog.getOpenFileName(
            self, "Install gamepack", "", "Gamepack ZIP (*.zip)")
        if not filename:
            return
        self._installing = True
        self.start_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.status_label.setText("Installing gamepack…")
        self._install_thread = threading.Thread(target=self._install_worker,
                                                args=(filename,), daemon=True)
        self._install_thread.start()

    def _install_worker(self, filename):
        try:
            manifest = install_archive(filename, self.packages_dir)
        except Exception as error:
            self._events.put(("install-error", error))
        else:
            self._events.put(("install-done", manifest.id))

    def _assert_owners_idle(self):
        self.controller.assert_idle()
        self.management_controller.assert_idle()
        self.overview_controller.assert_idle()

    def _assert_update_idle(self):
        if self._starting or self._stopping or self._managing or self._installing:
            raise RuntimeError('A package owner or installation is still active')
        self._assert_owners_idle()

    def _is_installed(self, manifest):
        return (manifest.root == self.packages_dir.resolve() / manifest.id
                and (manifest.root / 'files.json').is_file())

    def update_selected(self):
        if (self.process is not None or self._starting or self._stopping or self._managing
                or self._installing or self._updating or self._closing):
            return
        manifest = self._manifest()
        if manifest is None:
            return
        if not self._is_installed(manifest):
            self._error(ValueError('Only installed indexed gamepacks can be updated; source checkouts are excluded'))
            return
        filename, _filter = QFileDialog.getOpenFileName(self, 'Update gamepack', '', 'Gamepack ZIP (*.zip)')
        if filename:
            self._start_update_prepare({'archive': str(Path(filename).resolve()), 'package_id': manifest.id,
                                        'current_version': manifest.version})

    def _start_update_prepare(self, request):
        manifest = self._manifest()
        if self._updating or self._closing:
            raise RuntimeError('A package update or application close is already in progress')
        if manifest is None or not self._is_installed(manifest):
            raise ValueError('Only installed indexed gamepacks can be updated; source checkouts are excluded')
        if request['package_id'] != manifest.id or request['current_version'] != manifest.version:
            raise ValueError('Update request does not match the selected installed package')
        self._updating = True
        self.overview_button.setEnabled(False)
        self._update_management_error = None
        self.package_select.setEnabled(False)
        self.start_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.status_label.setText('Verifying gamepack update…')
        self._update_thread = threading.Thread(target=self._prepare_update_worker, args=(request,), daemon=True)
        self._update_thread.start()

    def _prepare_update_worker(self, request):
        try:
            if self._overview_thread is not None:
                self._overview_thread.join()
            self.overview_controller.close()
            self.overview_controller.assert_idle()
            archive = Path(request['archive'])
            if not archive.is_absolute():
                raise ValueError('Update archive must be an absolute path')
            if 'sha256' in request:
                with archive.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if archive.stat().st_size != request['size'] or digest != request['sha256']:
                    raise ValueError('Update archive does not match its published SHA256/size')
            target = request.get('target_version')
            if target is None:
                with zipfile.ZipFile(archive) as bundle:
                    names = [name for name in bundle.namelist()
                             if len(name.split('/')) == 2 and name.endswith('/manifest.json')]
                    if len(names) != 1:
                        raise ValueError('A gamepack ZIP must contain one package manifest')
                    target = json.loads(bundle.read(names[0]))['version']
            plan = prepare_update(archive, self.packages_dir, package_id=request['package_id'],
                                  current_version=request['current_version'], target_version=target)
        except Exception as error:
            self._events.put(('update-error', error))
        else:
            self._events.put(('update-prepared', plan))

    def overview_selected(self):
        manifest = self._manifest()
        if (manifest is None or not manifest.overview or self._closing or self._updating
                or self._installing or self._overview_starting):
            return
        self._overview_starting = True
        self.overview_button.setEnabled(False)
        self._overview_thread = threading.Thread(target=self._overview_worker, args=(manifest,), daemon=True)
        self._overview_thread.start()

    def _overview_worker(self, manifest):
        try:
            process = self.overview_controller.start_overview(manifest, data_dir=self.data_dir / manifest.id)
        except Exception as error:
            self._events.put(('overview-error', error))
        else:
            self._events.put(('overview-started', process))
            threading.Thread(target=self._read_overview_output, args=(process,), daemon=True).start()

    def _read_overview_output(self, process):
        try:
            for line in process.stdout:
                self._events.put(('overview-line', line.rstrip()))
            self._events.put(('overview-exit', process.wait()))
        except Exception as error:
            self._events.put(('overview-error', error))

    def _management_update_status(self, line):
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            return
        if isinstance(request, dict) and request.get('event') == 'gamepack-update-ready':
            try:
                # A management request always includes the verified release envelope.
                for field in ('archive', 'package_id', 'current_version', 'target_version', 'sha256', 'size'):
                    request[field]
                self._start_update_prepare(request)
            except Exception as error:
                self._error(error)

    def _apply_pending_update(self):
        if (self._pending_update is None or self._closing or self._managing
                or self._starting or self._stopping or self._installing):
            return
        if self._update_management_error is not None:
            self._finish_update(error=self._update_management_error)
            return
        try:
            self._assert_update_idle()
        except Exception as error:
            self._finish_update(error=error)
            return
        self.status_label.setText('Applying gamepack update…')
        plan = self._pending_update
        self._pending_update = None
        self._update_thread = threading.Thread(target=self._apply_update_worker, args=(plan,), daemon=True)
        self._update_thread.start()

    def _apply_update_worker(self, plan):
        try:
            manifest = apply_update(plan, ensure_idle=self._assert_update_idle)
        except Exception as error:
            self._events.put(('update-error', error))
        else:
            self._events.put(('update-done', manifest.id))

    def _finish_update(self, *, package_id=None, error=None):
        self._updating = False
        self._pending_update = None
        self.package_select.setEnabled(not self._closing and not self._managing)
        if package_id is not None:
            self._reload_packages(package_id)
            self.status_label.setText(f'Updated {package_id}')
        else:
            self._select_package(self.package_select.currentIndex())
            self._error(error)
        self.install_button.setEnabled(not self._closing and not self._managing and self.process is None)

    def _reload_packages(self, selected_id):
        self.packages = discover(self.packages_dir)
        self.package_select.blockSignals(True)
        try:
            self.package_select.clear()
            for manifest in self.packages:
                self.package_select.addItem(f"{manifest.title}  {manifest.version}")
            index = next(i for i, manifest in enumerate(self.packages) if manifest.id == selected_id)
            self.package_select.setCurrentIndex(index)
        finally:
            self.package_select.blockSignals(False)
        self._select_package(index)

    def manage_selected(self):
        manifest = self._manifest()
        if (manifest is None or not manifest.management or self.process is not None
                or self._starting or self._installing or self._closing or self._managing or self._updating):
            return
        self._managing = True
        self.start_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.package_select.setEnabled(False)
        self._management_thread = threading.Thread(target=self._manage_worker,
                                                   args=(manifest,), daemon=True)
        self._management_thread.start()

    def _manage_worker(self, manifest):
        try:
            process = self.management_controller.start_management(
                manifest, data_dir=self.data_dir / manifest.id)
        except Exception as error:
            self._events.put(('management-error', error))
        else:
            self._events.put(('management-started', process))

    def _read_management_output(self, process):
        try:
            for line in process.stdout:
                self._events.put(('management-line', line.rstrip('\r\n')))
            self._events.put(('management-exit', process.wait()))
        except Exception as error:
            self._events.put(('management-error', error))

    def stop_selected(self):
        if self.process is None or self._stopping:
            return
        self._stopping = True
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.disable_button.setEnabled(False)
        self.status_label.setText("Stopping worker…")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def disable_selected(self):
        manifest = self._manifest()
        row = self.task_list.currentRow()
        if self.process is None or self._stopping or self._closing or row < 0:
            return
        task = self._visible_tasks[row]
        if manifest.supports_session and task.kind == 'service':
            try:
                self.controller.set_service(task.id, False)
            except Exception as error:
                self._error(error)
            else:
                self.status_label.setText(f'Disable requested: {task.title}')

    def toggle_pause(self):
        if self.process is None or self._stopping or self._closing:
            return
        try:
            if self._paused:
                self.controller.resume()
            else:
                self.controller.pause()
        except Exception as error:
            self._error(error)
        else:
            self.pause_button.setEnabled(False)
            self.status_label.setText('Resume requested' if self._paused else 'Pause requested')

    def _pause_status(self, line):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return  # Worker output also includes human-readable dependency logs.
        if isinstance(event, dict) and event.get('event') == 'task-paused':
            self._paused = event['paused']
            self.pause_button.setText('Resume' if self._paused else 'Pause')
            self.pause_button.setEnabled(self.process is not None and not self._stopping and not self._closing)
            self.status_label.setText('Paused' if self._paused else 'Running')
        elif isinstance(event, dict) and event.get('event') == 'finished':
            result = event.get('result', {})
            self._exit_requested = bool(result.get('exit_requested')
                                        or result.get('business_result', {}).get('exit_requested'))
        elif isinstance(event, dict) and event.get('event') == 'session-task-finished':
            self.status_label.setText(f'Finished {event["task_id"]}')
        elif isinstance(event, dict) and event.get('event') == 'session-task-failed':
            self.status_label.setText(f'{event.get("task_id")}: {event["error"]}')
        elif isinstance(event, dict) and event.get('event') == 'user-tasks-reloaded':
            self.refresh_tasks()
            self.status_label.setText('User tasks applied: ' + str(event['applied_revision']))

    def _stop_worker(self):
        try:
            self.controller.stop()
        except Exception as error:
            self._events.put(("error", error))
        finally:
            self._events.put(("stop-done", None))

    def _drain_events(self):
        while True:
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == 'overview-started':
                self._overview_starting = False
            elif kind == 'overview-line':
                self.output.appendPlainText(value)
            elif kind in ('overview-exit', 'overview-error'):
                self._overview_starting = False
                manifest = self._manifest()
                self.overview_button.setEnabled(manifest is not None and manifest.overview
                                                and not self._closing and not self._updating and not self._installing)
                if kind == 'overview-error':
                    self._error(value)
                elif value != 0:
                    self._error(RuntimeError(f'Read-only overview exited with code {value}'))
            elif kind == "line":
                self.output.appendPlainText(value)
                self._pause_status(value)
            elif kind == 'management-line':
                self.output.appendPlainText(value)
                self._management_update_status(value)
            elif kind == 'management-started':
                self._management_process = value
                self.status_label.setText('Management running')
                threading.Thread(target=self._read_management_output,
                                 args=(value,), daemon=True).start()
            elif kind in {'management-exit', 'management-error'}:
                self._managing = False
                self._management_process = None
                self.package_select.setEnabled(not self._closing and not self._updating)
                self._select_package(self.package_select.currentIndex())
                self.install_button.setEnabled(not self._closing and not self._updating)
                if kind == 'management-error':
                    if self._updating:
                        self._update_management_error = value
                        self._apply_pending_update()
                    self._error(value)
                else:
                    self.status_label.setText(f'Management exited with code {value}')
                    if self._updating:
                        if value == 0:
                            self._apply_pending_update()
                        else:
                            self._update_management_error = RuntimeError('Management did not exit successfully before update')
                            self._apply_pending_update()
            elif kind == "started":
                manifest, task_id, process = value
                self._starting = False
                self.process = process
                self.package_select.setEnabled(False)
                self.device_edit.setEnabled(False)
                self.status_label.setText(f"Running {manifest.id}/{task_id} ({manifest.execution})")
                self.stop_button.setEnabled(not self._closing)
                self._paused = False
                self.pause_button.setText('Pause')
                self.pause_button.setEnabled(manifest.execution == 'native' and not self._closing)
                self.install_button.setEnabled(False)
                self.update_button.setEnabled(False)
                self.start_button.setEnabled(manifest.supports_session and not self._closing)
                self.start_button.setText('Run / enable task' if manifest.supports_session else 'Start')
                self.disable_button.setEnabled(manifest.supports_session
                                               and manifest.task(task_id).kind == 'service'
                                               and not self._closing)
                self._reader = threading.Thread(target=self._read_output, args=(process,), daemon=True)
                self._reader.start()
            elif kind == "start-error":
                self._starting = False
                self.package_select.setEnabled(not self._closing)
                self._error(value)
                self.start_button.setEnabled(not self._closing and self.task_list.currentRow() >= 0)
                self.install_button.setEnabled(not self._closing)
                self.manage_button.setEnabled(self._manifest().management and not self._closing)
                self.update_button.setEnabled(not self._closing and self._is_installed(self._manifest()))
            elif kind == "exit":
                self.status_label.setText(f"Worker exited with code {value}")
                self.process = None
                self.package_select.setEnabled(not self._closing and not self._updating)
                self.device_edit.setEnabled(self._manifest().execution == 'native' and not self._closing)
                self.start_button.setText('Start')
                self.disable_button.setEnabled(False)
                self.start_button.setEnabled(not self._closing and not self._starting and not self._updating
                                             and self.task_list.currentRow() >= 0)
                self.stop_button.setEnabled(False)
                self.pause_button.setEnabled(False)
                self.install_button.setEnabled(not self._closing and not self._installing and not self._updating)
                self.manage_button.setEnabled(self._manifest().management and not self._closing and not self._updating)
                self.update_button.setEnabled(not self._closing and not self._updating
                                              and self._is_installed(self._manifest()))
                if value == 0 and self._exit_requested:
                    self.close()
            elif kind == "install-done":
                self._installing = False
                self._reload_packages(value)
                self.status_label.setText(f"Installed {value}")
                self.install_button.setEnabled(not self._closing)
            elif kind == "install-error":
                self._installing = False
                self._error(value)
                self.start_button.setEnabled(not self._closing and self.task_list.currentRow() >= 0)
                self.install_button.setEnabled(not self._closing)
                self.manage_button.setEnabled(self._manifest().management and not self._closing)
                self.update_button.setEnabled(not self._closing and self._is_installed(self._manifest()))
            elif kind == 'update-prepared':
                if self._updating:
                    self._pending_update = value
                    self.status_label.setText('Gamepack verified; waiting for owned processes to exit')
                    self._apply_pending_update()
            elif kind == 'update-done':
                self._finish_update(package_id=value)
            elif kind == 'update-error':
                self._finish_update(error=value)
            elif kind == "stop-done":
                self._stopping = False
                self.stop_button.setEnabled(self.process is not None and not self._closing)
            elif kind == "cleanup-done":
                self._cleanup_done = True
                self.close()
            elif kind == "cleanup-error":
                self._closing = False
                self.start_button.setEnabled(self.process is None and self.task_list.currentRow() >= 0)
                self.stop_button.setEnabled(self.process is not None)
                self.install_button.setEnabled(self.process is None and not self._installing)
                self._error(value)
            elif kind == "error":
                self._error(value)
        manifest = self._manifest()
        self.reload_tasks_button.setEnabled(manifest is not None and manifest.task_catalog is not None
                                            and self.process is not None and self.controller.session
                                            and not self._stopping and not self._closing and not self._updating)

    def closeEvent(self, event):
        if self._cleanup_done:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.disable_button.setEnabled(False)
        self.manage_button.setEnabled(False)
        self.status_label.setText("Closing worker…")
        self.overview_button.setEnabled(False)
        threading.Thread(target=self._close_worker, daemon=True).start()

    def _close_worker(self):
        try:
            if self._start_thread is not None:
                self._start_thread.join()
            if self._install_thread is not None:
                self._install_thread.join()
            if self._update_thread is not None:
                self._update_thread.join()
            if self._management_thread is not None:
                self._management_thread.join()
            self.management_controller.close()
            if self._overview_thread is not None:
                self._overview_thread.join()
            self.overview_controller.close()
            self.overview_controller.assert_idle()
            self.controller.close()
        except Exception as error:
            self._events.put(("cleanup-error", error))
        else:
            self._events.put(("cleanup-done", None))


def run_gui(packages_dir: Path | str, data_dir: Path | str) -> int:
    app = QApplication.instance() or QApplication([])
    window = GameFrameWindow(packages_dir, data_dir)
    window.show()
    return app.exec()
