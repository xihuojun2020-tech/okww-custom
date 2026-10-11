# GameFrame 最终交付覆盖核查

核查日期：2026-10-11；生产源码版本：`1.97.76`。**已确认的原魔改版消费者迁移缺口现已接通，当前没有发现阻止这批独立框架与鸣潮包交付的必需实现缺口。** 这个结论限定于已盘点并有调用依据的产品行为；它不表示29个任务、全部角色、真实登录、后台桌面或模拟器战斗已经实测成功。

本报告更新 v71 的 `final-coverage-gaps` 与 v73 的 `remaining-consumer-audit` 的状态，保留两份历史报告原文。核查读取当前生产入口、native manifest、核心 README、迁移 inventory、v71–v75 验收及 v76 本地安装证据；唯一新增文件为本文。没有启动游戏、模拟器、真实设备或系统输入，没有访问真实账号、NAS、驱动或创建真实计划任务。下文“已接通”要求存在实际生产消费者，接口定义、任务注册、mock返回值和适配器本身不单独作为游戏验收。

## 1. 功能矩阵：实现、离线证据与实际限制

证据简称：**A71–A75** 为各版本的离线验收报告；**M76** 为实际离线托管安装记录；**R76** 为实际安装后的生产轮转 Replay 记录；**T** 为对应源码专项测试。测试文件列出可定位的检查范围，不表示本轮重新运行了这些检查。M76/R76 的结果来自已生成的 JSON 回执及对应执行脚本，和使用假 pip/假租约的单元测试分开记录。

| 功能 | 当前生产实现路径与判定 | 离线证据 | 剩余实测限制 |
| --- | --- | --- | --- |
| 通用核心、包发现与执行 | `gameframe/api.py`、`runtime.py`、`state.py`、`packages.py`、controller/worker；设备帧、动作、取消、运行记录、索引和能力检查有真实实现。核心不导入鸣潮规则或 `ok`。 | T：TestGameFrameCore/Worker/CLI；A73–A75 的独立 wheel 逐字节源码与隔离导入核对；M76 的安装来源核对。 | 其他游戏仍须自行提供规则和素材；不是自动生成游戏日常的框架。 |
| 原29个内置任务与角色轮转 | native manifest 将原生产 module/class 注册到 `NativeCombatHost`、`native_task`、`native_combat_executor`；战斗复用 `src/task`、`src/combat`、`src/char` 的生产算法。 | 迁移 inventory 的注册对照；T：NativeCombatHost/BusinessTasks/WWOneTime；A71–A75 的安装 payload 生产轮转 Replay；R76 从真实安装core和ZIP payload加载212个src模块、产生2次Replay动作，取消后enabled仍为True。 | 注册、识别一张图片或到达一次输入分支不等于整轮日常、全部挑战和每个角色实战通过。 |
| 自动战斗持久意图与单输入 owner | host/executor共享前台与辅助战斗；普通错误、采集失败、恢复或观察者失败保留启用意图；显式停用才保存关闭。worker持包、数据与输入租约至清理结束。 | T：NativeCombatHost/Executor、GameFrameProcessLocks/WorkerLeases；A74–A75 的失败、暂停、退出与输入释放检查。 | WGC断开、原生调用阻塞及真实长时间错误恢复还需设备验收；强制终止不是正常清理或业务成功。 |
| 首账号、完整性、账号包及组内切号 | `native_management`、account repository/identity、`account_runtime_bootstrap`、`LoginFlowService`；UUID、修订、精确别名/掩码手机号、运行快照、事务和证据沿用原业务。`TestAccountSwitchTask`复用生产切号链。 | T：NativeAccountRuntime、AccountRuntime/Identity相关检查；合成账号与安装管理验收。 | 真实缓存列表、A1/A3/A4连续切换、验证码/登录/OCR与进入世界没有本轮实测。 |
| 每日计划、材料、配额与任务队列 | ManagementWindow→AccountSettings/AccountConfig及现有材料、周本、凝素、队列控件；数据读写与实际Daily/MultiAccount任务使用同一模型。 | inventory；T：NativeConfiguration、材料/配额/队列及生产业务图片回放；A73 的真实配置 JSONL。 | 领奖/资源消费和整轮断点续跑需游戏现场核验；返回成功不能替代确认账本。 |
| 特征码连续读取与确认绑定 | ManagementWindow的 `NativeLiveBridge`→GUI live路由→现有host；AccountConfigTab连续观察后预览、人工确认，再按预期revision重绑定并备份。 | A72：live management/inspection 6项；T：NativeLiveManagement/Inspection。 | 必须有真实执行owner；无设备管理页不能伪造读取，真实游戏OCR准确性尚未验证。 |
| 需要设备的配置动作 | NativeConfigurationTab的 `invoke-action`桥接到已运行host；复用已存在任务实例，管理动作与设备动作有明确边界。 | A72、T：NativeConfigurationUI/LiveManagement。 | 不另建第二输入owner；每个需要真实设备的回调仍须现场验收。 |
| 辅助服务恢复、运行/暂停/停止与热键 | `GameFrameWindow._restore_saved_session`按保存包/设备恢复session-only；无设备或未建立可信配置时保留配置界面。热键可在无会话时启动、运行时暂停/恢复。 | A73的session-only与保存偏好；A74的无会话热键；T：GameFrameSessionStartup/DesktopControls。 | 不升级强开已有禁用配置；真实注册冲突、游戏前台及用户停止交互尚未实测。 |
| 主页面账号上下文、分类与隐藏任务 | GUI通过配置owner/live owner查询原MultiAccount权威，显示已核验账号并在忙时锁编辑；manifest分类/排序复用原规则。PianoTeaching/SecondSol/EchoesRemain保留注册且隐藏。 | A73账号界面与builder元数据检查；T：NativeAccountContext/GameFrameAccountContext。 | A/B槽位不是Windows用户；运行中身份显示还需真实切号确认。 |
| 任务配置及六语言 | `native_metadata`、NativeConfigurationTab与真实Config写入；Language偏好、native/ok gettext fallback、worker与管理Qt安装路径已接通。调度/维护页固定文字已接 `translate()`；DeviceEditor字段、后端显示名、提示和错误已接现有launcher labels，GUI在加载与重置语言时调用。模板保留placeholder，用户内容不翻译。 | A73语言/配置元数据；A75六语言新增21条；v76每语言新增114条、原译文保留，语言专项10项通过。最终安装core/payload的设备5项及定时/维护页1项离屏检查通过。 | 六语言选择与已接通页面不保证每条错误/厂商名称均本地化；协议ID、后端算法名、JSON及用户数据保留原文。 |
| 程序偏好与OCR推理 | NativeProgramPreferences→WindowsPreferences真实静音/恢复、客户区缩放、已选PID退出检测；Trigger Interval进入host调度；Use DirectML进入OCR factory。 | A73偏好/OCR及ONNX provider fixture；T：NativeProgramPreferences；A75遮罩偏好。 | Auto按provider可用性选择，与旧NVIDIA空闲显存启发式不同；DML、音频、缩放与退出硬件行为没有现场验收。 |
| 托盘、GUI geometry、截图与手工OCR | desktop_controls、GUI保存/恢复geometry；live请求由owner释放输入后采集，截图保存身份遮罩副本，OCR用原帧；结果只返回请求方。 | A72桌面/截图/OCR；A74窗口普通/最大化恢复；T：NativeScreenshots/LiveInspection。 | 屏幕/DPI、实际热键、前台和真实截图仍须实测；截图遮罩与实时遮罩分别验收。 |
| 六个外部通知渠道 | plugin构造NativeNotificationHub；HTTP支持Discord/Telegram/企业微信/QQ Guild，QQ/微信桌面投递在现有输入owner边界串行交接；密钥保存/清除不回显。 | A74最终安装扩展34项；T：NativeNotifications/DesktopNotifications/NotificationOwnerIntegration。 | 没有真实发送或剪贴板操作；QQ Guild沿原语义只说明图片数量，不上传图片；桌面联系人/窗口兼容性不可靠。 |
| UID实时遮罩 | `NativeUIDOverlay`从当前owner缓存帧处理ROI，Blur/Inpaint/interval读Program Preferences；MIT PatchOverlay仅画通用PNG patch。暂停、采集失败、失去可信前台、停止和退出清除。 | A75 UID接线9项、最终producer/renderer 5项；T：NativeUIDOverlay与overlay接线。 | 实际游戏DPI/移动/遮挡和视觉效果尚未验证；不把诊断旧帧复活为当前帧。 |
| GPU启动告警 | worker `device_ready`→plugin→AGPL NativeGpuAdvisory/vendor；对真实已选Windows目标一次只读检测，未知与明确关闭分开，不修改驱动/HDR。 | A75 GPU11项及启动钩子状态；GPU provenance固定上游commit/SHA。 | NVAPI/ADLX/目标显示器/真实GPU状态未经本轮查询；日志观察不证明游戏渲染效果。 |
| Windows捕获与输入选择 | DeviceEditor→WindowsDevice真实WGC、BitBlt_RenderFull/PrintWindow、SendInput/PostMessage后端；显式选项，无猜测fallback。 | A75后端/geometry15项及原设备16项；T：GameFrameWin32Options/Devices。 | GDI同步调用可能超过timeout，拒绝最小化，不保证帧新鲜；PostMessage无raw relative mouse/物理鼠标能力，MouseReset不兼容；消息API接受不等于游戏处理。 |
| 完成证据、总览、耗时与退出 | CompletionCheckTab、native_overview、NativeExecutionOverviewDialog、DailyTimingDialog复用真实账本；成功后的Exit After Task释放输入并只结束已选目标游戏。 | A71–A75安装管理/只读总览；T：NativeExecutionOverview、证据与周期检查。 | 真实结算和跨日/跨周完成判定未由这些界面测试证明；不扩展为Windows关机。 |
| 配置维护、备份与输出迁移 | `native_maintenance`、NativeMaintenanceTab复用完整备份/验证/恢复/序列修复；NativeStorageService复用复制、校验、提交和owner重绑。账号/脚本数据根仍为权威。 | A72迁移5项+原存储16项；T：NativeMaintenanceUI/StorageManagementUI；提交后失败fixture。 | 真实DPAPI跨用户资料、实际磁盘损坏与大资料迁移没有本轮验收；不将输出迁移描述为账号根自动搬家。 |
| 角色编辑与用户脚本包 | NativeCharacterCodeTab/store/loader/owner reload；NativeUserTaskTab与bundle不可变catalog、稳定ID、namespace素材和运行registry原子重载。 | A71角色存储/UI/session、脚本包13项、安装namespace识别及破损候选保留旧registry；T：NativeCharacter/UserTask/Bundle系列。 | 只支持已明确转换契约的旧脚本API；未知依赖失败，任意第三方脚本不承诺自动兼容。 |
| 本地诊断与手动NAS归档入口 | `native_diagnostics`接现有local-only session、遮罩、脱敏和故障观察；ManagementWindow复用DiagnosticStatusCard的显式打包/上传路径。local-only不启动背景上传任务。 | A72–A75安装本地诊断；T：NativeDiagnostics与既有Archive/Retention tests。 | 未连接NAS或执行真实上传/审核。当前仅使用 `.173` 共享；ZIP实际审核后仍须实质报告与verified SHA review命令，不能由列表或本报告代替。 |
| 人工ZIP更新与完整环境更新 | 原indexed ZIP更新保留依赖检查、owner门禁、journal/rollback；v76 update_controls→独立package_process→NativeReleaseService验证schema2配对core/gamepack/wheels，再准备pending。 | A74真实拒绝跨依赖ZIP热更；T：NativeGamePackUpdate/NativeRelease/NativeUpdateControls；M76真实安装、缺requests拒绝、设备无关hook。 | 缺明确enabled源返回source_unconfigured且不访问默认NAS；pending不等于已切换。真实HTTPS/SMB投递未测试。 |
| 三种策略与正常启动原子切换 | Manual自动请求零source访问；稳定版只选stable，预发布选stable/beta/alpha，按完整身份排序不降级。managed bootstrap短switch gate→environment排他提交→整个子进程共享租约；失败验证旧active，明确retry。 | T：NativeRelease/ManagedInstallation/ManagedEntries；M76 copied bootstrap与安装core真实跨进程锁、busy owner保持active/pending、precommit失败保留旧active。 | schema限定三段数值及aN/bN；不支持rc/dev/local版本。真实应用退出/重启与长时间worker组合尚未现场验收。 |
| 登录自启与稳定系统定时 | HKCU自有GameFrame值仅显式保存；managed登录命令指稳定pythonw/bootstrap。NativeSchedule用安装根/package_id/当前用户稳定身份，bootstrap执行当前active及有效data_root；旧owned版本目录计划只提示并允许显式删除重建。 | T：GameFrameLoginStart/ManagedInstallation/NativeSchedule；调度专项7项、Qt假scheduler及bootstrap task dispatch fixture。 | 未写真实注册表、COM计划或登录/时间触发。仅当前用户交互会话；不自动切Windows用户，不隐藏worker占用。 |

## 2. 两份历史缺口报告已如何关闭

| 历史缺口 | 当前结论 |
| --- | --- |
| 特征码没有可用入口、设备动作按钮禁用 | v72 live bridge与owner动作请求已接；绑定仍需人工确认和revision事务。 |
| 打开应用没有辅助恢复、无会话热键不能启动 | v73 session-only恢复与v74 hotkey启动已接，保留原启用偏好。 |
| 当前账号/序列与导航、三项活动显示不一致 | v73复用权威上下文与分类，三项活动隐藏保持注册。 |
| 语言与真实Basic Options消费者缺失 | v73真实偏好/OCR、六语言加载已接；v75遮罩字段及v76调度/维护和设备表单固定文字接线补齐。 |
| 六个外部通知、UID实时遮罩、GPU告警缺失 | v74通知与owner交接、v75 producer/renderer及只读GPU告警已接。 |
| 只有WGC/SendInput、GUI位置大小不能恢复 | v75真实后端选择；v74geometry持久化。后端能力限制继续保留。 |
| Windows登录自启与三种自动更新没有原生消费者 | v76显式HKCU保存和完整托管配对更新已接；不依赖旧PyAppify app.json。 |
| 新托管更新后定时仍绑定旧环境；改data_root导致更新失败 | v76稳定bootstrap调度、稳定计划身份，以及CLI按owned launcher-context解析effective_root已修。 |

PyAppify的Launcher/OpenLauncher、kill/hide/self-upgrade、app_profile与PID清理是旧发行器协议，当前核心没有相应发行器进程；这些不列为必需迁移遗漏。`Auto Start Game When App Starts`在旧检查范围只有定义、且产品 `start_exe=False`，不能凭字段推导未迁移游戏自动启动。旧DX11布尔分支在该产品启动路径不可达，用户可明确给launch_command参数；不宣称已迁移该布尔偏好。HDR/night-light四字段未发现旧消费者，不添加强关行为。旧Fluent侧栏状态与锁定浅色主题也不要求新增当前布局不存在的开关。已注释的KR切换及弃用任务不恢复。

## 3. 实际v76安装证据和交付状态分开记录

已读取 `E:/AI work/okww-framework-backups/20261011-v1.97.76/managed-acceptance.json` 与 `managed_v76.py`。记录确认：真实创建venv、真实offline pip安装与pip check、30个依赖wheel、新core来源位于候选环境、29项manifest注册和文件索引有效；缺requests的真实resolver失败，不生成active/pending并删除本次失败环境。合成AutoCombat配置字节保持不变。复制到版本目录外的stdlib bootstrap与候选core的真实独立进程共享/排他锁互通，busy owner保留原active，坏receipt在owner离开后明确记录precommit失败并保留已验证active；实际安装包的设备无关更新hook返回source_unconfigured。

`final-rotation-acceptance.json`另记录最终E盘交付解释器/core与已安装ZIP payload的生产轮转回放：`install_archive`核验534个索引文件，归档字节未变；加载212个src模块，产生2次Replay动作，最终状态为cancelled且enabled为True。`real_input=false`，因此只证明真实安装环境能执行这条生产回放及保留启用意图，不证明游戏战斗成功。设备标签收尾后的最终core SHA为`b1010d6dcf63c00b5b69f5582ea7eda1d157b393c00f89db09d4750cee9d8881`，原生ZIP SHA为`0e5f6a825a97a0a48a88c6893302306ca50aa8e8667b713e7614cd60795653bc`；逐成员delta证明战斗与账号算法没有变化。

主线记录的v76专项结果为：release 11项、transport 6项、manifest 3项、managed 16项、entries 8项、login 6项、update 10项、schedule 7项及management pages 1项通过；最终组合50项先有49项通过，唯一旧fixture失败修正后单项复跑通过。这是主线已经执行的检查记录，本轮只读复核没有重新运行测试，也不将这些计数当作真实Windows触发或游戏结果。

这些记录关闭了此前“只做假venv/pip/租约fixture”的安装验证限制。实验安装的准备、commit和失败路径使用模拟GUI回调，没有真实设备。最终`delivery-installation.json`状态为`ready-pending-first-user-launch`：干净用户根`E:/AI work/GameFrame/Administrator`的Runtime、Managed和空LauncherData均已建立，实际offline pip/check/preflight和ready核对通过。稳定`Start-GameFrame.cmd`已生成但未执行，valid pending留给用户首次启动提交，不注册登录项或系统计划。先前AppData路径实际进入Codex MSIX LocalCache，已保留历史实验并改为E盘独立安装。`installed-surfaces-acceptance.json`记录最终安装code/catalog的6项离屏Qt检查；用户资料仍为空。最终哈希见`artifacts-acceptance.json`，备份与Git发布见主线`release.json`。

## 4. MuMu、雷电和后台会话的精确边界

| 路线 | 已实施能力 | 尚未实施或验证的范围 |
| --- | --- | --- |
| MuMu SDK | `gameframe/devices/mumu.py`动态加载用户DLL，nemu原始像素、display/app选择、0–9 contact映射SDK finger 1–10、持续down/move/up和退出释放；worker和设备表单有真实入口。 | SDK仅mock契约检查，未运行厂商DLL/模拟器；同步capture无取消timeout；不分发DLL。鸣潮native manifest仅Windows键鼠包，没有移动端任务映射。 |
| 雷电/通用ADB | `devices/adb.py`明确serial与adb_path、PNG screencap、tap/swipe/keyevent；是可运行的通用Android适配器，雷电可通过已有ADB端点接入。 | 没有雷电原生ldopengl截图或MaaTouch持续多点实现；它们是后续研究路线。ADB不是低延迟流，不支持持续多触点，不宣称雷电9/14原生SDK兼容。 |
| PC主桌面输入 | 默认SendInput要求选定游戏在当前会话前台；PostMessage提供消息后端并如实声明能力限制。Windows输入锁按真实WindowStation/Desktop统一owner。 | PostMessage是否被游戏消费未验证，显式activate仍改变前台；不能保证后台动作或不抢键鼠。 |
| Child Session/本机RDP | 已有固定源码与官方契约研究；框架的环境内执行器可以作为后续验证对象。 | 当前没有创建/宿主/编排Child Session的产品实现。它不是“已有实现但仅缺实测”的功能；此批授权范围为研究边界，不新增会话管理。反作弊、相对鼠标、锁屏/断开及主桌面影响仍未知。 |
| 多Windows用户 | 当前身份、资料根及包资料可见；登录与定时按当前用户；组内账号仍由生产流程切换。 | 系统用户由人手动切换；A/B槽位不自动等于OS用户，未建立跨用户全局账本或自动用户切换。不得让四用户无协调共写同一账号根。 |

MuMu和ADB的输入锁分别以安装/instance与serial命名，当前没有同一模拟器的跨backend映射，不能承诺两者操作同实例时互斥。Replay无真实输入。CPU/GPU/显存竞争、capture返回到动作的端到端延迟、帧年龄及长期战斗稳定性都没有本轮实测，不能由供应商FPS宣传或host-received时间推出低延迟成功。

## 5. MIT核心、AGPL派生与295项素材

独立编写的通用框架在 `gameframe/LICENSE` 和pyproject中采用MIT；鸣潮生产规则、账号/诊断/UI派生、旧gettext资源和GPU vendor留在AGPL包。原生执行器的隔离测试阻止 `ok`、Qt和qfluentwidgets导入；管理进程复用AGPL业务及相应GUI依赖。兼容包仍是旧AGPL应用适配，不把它当成完全独立执行器。分进程、换包名或换素材均不自动解除派生代码的许可义务，也不代表整个鸣潮产品可以闭源。

素材来源表对 `assets/` 与 `tests/images/` 的**295个文件**按固定上游commit `b210632a251371cc0bbb1d0e28ce16ff35657824` 比较：

| 分类 | 数量 | 可证明的内容 |
| --- | ---: | --- |
| upstream-identical | 67 | 本地blob在该上游commit存在，可能位于不同路径。 |
| upstream-modified | 10 | 同路径上游存在，但本地字节改变。 |
| custom-or-unverified | 218 | 没有匹配上游blob；不证明自有版权或再分发授权。 |

126张PNG fixture可用于离线回放，存在图片不等于已经执行相应任务。COCO有292条标注/类别、166条image记录及60个唯一可解析图像引用；裁剪或新增标注不使源像素变成原创。echo.onnx是独立模型权重，需单独核实来源。分类表及逐文件SHA随包保留，目前没有把295项全部替换为自有素材。用户接受素材暂时复用，后续按标签、尺寸、ROI、阈值与许可逐项替换。

GPU vendor固定到ok-script `90f4d86991329196cf935a19f64d528a16025a4b`，来源与AGPL许可另有SHA证据。MuMu/雷电厂商SDK不因EmulatorExtras或外围开源代码而自动获得分发权；当前动态加载用户DLL且不打包供应商DLL，商业使用授权仍须核对厂商条款。MIT只描述独立核心范围，不扩展到这些代码、图片、模型或厂商组件。

## 6. 证据索引

- [迁移前inventory](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-10-framework-migration-inventory.md>)：原注册表、业务与框架API盘点。
- [v71缺口基线](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-final-coverage-gaps.md>)、[v73消费者审计](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-remaining-consumer-audit.md>)：旧缺口及明确不适用依据。
- [A71](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-v71-acceptance.md>)、[A72](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-v72-acceptance.md>)、[A73](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-v73-acceptance.md>)、[A74](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-v74-acceptance.md>)、[A75](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-v75-acceptance.md>)：各版本实际离线执行范围。
- [M76回执](<E:/AI work/okww-framework-backups/20261011-v1.97.76/managed-acceptance.json>)、[M76执行脚本](<E:/AI work/ok-wuthering-waves-master/test_out/gameframe_acceptance/managed_v76.py>)、[R76轮转回执](<E:/AI work/okww-framework-backups/20261011-v1.97.76/final-rotation-acceptance.json>)、[用户交付记录](<E:/AI work/okww-framework-backups/20261011-v1.97.76/delivery-installation.json>)、[最终安装界面检查](<E:/AI work/okww-framework-backups/20261011-v1.97.76/installed-surfaces-acceptance.json>)、[v76工件记录](<E:/AI work/okww-framework-backups/20261011-v1.97.76/artifacts-acceptance.json>)：本地真实离线安装、依赖失败、跨进程锁、最终安装生产Replay与离屏Qt证据。用户入口已生成，未实际启动。
- [当前核心README](<E:/AI work/ok-wuthering-waves-master/gameframe/README.md>)、[native manifest](<E:/AI work/ok-wuthering-waves-master/gamepacks/wuthering_waves_native/manifest.json>)：设备能力、平台、完整发行身份及最低core版本。
- [295项素材分类](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-10-framework-asset-provenance.md>)及[逐文件JSON](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-10-framework-asset-provenance.json>)、[GPU来源](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-11-gameframe-v75-gpu-provenance.md>)：来源和许可范围。
- [后台可行性研究](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-10-okww-framework-and-background-feasibility.md>)、[多用户/模拟器/低延迟补充](<E:/AI work/ok-wuthering-waves-master/docs/research/2026-10-10-multiaccount-emulator-lowlatency-feasibility.md>)：Child Session、厂商SDK与后续路线；没有本轮实际性能数据。

本报告保留的验收边界是明确可定位的：没有游戏、真实账号、输入、消息、驱动、NAS、Windows登录/定时触发和后台会话的成功记录。真实离线安装已经通过，游戏行为仍需按任务、角色和目标设备逐项验收。
