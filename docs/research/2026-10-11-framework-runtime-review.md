# 框架迁移第二轮：运行基础、更新与材料逐文件审查

审查日期2026-10-11。迁移前基线1.97.61 / HEAD `4c0a4ad853d98bdc4474d3b6f43dc9c5ae03fcca`。本轮确认并修复一个存储迁移交接缺陷：成功提交当前schema 3后，交接代码仍按schema 2判断，错误恢复旧计划任务。修复及离线回归通过；没有启动游戏、读取真实账号/运行配置、访问NAS或操作真实计划任务。

## 范围与方法

逐文件完整阅读全文：`src/runtime` 36个Python文件、2个PowerShell文件，`src/update` 8个Python文件、`src/materials` 6个Python文件，以及`src/observability.py`、`src/daily_timing.py`、`src/task_status.py`、`src/storage.py`、`src/recording_policy.py`，合计57个文件。材料仓库首次输出曾被截断，已重新完整读取；上传器头部同样已补读。

阅读重点是生产调用路径的输入边界、文件和数据库事务、线程/进程归属、停止控制流、错误传播以及证据持久化。文件表记录实际人工语义阅读范围，不把AST解析或文件列表当作完整语义审查。完整阅读也不意味着每种外部输入、故障组合或并发交错已被实测。

账号根模块、GUI、任务/战斗实现与gameframe由其他审查负责人处理。本轮只阅读runtime中的账号服务边界，未修改这些服务或其任务调用者。新修复仅涉及`src/runtime/storage_handoff.py`，回归位于`tests/TestRuntimeReview.py`；版本与统一发布由主代理处理。

## R2-01：成功迁移恢复旧诊断计划任务（P2）

定位：`storage_handoff.quiesce_uploaders`的`finally`。`storage_bootstrap.SCHEMA`已经是3，`migrate`提交的`runtime_storage.json`也写3，交接判断却仍为`current.get('schema') != 2`。

真实生产链：启动迁移UI把`quiesce_uploaders`交给`bootstrap`，需要迁移时`migrate`在ExitStack中进入交接上下文；成功提交配置后退出上下文。上下文原逻辑看到schema 3，会执行PowerShell `Restore`，重新启用迁移前保存为Enabled的旧动作。该行为违反函数明确的提交契约：成功后保持旧动作禁用，由新启动路径接管；失败才恢复旧动作。不能据此宣称线上已经发生重复上传。

最小修复：导入现有`storage_bootstrap.SCHEMA`，替换判断中的字面量2。不新增配置、重试、进程终止或保护分支。root不匹配以及schema不匹配仍触发现有恢复路径。正常应用退出时诊断helper独立存活的行为不受此修改影响；本函数的停止行为仅属于存储迁移交接。

离线根因复现：从Git HEAD读取原文件并在子Python进程中编译运行，用临时目录写入生产当前SCHEMA，mock全部`subprocess.run`与`psutil.process_iter`。成功用例实际命令顺序是`Pause → Restore`，因此原版2项检查中1项按预期失败；失败迁移的恢复检查通过。测试没有实际调用PowerShell、枚举进程或触碰计划任务。

修复后：成功提交当前schema只调用`Pause`；复制失败调用`Pause → Restore`，原`OSError('copy failed')`继续向外传播。两个新增用例通过。既有复制、WAL快照、迁移中断恢复及schema 2证据布局升级的4个离线回归也通过，共6项。

## 逐文件覆盖记录

以下每行均表示完整源文件阅读。没有新确认缺陷的行仅说明本轮未找到有生产依据的修改点，不代表对所有部署环境作成功保证。

### runtime与PowerShell

| 文件 | 实际检查内容及结论 |
|---|---|
| `__init__.py` | 延迟导入映射、存储启动前不急切加载ok/config；与公开API对应。 |
| `account_runtime_bootstrap.py` | 单例锁、根目录一致性、出版事务恢复先于完整性检查、迁移失败后再检查及默认服务回收；账号业务交由对应负责人。 |
| `account_selection_service.py` | 显式profiles优先、仓库记录映射、可选/必需身份解析的错误语义；未读取实际profiles。 |
| `account_verification_service.py` | 目标canonical化、观察身份未知/不匹配明确失败；未修改生产切号路径。 |
| `login_flow_service.py` | 停止/捕获/完整性异常传播、证据结束、capture上下文清理、MouseReset恢复；依赖现有任务原语。 |
| `sequence_snapshot_service.py` | 对SequenceRepository的只转发边界，不另建快照算法。 |
| `task_run_coordinator.py` | 状态转换、停止意图、finish与fail保留错误；停止完成必须由执行循环清理后调用。 |
| `task_status_model.py` | 不可变状态数据模型，无磁盘或输入副作用。 |
| `game_runtime_errors.py` | 游戏进程丢失、帧不可用、启动状态变化的独立异常契约。 |
| `framework_overlay.py` | 首次ok导入前安装、同根幂等/不同根拒混、真实覆盖文件来源、未覆盖模块正常回落；第一轮13项回归已记录。 |
| `nas_location.py` | 当前173目标、旧地址仅迁移/凭证别名、自定义目标不误改；未执行网络操作。 |
| `diagnostic_storage.py` | 迁移gate/generation、活动磁盘不可用明确失败、安装盘路径限制、旧任务重定向。 |
| `diagnostic_export.py` | 脱敏递归、图片元数据处理、原子JSON、path traversal/链接拒绝、清单长度/大小/摘要验证。 |
| `diagnostic_session.py` | FileLease、append-only日志、批次_READY最后发布、偏移提交顺序、队列/worker、finish与恢复、诊断错误不影响被观察任务。 |
| `diagnostic_evidence.py` | 单worker帧环、窗口延续和上限、原始帧隔离、revision持久化与发布失败重试、不完整原因。 |
| `diagnostic_collector.py` | 首次历史边界、文件身份/前缀/截断、增量偏移、逐文件独立封存、坏文件隔离、退出后独立收集。 |
| `diagnostic_queue.py` | 持久pointer、有限协调扫描、游标轮转、完成批次ack、安全路径恢复。 |
| `diagnostic_uploader.py` | 子进程超时、逐文件暂存和续传、控制清单验证、完成标记最后发布、锁竞争、优先队列/重试状态及CLI分支。 |
| `diagnostic_runtime.py` | 外置不可变runtime、安装归属指纹、独立Python环境、Pillow/pywin32拷贝、自检与fresh stage清理；没有执行真实bundle构建。 |
| `diagnostic_lifecycle.py` | 应用钩子与网络子进程分离、manual_archive策略、启动与退出hook、daemon归属、frame采样边界；退出hook不终止上传helper。 |
| `diagnostic_policy.py` | mandatory manual_archive策略、173目标迁移、凭证不入JSON、1219目标服务器连接恢复、计划任务安装/禁用、旧worker归属检查。 |
| `diagnostic_archive.py` | 按日选封存批次、锁与partial ZIP提交、截图依赖、原文汇总、收据/ack时点、续传及失败保留。当前设计明确不在上传路径读回NAS内容，既有契约测试也要求这一点，本轮未擅改。 |
| `diagnostic_archive_retention.py` | 本地已上传一天后清理、未审30天/报告支持已审3天、报告/ZIP摘要、删除路径归属、legacy journal、维护子进程。 |
| `diagnostic_retention.py` | 旧逐文件传输保留策略、先撤完成标记再删除日志、保留图片/未上传、source stamp确认后才删源。 |
| `diagnostic_reader.py` | 完成批次验证、日志证据索引限额、分析状态与诊断结论区别、失败显式错误记录。 |
| `diagnostic_incidents.py` | verified batch重建事件视图、revision去重、帧摘要关联、日志到期裁剪与缺失帧标记。 |
| `diagnostic_status.py` | 缓存/脱离字典传给UI、坏状态不可读、来源区间、补传时间筛选、blocked不清除、受限核验目标；没有执行NAS核验。 |
| `diagnostic_performance.py` | 单线程低频采样、计数/p95、进程不可用明确标记而非伪造数值。 |
| `vision_metrics.py` | 热路径finally测量、仅已有诊断session、观察失败不改变控制流。 |
| `navigation_status.py` | 锁保护有限内存历史、成功/失败/停止观察、有限状态展示；没有增加导航重试。 |
| `ocr_backend.py` | 配置输入范围、OCR初始化前CPU重编译、保留现有后端作为有效恢复、实际后端日志；未启动模型。 |
| `ocr_reuse.py` | 同帧像素摘要与参数key、带副作用/OCR外帧绕过、深拷贝结果、短TTL与有界缓存。 |
| `post_message_drag.py` | 明确终点、有限非负时长、finally鼠标释放；输入设备未运行。 |
| `storage_bootstrap.py` | 本地路径/盘/链接边界、SQLite写锁与快照、copy/verify/commit、来源变化、历史冲突、schema 2→3、asset引用和原件保留。 |
| `storage_handoff.py` | 安装归属、计划任务暂停、仅owned worker停止、失败恢复/成功旧动作禁用；确认并修复R2-01。 |
| `storage_startup_ui.py` | migration线程、UI轮询、安全取消、结果错误传播、应用对象归属；未启动Qt。 |
| `storage_handoff.ps1` | 完全匹配Description与source binding的任务归属、保存状态、Pause/Restore只处理owned任务；仅阅读。 |
| `install_diagnostic_task.ps1` | 任务名归属校验、pythonw、Verify/Preview、限时、既有任务动作替换；仅阅读。 |

### update

| 文件 | 实际检查内容及结论 |
|---|---|
| `__init__.py` | 包标记，无运行副作用。 |
| `lan_manifest.py` | 外部JSON字段/固定宽版本/UTC发布时间/摘要/包路径及同源URL约束。 |
| `lan_service.py` | 默认173与旧源迁移、可用版本、验证下载缓存、生产apply-request来源和暂存目录。 |
| `lan_transport.py` | SMB专属子进程、响应/长度限制、HTTPS pin、下载partial、摘要、超时与明确失败。 |
| `package_validation.py` | 外层大小/摘要、case-insensitive重复成员、链接/特殊文件、configs隔离、清单成员集合/内层摘要。 |
| `dependency_compatibility.py` | 锁定框架与依赖语义比较、仅格式修复、备份与写失败回滚、独立CLI；未访问指定NAS路径。 |
| `lan_apply.py` | 等待父进程退出、安装依赖不变、staging路径、备份/journal、逐项替换和删除旧源码、异常回滚、rollback_incomplete禁止重启。 |
| `worker_process.py` | 子进程继承已初始化import paths、pywin32 bootstrap、失败信息脱敏。 |

### materials与附加根模块

| 文件 | 实际检查内容及结论 |
|---|---|
| `materials/__init__.py` | 包标记，无运行副作用。 |
| `materials/__main__.py` | accounts/stats/export/backup参数边界、显式输出与JSON数据序列化。 |
| `materials/model.py` | 非负整数量、完整结算证据契约、合成进位、周边界、同claim/revision与同group统计。 |
| `materials/catalog.py` | 材料组完整性、模板目录边界、识别阈值/差距、未知保持未知、缓存实例归属。 |
| `materials/repository.py` | SQLite事务、claim身份、immutable frame/parse去重、complete截图要求、快照选择、CSV不覆盖、DB和assets一致备份。 |
| `materials/vision.py` | normalized空间、结算/库存/目标场景确认、数量未知、跨页重叠歧义停止、目标变化/缺tier禁止花费、正面滚动边界证据。 |
| `observability.py` | 嵌套身份/凭证脱敏、日志record factory先于handler、异常栈、contextvar token还原、失败结果明确。 |
| `daily_timing.py` | 观察不参与调度、耗时owner避免嵌套重复、账号handoff时间、历史次数、停止/失败最终记录、错误不改变原任务。 |
| `task_status.py` | optional UI失败隔离、状态优先级、elapsed/完成数、work-area与游戏矩形位置选择。 |
| `storage.py` | 活动storage优先、旧仓库适配、backup路径避开configs、防止活动盘不可用时切空仓库。 |
| `recording_policy.py` | 当前录制页面常量，无线程或持久化行为。 |

## 核对后未修改的候选

- `DiagnosticSession._work`在`collector.collect`之前取sizes，表面可能遗漏退出收集的日志。完整读`FileCollector._collect_file`后确认，新日志自己调用`seal_run`且更新sealed-offsets，不依赖随后final的sizes；因此没有修改。
- `MaterialRepository.latest_complete_snapshot`按ISO字符串排序，跨offset输入可产生不同时间顺序。本轮核对生产调用没有传入自定义captured_at，统一使用`now_iso()`的GAME_ZONE；未发现任务当前路径跨offset输入，故未以假设扩展代码。它仍是公开API将来接入外部时间戳时应重新核对的边界。
- 材料备份先`BEGIN IMMEDIATE`冻结写入、另一连接backup，和存储迁移相同；没有把SQLite备份方案误判为重复连接问题。
- LAN apply请求由已验证`LanRelease`和当前version生成。没有仅凭理论恶意本地JSON扩大校验、引入更新崩溃恢复框架或未要求的兼容层。
- Catalog识别用前两模板的margin；本轮现有目录每个item只有一个模板，未把未来多模板的潜在识别差异当作当前缺陷修复。

## 验证记录与实际运行限制

执行：本地`.venv/Scripts/python.exe -B`。新增2项TestRuntimeReview通过；既有TestStorageBootstrap的`test_copy_originals_and_fast_second_start`、`test_wal_committed_rows_preserved`、`test_interruption_resumes_and_never_commits_early`、`test_upgrade_v2_keeps_old_files_and_rewrites_video_reference`通过；共6项。旧HEAD编译复现为2项中1项预期失败，确认旧版成功提交路径确实发出Restore。`git diff --check`通过（仅Git的LF/CRLF提示）。

这些测试全部使用tempdir/mock，验证Python交接逻辑、已有存储数据复制和事务，不验证真实计划任务注册、真实进程归属、磁盘掉线、SMB权限、HTTPS服务器、OCR模型、游戏输入或帧采集。未运行完整历史测试集。既有第一轮overlay/执行器/YOLO回归结果见第一轮报告，未在本轮重复运行。

本次新增代码没有增加保护分支，只用当前生产SCHEMA修正旧分支的判断依据。既有“未提交时Restore”属于已明确的数据迁移失败恢复契约；删除会使失败迁移永久保留旧任务禁用，不符合现有行为。
