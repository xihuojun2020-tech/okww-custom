# 1.59.00 材料规划实施与验收记录

日期：2026-09-12。用户要求实施、持续更新文档、上传GitHub和NAS；随后明确实机由用户自行验收。版本默认关闭材料规划，交付代码与手动验收步骤，不自动操作游戏。

## 完成内容

- 十组四十档材料白名单，七个已观察怪物图标作排除样本；只按武器类型文字与图标预览寻找凝素入口。
- 四档真实库存、3:1仅向上合成、缺口计算；通用材料及“可补齐”不计入；突破只记录，周本只读培养页数量。
- 仓库回顶/重叠滚动/总格数核对，完整周快照与部分记录分离；每笔收益后刷新培养目标与实际持有量，停刷前再次校准。
- 领取前保存UUID关联意图；最后一笔也先采集后退出；完整跨屏拼接和绿色目标格计份；实际消耗独立于奖励份数。
- 永久SQLite、不可覆盖PNG、解析修订、CSV及完整备份。模板未识别、OCR不全、覆盖不全停止新增消费，原图保留。
- 沿用每日任务、领域恢复和账号验证；预算内凝素满足后刷无音区。周本未指定采用自动列表首项，显式“无”继续关闭。
- NAS默认172、新共享名、173回退、旧凭据别名；诊断隔离包同步新模块。管理端口5666不作下载源。

## 验证证据

| 项目 | 结果 | 证据 |
|---|---|---|
| 原始两张收益图OCR和图标识别 | 通过：22格，绿13蓝16紫3金0，2份，绿等价88 | TestMaterialVision；脱敏原图与源SHA见 tests/images/materials/manifest.json |
| 同角色两代佩枪材料与怪物排除 | 通过：pistol_a、pistol_b分组，周本0/26 | TestMaterialVision |
| 十组凝素入口预览 | 通过：四张真实页面回放覆盖十组；不按副本名 | TestMaterialVision |
| 仓库右侧旧详情与格子数量隔离 | 通过：实际格内26、279、10，不取右侧旧8 | TestMaterialVision |
| 单向合成/账号隔离/不可变截图/修订/CSV备份 | 通过 | TestMaterialModel、TestMaterialRepository、TestMaterialCatalog |
| 最后一笔留档/异常不重开/停止不补截图/40体力限领/预算后复核 | 通过 | TestMaterialIntegration |
| 全量标准隔离回归 | 115文件、1200项，1192通过、8既有跳过，无失败 | test_out/test_runs/20260912-082758-482 |
| 全量之后的相关改动复核 | 材料视觉+协调10项、账号/周本/模型契约131项、周本原图11项、NAS/诊断37项通过 | test_out/material-final-focused.log、material-final-contracts.log、material-weekly-images.json、material-nas-final.log |
| 五语言文案 | 通过：PO无重复、MO已编译 | task_i18n_helper check |
| 172真实更新源读取 | 通过：独立工作进程读到此前1.49.00清单 | LanUpdateService实际check |
| 173故障回退和下载绑定 | 模拟测试通过；173实际下载未验收 | TestNasLocation |

最初直接 unittest discover 的合并进程运行出现Qt单例冲突；同时暴露新增测试尚未注册标准分组。已补充分组，改用仓库 run_tests.ps1 逐文件隔离，以上全量结果以该方式为准。

## 实现取舍与未验收项

- 不新增独立整套材料页面，运行信息显示在每日任务信息区，历史数据由 `python -m src.materials` 查询/导出/备份。
- 未做名称学习或通用模糊分类；首版40凝素图标明确白名单，其他未知培养素材保留证据并停止。原始名称字段预留但不用于定位；a/b只代表图标系列。
- 仓库完整性由上下边界、重叠拼接、资源总格数共同核对；未识别的物品不转成零库存。培养页当前持有量用于更新仓库之后发生的变化，停刷前完整扫描与目标复核。
- 当前平均值仅描述已采集样本，尚不按难度/世界等级建预测模型，不控制刷取次数。
- 单份/四份奖励、真实滚动与导航、零库存、跨账号完整流程、其他怪物组合和实际活动收益由用户手动验收。现有图像回放不等于实机通过。
- 详细操作清单：[使用与手动验收](../references/material-planner-1.59.md)。

## 发布

- 版本与注释标签：`1.59.00` / `v1.59.00`。
- GitHub：[版本源码](https://github.com/xihuojun2020-tech/okww-custom/tree/v1.59.00)，发布分支 `codex/account-switch-foreground-bitblt`。安装器由标签触发GitHub Actions生成，不将源码推送等同于安装器完成。
- 更新包：`dist/material-planner/okww_update_v1.59.00.zip`，36,729,857 字节；357个源码文件验证通过。
- SHA-256：`0a4f85ba9a4aaf13b26f586af8b3c01c899404db0764623da2484ae5c9fed3a7`。
- 分别从 `v1.58.00`、NAS原清单对应的 `v1.49.00` 合成升级通过，本机配置保留。
- NAS已写入并读回：`\\192.168.3.172\羲火君 共享给我\AI诊断\OKWW-Updates\stable\releases\v1.59.00\okww_update_v1.59.00.zip`。
- 发布后通过程序的 `LanUpdateService.check` 读回1.59.00清单，并完整读取NAS包校验SHA-256一致；证据 `test_out/material-nas-readback.json`。
- 最后补充验证：材料视觉/领取22项与声骸预算取整6项通过。手动实机验收仍按用户选择保留。

