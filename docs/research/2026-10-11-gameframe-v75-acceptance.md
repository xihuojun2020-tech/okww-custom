# GameFrame v1.97.75 离线验收

本阶段恢复实际 Windows 后端选择、UID 实时遮罩和启动前 GPU 后处理告警，六语言各补充 21 条。登录自启和完整环境自动更新继续实施；不能将这一阶段发布视为总目标完成。

验收全程使用模拟 Win32/GPU、现有图片、临时资料、Replay 和离屏 Qt。没有启动游戏、模拟器，调用真实系统输入/剪贴板、检查真实 GPU/驱动或访问 NAS。

- 冻结 wheel 的核心界面 17 项通过，Python 源码逐字节核对及隔离核心导入通过。
- 候选安装 wheel/payload 的视觉、后端、GPU 及语言扩展 35 项通过；生产轮转、真实管理与只读总览 3 项通过；v74→v75 实际 ZIP 更新及安装诊断通过，合成私人数据不变。
- 最后复核删除 producer 中仅测试使用的重复默认常量，唯一配置权威继续为 Program Preferences。重新构建两个 ZIP 后逐成员对照，只有该 Python 文件和索引变化；其他生产文件、manifest、wheel 全部一致。最终安装的 producer 与通用 Qt renderer 5 项通过，包含独立 timer 的移动、背景、复用进程及尺寸变化。最终两个 ZIP 的安装索引、ZIP CRC、产物前后 SHA256 有效。
- 源码专项分别通过：Windows 新后端/geometry 15 项和原设备 16 项；UID 接线 9 项；GPU 检测 11 项、worker 启动钩子单项的六种状态及无钩子路径；语言 10 项。新 overlay 契约下的旧通知/程序偏好 fixture 更新后，6 个受影响检查通过；没有向生产添加兼容不完整 fixture 的 fallback。

Windows 默认仍为 WGC+SendInput。PostMessage 的投递成功仅证明窗口消息 API 接受，不证明游戏处理；不提供 raw relative mouse 或物理鼠标移动。PrintWindow/BitBlt_RenderFull 同步渲染拒绝最小化，不承诺 timeout、新鲜帧或游戏兼容性。独立 Windows 会话、Child Session/RDP 的研究路线仍未经实机验证。

UID producer 复用实际 current frame 并只处理 ROI，暂停、采集失败/超时、失去可信前台和退出清除。GUI 只消费 patch，不输出 PNG 私密载荷。GPU 告警在 prepare_device 后由包执行一次；缺可选 NVAPI/ADLX 保持未知，失败继续启动。所有这些检查均不修改战斗启用偏好。

分发物、安装来源、final-artifact-delta、索引/哈希及备份证据存于 `E:/AI work/okww-framework-backups/20261011-v1.97.75`。源码快照按逐文件 SHA、ZIP CRC、Python AST 验证，完整 Git bundle 验证后随版本发布。真实游戏账号、硬件延迟、后台实战、屏幕/DPI视觉效果与驱动状态尚未验证。
