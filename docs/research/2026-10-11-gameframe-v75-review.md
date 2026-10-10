# v75 后端与视觉调用链复核

独立专项复核见本目录 win32-review、uid-overlay-integration、gpu-startup-review 和 gpu-provenance。主线审查合并后的 worker/plugin/executor/host/GUI、配置迁移、语言与最终安装物，未重新审查无关旧业务。

Windows 后端选择是显式外部设备参数，非法值明确失败，不猜后端或回退。GDI 资源逐层持有和释放；PostMessage 保留键/按钮 ownership、DPI 和 Win32 消息契约，失败释放真实拥有状态，不谎报成功。选定 HWND/PID/create-time、客户区物理尺寸及前台状态是跨进程/窗口边界。新增 overlay_target 无 capture、activate、Qt 或额外设备创建；对象复用与几何读取期间变化有对应 fixture。

UID 的区域、算法和参数归 AGPL 游戏包；MIT renderer 无鸣潮区域或素材。producer 从当前 owner 缓存处理局部 ROI，不读取 diagnostic_frame 作为当前画面。executor 每次新帧开始先清场景，采集失败及超时不会复活旧帧。overlay 事件发送失败后 active 仍可被 clear 收尾；host 明确记录视觉失败，保持捕获返回和战斗。plugin 的三个执行路径共用 finally 清除，GUI 停止/暂停/worker exit/close 独立清除。旧 owner 的 clear 不影响新 owner。

GPU detector 固定上游 commit 与原始 SHA，许可在 AGPL 包内，核心只提供可选设备准备钩子。只保留已有启动消费者可到达的检测路径；去掉未使用查询，不自动修改 HDR/驱动。无法检测与明确 off 分开，观察结果不等于该游戏实际渲染效果；失败记录 unknown 并继续启动。worker 租约与关闭顺序保持。

配置只从明确资料根一次导入已有三个遮罩偏好，秒间隔不误当毫秒。全局默认集中在 Program Preferences；删除仅测试使用的重复 DEFAULTS。所有旧 native 译文与 ok.po/mo 字节保留。新增保护分支依据为设备 JSON、Win32/GDI 契约、身份与图像尺寸、持久配置、可选驱动和事件出口，未发现无依据重试或总次数关闭。

最终 wheel 17 项；候选安装扩展 35 项和三个生产入口通过。仅移除未消费常量后，以逐成员 delta 确认其他代码不变，最终 producer/renderer 5 项及所有索引有效。上述证据不包含真实游戏、驱动、后台会话、输入、视觉效果或 NAS。
