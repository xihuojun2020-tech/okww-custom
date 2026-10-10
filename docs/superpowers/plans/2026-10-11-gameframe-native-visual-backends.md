# 原生捕获、后台输入及视觉消费者实施计划

目标：恢复原版已存在的 BitBlt_RenderFull/PostMessage、UID 实时遮罩和启动前 GPU 后处理告警，保持单一输入 owner 与自动战斗启用意图。沿用已授权框架设计；只做离线接口与最终安装物验收。

1. WindowsDevice 明确选择 WGC / BitBlt_RenderFull / PrintWindow，以及 SendInput / PostMessage。默认 WGC+SendInput，配置表单写入实际 worker 参数，不自动回退。PostMessage不声明 raw relative mouse 或物理鼠标能力；同步 PrintWindow 不承诺超时或最小化支持。
2. WindowsDevice 提供只读 overlay_target 物理客户区和 HWND/PID/create-time。AGPL producer 只从当前 capture 缓存处理鸣潮 UID ROI；MIT Qt renderer 只消费通用 PNG patch/geometry。捕获失败、超时、暂停、退出或失去可信前台时隐藏，视觉错误明确报告而不关闭战斗。不额外截图，不复活故障诊断旧帧。
3. Program Preferences 迁移旧 Enable Blur=False、Blur Algorithm=Inpaint（Blur/Inpaint）、Blur Interval=1秒，并提供实际消费者。无设备配置进程不创建 producer、Win32 或 Qt。
4. worker 设备 prepare 后调用包的可选 device_ready 钩子；鸣潮包执行一次可信目标 GPU 告警。AGPL vendor 来源固定到 ok-script commit 90f4d86991329196cf935a19f64d528a16025a4b，保留许可和引用；MIT 核心不导入检测代码。缺 NVAPI/ADLX/观察结果报告 unknown，不自动修改 HDR 或驱动设置。
5. 合并后用 fake Win32、GPU、Qt、当前帧和完整关闭路径检查；独立复核新增分支来源，再构建 wheel/两个 ZIP，核对安装来源/索引/哈希并备份发布。真实后台游戏、驱动告警、屏幕/DPI效果与延迟均保留未验证标记。
