# 鸣潮游戏包：生产兼容阶段

当前版本 **1.97.65**。游戏包保留当前完整鸣潮应用、22 个一次任务、7 个触发任务、57 个角色源码文件，以及全部 `src`、定制 `custom_ok`、素材、翻译和图标。完整应用入口打开原界面；单项入口按精确类名调用同一生产 `main.run_application` 和 `OK.run_task`。任务的配置继续由原程序管理，没有复制账号选择、登录、战斗或消费账本实现。

这是 **AGPL 兼容接入**，尚未移除旧 `ok-script`、Qt 及其他依赖，也没有宣称全部业务已经独立重写。旧依赖和资源的原有授权仍适用；素材来源表不能代替商用授权。

## 在源码目录使用

从项目根目录启动 GameFrame，选择此包。`application` 运行完整应用；其他任务以无主界面模式运行对应生产任务。触发任务持续运行到用户停止。GameFrame 只管理自己启动的进程，进程退出不等同任务业务成功。

`source_root='../..'` 指向当前安装，兼容应用读取该安装自己的现有配置。传给 `legacy_command` 的 `data_dir` 用于框架运行记录，不会重定位、复制或清空原程序账号资料。运行资料仍采用生产 storage bootstrap 的安装盘布局。

## 构建和独立安装

```powershell
.\.venv\Scripts\python.exe scripts/build_gamepack.py --output dist/wuthering_waves.zip
```

构建包包含独立 `payload`，无需原 checkout；ZIP 内所有文件具有 SHA256 索引。构建只允许生产源码目录和显式资源/元数据，排除真实 `configs`、日志、缓存、`.venv`、诊断证据和厂商 DLL。输出已存在时明确失败，防止覆盖旧构建。

通过框架的 Install gamepack 按钮或 `python -m gameframe install <ZIP> --packages <包目录>` 安装；目标包已经存在时拒绝覆盖。安装 Windows CPython 3.12 与 `payload/requirements.txt` 的固定依赖后，由框架启动包。包自身不携带 Python 或已安装依赖。首次启动是新的生产安装，会初始化新资料；从旧安装迁移私人配置应继续使用原生产导入/备份流程，构建不搬运账号资料。

兼容启动通过生产 `_sync_custom_ok` 在首次导入 ok 前安装当前进程的模块覆盖，未修改的模块来自固定旧依赖，不写共享 site-packages。包内纯颜色工具已经独立于 ok 与 GameFrame；完整战斗循环仍由生产兼容应用执行。更新须在任务停止后进行；生产程序仍带现有诊断/更新功能，其配置与授权范围保持原有语义。

## 验证界限

离线测试检查任务注册、源码/资源完整性、无设备副作用导入、自包含路径、精确生产入口调用和私密目录排除。游戏、模拟器、Child Session 与 NAS 均未启动；实际登录、战斗和日常成功不能由这些测试推断。
