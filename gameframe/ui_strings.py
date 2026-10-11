"""Generic launcher labels that a package may localize in its configuration schema."""

LABELS = (
    'Package', 'Execution mode', 'Tasks', 'Task config JSON', '设备', '高级设备 JSON', '能力匹配',
    '启动 / 暂停 / 恢复热键', '系统托盘通知', '关闭窗口时最小化到托盘', '保存截图', '截图并识别文字',
    '打开资料目录', '选择本地资料根', '打开应用时恢复已保存辅助服务', '仅启动会话',
    '任务分类', '当前序列', '当前账号', '刷新账号上下文', '全部任务',
    'Start', 'Stop', 'Pause', 'Resume', 'Install gamepack', 'Update gamepack',
    'Disable selected service', 'Manage gamepack', 'Read-only overview', 'Refresh tasks',
    'Apply user task reload', 'Apply character code reload', 'Worker output',
    '显示窗口', '暂停 / 恢复', '退出', 'Run / enable task',
    '本次运行覆盖配置（长期设置在管理窗口保存）',
    '已核验运行账号：{account}',
    'Windows 用户：{user}\n资料根：{root}\n游戏包资料：{package_root}',
    '启动会话 / 暂停 / 恢复，保留服务启用设置。',
    '账号配置已更新；当前操作结束后请刷新账号上下文。',
    'Capture method', 'Input method',
    'Device backend', 'Windows HWND', 'MuMu SDK', 'Android ADB', 'Frame replay',
    'Visible window', 'HWND (decimal or 0x)', 'Launch command (one argument per line)',
    'Target executable (absolute path)', 'MuMu installation directory', 'Instance index',
    'MuMu SDK DLL path', 'Android package name (optional)', 'App index', 'ADB serial',
    'ADB executable path', 'Frame paths (one per line)', 'Refresh to list visible windows',
    'Refresh windows', 'Select a window or enter HWND below', 'Capabilities: {capabilities}',
    'Device options must be a JSON object with a type', 'Unknown device type: {kind}',
    '{field} must be an integer', '{field} cannot be negative', 'Window enumeration failed: {error}',
    '手动更新', '自动更新（正式版）', '自动更新（含预发布）', '更新策略', '检查更新',
    '下载完整环境并待下次启动应用', '重新尝试待应用更新',
    '登录后打开 GameFrame', '保存登录自启', '登录自启未保存：{error}',
    '登录启动项已更新，界面状态保存失败：{error}', '登录自启已保存',
    '当前游戏包没有完整环境更新入口。',
    '当前环境未受管理；可检查发布，完整更新须先迁入受管理环境。',
    '完整环境安装入口（请填入长期路径）：',
    '完整环境候选已保存，等待下一次正常启动。', '上次完整环境更新失败：',
    '上次更新未完成：{error}', '更新策略已保存；不会停止当前任务。',
    '手动更新：不会自动检查或下载。', '正在检查并准备完整环境…', '正在处理更新请求…',
    '完整环境更新失败：{error}', '检查完成，当前发行已是最新。',
    '已配置源尚未发布允许通道。', '检查到新发行，可下载完整环境。',
    '完整环境已下载并验证，待下一次正常启动应用。',
    '已允许重试待应用候选；下一次正常启动处理。',
    '独立游戏包更新源尚未配置，不会访问默认地址。', '已配置的更新源处于停用状态。',
    '完整更新须先迁入受管理环境，当前环境保持不变。',
    '当前为源码目录，请使用完整环境安装入口。',
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
