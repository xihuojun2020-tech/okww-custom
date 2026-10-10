# 独立框架、游戏包与后台执行：补充来源核查

调研起始日期：2026-10-10，北京时间跨日完成于 2026-10-11。本文补充同目录的 [框架与后台报告](2026-10-10-okww-framework-and-background-feasibility.md) 和 [多账号、模拟器与低延迟报告](2026-10-10-multiaccount-emulator-lowlatency-feasibility.md)，只调查能够改变今晚技术选择的公开资料。

**建议保持“独立 Python 核心＋游戏包＋独立执行器”的选择。** 本次没有找到更适合完整迁移当前魔改版功能、又同时解决桌面隔离与授权的现成通用产品。MaaFramework 已有成熟的游戏资源清单和独立进程扩展，可以借鉴边界；pluggy、stevedore 解决插件发现与调用，不提供游戏捕获、会话或进程隔离。Windows 继续以当前用户 Child Session 为待验证环境；MuMu 保留原生截图、多触点研发方向。

本次新增三项必须准确表述的证据：

1. **windows-capture 的 Python `crop()` 是整帧回读后的 NumPy 切片；Rust `buffer_crop()` 才进行 GPU 区域复制。DXcam 的现有 WinRT 后端采集显示器，不能直接代替 HWND 窗口捕获。**
2. **MuMu 官方协议明确个人使用以外及商业用途需要另行授权。** 已公开的 YofunSDK、MuMuPlatformSDK 不等于外部渲染 IPC SDK 的商用或重分发许可。
3. **BetterGI 有实际子会话输入法干扰主桌面的用户报告。** 本次未找到鸣潮在 Child Session 成功执行战斗、登录与日常的直接报告，不能提前宣称该组合已经兼容。

没有启动游戏、模拟器或子会话，没有操作账号、读取私有凭据、访问 NAS、修改产品代码，也没有安装研究依赖。所有性能判断均为接口或源码结论，未经本机测量。

## 1. 游戏包与独立进程：现成组件解决什么

| 方案 | 已确认的能力 | 没有因此得到的能力 | 对当前迁移的建议 |
|---|---|---|---|
| Python 标准 `importlib.metadata`＋PyPA entry points | 安装包声明入口、按 group/name 发现、加载 Python 对象 | 子进程、独立依赖环境、捕获与输入隔离 | 首版可用标准库；目录包清单也足够，不必立即要求 pip 插件安装 |
| pluggy，MIT | hook 规范、插件注册、入口点加载及有序调用 | 独立执行进程、游戏包分发、任务持久化与输入所有权 | 只有出现多个包需共同响应 hook 的真实需求时引入 |
| stevedore，Apache 2.0 | 对入口点的 driver、extension 等发现与加载模式 | 进程隔离和游戏执行器 | 当前选中一个游戏包时，标准库已经覆盖主要需求 |
| MaaFramework，LGPL-3.0 | ProjectInterface 资源/任务/控制器清单；AgentServer 在独立进程实现识别和动作，AgentClient 负责桥接 | 当前 okww 全量角色策略与账本迁移；跨游戏动作反应延迟保证；Child Session 宿主 | 可作包清单与业务/主控边界参考；不因有 Agent 就替换现有完整战斗循环 |

Python 官方文档把 `EntryPoint.load()` 定义为解析入口值；PyPA 规范的对象引用按 `importlib.import_module`、`getattr` 解析。这是普通 Python 对象加载，不是沙箱或自动子进程。[F01][F02] pluggy 和 stevedore 的许可与职责已读取项目来源；GitHub API 观察到两者在 2026-10 仍有更新，更新日期不等于对本项目的兼容保证。[F03][F04]

MaaFramework 的 `Custom & Agent` 文档明确：AgentServer 负责业务识别、动作和事件监听，主流程调度及生命周期由 UI/主控承担。ProjectInterface V2 的 `agent` 提供 `child_exec`、`child_args`、连接标识，并约定启动子进程时注入当前控制器和资源的运行快照；Python 示例实际调用 `AgentServer.start_up(socket_id)`、`join()`、`shut_down()`。[F05][F06][F07] 因而“界面选择包、执行进程执行规则”已经有可核查实现，不需要为这个组织方式另造插件中间件。

但 Maa 的独立进程识别调用也有图像传输成本：固定源码 `Transceiver::send_image` 先发送图像头，再通过 ZeroMQ 发送 `mat.total() * mat.elemSize()` 的像素数据。[F08] 这是实际进程间图像传输，不能称为零拷贝 GPU 推理链。当前动作游戏的采集→识别→规则→输入应尽量在同一环境内执行器完成，主界面只接收状态、控制命令和按需预览。

**首版建议**：当前选中一个游戏包，执行器加载这个包；保留已确认的生产任务与角色行为，由主控管理选择、状态和停止。不要为了“插件”先把每帧识别拆成跨进程 RPC，也不要新增通用行为树或多游戏常驻服务。后续包依赖冲突出现时，再按证据决定每包独立运行环境。

这里的独立进程隔离属于软件生命周期边界，不自动证明复制旧代码后可闭源。前两份报告已经说明旧 okww/ok-script、BetterGI、OneDragon 的许可；本次没有发现可以通过子进程绕过这些许可的授权依据。

## 2. WGC 维护与 ROI：Python 接口和原生接口要分开

| 组件与核查基线 | HWND 窗口捕获 | ROI 实际位置 | 发布与维护观察 |
|---|---|---|---|
| windows-capture，`c7d106448eb9d9b251345c39047711e1cd408ae2` | Python 提供 `window_hwnd`；名称匹配另有路径 | Python `Frame.crop()` 为 NumPy 切片；原生 bridge 先整帧 `CopyResource`；Rust `Frame.buffer_crop()` 用 `CopySubresourceRegion` | GitHub `pushed_at` 为 2026-10-05；PyPI 2.0.1 于 2026-08-08 上传 Windows x64 wheel，Python ≥3.9 |
| DXcam，`1e595ff55e57263c4b5d0414828f74104afa86f4` | 此 WinRT 实现调用 `create_for_monitor`，没有对应 `create_for_window` | 显示器区域可以使用其区域路径；不能据此宣称得到遮挡窗口 ROI | GitHub `pushed_at` 为 2026-09-23；PyPI 0.3.0 于 2026-03-12 发布，Python ≥3.10 |
| PyWinRT | 为 WinRT 类型与互操作提供绑定 | ROI 回读还需 D3D11 原生处理；绑定不代替完整采集实现 | MIT；GitHub 于 2026-10-10 有更新，仍为可维护基础候选 |
| wincam，`0d7035c5a4f906560411aa23fafb7825c8fbecf5` | 本次没有把它核定为直接 HWND 替代 | C++ 源码有 GPU `CopySubresourceRegion` 后续回读实现，可作参考 | 许可为 MIT，并注明使用 FFmpeg LGPLv2.1；PyPI 最新观察为 1.0.14，2025-04-03 发布 |

windows-capture Python 构造器同时提供 `monitor_index`、`window_name`、`window_hwnd`，要求只选一种目标；`window_name` 是 substring matching。执行器已有确切窗口句柄时应使用 HWND，避免把名称匹配当作精确进程身份确认。[C01]

其 Python `Frame` 带 `timespan`；Rust 桥从 `frame.timestamp()?.Duration` 获取它，Rust `timestamp()` 返回 WGC `SystemRelativeTime()`。它适合记录帧新鲜度，但仍不能当作游戏逻辑实际生成时刻。[C02][C03] 本次还通过 PyPI JSON 找到 2.0.1 wheel，在内存中读取其 Python 源文件，确认已发布版本包含 `window_hwnd`、`timespan` 与 NumPy `crop()`；没有把仅在主分支出现的接口误报成已发布能力。[C04]

原生 Python bridge 的 `NativeMappedFrame` 持有映射资源，CPU 视图保持 owner 生命周期；这种“zero-copy view”可以减少 Python 再复制，GPU→CPU 的 staging `CopyResource` 与 `Map` 仍存在。[C02] 因此有两层不同收益：**减少 CPU 整帧复制**与**减少 GPU 回读面积**。只应用 `frame.crop()` 不能获得后一层收益。

Rust `buffer_crop()` 接收矩形起止坐标，创建小 staging 纹理并用 `CopySubresourceRegion` 复制指定区域。[C03] 如果战斗识别明确只需 HUD ROI，未来可以给独立采集模块暴露这种路径；多个分散小区域与一次全帧回读孰优，需要实际帧年龄和回读耗时判断。当前没有实测依据要求今晚重写整个采集栈。

windows-capture issue #80 的用户反馈过大显示器捕获后再 crop 仍慢，维护者指出底层 WGC 不能直接选择任意屏幕区域。[C05] 该帖是 2024 年的反馈，不当作当前版本性能测量；本次源码才是 CPU 裁剪与 GPU 区域复制边界的主要依据。

**选型建议**：要求被遮挡游戏窗口时保留 `CreateForWindow` 类 WGC 路径，或使用已发布、支持 HWND 的 windows-capture。DXcam 作为显示输出捕获的候选；不能仅因提供 WinRT backend 就替换窗口采集。固定发行版本与依赖，记录来源时间戳，在执行器内运行。GPU ROI 优化独立排期，等当前迁移和同环境基线测量完成再判断。

## 3. MuMu：多触点能力成立，商用许可尚未取得

本次继续确认前份报告的技术证据：MaaFramework MuMu 后端调用 `nemu_input_event_finger_touch_down/up`，EmulatorExtras 的头文件描述手指 ID；这说明持续多触点可表达。它不证明所有目标游戏的摇杆、攻击、镜头并发实际稳定，也不证明厂商授予重分发权。[M01]

新增官方来源比“未找到许可证”更明确：[MuMu 平台使用许可及服务协议](https://mumu.163.com/20250103/25905_1204122.html) 定义覆盖 Windows、Windows ARM、macOS 等模拟器软件。第四条第 1 款授权个人非商业使用，并写明：

> 如用户有需要在个人使用的范围以外使用本平台及本服务或者将本平台与本服务用于任何商业用途，则用户应与网易公司联系并获得网易公司另行授权。

第四条第 2 款另限制未经书面同意复制、传播本平台程序与手册等。[M02] EmulatorExtras 固定 README 也仍写 `No License`，由模拟器厂商保留一切权利。[M03] 不能因 MaaFramework 是 LGPL，就将该目录的 SDK/DLL 当作 Maa 的 LGPL 内容打包。

搜索容易混入三个不同接口：

| 名称 | 来源确认的用途 | 与本项目外部控制的关系 |
|---|---|---|
| MuMuManager CLI | 官方提供实例管理、ADB 等开发者操作 | 可作为发现/生命周期依据；不是 external_renderer_ipc 商业使用授权 |
| YofunSDK / 联运 SDK | MuMu 开放平台中的游戏渠道接入、APPID 与包体管理 | 不应把 SDK 接入或隐私合规页面套用到 PC 截图/触控 IPC |
| MuMuPlatformSDK | TapTap 技术适配手册明确面向游戏/引擎开发，辅助适配、检查、调优；获取需联系 MuMu 商务 | 是游戏内部适配 API，不是 `external_renderer_ipc` 的授权正文 |

TapTap 手册明确说 MuMuPlatformSDK 和 MuMu 联运 SDK 不同，也提醒只介绍能力、合作获取联系商务。[M04] 官方开放平台 SDK 接入页要求游戏管理中的 SDK 包体管理、接入文件与 APPID。[M05] 这些是厂商公开支持合作接入的证据，但没有给第三方自动化框架提供我们所需的 external renderer 使用/商业化/重分发许可。

本次针对 `site:mumu.163.com external_renderer_ipc`、`nemu_input_event_finger` 的搜索未获得厂商对应授权说明；搜索结果甚至包含站点限定以外的 GitHub 链接，因此没有将搜索摘要作为官方证明。

**建议**：保留后端开发，运行时读取用户已安装厂商组件；发行包先不要附带 DLL、头文件或厂商手册，也不要宣称已经获得商业授权。商业发行需要明确确认外部渲染/触控 API 调用、使用范围、DLL 重分发、接口版本维护这几项。这里是本任务已有商业发布目标的真实边界，不要求阻止已经授权的本地迁移或个人测试。

## 4. Child Session：原神证据充分，鸣潮仍需现场验证

BetterGI 官方页面仍写明“理论上”支持任意游戏，并在 FAQ 解释：原神相对鼠标由 BetterGI 做特殊转发，其他游戏兼容需提出 issue。[S01] 文档不是鸣潮兼容报告。执行器在子会话本地输入与人工通过 RDP 宿主控制镜头是两条不同路径；后者存在原神特定实现，不能据此否定前者，也不能据此证明鸣潮已经可用。

本次搜索范围包括公开网页、Bilibili 索引、GitHub issues/PR：

- GitHub issue 搜索 `repo:babalae/better-genshin-impact 鸣潮` 返回 2 项，分别是旧“更好的鸣潮/归龙潮”功能建议和一般后台执行建议，不是 Child Session 鸣潮运行记录。
- 同仓库 `Wuthering` 返回 0 项。
- GitHub 全站组合 `"ChildSession" "Wuthering"`、`"桌面分身" "鸣潮"` 均返回 0 项。
- anysearch 的 `BetterGI 桌面分身 鸣潮`、`鸣潮 ChildSession 子会话 黑屏` 和 Bilibili 定向组合没有给出可核查的鸣潮成功报告；普通鸣潮黑屏帖与自动生成教程不作为子会话证据。

这些是**本次未检索到**，不能写成“所有社区都不存在”或“鸣潮一定不兼容”。没有启动游戏，因此启动器链、渲染、WGC 新帧、登录与战斗输入都保持未验证状态。

新增的实际兼容性边界来自 BetterGI [issue #3685](https://github.com/babalae/better-genshin-impact/issues/3685)：用户报告 Windows 11 25H2 Build 26200、BetterGI 0.64.0、微信输入法，在子会话切号登录后，自动化字母按键失灵，主桌面凭空出现字母/候选框；宿主窗口隐藏和打开时均可发生。[S02] 用户将原因推断为 TSF 输入法与 RDP MS-RDPEIME 重定向，并提供过个人实验解释。没有本次独立复现，因此原因链按用户推断表述。

评论中维护者 `huiyadanli` 认为这是第三方软件或微软需要适配的同名用户多登录问题，其他软件处理困难；没有承诺 BetterGI 已修好。其余 AI bot 评论明确为 AI 建议，本报告不拿它作独立证据。Issue 已关闭也不证明修复成功。[S02]

另一个真实用户反馈 #3409 记录 Win11 Pro 23H2、微软账户、SuperRDP 与子会话模式互斥、登录提示用户名错误；后续维护者将说明更新到文档。[S03] 这支持检查已有 RDP 修改与实际登录身份，但不支持自动安装/卸载系统补丁。用户还主动澄清“桌面分身更快”指人工预览和交互，BGI 在会话内运行时与普通 RDP 的采集/输入不能按此评价；不将该主观感受改写成程序性能优势。

开放 PR #3763 为 RDP 关闭、Hello-only 等启动条件加入诊断；其中 `DevicePasswordLessBuildVersion` 被作者明确标为社区结论，尚无微软公开契约。[S04] 它是待合入建议，不是已经发布的兼容保证，不要求照搬全部保护分支。

**建议**：当前用户 Child Session 仍是 PC 桌面隔离的优先验证环境。首次允许实际运行后，只验证目标游戏启动、持续新帧、镜头与按键、主桌面输入法干扰、登录切号、隐藏/恢复与正常退出。依据 #3685，应把子会话输入法/重定向列为具体观察项；没有现场失败依据时，不添加进程注入、全局卸载输入法或自动修改系统设置。

## 5. 今晚可以据此确定与仍不能确定的事项

| 状态 | 事项 | 实施含义 |
|---|---|---|
| 已确认 | 普通 Python 包可以声明入口并在指定执行器加载 | 包组织无需等待新的第三方插件框架 |
| 已确认 | Maa 的 ProjectInterface 与 AgentServer 是现成包/独立进程设计 | 可借鉴职责划分；不保证换用它更快完成全量迁移 |
| 已确认 | 支持 HWND、时间戳的 windows-capture Python 2.0.1 已发布 | 可以固定发行版本评估；仍要现场验证目标窗口 |
| 已确认 | Python crop 与原生 GPU ROI 回读不同；DXcam WGC 采集显示器 | 避免以错误接口替换现有窗口捕获或虚报性能收益 |
| 已确认 | MuMu 商业用途有官方另行授权条款 | 本地研发继续；授权与厂商 DLL 分发单独处理 |
| 已确认 | BetterGI 已有真实子会话主桌面输入干扰反馈 | 隔离承诺需要实际目标环境验证，纳入有依据的检查 |
| 未确认 | 鸣潮在当前机器 Child Session 的渲染、输入与登录链 | 先保留环境入口和验证项，不能算交付成功 |
| 未确认 | MuMu SDK 商用/再分发授权已经取得 | 没有取得或联系厂商；本次不代用户发送消息 |
| 未确认 | 哪个捕获模块对当前鸣潮总反馈延迟最佳 | 需要同环境测量；仓库维护、FPS 宣传或语言不能替代 |
| 未确认 | 全部魔改功能迁移后的行为一致性 | 本文只补来源；需要迁移清单、离线与授权现场验证 |

没有来源证据表明应今晚推翻现有选型，切换到 C# 全量重写、行为树、插件管理服务或完整 Maa pipeline。更值得落实的是：游戏代码与框架职责真正分开，当前生产切号/任务/账本继续统一，观察和输入留在同一个环境执行器，发布清单明确依赖及素材来源。

## 6. 可复核来源

公开网页均在本轮直接获取 HTTP 正文；GitHub 源码使用固定提交；GitHub issue 使用公开 REST API 读取正文与人类评论。搜索服务用于发现，结论以正文为依据。动态网页、issue 状态及 PyPI 当前版本会继续变化。

### Python 插件与进程

- [F01] [Python importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html)，Entry points、`EntryPoint.load()`。
- [F02] [PyPA Entry points specification](https://packaging.python.org/en/latest/specifications/entry-points/)，对象引用与导入方式。
- [F03] [pluggy](https://github.com/pytest-dev/pluggy/tree/87f130aa18d8fdf9c92585e72423eca7f3de727d)、[MIT LICENSE](https://github.com/pytest-dev/pluggy/blob/87f130aa18d8fdf9c92585e72423eca7f3de727d/LICENSE)。
- [F04] [stevedore](https://github.com/openstack/stevedore/tree/849be420e44d47218156adec6ccd9bfa77c4659e)、[Apache 2.0 LICENSE](https://github.com/openstack/stevedore/blob/849be420e44d47218156adec6ccd9bfa77c4659e/LICENSE)。
- [F05] [Maa Custom & Agent](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/docs/en_us/1.3-Custom%26Agent.md)。
- [F06] [Maa ProjectInterface V2，agent 配置](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/docs/en_us/3.3-ProjectInterfaceV2.md#L428)。
- [F07] [Maa Python AgentServer 示例](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/sample/python/demo3_agent.py#L21)。
- [F08] [Maa Agent 图像传输](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/source/AgentCommon/Transceiver.cpp#L503)。

### 捕获

- [C01] [windows-capture Python HWND/Frame.crop](https://github.com/NiiightmareXD/windows-capture/blob/c7d106448eb9d9b251345c39047711e1cd408ae2/windows-capture-python/windows_capture/__init__.py#L69)。
- [C02] [windows-capture Python 原生桥](https://github.com/NiiightmareXD/windows-capture/blob/c7d106448eb9d9b251345c39047711e1cd408ae2/windows-capture-python/src/lib.rs#L443)，`CopyResource`、映射 owner 及时间戳。
- [C03] [windows-capture Rust Frame](https://github.com/NiiightmareXD/windows-capture/blob/c7d106448eb9d9b251345c39047711e1cd408ae2/src/frame.rs#L188)，`buffer_crop`。
- [C04] [PyPI windows-capture 2.0.1](https://pypi.org/project/windows-capture/2.0.1/)、[公开发布元数据](https://pypi.org/pypi/windows-capture/2.0.1/json)。
- [C05] [windows-capture issue #80](https://github.com/NiiightmareXD/windows-capture/issues/80)，2024 年区域捕获反馈。
- [C06] [DXcam WinRT 后端](https://github.com/ra1nty/DXcam/blob/1e595ff55e57263c4b5d0414828f74104afa86f4/dxcam/core/winrt_duplicator.py#L283)、[PyPI 0.3.0](https://pypi.org/project/dxcam/0.3.0/)。
- [C07] [PyWinRT](https://github.com/pywinrt/pywinrt)。
- [C08] [wincam GPU crop](https://github.com/lovettchris/wincam/blob/0d7035c5a4f906560411aa23fafb7825c8fbecf5/src/ScreenCapture/ScreenCapture.cpp#L276)、[LICENSE 与 FFmpeg 提示](https://github.com/lovettchris/wincam/blob/0d7035c5a4f906560411aa23fafb7825c8fbecf5/LICENSE)、[PyPI](https://pypi.org/project/wincam/)。

### MuMu

- [M01] [Maa MuMu 多触点](https://github.com/MaaXYZ/MaaFramework/blob/8963191215ca49d6b037802acd07d20a4213160a/source/MaaAdbControlUnit/EmulatorExtras/MuMuPlayerExtras.cpp#L125)、[厂商接口头](https://github.com/MaaXYZ/EmulatorExtras/blob/54d3a3ad448f0541df3759ae91b571a6762daaf1/Mumu/external_renderer_ipc/external_renderer_ipc.h#L83)。
- [M02] [MuMu 平台使用许可及服务协议](https://mumu.163.com/20250103/25905_1204122.html)，第二条定义、第四条使用许可与限制。
- [M03] [EmulatorExtras No License 声明](https://github.com/MaaXYZ/EmulatorExtras/blob/54d3a3ad448f0541df3759ae91b571a6762daaf1/README.md)。
- [M04] [TapTap：MuMu 模拟器游戏技术适配参考手册](https://developer.taptap.cn/docs/pc-store/sim-intro/sim-tech-manual/)，第三节 MuMuPlatformSDK。
- [M05] [MuMu 开放平台 SDK 接入](https://open.mumu.163.com/help/20240130/40147_1135196.html)。
- [M06] [官方 MuMuManager CLI 开发者说明](https://mumu.163.com/help/20240807/40912_1170006.html)。

### Child Session 实际反馈

- [S01] [BetterGI 桌面分身文档](https://www.bettergi.com/feats/command/session.html)，本次正文标注最近更新 2026-10-09，其他游戏与相对鼠标 FAQ。
- [S02] [BetterGI #3685：子会话输入法干扰主桌面](https://github.com/babalae/better-genshin-impact/issues/3685)，正文和维护者评论；没有本次独立复现。
- [S03] [BetterGI #3409：分身与 RDP 修改模式反馈](https://github.com/babalae/better-genshin-impact/issues/3409)，Windows 11 Pro 23H2 用户正文与评论。
- [S04] [BetterGI 开放 PR #3763](https://github.com/babalae/better-genshin-impact/pull/3763)，启动预检与诊断建议。

检索限制：Github 未登录公开 API 和搜索索引不会穷尽未索引论坛、私有群或视频评论；0 个命中只描述本次检索结果。搜索 API 未故障，无需以虚构或未经授权来源补足。首次 HTML 请求遇到字符编码与缺少 BeautifulSoup 后，改用 UTF-8 与标准库解析公开正文，没有安装包或读取私密资料。
