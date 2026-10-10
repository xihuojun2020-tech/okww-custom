# GameFrame 维护与运行总览实施计划

**Goal:** 独立游戏包迁移可恢复配置备份、序列修复、运行总览和每日耗时；启动器可在worker运行期间打开明确只读的总览。

**Architecture:** 复用ConfigBackupService/ConfigIntegrityService和现有账号控件。维护在data独占锁内执行，配置owner正常退出后恢复并重绑缓存。每worker使用PROCESS_SESSION独立状态文件，真实PID/create_time确认存活，复用现有阶段和计时事件发布；只读总览有独立包进程，不启动配置owner。

**Tech Stack:** 现有Python/Qt、OS文件锁、psutil、原子JSON；不新增依赖。

**Spec:** 用户全量功能迁移与单输入owner要求；v68数据生命周期锁和v69只读设计。版本1.97.69，不运行游戏/模拟器、NAS或真实账号，不注册系统任务。用户手动切换Windows账号。

本阶段同时迁移原日历定时：NativeSchedule使用Windows Task Scheduler COM，InteractiveToken绑定当前用户，命令使用实际核心目录、绝对包/数据目录、稳定任务ID和明确设备JSON。NativeScheduleTab仅明确按钮触发查询/创建/更新/删除；开窗不注册任务。共享安装的归属前缀包含当前用户，避免跨用户覆盖。此接口已属于现有产品功能迁移，不增加自动切换Windows用户。

## 文件与接口

| 责任 | 文件 | 必要接点 |
|---|---|---|
| 维护服务代理 | native_maintenance.py、account_runtime_bootstrap.py、native_configuration.py、worker.py、plugin.prepare_data、management启动 | prepare_native_data在SH之前；EX恢复pending journal及安全每日快照；NativeMaintenanceService路径/备份/验证/预览/恢复/序列修复/清理；EX内reload_account_runtime |
| live代理 | native_live_status.py、native_combat_host.py、task_status.py、daily_timing.py、两既有总览/耗时控件、新NativeExecutionOverviewDialog及测试 | NativeLiveWriter(context,package_id,version)，NativeLiveReader(data_dir).reload/owners/live/timings；显式选择worker，按session/batch/profile/attempt匹配活记录 |
| 主代理 | NativeMaintenanceTab、ManagementWindow、AccountManagementService.rebind、src.native_overview、plugin live/overview command、核心manifest/controller/CLI/gui、版本和文档 | 先冻结写入口和停止config owner，再异步维护；成功重建账号页/重新配置owner，失败区分磁盘与reload/重启；独立readonly overview入口与正常关闭 |

## 依据与约束

- ConfigBackupService构造会恢复journal，不能在SH内无条件实例化。pending恢复无法取得EX必须失败；每日快照遇活owner可明确延后。
- native Config只原子替换单文件，不走账号writer mutex，所以完整树快照也要EX。继续复用原备份策略，不扩大删除范围。
- 恢复先保留预览digest/base revision，再原事务提交；warm runtime同root不会自动重绑，新增生产reload。重建持旧repository引用的账号/序列页，不保留恢复前draft。
- 维护操作前检查账号页/序列页已在途BackgroundOperation，freeze入口后才能停止config owner。停止未确认时不恢复。维护失败后明确恢复界面状态；磁盘提交成功而runtime/config启动失败分别报告。
- data SH允许多worker，不能一个live.json覆盖；使用PROCESS_SESSION文件和真实执行PID/create_time。正常只删除自身文件，崩溃文件按身份忽略。
- 总览只读入口持SH，不调用账户迁移/恢复，不创建设备、TaskHost或配置owner，不放宽现有管理写操作guard。

## 实施与离线验收

- [x] 维护服务和pre-data启动安全点：真实EX/SH竞争、pending恢复、预览后变更拒绝、暖缓存重绑，临时合成配置验证。
- [x] Qt维护页：实际按钮/预览确认、忙操作禁止恢复、停止失败不提交、成功重建账号页，配置重启失败不伪报回滚。
- [x] Live写入/读取：多worker独立文件，PID复用/死亡不显示运行，业务ID/monotonic时间不混框架run_id；普通诊断失败不改变任务。
- [x] 总览/耗时Qt与launcher入口：只读无写动作、worker选择、精准session/batch/attempt运行状态、正常停止；退出前停止刷新并等待实际后台读取结束，才释放包/数据锁。
- [x] 系统定时：Windows argv真实解析、模拟COM创建/更新/删除、用户归属、安装核心路径；未注册真实任务或启动游戏。
- [x] diff保护分支和独立复核，最终wheel/ZIP实际安装验收；本地备份与v1.97.69发布依项目流程记录。随后继续动态任务/角色、设备设置及其他剩余迁移。
