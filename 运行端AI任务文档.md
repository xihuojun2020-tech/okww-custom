# 运行端 AI 任务文档：多账号每日任务「退登后卡死」证据采集与验证

> 面向：运行端（okww 使用端机器）上的 AI 助手
> 文档版本：2026-08-18 v3（开发端提供）
> 目标版本：okww-custom（当前应已更新到 **v1.06.00**）

---

## 0. 背景（你不需要重新排查，照做即可）

多账号每日任务在「完成第一个账号 → 退登 → 等登录界面」环节**偶发卡死**（60 秒找不到账号下拉框后任务异常终止）。

**开发端已确认的根因（机制层面）**：
- 游戏的**登录账号下拉框不在游戏主窗口（UnrealWindow）里**，而在 `Client-Win64-Shipping.exe` 的**另一个独立顶层窗口**中（OBS 里显示为【client-win64-shipping.exe】:(null)，类名可能是 `CNativeLoginDlg / CLoginDlg_P_ / CefBrowserWindow` 之一）；
- okww 的截图管线（WGC/BitBlt）**只捕获主窗口**，从不捕获这个登录对话框窗口 → OCR 永远看不到账号下拉框 → 超时卡死；
- v1.03.71 已做抗闪烁加固（两阶段等待、窗口恢复前台、日志），但**捕获目标没变，所以根因还在**。v1.03.72 将修复捕获目标（登录识别时回退捕获登录对话框窗口）。

**你的任务**：① 用探针拿到决定性证据，证明「账号下拉框在独立窗口」；② 确认 okww 内部 `top_hwnd` 是否指向该窗口；③ 后续更新到 v1.03.72 后复测。

---

## 1. 任务 A：运行探针，采集登录窗口证据（必须先做）

### A1. 准备
- 确认当前版本：`working\config.py` 第 16 行应为 `version = "1.03.71"`；
- 确认探针存在：`working\probe_login_window.py`（若缺失，向开发端要，或按附录 A 重建）。

### A2. 触发场景
1. 启动 okww（游戏已登录、在大世界）；
2. 运行「👥 多账号每日任务」；
3. 等它完成第一个账号的每日任务、自动退登到登录界面；
4. **如果卡住（60s+ 无反应）→ 正是我们要的时刻**；
5. 若没卡住（正常到登录界面），也请在**登录界面停留期间**执行 A3（同样有证据价值）。

### A3. 执行探针
在 okww 卡住/停在登录界面时，打开 PowerShell 运行（用 okww 自带的 python）：
```powershell
cd "E:\game\okww owener\data\apps\okww-custom\working"
runtime\python\python.exe probe_login_window.py
```
（若运行端路径不同，用对应的 `working` 目录。）

### A4. 探针会输出
1. `Client-Win64-Shipping.exe` 的所有顶层窗口：`hwnd / 类名 / 标题 / 可见性 / 矩形`；
2. 每个可见窗口的截图，保存在 `working\probe_login_out\` 目录（如 `hwnd_12345_CNativeLoginDlg.png`）；
3. 判断标准打印在末尾。

### A5. 用你自己的视觉能力读图并报告
**请用你的看图能力（modlens / codex / 直接读图）逐一查看 `probe_login_out\` 里的截图**，回答：
1. **账号下拉框（形如 `180****1088` 的掩码账号、或扫码 U 账号、或「登录」按钮）出现在哪张截图里？** 该截图的窗口类名是什么（文件名里有）？
2. 游戏主窗口（`UnrealWindow`）的截图里**有没有**登录选项？
3. 如果有多个窗口截图，描述每个窗口大概是什么界面（登录对话框 / 主菜单 / 加载画面 / 启动器等）。

### A6. 报告给开发端的内容（文本即可）
```
- 当前版本：v1.03.71
- 是否卡死：是/否
- 窗口列表（探针输出的完整列表）
- 每张截图的窗口类名 + 一句话内容描述
- 关键结论：账号下拉框在哪个窗口（类名）？主窗口截图是否包含登录选项？
- 截图文件路径清单
```

---

## 2. 任务 B：确认 okww 运行时的 top_hwnd（只读，不侵入）

登录界面期间，在另一个 PowerShell 里运行以下命令，查看 okww 进程日志中是否有窗口信息，**或**用只读方式读取：
```powershell
# 方式1：看 okww 日志里有没有 hwnd/top 相关信息（找到即可）
Select-String -Path "logs\ok-ww.log","logs\ok-script.log" -Pattern "top_hwnd|hwnd changed|do_update_window_size hwnd" | Select-Object -Last 20
```
- 若日志显示 `hwnd changed from X to Y top Z` 之类的行，**记录 Z 是什么**（对照任务 A 的窗口列表）；
- 若日志没有，跳过即可（不强制），把任务 A 的证据发回更重要。

> ⚠️ 不要修改/注入 okww 运行中的进程，只做只读检查。

---

## 3. 任务 C：更新到 v1.03.72 并复测（等开发端发布后执行）

开发端确认证据、修复并发布 v1.03.72 后，运行端执行：

### C1. 更新
1. 通过 okww/PyAppify 的更新流程拉取 v1.03.72（或按开发端给出的同步方式）；
2. 确认 `working\config.py` 版本为 `1.03.72`；
3. 确认 `working\src\task\MultiAccountDailyTask.py` 里出现**新的登录窗口捕获逻辑**（如函数名含 `top_hwnd` 或 `login_window` 相关的捕获回退，具体以开发端说明为准）。

### C2. 复测
1. 重启 okww，运行「👥 多账号每日任务」；
2. 观察是否仍卡死；重点看日志：
   - 退登四步骤日志；
   - `等待登录界面（宽松探测…）`；
   - 若新增了「登录窗口捕获」相关日志（如 `捕获登录对话框窗口 top_hwnd=...`），**原样记录**；
3. **连续跑 2~3 轮**（多账号任务本身会循环多个账号），确认不再出现 60s 超时；
4. 若仍有问题，把**最新日志尾部 + 卡死时刻截图**发回开发端（截图路径 `screenshots\` 里带时间戳的文件）。

### C3. 报告
```
- v1.03.72 复测结果：通过/仍失败
- 跑了几个账号：A1~A?
- 每轮退登到登录界面耗时（大致）
- 新日志片段（登录窗口捕获相关）
- 若失败：卡死时刻截图路径 + 日志尾部
```

---

## 4. 任务 D：更新到 v1.03.74 并复测（当前任务，最重要）

> v1.03.73 复测结论：登录界面识别已通过，但卡在 `click drop down no effect` ×5（账号列表其实已展开，被误判为点击无效）。v1.03.74 已修复该误判 + 修复「多账号↔每日任务方案联动」（此前联动 A4 却执行 A3）。

### D1. 更新
1. 通过 okww/PyAppify 更新流程拉取 **v1.03.74**（或按开发端给出的同步方式：部署 repo/working + app.json 已同步）；
2. 确认 `working\config.py` 版本为 `1.03.74`；
3. 确认 `working\src\task\MultiAccountDailyTask.py` 里出现 `_account_list_expanded`、`_link_daily_profile` 两个新函数（v1.03.74 标志）。

### D2. 复测（重点：完整跑通 2~3 个账号，全程无卡死）
1. 重启 okww 一次（让 `_sync_custom_ok` 把 custom_ok 框架覆盖同步进 site-packages）；
2. 打开多账号任务配置，确认「当前序列/账号」是你想要的（序列1 A 系列）；
3. 运行「👥 多账号每日任务」，观察完整链路：
   - 主界面分支 → 联动日志：`每日任务方案已联动到 X` **且紧接着** `DailyTask:开始执行每日任务（账号：X）` **两处 X 必须一致**（这是 v1.03.74 修复的联动，旧版会联动 A4 却执行 A3）；
   - 退登四步骤 → `等待登录界面` → `已返回登录界面`；
   - **点下拉框 → 列表展开 → 选中目标账号 → 点登录**（不再出现 `click drop down no effect`）；
   - 每完成一个账号继续下一个，**连续 2~3 个账号**全通过即算通过；
4. 重点采集日志关键词：`每日任务方案已联动到`、`开始执行每日任务（账号：`、`账号列表已展开`、`click drop down no effect`（**应不再出现**）、`Timed out waiting for the login screen`（**应不再出现**）；
5. 若仍失败：发回 **最新日志尾部 + 卡死时刻截图**（`screenshots\` 带时间戳文件）。

### D3. 报告
```
- v1.03.74 复测结果：通过 / 仍失败
- 跑了几个账号：A1~A?（每轮联动方案是否与执行账号一致：X→X）
- 每轮退登→登录→选号→进游戏耗时（大致）
- 关键日志片段（联动两行 / 展开检测 / 是否有 no effect）
- 若失败：卡死时刻截图路径 + 日志尾部
```

---

## 5. 任务 E：更新到 v1.05.01 并运行连续账号切换测试（当前任务）

### E1. 更新
1. 通过 GitHub/PyAppify 更新到 **v1.05.01**；
2. 确认 `working\config.py` 为 `version = "1.05.01"`；
3. 确认「🔄 账号切换测试」中出现「测试模式」与「连续账号顺序」。

### E2. 运行（仅测试切换，不运行每日任务）
1. 测试模式选择「连续序列切换」；
2. 连续账号顺序保持默认 `A1,A3,A4`，测试轮数先选 `1`；
3. 从主界面启动也可以，任务会先退登；随后应严格按 `A1 → A3 → A4` 登录；
4. 每次账号登录成功后，任务只模拟「每日任务已完成」，退登并选择下一个账号，不执行任何每日任务，也不写入完成进度；
5. A1 可能以备用名显示，A3/A4 可能以手机号掩码显示，两种识别方式都应命中各自目标；
6. 若当前显示账号与目标不一致，应先看到稳定检测与“重新选择”日志，而不是第一次不一致就停止；目标账号连续识别两次后才确认。
7. 程序应优先捕获 `ComboLBox` 下拉列表并对目标 OCR 框执行系统鼠标点击；只有无法获得安全屏幕坐标时才回退 PostMessage。任何点击方式都不能依赖固定行号或绕过登录前账号核对。
8. 日志应区分“已发送账号点击”与“确认已选择账号”，并记录点击方式、目标 HWND/窗口类和坐标；只有多次重试仍不一致时才会为防误登停止。
9. 额外从 A4 游戏主界面启动一次：任务应先退登识别真实 A4，联动 A4 方案后才执行其每日任务，不得直接按序列下一项的方案运行。
10. 在退登、等待登录界面或选号期间点击停止；确认后续日志不再出现 OCR、置前、选号或登录操作。
11. 选中 A3/A4 后若首次点击登录没有跳转，日志应显示下一次改用“系统屏幕”点击，并且每次都重新 OCR 当前登录按钮，不得重用旧坐标。
12. 退登确认框仍在时应直接重点确认，不得发送 ESC；进入加载态后可等待最多 45 秒，期间不应盲点或重复抢占前台。

### E3. 报告
```text
- v1.05.01 连续测试结果：通过 / 仍失败
- 实际切换顺序：A1 → A3 → A4 / 其他
- 是否发生重新选择：否 / 是（第几个账号）
- 是否误执行每日任务或写入完成进度：否 / 是
- 若失败：脱敏后的关键日志 + 截图路径
```

---

## 6. 注意事项
- **只读/采集为主，不要改代码、不要改配置**（修复由开发端出）；
- 探针是独立脚本，不影响 okww 运行；
- 截图/日志不要外传（含账号信息），只发给开发端；
- 如果游戏当时没卡死（正常到了登录界面），A3 照做——正常态的窗口列表同样能验证「登录对话框是独立窗口」。

---

## 附录 A：probe_login_window.py（若缺失，运行端自己创建）
```python
# 探针：列出 Client-Win64-Shipping.exe 的顶层窗口并截图（见任务 A）
import os, win32gui, win32ui, win32con
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_login_out")
os.makedirs(OUT, exist_ok=True)
def exe_of(hwnd):
    try:
        import win32process, psutil
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        return psutil.Process(pid).name()
    except Exception:
        return None
def shot(hwnd, path):
    try:
        l,t,r,b = win32gui.GetWindowRect(hwnd); w,h = r-l, b-t
        if w<=0 or h<=0: return False
        dc = win32gui.GetWindowDC(hwnd); mfc = win32ui.CreateDCFromHandle(dc)
        sdc = mfc.CreateCompatibleDC(); bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc, w, h); sdc.SelectObject(bmp)
        sdc.BitBlt((0,0),(w,h),mfc,(0,0),win32con.SRCCOPY)
        bmp.SaveBitmapFile(sdc, path); sdc.DeleteDC(); mfc.DeleteDC()
        win32gui.ReleaseDC(hwnd, dc); return True
    except Exception:
        return False
found = []
def cb(hwnd, _):
    try:
        if exe_of(hwnd) and exe_of(hwnd).lower() == "client-win64-shipping.exe":
            found.append((hwnd, win32gui.GetClassName(hwnd), win32gui.GetWindowText(hwnd),
                          win32gui.IsWindowVisible(hwnd), win32gui.GetWindowRect(hwnd)))
    except Exception:
        pass
    return True
win32gui.EnumWindows(cb, None)
print(f"找到 {len(found)} 个顶层窗口：")
for hwnd, cls, title, vis, rect in found:
    print(f"  hwnd={hwnd} 类={cls!r} 标题={title!r} 可见={vis} rect={rect}")
    if vis and cls not in ("ComboBox","ComboLBox","Button","Static"):
        p = os.path.join(OUT, f"hwnd_{hwnd}_{cls}.png")
        print(f"    截图: {p}") if shot(hwnd, p) else None
print(f"输出目录: {OUT}")
```

---

## 7. 账号总配置完整性（v1.06.00）

账号稳定意图现在由 `configs/account_master_config.json` 提供。主程序只读该文件，
不会自动创建、迁移、修复或把当前界面配置写回总配置；旧的
`configs/daily_profiles.json` 仅作为兼容工作副本。请先备份整个 `configs` 文件夹。

首次升级或想新增账号时：

1. 复制 `config_templates/account_master_config.template.json` 到临时位置，根据现有账号手工生成候选文件；每个账号使用新的 UUID `profile_id`，序列只引用 UUID。每个 `task_config` 必须完整包含当前 DailyTask 受保护键（刷取目标、材料、梦魇/残象、每周乐园、融合和备用识别名称）；`RECORD_*` 与 `Logout PC After Daily Task` 是全局/运行字段，不放入账号配置。首次迁移时，`display_name`/`account_aliases`/备用识别名称必须覆盖旧方案的短名（如 A1、A10）、完整手机号对应的掩码手机号和 U 名；否则旧工作副本会保持差异并阻断启动。
2. 只读验证候选文件：源码环境使用 `.venv\Scripts\python.exe scripts\validate_account_master_config.py <候选文件.json>`；部署目录使用 `runtime\python\python.exe scripts\validate_account_master_config.py <候选文件.json>`。验证命令只输出错误/指纹，不会写文件。
3. 用户确认无误后，在主程序外把候选文件人工放入 `configs\account_master_config.json`，重新启动。
4. 若工作副本存在差异，先点击“已知晓并查看差异”，再确认总配置修改，最后选择“按照总配置恢复工作配置（推荐）”。“已知晓”本身不会解锁任何自动任务；关闭对话框或选择手工处理会继续保持安全模式。

完整性事件证据保存在 `config_integrity_incidents\`，重复差异会复用同一待处理目录。
不要删除事件、旧工作副本或运行状态；恢复前服务会自动备份工作副本。完成时间、游标和断点只写入 `account_runtime_state.json`，不会覆盖账号方案。

运行端 AI 严禁：删除旧配置、把工作副本设为总配置、自动点击“确认总配置修改”、在差异未解决时绕过门禁继续任务，或输出密码、PAT、鉴权 URL 等敏感令牌。需要把当前工作配置作为新标准时，退出程序后由用户在文件夹中手工编辑总配置，再重新验证。
