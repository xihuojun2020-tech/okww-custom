# PC 账号配置与序列管理参考文献

日期：2026-08-25

## 本地设计来源

- `E:\AI work\better wuwa\src\account_identity.py`：身份候选、精确短名和歧义拒绝的早期实现；本项目仅吸收纯 PC 解析思想。
- `E:\AI work\better wuwa\src\account_config_editor.py`：独立草稿、差异预览、CAS 保存和保存前备份设计。
- `E:\AI work\better wuwa\src\gui\AccountConfigTab.py`：单账号编辑页面的信息组织参考。
- `E:\AI work\better wuwa\src\sequence_repository.py`：序列草稿、修订检查和不可变快照参考；设备绑定相关逻辑未移植。
- `E:\AI work\better wuwa\src\gui\SequenceManagementTab.py`：序列 CRUD 与重排交互参考。
- 当前仓库 `src/config_integrity.py`、`src/account_config_bundle.py`、`src/account_repository.py`、`src/task/MultiAccountDailyTask.py` 和 `src/task/TestAccountSwitchTask.py`：权威数据、原子发布、运行状态及生产切换边界。

封存项目中的 Android、MuMu、ADB、Combat Agent、设备控制台、安装与心跳代码不属于本次来源，也未导入。

## 外部参考

- Python 3 文档，`copy`：深拷贝用于隔离编辑草稿与运行快照。<https://docs.python.org/3/library/copy.html>
- Python 3 文档，`types.MappingProxyType`：只读映射用于阻止运行期修改冻结快照。<https://docs.python.org/3/library/types.html#types.MappingProxyType>
- Python 3 文档，`uuid`：为每次运行生成独立 `run_id`。<https://docs.python.org/3/library/uuid.html>
- Python 3 文档，`tempfile` 与 `os.replace`：现有原子写入和事务回滚实现所依据的同卷临时文件/替换语义。<https://docs.python.org/3/library/tempfile.html>、<https://docs.python.org/3/library/os.html#os.replace>
- Qt for Python 文档，Widgets：自定义页使用的输入、列表、确认对话框和信号槽。<https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/index.html>
- OWASP Logging Cheat Sheet：日志与错误信息避免记录认证数据、会话令牌及敏感个人数据。<https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html>
- CWE-367（TOCTOU）：修订号/指纹检查用于防止预览后、保存前的外部修改被静默覆盖。<https://cwe.mitre.org/data/definitions/367.html>
