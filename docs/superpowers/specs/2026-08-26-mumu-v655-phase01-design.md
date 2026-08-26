# MuMu V6.5.5 阶段01只读预检设计规范

- 状态：已获用户批准，进入实现
- 日期：2026-08-26
- 目标仓库：`ok-wuthering-waves-master`
- 参考实现：`better wuwa_1.12.04_archived_20260825`
- 目标设备：MuMu V6.5.5，单实例，横屏 1280×720
- 固定队伍：奥古斯塔（Augusta）、尤诺（Iuno）、守岸人（ShoreKeeper）

## 1. 范围

阶段01只实现设备基础设施的只读预检，不执行鸣潮战斗输入，不执行角色切换，不启动自动战斗。

预检必须能够发现并报告：

1. MuMu 安装根目录、管理器路径和版本；
2. MuMu 实例、实例编号和 ADB serial；
3. 实际安装的鸣潮包名；
4. Android SDK、ABI、display ID 和设备状态；
5. 物理/逻辑分辨率、DPI、方向和黑边；
6. Nemu IPC 截图可用性和截图尺寸；
7. Combat Agent JAR 哈希、协议身份和心跳；
8. 设备是否满足进入 `READY` 的全部条件。

## 2. 非目标

本阶段不实现：

- `semantic_action` 的游戏触控；
- LayoutMap 和触控布局校准；
- Android 端视觉识别；
- 奥古斯塔、尤诺、守岸人的战斗策略；
- 每日任务、账号切换和登录；
- Root、Magisk、Shizuku、进程注入或检测规避。

## 3. 架构

```text
MuMuDiscovery
  → ADBRunner
  → PackageDetector
  → DevicePreflight
  → Nemu IPC Capture
  → CombatAgentDeployment/Transport
  → PreflightReport
  → DeviceSupervisor/DeviceConsoleTab
```

主仓库作为代码基线，废弃代码只迁移已经验证的边界模块。PC 战斗代码保持不变。ADB serial、游戏包名和设备绑定属于设备域，不写入账号配置。

## 4. MuMu 发现

发现顺序：

1. 读取运行中的 `MuMuManager.exe`、`MuMuPlayer.exe`、`MuMuNxMain.exe` 进程路径；
2. 读取 Windows 卸载注册表的 MuMu 安装项；
3. 检查有限的默认安装目录；
4. 对每个候选使用文件版本、`MuMuManager.exe version` 或实例信息确认版本；
5. 使用 `MuMuManager.exe info --vmindex all` 读取实例候选。

实现补充：当前 MuMuManager 在实例停止时可能省略 `adb_host_ip`/`adb_port`；发现层只在展示候选时按实例 0=`127.0.0.1:16384` 的稳定规则推断 serial，并标记 `adb_serial_inferred`，不会自动连接、启动或选择实例。

发现只能产生候选，不能按照枚举顺序自动选择设备。无法确认版本时，候选标记为“版本未核验”。

## 5. 鸣潮包名检测

对绑定的明确 ADB serial 执行 `pm list packages`，筛选包含 `mingchao`、`wuthering` 或 `kurogame` 的候选，再通过 `dumpsys window`/`dumpsys activity` 确认前台包和安装状态。

- 一个明确候选：填入预检报告，要求用户确认后才持久绑定；
- 多个候选：显示完整包名、版本和标签，禁止猜测；
- 无候选：预检失败，禁止 Agent 输入。

默认配置中的 `com.kurogame.mingchao` 只作为候选提示，实际设备检测结果为权威值。

## 6. 预检契约

新增不可变 `PreflightReport`，至少包含：

```python
PreflightReport(
    emulator_version: str | None,
    emulator_root: str | None,
    instance_name: str | None,
    instance_index: int | None,
    adb_serial: str,
    adb_state: str | None,
    game_package: str | None,
    game_installed: bool,
    game_foreground: bool | None,
    android_sdk: int | None,
    abi: str | None,
    display_id: int | None,
    physical_resolution: tuple[int, int] | None,
    logical_resolution: tuple[int, int] | None,
    density: int | None,
    orientation: str | None,
    black_bars: bool | None,
    screenshot_size: tuple[int, int] | None,
    nemu_ipc_ready: bool,
    agent_jar_present: bool,
    agent_hash_valid: bool,
    agent_heartbeat: bool,
    errors: tuple[str, ...],
)
```

`ready` 只有在以下条件全部满足时为真：MuMu 版本已确认、ADB 状态为 `device`、serial 唯一、游戏包明确且已安装、SDK/ABI/display ID 已知、逻辑分辨率为 1280×720、DPI 为 240、横屏、无黑边、Nemu IPC 截图尺寸为 1280×720、Agent 心跳成功。

任何字段无法确认都按失败关闭处理，不允许降级为“可能可用”。

## 7. Combat Agent 边界

阶段01只验证 JAR 存在、本地/远端 SHA-256、协议版本、构建版本、普通心跳、紧急心跳、取消、紧急停止、`RELEASE_ALL` 和 forward 清理。

当前 Agent 对 `semantic_action` 返回 `layout_not_configured` 是预期行为。阶段01不得把该结果改成真实游戏输入。

## 8. 配置和固定队伍

Android 设备配置保存 MuMu 实例、serial、实际游戏包名、1280×720、240ppi、横屏和捕获/控制后端。固定队伍配置只用于后续战斗阶段的校验：

```json
{"team": ["Augusta", "Iuno", "ShoreKeeper"]}
```

角色名必须能由 `CharFactory` 解析；阶段01不读取游戏画面验证当前队伍。

## 9. UI

设备控制台显示：MuMu 版本、实例、serial、实际包名、Android 版本、ABI、分辨率、DPI、方向、Nemu IPC、Agent 版本/心跳、固定队伍和最后错误。

状态至少包括：未发现、发现候选、等待绑定、预检中、未检测到鸣潮、分辨率不符、截图不可用、Agent 未部署、Agent 心跳失败、就绪、故障。

所有危险操作明确写出目标设备；阶段01不提供战斗启动按钮。

## 10. 测试和验收

单元测试覆盖版本识别、实例解析、serial 唯一性、包名候选、分辨率/DPI/方向、Nemu IPC 截图尺寸、JAR 哈希、心跳超时和失败关闭。

真实测试按风险递增：发现 → 读取 serial → 检测包名 → 读取属性 → Nemu IPC 截图 → Agent 部署 → 心跳 → 停止/释放。整个阶段不发送游戏输入。

## 11. 后续阶段接口

后续战斗阶段使用本阶段输出的 `DeviceChannel`、`PreflightReport`、`NemuIpcCaptureMethod`、`CombatAgentDeployment` 和 `DeviceSupervisor`，再新增 LayoutMap、语义动作、Android HUD 观察和固定三人队策略适配。

## 12. 安全约束

用户停止优先级最高；身份、包名、serial、截图或 Agent 状态无法确认时拒绝输入；不使用 Root/注入/反检测；程序不得为了通过预检而修改游戏或模拟器数据。
