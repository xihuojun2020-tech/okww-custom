"""Generic launcher labels that a package may localize in its configuration schema."""

LABELS = (
    'Package', 'Execution mode', 'Tasks', 'Task config JSON', '设备', '高级设备 JSON', '能力匹配',
    '暂停 / 恢复热键', '系统托盘通知', '关闭窗口时最小化到托盘', '保存截图', '截图并识别文字',
    '打开资料目录', '选择本地资料根', '打开应用时恢复已保存辅助服务', '仅启动会话',
    '任务分类', '当前序列', '当前账号', '刷新账号上下文', '全部任务',
    'Start', 'Stop', 'Pause', 'Resume', 'Install gamepack', 'Update gamepack',
    'Disable selected service', 'Manage gamepack', 'Read-only overview', 'Refresh tasks',
    'Apply user task reload', 'Apply character code reload', 'Worker output',
    '显示窗口', '暂停 / 恢复', '退出', 'Run / enable task',
    '本次运行覆盖配置（长期设置在管理窗口保存）',
    '已核验运行账号：{account}',
    'Windows 用户：{user}\n资料根：{root}\n游戏包资料：{package_root}',
)


def apply_labels(window, labels):
    """Keep IDs, saved values and user content outside the display translation."""
    from PySide6.QtWidgets import QAbstractButton, QLabel
    from PySide6.QtGui import QAction
    for widget in (*window.findChildren(QAbstractButton), *window.findChildren(QLabel),
                   *window.findChildren(QAction)):
        original = widget.property('launcher_label')
        if original is None:
            original = widget.text()
            if original not in LABELS:
                continue
            widget.setProperty('launcher_label', original)
        # Pause and Start change state while the application is running.
        current = widget.text()
        if current in LABELS:
            original = current
            widget.setProperty('launcher_label', original)
        widget.setText(labels.get(original, original))
