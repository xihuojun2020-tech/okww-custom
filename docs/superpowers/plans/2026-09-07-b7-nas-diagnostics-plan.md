# B7 领奖确认与 NAS 诊断链路详细任务方案

> 执行说明：按任务逐项实现、测试、复核。本文为计划交付，不代表已经修改代码、连接NAS、部署定时任务或授权更改服务。实现时沿用用户已明确的授权范围；设备凭据、真实游戏操作和外部部署分别按实际范围处理。

**Goal:** 优先解决v1.35.00领奖确认的实机盲区，再建立不影响游戏运行、可恢复、可脱敏、可校验的NAS诊断交付链路。
**Architecture:** B7修复与NAS链路独立发布。诊断使用本地持久目录、不可变上传批次及独立上传进程；主程序只记录本地事件，不在GUI/战斗线程访问SMB。NAS只处理完成且哈希通过的批次。
**Tech Stack:** Windows、Python 3.12、本地.venv、标准库、现有ok-script/Qt和日志脱敏工具；SMB使用Windows已有凭据；优先复用已有PowerShell同步脚本和计划任务。
**Spec:** `E:/AI work/程序日志与截图自动上传NAS实现规格.md`；`E:/AI work/nas_ai_log_reader.md`；用户提供的20260901–20260907对话记录汇总；当前仓库v1.35.00实现。

## 1. 当前事实与证据限制

- 当前代码基线v1.35.00，提交f2c15764；已有A4异常分流、领域阶段门禁和领奖确认。
- 汇总声称B7已从240扣至120，但结算弹窗遮挡旧OCR区域；本任务尚未拿到该B7诊断包和对应图像，因此先核验，不把汇总当作已经复现的代码事实。
- 规格路径是 `\\192.168.3.170\AI诊断`，对话汇总称实际路径是 `\\192.168.3.170\xihuojun 共享给我\AI诊断`。以后者作为待验证候选，不能声称已连接成功。
- 当前设备没有发现映射SMB盘，也未在E:/AI work中找到nas_log_sync.ps1或一键上传脚本。它们可能只在笔记本上，不能重复创建后再排查冲突。
- src/diagnose.py现有export_diagnostic_archive只分享脱敏文本，排除图片；截图上传需要新增独立策略，不直接取消原保护。
- main.py已有启动错误报告、单实例检查与atexit清理；框架另有任务异常和截图保存路径，接入前需避免重复注册/重复上传。
- 不把旧汇总的“3.1秒固定识别超时”“当前体力2不能继续”“B12/B13裸名必错”等结论重新引入实现。

## 2. 任务边界与顺序

| 阶段 | 内容 | 依赖 | 交付 |
| --- | --- | --- | --- |
| A0 | B7证据和实际版本核验 | B7原始诊断包 | 定位记录、脱敏回归帧 |
| A1 | 领奖结果分状态确认 | A0 | 独立修复与测试 |
| B0 | NAS路径、权限、已有脚本/任务盘点 | 目标设备只读材料 | 链路清单和部署差异 |
| B1 | 本地运行目录与事件批次 | 无需NAS | 可测试的本地诊断模块 |
| B2 | 脱敏与截图导出策略 | B1 | 可上传批次，无原始凭据 |
| B3 | 持久上传和断网重试 | B0–B2 | 独立上传器与状态文件 |
| B4 | 程序启动/退出/错误/截图接入 | B1–B3 | 产品端完整触发链 |
| B5 | NAS读取与分析协议 | B3 | NAS读取工具/操作文档 |
| C | 集成验收、发布、受控部署 | 对应阶段通过 | 版本、更新包、实机验收记录 |

A与B独立，不因NAS权限问题延迟B7修复，也不因B7证据尚未到齐停止本地上传模块开发。当前只生成方案。

此前讨论的“自动战斗遇可恢复错误保持开启”列为独立后续任务，不混入本次NAS或领奖修复；手动停用必须始终生效。

## 3. 必须先解决的设计差异

### 3.1 退出后补传

进程内daemon线程会随程序退出，不能满足“NAS恢复后无需重新打开游戏就补传”。采用独立上传入口，复用或更新已有Windows计划任务，建议登录后触发并每5分钟扫描一次。每次进程处理到队列清空或达到运行预算退出；运行中的客户端可唤醒同一个上传器。单实例锁防止计划任务和客户端同时处理队列。

已有每小时任务如仅复制原日志，不能与新上传器同时读取同一队列并写同名文件；先记录旧配置，验收后切换唯一队列所有者，不删除其他用户任务。

### 3.2 运行中错误要立即可分析

一个run只有退出时才写_UPLOAD_COMPLETE，会让运行中的错误截图一直等到结束。改为每个run下多个不可变batch：错误批次可立即封口，最终批次另行封口。NAS按batch分析，按run汇总。

```text
待分析/日志/okww-custom/YYYY-MM-DD/run_id/batch_id/
  run.log 或 context.log
  events.jsonl
  metadata.json
  manifest.json
  各文件.sha256
  _UPLOAD_COMPLETE
待分析/截图/okww-custom/YYYY-MM-DD/run_id/batch_id/
  event-001.png
  event-001.png.sha256
```

manifest引用日志与截图目录内的相对路径及哈希。完成标记只在所有引用文件和校验文件落地后写入日志批次目录。NAS不能仅凭截图文件存在就读取；batch_id以单调序号加随机后缀生成，重试不更换ID。

### 3.3 状态和“成功”含义

进程正常退出不代表所有账号成功。metadata分别保存：process_status（running/exited/crashed/interrupted）、exit_code、task_summary（成功/失败/停止数）、batch_kind（error/screenshot/final）。上传状态是另一个维度，不能与业务成功混用。

### 3.4 图片脱敏不是文本替换

首版优先上传游戏窗口帧，禁止默认全屏回退，避免把其他应用、登录口令等带入包。已知游戏画面应用固定身份遮盖区；未知窗口、登录界面或无法确认隐私遮盖时只保留本地并标记needs_review。需要分享时用户可选择审核后的副本。

全屏回退作为显式可选功能，初始关闭。该项是对原规格的明确收紧，不宣称自动遮盖能识别全部隐私。

### 3.5 重试保留与删除

采用5秒、15秒、60秒、5分钟、之后15分钟的退避；24小时后停止自动重试并标记expired_pending，而非直接删除未上传原件。建议本地总容量上限2GiB；优先清理确认已交付且超过7天的副本。未交付材料达到容量上限时暂停新增普通截图、发出明确提示，错误日志保持受控滚动；不得悄悄删除未上传证据。

NAS读取端优先写“已处理”标记/报告，保留输入不可变；只有具备相应删除权限且明确选择归档移动方式时才移动原件，避免与最小权限规则冲突。

## 4. A0：核验 B7 领奖失败

**读取文件：** 当前src/task/BaseWWTask.py、DomainTask.py、TacetTask.py、对应B7日志/截图和运行副本。证据存本机test_out，脱敏测试图另放tests/images。

- [ ] 获取B7诊断ZIP并校验清单；确认版本和真实执行入口。
- [ ] 对齐领取前、点击单/双倍、结算弹窗、确认超时和后续处理，区分OCR实测与计算值。
- [ ] 用现有图像测试入口回放成功结算帧，读取右下角“剩余120”的位置、文字和语义；核对它是当前体力、总余额还是其他数值。
- [ ] 验证top区域OCR确实因结算界面不可用；同时核对是否允许备用、领取前余额和成本。
- [ ] 输出最小原因记录：确切行号、时间、失败帧和可识别结果；无证据时不先改阈值或固定等待。

交付标准：能用一张或一组真实图像复现旧_confirm_stamina_used误拒绝，且明确正确结果应是什么。

## 5. A1：修复领奖确认，不重复消费

**Modify:** src/task/BaseWWTask.py、src/task/DomainTask.py、src/task/TacetTask.py。
**Tests:** tests/TestStaminaAccounting.py、tests/TestDomainRecoveryLoop.py、tests/TestTacet.py及B7图像回放。

建议接口（实现时与实际奖励界面证据匹配）：

```python
@dataclass(frozen=True)
class ClaimObservation:
    state: str  # confirmed / pending / unknown
    current: int | None
    backup: int | None
    source: str  # reward_screen / top_bar / world_book
```

- [ ] 先加入失败回归：结算界面确认已消费、顶部读不到余额时，不能断言未消费，更不能再次点击领取。
- [ ] 实现reward_screen优先的只读观察；只有匹配到正确结算状态时才使用该区域读数，禁止随意OCR一个数字当余额。
- [ ] 若结算帧证据足够，确认一次消费，保持原地“再次挑战”能力；不要默认每局退出副本。
- [ ] 若图像只证明结算出现但余额仍不足以核对，使用受控退回世界再开F2核验作为末级方案。领域需要显式返回“已退出、需重进”的状态，不能让调用方继续点击副本内坐标。
- [ ] 读数未知时使用ClaimVerificationPending一类独立异常/结果，明确“已投递领取，消费未确认”。恢复不能再次发领取输入；保留before、requested_cost与观测记录，供人工或后续只读核对。
- [ ] 不盲目把8秒改成30秒。先保证读取正确界面；剩余等待预算覆盖确有必要的动画/跳转，停止可立即中断。
- [ ] 核对备用体力消费：只有当前余额时不得假设备用未变化；保持日常must_use上限，不把未知值记作0。
- [ ] 通过Domain/Tacet两条调用链测试：成功只记一次、失败不重领、退出副本时正确返回/重进、用户停止原样传播。

测试契约示例：

```python
assert observe_reward(b7_success_frame).state == 'confirmed'
assert claim_click_count == 1
assert recorded_cost == expected_cost
# 顶部区域不可读不应触发再次领取。
```

发布门槛：B7真实结算帧回放与原A4两帧回归同时通过。该修复单独形成版本，不等待NAS部署。

## 6. B0：盘点目标设备现有链路

**输出：** docs/reviews/NAS诊断链路盘点.md（不含凭据）。

- [ ] 在目标笔记本确认实际UNC目录与ai-upload权限：先只读枚举，获准部署时才创建唯一临时文件做写入/重命名验证。
- [ ] 读取nas_log_sync.ps1、一键上传脚本及“okww日志自动同步NAS”任务定义，记录解释器、账户、权限、触发器、工作目录、状态文件和目标路径。
- [ ] 检查是否存在明文凭据、net use清理、路径拼接、源文件仍写入时直接复制、只看文件名判重等问题。不在输出中显示密码。
- [ ] 记录Windows凭据管理器是否已有该共享的会话可用性；不导出凭据，不使用net use * /delete。
- [ ] 形成保留/替换清单及旧任务恢复步骤。NAS若仍拒绝写入，停在本地模拟验收，明确外部权限阻塞。

## 7. B1：本地诊断与不可变批次

**Create:** src/runtime/diagnostic_session.py。
**Tests:** tests/TestDiagnosticSession.py。

接口：

```python
start_session(root, version) -> DiagnosticSession
session.record_event(kind, data) -> None
session.add_screenshot(path, event_id) -> None
session.seal_batch(kind) -> str
session.finish(process_status, exit_code) -> None
```

- [ ] 创建%LOCALAPPDATA%/okww-custom/diagnostics/run_id，保存run.log、events.jsonl、metadata.json、screenshots和upload-status.json。
- [ ] run_id同时含时间与随机成分，不用账号真实ID命名；事件含墙钟、单调时间、序号和任务代号。
- [ ] 文件写入采用UTF-8，状态JSON以同目录临时文件替换；异常文本先用现有redact_message/redact_data处理。
- [ ] 最终日志采用本次会话专用日志handler，保留框架原日志；不把跨多次启动的全量历史日志误作本run。
- [ ] seal_batch在本地生成快照，不直接上传仍在写入的run.log。记录文件清单、原始事件范围和不可变batch_id；重复seal同一事件不生成无界副本。
- [ ] 错误批次保留故障前后有限上下文；最终批次包含全运行日志。长日志按固定上限分片，不能静默截断后声称完整。
- [ ] 下次启动识别上次未finish的运行，标记interrupted，补交已有内容；不伪造上次正常结束。

验收：并发写日志时封口内容一致、run唯一、JSON损坏可隔离、突然退出后队列可恢复。

## 8. B2：文本与图片导出策略

**Create:** src/runtime/diagnostic_export.py。
**Reuse:** src/observability.py、src/diagnose.py现有脱敏能力。
**Tests:** tests/TestDiagnosticExport.py。

接口：`prepare_batch(session, batch_id, image_policy) -> PreparedBatch`。PreparedBatch包含不可变文件列表、相对路径和SHA256。

- [ ] 类型白名单.log/.txt/.json/.jsonl/.png/.jpg；逐行解析JSONL。无效编码/解析失败标记blocked，不回退上传原始字节。
- [ ] 对Authorization、Cookie、Session、访问令牌、密码、私钥、手机号、身份证与注册账号身份做结构化+文本脱敏，文件名和错误状态同样检查。
- [ ] 拒绝链接/junction、根目录外文件和路径穿越；单文件建议64MiB，PNG建议20MiB，整批256MiB，大日志分片。
- [ ] 上传目标目录名用程序名、日期、run_id、batch_id；不使用OCR原始账号名。
- [ ] 图片只导出经配置策略处理的副本；未知界面进入needs_review，事件仍可上传且明确注明图片缺失原因。
- [ ] 现有export_diagnostic_archive行为保持不变，避免普通分享出口意外带出原始截图。
- [ ] 测试材料使用合成密码/令牌；私钥多行、混合JSON、文件名身份及未知图片均不得绕过检查。

## 9. B3：上传器与持久重试

**Create:** src/runtime/diagnostic_uploader.py、scripts/upload_diagnostics.py。
**Tests:** tests/TestDiagnosticUploader.py、tests/TestDiagnosticUploadProcess.py。

接口：

```python
enqueue(batch_id, priority) -> None
upload_one(batch_id) -> UploadResult
retry_pending(now) -> None
flush(timeout) -> None
write_status(batch_id, state) -> None
```

- [ ] 队列状态落盘：pending/uploading/retrying/uploaded/blocked/expired_pending；包含attempts、next_retry与脱敏last_error。
- [ ] 优先级错误批次>关键事件>最终日志>普通截图；同batch幂等，已成功文件哈希相同时不重传。
- [ ] 每次传输仅操作允许NAS根路径下的batch，使用唯一.uploading临时名；内容写完关闭句柄后改正式名，再写sha256，最后写manifest及_UPLOAD_COMPLETE。
- [ ] 完成标记内容包含manifest哈希，NAS校验标记、清单和全部文件；不因某个文件存在就判全批成功。
- [ ] SMB调用可能长时间阻塞：上传在独立工作进程中执行并设总截止时间，主程序只有限等待。超时只终止自己创建且持有句柄的上传子进程，不杀游戏、NAS或用户其他进程。
- [ ] 中断留下.uploading不对读端可见；重试仅处理本批自己的临时文件，不递归删除NAS目录，不覆盖不同哈希的已完成批次。
- [ ] 计划任务与客户端使用本地进程锁；崩溃后锁可恢复，不能仅凭遗留文件永久认定有人上传。
- [ ] 重试按第3.5节执行；重启电脑/程序后读取原队列，不重置尝试次数或生成新run冒充补传。

关键测试：

```python
assert not completed_marker.exists()  # 任一文件失败时
assert status.batch_id == original_batch_id  # 重试不变
assert source_bytes == source_before  # 原始证据不被脱敏流程覆盖
```

使用临时目录模拟SMB断写、rename失败、文件冲突、hash错误和子进程卡住。真实断网测试通过适配器故障注入完成第一轮，不擅自关闭用户网卡。

## 10. B4：接入程序生命周期与错误事件

**Modify:** main.py、config.py；在核对框架后对custom_ok/ok/task/TaskExecutor.py或现有项目任务事件入口做最小接入；截图保存接口选择现有框架保存回调，必要时新增custom_ok覆盖并登记包清单。
**Tests:** tests/TestDiagnosticLifecycle.py、tests/TestMainWindowStartup.py、tests/TestLoggingRedaction.py。

- [ ] 单实例通过后尽早建立本次诊断会话；初始化失败也有本地启动错误记录。
- [ ] 注册handler时链式调用已有sys.excepthook/threading.excepthook，不吞原错误、不递归记录上传器自己的错误。
- [ ] 未捕获异常处理器只记录本地错误、复用最近游戏帧并投递批次，不在崩溃线程执行SMB、OCR或Qt控件操作。
- [ ] 任务失败往往被TaskExecutor捕获，未必到达excepthook；单独接入任务失败事件，标记task_failed，不误把进程写为crashed。
- [ ] 普通异常与致命Qt/C++访问冲突分开：Python钩子不能保证处理native crash。后者依靠已有落盘资料、可选外部监测/系统崩溃报告补交；不能承诺强杀后还能当场截图。
- [ ] 截图在本地保存成功后通知导出模块；不在截图编码/GUI线程等待上传。
- [ ] 正常结束刷新本会话日志、封口final批次，最多等待例如2秒后交给独立上传器。退出时序排在已有_exit_cleanup之前，不误杀仍负责补传的独立进程。
- [ ] 不关闭全局日志系统来等待NAS；仅移除本会话handler，关闭本会话文件。
- [ ] 用户状态显示仅包含队列数、最后成功、阻塞原因和手动重试入口；不暴露账户凭据，不把网络失败表现为游戏任务失败。

验收：合成未捕获异常在5秒内产生本地错误资料（截图可得时包含截图；不可得明确记录原因）；网络不可达时主程序仍可运行和退出。5秒要求针对本地落盘，不能承诺SMB不可达时5秒送达NAS。

## 11. B5：NAS读取器与分析交接

**Create:** scripts/validate_diagnostic_batch.py、docs/NAS诊断部署与读取说明.md。
**Tests:** tests/TestDiagnosticBatchReader.py。

- [ ] 只扫描待分析，忽略.uploading，无完成标记不读取。
- [ ] 验证manifest与每个sha256，限制大小和路径、禁止符号链接越界；稳定性重复检查作为附加保护，不替代完成标记。
- [ ] 日志与截图通过run_id/batch_id/event_id关联，使用日志的时区与墙钟；不能仅靠文件最后修改时间强行配对。
- [ ] 按程序和运行构建时间线；将ERROR/WARNING作为检索入口，不自动把任一错误当根因。
- [ ] 分析报告包含现象、关键证据、截图观察、置信度、只读验证、修复建议及风险。引用事件/帧编号，不复制原始身份。
- [ ] 本地模型优先；云端仅接收已脱敏文本及经过审核的图片，不把文件内容当作可执行指令。分析器没有系统修复权限。
- [ ] 已处理状态写到已处理/日期/run_id/batch_id，记录manifest哈希和报告路径；失败写错误目录，不反复处理相同批次。
- [ ] NAS文件夹权限与模型/OpenClaw接入由目标设备按部署说明完成；本仓库工具不假装已经在NAS上线。

## 12. C：集成、版本与部署验收

新增测试文件先登记run_tests.ps1分组：持久化/脱敏/上传为unit/integration；生命周期为integration/ui；真实图片为image。

每批验证顺序：

```powershell
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestStaminaAccounting.py
.\run_tests.ps1 -Group all
.\.venv\Scripts\python.exe -m pip check
```

A批建议按实际体量选下一补丁版本；B批涉及生命周期与新模块，应独立中等版本。实施时重新核对config.py和远端标签，不在计划中占用可能冲突的版本。

- [ ] 版本号遵守固定宽度X.YY.ZZ；同步config、更新日志、程序结构、操作说明。
- [ ] 队列原件、凭据、运行目录、原始NAS日志不进入Git或发布包。
- [ ] 新模块与必要custom_ok覆盖纳入受控源码包，验证从上一正式版本覆盖后配置保留。
- [ ] 全量通过后提交、注解标签、推送并核对CI；安装器与真实NAS部署单独报告。
- [ ] 部署计划任务前备份旧任务定义/脚本；以同一专用账户测试读写/重命名，不授予NAS系统管理员权限。
- [ ] 正常退出、运行中错误、任务被捕获的失败、关键截图、断网补传、进程被终止、重启后补传、哈希不符、脱敏失败逐项实测。
- [ ] 检查原始材料未丢失、重复事件未生成无界批次、NAS没有误读半包、客户端错误不会杀进程或卡住退出。

## 13. 回滚

A批：保留上一发布版本和合成/真实回归材料；若确认界面仍不兼容，停止该任务并保留消费证据，不能自动重跑可能已消费的奖励。

B批：关闭新增诊断上传开关，队列保留本地；恢复已备份的旧计划任务定义。回滚不删除NAS已上传材料或未交付队列。协议记录schema_version，旧版本遇新结构拒绝处理并提示，不误解析后覆盖数据。

## 14. 完成交付清单

1. B7定位及修复报告、实际帧回归、版本与测试结果。
2. NAS盘点与迁移清单、无凭据的配置示例。
3. 本地诊断/导出/上传模块，独立上传入口与计划任务部署说明。
4. 批次协议、NAS验证读取工具、脱敏与失败处理说明。
5. 断网/中断/重启/隐私/幂等验收结果。
6. 发布提交和标签、源码包哈希、CI状态及尚未完成的实机项目。

## 15. 当前计划状态

### 2026-09-07 执行更新（1.36.00）

- B1/B2/B3/B4：已实现本地会话、文本脱敏、图片待审核、不可变批次、持久重试、异常/退出/截图接入和通用设置状态入口。测试合并为 TestDiagnosticPipeline.py，已登记 integration 分组。
- B5：已实现校验和证据索引读取器，位于 src/runtime，确保随源码更新包交付；不自动调用模型或宣称根因分析完成。
- 系统计划任务安装/卸载脚本位于 src/runtime/install_diagnostic_task.ps1，随 src 打包；未在实际目标设备执行。上传默认关闭。
- A0/A1 仍等待 B7 原包；B0 本机探测返回 Windows 1326，未找到历史同步脚本/任务。没有修改登录凭据、NAS 服务或游戏领奖逻辑。
- 明确实现边界：图片须人工审核后显式导出；原始资料不自动清理，达到容量限制需人工归档；没有完整自动图像脱敏、NAS 模型部署或无人登录时的补传。
- 全量 86 个测试文件通过；15 项诊断专项通过；pip check 通过。真实 NAS、计划任务跨重启、游戏截图、B7 仍待目标设备验收。
- 部署和操作以 docs/NAS诊断部署与读取说明.md 为准；上文复选框保留原始计划，不表示所有实机验收已完成。

以下为编写计划时的历史状态：

已完成：两份文档阅读、当前入口/导出/领奖代码盘点、本计划。
未执行：B7原包核验、代码修改、NAS访问/写入、现有任务变更、游戏复测、发布。
下一步：先取得B7诊断包及另一台设备的同步脚本/任务定义；无NAS访问也可先完成B1/B2和B3模拟测试。
