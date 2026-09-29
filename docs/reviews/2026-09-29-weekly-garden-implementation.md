# 多账号每周乐园实施与验收

## 范围与基线

用户批准 `docs/superpowers/plans/2026-09-28-weekly-garden-sequence-linkage.md`，并指定 GPT-6 Sol 监督 GPT-6 Luna 实施。Sol 负责拆分、审查和回归，Luna 分别实施任务流程与账号迁移；主代理负责发布及文档整合。

基线为 `f90b8912374dd9a77bc1f477ce047fe6f519164a`（1.87.03），目标版本为 1.88.00。工作树为 `E:\AI work\okww-nas-20260923-recovery`。已有未跟踪诊断证据保留，不加入本次发布。

## 用户行为与验收重点

1. 多账号每日及新增的多账号每周乐园只列出当前序列成员；无效当前账号同步清空配置和界面，共享成员可保留。
2. 旧检查日为周一至周日的全部账号迁移为独立周任务；旧“无”、缺失或无法确认的安排保持关闭。有效新设置优先，升级不得重复覆盖用户选择。新账号默认关闭。
3. 单账号每日、多账号每日、独立周任务共用稳定 profile_id 对应的 Weekly Garden 完成记录；跨序列互认，每日状态和乐园状态各自独立。
4. 乐园积分必须确认达到 6000；空白、只出现目标值、5999/6000、保存失败或跨周未经新周复核均不能标记完成。积分达标不等于奖励已领取。
5. 账号数与时间预算只在账号边界停止；失败先继续后续账号，补跑受本轮次数及预算限制。

## 离线验证记录

- Sol 独立定向回归：`TestMultiAccountWeeklyGardenTask`、`TestWeeklyGardenState`、`TestWeeklyDailyIntegration`、`TestMultiAccountDailyTask`、`TestAccountSwitch`、`TestAccountSwitchEvidence`、`TestMergeEchoTask`、`TestCompletionEvidence`，226 项通过，2 个 pytest 测试类收集警告。
- 主代理按 `run_tests.ps1` 的全部 184 个文件逐文件调用 `scripts/run_test_file.py`，启用实际发布的框架覆盖模块；首轮运行 1949 项，8 项跳过，179 个文件通过，5 个文件进入归因/复测。完整原始结果保存在本机 `test_out/weekly-release-full-20260929-094453/summary.json`。
- 首轮定位到账号主配置缺失或损坏时的任务构造回归，已修复为界面保留修复入口、运行仍受完整性保护。相关旧测试已按获批行为调整；无效旧序列回退的测试按实际当前序列计算成员，可检测刷新顺序错误。
- 海墟成功流程测试未固定赛季日期，在 2026-09-29 触发已到期规则；相关测试及海墟生产文件与 1.87.03 基线一致。已仅为成功流程测试固定有效赛季，生产赛季保护保持原逻辑，不能据此声称当前游戏赛季规则有效。
- 工作树敏感信息扫描命中既有未提交诊断原文。本次保留证据，不修改扫描规则；已将暂存源码导出到临时目录，使用隔离 Git 索引/工作树视图运行原 `TestSensitiveIdentifierScan.py`，1175 个源码文件范围内扫描通过。结果保存在 `test_out/weekly-release-source-scan.json`。
- 最终更新包已重新构建并校验通过：450 个受控文件，从 `v1.87.03` 覆盖升级后配置保留。包为 `okww_update_v1.88.00.zip`，38454814 字节，SHA-256 为 `5477dbe2a480804a3fd1212184b1dd8ca9b222c18a6f4fa4181d87e2c1f5fdef`。

### 最终定向复测

Sol 使用项目虚拟环境，逐文件执行 `scripts/run_test_file.py tests/<文件> --timeout 180`，实际加载发布的框架覆盖模块。10 个文件共 264 项全部通过，0 跳过、0 失败、0 错误；结果保存在 `test_out/weekly-final-sol-20260929/`：

| 测试文件 | 通过数 |
| --- | ---: |
| TestAccountRuntimeIntegration | 16 |
| TestScheduleSupport | 5 |
| TestFlatUI | 35 |
| TestSeaRuinsRecovery | 33 |
| TestMultiAccountWeeklyGardenTask | 8 |
| TestWeeklyGardenState | 10 |
| TestWeeklyDailyIntegration | 20 |
| TestMultiAccountDailyTask | 115 |
| TestAccountSwitch | 7 |
| TestAccountSwitchEvidence | 15 |

上述复测覆盖整库发现的四个逻辑/测试文件问题及受影响的每日、周任务和切号路径；其余已通过文件未重复运行。工作树扫描涉及的原始诊断证据不属于发布源码，干净导出的原扫描检查也已通过。

## 发布核验

版本、README 和更新日志必须一致。GitHub 分支及 annotated 标签需要远端核验。NAS 只使用 `\\192.168.3.173\羲火君 共享给我\AI诊断\OKWW-Updates`，以真实 stable 清单版本验证更新包；发布后回读版本、包大小和 SHA-256。

本轮已读取 NAS 基线清单：1.87.03，包大小 38439263 字节，SHA-256 `0c4d61d00e31ed010dd7044faa313e14d8de14d308616b17ad75112d5bab1345`。

## 验证边界

离线状态和模拟流程测试不能证明远端游戏账号实际登录或对局完成。本次未控制另一台设备；部署后仍需在使用端验证两条序列、一个共享账号和三个入口的真实跳过行为。更新发布不代表设备已经安装，也不会自动合并不同电脑的完成记录。
