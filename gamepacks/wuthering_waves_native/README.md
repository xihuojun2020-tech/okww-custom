# 鸣潮独立战斗游戏包

这个包通过 GameFrame 设备执行现有生产自动战斗和角色轮转。它使用包内的任务 API、配置、Box、COCO 匹配、颜色检测和 OCR 服务，保留原规则和素材。程序源自 AGPL 项目，本包继续采用 AGPL；更换图片不会改变派生代码的许可义务。

此入口只提供自动战斗。完整日常、多账号、材料、挑战、诊断及原界面目前由另一个 `wuthering_waves` 兼容包提供。迁移状态分开记录，不能把它们算作已经独立实现。

安装 GameFrame 和此包的 `requirements.txt` 中依赖后，使用启动器选择明确的设备 HWND，或在离线测试中提供 Replay 帧。模型从已安装的 onnxocr 依赖读取，OpenVINO 编译缓存、配置、日志、截图和执行账本保存在调用方指定的数据目录。不会读取旧程序私人账号配置。

源码模式包的素材位于当前仓库；ZIP 构建包含自己的 `payload/src` 和 `payload/assets`，不依赖原 checkout。构建命令：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_native_gamepack --output C:/your/output/wuthering_waves_native.zip
```

当前不承诺游戏实战、后台会话兼容性或硬件延迟。本轮禁止启动游戏／模拟器。Windows WGC 和 SendInput 仍要求执行器位于目标会话，输入目标处于该会话前台。MuMu 设备提供触控而非 PC 键鼠，此鸣潮包不会据此宣称模拟器能运行鸣潮。
