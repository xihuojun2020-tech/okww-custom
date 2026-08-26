# PC 账号配置与序列管理参考文献

日期：2026-08-25

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
- OWASP Logging Cheat Sheet：日志与错误信息避免记录认证数据、会话令牌及敏感个人数据。<https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html>
- CWE-367（TOCTOU）：修订号/指纹检查用于防止预览后、保存前的外部修改被静默覆盖。<https://cwe.mitre.org/data/definitions/367.html>
