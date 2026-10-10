# 原生通知及剩余入口实施计划

目标：接通原魔改版真实通知渠道，保留共享输入所有权；补齐管理退出刷新、窗口状态保存和无会话热键启动。用户已授权全部功能迁移且要求不提问，按既有架构实施。

1. `native_notifications.py` 以公开 HTTP API 实现 Discord、Telegram、企业微信及 QQ 频道；只接收明确提供的 PNG，返回逐渠道真实 HTTP/API 结果，关闭取消排队并等待当前请求。不因通知失败关闭战斗服务。
2. 执行 plugin 和 configuration host 使用同一 Native Notifications 持久配置；metadata 响应不含凭据，Qt 字段为空密码输入、显示已配置状态、明确保存/清除。诊断出口遮盖旧/新通知凭据与目的地址。
3. `NativeCombatHost` 在生产 notification 和 notify 日志调用点投递一次；截图只用当前缓存/调用方图像并复用身份遮罩，不为通知额外捕获。HTTP worker 不发送系统输入，完成结果通过原事件出口报告。
4. 桌面 QQ/微信由 shared owner 的安全边界执行。background checkpoint 只让出当前栈，队列在下一轮 owner 边界处理；前台任务/全局暂停期间等待，停止取消。保留 Runtime 输入锁、跨进程租约和服务开关。目标 HWND/PID/create-time、输入释放、窗口恢复及完整剪贴板保留须有真实 API 契约与 fixture，不能把未实现值展示成已送达。
5. GUI 独立任务修管理退出刷新，复用 Qt 保存/恢复 geometry，并令无会话热键进入 session-only 启动，不强开战斗或猜测设备。BitBlt/PostMessage、UID覆盖层及显卡启动告警作为下一可独立验收单元，不能算在本阶段完成。
6. 只进行 fake HTTP、Win32/OLE、Replay、临时资料及离屏 Qt 验证；不启动游戏/模拟器、不真实消息/输入/NAS。合并后检查本次新增保护分支，构建最终安装物验收并本地备份，按 AGENTS 同步版本和发布。最终报告保留未实战范围。
