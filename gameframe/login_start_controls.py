# SPDX-License-Identifier: MIT
"""GUI insertion candidate; constructor never imports winreg or registers an entry."""
from PySide6.QtWidgets import QCheckBox, QPushButton

from gameframe.login_start import configure_login_start
from gameframe.managed_login_start import configure_managed_login_start


def attach_login_start(window, form, *, launch_argv=None, installation_root=None, managed_root=None):
    window.login_start = QCheckBox('登录后打开 GameFrame')
    window.login_start.setChecked(window._launcher_context.get('login_start', False))
    window.login_start_save = QPushButton('保存登录自启')
    form.addRow(window.login_start, window.login_start_save)

    def save():
        previous = window._launcher_context.get('login_start', False)
        try:
            if managed_root is not None:
                command = configure_managed_login_start(window.login_start.isChecked(), managed_root)
            else:
                command = configure_login_start(window.login_start.isChecked(), launch_argv,
                                                installation_root=installation_root)
        except (OSError, ValueError, TypeError) as error:
            window.login_start.setChecked(previous)
            template = '登录自启未保存：{error}'
            window.status_label.setText(window._launcher_labels.get(template, template).format(error=error))
            return
        window._launcher_context['login_start'] = command is not None
        try:
            window._save_launcher_context()
        except OSError as error:
            template = '登录启动项已更新，界面状态保存失败：{error}'
            window.status_label.setText(window._launcher_labels.get(template, template).format(error=error))
            return
        text = '登录自启已保存'
        window.status_label.setText(window._launcher_labels.get(text, text))

    window.login_start_save.clicked.connect(save)
