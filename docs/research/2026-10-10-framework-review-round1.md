# 框架迁移第一轮静态审查与根因复现

检查于2026-10-10，报告完成于2026-10-11。迁移前基线1.97.61 / HEAD `4c0a4ad853d98bdc4474d3b6f43dc9c5ae03fcca`。完整功能、API和模块盘点见framework-migration-inventory报告。

本轮确认三种错误边界缺陷：定制框架同步失败被忽略、YOLO推理失败返回空检测、一次任务清理异常中止共享执行器。三项都用实际方法的AST片段、合成输入和内存fake复现；没有启动游戏、读取真实账号或访问NAS。不能把故障注入结果说成已观察到线上发生。

## 范围与证据强度

- 产品307个Python文件与顶层测试222个文件全部AST解析，无语法错误；产品68,693行。完成引用/继承/注册盘点，人工点读启动、执行器、自动战斗、账号运行、登录服务、关键界面、YOLO与既有研究。
- 此处“全量”指文件结构扫描。没有声称529个文件每条分支都经过人工语义审查，也没有运行完整历史测试集。
- API核对只定点读安装ok源码，没有导入OK/启动controller或操作设备。
- 下面行号对应修改前源码，之后修复会改变行号；以函数名和语句为稳定定位。

## R1-01：after_run异常使自动战斗共享执行线程终止（P1）

定位：`custom_ok/ok/task/TaskExecutor.py` execute，原773行 `after_run()`，之后依次清 `_account_feature_run`、`prevent_sleeping(False)`、释放task-owned输入、清running/current_task；`destroy()`在while之后。

根因：run主体有except恢复，但finally中直接调用after_run。finally抛出的普通异常不会回到同一个try的except，直接逃出execute，后面的输入/身份/状态清理及destroy也不执行。自动战斗保存的enabled仍可能为True，但执行线程已经停下，不能满足“其他任务故障不能终止自动战斗服务”的要求。

生产钩子链：BaseWWTask.after_run会分类任务、查DailyTask并清profile binding。当前标准实现主要做内存字段清理；本轮未证明该标准实现已经在线上抛错。故障边界仍违反现有共享执行器的生命周期契约，以及AGENTS对持续自动战斗和恢复hook的明确要求。

隔离复现：提取execute AST到小类，用fake一次任务，run设置内存exit_event以限制循环；after_run注入RuntimeError。原结果：异常逃出、destroy次数0、输入release次数0、`_account_feature_run`仍为`bound`。不触发Qt/游戏/账号初始化。

最小修复目标：在清理边界明确记录普通after_run失败，继续执行其余清理和调度；保留显式停止/退出异常的控制流。输入释放不能被前一个清理钩子失败跳过；身份与running/current_task必须清理。不能为此清除后台战斗enabled，也不能加入总重试次数关闭。

最小回归：成功/失败after_run、日志报告本身失败、task-owned release调用、账号上下文/running/current_task清除；先失败的一次任务后能继续执行持久后台任务；停止/退出路径仍有效。现有TestAutoCombatRecovery覆盖多项恢复，但没有该finally异常路径。

## R1-02：YOLO推理异常伪装为“没有检测”（P1）

定位：`src/OnnxYolo8Detect.py` detect原180–199行；`src/OpenVinoYolo8Detect.py` detect原135–148行。两者捕获任意Exception、log error后return []。

根因：空检测是有效业务结果；后端运行/模型输出/预处理故障也返回同样[]，调用者无法区别。Globals.yolo_detect直接返回该值；BaseWWTask中声骸/目标识别直接消费。已有任务框架和自动战斗具有异常恢复路径，把异常吞掉会绕过这些路径，造成无目标或扫描完成的错误观察。

隔离复现：提取两份detect方法AST，2×2合成BGR帧，fake预处理成功，ONNX session.run / OpenVINO compiled_model抛RuntimeError。两者原结果均[]，error日志各1次。

最小修复目标：让实际推理失败沿既有异常边界传播；无需新增fallback或重试。保留真正没有候选框时_postprocess正常返回[]。OpenVINO初始化的NPU→CPU回退有具体后端契约，与推理错误吞掉不是同一问题，本轮不顺手改动。

最小回归：两后端失败保持异常类型/对象，不能返回[]；真实空后处理仍[]；成功detect仍调用sort_boxes并返回框列表。无需加载模型或ONNX/OpenVINO设备。

## R1-03：定制框架文件未同步却继续启动（P1）

定位：`main.py` _sync_custom_ok原78–110行，逐文件和最外层except Exception均pass；__main__原324行在启动错误try块之外调用它。

根因：copy2、源/目标读取或import失败被忽略。后续进入SourceVersionOK并宣称当前源码版本，但可能使用旧/混合框架；这不是有效恢复。ConfigItemFactory与TaskExecutor的实质改动正由该同步交付，启动前必须知道是否成功。

隔离复现：提取_sync_custom_ok方法AST；fake源/目标分别`custom`/`old`，copy2注入PermissionError。原结果：copy调用1次、返回None、print次数0。没有读写site-packages。

最终修复：用当前进程的导入overlay替代全部复制。同步import ok后再复制的方案仍会执行旧包初始化与依赖，也不会自动重载已导入的模块，并污染其他包共享的venv。因此保留_sync_custom_ok名称但改为安装src.runtime.framework_overlay，生产在prepare_storage之前安装，测试runner共用同helper。第一次安装发现ok已import明确失败；同root幂等，不同root拒混；只覆盖真实存在custom_ok文件，未覆盖模块仍由锁定ok-script==1.0.190提供。缺失整个定制目录/真实IO失败明确报错。没有向site-packages复制文件。

最终回归：合成base包与custom包验证模块来源、未覆盖模块回落base、base源码不变；同root安装幂等；晚安装/不同root混用/缺目录/真实IO失败明确报错；主入口overlay先于storage且失败先于OK构造。此前复制IO回归已删除，它不再是当前实现契约。

## 本轮不作为已确认bug的事项

| 事项 | 已知事实 | 后续验证 |
|---|---|---|
| 独立核心/Qt与游戏相互导入 | 153种ok导入符号；custom_ok反向导入src业务 | 实际迁移时拆分hook/UI注册，不增加没有需求的通用抽象 |
| Windows/设备兼容 | 当前WGC/BitBlt/PostMessage配置与Win32输入存在 | 离线契约不能证明后台输入或Child Session兼容，需要授权设备测试 |
| BackgroundOperation超时 | 只有LanUpdateCard.check使用20秒timeout；未发现mutating apply操作使用该timeout | 不把任意异步超时理论竞态扩大为本轮缺陷 |
| 账号/材料/证据真实性 | 源码有protected master、snapshot、生产登录服务和账本 | 只用合成输入/fixture测试；不读取真实账号验证 |
| 老活动/隐藏入口 | hidden和注释未注册任务确实存在 | 保留当前状态，不能仅凭盘点自行重新启用 |
| 主导航数量 | 实际6个区域，旧注释写5个 | 文档口径应跟实际manifest；不是运行故障 |

## 验证记录与限制

本轮在仓库本地`.venv/Scripts/python.exe`执行AST解析和上述3类隔离复现。结果：529文件解析无错；三类原缺陷均按预期触发。所有fake只在内存，不调用源码模块启动流程。既有全套测试未执行，图片回放/Qt/模型/真实设备也未实测。

后续修复及其最小回归执行结果应追加此文档；修复测试通过只说明这几个错误边界通过，不能等同全部功能完成迁移或真实运行成功。

## 最终修复与最小回归（2026-10-11）

修改main.py、custom_ok/ok/task/TaskExecutor.py、两YOLO文件、scripts/run_test_file.py；新增src/runtime/framework_overlay.py和tests/TestFrameworkErrorBoundaries.py。根代理统一版本与发布，本代理未修改config.py。

- overlay替代全部venv复制；只在本进程改变导入来源。报告中的复制PermissionError复现是基线历史证据，最终实现不再进行复制。
- YOLO失败传播；真正零候选仍[]；没有新增fallback或重试。
- after_run普通故障明确报告，诊断hook失效不阻断身份/输入/状态清理和下一后台task。停止/退出信号保留，未清自动战斗enabled。
- 生产共用run_application(task=None,stop_event=None)，pre-set停止不初始化；运行停止桥调用真实OK.quit并等待executor线程清理。frame/sleep停止改为FinishedException，避免SystemExit跳过destroy；未另写账号/任务切换实现。
- 一次任务旧run_task返回True只表示其等待循环已结束，不能证明业务完成；服务返回True也可能是停止。包装原样返回，--headless仍由包bootstrap先设置。

最终执行：ErrorBoundaries直接运行13项通过（0.265秒）；scripts/run_test_file.py隔离入口13项通过（0.278秒，子进程监督0.422秒）；既有TestTestRunner的模块来源和成功/skip统计2项通过（0.504秒）。当前diff --check通过。合成临时包与内存对象不加载真实账号/设备；既有模块来源测试仅import实际TaskExecutor类，不创建OK/TaskExecutor对象或启动游戏。

新增边界只处理已复现hook/退出故障、已导入模块不会重载的导入契约、固定源码来源与真实文件IO。没有总重试关闭或无证据默认结果。测试通过不等同全部功能迁移完成、模型推理/设备/后台输入实测成功。
