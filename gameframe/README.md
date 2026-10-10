# GameFrame

独立的规则自动化框架：启动器负责游戏包和执行器生命周期；执行器在设备所在 Windows 会话内完成截图、识别、决策和输入。核心不导入 `ok` 或鸣潮业务。游戏包可以提供 Python 规则、素材和任务元数据。

当前提供原生执行接口、离线帧后端、WGC 客户区截图与 SendInput、MuMu 用户 SDK 多触点、MuMu/雷电等通用 ADB 后端，以及完整鸣潮 **AGPL 兼容包**和**独立战斗包**。独立战斗包实际执行原角色轮转，无 ok-script/Qt 导入；日常、多账号、挑战和原界面仍由兼容包提供，继续按模块迁移。框架能够执行独立规则包，不表示修改图片即可自动支持另一个游戏的角色、镜头、地图和日常业务。

## 安装和使用

从独立 wheel 安装核心，界面和 Windows 捕获按需要安装可选依赖：

```powershell
python -m pip install "gameframe-runtime[gui,windows] @ file:///C:/your/path/gameframe_runtime-1.97.65-py3-none-any.whl"
gameframe install .\wuthering_waves-1.97.65.zip
gameframe list
gameframe gui
```

开发源码下使用项目虚拟环境，查看现有源包；这些命令仅读元数据：

```powershell
.\.venv\Scripts\python.exe -m gameframe list --packages .\gamepacks
.\.venv\Scripts\python.exe -m gameframe inspect .\gamepacks\wuthering_waves
.\.venv\Scripts\python.exe -m gameframe gui --packages .\gamepacks
```

GUI 支持安装 ZIP、选择任务、编辑原生任务 JSON、执行和停止，显示执行器原始输出及退出码。兼容鸣潮任务使用其完整生产配置与设备选择，具体业务完成由原程序的完成检查判断。退出码 0 只表示进程正常返回。

独立战斗包 `wuthering_waves_native-1.97.65.zip` 单独安装并按包内 `requirements.txt` 安装 OCR 依赖；它使用 GameFrame 设备和显式数据目录。ZIP 已在禁止旧框架导入的隔离进程中完成真实生产轮转与停止验收，当前只有自动战斗入口；它与完整兼容包的功能范围分别记录。

默认安装与框架状态位于当前 Windows 用户的 `~/.gameframe`。Windows 用户由人手动切换；在各用户目录分别安装游戏包，可以保留各自的游戏包配置和账号组。源模式鸣潮包使用当前源码安装的数据路径；它不会自动复制或迁移私人账号配置。安装拒绝覆盖同 ID 的已有包，避免把更新当成重装而丢失包内配置。

原生规则包的单次执行示例：

```powershell
.\.venv\Scripts\python.exe -m gameframe run .\examples\vision_probe --task find-template --device '{"type":"replay","frames":["C:/your/frame.png"]}' --config '{"template":"C:/your/template.png"}' --data-dir .\test_out\probe
```

截图和素材的相对路径以调用者目录解释，包资源建议通过 `Path(__file__).parent` 定位。元数据与安装不会执行游戏包入口；点击运行才导入其 Python 代码。

## 设备合同

| 后端 | Device JSON | 实际能力 |
|---|---|---|
| 离线 | `{"type":"replay","frames":["frame.png"]}` | PNG 帧、动作轨迹，完全不向系统输入 |
| Windows | `{"type":"windows","hwnd":123456}` | WGC 最新客户区 BGR 帧；键盘/鼠标/相对镜头、滚轮与 Unicode 文字；输入要求目标窗口在该会话前台 |
| MuMu | `{"type":"mumu","install_dir":"C:/MuMu","instance_index":0,"dll_path":"C:/your/nemu.dll"}` | 用户安装的 SDK 像素读取、持续多触点；不分发供应商 DLL |
| 通用 ADB | `{"type":"adb","serial":"127.0.0.1:5555","adb_path":"C:/your/adb.exe"}` | PNG 截图、tap、swipe、keyevent；无持续多点，不作为低延迟战斗路线 |

`Frame.image` 是消费者可持有的独立 BGR 数组，坐标以客户区/Android 图像原点为准。新帧带单调序号和明确的主机接收时间；主机接收时间不是游戏渲染时间。Python/OpenCV 裁剪仍在 CPU，不能消除 GPU 到 CPU 的整帧回读。

原生包在 `run(task_id, context)` 内用 `context.frame()`、`context.act()`、`context.sleep()` 和 `context.emit()`。设备只声明实际支持的能力；例如 MuMu 需要 `touch_down/move/up(contact=0..9,x,y)`，不把鼠标 click 假装为持续摇杆。Windows 支持虚拟键整数、ASCII 字母/数字，以及 space/tab/enter/esc/shift/ctrl/alt、左右修饰键、方向键和 F1–F24。

停止通过受控 stdin 请求协作退出，任务在 finally 释放持有的输入。对不响应停止的自有执行器，控制器会强制结束其进程树；强制结束无法保证已挂起的原生调用执行清理，不能算正常停止或游戏业务成功。普通服务故障保留 enabled 意图，观察者输出失败也不终止战斗服务。

## 后台和商业化边界

WGC 可选择 HWND 采集，但 SendInput 仍需要该会话的前台窗口。完全不抢占主桌面键鼠，需要在独立 Windows 会话内运行游戏与执行器；当前研究优先保留 Child Session/本机 RDP 路线，但未在本轮配置或测试。BetterGI 的公开 issue 已报告输入法重定向可能影响主桌面，鸣潮的反作弊/会话兼容性也未验证，不能承诺后台输入成功。

框架自主代码采用目录内 MIT 许可。兼容鸣潮源码与其运行时继续遵守 AGPL，游戏素材、模型及 SDK 另有来源和授权；分进程本身不自动消除许可义务。素材来源和原版替换清单随游戏包附带，未匹配上游的文件也不能自动视为自有版权。MuMu 商业使用及 SDK 再分发需另行确认授权。

本轮仅离线图片、mock 接口、隔离 Python 子进程及包结构验证；没有启动游戏或模拟器，也没有验证任何真实账号、后台会话、采集延迟或实战轮转。
