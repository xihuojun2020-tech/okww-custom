# v73 配置与启动路径复核

## 范围与证据

本次复核覆盖原生配置 host、账号上下文协议、任务清单导航，以及 Controller、Runtime、worker session-only、启动器资料根与会话恢复接线。代码处于多人共同实施阶段；中间快照缺口不等同于已发布缺陷。

没有连接设备、启动游戏或模拟器、发送真实输入、执行真实账号登录、访问 NAS 或发送通知。

## 配置 host 修复

`create_configuration_host` 与执行 plugin 使用同一组 Program Preferences 和 Language 默认配置。它实例化真实偏好迁移对象，将偏好配置传给 host，再绑定 host 的全局配置实例，确保配置页和执行过程读取同一文件。任务清单元数据也绑定到 host，供隐藏、分组与排序使用。

配置过程保持 `TaskContext.device=None`、`ocr_engine=None`，未新增设备准备、OCR 模型加载或输入路径。

## 账号上下文与导航

账号选择依赖生产 MultiAccountDailyTask 的序列、账号注册资料和写入锁。前台工作期间拒绝修改；已经核验的身份与保存选择、运行上下文分开表示。通用 set-config 的选择字段同样经过该协议，避免绕过只读状态；普通字段验证完成后才进行一次合并写入。

清单保留全部 29 个注册任务，隐藏旧导航中的内部或停用项目，并使用既有分类顺序。

## 启动与会话复核

Controller 在 session-only 情况下要求共享会话、不接受任务配置，并由 worker 的互斥参数明确区分任务与仅会话启动。Runtime 使用 session 专属能力集合和 `__session__` 运行记录，保持同一输入锁与 finally 释放输入。原生 host 的初始请求为空时不显式启用 AutoCombat；服务恢复依赖保存偏好。

启动器配置查询结果的事件分派和 query 期间切换锁已由主任务完成。最终专项验证确认：配置 owner 退出且管道关闭后才投递 UI 结果；查询完成清除 busy 状态；查询期间不能切换包或资料根；live context 回复进入账号界面；前台任务请求冻结选择；预检失败清除恢复请求并阻止启动。

已有边界：真正空白资料根的配置 host 仍会在 DailyTask 初始化时遇到未发布账号索引。账号上下文的未初始化测试在已构造 fixture 上模拟缺失资料，不能据此声称首次空白启动成功。该问题已单独告知主任务。

## 验证与限制

配置接线后，使用仓库 `.venv` 隔离 Python、显式加入仓库路径运行 `TestNativeAccountContext.py`：4 项测试通过，3.255 秒。覆盖选择持久化与成员关系、前台只读和通用配置绕过拒绝、缺失资料边界、29 项清单与隐藏排序。

新增 `TestGameFrameAccountContext.py` 的 5 项专项测试通过（首次运行 1.823 秒）：Qt 使用真实 Controller 和合成配置子进程覆盖 get/set 持久化、收尾先后顺序、查询锁、live 路由、前台冻结、稳定任务 ID 与分类隐藏；独立生产配置子进程使用真实账号 fixture，通过 JSONL 保存 S1/A3 并核对 MultiAccountDailyTask 文件，确认没有运行记录数据库。未构造设备。

这些是源码 fixture 与生产配置子进程验证；未重新执行安装包验收，也不能证明硬件捕获、输入、真实账号认证或完整空白资料初始化成功。此子任务不承担版本更新或发布。

## 冻结候选的独立分支复核

安装扩展验收另保存于版本备份目录 `installed-extensions-acceptance.json`：12 项通过，涵盖安装 wheel 的核心 Qt、安装 payload 的生产配置子进程、语言元数据、程序偏好、可选 ORT 缺库边界，以及独立 Replay session-only 保存开关混合状态。来源断言、执行后安装索引和产物前后 SHA256 均通过。此轮只读复核未重复这些测试，也未修改已打包生产代码。

所查新增保护分支具有实际边界依据：配置 JSONL 输入和持久化 launcher context 的类型检查属于外部输入；session-only 无任务配置检查属于接口契约；前台只读与 query 切换锁防止账号和资料混用；账号成员校验沿用生产可信序列；完整性失败明确返回错误；服务暂停/停止期间仅保存开关而不执行输入。没有发现应在冻结候选中删除的无依据保护分支。配置 host 与执行 plugin 的共同 global options 是两个独立进程的必要构造接线，此时提取新抽象没有独立需求依据。

确认一个后续界面接线缺口：首账号建立后的管理页本身通过 `ManagementWindow._done → refresh → _reload_configuration` 更新；返回启动器时，无 session 的 `management-exit → _select_package` 清空账号上下文、任务译名和 launcher 译文，但没有再查询配置。已有 session 时该分支仅刷新任务列表，也没有刷新账号上下文。直接选择包或改变资料根同样只清空并加载静态任务导航。结果是账号框保持空白或保留旧状态，用户必须点击现有“刷新上下文”入口；账号保存本身没有丢失。启动时恢复配置 preflight、运行 session 的 get-schema，以及手动刷新路径能够重新取得正确上下文，不能据此视为已自动覆盖建立首账号/切换资料的路径。

该结论来自完整调用路径对照，未新增测试、等待或 fallback；已通知主任务作为后续功能接线范围，不修改已冻结 v73。

## 主线集成与最终安装物复核

之后主线完成了最终 wheel 和两个 ZIP 构建。核心 13 项、安装生产轮转/管理/总览 3 项及最终安装扩展 12 项通过，安装路径逐模块核对，索引及前后哈希未变化，详见同目录 v73-acceptance 与备份中的 JSON 记录。

确认并修复了 OCR 默认 Auto 强制导入未安装的可选 ONNX Runtime。模块不存在属于实际依赖边界：Auto 保留 OpenVINO，Yes 明确 unavailable；driver/session 初始化异常继续报告，未增加重试或广义兜底。Windows extras 增加实际音频消费者所需 pycaw/comtypes。

本阶段新增检查均位于 manifest/catalog、保存的 launcher context、配置协议、任务资料完整性、可信进程身份或可选推理后端边界。session-only 参数拒绝任务配置源于明确契约；查询时冻结包/资料根并先收尾后投递结果源于已观察到的 owner 清理竞态；动态任务查询传入包资料根修复实际目录遗漏。没有为内部不变量增加逐层空值默认或重试。每 tick 全树翻译曾增加并已删除，静态控件只翻译一次，动态文本在变更点显式更新。
