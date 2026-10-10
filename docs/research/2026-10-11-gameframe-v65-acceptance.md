# GameFrame 1.97.65 阶段验收

独立战斗包已在不导入 ok-script／Qt 的进程中执行真实 AutoCombat 和原角色轮转；安装后的 ZIP 也通过同一业务链验收。完整日常、多账号、挑战、诊断、更新和原界面由完整兼容包保留，下一批继续独立迁移。本报告不将源码存在、注册入口或仅能导入算作业务完成。

## 代码与运行证据

| 检查 | 结果 | 能证明的范围 |
|---|---|---|
| NativeCombatHost + NativeCombatExecutor | 最终 23 项通过，13.628 秒 | 屏蔽 ok/PySide6/qfluent 导入，真实截图识别两组角色，进入原 perform/do_perform，Replay动作、停止、暂停、连续故障恢复、单次输入释放与启用意图；真实本地 OCR 同帧推理一次、换帧重新推理 |
| NativeTask + NativeCombatExecutor | 最终 20 项通过 | 实际滚轮、文字、拖动 API；停止竞态与持有按钮释放；OCR 阈值属性委托真实服务 |
| Windows/MuMu/ADB 模拟设备合同 | 15 项通过 | 客户区、新帧、WGC失败、键鼠/多触点、Unicode与代理对、滚轮方向、失败抬键仍持有并清理；未调用真实设备 |
| 原生日志／任务／Feature 对照修复 | 19 项通过 | 错误日志落入显式目录、证据保存到监控室；v64生产宽屏锚点的独立基线，避免空名单对照 |
| 生产兼容回归 | 76 项通过，0 failure/error/skip | 隔离配置与生产 overlay 下，原 GameRuntimeErrors/BaseCombat/AutoCombatRecovery/CharacterIdentityRecovery 保持原行为 |
| 最终包与版本 | 9 项通过，11.019 秒 | 完整兼容包清单/构建、原生 ZIP 实际生产轮转、元数据安全、固定宽度版本与更新日志同步 |
| MIT wheel | 隔离 `-I` 进程通过 | core/runtime/worker/CLI 可在禁止游戏、旧框架与 UI 导入时加载；wheel不含 src/assets/custom_ok。使用已有第三方依赖，不是全新环境安装测试 |

这些批次有测试重叠，不能相加为独立测试总数。OCR使用本机已安装 onnxocr 与 OpenVINO CPU 模型，不下载模型；只有 Device 输入边界模拟，战斗识别、角色加载和轮转没有替换成固定成功。

发布前另两项专项回归通过：真实开放世界分类不载入 Daily／Tacet，忌炎相对中键点击保持原宽屏全屏像素语义并释放输入。首个 down 后取消的轮转测试不覆盖所有角色后续分支；发布前静态比对已核对角色源码实际引用的 Task 属性，未将它当作全场景实战验证。

## 可恢复备份与分发物

本阶段目录：`E:/AI work/okww-framework-backups/20261011-v1.97.65`。保存源码 ZIP、逐文件 SHA256、Git状态/补丁、完整 Git bundle 和机器可读验收记录；原有脏文档和删除状态保留，不进入代码发布提交。

| 分发物 | 字节 | SHA256 |
|---|---:|---|
| gameframe_runtime-1.97.65-py3-none-any.whl | 28749 | a6c088271a832673fa2536df777ae99ade91afd2405b0f5fd8e84b49e3b0b176 |
| wuthering_waves-1.97.65.zip | 38841609 | df9cd78cea7163838fc6fb7a4cd9c6e20e90e93eaae3319d6af1b23dc2beb5b7 |
| wuthering_waves_native-1.97.65.zip | 38256797 | 723d49b2b964df4588c2b86b0abee8bde8ea118e4bf6949f4c967b4eff960570 |

两份最终 ZIP 均在临时目录完成原子安装及完整 SHA256 索引校验；兼容包全部30个入口解析到自身 payload。最终 artifact 校验只加载元数据和解析命令；真实独立轮转来自上述安装 ZIP 的测试，不执行兼容应用。

核心采用目录内 MIT；角色、视觉／OCR／任务派生实现与鸣潮包继续 AGPL。替换素材不消除已有代码许可义务。素材原版/修改/待确认清单沿用逐文件来源表；未匹配上游不代表拥有版权。

## 后续迁移边界

另28个任务各在独立阻断导入进程探测：MaterialPlanner/Solo可以导入，26个遇到真实旧依赖；两个导入成功者也未算业务验收。下一批依照 `2026-10-11-gameframe-noncombat-native-boundary.md` 实施通用任务、原类名/生命周期、组内账号服务、明确数据根与设备初始化前的完整性校验。账号切换测试继续复用生产选号、别名/掩码身份、登录、核验与消费账本。

没有启动游戏或模拟器，没有真实账号操作、Child Session、NAS访问、硬件捕获/输入或延迟测量。已证明的是离线算法接线、包移植性与停止合同，尚未证明整场实战或后台会话兼容性。总目标保持进行中，线程提醒与临时系统保持唤醒继续启用。
