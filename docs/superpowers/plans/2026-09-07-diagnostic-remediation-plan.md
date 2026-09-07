# 2026-09-07 诊断包错误核验与修改方案

> 执行更新（2026-09-07，目标版本 1.34.00）：用户已授权按计划修复。实际基线为 v1.33.03，保留其窗口/热键所有者修复。T1–T5 已实现并加入专项测试；T6 只增加未确认技能的上下文日志，未改变战斗行为。计划中的完整实机矩阵、原始技能片段与输入送达证明仍未完成，不能将离线测试等同于这些验收。具体证据及发布结果见 [诊断整改执行记录](../../reviews/2026-09-07诊断整改执行记录.md)。下方未勾选的原始细项用于保留原验收要求，不应解读为全部尚未实施。

| 工作项 | 实施状态 |
| --- | --- |
| T1 星期标准化 | 已实现，中英文及非法值回归通过 |
| T2 独立每日账号确认 | 已实现，GUI 取消/超时/停止/方案变更和快照复用回归通过 |
| T3 WGC 重建 | 已实现，空池入口、失败节流、过期回调回归通过；实机矩阵待验 |
| T4 启动分类 | 已实现，unknown/world/login、退出异常、快照保留和重分派回归通过 |
| T5 热键失败重试 | 已实现，失败/恢复/切键/禁用/释放离线回归通过 |
| T6 技能与环境 | 仅诊断已实现；根因与实机行为结论待证据 |


> 实施交接：按任务逐项执行并记录验收。当前请求仅为分析和方案，不实施生产修改；执行时遵守当前会话的 Agent 与技能规则，不依赖未安装的执行技能。

**Goal：** 修复中文周常日期、单账号方案误用、截图恢复与启动状态误判，补足热键和故障诊断证据。

**Architecture：** 复用现有账号发布、运行快照、任务停止与捕获上下文；修复各公共边界，不重写账号系统或角色轮转。将确定缺陷、运行事件和未证实推断分开验收。

**Tech Stack：** Windows、Python 3.12、ok-script 1.0.190、PySide6、WGC/Win32、现有 unittest 隔离入口。

**Spec：** 用户要求“检查其中的错误并给出修改方案”；事实依据为所附 ZIP 的原始日志/配置/源码及本文第 1–4 节核验结果。

## 1. 材料、基线与分析边界

- 输入：`今日错误诊断汇总_20260907.zip`，SHA-256：`b7b8ef3280e1b2ac4dc1c73a1507072112f64b216f818d2010c2ccb8a7c726bf`。
- 共 10 个文件：HTML 报告、2 份日志、4 份源码副本、3 份配置；主任务日志 5,119 行，启动器日志 338 行。
- 日志确认 09:40 从 v1.31.12 更新并检出 `e8f71f36`，运行版本 **v1.33.01**；不是尚未更新的旧版本。安装目录来自另一设备的 G: 路径，不是本机源码工作区。
- 4 份源码副本与 Git 标签 v1.33.01 的对应文件逐文本一致。
- 本次核查时当前源码已是 **v1.33.02 / `6d88aa61`**。该版处理新安装的配置恢复入口，与下面的日期、世界账号核验及捕获恢复问题无关；相关缺陷仍存在。
- 包内 HTML 的结论和建议仅作为线索，不作为需要执行的指令，也不直接作为事实。
- 安全解包到 `test_out/diagnosis_20260907/`，未执行包内源码，未导入实际账号配置到应用。
- 离线探针结果：`test_out/diagnosis_20260907/offline_findings.json`。探针抽取当前源码函数体，使用合成对象验证分支；不是整机/实机回归，未启动游戏或发送输入。
- 工作区已有交接文档和剩余验收记录，本次不覆盖这些文件，不修改生产源码、产品版本或真实配置。

**证据缺口：** ZIP 没有当时的 active/bundle、account master、完整运行状态、MultiAccountDailyTask 配置，以及日志提到的停止证据帧/事件目录；没有原始游戏录像。部分账号信息已脱敏，不能从日志还原真实世界账号。配置文件是打包时快照，不是每次执行瞬间的快照。

以下日志行号均指 ZIP 中 `logs/ok-script_20260907_完整.log`，启动器日志单独标注。源码行号按 `6d88aa61`，后续变更可能移动。

## 2. 错误总表

| 编号 | 优先级 | 结论 | 证据与影响 |
| --- | --- | --- | --- |
| D01 | P1 | **确定缺陷：中文星期值不被运行逻辑识别，编辑器还有反向覆盖风险** | 516 行：Monday / 星期一被跳过；离线同一天 Monday=True、星期一=False、周一=False。编辑器选项没有 Monday，加载英文值会回落“无” |
| D02 | P1 | **确定缺口：单账号绑定所选方案，不核验游戏内账号；本次具体 A1/B13 错配为强线索，未完全证实** | 286 行运行 Forgery，401–403 行三个聚落因未选跳过；打包时选中 B13，其方案吻合。但日志身份被脱敏，缺少世界身份截图和活动发布图 |
| D03 | P1 | **确定捕获异常；另有可复现的自动恢复门控问题** | 647–699 行 WGC CreateForWindow 0x80070057 → FrameUnavailable → AutoCombat 停止；全日志 4,056 条 no frame。frame_pool=None 后 connected=False 可阻断 get_frame 内的重建入口 |
| D04 | P1 | **确定启动状态处理缺陷；本次是否由异常分支触发待证实** | Multi 一次 is_main False/None/一般异常都进登录路径，不能表达未知状态；4775–4790 行等待登录后用户停止，无捕获异常栈证明当次 is_main 抛错 |
| D05 | P2 | **确定 F9 注册失败；失败后仍记录为 current_hotkey 的代码缺陷** | 46 行；StartCard.check_hotkey 不检查 rebind 结果，之后相同 F9 不重试。是否被其他程序占用未记录 Win32 错误码 |
| D06 | P2 / 待复现 | **三次共鸣解放未获成功确认，不等于三次程序崩溃** | 385、591、5084 行；BaseChar 0.4 秒未检测到队伍 UI 消失便返回 False。5086 行随后释放成功，5089 行战斗正常结束 |
| D07 | P3 / 环境 | **Defender 偏好读取失败，不是日常流程根因** | 启动器日志 17–24 行 Get-MpPreference / 0x800106ba；后续更新、启动成功。运行启动器自报 1.1.12，与新构建固定的启动器源码版本不是一回事 |

P1 表示应优先解决的功能/数据归属问题；当前证据不足以把全部项目列为 P0 全局阻断。

## 3. 主要问题的根因与报告纠偏

### 3.1 D01：运行值和界面存储值不一致

`src/task/DailyTask.py:81` 的 `weekly_garden_check_due()` 只接受英文 WEEKDAYS，其他值统一当成周日。`src/account_field_metadata.py:37` 却把中文“星期一”等直接作为下拉项数据，`restore_account_value()` 也没有星期映射。

更隐蔽的一面是 `src/gui/AccountConfigTab.py` 的账号表单与模板对话框都执行 `findData(value)`，找不到就选第 0 项“无”。因此已有正确英文 Monday 的方案，在进入编辑器后可能显示成“无”，保存时又覆盖原值。

配置样本共 9 个方案：8 个为“星期一”，1 个为 Monday。这不是“8 个账号都已实际运行失败”的证明，只说明 8 个配置会触发同一种日期兼容缺陷。

“无”当前明确约定为周日起补检，不能顺手改成“禁用周常”。补检规则应保留：到达所选日期后，本周未完成则继续补检，完成后本周不再运行。

### 3.2 D02：方案绑定不等于游戏账号确认

`DailyTask.run()` → `_run_daily_inner()` → `ensure_daily_profiles()` 从 `Daily Profile` 绑定方案。`bind_verified_profile()` 验证 UUID 和配置，`_guard_bound_profile_identity()` 检查运行中身份是否被修改；**两者都没有观察游戏内账号**。离线用只包含 B13 合成配置的对象即可完成绑定，无需提供任何游戏身份。

`ensure_main()` 只证明进入游戏世界，不证明是哪一个账号。由此可能按另一账号方案消耗体力、少刷聚落，并把完成记录记到错误 UUID。这是代码确定存在的风险，即使本次真实世界账号尚不能独立核实，也值得修复。

当前样本中：

- A1：4 个聚落、Tacet Suppression；B13：1 个聚落、Forgery Challenge。
- `DailyTask.json` 保存 `Daily Profile=B13`，但同文件 `Which to Farm=Tacet Suppression`、星期 Monday；并不是 HTML 所说“该文件每项都与运行完全吻合”。
- 实际任务参数优先来自已绑定的发布方案。日志的 Forgery + 1 聚落与 B13 的方案吻合，但多个其他方案也可能有同样组合；不能单凭组合唯一还原身份。
- `NightmareNestTask.json` 的 1 聚落也可能是 Daily 执行时写入的结果，不是独立的根因证明。Daily 在调用子任务前两处直接设置 nightmare_task.config。
- “9 月 6 日多账号把方案停留在 B13”需要前一日日志，当前包不能证明；v1.33.01 正常快照绑定已经避免把每轮参数写回所选偏好，不能再次无条件建议“多账号联动切一下就会修好”。

**不能采用裸名禁用规则。** B12/B13 虽然展示名简短，样本中有非空 phone、masked_phone、nickname、game_feature_code、profile_id。是否能匹配应依据结构化身份、启用别名和歧义规则，不能要求名称必须形如“昵称-手机号”。

### 3.3 D03/D04：截图故障和状态误判是两层问题

10:05:49 捕获目标签名变化，WGC 重建；10:05:50 日志记录窗口短暂 exists=0；随后 CreateForWindow 参数错误。可以确定窗口生命周期变化与异常相邻，但不能仅凭 HRESULT 断言显卡驱动损坏。

当前 WGC `connected()` 要求 frame_pool 非空。创建失败后 `close()` 置空 frame_pool，而 TaskExecutor 的 `can_capture()` 又要求 method.connected() 才允许 `get_frame()`；WGC 的自动重建恰好在 `get_frame()` 内的 start_or_stop。这构成恢复入口被“未连接”判定挡住的链路。离线复现了“窗口存在、交互允许截图、池为空，但 can_capture=False”。其他设备刷新路径也能重建，所以这不是断言任何失败后都永远不能恢复。

14:35 窗口再次 visible=True 后仍持续 no frame；14:41:35 用户触发刷新，DeviceManager 重建 WGC，14:41:39 Daily 检测到主界面。这更支持需要检查捕获恢复，而不是只增加登录等待时长。

Multi `_run_inner()` 在一次 `is_main(esc=False)` 后直接分支：False、None 和被捕获的一般异常都当成登录状态。`BaseWWTask.is_main()` 内还会调用 wait_login、handle_monthly_card，不是纯粹无副作用的状态探测。方案不能简单“连续调用 is_main 三次”而忽略潜在输入。

本次 14:37:31 开始 120 秒登录等待，14:39:22 用户停止，约 111.5 秒；不是已经出现登录等待超时，也不是停止机制失效。后续 Daily 能进入世界，不能反证 14:36 时窗口必定处于可识别的游戏世界。

### 3.4 其他日志应如何解释

- F9：只知道 RegisterHotKey 失败，不能确定冲突程序；即使以后冲突解除，当前相同键值不会触发重绑。停止按钮与 F9 是否可用必须分别显示。
- 绯雪：错误出自共享 BaseChar 的动画确认逻辑，不是直接证明 Hiyuki 轮转公式错误。先核验输入投递、技能冷却/状态、队伍 UI 及帧时间，再决定是否需要角色专属成功证据。
- 多条 0.1 秒 wait_until timeout 是技能短轮询，不是每条都代表任务异常。协奏比例略大于 1 已有 clamp，重复匹配到两个取消按钮未造成该日志中的任务中止；先保留为观察项。
- Defender：记录为启动器环境提示；不通过关闭防护、加排除项或强制启动安全服务来“修复日常”。

## 4. 全局实施约束

- 在当前最新提交上实施，不覆盖已完成的 v1.33.02 新安装修复。
- 真实账号和 configs 只读；旧中文值读取兼容，正规编辑/导入时按现有事务写入规范值，不启动时直接重写 master/active 破坏摘要。
- 停止/暂停、ConfigIntegrityBlocked、GameProcessLost、FrameUnavailable 的语义必须保留。不得用 broad except 把完整性故障变为可继续任务。
- “配置 UUID 已核验”“用户声明当前账号”“观察并唯一匹配实际账号”是三种不同证据，不可混称 verified。
- 所有 GUI 在 GUI 线程；工作者等待用户响应时仍可停止。用户取消、窗口关闭、超时或配置变化必须拒绝执行，不能默认同意。
- 不增加第二套切号算法；继续复用生产选择、核验、重试、退登、登录和证据收尾；测试默认 A1/A3/A4 规则不变。
- 原始截图/账号配置不进 Git。日志新增字段用会话标识、短名称及脱敏内容，不直接打印前五条原始 OCR。
- 生产代码修改才进入版本发布流程；本文不提升版本、不提交标签、不启动游戏。

## 5. 分步修改任务

### T1：统一星期存储和兼容读取（先实施，P1）

**文件：** 修改 `src/account_field_metadata.py`、`src/task/DailyTask.py`、`src/gui/AccountConfigTab.py`；扩展 `tests/TestAccountFieldMetadata.py`、`tests/TestMergeEchoTask.py`、`tests/TestAccountManagementTabs.py`。

**接口：** 在现有字段元数据模块增加 `normalize_weekday(value) -> str`，返回 Monday…Sunday 或“无”；同时处理 `星期一/周一` 至周日，兼容 `星期天/周天`。未知非空值抛 ValueError，由表单显示错误/任务转成配置不可执行提示，不再默默改成周日。

- [ ] 添加会失败的运行回归，覆盖星期别名和周内完成状态：

```python
def test_chinese_monday_matches_english(self):
    monday = datetime(2026, 9, 7, 12)
    for value in ('Monday', '星期一', '周一'):
        with self.subTest(value=value):
            self.assertTrue(weekly_garden_check_due(value, None, monday))
            self.assertFalse(weekly_garden_check_due(value, '2026-09-07 09:00:00', monday))
```

- [ ] `_OPTIONS['Weekly Garden Check Day']` 改为“无”与英文标准值，`option_labels` 显示中文；运行入口统一 normalize，日志显示标准日与原值。
- [ ] 两个 GUI 创建星期下拉前规范化当前值再 `findData()`；未知值显示校验错误并禁止保存，不能回落第一项。打开但不保存不能修改磁盘。
- [ ] 旧中文配置在运行中只规范化副本，编辑保存通过现有仓库事务落盘；两个界面都补“打开 Monday → 保存仍为 Monday”的真实 GUI 回归。
- [ ] 检查七天、周日别名、“无”、空值、非法值、上一周/本周完成记录，以及星期之前不执行、星期之后补检。保留“无=周日起补检”。

**验收：** 所有表示同一天的受支持输入得到相同结果；界面中文显示与英文存储往返一致，旧配置不需用户手改。

### T2：给独立 Daily 加本轮账号确认门禁（P1）

**文件：** 修改 `src/task/DailyTask.py`；必要时新增小型 `src/gui/DailyRunConfirmation.py` 负责 GUI 线程确认桥；扩展 `tests/TestAccountRuntimeIntegration.py`、`tests/TestMultiAccountDailyTask.py`、`tests/TestUsabilityUI.py`。UI 字符串按项目 gettext 规则同步。

**推荐最小行为：** 先保证独立 Daily 不会静默使用上次遗留方案。现有代码没有可靠的“世界画面直接读出账号”入口，不承诺凭任意 OCR 自动识别。显示本轮账号短名称、体力用途、聚落数量与周常日，由用户明确确认；如果未来已有可验证世界身份，必须唯一匹配后才能跳过该确认，不能凭历史选择猜测。

**接口：** 新增 `DailyTask._confirm_standalone_profile() -> bool`，只读本轮方案；本轮确认绑定 profile_id、身份签名和快照，不持久写“已经确认”。GUI 桥只处理显示/回应，生产任务负责校验、超时与停止。

- [ ] 在现有隔离运行夹具中设配置 B13、模拟未确认/取消，断言 Daily 子任务、体力输入和完成记录均未发生。核心断言：

```python
daily._confirm_standalone_profile = Mock(return_value=False)
# 使用 TestAccountRuntimeIntegration 的合成仓库和运行夹具调用真实 Daily.run。
# 捕获明确的取消/任务终止异常后检查：
daily.run_task_by_class.assert_not_called()
daily.record_last_completed.assert_not_called()
```

- [ ] 门禁放在独立执行的配置绑定完成后、WWOneTimeTask/游戏业务动作前；在 `run()` 清除外部标记前保存本次来源，只有生产 Multi 提供的有效运行快照可复用已有确认链。
- [ ] 使用 Qt queued signal 在 GUI 线程展示，任务线程以可中断 `self.sleep()` 等待结果；窗口关闭/用户拒绝/60 秒无响应都停止。无 GUI 的独立调度若没有有效实际身份确认则拒绝并说明，不悄悄放行。
- [ ] 确认展示至执行之间账号删除/重绑/版本改变，拒绝旧回应；不自动选择第一个方案代替已失效选择。普通运行快照机制保持不变。
- [ ] Multi 的正常验证快照不重复弹窗、不改 Daily 持久偏好；单账号确认不反向写入 Multi 起始账号。
- [ ] 用假 Game A / 目标 B 测试可得身份明确不一致时拒绝；缺少观察来源只记录 user_confirmed，不称为 observed_verified。
- [ ] 确认后对子任务实测参数：A1 4 聚落/Tacet，B13 1 聚落/Forgery；完成记录归本轮 UUID。由 UI/输入替身执行，不用真实账号消耗体力。

**验收：** 独立任务运行所用账号和方案对用户可见且经本轮明确确认；取消和不匹配不会消耗资源、写完成记录；多账号路径保留自动化与快照语义。

### T3：恢复 WGC 失败后的可重试路径（P1）

**文件：** 修改 `custom_ok/ok/device/capture_methods/windows_graphics.py`；新增 `tests/TestWindowsGraphicsRecovery.py` 并登记 `run_tests.ps1` 的 unit 组；复测 `TestGameRuntimeErrors.py`、`TestLogoutCapture.py`、`TestTestGroups.py`。

**接口：** 保持 `connected()` / `get_frame()` 的框架接口。参考框架 `BaseWindowsCaptureMethod.connected()`：连接状态表示仍存在的合法目标 HWND，不能仅由 frame_pool 判断；“没有可用帧”仍返回 None/FrameUnavailable，不伪造就绪帧。

- [ ] 先用虚拟时间、假 HWND 和假帧池构造“CreateForWindow 首次失败 → 窗口稳定 → 后续请求成功”，通过真实 TaskExecutor.next_frame 的门控测试 get_frame 后续确实被调用。修复前应因 frame_pool=None 被拒绝。
- [ ] 将 WGC connected 改为逻辑窗口连接，不在 GUI 高频 connected 查询中创建 COM 资源；重建仍在受锁保护的 start_or_stop 中执行。实现方向：

```python
def connected(self):
    return bool(
        not self.exit_event.is_set()
        and self.hwnd_window is not None
        and self.hwnd_window.exists
        and self.get_capture_hwnd()
    )
```

- [ ] 保留同 HWND 失败 5 秒节流，窗口/目标更换后允许新目标重建；临近 CreateForWindow 前再次核验 HWND。生命周期竞态失败依旧返回不可用，不能继续使用旧目标帧。
- [ ] 清理时同步 last_frame、事件及目标签名，禁止上一窗口延迟回调污染新会话；退出/停止不再重建。
- [ ] 覆盖正常连接、空池、无效窗口、连续失败、5 秒节流、目标改变、并发查询/取帧、退出后无重试。断言没有新帧时输入计数为 0；对恢复后是否重新启动已失败任务，保持框架原有语义，不自动重跑战斗。
- [ ] 实施后在受控环境单独验证窗口切换与刷新恢复；若合法窗口稳定存在仍持续失败，再依据证据评估现有 BitBlt 回退，不在捕获失败时盲目发送输入。

**验收：** 一次重建失败不使后续恢复依赖用户点刷新；恢复有界、可停止、没有过期帧和错误窗口输入。

### T4：多账号启动区分世界、登录与未知（P1，建议在 T3 后）

**文件：** 修改 `src/task/MultiAccountDailyTask.py`，按复用需要调整 `src/runtime/login_flow_service.py`；扩展 `tests/TestMultiAccountDailyTask.py`、`tests/TestRuntimeServices.py`、`tests/TestWaitLogin.py`、`tests/TestAccountSwitchEvidence.py`。

**接口：** 新增 `_classify_start_state(time_out=20) -> str`，成功返回 `world` / `login`；超时无法判断抛 FrameUnavailable/明确状态不明错误。不以 False 等价 login。需要中途重新分派时新增内部 `StartupStateChanged` 异常，只由初始账号启动编排捕获，不当作切号成功。

- [ ] 使用现有无输入夹具逐例注入：未知帧→世界、未知帧→登录、持续黑屏、窗口不存在、停止、ConfigIntegrityBlocked。断言未知期间不选号、不写完成记录。
- [ ] 探测尽量使用现有 `in_team_and_world()` 与 `_find_login_ready_box()` 的只读判断，避免循环调用有登录/月卡副作用的 is_main；每次使用新帧和正确 CaptureSample 坐标来源。世界状态需连续两张有效新帧一致；登录强证据沿用同帧账号身份+精确登录按钮规则。
- [ ] `TaskDisabledException` 和完整性异常直接传播；窗口丢失明确失败；短暂帧不可用在总 20 秒预算内重试。超时预算用 monotonic，内层等待不得重新获得完整预算。
- [ ] 仅 world 进入既有“配置起始账号/退登识别”分支，仅 login 进入选号；未知给出“截图不可用/状态未确认”的原因，而非开始 120 秒登录等待。
- [ ] 初始登录等待若重新看到连续世界证据，返回到启动编排重新分类一次，先退出捕获上下文/恢复鼠标状态；不能在 `_wait_login_screen_stable()` 里直接执行 Daily 或把 world 返回成登录按钮。
- [ ] 已明确发起退登的其他调用若仍在世界，使用既有有界退登重试或报错；不一概转为起始世界快路径，避免错误重跑 Daily。
- [ ] 记录阶段、原因、捕获来源、帧龄、窗口可见/存在性与 OCR 类别计数；停止时也保存最近状态。有限 OCR 摘要先经过现有脱敏，不输出原始身份文本。

**验收：** 状态不明不会被当成登录；恢复可重分类，取消仍立即走正常收尾；A1/A3/A4 专项继续复用生产入口。

### T5：热键失败可见、可恢复（P2）

**文件：** 若无法通过当前项目挂接点修复，新增受控覆盖 `custom_ok/ok/gui/start/StartCard.py`，以 ok-script 1.0.190 原件为基线做最小差异；新增 `tests/TestHotkeyRegistration.py` 并登记 unit 组；同步覆盖数量文档及现有清单断言。

**接口：** `rebind_hotkey(hotkey) -> bool`，只有成功注册或明确禁用才更新实际绑定键；desired 与 registered 状态分开。调用 GetLastError 必须紧接失败 API，避免中途其他调用改写错误码。

- [ ] 用假 RegisterHotKey 返回 False→True，核对失败不标成已绑定，5 秒退避后能重试；假值而非在测试机抢占真实 F9。
- [ ] 修复调用关系的核心行为：

```python
if new_hotkey != self.current_hotkey and retry_due:
    if self.rebind_hotkey(new_hotkey):
        self.current_hotkey = new_hotkey
        self.hotkey_changed.emit()
```

- [ ] 注册、注销和消息处理保持原 Handler 线程；错误状态用 signal 回 GUI。界面显示“F9 注册失败，使用按钮或选择其他热键”，保留真实按钮功能。
- [ ] 覆盖持续失败不每 0.1 秒刷屏、禁用 None、F9→F10、关闭释放、Win32 错误码保留；不擅自替用户改热键。

**验收：** 失败后不虚报可用，解除冲突后有节流重试，日志能区分键占用和其他原因。

### T6：补齐角色与环境诊断，再决定行为修改（P2/P3）

**文件：** 条件性修改 `src/char/BaseChar.py` / `src/char/Hiyuki.py` 的局部诊断；复用 `src/observability.py` 和现有截图证据能力。行为测试优先 `tests/TestChar.py`、`tests/TestBaseCombatTask.py`。

- [ ] 获取三个失败时段的脱敏截图/短视频或受控重现，核验共鸣解放 CD、技能形态、目标、队伍 UI、输入投递及当前帧时间。当前 ZIP 没有这些材料，不能假装已验证。
- [ ] 在共鸣解放未确认分支记录低频摘要：角色、阶段、按键尝试次数、等待时长、帧龄、可见状态和确认失败原因；不要只把 ERROR 降级来“消除故障”。
- [ ] 用替身覆盖“输入未被接受”“0.4 秒内确认”“晚到动画”“目标已结束”“停止”。只有新增证据证明判定过窄才调整等待/角色专属成功判据；不得默认全角色加长等待或固定多按一次 R。
- [ ] Defender 事项保留环境结论：必要时读取 WinDefend 服务状态和 API 错误，不更改防护设置。本次应用更新/启动成功，不能将此项与周常/方案/截图故障合并。

**验收：** 角色日志能区分输入未接受与动画未被识别；无新证据时明确保留未确认，不承诺轮转已修好。

## 6. 验证与发布顺序

建议开发顺序：**T1 → T2 → T3 → T4 → T5；T6 随材料补齐推进**。T1 体积小，可先形成补丁；T2–T4 按实际改动量单独安排验证与版本，避免为了快速发布跳过输入边界测试。

聚焦入口（仓库根目录）：

```powershell
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAccountFieldMetadata.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMergeEchoTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestAccountRuntimeIntegration.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestMultiAccountDailyTask.py
.\.venv\Scripts\python.exe .\scripts\run_test_file.py .\tests\TestRuntimeServices.py
.\run_tests.ps1 -Group all
```

新增测试已登记分组并执行专项与全量回归。以下原计划条目保留作为验收清单；实施状态以文首执行更新及执行记录为准，不代表所有实机场景已验收。

每批代码实施时：

- [ ] 核对最新版本、远端标签和用户修改；当前基线 1.33.02，单纯小修下一候选可为 1.33.03，但实施时重新核对，不能抢占其他任务版本。
- [ ] 新增失败回归 → 最小修复 → 聚焦测试 → 全量 → 版本/包校验。
- [ ] 同步 `config.py`、`更新日志.md`、程序结构与整改记录；新增覆盖文件确保进入源码包/安装器及相关测试清单。
- [ ] 按 AGENTS.md 创建提交、匹配的固定宽度注解标签并推送，核对 CI/Release；不改写 1.33.01 或 1.33.02。
- [ ] 实机验证仅在另行明确的受控场景进行，报告环境和输入结果。离线通过不等于实际账号正确、WGC 全兼容或 F9 一定无冲突。

## 7. 当前可采取的临时措施

1. 单独运行 Daily 前核对游戏内账号与所选方案，重点确认体力用途和聚落列表。不要靠“先运行一轮多账号”来修复持久选择。
2. 中文星期缺陷修复前，不要直接编辑受保护的 published/master 文件；界面若无法保留标准星期值，周常先人工检查，不用破坏完整性来临时绕过。
3. 再遇长期 no frame 时先停止业务任务、恢复游戏窗口并用现有刷新入口确认截图恢复，再决定重新启动；仅窗口 visible 不代表已有新帧。
4. F9 注册失败时使用界面停止按钮；若需要可在设置中选择未冲突的受支持热键并验证。当前日志不能指定哪个外部程序占用了 F9。
5. 后续定位优先补：14:36–14:39 切号停止证据目录的脱敏事件/帧、当时有效配置图的脱敏导出、三次技能未确认片段。缺少这些材料不妨碍先实施 T1–T5 的确定边界修复。

**原分析阶段交付：** 日志核验、源码对照、四组离线分支探针和上述修改方案。后续代码实施见文首执行更新。
