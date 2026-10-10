# 独立管理与更新迁移计划

用户授权自主设计和实施，本批承接已发布1.97.66。目标是让独立包有实际配置/诊断/更新入口；禁止游戏、模拟器、真实账号和NAS访问，验证使用临时目录与本地transport。核心保持MIT，诊断、账号和原业务派生实现留在AGPL包。

| 责任 | 文件 | 交付接口与最小验收 |
|---|---|---|
| 更新核心代理 | gameframe/packages.py、package_updates.py、controller.py | prepare_update(archive,packages_dir,package_id,current_version,target_version)、apply_update(plan,ensure_idle)、recover_updates；实际rename故障恢复、强制index、双owner空闲、用户data不变 |
| 配置运行时代理 | src/runtime/native_combat_host.py、native_configuration.py及metadata | 真实schema/current/default/help/type/options/visible，owner set-config/invoke-action；no-device JSONL管理进程。布尔sub_configs不丢类型，原Config validator/on_change和服务意图保留 |
| 诊断代理 | diagnostic_lifecycle/session、native诊断helper、native_screenshots、login_flow、plugin、诊断控件/ManagementWindow | local_only与显式root/source/version；缓存copy-mask、exact screenshot、脱敏事件、一次session生命周期；零额外capture/input/隐式网络，真实封存ZIP |
| 主代理 | gameframe/gui/worker/__main__、src/gui/NativeConfigurationTab、native包更新服务/卡片 | JSONL界面与owner连接；typed schema控件、动态选项/隐藏依赖，配置不由launcher重复持久化；包更新事件待管理退出后应用并rediscover |

管理进程现有账号Qt控件使用旧框架类型，配置执行类必须在独立no-device进程native模式装配，避免同进程模块缓存混版。配置子进程没有设备构造入口，保存由其owner执行；真实执行session通过相同请求在执行owner处理。

更新准备在包目录旁的隐藏事务目录，持久记录prepared/switching/committed。非committed交换中断恢复旧包，committed保留新包并完成清理；prepared保持待用户应用。GUI串行管理代码变更，并在两个实际owner都退出后应用。更新网络继续复用原传输，原生发布源和包命名与旧应用分开；锁文件发生真实依赖差异拒绝热更新，不自动pip或重启游戏。

- [x] 核心事务和故障恢复：索引、包身份/版本、实际依赖校验及交换中断恢复已通过相关隔离检查。
- [x] 真实任务/全局配置metadata与owner命令：无设备JSONL配置进程和真实生产schema已通过检查。
- [x] 管理设置页与动态schema控件：类型、动态选项、隐藏条件与保存生命周期已通过相关Qt检查。
- [x] 原生本地诊断与管理入口：缓存copy-mask、exact screenshot、脱敏事件及会话封存已通过隔离检查。
- [x] 原生包更新传输、依赖比较、同启动器GUI owner协调：本地transport验证；缓存损坏重下与UTF-8 BOM一致性修复后，主代理报告17项更新检查通过。
- [x] 本轮源码复核及相关旧路径回归；复核范围和限制见 `docs/research/2026-10-11-gameframe-v67-review.md`。
- [x] 最终ZIP/wheel artifact实际安装验收：生产轮转、管理配置、v66→v67替换与安装后诊断通过。
- [ ] 备份与发布。

用户任务/角色编辑热载、日历定时及耗时视图承接本批稳定配置接口继续实施；不把注册任务或可编辑JSON当成这些功能已经完成。

跨启动器与CLI的设备输入/包生命周期锁已完成方案讨论，留待v68；本批owner空闲检查只覆盖当前启动器的两个实际进程，不代表跨进程互斥完成。
