# 全输出角色单人分支实施计划

> 执行方式：本会话顺序实施；用户已授权完成代码与文档，不再次请求方案批准。

**Goal:** 主输出、副输出及漂泊者全部已识别形态进入单人输出路径，不依赖不存在的队友。
**Architecture:** BaseChar.perform 根据真实队伍成员和角色定位分派 perform_solo；默认单人路径复用已可独立运行的专用 do_perform。无法独立启动的角色覆盖 perform_solo，局部移除仅为切人服务的协奏门槛。多人路径继续 do_perform。
**Tech Stack:** Python、ok-script、现有图像模板及 unittest；不新增依赖和假造模板。
**Spec:** 用户本轮要求及 1.69.01～1.69.03 单人入口/清宵实证。

## 全局约束

- 在隔离工作树工作；仅提交本任务文件。保留其他修改。
- 本地 .venv；版本按中型改动提升 1.70.00；GitHub 分支和注释标签及 .173 NAS 更新源同步。
- 只以真实成员数判断单人；不伪造变奏、队友增益或能量。
- 主角现有衍射/湮灭/气动保留各自专用轴；其他元素枚举及未知形态使用明示的基础技能轴，不臆造未提供的技能机制。
- 不将离线回放、分支测试声称为所有角色实战通过。

## Task 1：共用调度与保护

Files: src/char/BaseChar.py, tests/TestAllSoloRotations.py。
- [x] 注册表枚举 MAIN_DPS/SUB_DPS 和千咲输出配置，验证真实单人调用 perform_solo、多人调用 do_perform。
- [x] 实现 is_solo 属性、perform 分派、默认 perform_solo 委托专用轴、基础可用技能轴。
- [x] 清理单人残留变奏状态；switch_other_char 不向自身发切人键；大招 con_less_than 仅多人有效，仍保留 use_liberation 检查。

```python
if self.is_solo and (self.is_main_dps or self.is_sub_dps):
    self.has_intro = self.has_sub_dps_intro = False
    self.perform_solo()
else:
    self.do_perform()
```

## Task 2：角色专项与形态

Files: Aemeath, Jinhsi, Hiyuki, Camellya, Lucilla, HavocRover；Danjin, Denia, Encore, Linnai, Zhezhi, Changli, Jiyan, Xiangliyao 与相关 helper。
- [x] 为爱弥斯补无增益/无变奏输出，为今汐补独立启动，为绯雪补无长动作标记起手，为其他已审计专用轴保留形态流程。
- [x] 椿保留强化技能与重击，洛瑟菈保留蓄能与变身但不因大招冷却只切人。
- [x] 丹瑾满回路单人可重击、达妮娅不因满协奏提前退出、安可单人可开大、琳奈/折枝不因协奏满跳过技能。
- [x] 漂泊者单人不走赞妮插入窗口，按元素调用已有形态函数；湮灭轴普攻时长不依赖永不更新的切人时间。
- [x] 单人长循环设置边界，原成员数变化、冷却与异常退出保护回归。

## Task 3：验证、文档与发布

Files: tests/TestAllSoloRotations.py, tests/TestSoloTeam.py, docs/references/solo-combat.md, docs/reviews/2026-09-14-all-solo-rotations.md, README.md, config.py, 更新日志.md。
- [x] 生成注册表覆盖清单：各角色策略、主角形态策略、基础轴与专用轴区别。
- [x] 新增真实调度覆盖、关键角色无变奏/满协奏/无技能时行为、大招关闭、无切人、成员变化及形态测试。
- [x] 运行 TestAllSoloRotations、TestChar、TestSoloTeam、TestQingxiaoSolo、TestQingxiaoSoloImages、相关战斗回归。
- [x] 文档记录通过/跳过/实机待验收边界；版本 1.70.00 校验。
- [x] 发布操作：显式暂存、提交、注释 v1.70.00、推送。
- [x] 打包与校验更新包，同步 \\192.168.3.173\羲火君 共享给我\AI诊断\OKWW-Updates；原工作树安全快进。
