# 1.73.00 稳定等待推广续作与使用端交接

日期：2026-09-14。基线 efc96411 / 1.72.00。仍使用隔离工作树，未改实际账号配置，不执行实机点击或消费。

## 本次落实

| 原未完成项 | 本次实现 | 验证边界 |
| --- | --- | --- |
| 指南内部页签 | 简体中文六个可见页签通过素材获取标题、唯一页签名、浅色选中底色、右侧前往/直接挑战/挑战控件核验；使用新帧按钮中心与共用预算 | 真实凝素截图证明六个页签的文字位置和选中/未选中底色。其他五页完整选中后的实机效果仍需验收；不是序号行目标 ID 核验 |
| 周本目标详情 | 自动首项及指定 Boss 搜索结果均委托同一 `_open_weekly_target`；锁定同名同排按钮，目标必须是对应 Boss 标题和单人挑战按钮 | 错详情立即停止；转换超时不是 WeeklyPageTimeout，外层不会重新开书扩大此步三次输入预算。滚动搜索本身保留原限制 |
| 深塔完成编队 | 来源详情+完成，终态编辑队伍+开启挑战；丢点击可在原页有限重试 | 仍先由原方法验证三人选择；没有添加开启挑战点击，其他选塔选层步骤保留专用流程 |
| 切号/深塔统一诊断 | 原账号选择和深塔结算返回外围仅增加诊断观察，不改输入、匹配、返回值、异常或重试循环 | 切号显示选择轮次，不冒充实际点击次数；专用等待没有统一总秒数时显示专用等待预算；不记录目标账号或异常正文 |
| 材料列表边界 | 培养目标与仓库同时要求语义/图像不变及对应滑块位于端点，滑块在中间则停止并保留图像 | 仅支持已核验的16:9轨道。滚动条缺失/布局不匹配不会推测到头；奖励结算扫描不改 |

本版把上述变化应用到 [1.72.00 的35文件矩阵](2026-09-14-navigation-rollout-1.72.00.md)：BaseWWTask、WeeklyBossTask、AutoAbyssTask、MultiAccountDailyTask、MaterialPlannerTask 的覆盖增加，其余文件状态沿用。DailyTask 的聚落留档调用现在会等待已选中聚落页签和列表控件，但没有新增聚落完成数量判定。

## 使用的页面依据

- `tests/images/materials/17_02_22.png`、17_02_46、17_03_02、17_03_16：完整素材获取页，凝素选中，其余页签未选中。实际名称/OCR 为残象聚落，业务键 canxiang 不变。
- `17_29_48.png`：仓库资源页滑块到顶；`17_29_58.png`：滑块在中间；`17_30_02.png`：滑块到底。
- `13_33_40.png`、`13_33_50.png`：培养目标顶部和底部。轨道与左侧页签滚动条区分，防止误取另一根滚动条。
- 周本 list1 图像左侧曾脱敏为黑色，不能证明页签已选中；专门测试这种图像返回未知。素材截图的滑块测试将原有720P夹具缩放为1080P、1440P进行验证，不能据此宣称拥有两种原生分辨率截图。
- 深塔完成使用既有生产页面契约：角色列表左上是“详情”，不是“快速编队”；编辑队伍页同时要求“编辑队伍”和“开启挑战”。

## 保护与限制

- 用户明确跳过领域结算、乐园周常和声骸融合，其生产逻辑没有改动。领域收益扫描保持原行为；本次滚动条检查只用于 inventory/target 场景。
- 材料上移16次、最多60页的原预算未扩大；滚动条读不到，包括某些无滑块的短列表，将保守停止，不记录完整扫描。培养目标已到声骸培养分类时继续使用原语义终点，允许此时没有完整材料格。
- 共用指南页签只迁移简体中文六项，梦魇入口和其他语言沿用原逻辑。它验证所选类别，不验证该类别某个序号对应的具体 Boss/副本。
- 诊断观察不添加游戏输入，不读取额外图像，不修改账号切换实现。TestAccountSwitchTask 继续调用生产账号方法，默认 A1→A3→A4 和别名/掩码手机号测试保留。
- 界面沿用工具页原诊断卡片，无新弹窗、卡片或风格变化。切号显示“选择轮次”，深塔显示“输入尝试”，避免把多次查找说成多次点击。摘要只保存错误类型。

## 仍未完成

1. 按序号挑选副本的真实目标 ID，以及模拟/凝素/刷声骸/聚落各自的专用挑战入口；目前仍保留旧方法，不因为共用页签接入就宣称整模块迁移。
2. 战令/邮件的完整页面与领取完成证据；其他非任务页截图的所有终态仍未全量重做。
3. 深塔其他专用选塔、选层、返回和切号登录/退出的统一摘要未全部覆盖。本次只增加明确的账号选择与结算返回观测。
4. 新页面布局、非16:9、无滚动条的短列表及除凝素外各类别选中效果需使用端实机验收。

## 使用端 AI 操作

从唯一 NAS `\\192.168.3.173\羲火君 共享给我\AI诊断` 的 AI交接目录读取本报告及1.72.00消费保护恢复说明。关闭旧程序后通过局域网 stable 更新，确认程序版本1.73.00以及更新包SHA256。

依次验证：凝素/模拟/讨伐/战歌/无音/聚落六页签；重复进入已选中页签应零点击；切页延迟时只等待。然后运行材料读取，滑块仍在中间而画面不变应停止，不能生成“完整”结果。深塔完成编队必须停在编辑队伍页，不自动开战。工具页应看到切号选择轮次及深塔返回结果。

在1080P与2560×1440分别验收，保留包含标题、选中底色、右侧列表和滚动条的完整画面；涉及账号内容继续使用现有诊断脱敏。不要为验证本版去运行用户已跳过的三类任务，不修改账号、体力和活动消费授权。

## 回归结果

37 个测试文件、522 项通过。失败排查期间的旧夹具已改为调用新的生产导航入口：周本搜索仍验证搜索边界，具体重试/错详情由 TestWeeklyTransitions 验证；深塔完成采用真实导航适配器的合成输入测试。诊断存储失败不改变成功结果，不吞用户停止异常。没有审阅诊断ZIP，未进行实机消费或确认使用端安装成功。

| 测试文件 | 用例数 | 结果 |
| --- | ---: | --- |
| TestAbyssCancelRetry | 8 | 通过 |
| TestAbyssReturnImages | 1 | 通过 |
| TestAbyssReturnRecovery | 7 | 通过 |
| TestAccountFeatureVerification | 19 | 通过 |
| TestAccountSwitch | 7 | 通过 |
| TestAccountSwitchEvidence | 15 | 通过 |
| TestAutoAbyssTask | 101 | 通过 |
| TestAutoLoginTicks | 5 | 通过 |
| TestBackgroundNavigationTasks | 6 | 通过 |
| TestBookTabImages | 3 | 通过 |
| TestBookTabTransitions | 3 | 通过 |
| TestDailyActivityFlow | 10 | 通过 |
| TestDailyReservePolicy | 9 | 通过 |
| TestForgeryDomainLabels | 2 | 通过 |
| TestMaterialIntegration | 6 | 通过 |
| TestMaterialPagingSafety | 3 | 通过 |
| TestMaterialRepository | 4 | 通过 |
| TestMaterialScrollEdges | 4 | 通过 |
| TestMaterialVision | 5 | 通过 |
| TestMultiAccountDailyTask | 112 | 通过 |
| TestNavigationAdapter | 11 | 通过 |
| TestNavigationSections | 2 | 通过 |
| TestNightmareNestTask | 19 | 通过 |
| TestSpecialistNavigationStatus | 3 | 通过 |
| TestStaminaAccounting | 13 | 通过 |
| TestTaskEntryTransitions | 6 | 通过 |
| TestTaskNavigationClassification | 2 | 通过 |
| TestTriggerNavigation | 8 | 通过 |
| TestUITransition | 16 | 通过 |
| TestVisionOptimization | 4 | 通过 |
| TestWaitLogin | 7 | 通过 |
| TestWeeklyBossImages | 11 | 通过 |
| TestWeeklyBossTask | 46 | 通过 |
| TestWeeklyDailyIntegration | 12 | 通过 |
| TestWeeklyNavigation | 13 | 通过 |
| TestWeeklyTransitions | 6 | 通过 |
| TestWin32LoginInput | 13 | 通过 |
