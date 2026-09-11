# 原版 OK-WW 更新检查与融合方案

## 后续实施：1.57.00

用户已批准按方案执行。本轮完成第一批四角色头像、鼠标调度，以及第二批 Lucy/Rebecca/Mornye 局部轮转移植；审计器补齐标准素材尺寸、注册别名与枚举排除。角色头像已检查脱敏裁剪，新增两张独立黑色画布。角色试用保留新识别角色的身份和通用战斗兜底。

迁移采用本地技能确认、可中断等待、长按释放及冷却时停修正。没有整体合并、修改共享战斗基类、升级框架或运行游戏。赞妮/菲比/光主与图鉴专项仍等待适用故障证据。框架已增加基于两个官方 wheel 的[详细说明](framework-upgrade-assessment-2026-09-11.md)，本轮保持 1.0.190。

最终离线验证为 109 文件、1170 项（1162 通过、8 项既有跳过），无失败错误。301 文件更新包通过 v1.56.00 基线的合成更新与配置保留验证；NAS 当前不可达。实机配队未验证。

2026-09-11 文档复核：源码提交 `2532db11efc60a2aff49beeff9325a94366c3647` 和注解标签 `v1.57.00` 已推送；发布时核对远端分支与标签解引用一致。[GitHub 构建 #34563119497](https://github.com/xihuojun2020-tech/okww-custom/actions/runs/34563119497) 已结束，结论为 failure：validate-version 通过，tests 的 Run isolated test groups 步骤失败，package、artifact-content-check、checksums、github-release 均被跳过。Release API 返回 404，不能视为安装器已经发布。本轮只核对到失败步骤，具体失败用例及根因尚待日志诊断；本地全量通过不代表 CI 通过。

下一步优先诊断 CI 隔离测试失败，恢复安装器发布；角色轮转实机验收仍由用户操作。框架迁移继续按独立专项推进，主环境依赖保持 1.0.190。

下文为实施前评估，保留来源和取舍；其中“未修改/未授权/审计失败”为当时状态，以上述后续实施记录为准。

检查日期：2026-09-11（北京时间）。本轮只更新文档、读取 GitHub 和审计源码，没有合并上游或修改产品代码。比较本地已发布源码 `acbe4e0972d98f743e9ed5aa8a4d6347c1a281d8`（1.55.00），不将另一任务正在进行的界面修改视作已发布功能。

## 结论与基线

原版有更新，建议分批做语义移植，不整体合并，也不因为原版版本号更大就升级本地版本号到 3.x。

- 官方仓库：[ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves)。最新稳定版 [v3.6.7](https://github.com/ok-oldking/ok-wuthering-waves/releases/tag/v3.6.7)，9 月 6 日 19:52:05 发布，主要说明为“优化自动登录”。注解标签解析到 `7df910be3b91e73be0f7a96d34fb4091510f7fac`。
- 最新 master 为 [`6b1bc9d0032b2ce0bd93a693a1e4033fceefbf2b`](https://github.com/ok-oldking/ok-wuthering-waves/commit/6b1bc9d0032b2ce0bd93a693a1e4033fceefbf2b)，9 月 6 日 20:27:57：回撤赞妮、菲比及光主至已知正常逻辑。它晚于稳定版，稳定版不包含这次回撤。
- 本地 `config/upstream_characters.json` 中的 `a24c30f2ec90e56e40287bb76caf7c3a52266d77` 只记录清宵（Qingxiao）的迁移来源，不是整个项目的同步点。因此也检查了 8 月下旬尚未吸收的变化。
- 已核对最近 60 条提交、12 个发布条目、相关实际差异及本地实现。原始 API 快照在忽略目录 `test_out/upstream-review-20260911/`；检查结果是本次时间点快照，不承诺后续上游状态不变。

## 候选项与取舍

| 优先级 | 上游变化 | 本地核对结果 | 建议 |
| --- | --- | --- | --- |
| 第一批 | 凌阳及秋水、秧秧、灯灯头像素材 | `src/Labels.py` 缺少 `char_lingyang/char_aalto/char_yangyang/char_lumi`；普通秧秧与现有 `yangyang_sp` 必须分开 | 增量移植四个头像及标注，补本地角色映射；通用战斗可用不等于专属轮转已实现 |
| 第一批 | 鼠标复位回调去重 | 本地仍用 `running_reset`，但已将轮询从 2ms 降至 50ms；本地 Handler 支持 `remove_existing` | 吸收单回调调度、停用检查和重启恢复，保留 50ms 节能策略 |
| 第二批 | 莫宁协奏不足时普攻补足 | 本地仍在等待 1.5 秒后直接尝试声骸；上游增加最多 2 秒空中普攻 | 优先移植这项小改动，验证停止、落地、肘击和超时 |
| 第二批 | 露西、丽贝卡配队连段优化 | 本地两文件与上游存在实质差异；露西长按/条形状态等待、丽贝卡二次切入冷却处理尚不同 | 将两人作为联动单元移植，验证露丽莫、露丽维及非标准配队；避免仅改单人造成 F 处决归属错误 |
| 单独专项 | 赞妮、菲比、光主回撤 | 本地与回撤后源码仍有较大差异；本地漂泊者位于 `HavocRover.py`，上游为 `Rover.py` | 不直接回撤本地文件；先比较状态协议和实际故障，保护风主初始化、暗主和本地战斗恢复逻辑 |
| 后续按故障推进 | 图鉴分组标题高度校准、可见行不足重试 | 本地仍是固定分隔高度；但无 structure 时已有按序号计算，未发现上游 8 月 29 日修复的“无条件到底”表达式 | 不重复修同名 bug；有定位失败截图时吸收动态校准与一次有界重试 |
| 无需重复移植 | 自动登录“点击连接”、Click to Connect | 本地已有独立连接入口识别和完整按钮匹配，还包含账号核验与输入投递保护 | 保留本地路径，不把上游宽泛正则直接替换进来 |
| 已有 | 显式声明 OCR 依赖 | 本地 requirements.in/txt 均固定 `onnxocr-ppocrv5==0.0.20` | 无需重复添加；依赖升级另议 |
| 暂缓 | ok-script 2.0.7b1 | 本地为 1.0.190，且有大量 custom_ok GUI、执行器和截图覆盖 | 独立兼容性项目，不能跟随角色素材一并升级 |
| 暂缓 | 角色工坊团队 URL 规范化与请求日志 | 上游补丁依赖其工坊实现，本地 CharacterCodeTab 未发现相同工坊接口 | 不为一条修复移植整个工坊；先确认确有团队代码下载需求 |

“添加凌阳”提交实际只修改 `src/Labels.py`、COCO 标注与 `assets/images/47.png`，没有新增 Lingyang 战斗类。四个头像可提升身份识别，但本地 CharFactory 根据注册集合检索模板，仅拷图片不会自动获得角色识别能力；须补注册及通用行为策略。角色试用现有未知角色兜底继续保留，不能让注册后退回不适合试用的路径。

## 分批实施与验收

### 第一批：头像识别和鼠标调度

1. 固定上述 master SHA，抽取四个目标标签对应的图像区域，不复制完整 Labels 或 COCO。根据执行时本地最大 ID 分配图片、类别和标注 ID，已有同名标签复用而非重复创建。
2. 调整 `src/Labels.py`、`src/char/CharFactory.py`、最小素材和必要的角色名称映射；普通秧秧不映射到特殊形态。先确认 BaseChar 与试用专用 TrialGenericChar 的选择关系，再决定注册策略。
3. 局部修改 `src/task/MouseResetTask.py`：开启只保留一条待执行回调；停用及浏览器模式立即返回；异常后允许后续触发恢复。保留本地 50ms 正常轮询，不复制上游 2ms。
4. 验收模板加载、四角色映射、ID 唯一、多尺寸正反例、已知与未知混合试用；鼠标测试覆盖反复开关、异常恢复和队列不叠加。由用户实机验收后台防漂移和试用，助手读取日志。

### 第二批：配队轮转

1. 先单独迁移莫宁小改动，再处理 Lucy/Rebecca 的 F 处决时机、强化重击和冷却快速切人。
2. 不照搬原始 `time.sleep` 和无 finally 的长按；按本地停止、输入释放、战斗总时限改写。保留任务异常恢复接口。
3. 回归技能不可用、协奏未满、落地、下一波、角色死亡、停止和战斗结束；实机比较露丽莫、露丽维的空转、处决、换人和完成情况。没有实测数据不承诺伤害提升百分比。

审计器已试运行：Lucy/Rebecca 因 `images/36.png` 为 1920×1080 而被当前素材迁移器拒绝；Mornye 因推导的 `char_mornye` 与实际 `char_moning/char_moning_new` 不符而失败。后续先修正审计器的尺寸支持与别名读取，补回归，再生成候选。此次未修改审计器，也未生成可直接合入的三人移植包。

### 第三批：稳定性专项与框架评估

- 赞妮/菲比/光主以回撤后的源码为参考，逐一核对跨角色字段、返回值、形态识别和状态重置。Zani/Phoebe 审计报告未发现静态方法缺失，但报告将首个枚举 State 识别为 class_name，且不能保证导入路径和运行时协议正确，因此不构成兼容性通过。必须人工映射 Rover→本地漂泊者并验证风主原有修复。
- 图鉴滚动保留本地截图识别起点，在失败样本上比较标题高度校准与一次重试。覆盖无分组、分组边界、前四项、底部、可见行不足和找不到按钮。
- 框架升级另建隔离验证环境，逐项比较 `custom_ok/ok/task/TaskExecutor.py`、GUI 控件覆盖、截图、任务启停和依赖。必须覆盖账号切换生产路径及 TestAccountSwitchTask 的 A1→A3→A4、别名与掩码身份，不建立另一套测试切换逻辑。未完成这些检查不改主环境依赖。

每批独立提交、回归、记录实机边界；代码发布按届时最新本地版本递增，不预占版本号。禁止整分支合并、整提交 cherry-pick、覆盖共享 Base 类及全部素材。第一批与当前并行的界面/账号修改协调完成后再实施；本轮方案不表示已经授权执行这些新改动。

## 核对来源

- [四角色之一：凌阳素材，9 月 5 日](https://github.com/ok-oldking/ok-wuthering-waves/commit/f353fa938a907d11f92a623975e33662ab90518d)
- [秋水、秧秧、灯灯素材，8 月 31 日北京时间](https://github.com/ok-oldking/ok-wuthering-waves/commit/38bd892a95d7e656753db229b0605821e74bb5b1)
- [露西、丽贝卡、莫宁优化](https://github.com/ok-oldking/ok-wuthering-waves/commit/30eda70de946018f3d9cd634e743ee1c8b8afbef)
- [鼠标复位调度](https://github.com/ok-oldking/ok-wuthering-waves/commit/4d616d02a3bc07260bd77cc67ee8136825a6e3dc)
- [图鉴校准](https://github.com/ok-oldking/ok-wuthering-waves/commit/f4b3799c5e0ab8bc3d7191f43a842b84197081ff)／[无分组到底修复](https://github.com/ok-oldking/ok-wuthering-waves/commit/1137bdb431d5c6a5a5e08f8b7f45412adbaf3bf0)
- [自动登录](https://github.com/ok-oldking/ok-wuthering-waves/commit/7df910be3b91e73be0f7a96d34fb4091510f7fac)／[框架依赖升级](https://github.com/ok-oldking/ok-wuthering-waves/commit/c3fef9a06f61f96abeb53571fb47dd578b6f7063)
- [工坊 URL 修复](https://github.com/ok-oldking/ok-wuthering-waves/commit/aa2afd8f9f597d332fa82c6488bffbb3f5686b86)
