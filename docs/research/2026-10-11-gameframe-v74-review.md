# v74 通知与桌面入口复核

审查当前变更的生产调用链及最终安装物；不重复旧角色和任务的已完成审查。独立子代理复核见 `2026-10-11-gameframe-v74-owner-notification-review.md`、`2026-10-11-gameframe-v74-desktop-review.md`，生产通知与配置接线见 `2026-10-11-gameframe-v74-notification-integration.md`。

HTTP 线程只投递网络请求；桌面 dispatcher 从 owner 线程惰性创建 Win32/OLE 对象，Runtime 的线程所有权和桌面输入租约持续持有。后台检查点只抛出既有 SessionPreempted，原栈释放输入后到调度边界处理；前台任务期间只排队，暂停不取队列，退出取消。没有修改自动战斗启用偏好，也没有新增总重试次数关闭。

通知 Future 代表排队，完成事件使用逐 route 结果。业务响应、HTTP 错误、部分图片失败与关闭被分别报告；不记录原响应、带 token URL 或 private exception，不重发已完成请求。QQ Guild 图片保持旧版未上传边界。系统托盘开关由核心现有消费者负责，删除未消费的重复新默认项。

配置迁移只读取明确数据根的旧 Notification.json，一次复制已识别字段并保留明确 False 和原文件。Schema 不回显密钥；Qt 密码输入空白编辑不清旧值，保存/清除按钮分别提交。诊断出口遮盖新旧 token、webhook、联系人和目的地。configuration host 不构建设备、OCR 或网络投递器。

剪贴板恢复以原生 IDataObject 完整 FORMATETC/tymed 为契约，STA 物化后 Flush；用户外部改变剪贴板时保留外部内容并报告失败。可信 HWND/PID/create-time、准确联系人/聊天标题及出站确认属于真实外部输入边界。窗口身份检查、PNG 尺寸和 HTTP/API 验收均有接口依据；未发现应删除的无依据保护分支。

插件每次 _run 的 finally 关闭通知辅助实例后清空引用，并恢复 cwd/events；后续服务重试不会沿用已关闭实例。桌面通知错误在通知边界报告，不关闭战斗。窗口 geometry 复用 Qt save/restore，无每 tick 重复写入。管理页成功退出后使用现有 live owner 或无设备查询；繁忙状态明确显示，空白资料根不自动构造假账号。

最终安装核心 17 项、安装生产入口 3 项、通知扩展 34 项及依赖升级/诊断单项通过，索引及来源验证记录在版本备份目录。模拟接口通过与真实游戏、硬件、消息送达成功不同；未使用真实 Win32 输入、剪贴板、网络通知或 NAS。
