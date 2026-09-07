# A4 领域战斗状态与领奖修复实施计划

> 执行方式：当前任务逐项实施与复核。用户已批准《A4新增帧证据复核与修改方案》，不另行分派子代理。

**Goal:** 阻止异常脱战后寻宝/领奖，短暂切人失配可恢复，领奖未确认不得记账。
**Architecture:** 保留现有任务结构；增加明确的CombatStateUnknown异常，领域用同一挑战一次恢复预算。复用队伍、目标、奖励交互特征，不引入新依赖或修改角色轮转。
**Tech Stack:** Python 3.12、本地.venv、ok-script 1.0.190、unittest与现有图像测试。
**Spec:** docs/reviews/2026-09-07-A4新增帧证据复核与修改方案.md

## 全局约束

使用本地.venv；不操作真实游戏/账号，不携带原包身份事件。保持0.8匹配阈值和备用体力策略。中等行为变更候选1.35.00，发布前核对远端标签。保留其他任务的未跟踪文档。所有未知结果阻止完成写入。

## T1：异常语义

文件：src/task/BaseCombatTask.py、src/combat/CombatCheck.py、tests/TestBaseCombatTask.py。
- [x] 添加普通Exception派生的CombatStateUnknown，避免被旧NotInCombat死亡恢复分支误捕获。
- [x] 先写行为测试：注入非预期NotInCombatException，combat_once必须上抛CombatStateUnknown，不能调用combat_end；预期结束保留进入战斗结果；死亡原样上抛。
- [x] 实现捕获分流：`if not self.is_expected_combat_end(): raise CombatStateUnknown(str(e)) from e`。
- [x] 运行状态检查遇TaskDisabledException、配置完整性/写保护异常、窗口丢失、无帧必须传播。
验证：`.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestBaseCombatTask.py`。

## T2：领域阶段门禁与一次恢复

文件：src/task/DomainTask.py、tests/TestDomainRecoveryLoop.py。
- [x] 新增`_domain_reward_state()`返回combat/claim/treasure/unknown；目标或血条优先为combat；明确体力领取窗为claim，领取交互或宝藏图标为treasure；其他unknown。
- [x] 新增`_finish_domain_combat()`：执行combat_once，捕获仅CombatStateUnknown；取新帧，在约5秒预算内等待阶段明确。combat允许本挑战恢复一次（3秒等入战斗），第二次仍combat则上抛；unknown超时上抛。
- [x] farm_in_domain只在treasure状态寻宝并按F；claim直接进入领奖，不再重复寻宝。寻宝超时仅在已看到claim时继续。
- [x] 删除“无目标就结束”弱契约；死亡分支只捕获CharDeadException。恢复次数耗尽上抛失败而非返回成功。
- [x] 行为测试覆盖同一挑战一次恢复、未知不寻宝、直接claim、真实死亡、停止/截图异常。
验证：`.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestDomainRecoveryLoop.py`。

## T3：切人短暂失配

文件：src/task/BaseCombatTask.py、tests/TestBaseCombatTask.py。
- [x] 新增`_wait_switch_team(timeout=1.0)`：首次False保存现有帧，直接用executor.next_frame取新帧，连续两次有效队伍结果后恢复；等待不发输入，不调用可能处理月卡的sleep。
- [x] 循环总时限10秒使用单调时钟，所有分支都检查，删除不可达代码。首次读队伍失败先等待，再发键；发键后失配同样等待。
- [x] 到期复核死亡或明确结束，其他情况传播状态异常；诊断日志包含现有时间/角色/帧龄，截图使用原帧，首次缺失每次切人最多一份。
- [x] 测试瞬时恢复、持续缺失、停止、帧异常，不降低模板阈值。

## T4：领奖成功核验

文件：src/task/BaseWWTask.py、tests/TestStaminaAccounting.py。
- [x] 领取前确认has_claim_stamina，并拒绝无效OCR读数；available使用allow_backup控制。
- [x] 操作后从新帧读取余额，在有限8秒内确认总余额下降与本次40/80或60/120相符（允许短窗内自然恢复1点），且领取窗口已关闭。
- [x] 未确认上抛错误，不返回used，不递减调用者预算；不重试领取按钮，避免重复消费。无可用体力正常返回False,0。
- [x] 日志分别标注实测和推算，继续策略保持原预算/备用规则。无法读到可靠余额时安全停止，实机确认窗口可见性作为待验项。
- [x] 测试未扣费/无效OCR/补充失败、预算结束和备用True/False；复查Domain/Tacet共享调用。

## T5：回放、全量与发布

- [x] 将两张无身份故障PNG作为图像回归，确认in_team=True、has_target=True、领域state=combat。
- [x] 专项通过后运行`.\run_tests.ps1 -Group all`，修正旧测试错误契约。
- [x] config、更新日志、结构说明及执行记录同步1.35.00；翻译仅在新增可翻译UI时更新，本批运行诊断沿用中文日志。
- [x] stage仅本批文件，构建源码更新包并对v1.34.00验证SHA256与配置保留；版本校验、pip check。
- [x] 创建提交、注解v1.35.00标签，推送当前分支与标签；核对远端提交与CI状态。不得宣称实机或安装器已验证。

## 测试契约示例

```python
with self.assertRaises(CombatStateUnknown):
    BaseCombatTask.combat_once(task)
task.combat_end.assert_not_called()
```

```python
assert task._domain_reward_state() == 'combat'  # 两张敌人仍在的故障帧
```

```python
# 未确认扣费时，上抛而非返回used=80；调用者不能据此写入完成状态。
with self.assertRaises(RuntimeError):
    BaseWWTask.use_stamina(task, once=40, must_use=120, allow_backup=True)
```

## 发布风险与实机验收

首次视觉丢失的游戏侧原因仍未证实；本批修复其控制流后果与短暂失配边界。1秒宽限不是新证据证明的角色动画时长；受控实机需验证。领取后余额若界面不可读，将安全停止，需要实机奖励帧进一步适配，不采用假定扣费成功兜底。


## 执行验收（2026-09-07）

已按T1–T5完成实现及本地验证。全量85文件、789项、8跳过、0失败，目录test_out/test_runs/20260907-184112-958。源码包从v1.34.00覆盖验证239文件且configs保留，SHA256为3ccdc8dc13eabfe2bc197861f1d089dbbcbd973b8fcd5567e7c2a32c2979bc08。版本1.35.00，发布提交/标签状态以远端为准。未开展实机验收。

实施细化：get_stamina新增可选超时和静默失败参数，领奖确认轮询不重复保存截图；缺少当前体力OCR时返回负值并拒绝消费。切人复核截图显式绑定首次匹配帧；正常角色选择测试补齐了同帧接口替身。所有测试失败均已解决后才进入发布。
