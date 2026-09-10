# 局域网自动日志与错误截图

自 1.54.00 起，程序每秒滚动缓存游戏画面；发生 ERROR/未处理异常时，保存错误前 10 秒、当时和后 5 秒的画面，并使用既有 SMB 上传器发送。普通日志按约 2 秒周期封装，不等待错误。

## 两端分工

当前电脑开发、测试并发布主程序，提供接收共享；另一台电脑更新程序后配置发送目标、测试和回传证据，不再承担程序开发。

- [异机 AI 更新配置与验收文档](../superpowers/specs/2026-09-10-remote-ai-diagnostic-requirements.md)
- [详细设计](../superpowers/specs/2026-09-10-lan-error-evidence-design.md)

## 接收端准备

建立专用 Windows 共享文件夹（例如本地 `E:\OKWW-Diagnostics`，共享名 `OKWW-Diagnostics`），只允许指定 Windows 账号读写、改名和删除该目录里的文件。共享权限和 NTFS 权限都要允许；防火墙仅开放可信 LAN 的 SMB。

将实际 UNC 路径 `\\接收电脑\OKWW-Diagnostics` 和账号名交给发送端。密码由用户在发送端输入；Windows Hello PIN 通常不能当共享密码。接收端 IP 建议做 DHCP 保留。程序原来的 NAS 默认目标不会自动变为当前电脑。

## 发送端操作

“工具 → 日志与诊断”：填写共享路径、账号和密码，保存设置，先点击“测试共享连接”。进入游戏并成功捕获画面 12 秒后，点击“测试错误截图”，保持游戏可捕获 5 秒，等待上传。

测试截图按钮不改变任务结果、不执行游戏输入。采集状态会说明缓存数量、画面未更新和磁盘不足等情况；成功上传不等于采集窗口完整。

命令行可选检查（在实际程序源码根目录运行）：

```powershell
.\.venv\Scripts\python.exe -m src.runtime.diagnostic_uploader --probe --target '\\接收电脑\OKWW-Diagnostics'
.\.venv\Scripts\python.exe -m src.runtime.diagnostic_uploader --status
```

接收端可在对应源码根目录运行下列命令，验证完成批次并更新事件聚合视图：

```powershell
.\.venv\Scripts\python.exe -m src.runtime.diagnostic_reader 'E:\OKWW-Diagnostics'
```

图片和日志仍位于共享目录的“待分析/截图”“待分析/日志”；聚合结果位于“事件索引”。`state` 表示采集完整性，`delivery_state` 表示引用图片是否全部验证，`needs_analysis` 不代表已完成根因分析。

## 可靠性与保留

网络恢复后自动补传，退避最长约 15 分钟加调度间隔，也可手动重试。计划任务仅在当前 Windows 用户已登录时工作。

无新画面、初始化不足 10 秒、退出中断、容量超限均会如实标记缺图。连续错误合并，窗口最多 30 秒。截图上限约为 4K、单图 16 MiB、单事件 128 MiB；待传超过 2 GiB 或磁盘剩余不足 2 GiB 时暂停新诊断图片。

截图按用户授权传输游戏画面，可能包含 UID、昵称等。文本脱敏不会自动遮挡图片内容。

保持既有“每周清理已上传超过 7 天日志”的规则，同时清理事件摘要副本；截图和不含日志内容的图片关联保留。不会用账号切换专用清理器删除通用错误截图。
