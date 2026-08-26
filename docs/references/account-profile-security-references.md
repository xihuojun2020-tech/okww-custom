# 账号配置安全参考资料

本项目采用的实现原则与以下公开资料一致；资料用于设计校验与后续维护，不代表项目依赖这些网站运行。

1. Python `os.replace`：同一文件系统内进行原子替换，是发布 `active.json` 指针和配置文件写入的基础。
   - https://docs.python.org/3/library/os.html#os.replace
2. Python `hashlib.sha256`：用于 bundle 文件清单和 revision 内容寻址。
   - https://docs.python.org/3/library/hashlib.html#hashlib.sha256
3. RFC 4122 / RFC 9562 UUID：账号文件名使用 UUID，显示名和手机号变化不会改变文件归属。
   - https://www.rfc-editor.org/rfc/rfc4122
   - https://www.rfc-editor.org/rfc/rfc9562
4. OWASP Authentication Cheat Sheet：身份识别失败、歧义和认证状态不明确时应拒绝继续，而不是猜测。
   - https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
5. OWASP Logging Cheat Sheet：日志应避免凭据泄露；配置包导出会对密码、令牌、Cookie 和鉴权字段脱敏，但保留账号切换所需的带星号手机号。
   - https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
6. Alas（碧蓝航线脚本）公开的配置分组思路：用户配置与程序设置分离、按账号/任务组织可编辑项。本项目只吸收组织方式，不复制其运行代码或账号数据。
   - https://github.com/LmeSzinc/AzurLaneAutoScript
7. OWASP Authorization Cheat Sheet：高风险身份变更应使用独立边界、显式确认、最小权限和可审计记录；本项目将身份重绑定与普通任务编辑分离，并在发布前执行修订号 CAS。
   - https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html
8. Microsoft Data Protection API（DPAPI）：绑定当前 Windows 用户/计算机的本机数据保护接口；本项目在不可用时进入安全错误，不把敏感备份降级为明文。
   - https://learn.microsoft.com/en-us/windows/win32/api/dpapi/

9. Qt `QScrollArea.takeWidget()` 与 `QSizePolicy.Expanding`：重新嵌入设置页内容时先解除旧滚动区所有权，再让分区布局接管水平尺寸，避免尺寸提示造成不可用空间。
   - https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QScrollArea.html#PySide6.QtWidgets.QScrollArea.takeWidget
   - https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSizePolicy.html
