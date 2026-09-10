# LAN error evidence implementation plan

**Goal:** 本机完成主体程序、测试和 GitHub 发布；异机更新后只配置发送端并验收。

**Architecture:** 复用 SMB 批次协议。新增有界错误窗口模块，executor 自己的线程刷新诊断帧，诊断后台线程压缩/落盘，原上传器传输，reader 汇合事件。

**Tech Stack:** Python 3.12、现有 OpenCV/Pillow、threading、SMB、现有 Qt 状态卡。

**Spec:** ../specs/2026-09-10-lan-error-evidence-design.md（设备分工以用户最新指示为准）。已获实现和发布授权，在本次会话内顺序执行，不再请求执行方式确认。

## Global constraints

- 前 10 秒、后 5 秒、每秒 1 张；不编造历史帧。
- 不修改游戏任务语义；读取/补采在 executor 原有线程完成。
- 保留 manifest v1、既有目录、重试、保留策略和凭据机制。
- 独立 worktree，不包含主工作区另一项功能的修改。
- 用本地 .venv 运行测试。最后协调远端最新版本，按中等变更更新 X.YY.00、发布说明并推送注释标签。

## Task 1: 有界错误窗口和测试

Files: 新建 src/runtime/diagnostic_evidence.py、tests/TestDiagnosticEvidence.py。

接口：EvidenceWindow(root, identity, publish, clock=time.monotonic)；trigger(data, at)、sample(frame, captured_at, captured_monotonic)、tick()、finish()。publish(index, pictures) 返回已封装批次，window 单线程拥有，触发通过 session 队列传递。

- [ ] 编写假时钟测试，采样 t=0..20、t=10 触发，断言 pre=10、at=1、post=5；再验证启动不足、旧帧、合并、30 秒截断和字节上限。
- [ ] 执行 `.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestDiagnosticEvidence.py`，确认未实现时失败。
- [ ] 实现按 monotonic 划窗、压缩缓存、立即前帧落盘、每次追加图片形成不可变批次和事件 revision、异常恢复。
- [ ] 重跑测试，检查 complete 与 uploaded 各自独立。

## Task 2: 主程序接入和周期刷新

Files: diagnostic_session.py、diagnostic_lifecycle.py、custom_ok/ok/task/TaskExecutor.py；测试扩展 TestDiagnosticEvidence.py 和 TestDiagnosticPipeline.py。

接口：executor 提供 `_diagnostic_frame` 元组和 `_service_diagnostic_capture()`；仅原线程采集。session 将 trigger 放入独立有界队列，worker 按独立 1 秒采样/2 秒日志截止时间运行。

- [ ] 验证 ERROR、异常钩子调用同一路径、WARNING 不触发、退出不等 5 秒。
- [ ] 验证 executor 暂停/等待仍可安全刷新，且不改 `_frame` 业务状态；超过 freshness 上限记为 stale。
- [ ] 保留普通截图接口及现有测试；后台采样不调用 UI/网络。

## Task 3: 接收索引、恢复与保留

Files: diagnostic_export.py/session.py、diagnostic_reader.py、diagnostic_retention.py；TestDiagnosticEvidence.py。

接口：seal_run 附加 `incident` JSON，图片仍走原导出；reader 从已校验批次生成事件视图；retention 删除相关日志文本副本，保留图片关联。

- [ ] 测试本地模拟远端上传、重复、断线、乱序、最后索引先到，图片齐后可重建。
- [ ] 测试断电遗留 collecting 事件恢复为 incomplete、已落盘图片可补传。
- [ ] 测试日志清理后无错误文本副本残留、图片关联保留。

## Task 4: 配置状态与异机操作文档

Files: DiagnosticStatusCard.py、diagnostic_uploader.py、两份 spec 文档、docs/references/lan-diagnostics.md。

- [ ] 显示错误截图状态、缺帧原因与容量暂停；保留本机目录/凭据入口。
- [ ] 添加显式命令行 LAN 写读改名删除探针，只使用临时唯一测试目录。
- [ ] 文档改为“本机开发发布、异机更新配置验收”，提供版本验证、配置、测试探针、截图验证与报告步骤。

## Task 5: 回归和发布

Files: run_tests.ps1、config.py、README.md、更新日志.md、验收记录。

- [ ] 诊断、捕获、UI、版本、打包检查通过后运行全量测试组。
- [ ] 使用合成帧跑至少 20 次端到端事件时延，明确非真实双机测量。
- [ ] 查询远端标签，避免与另一任务的发布冲突；验证固定宽度版本和发布说明。
- [ ] 仅提交本次文件，创建对应注释标签、推送分支和标签，验证 GitHub 构建/Release，报告真实状态。
