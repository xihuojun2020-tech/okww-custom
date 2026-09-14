# 1.72.00 稳定等待推广：实施、覆盖与使用端交接

日期：2026-09-14。基线：89a7e337 / 1.71.00。工作在独立目录 okww-navigation-rollout 完成，未修改其他会话的账号数据或历史报告。

## 范围与结论

本次落实可根据现有页面识别核验的导航，并加固后台调度、活动消费和材料分页。用户明确要求跳过领域结算、乐园周常和声骸融合，这三项生产代码未修改；乐园曾尝试的积分判断已撤回。其他未迁移细目仍列为未完成，不能用公共 helper 接入代替整模块验收。

没有运行游戏输入、消耗体力或操作实际账号；没有审阅诊断 ZIP。NAS 根目录和证据交换目录的只读盘点不代表完成诊断审阅。

## 已实现行为

1. 后台 advance 每次调用观察当前帧，至多提交一次输入，无 sleep/取帧等待循环。记录操作、窗口、账号、分辨率和执行器所有权；旧帧不计稳定，其他任务实际接管后终止旧步骤。异常锁定 pending，后续 tick 不自动重开预算；关闭对应任务清理 pending。
2. 自动登录继续复用 wait_login 与经过验证的 SendInput 边界，同步切号默认分支不变。登录按钮保留 4 秒等待自动登录的机会；重启提示等待分散到后续 tick，不再后台等待 90 秒。月卡展示与继续按钮分步；真实重启和月卡流程待实机验收。
3. 快速旅行与传送确认分两步，确认弹窗必须具有传送文案和已知控件。只识别到移除标记时不点击。传送源页锁定右侧标题区 OCR 内容，标题区空白停止；它不等价于验证调用方预期的 Boss ID。
4. 跳剧情分为请求跳过、确认跳过，单次触发不连续点击两页。通用确认必须发生在本任务已发起跳过之后；跳过请求单次提交并等待，不反复跳到下一句。
5. 初露峥嵘保留 5/6 槽位、归一化坐标、第六人拖拽、介绍页 Esc 和右侧黑框确认。入口、试用进入、退出弹窗和返回活动页复用稳定导航；完成与领奖仍使用原专用核验。
6. 周本单人挑战前验证 Boss 名称，开启挑战只提交一次并允许 120 秒加载；结算退出保留挑战成功、按钮与奖励数量的原强识别。编队终态目前证明开启挑战按钮存在，没有新增编队页 Boss 标题核验。
7. 深境区入口用中间卡片标题定位同卡片前往，三塔总览为终态。现有深塔取消选择、能量与结算返回的专用保护不改。
8. 无音危机下一波确认、离开商店、死亡重开接入来源/终态核验。离开商店未确认不能返回成功，从而不能通过再次进入 handler 重置刷新预算。
9. 活动消费必须有明确正价格、余额及即时价格复查，提交前持久化待核实标记并读回 JSON。扣款后同一页面两次读到 balance-cost 才清标记。未知、异常或停止不再提交；零价格不能用余额差证明结果，因此停止。锁定按钮作为切换状态只点一次，已锁不点，未验证锁定不购买。
10. 材料列表保留既有上移 16 次、扫描 60 页的边界，新增页面/培养目标和材料条目签名比较。空白未知页不能形成边界；已识别的空列表也会保守停止。相同语义与像素仍不能独自区分到达边界与滚动完全失效，可靠滚动条证据仍待补齐。

## 35 文件覆盖矩阵

“保留”表示现有专用流程未重写；“间接”只代表走到公共 helper 时受益，不表示整个任务完成迁移。

| 文件 | 本次状态与边界 |
| --- | --- |
| AutoAbyssTask | 深境区前往接入；选塔选层、编队和结算返回保留专用流程，其他导航未统一 |
| AutoCombatTask | 实时战斗排除，不增加导航重试 |
| AutoLoginTask | 后台分帧接入；实机重启/月卡待验收 |
| AutoPickTask | 实时拾取排除 |
| BaseCombatTask | 战斗与恢复保留；公共传送调用间接受益 |
| BaseWWTask | 开书首批已接入；本次传送接入；内部页签、序号选行、通用挑战入口仍未迁移 |
| ChangeEchoTask | 未注册，保持隐藏，未推广 |
| CharacterTrialTask | 入口、进入、退出接入；槽位和领奖保留专用流程 |
| DailyTask | 任务页留档为首批接入；战令、邮件、周常/聚落截图目标识别仍待补齐 |
| DiagnosisTask | 未注册，保持隐藏，未推广 |
| DomainTask | 用户要求跳过领域结算；消费预算与恢复原样保留 |
| EchoesRemainTask | 首批四步接入，本次回归，不自动开战 |
| EnhanceEchoTask | 未注册，保持隐藏，消费不推广 |
| EventTask | 下一波/重开导航、锁定结果与消费持久化接入；卡牌商品语义身份仍待补齐 |
| FarmEchoTask | 公共开书/传送间接受益；序号选择、难度与 Boss 专用入口未统一 |
| FarmMapTask | 未注册，保持隐藏，未推广 |
| FastTravelTask | 后台分帧及独立传送确认接入 |
| FiveToOneTask | 未注册，保持隐藏，不加入融合重试 |
| ForgeryTask | 公共开书/传送间接受益；凝素行与直接挑战入口未迁移；结算跳过 |
| GardenTask | 按用户要求跳过，生产代码无修改 |
| KRLauncherSwitchTask | 弃用入口保持弃用，不恢复 |
| MaterialPlannerTask | 页面/目标/条目检查新增；像素边界判定未彻底替换，事务保持 |
| MergeEchoTask | 按用户要求跳过，生产代码无修改 |
| MouseResetTask | 鼠标复位不属于页面转换，不推广 |
| MultiAccountDailyTask | 保留生产选中/复核/登录有限重试，不另写账号切换实现 |
| NightmareNestTask | 首批去掉开书外层重试；公共传送间接受益，列表身份未迁移 |
| PianoTeachingTask | 实时音游排除 |
| SecondSolTask | 实时音游排除 |
| SimulationTask | 公共开书间接受益；材料入口仍是原流程，结算跳过 |
| SkipBaseTask | 同步默认行为保留，新增后台非阻塞分支 |
| SkipDialogTask | 跳过/确认分帧，消息输入返回已处理，记录调度所有权 |
| TacetTask | 公共开书/传送间接受益；结算按用户要求跳过 |
| TestAccountSwitchTask | 不另写切号实现；继续生产方法代理，A1/A3/A4及别名回归 |
| WeeklyBossTask | 单人/开启/结算退出接入；指南目标和消费保留专用流程 |
| WWOneTimeTask | 保持原公共生命周期 |

## 尚未完成的细目

- B/C：指南具体页签的选中证据、序号行实际目标 ID、模拟/凝素/聚落/刷声骸专用入口；仅有按钮或固定坐标不能证明选对目标，因此没有添加自动重试。
- B/F：战令、邮件、聚落/乐园留档目标与领取完成证据。没有把旧“执行坐标即成功”宣传为已修复；领奖流程未扩大重试。
- C：材料滚动失败和实际边界的可靠区分。新增语义签名只能减少错误，不能消除这个证据缺口。
- D/E/G：深塔其余专用步骤、切号专用诊断尚未全部映射到统一工具页；工具页只有实际接入步骤才显示统一导航摘要。
- 用户跳过的领域结算、乐园周常和融合不安排本轮实机采集，继续保持原行为。

## 无音危机消费保护的恢复

停止任务后先核对游戏余额、商品/刷新结果和错误前后截图，保存判断报告。任务配置中 `_pending_event_spend` 记录 page、cost、balance、created_at；非空时新启动也阻止消费。不要删除整个配置文件、重建账号或清除账号主配置。

使用端 AI 在明确核实这一次结果后，关闭 OKWW，备份实际数据目录中包含此键的任务 JSON，再仅将该键改成空对象 `{}`；保持其他键和编码不变。重启后先人工核对页面再启动任务。不能以“想继续运行”为由自动清空；若无法核实，保留标记并停止该活动。该标记默认值必须是对象，不能改成 null，否则框架类型校验可能在重载时重置它。

## 使用端更新与验收

NAS 仅用 `\\192.168.3.173\羲火君 共享给我\AI诊断`。先关闭旧主程序，通过局域网 stable 更新至 1.72.00，核对程序内版本、latest.json 及 ZIP SHA256。更新包不含文档，AI 从同一 NAS 的 AI交接目录读取本报告。

- 1080P 和 2560×1440 分别验收：丢首击后仅在原页补点、切入加载后不继续点、手动换页/改分辨率后停止。
- 后台登录/跳剧情/快速旅行分别单独启用，再与其他后台任务组合；检查任务切换后旧 pending 不继续操作。不要同时人工操作与自动操作来验证消费。
- 初露峥嵘检查介绍页 Esc、黑框确认、5/6 人模式；周本只在用户已有消费授权时验收领取。
- 活动购买只核验一次已授权操作；结果未知必须停止，重启仍应阻止重复。确认工具页导航摘要、诊断上传成功/失败明细与现有卡片样式一致。
- 多账号切换使用正式 TestAccountSwitchTask，默认 A1、A3、A4，覆盖备用登录名和掩码手机号；不得将测试账号映射写回用户账号配置。

## 自动验证

40 个测试文件共 630 项通过。覆盖共用状态机、1080P/2K 合成输入、缓存帧、停止和身份变化、后台一步一输入、活动真实 Config 重载/静默写失败、周本/试用/深塔导航，以及账号、体力政策、材料事务回归。真实若梦、周本、深塔截图识别测试通过；图像套件退出时已有 gc ResourceWarning，不是测试失败。

TestMergeEchoTask 中的每日参数校验测试补齐 executor 并隔离真实账号运行时初始化，使其检查目标恢复为参数校验；没有改变融合生产逻辑。TestVisionOptimization 的静态页夹具补上已识别材料，避免用空奖励页证明扫描成功。

下列自动测试不能证明真实游戏输入必达、NAS 使用端安装成功、所有页面均已接入或实际资源消费结果。游戏实机验收尚未执行。

| 测试文件 | 用例数 | 结果 |
| --- | ---: | --- |
| TestUITransition | 16 | passed |
| TestNavigationAdapter | 11 | passed |
| TestTriggerNavigation | 8 | passed |
| TestBackgroundNavigationTasks | 6 | passed |
| TestAutoLoginTicks | 5 | passed |
| TestTravelTransitions | 5 | passed |
| TestTaskEntryTransitions | 4 | passed |
| TestEventSpendSafety | 14 | passed |
| TestWeeklyTransitions | 4 | passed |
| TestCharacterTrial | 41 | passed |
| TestVisionOptimization | 4 | passed |
| TestMaterialPagingSafety | 3 | passed |
| TestMaterialIntegration | 6 | passed |
| TestMaterialVision | 5 | passed |
| TestMaterialRepository | 4 | passed |
| TestMergeEchoTask | 19 | passed |
| TestAutoAbyssTask | 101 | passed |
| TestAbyssCancelRetry | 8 | passed |
| TestAbyssReturnImages | 1 | passed |
| TestAccountSwitch | 7 | passed |
| TestAccountSwitchEvidence | 15 | passed |
| TestMultiAccountDailyTask | 112 | passed |
| TestWin32LoginInput | 13 | passed |
| TestWaitLogin | 7 | passed |
| TestDailyActivityFlow | 10 | passed |
| TestDailyTaskStatus | 4 | passed |
| TestDailyReservePolicy | 9 | passed |
| TestStaminaAccounting | 13 | passed |
| TestDomainRecoveryLoop | 11 | passed |
| TestForgeryDomainLabels | 2 | passed |
| TestAutoCombatRecovery | 13 | passed |
| TestAccountFeatureVerification | 19 | passed |
| TestWeeklyBossTask | 46 | passed |
| TestWeeklyNavigation | 13 | passed |
| TestWeeklyDailyIntegration | 12 | passed |
| TestSkipDialogConfirm | 4 | passed |
| TestEchoesRemainTask | 24 | passed |
| TestEchoesRemainImages | 1 | passed |
| TestWeeklyBossImages | 11 | passed |
| TestNightmareNestTask | 19 | passed |

## 发布核验结果

- 代码提交：c53c6fd5；注释标签 v1.72.00 已推送 GitHub，codex/task-navigation-rollout 与原工作分支 codex/account-switch-foreground-bitblt 均已推送。
- 原工作区已快进到该提交，原有历史文档删除、修改和未跟踪文档保留。
- NAS stable/latest.json 实读版本为 1.72.00；更新包验证 392 个文件，用户配置保留检查通过。
- ZIP：OKWW-Updates/stable/releases/v1.72.00/okww_update_v1.72.00.zip，37,847,479 字节。
- SHA256：`2dfefd02eae461fefe56de4949aac1faf68413c54e71f3d023b2de10315339fe`，已读取 NAS 实际文件计算并与索引比对。
- 发布时刻：2026-09-14 19:37:32（北京时间）。交接报告存入同一 NAS 的 `AI交接/2026-09-14-navigation-rollout-1.72.00.md`。
- GitHub 安装器构建结果及另一台电脑实际安装/运行未核实；NAS 更新包已独立验证，不把标签推送当作安装器构建完成。
