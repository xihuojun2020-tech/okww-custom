# 全任务稳定等待与重试：适用清单和设计方案

状态：1.71.00 已完成首批公共层与部分导航接入，尚未全量实施。原盘点基线为 `3b75ddf1` / 1.70.07；实际逐文件覆盖及使用端验收见 [首批实施报告](../reviews/2026-09-14-navigation-rollout-1.71.00.md)。

## 结论与盘点口径

可以推广，但应推广“识别来源页—稳定目标—执行一次—核验结果—有条件重试”的流程，不能让所有 click、send_key 或任务 run 自动重试。

本次按 config.py 的实际注册表（排除注释）及 src/task 下全部 `*Task.py` 盘点：18 个一次性入口、6 个后台入口，共 24 个注册任务；另有 5 个公共任务基类和 6 个未注册/隐藏模块，共覆盖 35 个任务文件。FarmMapTask.py 中的 BigMap 一并纳入。没有发现 ok_tasks 下可供盘点的现存脚本；用户设备后续加载的自定义任务、src/char 角色循环不等于本次已逐项接入。

24 个注册入口中，19 个有导航或流程核验推广点（含仅复用生产逻辑的切号测试入口）；另 5 个主循环不直接采用页面重试：自动战斗、自动拾取、鼠标复位、弹琴、第二索拉。自动战斗的复活/传送可在公共战斗基类单独受益。这些数量表示适用分类，不表示已修改完成。

盘点结合 AST 输入调用定位和关键函数人工阅读；附录列出源码定位。静态调用扫描不证明实际点击成功率，也不是游戏内全任务验收。

## 现有可复用能力与缺口

| 位置 | 已有能力 | 推广时要保留或补齐 |
| --- | --- | --- |
| EchoesRemainTask._click_transition | 三帧稳定、OCR 中心归一化、最多三次、目标页优先、前后截图、延迟切页不补点 | 目前在活动类内；各轮各自计时，尚无跨嵌套总预算；需更明确的未知/加载态、动作分类和诊断限额 |
| AutoAbyssTask._return_from_result | 新帧、30 秒总等待、最多三次返回 | 保留塔/层上下文，不能用通用 3 秒取代加载等待 |
| AutoAbyssTask._click_character_record / _cancel_character_selection | 身份重定位、选中标记复核、取消失败有限重试 | 选中和取消属于目标状态操作，不等同打开页面 |
| MultiAccountDailyTask._select_account_with_retry | 展开列表、输入投递结果、账号稳定核对、诊断阶段 | 保留 Windows 控件与屏幕坐标转换、前台与输入后端，不强行转为游戏画面 OCR |
| CharacterTrialTask._stable / _claim | 稳定状态、领奖前后角色复核、已完成状态 | 进入/退出可补点击恢复，领奖不能用按钮仍在作为重复依据 |
| WeeklyBossTask._stable_value / _confirm_claim_if_needed | 资源读数稳定、费用比对、确认仅一次 | 保留领取后等待结算和余额核验，结果不明不再次挑战 |
| BaseWWTask.use_stamina | 余额核验、备用额度、pending_conversion、结果不明停止 | 不包裹自动重试，不重置消费状态，不重跑整段刷本 |
| NightmareNestTask._open_book_with_retry | 打开 F2 失败后返回主界面有限恢复 | 避免外层 3 次×公共层 3 次放大；区分页面失败和停止/身份异常 |
| DailyTask.claim_daily | 点击后新帧检查按钮，一次补点 | 补同一账号/日期/奖励目标证据，取消不确定页面的坐标兜底重试 |

## 按动作后果划分策略

| 类别 | 例子 | 重试规则 |
| --- | --- | --- |
| N：页面导航 | 打开指南、选择分类、活动前往、单人挑战、返回总览 | 必须确认仍是同一来源页及同一目标，目标页未到达才补点 |
| S：设置目标状态 | 选角色、取消角色、锁定、勾选“不再提醒” | 先读当前状态；已达目标直接成功；同一对象且明确未改变才补点；未知停止 |
| C：领取或消耗 | 体力领取、备用转换、商店购买/刷新、融合、强化 | 一次提交后核对余额/库存/批次/结算；结果不明停止，不自动重放。免费领取也需证明同一奖励未领取 |
| P：分页与拖拽 | 指南列表、角色列表、材料列表、头像横条 | 确认列表内容及位置变化；每次重新定位目标；无变化有限调整；到顶/到底停止 |
| R：实时输入 | 战斗技能、拾取 F、跑图移动、节奏按键 | 不接入页面级稳定等待；保留领域专用节奏和恢复 |

“按钮还在”“窗口没报错”“颜色看起来一样”均不足以证明一次消耗或选择未生效。导航已到目标页即成功，也不能据此写入任务通关、领奖或完成检查记录。

## 全量注册任务清单

P0 为首批公共与高频入口；P1 为随后分模块接入；P2 为有副作用动作专项；P3 为保持现状/未来启用时处理。优先级不代表任务重要程度。

| 注册任务 / 文件 | 具体可推广位置 | 必须核验的成功状态与保护 | 计划 |
| --- | --- | --- | --- |
| 每日 DailyTask | open_daily、_open_record_page、claim_battle_pass、claim_mail、claim_daily | 每日/周常页签与页名；活跃度达标不等于奖励已领；截图前确认真实目标页；每份奖励按账号和日期识别 | P0 导航，P2 领奖 |
| 刷声骸 FarmEchoTask | teleport_to_configured_boss、enter_configured_boss_realm_from_f、click_configured_boss_level、teleport_to_nearest_boss、teleport_to_octagon_boss、scroll_and_click_buttons、manage_boss_interactions | Boss/等级/传送目标一致、加载完成；F/重开前重读交互；不重复战斗和宝箱消费 | P1 N/P，交互逐类审查 |
| 梦魇与残像聚落 NightmareNestTask | _open_book_with_retry、_travel_to_nest_or_skip、find_nest、go_nightmare_scroll、combat_nest 的入口 | 目标聚落与列表身份不变，传送后大世界确认；接续捕获/战斗保持原逻辑 | P1，消除嵌套重试 |
| 无音区 TacetTask | farm_tacet 的指南、挑战、再次挑战、返回；teleport_to_tacet | 目标无音区一致；再次挑战与退回区分；use_stamina 预算、活跃度满禁止备用、余额确认不变 | P0 共用入口，P1 结算导航 |
| 凝素领域 ForgeryTask | teleport_into_domain、purification_material 的菜单/材料入口 | 领域/等级及材料目标一致，传送和编队目标页明确；消费仍归 DomainTask/use_stamina | P0 |
| 材料规划 MaterialPlannerTask | scan_target、scan_inventory、enter_forgery、_pages | 培养对象、材料 group_id/weapon_type、列表页和目标版本；缺样本/覆盖不足继续停止消费 | P1 N/P；不重放领取事务 |
| 模拟训练 SimulationTask | teleport_into_domain 的分类、目标、前往、挑战 | 共鸣者经验/武器经验/贝币目标一致；固定行号操作改为先核对列表和条目 | P0 |
| 多账号每日 MultiAccountDailyTask | _switch_to_login、_wait_login_screen_stable、_open_account_list、_select_account_with_retry、_click_login_for_target | UUID/短名及备用名、掩码手机号准确匹配；选中成功不等于已登录；新窗口重新定位；配置 revision 变化立即终止本轮 | P1 专用路径补缺，不替换全部切号实现 |
| 合并废弃声骸 MergeEchoTask | open_merge_page 的六步导航；merge_full_batch 的选择状态和结果 | 页签/筛选器；100/100 当前批次、废弃条件、选择集合；融合确认属于 C，不重复提交 | P1 导航，P2 融合 |
| 周常乐园 GardenTask | open_garden_weekly_page、run 的奖励/祝福/返回/重开、_choose_first_blessing | 每周页、祝福目标、结算与已达上限状态；取消选择/领取不能用双击代替核验 | P1 导航，P2 选择/领奖 |
| 悲鸣行动：无音危机 EventTask | _select_and_confirm、_handle_confirm_next_wave、_click_restart；_handle_shop_screen、_click_lock、购买/刷新 | 波次与卡片身份；锁定属于 S；购买和刷新属于 C，价格/货币未知不得扩大重试；旋转走位不动 | P1 N，P2 S/C |
| 切号测试 TestAccountSwitchTask | run 通过 _get_multi_account_task 调用生产切号 | 不新增平行实现；连续默认 A1→A3→A4，准确短名及备用名/掩码手机号覆盖 | 随切号修改同步 |
| 深塔 AutoAbyssTask | _open_period_challenge、_open_adversity_tower、_open_tower、_verify_floor_state、_click_start_challenge、_finish_team_formation、返回路径、角色分页 | 塔/层/编队角色身份与能量；已选不反向取消；战败不标通关；已有取消/结算重试保留 | P0/P1 补缺、统一诊断 |
| 周本 WeeklyBossTask | _open_weekly_book、_select_target、_enter_challenge、_leave_settlement、_confirm_list_top | 周本名称、等级、剩余次数、挑战入口；领奖确认保持仅一次，结果不明不重开 | P1 N/P；C 仅核验增强 |
| 弹琴 PianoTeachingTask | 仅将来新增的页面准备步骤可用 | _press_event/run 音符时序不可增加 0.7 秒页面等待；保留按键释放 | P3 主循环排除 |
| 第二索拉 SecondSolTask | 当前无自动导航；手动进入后持续按 F | 前台检查、短按和手动停止保持原义；不能把连续 F 改成“页面未变化就重试” | P3 主循环排除 |
| 若梦仍有回声 EchoesRemainTask | 已有三处导航；_open_event 活动列表；run 的“完成返回编队” | 活动、关卡、试用三人、完成页；已实现作为种子，补完成按钮前后关卡检查；不自动开启挑战 | P0 首个公共接入基准 |
| 初露峥嵘 CharacterTrialTask | _open/_select_activity、_enter、_wait_trial_map、_leave/_confirm_trial_exit；_select 头像翻页 | 5/6 人配置、角色槽位/页面、介绍页“下一页+X”、试用地图/结算；领奖前后同角色状态，不全屏点“确认” | P1 N/P，S/C 专用 |
| 自动战斗 AutoCombatTask | 仅继承的复活弹窗、传送治疗可间接受益 | _run_combat/realm_perform、角色技能循环保持原恢复；不得自动重启整场战斗 | P3 主循环排除 |
| 自动拾取 AutoPickTask | 当前 send_fs/run 高频交互不套用 | 场景识别与拾取触发保留，不能给每个 F 等待页面变化 | P3 主循环排除 |
| 自动登录 AutoLoginTask | run→BaseWWTask.wait_login | 保留登录画面分类、前台/窗口及月卡处理；不得与多账号切换争夺操作；验证进入游戏而非仅投递点击 | P1 专用适配 |
| 自动跳剧情 AutoDialogTask（SkipDialogTask.py） | SkipBaseTask.check_skip/skip_confirm；skip_message | 仅已识别跳过/对话界面；下一句属于新步骤，非同一按钮重试；不得点击购买/退出等同名确认 | P1 轻量适配，不能阻塞后台数秒 |
| 快速旅行 FastTravelTask | run→click_traval_button | 地图/传送目标有效、按钮类别确定、加载后大世界；remove_custom 与旅行不能混为成功 | P0 共用导航，后台分帧处理 |
| 鼠标复位 MouseResetTask | 无导航业务入口 | 20Hz 纠偏与延时回调独立，不包装为点击重试 | P3 排除 |

## 公共基类与未注册模块

| 文件 | 处理范围 | 结论 |
| --- | --- | --- |
| BaseWWTask | open_esc_menu、openF2Book、open_boss_book、click_on_book_target、wait_click_travel/click_traval_button、click_team_challenge、ensure_main、wait_login、月卡、调时间 | P0 最大收益点。只在具体语义入口适配；click/send_key/scroll 底层保持单次输入。领取/备用转换沿用独立策略；确认弹窗必须带上下文 |
| BaseCombatTask | close_revive_popup、revive_at_tower_and_heal、_travel_to_nearest_waypoint | P1 复活/治疗导航；send_key_and_wait_animation、switch_next_char、寻敌/战斗走位不接入 |
| DomainTask | revive_action、make_sure_in_world、farm_in_domain 结算重开/退出 | P0/P1；不可在超时后重新跑 farm_in_domain 整段，不清空 must_use、planner 领取意图和备用锁 |
| SkipBaseTask | skip_confirm、try_click_skip、check_skip | P1 专用轻量确认；有对话身份、页面与下一句变化判据，非任意确认按钮 |
| WWOneTimeTask | run 启动公共准备 | 不增加整任务重试；按调用链使用 BaseWWTask 适配 |
| ChangeEchoTask（隐藏） | 属性修改入口、数据重构、确认 | N 可设计，重构为 C；无材料与结果证据不启用自动重试，也不恢复注册 |
| EnhanceEchoTask（隐藏） | 强化页、材料选择、强化调谐、锁定/丢弃 | N/S/C 分开；锁定需目标状态，强化/丢弃禁止盲重放；维持隐藏 |
| FiveToOneTask（未注册） | 数据坞/筛选/批量融合 | 仅整理，未来启用时按 MergeEcho 专项处理；不假定无调用就可删除 |
| FarmMapTask 与 BigMap（未注册） | load_stars 地图开关、go_to_star 开始前定位 | N/P 可用；路径移动/镜头方向为实时控制，不套导航重试，不主动注册 |
| KRLauncherSwitchTask（废弃/未注册） | 历史登录画面与屏幕点击 | 不复活旧切号实现；修复以 MultiAccountDailyTask 生产路径为准 |
| DiagnosisTask（未注册） | choose_level 等辅助入口 | 如将来启用再适配；性能测量主循环不加人为等待，否则改变测量结果 |

## 最小共用设计

建议新增 `src/task/ui_transition.py`，只包含同步流程执行器、策略和结果类型；BaseWWTask 提供薄包装，各任务提供来源/目标识别、对象身份和已有输入方法。先迁移 EchoesRemainTask 验证等价，再推广，避免在各任务复制三轮循环。

接口概念（不是本轮已实现代码）：`run_transition(task, step_id, observe, act, policy, guard, diagnostic)`。observe 消费调用方取得的同一新帧，返回明确枚举与目标标识、可选按钮；act 只执行一次授权动作，不自行等待或递归重试。关键约束：

1. **先观察是否已到目标**，成功立即返回，不点击“完成”或其他当前位置按钮。
2. `SOURCE_READY / TARGET_READY / LOADING / UNKNOWN / CONTEXT_CHANGED` 分开。UNKNOWN 只等待到预算耗尽；LOADING 只等待，不重复 F1/F2/Esc。来源与目标同时满足视为歧义，禁止点击。
3. 稳定判断使用页面锚点、目标 ID、按钮位置及必要业务值；不要求全画面像素不变。动画、水面、鼠标和 FPS 叠层不能破坏稳定判据。相同缓存帧不能被数成三次独立观测；使用捕获序号/时间而非仅图像哈希。
4. 默认导航 3 次连续观测、间隔 0.25～0.35 秒、中心偏差≤归一化 0.005；这是初值，逐页面按样本校准。辨认出文字不等于按钮已可交互，须结合页面/遮挡/控件状态。模板入口不强制改 OCR。
5. guard 在取帧后、动作前及等待期间执行：任务取消、暂停、账号/配置 revision、游戏窗口、关卡/材料目标、输入所有权。系统中断、身份错误、资源不明不当作点击失败重试，不自动重启程序。
6. 普通导航初始总预算建议 15～20 秒，最多三次输入；传送/加载用已有调用方超时（如 30/120 秒），输入次数仍有上限。所有子步骤消费同一单调时钟剩余预算；不能 3×3×3 重试放大。领域恢复和页面输入恢复分别记次数。
7. 使用 OCR/模板在当前新帧定位按钮中心，经项目已有游戏客户区坐标转换；归一化点必须属于识别框和有效画面。窗口尺寸变化后重新定位，旧坐标失效。不能把登录弹窗桌面绝对坐标除以游戏帧宽高。
8. 目标页要求有业务锚点：单人挑战到编队要核对关卡；材料副本核对材料类型；指南核对页签；切号核对账号。按钮消失不是充分成功证据。
9. 返回结构化结果：status、attempts、elapsed、source/target、target_id（脱敏）、evidence_ids；用类型化异常区分超时/上下文变更，替代字符串比较异常。识别值可能为 0/False/NumPy 数组，不能依赖任意对象真值决定成功。
10. 不在通用层自行按 Esc、Alt、切回大世界或点击同名“确认”。恢复动作由任务显式提供且有界；按住的键和鼠标由原 finally 释放。总超时还受底层 OCR/截图调用上界限制，不能声称能中断阻塞原生调用。

后台 TriggerTask 使用分帧推进：每次 run 只观察或做一次动作，后续 tick 核验，不在一次 run 中等待 20 秒阻塞其他后台任务。状态绑定 executor/任务/账号/window epoch，停用、切号或窗口变化时清除；捕获与游戏输入仍由既有执行线程负责，不新增并发点击线程。跨 tick 期间若别的任务拿走界面，放弃旧步骤，重新由主任务定位。

## 有副作用操作的专项设计

**体力/备用/周本**：保留现有 pending_conversion、剩余额度、活跃度满禁止备用、周本次数与单次费用检查。等待动作结果不能重置锁；只在明确证明未发生且同一事务仍有效时才考虑特定操作补点。第一阶段将它们保持“一次提交＋核验或停止”，不提供通用自动重试开关。

**角色选择/取消**：目标是“角色 X 处于 selected=True/False”，不是“点击槽位 Y”。确认角色身份和选中集合；已达目标零输入，身份未知停止；列表滚动后重新定位。参考深塔已有实现，不能直接把三次点击套在六次换人序列外面。

**领奖**：保存账号、日期/活动期、角色/任务项、领取前状态。弹窗出现或已领取即成功；按钮消失但结果不明继续观察或停止。每日、邮件、战令、活动奖励分别定义结果标记，不能把“活跃度满”当作“奖励已领”。

**商店与融合/强化**：以商品/批次、价格、余额/库存、选中物品集合和结果页为证据。刷新会改变商品身份、锁定会切换状态，必须各自处理。EventTask 当前存在价格未知直接尝试和读取失败保留旧余额的分支，这些分支不能自动扩大为多次购买；改变购买策略须作为明确的后续专项实施项。缺少可验证前后状态时，保持一次或停止。

**分页/拖拽**：列表页指纹应来自可见对象 ID、页码/滚动条和边界，动画像素哈希不能单独表示翻页成功；去重、顶底检测、最大页数与目标总量同时约束。拖拽方向/距离的调整属于任务适配，不是统一全屏拖拽工具。

## 日志、截图及工具页方案

每个步骤分配 operation_id，记录 task、step、动作类别、attempt、窗口尺寸、来源/目标状态、目标摘要、等待耗时、输入是否尝试/是否投递/是否被游戏确认、终止原因。三者分开，不能把 PostMessage/SendInput 返回正常当作切页成功。特征码、完整手机号、登录名及凭据不写入通用日志。

建议工具页显示最近步骤：“来源页不稳定”“第 2/3 次点击”“加载中，剩余预算”“已进入目标页”“结果不明，已停止重复操作”，沿用现有组件与整体风格。诊断状态必须区分截图请求、文件落盘、进入上传队列、上传失败/重试、NAS 校验成功，不能只显示一个“已上传”。1.71.00 已在原诊断卡片显示最近导航步骤；上传仍走原明细组件，后续统一证据入口尚待收口。

首次接入调试期可保留每次 before/after；稳定后普通成功默认保留日志和必要终态，发生重试/失败保留前后关键帧，建议单操作上限 8 张（3 次前后＋终态/补充）。实际容量与队列上限复用现有诊断配置，不新建无限缓存。截图落盘或 NAS 离线不重放游戏动作；诊断失败单独告警。

按现有隐私过滤遮挡账号信息和特征码；顶部/底部 2.5% 只是若梦界面的既有策略，不能直接认为适合所有登录/账号/背包页面。无法可靠脱敏的登录画面仅保存局部控件状态或脱敏文本。NAS 仅 `\\192.168.3.173\羲火君 共享给我\AI诊断`，不使用旧地址。

## 验收标准和分批策略

先公共协议＋若梦基准，再指南/日常/刷本，再活动与深塔/周本，再切号与后台，最后处理选择与消费专项。每批以用户常用路径验收后才扩大默认接入范围，不让“全量开关”掩盖未验证任务。

每个接入步骤至少覆盖：首次成功、首次输入丢失、延迟成功、三次失败、来源变化、按钮漂移、弹窗遮挡、未知/加载、重复缓存帧、窗口/账号变化、用户停止、截图失败、同名按钮负样本、1080P/2K 坐标。消费类额外覆盖结果不明零重复提交，选择类覆盖已达目标零点击；后台覆盖其他任务不被长等待阻塞。

自动测试通过只证明控制流/样本识别。实机采集首击成功率、重试恢复率、未知状态退出率、P50/P95 步骤耗时和诊断体积。发布门槛为无错误页点击、无重复消费、无停止后追加输入；性能目标须先测基线，不能现在承诺提高某个百分比。每个已迁移语义入口都要具备后置成功判据；无法实现判据的入口列入待补样本清单，而非宣称全量完成。

实施文件、分批测试和协作要求见 [实施计划](../superpowers/plans/2026-09-14-task-navigation-reliability.md)。源码方法索引见 [盘点附录](../reviews/2026-09-14-task-navigation-inventory.md)。首批实现已修改程序逻辑；未审阅 NAS ZIP。


## 2026-09-14 / 1.72.00 实施进展

本轮接入后台分帧、共用传送、初露峥嵘、周本和部分深塔/事件导航，增加活动消费持久化核验与材料页面身份检查。40 个测试文件共 630 项通过。用户明确跳过领域结算、乐园周常、声骸融合；其他未迁移细目仍未完成，不勾选含未实现或实机验收的复合项。完整35文件状态、消费保护恢复与使用端验收见 [1.72.00 覆盖报告](../reviews/2026-09-14-navigation-rollout-1.72.00.md)。
