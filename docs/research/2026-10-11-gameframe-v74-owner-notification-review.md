# v74 桌面通知输入所有者接线复核

日期：2026-10-11。范围是当前生产代码的 `native_combat_host`、`native_notification_hub`、`native_desktop_notifications` 和原生游戏包 `plugin._run`，以及新增的 `TestNativeNotificationOwnerIntegration.py`。本次没有启动游戏、调用 Win32/OLE、操作剪贴板、发送网络通知或访问 NAS。

## 结论与证据

后台服务的通知提交只进入队列。生产 `run_service` 安装的检查点发现队列时抛出 `SessionPreempted`，任务栈先退出，服务 `finally` 清除检查点并释放设备输入，下一轮循环才调用桌面所有者的 `drain_one`。新增测试直接运行这一调度路径；记录顺序为 `poll → unwind → release → release → send → release`。前后两次额外释放来自桌面交接本身。发送结果经真实 hub 的 Future 完成回调报告，而提交时没有成功事件。

前台一次性任务没有安装桌面队列抢占检查点。生产插件先等待 `run_once` 返回，再排空桌面队列。隔离子进程中的真实插件测试在 `run_once` 内提交通知，并断言队列仍待处理且尚未调用发送；随后验证 `foreground-unwind → send → http-close` 顺序。

暂停时 `drain_one` 在取出队列项目之前返回，因此项目仍待处理，也没有成功事件。停止后的 hub 关闭取消待处理 Future，发出 cancelled 结果，并关闭 HTTP 客户端。测试确认这两个过程均没有改变战斗 `enabled` 或配置 `_enabled=True`。

插件执行错误会传播原始异常；其 `finally` 关闭桌面/HTTP 实例、清空 `_notifications`、恢复事件接收器和工作目录。真实插件测试连续执行成功、失败、成功三次，确认三个桌面实例与三个 HTTP 客户端都关闭，失败运行没有发送，后续运行使用新实例。此次没有发现需要修改生产代码的已证实根因。

代码复核还确认会话循环在后台 poll 的 `finally` 清除检查点、释放输入并切回背景任务后，才到下一轮桌面排空；前台任务分支也先执行其收尾。服务和会话在暂停时等待，停止时退出，由插件关闭剩余队列。

## 验证

新增集成检查：`.\.venv\Scripts\python.exe -m unittest discover -s tests -p TestNativeNotificationOwnerIntegration.py`，3 项通过。

已有 HTTP/桌面通知离线测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'TestNative*Notifications.py'`，23 项通过。这些测试补充了桌面所有者线程、输入租约、OCR、窗口/剪贴板 fixture 和 HTTP fixture 的检查。

## 验证限度

后台集成测试直接使用生产调度器、hub 和桌面 dispatcher，但发送器与设备是离线替身。前台测试直接使用生产插件，host 替身只提供一次性执行和发送边界，因此验证的是插件接线及资源生命周期。实际会话循环顺序在此通过代码复核确认，没有新增重复完整会话 fixture。

本次不能证明真实 QQ/微信界面中的 OCR 成功率、PrintWindow/DPI、窗口焦点恢复、OLE 全格式剪贴板往返，或公网提供方实际送达。离线测试通过与实际消息发送成功是不同结论。
