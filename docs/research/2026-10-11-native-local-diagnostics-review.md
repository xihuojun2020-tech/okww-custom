# 2026-10-11 原生包本地诊断与管理入口验收

本轮接入原生 worker 的本地诊断，并把已有诊断控件接入独立管理进程。复用原 DiagnosticSession、EvidenceWindow、采集游标、封存队列与 build_archive；没有另建上传器、证据存储或截图框架。版本与发布由主任务统一处理。

## 修改与依据

- 原 start_diagnostics 即使使用手动上传策略，也会启动计划任务停用线程、历史自动上传和保留策略线程。新增明确 local_only 模式，原生 prepare 仅启动本地 handler、采样与会话；初始化、批次回调及退出均不唤起 uploader。旧入口默认行为保留。
- 会话根目录由 data_dir 的 runtime_storage 选择诊断目录；文件采集源与 installation_id 均明确绑定 data_dir。采集器只处理原有 logs/screenshots 来源，不遍历整个 okww监控室。
- Runtime.run_service 会在同一 worker 重新调用包入口。诊断在 prepare 建立一次，每个新 Host 更新缓存提供者，_run 返回或重试时不关闭会话，退出沿用已有 atexit。被运行框架捕获的失败在原包入口记录并重新抛出；取消只记录 stopped。
- 采样仅复制 executor._diagnostic_frame，保留墙钟与 monotonic 时间，应用原身份区域遮罩；不调用 frame、next_frame、reset_scene 或输入方法。原帧、完成证据和材料图片不改写。
- save_native_screenshot 成功写入后才通知会话。Host、适配后的任务、原生基类及直接调用共用这个唯一 hook；编码或写入失败仍抛出原错误。观察器故障报告到 stderr，不把已保存 PNG 或业务结果变为失败。本地截图事件明确标记 local_pending。
- LoginFlowService 的生产选择、匹配、验证、重试、退登、登录与证据结束路径保留；原分支只补 started/succeeded/failed/stopped 事件。字段为任务类、状态、阶段与异常类型，不传目标、账号标识、手机号、昵称、备用名、特征码或原异常文本。只有 failed 请求错误窗口；入口已停止时不开始证据或事件。
- 独立管理页明确注入诊断 root/source/version；打开和刷新仅读取本地状态，不启动诊断会话。管理窗口没有执行器，因此错误截图测试按钮禁用并说明原因。补传入队不唤起上传器；共享探测、凭据保存、上传与远端核验仍由用户按钮触发。
- 管理入口传递明确 package_root 和实际 MIT core 路径；仅带 files.json 的安装包显示可操作更新卡，源码包显示不能替换游戏包的说明。配置表单由独立原生配置子进程提供，管理主进程继续使用原 Qt/ok-script provider。
- 管理窗口等待账号、诊断及更新 BackgroundOperation 完成，再请求配置子进程退出。未确认退出时保留窗口并报告失败。首账号、导入或真实账号编辑后重新绑定配置 owner；普通刷新产生的 graph_refreshed 不触发重启。完成证据原有取消行为保留。

## 验证

执行仓库 .venv 的 unittest；合并定向运行 16 项通过：TestNativeDiagnostics 6 项、TestNativeScreenshots 2 项、TestAccountManagementEntry 7 项，以及旧诊断生命周期崩溃/重复退出用例 1 项。最后的 graph_refreshed 过滤改动再次通过完整 installed 管理探测。git diff --check 通过。

关键检查使用真实对象：

1. 临时 data_dir、真实原生 AutoCombat Host 与 Replay 帧，实际 DiagnosticSession 写入错误事件、incident、遮罩图、封存批次，并实际 build_archive 生成离线 ZIP。检查 ZIP 有 PNG 和日志、合成 secret 已移除。
2. 缓存采样保留时间戳、复制而不改变原图；在设备 next_frame/submit 被禁止时仍完成诊断和退出封存。诊断采样没有新增捕获或输入。
3. 四条截图调用各通知一次；失败编码、失败磁盘写入不通知，后者抛出原异常且保留 enabled；附近原始 CompletionEvidence/private.png 与 material.png 未进入诊断包。
4. 真 Runtime.run_service 两轮构造新的 Host，复用同一未关闭诊断会话；普通失败及显式停止后保存的自动战斗 enabled 意图仍为真。
5. 会话观察器、遮罩采样与诊断目录解析分别注入故障。原 PNG、业务返回、原异常/停止对象以及自动战斗配置不被改成假成功或禁用。
6. 原 LoginFlowService 成功、失败、停止和入口已停止路径；只失败触发 incident，事件字段中无合成私人账号内容。
7. 真 build_native_gamepack + install_archive；安装 payload 在禁止 config/main/custom_ok 和 native 路径禁止 Qt/ok 的条件下完成本地诊断归档。独立 MIT core 从单独目录提供，未借用 checkout 中的 src。
8. Qt offscreen 真管理控件读取本地状态、打开明细及显式时间补传；source/version 正确且无需 root config。实际按钮调用被 spy 验证；没有默认上传或共享连接。
9. installed 包管理页真配置 QProcess 加载全部 29 个任务 schema；主进程保持 legacy provider。shutdown 超时明确阻止关闭；更新后台工作完成前配置子进程仍在，完成后确认 NotRunning 才关闭。普通刷新和切到账号页不重复启动配置 owner。

网络、上传、计划任务、保留维护和 Python Popen 外部边界由失败 spy 拦截并断言未调用。涉及合成账号事务的 Windows ACL 操作在新增诊断/安装入口探测中明确 stub；没有写 NAS 凭据或访问共享。新增检查没有运行旧的 193 项账号测试。

## 验证限制

这些结果证明纯本地数据链路、进程边界和故障语义，不能等同于真实游戏、真实抓帧、真实登录、Child Session、NAS 上传或安装更新成功。本轮没有启动游戏/模拟器、没有发送真实输入、没有访问 NAS 或执行实际更新。生成的 ZIP 是临时合成测试产物，不是 NAS 待审诊断包；没有将任何真实诊断包标记为已审核。

缺失可信 master 的新安装可打开管理窗口；原配置 owner 会明确报告账号仓库不可用。建立首账号或导入后通过真实事务重新启动配置 owner，不自动制造空 master。
