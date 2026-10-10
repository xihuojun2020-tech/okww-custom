# v74 HTTP 通知集成专项

`TestNativeNotificationIntegration.py` 的 6 项检查通过。最初 4 项 2.419 秒，新增诊断脱敏单项 0.092 秒、排队快照单项 0.073 秒。所有 HTTP 调用均由合成 transport 承接；没有真实消息、游戏、模拟器、设备输入或 NAS。

真实隔离配置子进程使用合成可信账号，调用生产 `native_configuration.main` 与 JSONL 协议。schema 为 6 个 global 组；Webhook/Token 当前值为空而 configured 正确；秘密保存、刷新及显式清除后核对实际 JSON。子进程禁止导入设备框架、Qt、OCR 与 HTTP 客户端，也没有运行记录数据库。

生产 host 的真实 `task.notification` 和 `task.log_info(notify=True)` 调用链分别产生一次 HTTP 投递及完成事件。解码上传 PNG 后核对身份区域为零、其他像素保留，原始 NumPy 帧不变。`PackageManifest.load` 创建的真实 plugin 关闭绑定的 hub 后，通知 executor 的线程全部退出，并拒绝后续排队。

缺失 Telegram 凭据时不调用 transport，完成事件明确为 configuration 失败。Qt 秘密字段使用 Password、初值为空，编辑和空白保存不清除；保存新值和“清除”按钮各发送明确更新参数。配置子进程检查另验证清除实际持久化。

诊断检查直接调用 `sanitize_data` 和用于准备诊断文件的 `sanitize_file`，核对旧 Notification 与 Native Notifications 中 Webhook、Bot Token、Chat/Channel ID、旧及新 QQ/WeChat 昵称全部脱敏。排队检查用阻塞的假 transport 验证：配置在第二项排队后修改目的地址，两项仍使用提交时地址。

未发现新的确定生产根因；不修改生产代码。`notification-delivery` 是明确的每路由完成结果，现有 GUI 日志入口能记录；单独状态栏汇总属于界面改进，不是 HTTP 集成正确性的必要修复。桌面通知 sender 尚不在本专项范围内，不能将 HTTP/Qt fixture 通过表述为桌面真实投递成功。
