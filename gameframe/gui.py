"""Small desktop launcher; package selection reads manifest metadata only."""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from gameframe.controller import Controller
from gameframe.packages import discover, install_archive


class GameFrameWindow(QWidget):
    def __init__(self, packages_dir: Path | str, data_dir: Path | str, *, controller=None):
        super().__init__()
        self.setWindowTitle("GameFrame")
        self.resize(760, 680)
        self.packages_dir = Path(packages_dir)
        self.data_dir = Path(data_dir)
        self.packages = discover(self.packages_dir)
        self.controller = controller if controller is not None else Controller()
        self.process = None
        self._events = queue.Queue()
        self._reader = None
        self._start_thread = None
        self._install_thread = None
        self._starting = False
        self._installing = False
        self._stopping = False
        self._closing = False
        self._cleanup_done = False

        self.package_select = QComboBox()
        for manifest in self.packages:
            self.package_select.addItem(f"{manifest.title}  {manifest.version}")
        self.task_list = QListWidget()
        self.mode_label = QLabel()
        self.config_edit = QPlainTextEdit()
        self.device_edit = QPlainTextEdit()
        self.device_edit.setPlainText('{"type": "replay", "frames": []}')
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.status_label = QLabel("Ready")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.install_button = QPushButton("Install gamepack")
        self.stop_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("Package", self.package_select)
        form.addRow("Execution mode", self.mode_label)
        form.addRow("Tasks", self.task_list)
        form.addRow("Task config JSON", self.config_edit)
        form.addRow("Device JSON", self.device_edit)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.install_button)
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
        self.install_button.clicked.connect(self.install_selected)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start(50)
        self._select_package(0)

    def _manifest(self):
        index = self.package_select.currentIndex()
        return self.packages[index] if index >= 0 else None

    def _select_package(self, index):
        manifest = self._manifest()
        self.task_list.clear()
        if manifest is None:
            self.mode_label.setText("No installed packages")
            self.start_button.setEnabled(False)
            return
        legacy = manifest.execution == "legacy-application"
        self.mode_label.setText(
            "Compatibility: original application, dependencies and production configuration"
            if legacy else "Native GameFrame worker")
        self.config_edit.setEnabled(not legacy)
        self.device_edit.setEnabled(not legacy)
        if legacy:
            self.config_edit.setPlainText("Production application configuration is used; this editor does not apply.")
            self.device_edit.setPlainText("Production application device selection is used; this editor does not apply.")
        else:
            self.device_edit.setPlainText('{"type": "replay", "frames": []}')
        for task in manifest.tasks:
            self.task_list.addItem(f"{task.title}  [{task.kind}]  ({task.id})")
        if manifest.tasks:
            self.task_list.setCurrentRow(0)
        self.start_button.setEnabled(bool(manifest.tasks) and self.process is None
                                     and not self._starting and not self._installing and not self._closing)

    def _select_task(self, row):
        manifest = self._manifest()
        if manifest is not None and 0 <= row < len(manifest.tasks) and manifest.execution == "native":
            self.config_edit.setPlainText(json.dumps(manifest.tasks[row].default_config,
                                                      ensure_ascii=False, indent=2))

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
        if (manifest is None or row < 0 or self.process is not None
                or self._starting or self._installing or self._closing):
            return
        task = manifest.tasks[row]
        try:
            config, device = self._native_options() if manifest.execution == "native" else (None, None)
        except Exception as error:
            self._error(error)
            return
        self.output.clear()
        self._starting = True
        self.status_label.setText(f"Starting {manifest.id}/{task.id} ({manifest.execution})")
        self.start_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self._start_thread = threading.Thread(target=self._start_worker,
                                              args=(manifest, task.id, config, device), daemon=True)
        self._start_thread.start()

    def _start_worker(self, manifest, task_id, config, device):
        try:
            process = self.controller.start(manifest, task_id, data_dir=self.data_dir,
                                            config=config, device=device)
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
        if self.process is not None or self._starting or self._installing or self._closing:
            return
        filename, _filter = QFileDialog.getOpenFileName(
            self, "Install gamepack", "", "Gamepack ZIP (*.zip)")
        if not filename:
            return
        self._installing = True
        self.start_button.setEnabled(False)
        self.install_button.setEnabled(False)
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

    def stop_selected(self):
        if self.process is None or self._stopping:
            return
        self._stopping = True
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping worker…")
        threading.Thread(target=self._stop_worker, daemon=True).start()

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
            if kind == "line":
                self.output.appendPlainText(value)
            elif kind == "started":
                manifest, task_id, process = value
                self._starting = False
                self.process = process
                self.status_label.setText(f"Running {manifest.id}/{task_id} ({manifest.execution})")
                self.stop_button.setEnabled(not self._closing)
                self.install_button.setEnabled(False)
                self._reader = threading.Thread(target=self._read_output, args=(process,), daemon=True)
                self._reader.start()
            elif kind == "start-error":
                self._starting = False
                self._error(value)
                self.start_button.setEnabled(not self._closing and self.task_list.currentRow() >= 0)
                self.install_button.setEnabled(not self._closing)
            elif kind == "exit":
                self.status_label.setText(f"Worker exited with code {value}")
                self.process = None
                self.start_button.setEnabled(not self._closing and not self._starting
                                             and self.task_list.currentRow() >= 0)
                self.stop_button.setEnabled(False)
                self.install_button.setEnabled(not self._closing and not self._installing)
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
        self.install_button.setEnabled(False)
        self.status_label.setText("Closing worker…")
        threading.Thread(target=self._close_worker, daemon=True).start()

    def _close_worker(self):
        try:
            if self._start_thread is not None:
                self._start_thread.join()
            if self._install_thread is not None:
                self._install_thread.join()
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
