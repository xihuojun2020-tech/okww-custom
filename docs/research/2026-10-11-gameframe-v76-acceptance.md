# GameFrame v1.97.76 离线安装与交付验收

本轮完成配套 core/native 环境准备、稳定引导器、三种更新策略、登录启动和定时计划入口。最终消费者复核补齐设备表单六语言。未启动游戏、模拟器或真实输入，未访问 NAS、读取真实账号、写系统计划或注册登录项。

| 验收范围 | 结果与证据 |
| --- | --- |
| Release/source/transport | NativeRelease 11、LanUpdateTransport 6、LanUpdateManifest 3 项通过。覆盖通道顺序、真正未发布与错误区分、索引/metadata/哈希、发布 readback 和保留旧 latest；远程传输使用 fake。 |
| Managed 生命周期 | ManagedInstallation 16、ManagedEntries 8 项通过，含版本倒退、重复候选、租约、迟到旧 owner、提交错误及恢复。 |
| GUI 更新与登录 | NativeUpdateControls 10、LoginStart 6 项通过；注册表使用 fake，不代表真实 Windows 登录触发成功。 |
| 定时与维护语言 | NativeSchedule 7 项及 NativeManagementPageLanguage 的真实离屏 Qt 单项通过，不运行真实 COM scheduler/维护写操作。 |
| 既有调用方回归 | CLI、PackageProcess、WorkerLeases、Core、MaintenanceUI、Schedule、Language 合集 50 项中 49 项首次通过；唯一失败的旧 task fixture 参数修正后该单项通过。没有为测试替身修改生产行为。 |
| 设备表单六语言 | DeviceEditor 全 5 项及 NativeLanguage catalog/source/binary 覆盖单项共 6 项通过。新增一项穿过真实启动器 schema 接线，六语言切换不改变参数、设备 ID 或用户窗口标题。 |

这些次数按实际执行分别记录，包含重复套件，不相加为独立测试总数。此前业务、角色、账号和所有已列任务分支的离线证据继续有效，详见 [最终覆盖矩阵](2026-10-11-gameframe-final-coverage.md)；未在本轮无理由重跑全部历史测试。

真实离线环境验收使用 30 个已核对的依赖 wheel、core wheel 和原生 ZIP，实际创建 venv、执行隔离 no-index pip、pip check 和无设备 preflight。core 来源为新环境 site-packages；包有 29 项任务和正确最低核心版本。真实缺 requests wheel 的负例产生 pip 失败，候选目录清理，未出现 ready/pending。证据为备份根 `managed-acceptance.json` 及 `offline-install.log`。

复制的纯标准库 bootstrap 与真实 core 子进程通过 Windows kernel 文件锁互操作。独立 child 持 shared owner 时保留 active/pending；释放后坏 receipt 明确失败，记录 precommit 并调用 verified 旧 active 的模拟 GUI callback。实际安装包的无设备 update hook 经 package_process 和 AGPL CLI 返回 source_unconfigured，未访问默认 NAS。合成 `_enabled:true` 私人配置字节不变。测试安装故意留下失败候选作为证据，不作为用户启动入口。

最终原生 ZIP 的代表性验收使用已安装 core、现有图片和 Replay，禁止旧 ok/Qt 执行依赖。实际生产 `_run_combat`、`perform_combat_rotation`、`perform`、`do_perform` 路径到达模拟设备边界，显式停止后 cancelled、held 为空、enabled 为 True。全部生产模块来源为安装 payload；完整索引和外层哈希有效。它证明实际生产规则在离线设备契约中可运行，不证明完整队伍或全部角色实战表现。

设备翻译收尾后重新构建发行物；旧候选及其证据保留在备份根 `before-device-labels`。逐成员 delta 证明 core 仅三个界面 Python 文件及 RECORD 改变，ZIP 仅翻译、说明、更新日志和索引改变，执行算法完全一致。最终 `artifacts-acceptance.json` 是工件尺寸和 SHA256 的权威记录，`paired-release/release.json` 是完整配套清单。core wheel 的全部 Python 文件与最终源码逐字节匹配；core 不含 src/ok/鸣潮素材或 catalogs。两个 ZIP 保留 AGPL、逐文件索引和素材清单。

干净用户交付安装位于 `E:/AI work/GameFrame/Administrator`：Python 基座独立于源码和测试环境，版本目录按原生产安装器生成，资料根全新，不复制合成失败候选或真实账号。真实离线安装、pip check、preflight、ready/索引及稳定入口检查通过。只准备 valid pending；首次用户启动稳定入口时提交并打开 GUI。本轮未执行该用户入口。原 AppData 安装观察到 MSIX 路径重定向，历史记录保留，最终改在 E 盘独立位置。完成状态记录在 `delivery-installation.json`。

最终 E 盘安装另外通过生产轮转 Replay，以及设备表单 5 项、定时/维护页 1 项的真实离屏 Qt 检查，core 来自最终环境 site-packages、生产代码和 catalogs 来自安装 payload。六语言标签重绘不改变设备数据，测试仅使用合成窗口/服务。证据为 `final-rotation-acceptance.json` 和 `installed-surfaces-acceptance.json`。语言完整专项 10 项及更新控件/overlay 接线 14 项也在收尾后通过。真实 Windows 登录、系统定时触发和界面设备效果仍待实测。

源码快照、逐文件 SHA、所有 Python AST、ZIP CRC、完整 Git bundle 和远程 ref 在发布步骤核对。备份根为 `E:/AI work/okww-framework-backups/20261011-v1.97.76`。新版本 commit 与 annotated tag 由 `release.json` 记录，保留无关工作区修改。
