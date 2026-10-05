# 多账号每日任务近期错误修复实施计划

> 执行者按下面复选步骤逐项实施、测试与审查；在当前会话顺序执行。计划状态：已按用户授权实施，发布与实机验收状态见末尾。

**Goal:** 修复已满活跃度误报、梦魇入口误点和周本领奖确认失败，并使补跑依据实际缺项恢复。

**Architecture:** 复用现有daily_observation、指南列表定位、周本领取账本和任务状态流程。在数字解析、列表行配对及领奖状态三个根因处修复，单账号和多账号调用同一生产路径。未知资源／未确认奖励仍保持待核验。

**Tech Stack:** Python、ok-script、OpenCV、现有OCR、unittest、仓库隔离测试运行器；不新增依赖。

**Spec:** `docs/reviews/2026-10-05-multi-account-daily-nas-investigation.md`。

## 全局约束

- 以已发布1.97.04为基线，在现有隔离工作树审查后继续；不混入主目录未提交改动。
- 自动战斗启用状态只能由用户手动关闭。菜单、加载、旧帧或角色未知时等待合法场景与新帧，不取消启用选择。
- 单账号每日、多账号每日、完成检查证据使用同一解析与状态规则。
- 活跃度未知不转换备用体力；真的体力不足不假报完成。保留当前体力／备用体力额度政策。
- 领取次数只根据已确认领取结果增加，重复补跑不得增加累计次数。确认已发出但结果未知时不再次消费。
- 保留账号昵称、序列、登录别名、每周乐园与周本／材料累计记录；不整体重置配置。
- 只使用`\\192.168.3.173\羲火君 共享给我\AI诊断`。诊断图、录像及新增失败证据进入okww监控室。
- 网络错误不列入本次实施；未确认根因的领奖站位问题先取证。
- Python使用`E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe`。实机测试逐项安排，不自动对真实账号消费体力。
- 用户已指定本次修复版本为1.97.05。发布前核验远端标签，禁止覆盖已有同名版本；如有冲突先报告。日常修复和功能完善谨慎使用第三段版本号，不因涉及多个模块自动提升第二段。2.00.00保留给所有功能基本完成后的整体发布。代码、config.py、README、更新日志同版提交，核验后注释标签、推送GitHub、发布NAS。

## Task 1：保存可复现样本

**Files:** 新增`tests/images/daily_nas_20261005/`中的脱敏图片、来源清单；报告沿用Spec。

**Interfaces:** 样本命名`activity_300.png`、`activity_240.png`、`nightmare_filter_open.png`、`weekly_claim_171.png`、`resource_234.png`；来源清单记录ZIP SHA、事件ID、原图SHA、裁剪／遮挡范围。

- [ ] 从已检查包／本次本地提取目录保存上述样本，遮挡UID后保留原图校验记录；不把多GB诊断ZIP加入Git或更新包。
- [ ] 提取10月5日A1／A5活跃度200／300、A8入口坐标与超时、A4周本pending事件的完整日志链。
- [ ] 使用现有隔离runner建立失败回归：300正确识别仍被拒、筛选菜单误当入口、1711240导致领奖弹窗None、234/240资源未知。
- [ ] 保留已有真实不足37/40、未确认领奖及用户停止的对照用例，避免用“全部视为完成”使测试通过。

## Task 2：统一活跃度解析与完成证据

**Files:** 修改`src/task/daily_observation.py`、`src/task/DailyTask.py`；测试`TestDailyActivityFlow.py`、`TestDailyClaimStability.py`、`TestDailyRegressionImages.py`、`TestDailyOutcomeRecovery.py`。

**Interfaces:** 在daily_observation新增`activity_points(boxes) -> int | None`，仅消费已通过活跃度页面及数字区域核验的OCR框；DailyTask运行读数与_capture_progress_page共同调用。保留`open_daily() -> (stamina_progress, ready)`现有接口。

- [ ] 编写解析与生产回归，明确200／240／300均为合法观察值，而不是把值改写为100。纯数字限定长度1～3位；其他区域的数字不送入解析。出现不同候选先重读，不直接取最大值。

```python
from types import SimpleNamespace

def box(text):
    return SimpleNamespace(name=text)

for score in (0, 80, 100, 160, 180, 200, 240, 300):
    assert activity_points([box(str(score))]) == score
assert activity_points([box('100'), box('300')]) is None
assert activity_points([box('100/180')]) is None
```

- [ ] 运行新增用例确认原0～180规则失败，再替换运行读数和收尾证据的两处解析；页面锚点、数字区域及多帧稳定读数保留。
- [ ] 达标阈值继续为100。五档奖励领取状态单独读取，100以上不能自动推出奖励已领取。
- [ ] 活跃度未知先在当前页重读，仍未知则保留待核验；不得继续无意义刷体力以“补齐”已完成账号。
- [ ] 核验单账号／多账号结果一致，完成检查记录真实200／240／300，并且重复运行不再触发整账号补跑。

**Deliverable:** A1、A5、B10实际高分截图识别通过，完成证据与执行结果一致；真实80分仍不能标完成。

## Task 3：梦魇列表按名称与同行按钮定位

**Files:** 修改`src/task/NightmareNestTask.py`，仅有必要时复用`src/task/BaseWWTask.py`目标状态探测；测试`TestNightmareNestTask.py`及真实图回归。

**Interfaces:** 新增`_nightmare_rows(frame, required=None) -> dict[str, tuple[int, int, Box | None]]`，返回名称对应的当前进度、总量、实际按钮；继续使用现有NestTarget返回与缓存键机制。

- [ ] 在真实筛选菜单图与顶部半行上建立失败用例：不能返回入口按钮，不能把“受蚀地／千殁沉岛”进度按序推成“三王峰”。
- [ ] 复用残像聚落的行配对方式，以完整地点名称定位，再匹配该行0/36等进度与真实“前往／直接挑战”按钮。移除梦魇的固定x=.9、从进度y估算按钮及可见行数推算名称。
- [ ] 顶部半行、缺标题、缺按钮、重复标题和筛选菜单遮挡均不点击；识别到筛选菜单时先关闭并复读。仅所选目标不完整时短滚动，最多三次源页恢复。
- [ ] 点击前再核验同一地点、进度、按钮；点击后识别地图传送、编队／单人挑战、已到世界三种确切状态。
- [ ] 成功后沿用现有战斗、获取声骸和清巢核验；入口失败直接记录目标、源页和按钮坐标，不只输出上层“巢穴未完整”。
- [ ] 验证残像上方四项不为底部第五项无条件滚动；三王峰、已完成目标、未解锁入口与两种挑战按钮均符合当前选择。

**Deliverable:** A8复现图中不再误点筛选栏；完整三王峰行才触发点击，误定位不消耗体力。

## Task 4：资源OCR和周本领取状态

**Files:** 修改`src/task/BaseWWTask.py`、`src/task/daily_observation.py`、`src/task/WeeklyBossTask.py`、`src/task/weekly_boss_progress.py`；测试`TestWeeklyBossImages.py`、`TestWeeklyBossTask.py`、`TestWeeklyBossPlan.py`、`TestWeeklyRewardRecovery.py`、`TestStaminaAccounting.py`、`TestDailyReservePolicy.py`。

**Interfaces:** 在BaseWWTask新增`_read_current_stamina(frame, region) -> int | None`；仅读取指定当前资源栏，先严格分数解析，再放大／二值化重读。现有get_stamina继续返回(current, reserve, total)，周本确认直接使用当前值，不要求备用栏有效。WeeklyBossProgress增加`set_phase(event_id, phase)`，phase采用interaction_sent、dialog_seen、confirm_sent；旧pending缺phase默认unknown。

- [ ] 用实际171/240图复现OCR为1711240、_claim_confirmation为None；用234/240与备用0图复现资源栏未知。
- [ ] 以当前体力图标／栏位和分母240为锚点重读；分隔符误成1或竖线时必须有确定位置与分母证据，当前值0～240且至少两读一致才能恢复。不是任意七位数字都替换为分数。
- [ ] 周本弹窗继续校验标题、费用正文、取消／确认、当前体力足够；任何一项未知不点击。费用60、体力171的真实图应通过；费用变化／体力59应拒绝。
- [ ] 持久化领取阶段：F发送前后记录交互阶段；明确弹窗记录dialog_seen；发送确认前写confirm_sent，确保发送后崩溃不会被自动当作未领取。
- [ ] 明确未发送确认、成功取消弹窗且游戏剩余次数未减少的事件可resolve(False)，累计不变。确认已发出但结果未知时保持pending，复核游戏剩余次数与结算，禁止盲目重领。
- [ ] 旧pending无发送阶段，不能仅凭事件时间或猜测自动清空；走现有人工核验接口或具有唯一归属的游戏次数复核。
- [ ] 结算、账本累计与游戏本周剩余次数三者一致才resolve(True)；重复resolve或重复运行不得计两次。
- [ ] 资源栏日志区分当前读数未知、备用未知、分母未知与实际不足；0备用合法，37/40保留资源不足。体力未知不转换备用。

**Deliverable:** A4实际弹窗能安全确认；计数准确，已证明未确认的事件不永久阻塞，未知结果仍禁止重复消费。

## Task 5：补跑、页面恢复与自动战斗场景

**Files:** 修改有证据需要调整的`DailyTask.py`、`MultiAccountDailyTask.py`、`AutoCombatTask.py`及现有场景判断；测试`TestDailyFailureRecovery.py`、`TestDailyRunConfirmation.py`、`TestMultiAccountDailyTask.py`、`TestAutoCombatRecovery.py`、`TestCombatTaskModes.py`。若触及切换路径，同时检查`TestAccountSwitchTask`与相关测试。

**Interfaces:** 保持现有每日目标检查点和账号身份验证接口。账号结果区分completed、failed、resource_shortfall、weekly_pending，通过现有结果记录／状态字段表达，不新增平行登录实现。

- [ ] 检查Task 2～4是否已消除整账号重复；只有剩余缺项才局部补跑，已清巢穴、已确认周本及材料累计不重刷。
- [ ] 每日检查点按账号、凌晨4点划分的游戏日及目标配置隔离；跨日或改目标后重新核验，不能把上一游戏日的完成记录套用到今天。跨周累计的周本／材料领奖次数不随游戏日清零。
- [ ] 加入“每日完成但周本待补检”“真资源不足不整账号重跑”“领奖结果未知不重复F／确认”的端到端用例。
- [ ] 非战斗菜单、加载页或截图失败时禁止战斗输入并保持enabled；回到真实场景与新帧后继续自动检测。用户手动关闭仍立即生效，不能被恢复流程重新打开。
- [ ] 对10月4日A5／B8尚缺原图的战后交互，补记F文字、宝箱位置、吸收提示、费用弹窗、实际移动及状态切换；保存到okww监控室，按事件关联，避免无限重复截图。
- [ ] 对残留弹窗和世界未就绪，先识别当前页再恢复；未知页面不按主菜单退登。涉及账号切换时复用生产方法与测试入口，连续测试顺序A1、A3、A4，别名／掩码身份均覆盖。

**Deliverable:** 没有证据证明已完成的任务仍保留未完成；补跑不会重复消费；菜单告警不会关闭自动战斗。

## Task 6：回归、发布与真实验收

- [ ] 每个逻辑变更先跑对应失败用例，再跑生产流程回归。使用实际runner，不凭导入成功宣称流程通过。

```powershell
$taskPython = 'E:/AI work/ok-wuthering-waves-master/.venv/Scripts/python.exe'
& $taskPython scripts/run_test_file.py tests/TestDailyActivityFlow.py
& $taskPython scripts/run_test_file.py tests/TestNightmareNestTask.py
& $taskPython scripts/run_test_file.py tests/TestWeeklyBossImages.py
& $taskPython scripts/run_test_file.py tests/TestWeeklyRewardRecovery.py
& $taskPython scripts/run_test_file.py tests/TestMultiAccountDailyTask.py
& $taskPython scripts/run_test_file.py tests/TestDailyReservePolicy.py
& $taskPython scripts/run_test_file.py tests/TestAutoCombatRecovery.py
```

- [ ] 对上述其他相关套件及原深塔回归进行隔离验证，避免回退1.97.04的选队与标记识别修复。记录测试数量和真实失败原因，不预先承诺固定通过数。
- [ ] 更新config.py、README、更新日志及使用说明，本版固定为用户指定的1.97.05。一次受控发布，避免每个子修复发布一次让使用端频繁升级；标签如已被使用则报告冲突，不自行跳到1.98.00或2.00.00。
- [ ] 打包覆盖1.97.04的模拟安装，核验账号配置、序列、每周乐园联动及周本／材料计数保留；旧pending不被批量删除。
- [ ] 核验后提交功能变更、创建匹配注释标签、推送GitHub；发布唯一NAS，验证发现新版、下载SHA、覆盖内容及安装后版本显示。
- [ ] 真实验收按账号记录单独进行：A1满200；A5满300；B10满240；A8三王峰准确入口；A4周本60费用确认与一次累计；真实不足37/40仍待补充。实机消费操作须在执行范围中明确安排，不在计划阶段自动运行。
- [ ] 下一次诊断按同一时间／账号／尝试口径对比，不能把ERROR行数下降当作任务成功。成功标准为账号结果和游戏实际目标一致。

## 完成标准

- [ ] 三项首要缺陷有实际图回归及生产路径测试通过。
- [ ] 单账号、多账号、完成检查对同一活跃度得出一致结果。
- [ ] 无重复领取、重复累计或未经政策允许的备用体力转换。
- [ ] 自动战斗用户启用状态保持，只有用户关闭可改变。
- [ ] 未确认根因的问题有明确剩余范围和证据；不宣称本版已经解决全部可能的日常失败。
- [ ] GitHub和NAS发布均可验证，升级配置兼容，实机验收结果单独记录。


## 2026-10-05实施状态

- [x] Task 1：五个已审阅包登记保留；五张脱敏真实图及来源哈希加入回归。详细日志链保留在调查报告及本地提取目录。
- [x] Task 2：运行与收尾共用高分解析，单帧矛盾读数拒绝；跨帧沿用既有进度增长规则，未引入必须每帧相等的新限制。
- [x] Task 3：按完整名称配对进度与按钮，关闭筛选复读，点击前重新核验；上下列表使用有限滚动，未确认目标不能假报完成。
- [x] Task 4：当前体力分数及备用0真实图回归，领取阶段持久化，未确认取消需剩余次数证明；旧pending不清空。
- [x] Task 5：既有检查点、单账号／多账号、资源不足与自动战斗启用规则通过回归；补充战后交互失败截图和标记坐标。未触及账号切换实现。
- [x] Task 6：测试汇总、GitHub/NAS发布及升级核验结果见`docs/reviews/daily-repair-1.97.05-verification.md`。
- [ ] 实机消费验收及下一批诊断对比：离线测试无法代替真实游戏验证；A4旧待核验记录需要人工核对。

上方细项是原设计验收清单；以此实施状态和核验报告记录实际交付，未声称每项实机标准已经满足。
