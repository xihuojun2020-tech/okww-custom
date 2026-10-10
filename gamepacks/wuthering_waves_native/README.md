# 鸣潮独立规则游戏包

这个包通过 GameFrame 设备执行现有生产自动战斗、角色轮转、日常、多账号、材料、活动和挑战任务。它使用包内任务 API、配置、Box、COCO 匹配、颜色检测、OCR、YOLO 与原账号/证据服务，保留原规则和素材。程序源自 AGPL 项目，本包继续采用 AGPL；更换图片不会改变派生代码的许可义务。

29个生产任务均有原生入口；GUI共享会话在同一执行线程运行辅助服务和前台任务，战斗可释放输入后响应服务关闭及任务请求。已验证真实图片识别/轮转和代表性业务分支，尚未验证全部任务完整实战。独立管理页已提供真实任务/全局配置、本地诊断与已安装游戏包更新。

安装 GameFrame 和此包的 `requirements.txt` 中依赖后，使用启动器选择明确的设备 HWND，或在离线测试中提供 Replay 帧。模型从已安装的 onnxocr 依赖读取，OpenVINO 编译缓存、配置、日志、截图和执行账本保存在调用方指定的数据目录。不会读取旧程序私人账号配置。

账号管理需另安装 `requirements-management.txt`，然后使用 Manage gamepack，或 `gameframe manage PACKAGE_PATH --data-dir ABS_DATA_PATH`。管理页只在独立进程加载 ok-script/Qt，提供账号与序列、完整性检查、配置包导入导出及已有完成记录；没有捕获/输入实例。新安装需明确建立首账号或导入配置包，缺失/损坏可信 master 会阻止执行任务。

“任务与配置”使用生产任务的当前配置、帮助、类型、动态选项和显示条件；保存交给独立的无设备配置进程，账号变更后重载选项。启动器中的 JSON 只覆盖本次运行，长期设置在管理页保存。部分内部任务按生产 `visible` 元数据隐藏，原生执行入口仍保留。

“日志与诊断”查看本包数据目录的会话资料和错误画面，支持本地查看/导出，以及用户明确点击的连接测试和打包上传。原生执行器只读取已有帧缓存，复制并遮盖身份区域后写入诊断，不为诊断额外截图或输入；不自动访问 NAS。

“游戏包更新”仅适用于已安装且包含完整 `files.json` 的包，源码目录显示限制说明。用户点击检查后读取独立发布源 `GameFrame-Packages/wuthering_waves_native/stable/latest.json`；下载的 `wuthering_waves_native-X.YY.ZZ.zip` 暂存于数据目录。校验身份、版本、大小、SHA256、文件索引和两份 requirements 后，由启动器在自己持有的执行/管理进程退出后交换包代码并重新发现任务。也可用启动器 Update gamepack 选择本地 ZIP。实际依赖变化拒绝热更新，需完整环境升级；更新不会自动启动游戏。

跨启动器/CLI 的输入与更新锁已接入；完整配置维护、系统定时和只读运行/耗时总览已接入；自定义角色/任务热载继续迁移。

源码模式包的素材位于当前仓库；ZIP 构建包含自己的 `payload/src` 和 `payload/assets`，不依赖原 checkout。构建命令：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_native_gamepack --output C:/your/output/wuthering_waves_native.zip
```

当前不承诺游戏实战、后台会话兼容性或硬件延迟。本轮禁止启动游戏／模拟器。Windows WGC 和 SendInput 仍要求执行器位于目标会话，输入目标处于该会话前台。MuMu 设备提供触控而非 PC 键鼠，此鸣潮包不会据此宣称模拟器能运行鸣潮。

执行器持包和数据共享锁到设备、诊断及证据写入者实际收尾完成；同一桌面输入由实际worker独占。管理与配置由核心package_process在导入payload前持包锁并核对版本，包更新需要独占代码锁。备份/恢复页停止配置owner后取得数据独占锁，提交后重建账号页；存储路径迁移继续推进。ADB和MuMu同模拟器实例的跨backend身份映射尚未提供。

只读总览通过启动器Overview gamepack或`gameframe overview PACKAGE_PATH --data-dir ABS_DATA_PATH`打开，显示已保存任务和明确选定worker的活状态；不执行账号迁移、设备连接或配置写入。“系统定时任务”保存当前Windows用户的交互任务，使用稳定任务ID和已保存设备，用户手动切换Windows账号。恢复、系统定时和总览仅完成离线验收，未注册真实系统任务或进行游戏运行验证。
