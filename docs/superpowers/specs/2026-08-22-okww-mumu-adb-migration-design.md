# OKWW MuMu/ADB 改版完整设计说明

- 状态：设计已确认，尚未开始实现
- 日期：2026-08-22
- 目标：中国版 MuMu 模拟器 12，横屏 1280×720
- 第一阶段：固定三人队自动战斗
- 第二阶段：单账号每日任务、多账号每日任务
- 默认账号序列：A1 → A3 → A4

## 1. 文档目的

本文说明 OKWW 从 Windows 游戏窗口、键盘和鼠标控制迁移到 MuMu/ADB 后的完整行为，供实现 AI、运行端维护 AI、测试人员和故障排查人员使用。本文是架构和验收规范，不代表功能已经实现。

## 2. 总体架构

采用“外部识别与调度 + 模拟器内战斗执行器”：

```text
Windows 外部 OKWW
├─ 只读总配置、账号、序列和计划
├─ Nemu IPC 高速截图
├─ OCR、模板识别和状态判断
├─ 角色策略、每日任务和多账号编排
├─ checkpoint、日志和故障证据
└─ 发送语义动作
              │ ADB forward + 持久化 Socket
              ▼
MuMu 内部 OKWW Combat Agent
├─ 多指触点状态
├─ 动作批次和本地精确计时
├─ 连招、长按、摇杆和视角执行
├─ 抢占、取消、心跳和看门狗
└─ Android InputManager 输入注入
              ▼
             鸣潮
```

原则：

1. 外部程序是唯一策略大脑；
2. 模拟器内程序只负责低延迟、低抖动地执行输入；
3. 账号密码、总配置、OCR 和调度不放入模拟器；
4. PC 模式继续保留，Android 是新增设备后端；
5. 角色决策行为与现有 OKWW 等价，替换输入与移动端 UI 识别；
6. 账号配置只来自只读总配置的稳定 UUID 快照；
7. 用户停止拥有最高优先级；
8. 输入已投递不等于操作成功，必须观察状态变化。

## 3. 范围与非目标

### 3.1 第一阶段

1. 中国版 MuMu 12；
2. 单个模拟器实例；
3. 横屏 1280×720；
4. 鸣潮默认手机触控布局、固定摇杆；
5. 一支固定三人队；
6. 自动战斗闭环；
7. 停止、触点释放、证据和性能基准。

### 3.2 第二阶段

1. 单账号每日任务；
2. 多账号每日任务；
3. A1、A3、A4 连续切换；
4. 短名、备用名、扫码 U 名称和掩码手机号；
5. 账号列表动态排序；
6. 游戏 UID 二次验证；
7. 步骤级 checkpoint；
8. 配置导入导出、备份和故障诊断包适配。

### 3.3 第一轮不做

1. 不同时适配全部 Android 模拟器；
2. 不同时迁移全部角色；
3. 不支持自定义手机按钮布局；
4. 不把完整视觉识别搬进模拟器；
5. 不默认启用 Root、Magisk、Shizuku 或系统镜像修改；
6. 不移除 PC 模式；
7. 不设计游戏检测规避机制。

## 4. ALAS 参考边界

借鉴：

1. 设备连接、截图、控制解耦；
2. 每个实例显式绑定 serial 和 package；
3. 实例名作为进程、日志和设备隔离键；
4. 类似 `Enable / NextRun / Command / Priority` 的调度语义；
5. 多后端、自动重连和启动基准测试。

不照搬：

1. 不把 NextRun 写回只读总配置；
2. 不把一个账号等同于一个进程；
3. 不允许多个进程争抢同一 ADB serial；
4. 不把完成记录写入账号任务配置；
5. 不引入 ALAS 的完整 WebUI 和配置继承体系。

参考：

- Device：<https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d816310324bf686dff3252b37efbb997d9a328a4/module/device/device.py#L64-L124>
- Scheduler：<https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d816310324bf686dff3252b37efbb997d9a328a4/module/config/config.py#L228-L320>
- ProcessManager：<https://github.com/LmeSzinc/AzurLaneAutoScript/blob/d816310324bf686dff3252b37efbb997d9a328a4/module/webui/process_manager.py#L28-L180>

## 5. 设备通道

每个 MuMu 实例对应一个 DeviceChannel：

```json
{
  "id": "mumu_main",
  "emulator": "mumu12_cn",
  "adb_serial": "127.0.0.1:16384",
  "package": "<game-package>",
  "resolution": "1280x720",
  "orientation": "landscape",
  "capture_backend": "nemu_ipc",
  "control_backend": "okww_combat_agent"
}
```

规则：

1. 多设备时禁止自动猜 serial；
2. 启动前核对 package、Android 版本、ABI、分辨率、方向和 display ID；
3. 进程锁与文件锁共同保证设备独占；
4. 日志、截图、checkpoint 和性能数据按设备通道隔离；
5. 账号迁移设备时不改变账号 UUID；
6. serial/package 属于设备层，不直接写进账号资料。

截图主路径为 Nemu IPC 原始帧。ADB screencap 只用于启动自检、故障诊断和对照截图，不能承担实时战斗截图。

## 6. 模拟器内战斗执行器

主控制路径为 `okww-combat-agent.jar`：

```text
adb push agent.jar /data/local/tmp/
adb forward tcp:<host-port> localabstract:okww_<session-id>
adb shell CLASSPATH=/data/local/tmp/agent.jar app_process / <main-class>
```

Agent 必须：

1. 默认以 ADB shell 权限运行，不要求 Root；
2. 使用持久 Socket，避免每次输入创建 shell；
3. 通过 InputManager 注入多点触控；
4. 支持 pointer ID、down/move/up 和批次提交；
5. 使用单调时钟执行动作；
6. 返回 `accepted/started/completed/cancelled/rejected`；
7. 心跳超时、断线或停止时释放全部触点；
8. 只监听 ADB 转发的本机端口，使用会话 token 和命令白名单。

备用后端：

1. ADB tap/swipe：低频单指 UI 降级；
2. AccessibilityService：无需 shell 的备用路径，不作为高频战斗首选；
3. MaaTouch/minitouch：实验性多指路径；
4. Root：只能显式开启，不能静默使用。

## 7. 控制权与停止

设备有两个互斥模式：

```text
COMBAT      Agent 独占触控并执行高层战斗动作
AUTOMATION  外部每日任务/账号流程决定每一步 UI 操作
```

模式切换必须停止旧动作、取消未执行批次、释放全部触点、等待 ACK，再发放新模式所有权。

紧急停止流程：

1. 设置全局取消令牌；
2. 禁止新动作；
3. 走独立通道发送 `EMERGENCY_STOP`；
4. `release_all_touches()`；
5. 中断 OCR、等待和重试；
6. 原子写入 `stopped` checkpoint；
7. 工作线程真实退出后 UI 才显示“已停止”。

验收：500ms 内不再生成动作，1 秒内释放触点。Agent 无响应时终止 Agent。用户停止后不得自动退登、切账号或置前游戏。

## 8. 自动战斗

### 8.1 复用边界

可以完整保留角色定位、buff、冷却、协奏、技能优先级、入场技、切人优先级、轮换顺序、冻结时间和状态重置，但不能做到所有文件一行不改。

代码审查结论：

1. 49/49 个角色的高层决策可保留；
2. 27 个角色文件有 104 处直接键鼠调用；
3. 12 个角色含 PC HUD 固定区域或像素检测；
4. 第一阶段只迁移固定三人队；
5. 其余角色后续按 Android 模板资源逐步开放。

必须替换：Q/E/R/T/F、鼠标左右键和长按、WASD、PC 技能字母图标、PC forte 模板、PC 头像/协奏/目标条、Win32 光标和中键锁定。

### 8.2 语义接口

```text
normal_attack()
heavy_attack(duration)
resonance_skill()
liberation()
echo_skill()
dodge(direction)
jump()
move(vector, duration)
camera(delta, duration)
switch_character(index)
break_action()
release(action)
release_all()
```

观察接口：`action_available`、`cooldown`、`meter`、`feature`、`combat_state`、`current_character`、`team_state`。PC 映射为键鼠，Android 映射为触控。

### 8.3 多指和 UI

```text
pointer 0：固定摇杆
pointer 1：视角
pointer 2：普攻、重击、闪避
pointer 3：技能、声骸、解放、切人
```

不同触点可并行，同一区域串行；闪避和停止可抢占普通攻击；所有长按必须登记释放回调。

固定 1280×720，但坐标使用归一化锚点。战斗前验证摇杆、普攻、闪避、技能、解放、声骸、三个头像、当前高亮、方向和黑边。布局不符时禁止盲点并保存标记截图。

### 8.4 性能与验收

预计自动战斗达到当前 PC 版本约 70%–90%，每日任务约 75%–90%。目标：截图 P95≤20ms，控制入队到发出 P95≤15ms，固定队 20 场至少 19 场成功，连续运行 60 分钟无残留触点，战斗耗时中位数不超过 PC 同队 1.35 倍。

## 9. 配置模型

### 9.1 四层结构

| 层级 | 内容 | 程序权限 |
|---|---|---|
| 总配置 | 账号、UUID、别名、序列、任务、时间、设备计划 | 只读 |
| 工作配置 | 兼容现有 UI 与旧模块的派生副本 | 原则只读、可重建 |
| 运行状态 | NextRun、完成时间、失败、checkpoint | 可写 |
| 证据数据 | 日志、截图、触点、冲突快照 | 可写、定期清理 |

建议结构：

```json
{
  "schema_version": 2,
  "device_channels": {
    "mumu_main": {
      "serial": "127.0.0.1:16384",
      "package": "<game-package>",
      "resolution": "1280x720"
    }
  },
  "accounts": {
    "<uuid-a1>": {
      "short_name": "A1",
      "aliases": ["<masked-phone>", "<u-name>"],
      "game_uid": "<uid>",
      "task_config": {}
    }
  },
  "sequences": {
    "sequence_1": ["<uuid-a1>", "<uuid-a3>", "<uuid-a4>"]
  },
  "plans": {
    "daily_main": {
      "enabled": true,
      "device_channel": "mumu_main",
      "sequence": "sequence_1",
      "schedule": {
        "mode": "daily",
        "local_time": "04:15",
        "timezone": "Asia/Shanghai"
      },
      "final_account_policy": "restore_starting_account"
    }
  }
}
```

安全规则：

1. App 不能写总配置；
2. 稳定 UUID 是真实身份，显示名只是标签；
3. 别名和掩码手机号只用于登录识别；
4. 游戏 UID 用于登录后的最终核验；
5. 每个账号运行前生成 detached effective config；
6. 子任务不能直接使用另一个账号的可变 Config；
7. 账号切换前重新验证总配置摘要；
8. 外部修改产生冲突时记录日志并要求用户确认；
9. 导出包带 schema、manifest 和哈希；
10. 导入必须预检、备份和原子替换；
11. 工作配置损坏后可由总配置重建；
12. 运行态不能反向覆盖总配置。

## 10. 调度与游戏日

默认：

```text
timezone = Asia/Shanghai
day_boundary = 04:00
logical_game_day = date(now - day_boundary)
```

不能仅使用操作系统自然日。账号级调度决定哪个账号何时运行哪些任务；任务级调度决定设备通道当前执行哪个 Command。`NextRun` 只写运行状态。

跨刷新边界规则：

1. 预计多账号运行会跨 04:00 时，不启动新账号；
2. 已开始账号完成当前安全步骤后停止；
3. 新游戏日生成新 run ID 和 checkpoint；
4. 不复制旧游戏日完成状态；
5. 周日任务根据游戏日星期判断。

## 11. 单账号每日任务流程

已确认：先清体力，再执行梦魇。

```text
调度准入
  → 设备自检与独占锁
  → 登录身份/游戏 UID/配置 UUID 三重核验
  → 生成 RunSnapshot
  → 检查每日积分和已消耗体力
  → 按账号配置清体力
  → 重新检查积分和体力
  → 执行梦魇捕获或自动刷取
  → 领取每日奖励
  → 领取邮件和战令
  → 每周乐园与周日声骸合并
  → 保存进度证据
  → 最终验证
  → 记录每日目标完成
  → 退登或进入最终账号策略
```

任务状态：

```text
completed
verified
already_done
skipped_disabled
skipped_not_due
retryable_failed
blocked
stopped
unknown
```

`unknown` 不能当作成功。

默认必须成功：账号验证、配置绑定、按账号配置清体力、每日积分达到 100、核心奖励领取、最终验证。

按配置决定是否必须：自动梦魇、每周乐园、声骸合并、指定资源副本。邮件、战令和进度录像默认尽力执行，但可配置为 required。

每一步可配置：

```json
{
  "enabled": true,
  "required": true,
  "max_attempts": 3,
  "timeout": 120
}
```

## 12. 清体力全部情况

旧条件：

```python
need_stamina = not daily_reward_ready and used_stamina < 180
```

该条件会在活跃达到 100 时跳过清体力。新条件：

```python
need_stamina = stamina_enabled and used_stamina < target_stamina
```

活跃积分不再决定是否清体力。

| 清体力开关 | 已消耗体力 | 活跃积分 | 行为 |
|---|---:|---:|---|
| 关闭 | 任意 | 任意 | `skipped_disabled` |
| 开启 | 小于目标 | 小于100 | 按账号配置清体力 |
| 开启 | 小于目标 | 已满100 | 仍按账号配置清体力 |
| 开启 | 等于或超过目标 | 任意 | `already_done` |
| 开启 | OCR未知 | 任意 | 重试识别，不得假定完成 |
| 开启 | 体力不足 | 任意 | `retryable_failed` 并安排后续重试 |
| 开启 | 副本失败 | 任意 | 回主界面、重读体力后决定是否重试 |
| 开启 | 战斗崩溃 | 任意 | 禁止直接重放，先读取实际体力 |
| 开启 | 用户停止 | 任意 | `stopped`，释放触点，不自动恢复 |

补充规则：

1. 默认目标为 180，每账号可在总配置修改；
2. 目标属于只读账号计划，运行中 UI 不得临时修改；
3. 每次副本结束后重新读取实际消耗；
4. 达到或超过目标立即停止；
5. 活跃达到 100 不能替代体力任务完成；
6. 副本可选无音区、材料本或模拟领域；
7. 运行前必须确认账号 UUID 和副本配置来自同一快照。

## 13. 梦魇全部情况

梦魇在清体力之后运行。模式：每日声骸、自动刷梦魇、关闭。

| 每日声骸 | 自动刷梦魇 | 清体力后活跃 | 行为 |
|---|---|---:|---|
| 关闭 | 关闭 | 任意 | 跳过 |
| 开启 | 关闭 | 小于100 | 执行每日声骸捕获 |
| 开启 | 关闭 | 已满100 | 可跳过，因为该模式只服务每日活跃 |
| 任意 | 开启 | 任意 | 按配置自动刷，不受活跃影响 |
| 开启 | 开启 | 任意 | 自动刷模式优先，避免重复两次 |
| 任意 | 开启 | OCR未知 | 按显式自动刷配置执行 |
| 任意 | 任意 | 任务失败 | 保存证据，按 required 决定阻断或继续 |

防污染：子任务临时覆盖必须用上下文并在 finally 恢复；子任务收到 detached config；失败后恢复主界面再领奖。

## 14. 奖励和每周任务

### 14.1 每日奖励

完成证明：活跃达到 100、核心奖励无可领取状态、重新打开每日页后仍成立。OCR 未知不能成功。

### 14.2 邮件

默认尽力执行；无可领取按钮为 `already_done`；失败独立记录；可在总配置设为 required。

### 14.3 战令

Android 不使用 Alt，改用可见入口。无领取按钮为 `already_done`，活动结束为 `skipped_not_due`，页面未知为 `unknown`。

### 14.4 每周乐园

所选日期或周日游戏日检查。已完成则跳过，未完成则运行；半途停止保留 checkpoint，下次重新检查实时状态。

### 14.5 声骸合并

仅周日游戏日且开关启用时运行。数量不足是业务结果，不是设备错误；是否 required 由账号配置决定。

## 15. Android 每日导航

禁止 DailyTask 直接使用 F2、Alt、ESC、Windows HWND 或系统鼠标。统一接口：

```text
ensure_main()
open_terminal()
open_guidebook_activity()
open_mail()
open_battle_pass()
open_map()
open_weekly_garden()
back_to_main()
open_settings()
logout()
```

页面状态：

```text
MAIN
TERMINAL
GUIDEBOOK_ACTIVITY
MAP
MAIL
BATTLE_PASS
WEEKLY_GARDEN
LOGIN
ACCOUNT_LIST_EXPANDED
UNKNOWN
```

规则：先识别再动作；未知状态不盲点；每次动作必须观察到状态变化；Android 模板与 PC 模板分开；不能只缩放 PC 坐标。

## 16. 多账号每日任务

### 16.1 标准流程

```text
读取 A1 → A3 → A4
  → 识别真实起始账号
  → 选择第一个未完成账号
  → 登录前核验目标
  → 登录并核验游戏 UID
  → 绑定同 UUID 的 DailyTask 配置
  → 运行单账号流水线
  → objective completed
  → 安全退登并 transition committed
  → 下一个账号
  → 按最终账号策略结束
```

### 16.2 不同启动现场

游戏主界面：识别 UID；当前账号属于序列且未完成时优先处理；不属于序列则不运行它，安全退登后再选择目标；记录真实起始账号。

登录界面：读取当前显示账号，根据序列和 checkpoint 选第一个未完成账号；显示账号不等于目标时重新选择。

未知界面：有限次数返回并重新识别；无法恢复则保存证据并停止；禁止连续返回键或盲点。

### 16.3 动态账号列表

1. 每次重新展开、截图和 OCR；
2. 匹配全部可见账号到 profile UUID；
3. 优先点击明确匹配目标；
4. “最下面一项”只作为已验证序列关系的辅助信息；
5. 点击后等待列表关闭和显示账号变化；
6. 未变化时重新展开、重识别并改变小范围点击偏移；
7. 不缓存固定行号和旧坐标。

身份匹配优先级：精确登录名、备用名、扫码 U 名称、掩码手机号。A1/A3/A4 仅用于配置解析，不假定登录页显示短名。一个文本匹配多个账号时禁止登录。

### 16.4 点击或账号错误

点击未生效：重新展开并重新 OCR，不消耗登录或退登重试。

登录前账号不符：不点登录，重新选择目标账号，达到独立上限后才安全停止。

登录后 UID 不符：绝不执行任务；保存证据；安全退登；重新选择目标；使用独立 post-login mismatch 预算；连续错误或不能安全退登时停止整个设备通道。

### 16.5 退登状态机

```text
MAIN → open_settings
SETTINGS → tap_logout
CONFIRM → confirm_logout
TRANSITION → wait
LOGIN → verify_login_screen
```

每个状态有独立连续动作预算；状态变化后使用新状态预算；无 OCR/过渡只受 deadline 限制；CONFIRM 只点确认；SETTINGS 只点退登；MAIN 只打开设置；退登失败不能导致重复清体力。

## 17. checkpoint 与完成事务

```json
{
  "schema": 2,
  "run_id": "...",
  "game_day": "2026-08-22",
  "sequence_fingerprint": "...",
  "master_digest": "...",
  "start_profile_id": "...",
  "state": "running",
  "current": {
    "profile_id": "...",
    "expected_identity": "...",
    "actual_identity": "...",
    "stage": "daily_started",
    "attempt": 1,
    "error": null
  }
}
```

两个完成边界：

1. `objective completed`：每日核心目标实时验证完成；之后恢复不得重复清体力；退登失败不回滚业务完成；
2. `transition committed`：到达登录界面、指定最终账号主界面或明确终止状态；只有此时编排器才能进入下一个账号。

| objective | transition | 恢复行为 |
|---|---|---|
| pending | pending | 重读积分/体力并恢复步骤 |
| completed | pending | 不重刷体力，只恢复退登/最终状态 |
| completed | committed | 跳过该账号 |
| stopped | 任意 | 等待用户重新启动，不自动操作 |
| unknown | 任意 | 先核验实际账号和页面 |

checkpoint 带 sequence fingerprint。序列变化后旧进度不能直接复用；账号级已验证 objective 可按 UUID 保留；显示名不能作为持久身份。

## 18. 最终账号策略

```text
restore_starting_account   默认，登录回运行开始时账号
stay_on_last_account       停留在最后完成账号
return_to_login            停留在登录界面
login_specific_account     登录指定 profile UUID
```

用户停止、UID 安全错误、配置完整性错误或设备状态无法验证时，不执行自动恢复策略。起始账号未知时默认停留登录界面，不猜测账号。

## 19. 错误等级与恢复矩阵

| 错误 | 等级 | 默认行为 |
|---|---|---|
| OCR 暂时为空 | 步骤级 | 刷新帧、等待、重试 |
| 点击无状态变化 | 步骤级 | 重新识别目标并重试 |
| 账号列表重排 | 步骤级 | 丢弃旧坐标，重新 OCR |
| 登录前账号错误 | 步骤级 | 重新选择目标账号 |
| 登录后 UID 错误 | 安全级可恢复 | 退登重选；连续错误停止 |
| 每日页面打不开 | 账号级 | 回主界面后重试该步骤 |
| 副本失败 | 账号级 | 重读体力与积分后决定 |
| 体力不足 | 业务级 | checkpoint + NextRun |
| 退登失败 | 转换级 | 保留 objective，不重刷体力 |
| Agent ACK 超时 | 设备级 | 紧急释放并重启 Agent |
| Nemu IPC 故障 | 设备级 | 诊断截图、重启截图后端 |
| ADB 断开 | 设备级 | 释放触点、重连一次 |
| 模拟器崩溃 | 设备级 | 可配置重启一次并重新核验 |
| 总配置摘要变化 | 安全级 | 安全节点停止并报告 |
| profile UUID 错绑 | 安全级 | 立即停止 |
| 用户停止 | 最高优先级 | 立即取消，禁止自动清理动作 |

每个步骤独立维护：

```text
attempt_count
action_delivery_count
state_deadline
recovery_count
```

账号选择、登录按钮、退登、导航和战斗不共享次数。无有效输入的 OCR 轮询不消耗输入次数；状态变化后新状态从自己的预算开始；用户停止不记为失败重试。

## 20. 日志、截图与点击证据

### 20.1 环形缓冲

1. 失败前 45 秒；
2. 失败后 15 秒；
3. 每秒 2–4 帧；
4. 不保存每一张实时识别帧；
5. 所有关键状态变化和输入动作均记录。

### 20.2 目录

```text
logs/incidents/
  <date>/
    <run_id>/
      <profile_id>/
        manifest.json
        task.log
        checkpoint.json
        effective_config.redacted.json
        touch_events.jsonl
        frames/
```

截图标记：绿色框表示识别目标；红色圆点表示点击位置；箭头表示滑动；数字表示 pointer ID 和动作序号；文字注明目标账号、识别账号、步骤和重试次数。

### 20.3 清理

默认失败证据保留 7 天、总容量不超过 2GB；先删最旧成功证据，再删最旧失败证据；最近一次失败始终保留；正在写入和上传的目录不得删除。

### 20.4 诊断包

运行端导出：

```text
diagnostics_<version>_<run_id>.zip
```

包含版本、脱敏设备信息、日志、checkpoint、标注截图、触点事件、脱敏 effective config、manifest 和 SHA-256。不包含密码、原始总配置、完整手机号、上传凭据或无关隐私信息。

## 21. 测试计划

### 21.1 单元测试

1. 游戏日边界和 NextRun；
2. 活跃 100 时仍清体力；
3. 体力在梦魇之前；
4. 梦魇模式矩阵；
5. 每步独立重试；
6. checkpoint 原子更新；
7. objective/transition 分离；
8. UUID 配置绑定；
9. A1/A3/A4 精确解析；
10. 备用名、U 名称、掩码手机号；
11. UID 错误后重选；
12. 停止异常不被吞掉。

### 21.2 离线回放

覆盖 Android 登录页、动态列表、UI 闪烁、点击未生效、积分和体力 OCR、邮件/战令/乐园页面、角色技能状态，并比较 PC 与 Android 的角色决策轨迹。

### 21.3 故障注入

在每个 checkpoint 前后模拟程序崩溃、ADB 断开、Agent 无响应、Nemu IPC 超时、OCR 空、错误账号、配置变化、checkpoint 写入失败、用户停止和跨 04:00。

### 21.4 集成验收

1. 固定队 20 场至少 19 场成功；
2. 连续战斗 60 分钟无残留触点；
3. A1→A3→A4 连续 10 轮无误账号执行；
4. 任意阶段停止后不再操作；
5. 任意账号不读取上一账号配置；
6. 活跃已满仍按配置清体力；
7. 每日完成但退登失败时不重复清体力；
8. 失败证据包含实际点击位置；
9. 定时清理不删除最近失败；
10. 运行端诊断包能在测试端验证。

现有账号切换相关基线为 66 项 unittest 通过。新架构必须保持这些语义并增加 Android、每日全流程和 checkpoint 测试。

## 22. 分阶段实施

### 阶段 1A：Android 基础设施

DeviceChannel、ADB 显式 serial、Nemu IPC、Combat Agent、多点触控协议、紧急停止、性能基准。

### 阶段 1B：固定队自动战斗

GameActions、Android Observation、固定三人队、PC/Android 行为等价、20 场和 60 分钟验收、战斗证据。

### 阶段 2A：单账号每日任务

Android 导航、游戏日调度、先清体力后梦魇、每日奖励二次验证、步骤 checkpoint、objective/transition 双边界。

### 阶段 2B：多账号每日任务

A1→A3→A4、动态列表、别名/掩码、登录前复核、UID 复核、错误账号退登重选、最终账号策略、测试任务复用生产切换代码。

### 阶段 2C：稳定性与运维

环形截图、点击标记、自动清理、诊断包、故障注入、长时间测试、配置导入导出和备份适配。

后续逐个迁移其他角色，再评估其他分辨率、模拟器和高性能后端。

## 23. 版本与 GitHub 发布

版本固定为 `X.YY.ZZ`：

1. 小修改：第三位加一；
2. 中等变更：第二位加一，第三位清零；
3. 大变动：第一位加一，后两位清零；只有用户明确提出才能执行；
4. 每次代码变更同步修改 `config.py` 和产品版本说明；
5. 每个可运行阶段验证后提交；
6. 创建带注释的 `vX.YY.ZZ` 标签；
7. 推送分支和标签到 GitHub；
8. 运行端通过 GitHub 更新；
9. 纯设计文档不属于代码变更，不单独改程序版本。

本项目根 LICENSE 与 `setup.py` 的 AGPLv3/MIT 描述目前不一致，实施前应单独统一。未明确要求首位升级时，本改版拆成多个中等版本发布，不擅自增加首位。

## 24. 实施前现场信息

1. 固定三人队具体角色；
2. 中国版鸣潮 Android package；
3. 目标 MuMu 实例真实 ADB serial；
4. MuMu Android 版本、ABI 和 ADB 状态；
5. 默认手机 UI 是否完全未调整；
6. A1/A3/A4 游戏 UID；
7. 各账号体力副本和目标值；
8. 自动梦魇是否 required；
9. 最终账号策略；
10. 诊断包从运行端传到测试端的通道。

这些信息不改变总体架构，但影响配置、模板采集和验收样本。

## 25. 不可违反的约束

1. 未验证账号身份不能执行账号任务；
2. 登录账号错误时先安全退登并重选，不能继续；
3. 账号列表不能依赖固定行号；
4. 点击投递后必须验证状态变化；
5. 各步骤重试预算相互独立；
6. 用户停止后不得继续输入；
7. 总配置不可由程序写入；
8. 运行态不能污染账号配置；
9. 活跃达到 100 不能替代清体力；
10. 清体力必须在梦魇之前；
11. 每日目标完成与退登完成分开记录；
12. 退登失败不能导致重复清体力；
13. Android 与 PC 角色决策行为等价；
14. 所有长按、异常和停止最终释放触点；
15. 失败现场必须保留可人工审核的截图和点击位置；
16. 代码发布必须遵守 `X.YY.ZZ` 和 GitHub 推送规则。

---

本文覆盖截至 2026-08-22 已确认的 MuMu/ADB 改版设计。改变目标模拟器、触控布局、账号序列、固定队伍或总配置安全模型时，必须先更新本文并重新评审，再修改代码。
