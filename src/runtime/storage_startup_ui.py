"""Minimal migration window; no application singleton or vision initialization."""
import threading
import queue


def prepare_storage(repo):
    from src.runtime.storage_bootstrap import bootstrap, configure_process_storage, read_json, SCHEMA
    from src.runtime.storage_handoff import quiesce_uploaders
    from pathlib import Path
    current = read_json(Path(repo) / 'configs/runtime_storage.json', {})
    if current.get('schema') == SCHEMA and Path(current['root']).anchor.casefold() == Path(repo).anchor.casefold():
        value = bootstrap(repo)
        configure_process_storage(value)
        return value
    # Qt is used only for this small dialog, before importing ok/config.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton
    owned_app = QApplication.instance() is None
    app = QApplication.instance() or QApplication([])
    stop = threading.Event()
    class MigrationDialog(QDialog):
        def reject(self):
            stop.set()
            label.setText('正在安全结束当前迁移步骤，资料会保留供下次继续。')
    dialog = MigrationDialog()
    dialog.setWindowTitle('OK-WW · 运行数据迁移')
    dialog.resize(560, 180)
    layout = QVBoxLayout(dialog)
    location = QLabel(f'安装位置：{repo}\n运行资料将保存到此安装盘。')
    location.setWordWrap(True)
    layout.addWidget(location)
    label = QLabel('正在检查旧数据并迁移到程序安装盘。首次启动可能需要较长时间。')
    label.setWordWrap(True)
    layout.addWidget(label)
    cancel = QPushButton('安全退出，下次启动继续')
    layout.addWidget(cancel)
    updates = queue.Queue(maxsize=1)
    result = {}
    def progress(message):
        if stop.is_set(): raise InterruptedError('用户退出，下次启动继续迁移')
        try: updates.get_nowait()
        except queue.Empty: pass
        updates.put_nowait(message)
    def work():
        try: result['value'] = bootstrap(repo, progress=progress, quiesce=quiesce_uploaders)
        except BaseException as error: result['error'] = error
        finally: result['done'] = True
    worker = threading.Thread(target=work, name='StorageMigration')
    worker.start()
    cancel.clicked.connect(stop.set)
    def poll():
        try: label.setText(updates.get_nowait())
        except queue.Empty: pass
        if result.get('done'): dialog.accept()
    timer = QTimer(dialog)
    timer.timeout.connect(poll)
    timer.start(100)
    dialog.exec()
    stop.set()
    worker.join()
    if owned_app:
        from shiboken6 import delete
        delete(dialog)
        delete(app)
    if 'error' in result: raise result['error']
    configure_process_storage(result['value'])
    return result['value']
