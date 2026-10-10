# GameFrame 鸣潮原生迁移审查（2026-10-11）

本轮发现的六项集成与验证问题已由对应负责人修复。随后显式 `combat_api` 完成生产 MRO/角色依赖迁移：负责人在禁止 ok/PySide6/qfluentwidgets 导入的进程中跑通真实自动战斗、角色轮转与本地 OCR，补齐同帧 OCR 缓存后 Host/Executor 最终共 23 项通过；主代理完成已安装原生 ZIP 的两项独立入口验收。这一批结论限于自动战斗子集。随后账号闭包已完成七项原生检查和193项旧账号回归，记录于 `2026-10-11-gameframe-noncombat-native-boundary.md`；其余任务须按各自生产路径验收。

## 范围与版本

这是 `v1.97.64` 提交后的增量审查。已发布基线为提交 `e1a27f8`、annotated tag `v1.97.64`；本轮未修改该历史验收结论，也不代替最终版本发布记录。

只读核对 GameFrame API/runtime/controller/worker/state、设备捕获契约、包内 Box/FeatureSet/OCR/预处理、原生 Config/日志/异常/executor/host/task、生产战斗接点和相关测试，并对照已安装 ok-script 1.0.190 与 v64 源码。没有启动游戏、模拟器、真实捕获或输入、账号操作、Child Session、系统设置或 NAS。测试使用项目 `.venv`、临时配置目录、现有截图与 ReplayDevice。

## 已修复的问题及依据

| 问题 | 实际证据与影响 | 修复与验证 |
|---|---|---|
| Host 未传完整模板配置 | 初稿使用阈值 `.95`，生产为 `.8`，且丢失水平/垂直中心标签；真实 `e_forte` 等宽屏锚点会偏移 | `src/combat/settings.py` 提供共用 `TEMPLATE_MATCHING_DEFAULTS`，生产 config 与 Host 显式传入同一配置；FeatureVision 使用 v64 独立基线对照 |
| 诊断失败覆盖业务故障 | Host `_write_log_images` 原先直接保存截图，磁盘失败可替换原始战斗异常；通知输出同样是外部诊断边界 | 诊断写入/通知失败记录异常并继续业务恢复；直接 `save_screenshot` 请求仍传播失败，不把截图写入伪装为成功 |
| 停止可能被单次抓帧阻塞 | executor 原先一次调用传入 6 秒，而 controller 默认停止宽限为 5 秒，可能在 held input 释放前强杀 worker | 保留总抓帧 deadline，把每次设备等待限制为最多 `.1` 秒并检查停止；无帧时消耗剩余本次等待预算，异常继续传播。负责人停止回归小于 1 秒；独立 probe 约 `.109` 秒返回 Cancelled，捕获预算为 `[.1]` |
| 原生日志遗漏真实视觉错误 | 初始仅向 `ok` logger 装 handler；独立 probe 显示生产日志落盘而 `src.vision.ocr` 错误未落盘。仅改 root level 后，旧 child logger 的 DEBUG 仍越过过滤 | handler 安装在 root，并设置 handler 自身 INFO/DEBUG level；测试清理 root handler，OCR 错误可落入显式 data_dir 的 `logs/ok-native.log` |
| NativeTask 证据目录不符合项目合同 | 初稿写入 `data_dir/screenshots`，项目要求保留在 `okww监控室` | 改为 `data_dir/okww监控室`；真实匹配→Replay动作→PNG 证据测试断言具体路径与文件头 |
| FeatureVision 名单断言静默失效 | config 改用字典展开后，旧 AST literal 提取变为空名单，两侧空名单比较仍通过 | 当前名单直接读取共用 defaults，独立参考来自 `git show v1.97.64`，恢复六类 processor 与宽屏锚点的真实对照 |

以上恢复边界有实际接口或故障依据。业务预处理、文件读取、OpenCV 匹配、OCR 引擎及直接截图失败仍传播；没有用空匹配、默认成功或额外重试隐藏错误。

主代理发布前复核还修复了两处实际角色路径：`BaseChar.click_echo`／安可会调用开放世界分类，原方法先导入 Daily／Tacet，独立战斗进程因此会拉入旧依赖；现在先判 AutoCombat 并完成真实场景分类，其他任务保留原判定。真实截图专项检查证明没有载入 Daily／Tacet，也没有发送输入。对全部角色源码的 Task 属性静态比对发现忌炎实际调用 `middle_click_relative`，原 NativeTask 缺此 API；补入与旧源码一致的全屏像素语义，在宽屏 Replay 检查中验证中键动作和释放。首个 down 后取消的轮转测试没有覆盖这些后续分支，不能将它写成全部角色场景已动态覆盖。

## 验证证据与限制

| 检查 | 已观察结果 | 能证明的范围 |
|---|---|---|
| `TestPackFeatureVision` | 10 项通过；独立隔离进程禁止 ok/GameFrame/PySide6 仍从显式 COCO 路径匹配真实 logout 图标 | 包内视觉实现可独立导入；几何、缓存、灰度/Canny、mask、ROI、外部模板、去重、target_height、业务错误与诊断边界符合对照契约 |
| 包内颜色/迁移组合 | 曾有 Feature 10 + Color 4 + Migration 6 共 20 项通过 | 当时文件集合可构建；后续并发新增源码导致集合检查变化，最终包需在源码稳定后重新构建检查 |
| 原生支持/task/feature 修复组合 | 主代理报告相关 19 项通过 | Config/日志/任务证据目录及 Feature 独立基线修复已有检查；不把该数量与其他历史批次相加 |
| `TestNativeCombatHost` + `TestNativeCombatExecutor` | 负责人报告 10 + 11 共 21 项通过，13.459 秒 | Runtime → host.run_service → AutoCombat.run/_run_combat → combat_is_active/load_chars → perform_combat_rotation → BaseChar.perform/do_perform → Replay真实 down 动作设置 stop；非 mock 战斗判断/角色/rotation/OCR |
| 完成显式 provider 和同帧缓存后的检查 | 负责人最终报告 Host 12 + Executor 11 共 23 项通过，13.628 秒 | Host 默认 native=True，使用包内 NativeBaseTask/NativeTriggerTask；硬阻 ok/PySide6/qfluentwidgets，拒绝测试进程预先加载旧模块；真实 CPU OCR 同帧只推理一次，换帧再次推理；角色链、输入释放与意图保持均通过。旧桥接 native=False 只供独立兼容 worker |
| `TestNativeGamePack` | 主代理报告 2 项通过：metadata-only 与实际安装 ZIP 后完整生产轮转 | 硬阻旧runtime/Qt；运行中 src 模块全部来自安装后的 payload；保留唯一释放、held清空、cancelled及enabled意图 |
| 两张战斗截图 | `in_combat.png` 识别 Iuno/Roccia/ShoreKeeper；`combat_has_cd.png` 识别 Aemeath/ShoreKeeper/Iuno | 现有截图的生产角色加载与轮转入口可执行；不能推断真实游戏内整轮战斗效果 |
| 停止与持久意图 | Runtime finally 的 release_all 恰好一次，held 清空，store enabled 保留，run 状态 cancelled | 单输入 owner 与协作停止链在离线运行成立；未证明所有真实设备的强杀清理 |
| 真实本地 OCR | onnxocr/OpenVINO CPU 对 `weekly_boss/detail.png` 识别 5 框，经生产 task.ocr；OCR 负责人另报告 6 项通过 | OCR 后端与生产接点可运行，处理结果对照旧 AST 处理；仍不是每日/账号业务验收 |
| 非 OCR 生产判断 | `con_full.png` 的 in_team 为 `(True, 2, 3)` 且未调用 OCR；`weekly_boss/list1.png` 非战斗 poll 无输入 | 对应帧的生产团队判定与非战斗保留意图行为成立 |

不重复已通过且未变的检查。`move_relative` 的生产 Task 合同是屏幕比例换算后绝对 move，不能按核心 dx/dy 接口擅改；旧桥接 Box class 注入用于真实 `isinstance` 接点，原生任务使用包内 Box。旧桥接与阶段测试数字保留为各自证据，最终 23 项不与它们累计。

本审查进程独立运行 post64 生产兼容回归：先安装生产 framework overlay，再将旧 `Config.config_folder` 绑定临时目录，随后导入四组 `TestGameRuntimeErrors`、`TestBaseCombatTask`、`TestAutoCombatRecovery`、`TestCharacterIdentityRecovery`。76 项通过，0 failure/error/skip，测试耗时 `.597` 秒；未初始化 OK 应用或设备。实际 import 路径使用新默认 legacy provider，异常类型及旧战斗恢复行为仍通过。

## 许可证与发布边界

包内 `src/vision/boxes.py`、`features.py`、OCR 和 `native_task.py` 是游戏包中的 AGPL 派生实现，不应迁入 MIT 核心。已安装 ok-script 1.0.190 的 metadata classifier 虽写 MIT，其真实 `dist-info/licenses/LICENSE.txt` 是 AGPL-3.0；仓库根 `LICENSE.txt` 也是 AGPL，不能用 classifier 把派生实现重新标为 MIT。

参考源码 SHA256：

- `ok/feature/Box.py`：`ff8076da66403d6fbac23d262d9cdd33aeaa161b18ae49befd210f4468b71e7d`
- `ok/feature/Feature.py`：`8d656c4d68c3a36bdde667ae93ffac10e5b9b3bca3351f29f32d00587a854902`
- `ok/feature/FeatureSet.py`：`baddc35efd3c2fe008c1ac610decd43b079d721d3417cdb4c982d0935629cd2d`

当前 `gameframe/pyproject.toml` 声明 MIT，并显式只打包 `gameframe` 与 `gameframe.devices`；源码游戏包 manifest 保留 AGPL 与旧运行时/资产原许可声明。独立核心的闭源发布空间取决于实际 wheel 不混入派生 `src`、模型或素材，并保留各外部依赖义务。游戏包去掉旧运行时导入不会自动消除既有 AGPL 义务；动态调用或分进程本身也不构成整体闭源授权结论。素材来源表提供出处证据，不能代替素材、模型、SDK 的商业授权。

已只读复核 `gamepacks/wuthering_waves_native/{plugin.py,manifest.json,requirements.txt,README.md}`、`scripts/build_native_gamepack.py`/`build_gamepack.py` 与 `TestNativeGamePack`：新包继续声明 AGPL；ZIP 入口与包依赖位于根，payload 只选完整 `src`、`assets`、根许可证及 provenance 两文件，不包含旧 `config.py`、`main.py`、custom_ok、私人 configs/logs、虚拟环境或供应商 DLL。完整 src 会保留尚未迁移的 GUI/每日源码，其存在不表示这些任务可从原生入口运行。

原生 plugin 元数据加载不导入 src/OCR；运行时将自身 payload 放入 sys.path 首位，指定 assets 的绝对路径。先切换到显式 data_dir，再创建 OCR 引擎及运行 Host，并在 finally 还原 cwd。真实安装的 onnxocr `predict_base.py` 使用 `Path.cwd()/cache/openvino`，模型默认位置则是其依赖安装目录，因此该切换有实际缓存写入合同依据。新的包测试检查所有运行中 src 模块实际来自已安装 payload、硬阻旧依赖、真实角色栈、唯一 release_all、cancelled 和 enabled 保持；主代理已报告该两项通过。本轮未重建核心 wheel，以上核心范围结论来自当前显式 setuptools 配置与 import 源码检查。

## 待最终装配完成后确认

1. 已完成自动战斗源码链及已安装 native ZIP 的 ok/Qt 阻断验收、真实模块来源与生产角色入口检查。
2. 新 Host 在 class-body calibration 创建前绑定 Config root；executor 在真实调用边界转换 Cancelled。已有模式锁测试防止已创建 MRO 跨 native/legacy 切换，class-body root 检查防止同进程混用数据目录。
3. 在源码集合稳定后完成 native/legacy 两种包构建文件集合与最终 MIT wheel 范围检查。版本、标签与发布由主代理统一处理。非战斗真实 import 调查及最小迁移批次见 `2026-10-11-gameframe-noncombat-native-boundary.md`。

来源：本仓库上述模块与测试、已安装 ok-script 1.0.190 源码/真实许可证、`v1.97.64` 源码基线；联合测试数字与完整战斗链来自对应负责人本轮输出。本文将独立 probe、源码核对与负责人报告区分记录，未把离线测试等同于真实游戏运行成功。
