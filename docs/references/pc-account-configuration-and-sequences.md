# PC 账号配置与序列管理参考文献

日期：2026-08-25

## 2026-08-26 UI 重构补充

- `src/gui/CodexTheme.py`：固定浅色 palette/QSS，颜色值来自 `docs/superpowers/specs/2026-08-26-codex-light-ui-redesign.md`；主题初始化不订阅系统深色模式。
- `src/gui/SectionPanel.py` 与 `src/gui/FlatSettingRow.py`：使用 Qt Widgets 原生布局承载区块标题、说明、设置控件和错误状态，不新增第三方依赖。
- ALAS 的职责型左侧入口和单页分区信息架构仍是界面参考；本项目只借鉴布局组织，不复制其任务实现。<https://github.com/LmeSzinc/AzurLaneAutoScript>
- Qt for Python `QPalette`、`QApplication.setStyleSheet` 和 Widgets 布局文档是浅色主题与平铺控件实现依据。<https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPalette.html>

### 2026-08-26 配置页面宽度修复补充

- `QScrollArea.takeWidget()`：将自定义页内容从原滚动区解除后再挂载到分区面板，避免旧滚动区继续控制内容几何尺寸。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QScrollArea.html#PySide6.QtWidgets.QScrollArea.takeWidget>
- `QSizePolicy.Expanding`：配置区块和表单容器采用水平扩展策略，使用父级布局提供的可用宽度。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSizePolicy.html>

### 2026-08-26 凝素领域名称补充

- `src/task/DailyTask.py` 的 `FORGERY_DOMAIN_OPTIONS` 使用 `(整数值, 显示名)` 对，借鉴 Qt 下拉模型“显示文本与内部数据分离”的做法；账号 JSON 继续保存整数，不影响旧配置和传送索引。
- `src/gui/LabelAndIntegerDropDown.py`：自定义 ok-script 配置控件负责显示名称、反向映射整数和保留异常旧值；工厂类型由 `custom_ok/ok/gui/tasks/ConfigItemFactory.py` 注册。
- Qt for Python `QComboBox` 文档：显示文本与当前索引的标准下拉交互。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QComboBox.html>

## 本地设计来源

- `E:\AI work\better wuwa\src\account_identity.py`：身份候选、精确短名和歧义拒绝的早期实现；本项目仅吸收纯 PC 解析思想。
- `E:\AI work\better wuwa\src\account_config_editor.py`：独立草稿、差异预览、CAS 保存和保存前备份设计。
- `E:\AI work\better wuwa\src\gui\AccountConfigTab.py`：单账号编辑页面的信息组织参考。
- `E:\AI work\better wuwa\src\sequence_repository.py`：序列草稿、修订检查和不可变快照参考；设备绑定相关逻辑未移植。
- `E:\AI work\better wuwa\src\gui\SequenceManagementTab.py`：序列 CRUD 与重排交互参考。
- 当前仓库 `src/config_integrity.py`、`src/account_config_bundle.py`、`src/account_repository.py`、`src/task/MultiAccountDailyTask.py` 和 `src/task/TestAccountSwitchTask.py`：权威数据、原子发布、运行状态及生产切换边界。
- 当前仓库 `custom_ok/ok/gui/MainWindow.py`、`ok.gui.widget.Tab` 与 `SettingTab`：五栏导航接线、连续滚动页和底部程序设置的既有组件边界。
- 当前仓库 `i18n/zh_CN/LC_MESSAGES/ok.po`：账号配置页的副本、材料和梦魇目标采用其中既有简体中文术语；持久化键和值不做本地化。

封存项目中的 Android、MuMu、ADB、Combat Agent、设备控制台、安装与心跳代码不属于本次来源，也未导入。

## 外部参考

- Azur Lane Auto Script（ALAS）项目：左侧按职责收敛入口、在一个设置页面组织相关配置分区的界面信息架构参考；本项目未复制其业务代码。<https://github.com/LmeSzinc/AzurLaneAutoScript>
- Python 3 文档，`copy`：深拷贝用于隔离编辑草稿与运行快照。<https://docs.python.org/3/library/copy.html>
- Python 3 文档，`types.MappingProxyType`：只读映射用于阻止运行期修改冻结快照。<https://docs.python.org/3/library/types.html#types.MappingProxyType>
- Python 3 文档，`uuid`：为每次运行生成独立 `run_id`。<https://docs.python.org/3/library/uuid.html>
- Python 3 文档，`tempfile` 与 `os.replace`：现有原子写入和事务回滚实现所依据的同卷临时文件/替换语义。<https://docs.python.org/3/library/tempfile.html>、<https://docs.python.org/3/library/os.html#os.replace>
- Qt for Python 文档，Widgets：自定义页使用的输入、列表、确认对话框和信号槽。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/index.html>
- Qt for Python 文档，`QMessageBox`：账号与序列删除二次确认及标准按钮返回值。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QMessageBox.html>
- Qt for Python 文档，`QComboBox` 与 `QWheelEvent`：下拉菜单选择及忽略滚轮事件、交由父级滚动区域处理的行为依据。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QComboBox.html>、<https://doc.qt.io/qtforpython-6/PySide6/QtGui/QWheelEvent.html>
- GNU gettext 文档：界面翻译与程序内部稳定标识分离的本地化原则。<https://www.gnu.org/software/gettext/manual/gettext.html>
- Microsoft Windows 文档，`WScript.Shell.CreateShortcut`：本机 `.lnk` 快捷方式的目标、参数、工作目录和图标属性。<https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/scripting-articles/cc364547(v=vs.85)>
- 运行目录约定：`E:\game\okww owener` 是推送后的打包版，`E:\AI work\ok-wuthering-waves-master` 是开发版；本次账号配置包的权威来源是打包版内 `data\apps\okww-custom\working`，导出前通过 `ConfigIntegrityService.check`，导出后通过 `preflight_import` 校验。
- `src/gui/AccountConfigTab.py` 与 `src/gui/SequenceManagementTab.py`：账号删除、序列删除和序列成员重排的界面对象边界；按钮文案必须明确当前操作对象。
- `src/account_repository.py` 的 `publish_profile`：账号任务配置和所属序列在同一个候选 master 中提交，保持 CAS 修订检查与配置包原子发布。
- OWASP Logging Cheat Sheet：日志与错误信息避免记录认证数据、会话令牌及敏感个人数据。<https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html>
- CWE-367（TOCTOU）：修订号/指纹检查用于防止预览后、保存前的外部修改被静默覆盖。<https://cwe.mitre.org/data/definitions/367.html>

## 2026-08-30 多账号启动恢复补充

- 正式切换入口在账号下拉框不可见时以 `in_team()[0]` 作为只读游戏世界兜底；仅在结果明确为真时退登，未知状态继续等待并保留证据。
- `TaskRunCoordinator` 的 `FAILED` 与 `STOPPED` 均允许下一轮 `start()`；多账号任务必须在异常、停止和正常出口显式结束状态。
- Python `try` 语句文档：任务异常边界使用 `except`/`else` 保留原异常并完成生命周期收尾。<https://docs.python.org/3/reference/compound_stmts.html#the-try-statement>
- Python `pathlib` 文档：备份校验按完整路径区分根 `manifest.json` 与发布 bundle 的嵌套同名文件。<https://docs.python.org/3/library/pathlib.html>
## 2026-08-26：任务联动读取与日志降噪

- 账号设置与任务模块共享 `AccountRepository` 的最新投影，避免完整性服务启动快照导致新序列/成员变更需重启才生效。
- 任务页仅过滤窗口尺寸内部诊断消息，保留原始文件日志，参考 ok-script 的窗口捕获日志行为。
