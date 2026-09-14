# 1.70.03：冷启动读取特征码无反馈

## 证据与根因

本机打包版日志确认 15:12:14 已从 1.70.01 更新至 1.70.02。15:11:56 起的启动记录包含 OCR、窗口捕获和界面初始化，但截至本次检查没有新的 TaskExecutor “start execute”记录。历史记录中执行线程在任务开始时才启动。

request_capture 只将 Future 放入队列并唤醒执行器；TaskExecutor.thread 初始化为 None，原先仅 start() 会创建线程。新启动后未运行任务，唤醒不会创建线程，因此读取请求无人处理。界面等待 Future 12 秒，期间没有读取状态提示，超时异常文本又为空，造成“点击没反应”的体验。

上一版修复的是读取成功后的旧账号保存失败，界面回归使用已完成的 Future，没有覆盖本次冷启动缺陷。该限制应明确承认，不能把上一版回归通过当成完整实机链路已验证。

## 修改

- TaskExecutor.ensure_capture_worker 在锁内按需创建唯一执行线程，保留 paused 状态；正常 start 复用该方法后仍按原流程解除暂停。
- 截图请求入队后调用该方法，暂停循环中的既有 process_capture 负责处理。截图与 OCR 保持在执行器线程，读取不会启动游戏任务或模拟按键。
- 账号页显示“正在读取”，操作期间禁用读取按钮；失败显示具体原因，超时明确提示并取消尚未执行的 Future，恢复按钮。日志只记录失败异常类型，不写入号码。

## 验证与边界

使用本地 .venv：TestAccountFeatureVerification 19 项、TestAccountManagementTabs 28 项、TestDiagnosticScheduling 4 项、TestAutoCombatRecovery 13 项、TestAccountIdentityProtection 5 项，共 69 项全部通过。

冷启动用例从 thread=None 创建真实执行线程，通过实际 execute/sleep/process_capture 路径读取三个合成帧，验证 OCR 在线程内执行、重复请求线程启动幂等、paused 仍为真、next_task 未被调用，并在结束时停止测试线程。界面用例验证进度、重复点击拦截、超时反馈及按钮恢复。既有旧账号保存/取消及磁盘重读回归继续通过。

未执行真实游戏内 OCR 和 A3 绑定，不能确认实际号码。更新 1.70.03 并重启后，不启动任何任务，直接读取特征码进行验收；保持游戏右下角完整可见，核对账号与实际号码后确认，等待“特征码已绑定”。若再次失败，应查看此时明确显示的失败文本与日志时间。

本轮只查阅本机文本日志，未审阅诊断 ZIP，不执行 NAS 证据保留期标记。工作在隔离分支，保留其他并行修改。
