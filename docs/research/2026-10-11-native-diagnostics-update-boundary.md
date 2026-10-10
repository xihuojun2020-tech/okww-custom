# 原生诊断与 gamepack 更新的下一版本迁移边界

诊断可继续使用现有 DiagnosticSession、EvidenceWindow、FileCollector、封存队列和归档上传业务，原生入口需要接入这些服务并显式绑定用户 data_dir。更新不能直接调用旧 LanUpdate 安装器替换 native gamepack：旧安装器处理旧应用的 update-manifest.json，gamepack 使用 manifest.json/files.json 和单一包目录，且现有安装函数拒绝替换已有包。

这是 v66 发布前的下一批只读方案研究。当前 v66 的账号/序列/完成证据管理入口不代表诊断上传或原生更新已迁移。本轮仅阅读源码和既有测试，不运行诊断生命周期、上传、共享探测、系统计划任务、安装器、游戏或真实捕获；下述验证均为下一版本实施建议，不能记为本轮测试通过。

## 诊断：现有调用链

1. 旧 main.py 在账号预检及 OK 构造前调用 start_diagnostics(version)。diagnostic_lifecycle 创建 DiagnosticSession(root, version, source_root=REPO)，将 session 安装为 root logging.Handler，并接管进程/线程异常通知。start_diagnostics 同时启动 ensure_task、旧日期 automatic_upload 和 maintenance_loop；不能把这个入口视为单纯的本地日志初始化。
2. 日志 ERROR 经 DiagnosticSession.emit → record_event(error_log) → record_error 的有界 triggers 队列 → request_batch。异常经 record_crash 保存 crash.json 并进入同一事件/incident 队列。record_combat_anomaly 也复用此链。
3. attach_framework_hooks 从 ok.og.executor 读 _frame/_diagnostic_frame，并包裹 Screenshot.save_pil_image → session.add_screenshot。采样在诊断本地线程进行，EvidenceWindow.sample 使用帧时间戳识别过期画面，保留报错前/当时/报错后的有界窗口；没有画面时记录缺帧而不伪造成功。
4. DiagnosticSession._work 定期采样、复制精确截图文件、FileCollector.collect 新增日志/截图，然后 seal_pending/seal_run。封存过程使用 sanitize_file、manifest 与 _READY，diagnostic_queue 维护 pending/ack 状态，失败资料留在本地。
5. diagnostic_archive.build_archive 将已封存资料打包，支持 session.flush_for_archive 而不中止活动会话。manual_upload 打包今天；automatic_upload 选择今天之前的 pending_days。send_archive → 独立子进程 diagnostic_archive --upload → upload_archive → connect(DEFAULT_TARGET)，写入 NAS 待分析/压缩包，完成后才确认相应批次。
6. 当前 archive 上传以本地流式摘要、长度与上传回执处理断点续传，不读回 NAS 内容校验。旧逐批 diagnostic_uploader 链还有 validate_remote/_COMPLETE 语义；迁移应保留正在使用的压缩包业务，不能把这两条不同传输路径拼成一个未经验证的新协议。
7. cleanup_local 保留活动/未上传资料；已上传本地证据满一天清理。NAS 未审阅包30天，实际审阅并登记报告后3天清理证据、保留报告；mark_reviewed 保留 ZIP 和报告摘要合同。维护线程还会启动远程清理子进程，因此本地读状态和远程维护必须在入口层区分。

settings(root) 当前强制 upload_mode=manual_archive，wake_uploader 因而不启动旧逐批 uploader。这个模式并没有禁止 start_diagnostics 另外启动的旧日期 automatic_upload；已有 TestDiagnosticArchive.test_pending_days_and_daily_archive_exclude_today 反映这一区别。迁移不能仅根据 manual 字段推断整个启动流程无网络。

## 诊断：原生已具备与缺少的接点

| 接点 | 实际状态 | 最小替换点 |
|---|---|---|
| 日志 | native_logging.configure_logging 已向 data_dir/logs/ok-native.log 写入；生产 logger 和视觉 logger 走 root | 初始化现有 session 后挂到同一个 root logger，不创建第二套 native 日志队列 |
| 帧 | NativeCombatExecutor 更新 _diagnostic_frame=(frame, wall_time, monotonic_time) | 提供读该缓存的 native sample_provider；诊断线程不调用设备 capture、task.frame、reset_scene 或发送输入 |
| 截图 | Host/NativeTask 已调用 save_native_screenshot，PNG 位于 data_dir/okww监控室，身份区域遮罩 | 在成功保存后的原生诊断接点调用 session.add_screenshot(确切文件)，沿用有界队列。保存失败不发 screenshot_saved |
| 账号事件 | LoginFlowService 调用生产 transition/evidence 方法；MultiAccountDailyTask 最终写 AccountSwitchEvidenceSession 的故障事件目录，普通日志仍存在 | 在既有结束事件接点记录脱敏结构化状态/证据引用；复用原失败截图，不建立第二个账号切换记录器、不记录完整手机号或凭据 |
| 战斗故障 | Host 恢复钩子记录日志/诊断截图，战斗 anomaly 已有 lifecycle.record_combat_anomaly 接口 | 包内明确绑定同一 session；session 初始化/记录/封存失败只能报告诊断不可用，不能关闭自动战斗或覆盖业务异常 |
| 生命周期 | native plugin.run/run_session 未调用 start_diagnostics/finish_diagnostics，旧 attach_framework_hooks 依赖 ok/Qt | 在游戏包 worker 的真实启动/finally 边界接入现有服务；worker/session只拥有一个日志 handler 和 session，退出统一 finish，不把 Qt hooks 带入原生进程 |

### 根目录与进程硬编码

| 文件/函数 | 当前绑定 | 原生差异 |
|---|---|---|
| diagnostic_policy.REPO | src 所在根；有 source.json 时改为 source_repo | 安装的 payload 是只读代码根，不能兼作用户资料根；参数/后台 source binding 必须指向 data_dir |
| diagnostic_policy.installation_id、DiagnosticSession.metadata | installation_id 默认参数在导入时绑定 REPO；session直接调用无参 installation_id | 更新包或移动代码根不应产生新用户安装身份；以显式 data root 保持身份和历史连续性 |
| diagnostic_session.default_root | LOCALAPPDATA/okww-custom/diagnostics/POLICY/installation_id，并用默认REPO读取runtime_storage | 使用 storage_path('diagnostics', data_dir/okww监控室/diagnostics, repo=data_dir)，保留已有存储迁移gate及盘不可用失败合同；已有明确存储设置优先 |
| FileCollector.files/acknowledge | 只认识 source/logs 与 source/screenshots，以及 screenshots 的 storage_path | 原生日志可将source设为data_dir；原生截图应走确切文件hook。不要递归收集整个 okww监控室，否则完成证据/材料收据也会进入上传 |
| collect_after_exit | 在 source/config.py 用regex读取version | native data root 没有config.py；把版本作为明确元数据传入或读取已绑定运行记录，不能默认为假版本 |
| diagnostic_runtime.prepare_runtime | code_repo提供诊断模块；source_repo决定外部工作绑定；background_home在source盘根/OKWW-Background | 两个参数已有职责，可直接以payload作为code_repo、data_dir作为source_repo；后台不可变runtime留在更新目标外。自检需保持脱离源代码目录 |
| send_archive、bounded_upload/probe、verify_archive、maintenance_loop | 子进程cwd固定src所在根，常用 -E -s -m | payload载荷可用，但若payload被替换，后台导入会失效；归档/上传/维护应使用已有不可变runtime命令，不继承被更新的旧payload路径 |
| ensure_task/stop_legacy_uploaders | 工作目录、task_name、SourceRepo与REPO/installation_id绑定；manual模式还会禁用旧任务 | 普通独立管理开窗不应隐式碰计划任务；真正生产生命周期要按明确data root判断既有任务所有权，保留旧别名迁移，不终止其他安装的上传进程 |
| DiagnosticStatusCard/DiagnosticDetails | 卡片构造default_root，测试错误截图依赖同进程lifecycle._session | 给状态/归档卡片明确root；独立管理进程只能查看worker诊断结果。它没有worker的画面/事件队列，实时错误截图测试需走已拥有输入的worker边界，不能在管理页创建设备 |

原生接入不需要新框架：最小实现是在现有 lifecycle 增加明确的 source_root、诊断root、版本与frame provider输入，将老 Qt hook 留给旧应用。包内Host与截图/账号结束接点调用现有session方法；现有EvidenceWindow、封存、归档、回执、上传和保留策略继续工作。

原生 _diagnostic_frame 当前为原始画面。EvidenceWindow.sample 复制、缩小并编码，但没有身份遮罩；sanitize_file 处理图片元数据，不能代替像素遮罩。原生 provider 必须对诊断副本应用已经确定的身份区域遮罩，不能修改 task 原帧，也不能改变完成证据、材料收据或监控视频的原始像素合同。不得以“图片已过 sanitize”宣称身份已遮罩。

## 更新：现有调用链与 gamepack 合同差异

旧 LanUpdateCard._check → LanUpdateService.check → FileShareClient/HttpsPinnedClient → LanRelease 解析与固定宽度版本比较。_download 则以 src 所在根为install_root，download 写 root/configs/update-staging/vVERSION，validate_package要求根 update-manifest.json，create_apply_request从根config.py导入当前version，并写旧应用安装请求。

旧 MainWindow.schedule_lan_update 使用 worker_command 携带当前import paths启动 lan_apply，等待 ready.json；只有 helper预检通过后才暂停executor并正常退出。lan_apply等待父进程退出、检查依赖、备份受影响文件、逐个replace并写journal，故障回滚，最后写update-result并重启 main.py命令。旧configs被明确排除在替换目标外。

现有native ZIP包含单包目录、manifest.json、files.json、plugin、requirements与payload/src/assets；install_archive先解包并校验files.json、PackageManifest，再rename到包目录。已有包存在时抛FileExistsError；它是首次安装接口，不能承担更新。core StateStore和包用户data_dir也不是旧应用install_root/configs布局。

| 必须分开的合同 | 旧实现 | 下一版本最小处理 |
|---|---|---|
| 版本 | LanRelease固定X.YY.ZZ；旧create_apply_request import config | 继续共用版本解析；当前版本从PackageManifest显式传入，下载后manifest.id/version必须与所选包及release一致 |
| 更新源 | 默认 .173 的AI诊断/OKWW-Updates/stable/latest.json，严格okww_update_vVERSION.zip路径 | 给native包单独发布命名空间，仍使用相同LanRelease格式和传输类；避免native客户端把旧应用ZIP当gamepack，或旧客户端读到nativeZIP |
| 完整性 | 旧包外层sha/size+update-manifest哈希；gamepack是files.json | 下载继续用现有transport的外层sha/size核验；包结构和内部index采用现有core gamepack验收合同，不用旧validate_package强行读取不存在的update-manifest |
| 依赖 | 旧lan_apply检查requirements.txt/.in及ok-script框架版本 | 原生worker lock与可选management lock分别比较实际依赖；只换代码时保留既有环境，真实依赖变更明确报告需要完整环境升级，不能无声pip install或沿用不兼容runtime |
| 替换 | 首次install_archive拒绝existing；旧lan_apply逐文件改src/custom_ok | core增加专用于已安装包的事务替换入口，复用现有解包/index验收。包目录整体准备与替换，失败恢复旧包；无需AGPL诊断/账号逻辑进入MIT核心 |
| 用户数据 | 旧安装器只保护旧root/configs | 替换目标只限installed package目录；data_dir、StateStore、账号master/工作副本、备份、证据和诊断runtime均在包目录之外且不变 |
| 活动进程 | 旧helper等旧app单一parent | launcher持有native worker与management；二者结束后方可换包。停止须保留enabled意图和输入释放，不能仅关闭管理窗口就替换仍运行的worker |
| 重启 | 原卡片构造main.py命令，helper cwd旧root | 使用已配置的launcher/管理入口重开方式，保留原data_dir与新manifest版本；同进程包缓存必须重新发现，不能继续执行旧已import插件 |
| 中断恢复 | 旧journal回滚在except执行；core首次install staging是临时目录 | 新包目录交换有实际多步rename中断边界，需持久化旧/新/backup阶段并在下次启动恢复。验证只要求这些真实阶段，不引入通用更新框架 |

建议把网络/发布源留在AGPL包内，MIT核心只提供通用已验证gamepack替换、当前owner空闲检查和完成通知。下载、版本判断、NAS凭据与原LanUpdate UI可以继续复用；旧lan_apply不能直接作为native更新器，因为它的包格式、依赖判断、路径和重启对象均不同。其ready-before-exit、事务记录、回滚和故障结果可以作为原生替换的合同参照。

普通Manage开窗不执行更新检查或网络访问。更新由用户明确检查/下载/应用控件触发，先形成已验证、可复核的待更新包，再交launcher管理owned进程退出及替换；更新资料和结果记录写data_dir。原LanUpdateCard初始化/_download只需替换明确service/root/version/重开对象接点，不复制整套GUI或把main.py加入native载荷作兜底。

## 下一版本离线验证建议

诊断先验证真实原生Host/Replay链：日志ERROR与脱敏账号失败事件进入原DiagnosticSession；provider只读取已有缓存，监视设备capture调用次数证明诊断不增加捕获或输入；预/当时/后窗口保留原时间戳，旧帧如实缺失，诊断副本身份区域遮罩且原帧不变。成功PNG通过精确保存hook进入既有batch/本地ZIP，不能收集旁边CompletionEvidence或材料原图。模拟采样/磁盘/诊断初始化失败，任务原异常和AutoCombat enabled意图均保持。finish及中断恢复沿用现有测试的lease/_READY/回执行为。

上传、共享探测、凭据和计划任务全部用明确spy或临时本地transport；assert没有真实UNC访问、Popen网络worker或PowerShell计划任务。下一版本可在临时目录对原build_archive运行离线真实ZIP验收，检查batch/incident依赖与脱敏数据；不调用manual_upload/automatic_upload等真实外部边界。原有TestDiagnosticPipeline、Evidence、Archive、ArchiveRetention可选取改变边界的相关用例，先检查各用例是否mock外部调用，不运行名称含upload的用例来替代边界判断。

更新使用两个实际build_native_gamepack产物和临时installed/data目录，FakeTransport返回下载文件；真实解包与内部index验收后执行包替换。坏外层摘要、坏files.json、错误包ID/版本、真实依赖差异、父进程仍存活应在替换前拒绝。fault_hook分别模拟旧包rename后、新包rename前及结果写入前失败，检查旧包可运行与下一次恢复；对data_dir全文件快照和StateStore enabled做前后比较。重开命令只spy，绝不启动游戏或真实launcher。原TestLanUpdateApply中bad_archive/live_parent_timeout/dependency_change/failure_rolls_back及原gamepack install checks提供现成合同。

最后必须再次以实际installed ZIP单独进程验收管理卡片、归档命令和新更新入口，硬阻根config/main/custom_ok；诊断原生worker同时硬阻ok/PySide6/qfluentwidgets。仅在这两层都通过后才能声明原生诊断与更新完成；源目录成功不能替代安装载荷验收。

## 推荐分工

- 诊断服务负责人：AGPL src/runtime/diagnostic_* 的显式root/version/provider接点，以及Host/日志/截图/账号事件绑定、遮罩和原归档链；不改core installer或新增诊断队列。
- 更新核心负责人：MIT gameframe/packages/controller/launcher 的通用包替换事务、owner退出、恢复与重新发现；不导入AGPL src/update、账号服务、Qt管理控件或NAS实现。
- 包管理与更新业务负责人：AGPL src/update、ManagementWindow及原DiagnosticStatusCard/LanUpdateCard的service/root注入、native发布命名空间、transport复用、依赖lock与独立进程请求；不修改战斗输入或账号选择算法。
- 主代理汇总版本与发布：明确这是v66之后的独立版本，协调包生产格式、root命名和IPC字段后执行最终安装ZIP验收，保留v66已验证结论，不提前写成完成。
