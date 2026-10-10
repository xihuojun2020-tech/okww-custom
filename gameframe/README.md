# GameFrame

独立的规则自动化框架：启动器负责游戏包和执行器生命周期；执行器在设备所在 Windows 会话内完成截图、识别、决策和输入。核心不导入 `ok` 或鸣潮业务。游戏包可以提供 Python 规则、素材和任务元数据。

当前提供原生执行接口、离线帧后端、WGC 客户区截图与 SendInput、MuMu 用户 SDK 多触点、MuMu/雷电等通用 ADB 后端，以及完整鸣潮 **AGPL 兼容包**和**独立规则包**。独立包登记原29个任务，执行器使用原业务算法和角色轮转，无 ok-script/Qt 导入；账号、完成记录、真实任务配置、本地诊断和游戏包更新由独立管理进程提供。框架能够执行独立规则包，其他游戏仍需提供自己的角色、镜头、地图和日常规则。

## 安装和使用

从独立 wheel 安装核心，界面和 Windows 捕获按需要安装可选依赖：

```powershell
python -m pip install "gameframe-runtime[gui,windows] @ file:///C:/your/path/gameframe_runtime-1.97.75-py3-none-any.whl"
gameframe install .\wuthering_waves_native-1.97.75.zip
gameframe list
gameframe gui
```

开发源码下使用项目虚拟环境，查看现有源包；这些命令仅读元数据：

```powershell
.\.venv\Scripts\python.exe -m gameframe list --packages .\gamepacks
.\.venv\Scripts\python.exe -m gameframe inspect .\gamepacks\wuthering_waves
.\.venv\Scripts\python.exe -m gameframe gui --packages .\gamepacks
```

GUI 支持安装 ZIP、选择任务、保存原生任务 JSON 与设备配置、执行、暂停/恢复、停止，显示执行器原始输出及退出码。支持会话的包在同一执行器中串行运行多个辅助服务和排队任务；前台任务独占输入，结束后继续后台服务。关闭某个服务使用 Disable selected service；Stop 结束执行器并保留服务偏好。兼容鸣潮任务使用其完整生产配置与设备选择，具体业务完成由原程序的完成检查判断。退出码 0 只表示进程正常返回。

独立规则包 `wuthering_waves_native-1.97.75.zip` 按包内 `requirements.txt` 安装执行依赖；管理窗口另需 `requirements-management.txt`。Manage gamepack 打开账号、序列、完整性检查、配置包及完成记录；全新安装须经明确表单/预览/确认建立首账号，或导入自己的配置包，任务入口不会创建空 master。ZIP 已完成禁止旧框架导入的实际生产轮转与停止验收，管理页也在安装载荷中打开并正常关闭；29项任务的代表性离线分支范围详见验收报告，不代表全部实战流程完成。

默认安装与框架状态位于当前 Windows 用户的 `~/.gameframe`。Windows 用户由人手动切换；在各用户目录分别安装游戏包，可以保留各自的游戏包配置和账号组。源模式鸣潮包使用当前源码安装的数据路径；它不会自动复制或迁移私人账号配置。安装拒绝覆盖同 ID 的已有包，避免把更新当成重装而丢失包内配置。

Manage gamepack 的“任务与配置”页读取生产任务和全局配置的当前值、默认值、帮助、类型、动态选项与显示条件，保存由无设备的配置进程执行。独立鸣潮包的启动器 JSON 是本次运行覆盖值；长期设置在管理页保存，启动器只持久化设备和所选任务。隐藏任务保留执行注册，不出现在任务列表。

“日志与诊断”页读取该包数据目录中的本地会话资料，支持查看、导出、打开目录及用户明确触发的共享连接测试和打包上传。执行器从已有帧缓存复制并遮盖身份区域，记录原生任务、账号切换和错误画面；管理窗口不构造捕获或输入设备。独立包不启动后台上传或 NAS 保留维护。

已安装且带 `files.json` 的包可从 Update gamepack 选择本地 ZIP，也可在管理页“游戏包更新”检查独立发布源并下载。原生发布路径为 `GameFrame-Packages/<包ID>/stable/latest.json`，ZIP 名为 `<包ID>-<版本>.zip`。下载暂存于用户数据目录；核心验证完整文件索引、包身份和版本，以及执行/管理 requirements 的实际依赖一致性，再等待本启动器的执行和管理进程退出后替换包代码并重新发现任务。事务日志支持交换中断恢复；用户数据目录不参与替换。源码工作目录不能热更新，真实依赖变化需要完整环境升级。

实际worker在payload导入前取得包共享锁及数据共享锁，在设备创建前取得输入独占锁。Windows输入按当前会话的真实WindowStation/Desktop互斥，因此不同HWND、包和数据目录仍不能同时发键；ADB按serial、MuMu按安装目录/instance互斥。Replay不占用真实输入。包安装、更新、回滚和交换恢复持独占锁，冲突立即报错；锁文件由内核管理且长期保留，不靠PID/超时判断失效。

管理与配置命令使用 `gameframe.package_process` 在同一实际进程的包共享锁内核对版本、导入载荷并运行。原生worker设备、游戏包异步诊断/证据和账本收尾完成后释放锁。恢复与整树备份在数据独占锁内执行；维护页先停止配置owner，提交后重建账号缓存。兼容bootstrap持包、source_root数据及桌面输入锁，已加载证据和诊断在返回前收尾；旧direct main.py和直接调用bootstrap.run未纳入此框架入口的锁保障。

ADB与MuMu尚未提供跨backend同实例映射，不能据此保证两个后端操作同一个模拟器时互斥。POSIX锁实现未在本轮Windows环境运行。配置备份、系统定时、只读耗时总览与原生用户任务编辑已接入；角色代码编辑与脚本包导入导出已接入。设备表单、暂停热键、托盘通知、截图/OCR、账号特征码及输出目录入口已接入；程序偏好、六语言与保存辅助恢复已接入；后台后端、UID实时遮罩和显卡告警已接入代码消费者，真实设备效果待实测；登录自启与完整环境更新继续迁移。

用户任务在管理页“用户任务代码”中保存，使用 `NativeBaseTask` / `NativeTriggerTask` 和稳定 UUID。框架只读取 JSON 目录来显示任务；源码在无设备的独立验证进程中执行，属于可信可执行代码，不能视为安全沙箱。运行进程使用 Apply user task reload 明确应用目录更新；单次任务通过重新启动应用。Refresh tasks 只刷新列表，保存不代表所有执行器已重载。执行前核对定义版本，长期设置从持久配置加载，运行 JSON 仅提供明确覆盖值。

原生规则包的单次执行示例：

```powershell
.\.venv\Scripts\python.exe -m gameframe run .\examples\vision_probe --task find-template --device '{"type":"replay","frames":["C:/your/frame.png"]}' --config '{"template":"C:/your/template.png"}' --data-dir .\test_out\probe
```

截图和素材的相对路径以调用者目录解释，包资源建议通过 `Path(__file__).parent` 定位。元数据与安装不会执行游戏包入口；点击运行才导入其 Python 代码。

## 设备合同

| 后端 | Device JSON | 实际能力 |
|---|---|---|
| 离线 | `{"type":"replay","frames":["frame.png"]}` | PNG 帧、动作轨迹，完全不向系统输入 |
| Windows | `{"type":"windows","hwnd":123456}` | 默认 WGC 客户区 BGR＋前台 SendInput；可明确选 BitBlt_RenderFull/PrintWindow 和 PostMessage，后者无原始相对鼠标/物理鼠标能力 |
| MuMu | `{"type":"mumu","install_dir":"C:/MuMu","instance_index":0,"dll_path":"C:/your/nemu.dll"}` | 用户安装的 SDK 像素读取、持续多触点；不分发供应商 DLL |
| 通用 ADB | `{"type":"adb","serial":"127.0.0.1:5555","adb_path":"C:/your/adb.exe"}` | PNG 截图、tap、swipe、keyevent；无持续多点，不作为低延迟战斗路线 |

`Frame.image` 是消费者可持有的独立 BGR 数组，坐标以客户区/Android 图像原点为准。新帧带单调序号和明确的主机接收时间；主机接收时间不是游戏渲染时间。Python/OpenCV 裁剪仍在 CPU，不能消除 GPU 到 CPU 的整帧回读。

原生包在 `run(task_id, context)` 内用 `context.frame()`、`context.act()`、`context.sleep()` 和 `context.emit()`。设备只声明实际支持的能力；例如 MuMu 需要 `touch_down/move/up(contact=0..9,x,y)`，不把鼠标 click 假装为持续摇杆。Windows 支持虚拟键整数、ASCII 字母/数字，以及 space/tab/enter/esc/shift/ctrl/alt、左右修饰键、方向键和 F1–F24。

停止通过受控 stdin 请求协作退出，任务在 finally 释放持有的输入。对不响应停止的自有执行器，控制器会强制结束其进程树；强制结束无法保证已挂起的原生调用执行清理，不能算正常停止或游戏业务成功。普通服务故障保留 enabled 意图，观察者输出失败也不终止战斗服务。

Windows 可在现有 `hwnd` 上执行，或明确提供 `launch_command`（绝对程序路径及参数）和 `target_executable`（目标游戏绝对路径），省略 HWND 时按此命令启动。重绑只选择该启动进程家族中的唯一可见目标窗口，验证进程身份并重建 WGC；模糊匹配或无法记录启动家族会报错。设备启动的游戏进程有明确身份登记，强制结束执行器时保留这些进程；“Exit After Task”仅在任务成功收尾后结束选定游戏进程并退出启动器。

游戏包声明 `supports_session` 后提供 `run_session(task_id, context)`，通过 `context.requests` 接收 `run-task` 和 `set-service`；包负责自身任务调度与能力检查，核心保留单一输入所有者。管理扩展声明 `management` 并提供 `management_command(data_dir)`，只在用户打开时启动独立进程。管理命令应使用 `gameframe.package_process --package ROOT --expected-version VERSION --module MODULE -- ...`，让实际进程在导入规则前持包锁；任意第三方命令不能由Controller代为保证其运行期持锁。包有异步写入者时提供 `close()`，在返回前完成自身写入者收尾。元数据发现与 ZIP 安装均不执行这些入口。

## 后台和商业化边界

WGC 可选择 HWND 采集，但 SendInput 仍需要该会话的前台窗口。完全不抢占主桌面键鼠，需要在独立 Windows 会话内运行游戏与执行器；当前研究优先保留 Child Session/本机 RDP 路线，但未在本轮配置或测试。BetterGI 的公开 issue 已报告输入法重定向可能影响主桌面，鸣潮的反作弊/会话兼容性也未验证，不能承诺后台输入成功。

框架自主代码采用目录内 MIT 许可。兼容鸣潮源码与其运行时继续遵守 AGPL，游戏素材、模型及 SDK 另有来源和授权；分进程本身不自动消除许可义务。素材来源和原版替换清单随游戏包附带，未匹配上游的文件也不能自动视为自有版权。MuMu 商业使用及 SDK 再分发需另行确认授权。

本轮仅离线图片、mock 接口、隔离 Python 子进程及包结构验证；没有启动游戏或模拟器，也没有验证任何真实账号、后台会话、采集延迟或实战轮转。

只读总览使用 Overview gamepack，或 `gameframe overview PACKAGE_PATH --data-dir ABS_DATA_PATH`，可与worker共存。管理页的“配置备份与恢复”复用完整配置备份与恢复事务；当前worker或其他总览占用数据时，独占维护会明确失败。系统定时任务按当前Windows用户隔离，仅明确点击创建或删除，不自动切用户；执行时需要该用户的交互会话及可用设备。硬件和实际系统定时运行尚未验证。

角色代码页按内置类身份保存自定义代码与使用模式，内置代码只读；Apply character code reload 由实际运行 owner 释放输入后应用，暂停与启用偏好保留。

用户任务页支持多个任务和随包素材的原生脚本包，导入前展示清单与转换差异。旧包只转换已支持的 API，未知依赖明确报错；导入包成员只读，通过整组重导入更新，稳定任务 ID 与私有配置保留。导出不包含私有配置，不覆盖现有文件。随包 COCO 特征以包标识为 namespace；素材更新也改变执行定义 revision。

设备表单保留高级 JSON，MuMu 与 ADB 能力不足以运行鸣潮键鼠任务。管理窗口可以与同包执行会话共存，设备动作和特征码由现有 owner 返回，特征码仍需用户确认绑定。暂停热键使用按下沿触发，冲突时停用该热键；关闭到托盘与系统通知可分别设置。截图文件按生产身份遮罩，OCR识别原帧，结果只返回请求方。

管理页“输出目录”复用原复制/校验/提交事务，保留原文件；当前数据根是目录配置权威。截图、证据及诊断在切换后重绑真实 owner，完整账号/配置/脚本根与运行控制状态留在数据根。其他worker/总览占用时独占迁移明确失败。

原生通知在管理页配置 Discord、Telegram、企业微信、QQ Guild 及 QQ/微信桌面渠道。密钥字段不回显，保存与清除为明确操作。HTTP 完成与桌面任务边界投递分别报告；桌面交接保留当前 owner 和输入锁，暂停不发送、退出取消排队项。QQ Guild 不上传图片。桌面联系人、剪贴板和真实送达均未实测。v1.97.75 增加 requests 执行依赖，从 v1.97.73 升级需要更新完整执行环境，不能只热替换 ZIP。

v1.97.75 设备 JSON 可设 `capture_method`（WGC / BitBlt_RenderFull / PrintWindow）和 `input_method`（SendInput / PostMessage）。GDI 使用同步渲染调用，不保证超时、新鲜帧或游戏兼容性，最小化会明确拒绝；PostMessage 的窗口消息不抢占键鼠，但目标游戏是否消费它们仍须验证，显式 activate 仍会改变前台。实时 UID 遮罩只在当前可信前台客户区显示；算法留在 AGPL 包，MIT 核心只绘制通用 patch。GPU 告警只读且一次执行，缺失可选接口保持未知；普通视觉或告警故障不关闭战斗。
