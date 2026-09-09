# 钢琴按键高亮识别详细执行方案 Implementation Plan

> **2026-09-09 实机规则修正（最高优先级）：** 任一时刻只有一个按键高亮，按下后才出现下一键；每段通常按1—7次，期间可能出现剧情或转场。`1.41.07` 改为只接受单键、按后默认停顿0.15秒、转场时重置锁定并持续等待，直到用户手动停止。本文后续多键/和弦章节仅保留历史设计，不再作为实施要求。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 执行说明：上句为计划模板的工作流引用。`1.40.00` 已实现本方案的最小生产路径；本文同时保留后续真实多键样本校准和扩展验收项。

**Goal:** 将原设计落成可离线验证的 21 键高亮识别器、逐键去重状态机和 ok-script 任务适配层；支持一个、两个及更多键同时高亮，输出经过确认的按键集合，不确定时停止输入。

**Architecture:** 新增一个不依赖 Qt、设备和账号的纯算法模块，统一处理比例布局、特征、候选和时序；新增薄任务类复用截图、输入、配置和诊断接口。离线回放直接调用同一算法和状态机，用伪输入器记录事件；正式输入默认关闭。

**Tech Stack:** Windows / Python 3.12；现有 ok-script、OpenCV、NumPy、标准库 dataclasses、enum、unittest、unittest.mock。无新增运行依赖。

**Spec:** [原始设计](2026-09-08-piano-key-highlight-detection.md)，以及用户 2026-09-08 补充的参考图和“可能同时有两个或两个以上按键高亮”要求。用户补充取代原设计的唯一候选限制。同时参考项目结构、交接、贡献说明和 AGENTS，接口以当前源码为准。

## Global Constraints

- 仅支持 PC 游戏画面，不使用安卓模拟器或游戏内部注入接口。
- 只读取屏幕图像，不读取进程内存、不修改游戏文件、不注入 DLL。
- 兼容 16:9 的 1920×1080、2560×1440 等分辨率，所有坐标使用归一化比例。
- 默认使用截图识别；WGC/BitBlt 的选择沿用现有截图服务，不新增截图后端。
- 输入动作必须经过连续帧确认，禁止单帧误识别直接发送按键。
- 支持 1–21 个位置组成的高亮集合，不因数量超过一个拒绝；位置或高亮状态不确定时暂停输入并记录诊断信息。21 是识别模型容量，不是已经实测的游戏同时按键上限。
- 理论验证使用离线截图和回放，不操控真实游戏。
- `1.40.00` 代码变更按 AGENTS 同步版本、更新日志和翻译，验证后提交、创建注解标签并推送；不夹带工作区既有改动。
- 本机当前源码基线为 `7aa5ea4d`，`config.py` 为 `1.39.00`；旧结构说明和交接中的 `1.38.01` 不作为发布版本依据。执行前重新核验。
- 账号、日常、多账号切换和现有活动任务不增加钢琴调用链。任务由用户在钢琴界面手动启动，不负责进入活动、领奖或判断曲目完成。

---

## 1. 当前实现与必须收紧的设计规则

已核对的接入点：

| 位置 | 当前事实 | 本功能的处理 |
| --- | --- | --- |
| `src/task/EventTask.py` | 悲鸣行动任务，非钢琴 | 新建 `PianoTask`，不扩展这个活动的大循环 |
| `src/task/BaseWWTask.py` | `send_key` / `send_key_down` 有账号输入守卫 | 沿用任务方法，禁止直接调用底层 PostMessage/SendInput |
| `src/task/WWOneTimeTask.py` | `run()` 会复位鼠标并激活窗口 | 观察模式不调用这一启动流程；钢琴类直接继承 `BaseWWTask` |
| 框架 `BaseTask` | `frame` 可以返回缓存；`next_frame()` 主动请求截图 | 循环每轮只取一次 `next_frame()`，同一帧做所有分析 |
| 框架 `TaskExecutor.next_frame()` | 默认取帧超时 6 秒 | 取帧后重新检查经过时间；不能声称暂停一定在 1.5 秒内完成 |
| `config.py` | 一次性任务按模块名、类名注册 | 增加 `PianoTask`；初期放“测试功能” |
| `src/gui/navigation_sections.py` | 支持任务显式 `navigation_section` | 使用 `tests`，无须新增导航页 |
| `run_tests.ps1`、`TestTestGroups.py` | 测试文件显式列举并检查完整覆盖 | 每个新增测试文件同步加入分组 |
| `diagnostic_lifecycle.py` | 已挂接框架截图保存，后台沿用自动上传策略 | 只保存钢琴裁剪区域，不新建上传通道 |

本方案明确以下歧义，实施和测试都以此为准：

1. 连续确认最低为 **2 次取帧观察**，删除原文“可降为 1 帧”的例外；这遵循原文全局约束。不要将重复读取 `self.frame` 计为两次。现有后端未在任务接口提供采集序列号，因此两次观察不等于已证明两次不同的游戏渲染；静态相同图像也不能直接认定为卡帧。
2. 每键独立判断 ON/OFF/UNCERTAIN，多个 ON 是合法集合；不再使用第一名减第二名作为接受条件。存在未决光晕位置时标为 `ambiguous`，这里指不确定，不指多键。
3. OCR 只能核对键帽与位置，不能证明该键正在高亮。视觉阈值不足时，OCR 正确也不能越过阈值直接输入。
4. 宽高比正确只证明坐标可投影，不能证明正在钢琴界面；须独立检查三行圆点结构。画面不匹配时不得按键。
5. 首帧可能已经亮着 `S`，不能直接作为非高亮基线。先使用静态特征；只在可靠的熄灭状态下建立和更新相应键的历史基线。
6. 一次 `ambiguous` / 无候选立即禁止本帧输入，但不马上结束任务；连续 3 次触发一次 ROI 复查。持续异常达到 1.5 秒后进入终止性的 `PAUSED` 并返回，需用户重新启动。复查不能无限重置超时。
7. 每键独立记录发送锁。原键连续 2 帧明确 OFF 才能重新触发该键；其他键出现不能解除原键的锁。新出现的键可以独立确认，防止 `S→S+D` 重发 S。
8. 已收到原始 2560×1440 参考图，图中可见 S 的金色外环。下面坐标来自本次显示图的人工估读并按 1.25 倍还原，属于初始标注；阈值、多键时序和独立 1080p 样本仍需验证。

### 参考图初始标注（2026-09-08 补充）

来源：`C:/Users/Administrator/Videos/Captures/鸣潮   2026_9_8 13_07_29.png`。原图 2560×1440，本次消息显示为 2048×1152；以下比例不受等比显示缩放影响。原图仅用于本地参考，纳入测试须遮掉右下角 UID 和钢琴区外内容。

| 列 | 高/中/低音键 | 原图中心 x 约值 | x/W 约值 |
| --- | --- | --- | --- |
| 1 | Q/A/Z | 747 | 0.2918 |
| 2 | W/S/X | 925 | 0.3613 |
| 3 | E/D/C | 1102 | 0.4305 |
| 4 | R/F/V | 1279 | 0.4996 |
| 5 | T/G/B | 1456 | 0.5688 |
| 6 | Y/H/N | 1633 | 0.6379 |
| 7 | U/J/M | 1810 | 0.7070 |

三行中心 y 约为 `988/1142/1296`，比例约 `0.6861/0.7931/0.9000`。S 圆点中心约 `(925,1142)`；白色圆点半径约 12px，而金环半径约 42px，**金环不紧贴圆点边缘**。原方案按白点半径取 `1–1.8r` 会漏掉金环，必须单独标注光环半径。

总布局 ROI 起始建议 `(0.26,0.64,0.76,0.96)`；每个光环取样框以圆点为中心半宽/半高约 60px（1440p），并排除圆点下方键帽及水平谱线。白点、光环、背景分别使用独立掩模。图中上方六个大圆点位于另一条横线，不属于下方 3×7 键阵，本阶段排除；不根据这张静态图猜测其规则。

这张图可确认布局和 S 的视觉样式，不能证明多个高亮是否同步出现、残影持续多久、是否要求长按。执行方案先按“持续高亮触发一次短按，新亮键单独确认，同批稳定键组合按下”实现离线模型，真实多键片段用于验证该假设。

## 2. 文件与接口边界

| 文件 | 操作 | 责任 |
| --- | --- | --- |
| `src/task/piano.py` | 新增 | 数据结构、布局校验、圆点特征、候选决策、状态机 |
| `src/task/PianoTask.py` | 新增 | 配置、取帧、OCR 核对、一次按键、状态日志和裁剪诊断 |
| `assets/piano/layout.json` | 新增 | 来自真实标注的 21 键比例坐标与掩模参数 |
| `assets/piano/detector.json` | 新增 | 校准所得阈值、归一化上下界、权重、数据版本 |
| `docs/assets/piano-key-layout.md` | 新增 | 原图来源、标注方法、比例表、缩放叠图、参数说明 |
| `tests/images/piano/manifest.json` | 新增 | 帧路径、原始尺寸、会话分组、标签和回放序列 |
| `tests/images/piano/*.png` | 新增 | 脱敏真实帧及明示为合成的测试帧 |
| `tests/TestPianoDetection.py` | 新增，unit | 布局、特征和候选的边界测试 |
| `tests/TestPianoState.py` | 新增，unit | 用虚拟时间验证完整状态转移 |
| `tests/TestPianoTask.py` | 新增，unit | 伪执行器下验证观察模式、输入、OCR、诊断 |
| `tests/TestPianoImages.py` | 新增，image | 同一生产算法的真实样本识别与序列回放 |
| `config.py`、`run_tests.ps1` | 修改 | 任务注册、测试分组；发布时更新版本 |
| `i18n/*/LC_MESSAGES/ok.po`、`ok.mo` | 修改 | 任务名称、描述、配置文字翻译和编译 |
| `更新日志.md`、`docs/程序结构说明.md`、`docs/项目交接与新对话上下文.md` | 修改 | 功能说明、验证边界和发布记录 |

不拆额外通用视觉框架，不改截图后端。布局和检测参数是包内资源；任务从相对模块位置计算项目根目录读取，不能依赖启动时工作目录。布局必须有真实标注才能提交有效值，缺文件、字段错误或版本不匹配均停止任务。

纯模块使用以下接口约定；这里的签名是实施目标，不表示当前已经存在：

```python
KEY_ROWS = ("QWERTYU", "ASDFGHJ", "ZXCVBNM")

# 所有数据记录使用 frozen=True 的 dataclass。
# KeyCell: row:int, index:int, key:str, center:(float,float),
#          roi:(float,float,float,float), dot_radius:float, halo_radius:float
# center/roi 坐标相对整张游戏截图；两种 radius 相对截图高度。
# KeyFeatures: mean_luma, max_luma, warm_ratio, saturation_mean,
#              halo_ring_score, delta_from_base:float|None, shape_ok:bool
# CandidateKey: row:int, index:int, key:str, score:float, features:KeyFeatures
# DetectionResult: status:str, ranked:tuple[CandidateKey,...],
#                  on_keys:frozenset[str], off_keys:frozenset[str],
#                  uncertain_keys:frozenset[str], layout_valid:bool, reason:str
# status: candidate/no_highlight/ambiguous/invalid_roi
# KeyEvent: key:str, row:int, index:int, score:float
# ChordEvent: notes:tuple[KeyEvent,...]，按行列排序；可包含一个或多个键
# StepResult: event:ChordEvent|None, recheck:bool, paused:bool, reason:str

def key_for(row: int, index: int) -> str: ...
def load_layout(path) -> tuple[KeyCell, ...]: ...
def load_parameters(path) -> dict: ...
def project_cells(shape, cells) -> tuple: ...
def normalize(value: float, low: float, high: float) -> float: ...
def score_features(features: KeyFeatures, params: dict) -> float: ...
def choose_keys(candidates, layout_valid: bool, params: dict) -> DetectionResult: ...

class PianoDetector:
    def __init__(self, cells, params): ...
    def reset(self) -> None: ...
    def analyze(self, frame_bgr) -> DetectionResult: ...

class PianoStateMachine:
    def __init__(self, confirm_frames=2, release_frames=2,
                 wait_timeout=1.5, max_sample_gap=0.20): ...
    def reset(self, now: float) -> None: ...
    def step(self, result: DetectionResult, now: float) -> StepResult: ...
```

签名中的省略号仅表示接口声明，实际实现步骤见下文，不将声明原样当成实现。分数、分差均为算法数值，不是统计概率；不要把 `score=0.91` 展示成“91% 可靠”。

## Task 1：样本、布局和场景有效性

**Files:** `assets/piano/layout.json`、`docs/assets/piano-key-layout.md`、`tests/images/piano/manifest.json`、`src/task/piano.py`、`tests/TestPianoDetection.py`。

**Interfaces:** 输入 BGR 帧尺寸及标注；输出 21 个 `KeyCell` 和合法像素检测区域。

- [ ] 登记已提供的 2560×1440 S 参考图；补充无高亮、双键、三键及更多键的人工时序素材，以及独立 1920×1080 同界面图。记录会话、分辨率、游戏 UI 缩放、截图来源；不得自动操作游戏获取。脱敏时保留原始画布尺寸，遮掉钢琴区以外内容，避免破坏比例坐标。
- [ ] 建立标注表。逐键记录行列、字母、中心 `(cx,cy)`、圆点半径 `r` 和外圈最大半径；另记键帽 OCR 框。先按完整 3×7 单元分界，再内缩 20%，检查光晕完整且不包含相邻中心；若文字在框内，用掩模排除文字而非一味缩小整个框。
- [ ] 写布局投影和映射的失败测试，再实现下列核心规则：

```python
def key_for(row, index):
    if not (0 <= row < 3 and 0 <= index < 7):
        raise ValueError("invalid piano key position")
    return KEY_ROWS[row][index]

def normalize(value, low, high):
    if high <= low:
        raise ValueError("invalid normalization range")
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))

# 布局读取时确认映射一一对应、21 个中心唯一且都在各自 ROI 中。
# 运行时校验：
height, width = frame_bgr.shape[:2]
aspect_error = abs((width / height) / (16 / 9) - 1)
layout_valid = aspect_error <= 0.03
# roi 的四个比例按 x*width / y*height 投影，round 后须正面积、全部在界内。
# 越界不静默 clip，返回 invalid_roi；颜色输入统一 uint8 BGR 三通道。
```

- [ ] 添加下列具体断言：`key_for(1,1)=='S'`，全部位置形成 21 个唯一字母；`(-1,0)`、`(3,0)`、`(0,7)` 均抛 `ValueError`；1920×1080、2560×1440 接受，1920×1200 拒绝；3% 边界两侧各测一个尺寸；空图、零面积、缺键、重复键、NaN 比例拒绝。
- [ ] 做钢琴场景结构检查。在标注的各单元中，用圆点内外亮度边界、连通域中心与尺寸检查静态圆点；初始调试规则为至少 18/21 个结构通过且每行至少 5/7 个通过。数值必须用正负样本校准；不要把高亮颜色作为场景存在的唯一依据。阴性样本包括大世界、登录页、菜单和纯色画面。
- [ ] 在两种分辨率输出检测框与圆环叠图，人眼核验 21 个中心。每个中心误差除以对应真实圆点直径均 ≤0.25。真实 1080p 图和从 1440p 缩小的派生图分别记录，后者不能冒充独立实拍适配证据。

**完成标准：** 布局有来源和可审查叠图；全部映射及几何边界测试通过；错场景不进入候选状态。初始人工估读坐标需原图叠加复核后才能标记为已标定。

## Task 2：特征、评分和高亮集合

**Files:** `src/task/piano.py`、`assets/piano/detector.json`、`tests/TestPianoDetection.py`、`tests/TestPianoImages.py`。

**Interfaces:** `PianoDetector.analyze(frame_bgr) -> DetectionResult`；21 项排序结果始终保留，便于状态机查看原键是否熄灭。

- [ ] 先写合成图测试：灰色圆点不亮；S 添加金色圆环时为 `{S}`；两个不同强度且都可靠的圆环输出两个键；三键、跨行和相邻键输出完整集合；白色文字、金色背景不构成高亮。21 键全亮仅作模型边界合成测试。
- [ ] 预计算圆盘、金环、背景掩模。使用独立 `dot_radius` 与 `halo_radius`；本图初始环带半径 35–49px，背景 52–60px（均为 1440p 约值），其他分辨率同比缩放。排除下方键帽矩形和水平谱线像素，形状扇区只在剩余有效像素上计数；不要按白点半径机械推算金环。后续多帧复核动画是否改变环半径。
- [ ] 将钢琴总 ROI 一次性转换为灰度及 HSV，避免对 21 个单元重复转换整屏。OpenCV H 范围是 0–179；初始暖色掩模仅供校准使用：`15<=H<=45`、`S>=70`、`V>=140`。特征实现采用：

```python
gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
warm = ((hsv[..., 0] >= 15) & (hsv[..., 0] <= 45)
        & (hsv[..., 1] >= 70) & (hsv[..., 2] >= 140))
mean_luma = float(gray[signal_mask].mean())
max_luma = float(gray[signal_mask].max())
warm_ratio = float(warm[ring_mask].mean())
saturation_mean = float(hsv[..., 1][signal_mask].mean() / 255.0)
halo_ring_score = max(0.0, float(gray[ring_mask].mean()
                                 - gray[background_mask].mean()))
# 基线取相同掩模下的 mean_luma；仅在已有可靠熄灭基线时计算。
delta_from_base = None if baseline is None else max(0.0, mean_luma - baseline)
```

- [ ] 形状检查要求暖亮像素围绕标注中心分布；将光晕环分成 8 个扇区，初始要求至少 5 个扇区有达到面积门槛的暖亮像素。扇区覆盖、连通域中心偏移和面积范围均用真实高亮、文字、直线和背景样本校准；先确认真实高亮不是局部弧线，以免硬性完整圆环造成漏检。
- [ ] 按原权重 `halo=.30,warm=.25,luma=.20,delta=.15,saturation=.10` 评分。每项采用持久参数中的固定上下界归一化，不能对本帧 21 键做 min-max：否则无高亮画面也会被强制造出满分第一名。`max_luma` 仅用于诊断饱和亮点，不单独决定高亮。
- [ ] 冷启动时 `delta=None`，其余权重除以 0.85 重新归一；所有候选在同一帧使用同一评分模式。21 键基线尚未都可靠时全帧使用静态模式，避免部分键有历史分导致排名偏置。静态候选阶段也必须支持识别首帧已亮的 `S`。
- [ ] 单键连续 3 帧符合熄灭条件且场景有效，才建立该键基线；之后仅在熄灭条件下按 `base=.95*base+.05*current` 更新。场景失效、尺寸变化、暂停重启时清空基线。静态模式和带历史模式分别校准 ON/OFF 阈值。
- [ ] 每键输出 ON/OFF/UNCERTAIN，全部键恰好属于一组。ON 要求分数及形状同时通过；OFF 要求低分且不存在暖色环线索；分数位于迟滞区、形状矛盾或残影无法确定时为 UNCERTAIN。禁止将全画面排名前两名分差用于多键筛选：

```python
on_keys, off_keys, uncertain_keys = set(), set(), set()
for c in candidates:
    if c.features.shape_ok and c.score >= on_threshold:
        on_keys.add(c.key)
    elif c.score <= off_threshold and c.features.warm_ratio <= off_warm_max:
        off_keys.add(c.key)
    else:
        uncertain_keys.add(c.key)
if not layout_valid:
    status = "invalid_roi"
elif uncertain_keys:
    status = "ambiguous"
elif on_keys:
    status = "candidate"
else:
    status = "no_highlight"
```

- [ ] 校准 ON/OFF 阈值及 `off_warm_max`。ON/OFF 探索起点可为 `.65/.40`，暖色 OFF 上界从无高亮样本分布测定；所有起点均未验证。释放阈值小于点亮阈值。若真实非高亮背景落入大量 UNCERTAIN，先修正局部背景特征和掩模，不将它们硬判为 OFF 来提高通过率。

**完成标准：** 静态无基线可识别真实 S；多键输出完整集合；文字、纯亮背景不误输入；固定参数在保留验证会话上复现结果。参数 JSON 记录模式、数值、布局版本与校准样本清单。

## Task 3：时序状态机与重复键

**Files:** `src/task/piano.py`、`tests/TestPianoState.py`。

**Interfaces:** 状态机只接收 `DetectionResult` 和单调时间，返回 `StepResult`，绝不调用真实键盘。生产、观察和回放共用这一实现。

- [ ] 用人工构造的候选记录和虚拟时间先写下表全部测试，不使用真实 `sleep()`。

| 输入序列（每帧间隔默认 50ms） | 预期事件 |
| --- | --- |
| `S` | 无 |
| `S,S` | 一次 `S` |
| `S` 持续 500ms | 总计一次 `S` |
| `S,S,D,D` | `S,D`；D 第二帧可直接完成切换 |
| `S,S,空,S,S` | 仅 `S`，单帧闪灭不能重新触发 |
| `S,S,空,空,S,S` | `S,S`，支持相邻同音重复 |
| `{S,D},{S,D}` | 一个组合事件 `{S,D}` |
| `{Q,S,M},{Q,S,M}` | 一个组合事件 `{Q,S,M}` |
| `{S,D}` 持续 500ms | 只发一次 `{S,D}` |
| `S,S,{S,D},{S,D}` | 先 `{S}`，再 `{D}`，S 不重发 |
| `{S,D},{S,D},D,D,{S,D},{S,D}` | 先 `{S,D}`，再 `{S}`，D 不重发 |
| `S,S,D,D,S,S` | `{S},{D},{S}`，S 经两帧 OFF 才重启 |
| `{S,D},{S,D},S,{S,D},{S,D}` | 仅首个组合，D 单帧消失不重发 |
| `S,不确定,S,S` | 只在最后两帧产生一次 `{S}` |
| `S,D,S,D` | 无 |
| `S` 后相隔超过 200ms 再 `S` | 无，确认计数重置 |
| 已输入 `S` 后原键超过 1.5s 不变化 | 暂停，仍只有一次 `S` |
| 连续 3 帧不确定，复查后持续不确定 | 发一次复查请求，原超时截止时间不变 |
| 高亮期间失去钢琴布局 | 立即禁止输入并复查；过期暂停 |
| `step()` 两次使用相同或倒退时间 | 第二次不累计确认 |

- [ ] 全局使用 `LOCATE_ROI → TRACKING → PAUSED`；`RECHECK_ROI` 为请求。TRACKING 内部每键独立拥有 `on_count/off_count/latched/sent_at`。同轮新确认的键组成一个 `ChordEvent`，不能用整个集合变化就清空全部锁。
- [ ] 在场景有效的观察中，对 ON 键累计 on_count 并清除 off_count，对 OFF 键反向处理，对 UNCERTAIN 键清除两种连续计数但保留锁。OFF 连续 2 帧解除该键锁；ON 连续 2 帧且未锁定才能发出。长采样间隔清除连续计数但保留锁；错误场景不更新熄灭证据。
- [ ] 若任一键 UNCERTAIN，整批暂缓，不发半个和弦；已知键可继续累计确认，但只有本轮没有未决键才发事件。按保守策略，任一未锁定 ON 键还未达到确认帧数时，本轮全部新键等待：例如 `S,{S,D},{S,D}` 输出一次 `{S,D}`。已锁定 S 不阻止后来 D 独立确认。总等待时间仍有上限，不能无限积攒旧候选。
- [ ] 复查后如果画面仍为同一位置，保留已输入键锁；几何布局发生变化时结束本次运行，要求重新启动，避免复位后把持续高亮重发。暂停恢复创建新状态机，需要重新完成两帧确认。
- [ ] 超时使用 `time.monotonic()`。无候选/未决等待从首次未决观察起计；每键等待熄灭从 sent_at 起计，其他键成功不得刷新旧键计时。任一已发送键超过 1.5 秒仍未观察到可靠熄灭则暂停。此值是短按模型的初始参数，真实多键时序若显示更长反馈延迟，须据样本修订，不把长按音符强行当短按。
- [ ] 输入失败后结束任务，不让已发事件被无限自动重试。观察模式把事件视为虚拟已发送，以验证与正式模式相同的去重行为。

核心回放断言示例，`results` 是测试中由 `CandidateKey/DetectionResult` 直接构造的十个 `S` 观察：

```python
machine = PianoStateMachine()
machine.reset(0.0)
events = []
for index, result in enumerate(results):
    step = machine.step(result, (index + 1) * 0.05)
    if step.event is not None:
        events.append(tuple(note.key for note in step.event.notes))
self.assertEqual(events, [("S",)])
```

**完成标准：** 上表逐项通过；重新定位不能清除同键锁后重复发送；计时不因重试永远延长。

## Task 4：任务接入与输入释放

**Files:** `src/task/PianoTask.py`、`config.py`、`tests/TestPianoTask.py`、`run_tests.ps1`。

**Interfaces:** `PianoTask(BaseWWTask)`；算法返回 `ChordEvent`，调用层负责显示或组合发送。

- [ ] 先用 mock 构造执行器：截图从列表返回，时钟可控，按键方法只追加记录。导入及构造测试不得启动 `main.py` 或通过 `run_task()` 连接真实设备。
- [ ] 初始化配置和元数据：

```python
class PianoTask(BaseWWTask):
    navigation_section = "tests"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Piano Highlight Detection"
        self.description = "Start on the piano screen; observe highlights by default."
        self.support_schedule_task = False
        self.default_config.update({
            "Send Keys": False,
            "Sample Interval": 0.05,
            "Confirm Frames": 2,
            "Wait Timeout": 1.5,
            "Key Hold Time": 0.03,
        })
```

- [ ] `validate_config()` 拒绝非法类型、NaN 和越界：采样间隔 0.03–0.08 秒，确认帧数 2–4，等待超时 1–2 秒，按住时间 0.02–0.08 秒。填写对应 `config_description`；阈值和坐标留在校准资源，避免暴露二十多个难以正确调整的界面选项。
- [ ] 循环按以下顺序实现：读取冻结配置 → 加载并校验参数 → `self.next_frame()` → 单调时间检查 → detector → machine → `info_set` → 观察或输入 → `self.sleep()`。帧为 `None` 时直接记录采集失效并结束，不能沿用缓存图。截图尺寸变化清理 detector 并停止本次运行。
- [ ] 50ms 是目标采样间隔而非固定 FPS：扣除本轮处理耗时再等待，处理过慢记录诊断。若取帧超过时序上限则丢弃候选连贯计数；框架自身取帧可能阻塞 6 秒，返回后不补发历史事件。
- [ ] 输入前一次性验证整批非空、无重复、全部行列和白名单一致，再转换小写。同批键依序执行 key_down，全部按下后统一等待，再逐个 key_up；禁止逐键完整 `send_key()` 把和弦串行化。固定行列顺序便于回放，底层投递不是原子操作，记录首末按下时差并由用户实测游戏是否接受。
- [ ] 用列表记录所有“已尝试按下”的键，包含按下接口已投递但抛异常的键。释放函数逐个处理，某键释放异常不能阻止其余键释放；保留失败键给外层再次清理：

```python
def _press_event(self, event, hold_time):
    notes = event.notes
    if not notes or len({n.key for n in notes}) != len(notes):
        raise ValueError("empty or duplicate piano keys")
    if any(key_for(n.row, n.index) != n.key for n in notes):
        raise ValueError("piano key mapping mismatch")
    try:
        for note in notes:
            key = note.key.lower()
            self._pressed_keys.append(key)
            self.send_key_down(key)
        self.sleep(hold_time)
    finally:
        self._release_pressed()

def _release_pressed(self):
    for key in tuple(reversed(self._pressed_keys)):
        try:
            self.send_key_up(key)
        except Exception:
            self.log_warning(f"Piano key release failed: {key}")
        else:
            self._pressed_keys.remove(key)
```

- [ ] `__init__` 初始化 `_pressed_keys=[]`。`run()` 外层 finally 和 `on_destroy()` 再调用释放函数；首次清理后仍有未释放键时必须结束输入循环并执行外层清理，不能继续下一组合。保留原始输入异常；只有释放失败时报告该失败。仅释放本任务登记的键，不扫全键盘。单次调用成功不能证明游戏收到组合键，真实响应仍依赖图像。
- [ ] Mock 验证组合 `{S,D}` 的顺序为 `down(S),down(D),wait,up(D),up(S)`；在第 2/第 3 个 key_down、等待、第一个 key_up、截图和识别阶段分别抛异常。确保所有尝试按下的键均有释放尝试，某键释放失败不跳过其他键，外层重试失败键。观察模式下鼠标、窗口激活、按下和抬起全部为零。
- [ ] 将 `["src.task.PianoTask", "PianoTask"]` 加到 `config.py` 测试功能区；增加四个测试文件到 unit/image 对应分组。检查任务只出现一次、默认发送关闭、没有调度和多账号调用链。

**完成标准：** 用假的截图、时钟和输入器完成一整段曲目事件回放；观察模式完全无输入副作用；中止和异常释放测试通过。

## Task 5：OCR 核对、诊断与翻译

**Files:** `PianoTask.py`、`TestPianoTask.py`、布局说明及 gettext 目录。

**Interfaces:** OCR 使用现有 `self.ocr` 接口并指定本轮帧和标注键帽框；诊断使用任务日志与 `self.screenshot(name=..., frame=cropped)`。

- [ ] 仅在布局有效、同一位置连续 3 帧低置信但有光晕线索时做 OCR 核对；每秒最多一次，仅核对该位置，不因多键增大 OCR 请求。先读取当前框架 ocr 签名确认传帧和 Box 参数，不能让 OCR 自行取另一帧。
- [ ] OCR 输出 strip 后转大写，只接受与 `key_for(row,index)` 完全一致的单字符。`O/0`、`I/1`、多字符、空结果或不匹配均拒绝。正确结果只记录 `label_verified`，不能把 UNCERTAIN 改为 ON，也不生成 ChordEvent。布局失效不触发 OCR。
- [ ] 保存字段：状态及原因、尺寸、布局/参数版本、ROI 比例、ON/OFF/UNCERTAIN 集合、各相关键分数/特征/确认数/锁状态、组合发送时间差、等待时长和截图相对路径。前两名分数可作附加诊断，不再用于接受判断。按事件记录，不逐帧输出全部特征，不记录账号、全屏 OCR 或绝对用户目录。
- [ ] 异常图片只保存钢琴 ROI；若连 ROI 都无法合法裁剪，则只记尺寸和原因。不要回退全屏保存。叠加检测框和分数的诊断图需复制图像后绘制，不能修改正在参与识别的原图。
- [ ] 相同异常原因 5 秒内最多存一帧、每次运行最多 20 帧；首次异常和终止异常保留在此总额内。满额后仅更新计数。写盘失败应保留日志并停止输入，不能使循环反复崩溃重启。
- [ ] 说明截图经现有诊断管道可能自动上传，遵守既有策略而不新增上传实现。通过 mock 检查送给 `screenshot` 的确是裁剪图，且保存频率和数量有界。
- [ ] 实施时使用项目 `ok-script-i18n` 工作流，为任务名称、描述及 5 个配置字段同步现有语言目录并编译 `.mo`；不改持久化英文配置键。初版只承诺已由素材验证的界面语言，文档明确范围。

**完成标准：** OCR 无法绕过视觉门槛；错误场景没有全屏泄露；异常存图限流；任务界面配置可读。

## Task 6：离线验收、性能测量与发布

**Files:** `tests/images/piano/manifest.json`、`TestPianoImages.py`、`run_tests.ps1`、版本及说明文档。

- [ ] manifest 每帧记录 `file,width,height,session_id,split,expected_status,expected_keys,synthetic`；expected_keys 为排序字母列表，单键也用列表。回放记录有序 `file,t_ms` 和 expected_events（按时间排列的按键集合）。静态标签与事件标签分别保存。
- [ ] 最小功能集覆盖 21 个单键、无高亮、强弱不同的双高亮、动画过渡、亮度变化、错误界面以及两种分辨率。它只能证明覆盖，不能由 21 张图就宣称有统计意义的 99% 准确率。
- [ ] 建议独立验证集至少 420 张真实单键帧（每键每种分辨率至少 10 张），另准备至少 100 张多键正样本，覆盖 2/3/更多键、同排、跨排、相邻、不同亮度；至少 100 张负样本及过渡帧。按采集会话隔离校准与验证；缩放增强和同一连续片段归同一 split。
- [ ] 单键准确率和多键集合完全匹配率分别要求 ≥99%；拒识计入未正确识别。多键缺一个、多一个均是集合错误，不能靠 21 个位置中多数 OFF 抬高准确率；同时报告逐键 precision/recall 和按键数量分层结果。负样本/真正未决样本事件为零，可靠多键必须产生正确组合。所有比例仅描述已测数据。
- [ ] 回放要求 expected_events 完全一致：无多发、错发、和弦漏键；持续 500ms 的同一组合只发一次；组合增减只触发新增或经确认熄灭后重新亮起的键；先后差一帧的组合、上一音残影与新音重叠分别测试。真实序列必须有时间戳；静态图和人工拼接多键不能代替真实时序验证。
- [ ] 测量真实分辨率下 detector 的 p50/p95 耗时、全循环观察间隔及一次性内存。初步预算为算法 p95≤20ms，50ms 采样下两次确认通常在首次检测后约一个采样间隔完成；这些是待测工程目标，不包括截图阻塞和游戏响应保证。若不达标，先检查是否整屏重复转换及掩模重复创建，不新增推理模型。
- [ ] 用本地虚拟环境逐文件运行。实施初期对新增行为先运行确认失败，完成后重复同一命令确认通过：

```powershell
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestPianoDetection.py --timeout 180
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestPianoState.py --timeout 180
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestPianoTask.py --timeout 180
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestPianoImages.py --timeout 180
.\.venv\Scripts\python.exe scripts/run_test_file.py tests/TestTestGroups.py --timeout 180
.\run_tests.ps1 -Group all
```

- [ ] 缺少钢琴真实样本时图像验收应明确失败或显示“未验收”，不能通过无条件 skip 把项目写成已完成。普通纯算法测试可以使用合成图继续推进。
- [ ] 文档列出：用户手动打开钢琴界面；默认观察；发送开关含义；异常返回后手动重启；支持同批组合短按。暂不支持非 16:9 自动裁剪、遮挡恢复、节奏预测及按住到结束的长按音符。游戏实际支持的组合数量和按下时间差另由用户实测，不由模型 21 键容量推断。
- [ ] 按执行当时版本决定中等功能变更的下一版本。若仍为 `1.39.00`，则新版本为 `1.40.00`；同步 `更新日志.md`、结构说明和交接，标明离线通过/用户实机待验证。分步可做本地检查点，最终发布只创建一个匹配产品版本的注解标签。
- [ ] 发布前读取项目 deploy 技能并遵循当前发布流程。先检查 `git status --short`、`git diff --check`、`git diff --stat`，只暂存本功能明确文件。不得使用 `git add -A` 带入用户既有的 11 个历史审查文档删除。
- [ ] 若实际版本为 `1.40.00`，运行以下版本校验；其他版本替换为 `config.py` 中的准确值。验证后提交、创建同名注解标签并推送分支和标签，不覆盖已有标签：

```powershell
.\.venv\Scripts\python.exe scripts/validate_release.py --tag v1.40.00
```

- [ ] 分别记录本地测试、提交/标签推送、CI、Release 产物和用户实机结果。推送完成不能写作实机通过。本阶段不启动游戏验证；用户之后手动测试所得反馈单独记录。

**完成标准：** 代码、数据、配置、翻译、分组和版本一致；真实样本指标及事件回放达标；未覆盖项显式保留，不将理论指标写成测试结果。

## 3. 执行顺序与审核节点

1. 用已提供原图复核本文件初始布局，产出 21 键叠图；状态机可先使用合成结果覆盖多键序列。
2. 完成任务 2，展示 S 和多键样本各位置的 ON/OFF/UNCERTAIN 结果；可靠多键未验证前不宣称和弦已验收。
3. 完成任务 3，锁定组合增减、持续亮、单帧闪灭、同音重入及超时行为。
4. 完成任务 4 和任务 5，用 mock 贯通观察、输入释放、OCR 和诊断；完成任务注册与翻译。
5. 完成任务 6 的独立真实数据评估、回放、全量回归和发布记录。若真实数据不足，交付进度注明“实现/合成测试完成，真实图像验收未完成”。

需求对应：比例坐标和缩放→任务 1；六项特征及多键集合→任务 2；逐键确认和去重→任务 3；组合输入及全部释放→任务 4；OCR/异常证据→任务 5；集合准确率、时序、跨分辨率→任务 6。

## 4. `1.40.00` 实施状态

已实现 `src/task/piano.py` 的 21 键比例布局、金环相对背景亮度差检测、钢琴圆点阵列门禁、ON/OFF/UNCERTAIN 判定和逐键两帧确认；`PianoTeachingTask` 已注册到测试功能，可把同批新音符一起按下并逆序释放。任务仅支持简体中文和 16:9，用户手动进入界面、启动及停止。异常诊断只保存钢琴裁剪区。

实现采用 ponytail 原则收敛了首版范围：固定位置已经能确定字母，因此没有加入 OCR；单张参考图能够稳定区分 S，无需先引入历史基线、JSON 参数层或新的视觉框架。新增合成单键/多键、逐键去重、长帧间隔和异常释放测试；原始 1440p 参考图及其等比 1080p 图均只识别到 S。全量回归为 91 个测试文件、903 项用例，895 通过、8 项原有跳过。

尚未具备用户真实多键连续帧和独立 1080p 实拍素材，因此真实和弦时序、UI 缩放变化、长按音符和统计准确率仍属实机验收项。用户补充的多键要求取代原设计中与之冲突的单键条款。
