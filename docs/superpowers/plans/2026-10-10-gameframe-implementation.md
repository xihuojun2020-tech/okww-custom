# GameFrame Implementation Plan

> **For agentic workers:** 按下面任务分批实施和审查。用户已授权自主实施，不再询问审批；禁止启动游戏／模拟器测试。使用现有 collaboration 工具和本地 .venv。

**Goal:** 实现独立框架与游戏包，保全并逐层迁移现有全部业务，完成两轮复核与离线验收。

**Architecture:** 独立Python核心加载游戏包，GUI与执行器分进程。当前鸣潮以明确的完整兼容包承接生产入口，核心与旧业务无反向依赖；后续逐层替换运行时。

**Tech Stack:** Python 3.12、stdlib、NumPy、OpenCV、PySide6；Windows可选windows-capture；原兼容包锁定ok-script 1.0.190。

**Spec:** [设计](../specs/2026-10-10-gameframe-design.md)。

## Global Constraints

继承设计中的全部用户约束；起始产品基线1.97.61，已集成1.97.63，本阶段1.97.64；不提升主／次版本。各任务只修改自己的文件，不回退既有脏文档。下面已勾选项表示有实现与离线证据；不表示游戏／设备实测通过。

## Task 1：备份、研究与基线

- [x] 保存Git bundle、工作区ZIP、dirty patch、逐文件SHA256，验证ZIP和哈希。
- [x] 保存后续来源研究、任务/API盘点、第一轮审查、素材来源表。
- [x] 逐项审核推荐与官方／社区证据冲突；更新设计。

## Task 2：核心与离线闭环

Files: gameframe/api.py、packages.py、runtime.py、state.py、vision.py、devices/replay.py；tests/TestGameFrameCore.py。

Consumes: 本地manifest和Frame/Action合同。Produces: PackageManifest读取、GamePackage.run(task_id,context)、Runtime.run(...), replay设备动作轨迹。

- [x] 测试以临时目录的真实PNG＋模板组成小包；规则识别后发送动作，而不是测试恒定True。
- [x] 未知任务、抛错任务、显式停止分别记录失败/取消，release_all总被执行。
- [x] 包路径和manifest在外部边界检查；不进入真实configs。
- [x] Run `.\.venv\Scripts\python.exe -m unittest tests.TestGameFrameCore`，核对结果与动作轨迹。

## Task 3：设备后端

Files: gameframe/devices/windows.py、mumu.py、adb.py；tests/TestGameFrameDevices.py。

Consumes: Device.next_frame/submit/release_all/close 与 Action。Produces: HWND WGC、新帧时间语义、Windows输入、MuMu触点ID持有与释放。

- [x] SDK/WGC依赖延迟导入；模块导入和CLI列包无设备操作。
- [x] 原生接口用注入的采集器／DLL模拟合同测试，不打开真实窗口。
- [x] 两个触点同时持有时只释放指定ID；退出释放全部，采集失败明确报告。
- [x] 验证帧buffer所有权、新帧序号和停止后线程清理。

## Task 4：完整鸣潮兼容包与构建

Files: gamepacks/wuthering_waves/manifest.json、plugin.py、README.md；scripts/build_gamepack.py；tests/TestGameFrameMigration.py。

Consumes: 完整原程序生产bootstrap和注册配置。Produces: 应用＋29个任务metadata、所有业务生产入口、自包含源码包ZIP（仍需安装锁定依赖）。

- [x] 静态提取注册项，检查manifest每项都指向真实类；不执行任务初始化。
- [x] 原入口与包入口共用生产启动流程；旧UI/诊断/账号/更新能力不删减。
- [x] 构建只复制源码、默认元数据和素材，排除真实configs、logs、.venv、NAS证据；保留许可证与来源表。
- [x] 用临时解包目录检查不存在源checkout依赖，验证全部注册文件和资源引用。
- [x] 标为兼容迁移，不标全部独立重写完成。

## Task 5：启动器与执行器

Files: gameframe/controller.py、worker.py、gui.py、__main__.py；tests/TestGameFrameLauncher.py。

Consumes: manifest task列表与TaskContext。Produces: list/inspect/replay/run/gui命令；子进程状态、停止与退出。

- [x] 独立fixture包子进程运行真实图像任务；首帧与动作在执行器内部。
- [x] GUI元数据检查不导入旧游戏业务；配置来自包任务默认字段。
- [x] 停止仅管理自己的执行器与输入，不杀无关进程；子进程失败回报非零退出。
- [x] QT_QPA_PLATFORM=offscreen对界面加载做离线测试，不启动游戏。

## Task 6：已确认根因修复与第一轮回归

Files: main.py、custom_ok/ok/task/TaskExecutor.py、已盘点YOLO两个实现及对应测试；root统一版本与release notes。

- [x] 移除共享虚拟环境框架覆写，改为生产和测试共用进程内 import overlay，防止混版继续启动。
- [x] after_run出错仍释放输入、destroy及清理身份上下文；普通hook不杀自动战斗服务。
- [x] 检测后端失败不返回等价于有效空检测的假结果。
- [x] 运行不触设备的故障注入测试及已盘点纯单元/截图组，保留完整结果摘要。

## Task 7：逐层独立迁移

- [x] 依据模块矩阵，将各ok依赖归入core替换、gamepack保留、UI扩展、platform边界。
- [x] 五项颜色工具迁入独立包内模块，以真实截图逐像素／占比对照旧实现；生产12个文件已改用新导入。
- [ ] 迁移 Box／COCO FeatureSet，用原截图逐项对照坐标／置信度／灰度／mask／回调／缩放结果。
- [ ] 以 Replay／mock Device 实施实际帧缓存、输入和停止任务桥，保持生产异常、场景和角色算法合同。
- [ ] 完成配置、OCR、场景／角色工厂装配，不创建 OK 应用即可执行生产战斗，随后才登记原生战斗入口。
- [ ] 每次替换一项生产边界，用原业务离线测试覆盖，再移除相应兼容依赖。
- [ ] 保留账号快照/精确身份、消费待确认、累计目标与周期完成、自动战斗启用偏好与单一输入者。
- [ ] 任务/角色/业务模块覆盖完整后才判断独立迁移是否完成。

## Task 8：复核、备份与发布

- [x] 第二轮独立审查新核心、设备、包构建、迁移业务和完整模块矩阵；既有任务／业务／运行时／角色另有逐模块覆盖记录。
- [x] 复验本阶段具体修复；新代码新增保护分支逐项指向真实边界，删除无依据分支。
- [ ] 生成阶段备份与机器可读验收记录，更新版本/更新日志。
- [ ] 只stage本次文件，commit、annotated tag和branch/tag push；不带入原有脏文档或私人资料。
- [ ] 所有目标有证据达成后结束goal和提醒；否则保持active并持续下一步。
