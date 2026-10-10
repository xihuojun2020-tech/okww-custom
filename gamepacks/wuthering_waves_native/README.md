# 鸣潮独立规则游戏包

这个包通过 GameFrame 设备执行现有生产自动战斗、角色轮转、日常、多账号、材料、活动和挑战任务。它使用包内任务 API、配置、Box、COCO 匹配、颜色检测、OCR、YOLO 与原账号/证据服务，保留原规则和素材。程序源自 AGPL 项目，本包继续采用 AGPL；更换图片不会改变派生代码的许可义务。

29个生产任务均有原生入口；GUI共享会话在同一执行线程运行辅助服务和前台任务，战斗可释放输入后响应服务关闭及任务请求。已验证真实图片识别/轮转和代表性业务分支，尚未验证全部任务完整实战。原诊断上传、更新及其他管理页面目前由 `wuthering_waves` 兼容包保留，继续迁移。

安装 GameFrame 和此包的 `requirements.txt` 中依赖后，使用启动器选择明确的设备 HWND，或在离线测试中提供 Replay 帧。模型从已安装的 onnxocr 依赖读取，OpenVINO 编译缓存、配置、日志、截图和执行账本保存在调用方指定的数据目录。不会读取旧程序私人账号配置。

账号管理需另安装 `requirements-management.txt`，然后使用 Manage gamepack，或 `gameframe manage PACKAGE_PATH --data-dir ABS_DATA_PATH`。管理页只在独立进程加载 ok-script/Qt，提供账号与序列、完整性检查、配置包导入导出及已有完成记录；没有捕获/输入实例。新安装需明确建立首账号或导入配置包，缺失/损坏可信 master 会阻止执行任务。

源码模式包的素材位于当前仓库；ZIP 构建包含自己的 `payload/src` 和 `payload/assets`，不依赖原 checkout。构建命令：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_native_gamepack --output C:/your/output/wuthering_waves_native.zip
```

当前不承诺游戏实战、后台会话兼容性或硬件延迟。本轮禁止启动游戏／模拟器。Windows WGC 和 SendInput 仍要求执行器位于目标会话，输入目标处于该会话前台。MuMu 设备提供触控而非 PC 键鼠，此鸣潮包不会据此宣称模拟器能运行鸣潮。
