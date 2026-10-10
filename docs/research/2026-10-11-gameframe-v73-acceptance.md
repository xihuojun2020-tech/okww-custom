# GameFrame v1.97.73 离线验收

本阶段实现仅会话启动与保存辅助服务恢复、生产账号上下文快捷选择、任务分类与隐藏行为、当前 Windows 用户的本地资料根，以及六语言和真实程序偏好消费者。全部功能迁移仍在推进。

检查使用临时账号、Replay、真实配置 JSONL 子进程、模拟窗口/音频/ONNX session 和离屏 Qt。没有启动游戏或模拟器、操作真实账号、发送系统输入/通知或访问 NAS。

- 最终 wheel 13 项通过：原桌面控制与破损目录、仅会话启动、账号查询收尾、选择锁、live 路由及导航。wheel 内 Python 源码逐字节核对，独立核心禁止旧 src/ok/Qt 导入检查通过。
- 最终兼容 ZIP 与原生 ZIP 安装索引有效；安装后生产轮转、真实管理窗口及只读总览 3 项通过。实际 v1.97.72 → v1.97.73 更新保留合成私人标记，安装后的诊断路径检查通过。
- 最终 wheel 与 payload 的扩展验收 12 项通过：核心账号界面 4 项、实际生产账号配置子进程、headless 语言、六语言配置元数据、程序偏好与 OCR 4 项、独立 session-only 恢复。逐模块确认核心和业务代码来自安装物，最后索引有效，前后 SHA256 未改变。
- 源码偏好与账号专项 15 项通过，含 builder 保持全部 29 个任务的 visible/category/order，缺失 ONNX Runtime 时 Auto 使用 OpenVINO、Yes 明确失败。六语言各 242 条译文及 Qt 行为的源码专项 9 项通过。

修复实际安装边界：onnxocr-ppocrv5 的依赖元数据只列 pyclipper/shapely/pillow，本地也未装 ONNX Runtime；默认 Auto 不能直接强制导入该可选模块。适配器只在模块存在时检查 DML provider，保留 OpenVINO；没有掩盖驱动或模型初始化错误。PyPI 已确认 onnxruntime-directml 1.24.4 存在 CPython 3.12 Windows x64 wheel，安装说明列为可选，不声称 GPU 性能提升。

全新资料根仍须先通过管理窗口建立首账号或导入配置包。configuration host 遇到未发布账号索引会明确失败，自动恢复因此不会启动设备；账号上下文模拟缺失测试不代表全新游戏运行成功。

分发物、安装来源与 SHA 记录保存于 `E:/AI work/okww-framework-backups/20261011-v1.97.73`。源码快照逐文件 SHA/ZIP CRC/Python 解析和完整 Git bundle另行核对后发布。独立核心 MIT，鸣潮派生包 AGPL；素材替换不解除派生代码义务。真实游戏、Windows 后台会话、模拟器、定时触发、音频和硬件延迟尚未实测。
