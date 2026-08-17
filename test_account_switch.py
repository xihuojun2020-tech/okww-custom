# -*- coding: utf-8 -*-
"""单独测试账号切换功能（v1.04.0 验证脚本）。

用法：
    # 基本用法：展开账号列表，交互选择目标并完成切换验证
    python test_account_switch.py

    # 指定目标账号，完整测试切换（选号 + 点登录）
    python test_account_switch.py --target A3

    # 循环 N 轮（测试多账号连续切换稳定性）
    python test_account_switch.py --target A3 --rounds 3

    # 仅诊断模式：检测登录界面 + 打印 OCR 结果，不做任何点击操作
    python test_account_switch.py --diag

前置条件：
    1. 游戏已启动并在登录界面（退登后 / 手动退登到登录界面均可）；
    2. okww 已安装 venv 依赖（win32gui / win32ui / numpy / onnxocr）。
"""
import argparse
import os
import re
import sys
import time

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ========================= 独立运行模式（无需 okww 框架） =========================

def _find_game_hwnd():
    """找到 Client-Win64-Shipping.exe 的主窗口 hwnd 和所有顶层窗口。"""
    import win32gui
    import win32process
    import psutil

    EXE = "client-win64-shipping.exe"
    main_hwnd = None
    all_hwnds = []

    def cb(hwnd, _):
        nonlocal main_hwnd
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            exe = psutil.Process(pid).name().lower()
            if exe == EXE:
                cls = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                visible = win32gui.IsWindowVisible(hwnd)
                rect = win32gui.GetWindowRect(hwnd)
                all_hwnds.append({
                    'hwnd': hwnd, 'class': cls, 'title': title,
                    'visible': visible, 'rect': rect,
                })
                if cls == 'UnrealWindow' and main_hwnd is None:
                    main_hwnd = hwnd
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return main_hwnd, all_hwnds


def _capture_hwnd(hwnd):
    """BitBlt 捕获窗口 → numpy BGR 数组 + (left, top) 原点。"""
    import win32gui
    import win32ui
    import win32con
    import numpy as np

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return None, None
    dc = None
    mfc = None
    sdc = None
    bmp = None
    try:
        dc = win32gui.GetWindowDC(hwnd)
        mfc = win32ui.CreateDCFromHandle(dc)
        sdc = mfc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc, w, h)
        sdc.SelectObject(bmp)
        sdc.BitBlt((0, 0), (w, h), mfc, (0, 0), win32con.SRCCOPY)
        bits = bmp.GetBitmapBits(True)
        frame = np.frombuffer(bits, np.uint8).reshape(h, w, 4)
        import cv2
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), (left, top)
    except Exception:
        return None, None
    finally:
        try:
            if sdc is not None:
                sdc.DeleteDC()
            if mfc is not None:
                mfc.DeleteDC()
            if bmp is not None:
                win32gui.DeleteObject(bmp.GetHandle())
            if dc is not None:
                win32gui.ReleaseDC(hwnd, dc)
        except Exception:
            pass


def _find_dialog_hwnd(main_hwnd, game_hwnds):
    """找可见的 #32770 登录对话框。"""
    import win32gui

    EXE = "client-win64-shipping.exe"
    candidates = []
    for w in game_hwnds:
        if not w['visible']:
            continue
        if w['class'] != '#32770':
            continue
        rect = w['rect']
        area = (rect[2] - rect[0]) * (rect[3] - rect[1])
        if area <= 0:
            continue
        candidates.append((w['hwnd'], rect, area))

    # 排除全屏背景（面积 ≈ 屏幕面积）
    if candidates:
        candidates.sort(key=lambda x: x[2])
        best = candidates[0]
        return best[0], best[1]
    return None, None


def _find_control_hwnd(class_name, game_hwnds):
    """找指定类名的可见控件。"""
    import win32gui

    results = []
    for w in game_hwnds:
        if not w['visible']:
            continue
        if w['class'] != class_name:
            continue
        rect = w['rect']
        w_size = rect[2] - rect[0]
        h_size = rect[3] - rect[1]
        if w_size <= 0 or h_size <= 0:
            continue
        results.append((w['hwnd'], rect, w_size * h_size))

    if results:
        results.sort(key=lambda x: x[2], reverse=True)  # 面积最大的
        return results[0][0], results[0][1]
    return None, None


# ========================= OCR 集成（使用 okww onnxocr） =========================

def _init_ocr():
    """初始化 onnxocr 引擎（轻量级，不需要完整框架）。"""
    try:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        ocr_engine = ONNXPaddleOcr(show_log=False)
        return ocr_engine
    except Exception as e:
        print(f"[WARN] onnxocr 初始化失败: {e}")
        print("       请确认已安装 onnxocr: pip install onnxocr")
        return None


def _ocr_frame(ocr_engine, frame):
    """用 onnxocr 对帧进行 OCR，返回 [(text, confidence, (cx, cy)), ...]"""
    if ocr_engine is None or frame is None:
        return []
    import numpy as np
    results = []
    try:
        ocr_result = ocr_engine.ocr(frame, cls=True)
        if ocr_result and ocr_result[0]:
            for line in ocr_result[0]:
                box_points, (text, conf) = line
                # box_points 是 4 个角点 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                xs = [p[0] for p in box_points]
                ys = [p[1] for p in box_points]
                cx = int((min(xs) + max(xs)) / 2)
                cy = int((min(ys) + max(ys)) / 2)
                results.append({
                    'text': text.strip(),
                    'confidence': conf,
                    'center': (cx, cy),
                    'box': box_points,
                })
    except Exception as e:
        print(f"[WARN] OCR 失败: {e}")
    return results


# ========================= 账号匹配逻辑 =========================

ACCOUNT_PATTERN = re.compile(r'\*\*\*\*')
SCAN_ACCOUNT_PATTERN = re.compile(r'^U[a-zA-Z0-9]+$', re.IGNORECASE)
LOGIN_TEXTS = ('登录', '登入', 'Log')
# 方案简称提取：【A1-溅青-13097291243】 → A1
_SHORT_NAME_RE = re.compile(r'【([A-Z]\d+)[-.]')


def _short_name(profile_name):
    """从方案全名提取简称（如 A1、B7）。"""
    if not profile_name:
        return None
    m = _SHORT_NAME_RE.search(profile_name)
    return m.group(1) if m else profile_name


def _is_account_text(text):
    """判断文本是否为账号条目（掩码或 U 扫码）。"""
    if not text:
        return False
    return bool(ACCOUNT_PATTERN.search(text) or SCAN_ACCOUNT_PATTERN.match(text))


def _is_login_text(text):
    """判断文本是否为登录按钮文字。"""
    return text.strip() in LOGIN_TEXTS


def _count_account_entries(ocr_results):
    """统计账号条目数量。"""
    return sum(1 for r in ocr_results if _is_account_text(r['text']))


def _has_login_text(ocr_results):
    """是否有登录/Log/登入 文本。"""
    return any(_is_login_text(r['text']) for r in ocr_results)


# ========================= 主测试逻辑 =========================

def _screen_click(x, y):
    """系统级鼠标点击屏幕坐标 (x, y)。"""
    import win32api
    import win32con
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.1)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def _box_center_screen(box_points, origin):
    """把 OCR 框中心换算为屏幕坐标。"""
    xs = [p[0] for p in box_points]
    ys = [p[1] for p in box_points]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return int(origin[0] + cx), int(origin[1] + cy)


def _account_matches_alias(account_text, aliases):
    """账号 OCR 文本是否属于目标方案。"""
    name = (account_text or '').strip()
    return name in aliases or any(alias in name for alias in aliases if len(alias) >= 4)


def _capture_account_list(dlg_hwnd, ocr_engine):
    """捕获展开的 ComboLBox；不存在时回退到登录对话框。"""
    _main_hwnd, game_hwnds = _find_game_hwnd()
    list_hwnd, _list_rect = _find_control_hwnd('ComboLBox', game_hwnds)
    source_is_list = bool(list_hwnd)
    frame, origin = _capture_hwnd(list_hwnd if list_hwnd else dlg_hwnd)
    ocr_results = _ocr_frame(ocr_engine, frame) if frame is not None else []
    return frame, origin, ocr_results, game_hwnds, source_is_list


def _wait_for_account_list(dlg_hwnd, ocr_engine, timeout=10):
    """等待独立 ComboLBox 或内嵌账号列表出现。"""
    deadline = time.monotonic() + timeout
    last = (None, None, [], [], False)
    while time.monotonic() < deadline:
        last = _capture_account_list(dlg_hwnd, ocr_engine)
        frame, origin, ocr_results, game_hwnds, source_is_list = last
        entry_count = _count_account_entries(ocr_results)
        if (source_is_list and entry_count >= 1) or entry_count >= 2:
            return frame, origin, ocr_results, game_hwnds
        time.sleep(1)
    return None


def _selected_target_from_dialog(dlg_hwnd, ocr_engine, target_aliases):
    """核对下拉框收起后当前显示的账号是否为目标。"""
    frame, origin = _capture_hwnd(dlg_hwnd)
    if frame is None:
        return False, [], frame, origin
    ocr_results = _ocr_frame(ocr_engine, frame)
    displayed = [r['text'].strip() for r in ocr_results if _is_account_text(r['text'])]
    matched = any(_account_matches_alias(name, target_aliases) for name in displayed)
    return matched, displayed, frame, origin


def _wait_for_login_completion(timeout=180, stable_seconds=5):
    """等待登录对话框持续消失且游戏主窗口可见，避免点击后立即假报成功。"""
    deadline = time.monotonic() + timeout
    stable_since = None
    while time.monotonic() < deadline:
        main_hwnd, game_hwnds = _find_game_hwnd()
        dlg_hwnd, _dlg_rect = _find_dialog_hwnd(main_hwnd, game_hwnds)
        main_visible = any(
            w['hwnd'] == main_hwnd and w['visible']
            and w['rect'][2] > w['rect'][0] and w['rect'][3] > w['rect'][1]
            for w in game_hwnds
        )
        if main_hwnd and main_visible and not dlg_hwnd:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_seconds:
                return True
        else:
            stable_since = None
        time.sleep(1)
    return False


def _wait_for_login_dialog(timeout=120):
    """等待登录对话框重新出现并返回最新窗口句柄。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        main_hwnd, game_hwnds = _find_game_hwnd()
        if main_hwnd:
            dlg_hwnd, dlg_rect = _find_dialog_hwnd(main_hwnd, game_hwnds)
            if dlg_hwnd:
                combo_hwnd, combo_rect = _find_control_hwnd('ComboBox', game_hwnds)
                return main_hwnd, game_hwnds, dlg_hwnd, dlg_rect, combo_hwnd, combo_rect
        time.sleep(1)
    return None


def run_test(target=None, rounds=1, diag_only=False, save_screenshots=True):
    """执行账号切换测试。

    Args:
        target: 目标账号方案名（如 'A3'）。None = 交互选择。
        rounds: 测试轮数（每次从登录界面开始，切换到 target 并登录）。
        diag_only: True = 仅诊断（检测登录界面 + 打印 OCR），不做点击。
        save_screenshots: 是否保存诊断截图到 test_out/ 目录。
    """
    if rounds < 1:
        print("  ✗ 测试轮数必须大于等于 1")
        return False

    print("=" * 70)
    print("  账号切换功能测试（v1.04.0）")
    if target:
        print(f"  目标账号: {target}  |  轮数: {rounds}")
    elif diag_only:
        print("  模式: 诊断（仅检测登录界面，不做点击操作）")
    else:
        print("  模式: 交互选择目标账号")
    print("=" * 70)

    # 1) 找游戏进程
    print("\n[1/6] 查找游戏进程...")
    main_hwnd, game_hwnds = _find_game_hwnd()
    if not main_hwnd:
        print("  ✗ 未找到 Client-Win64-Shipping.exe 主窗口（游戏未启动？）")
        return False
    print(f"  ✓ 主窗口 hwnd={main_hwnd}，共 {len(game_hwnds)} 个顶层窗口")

    # 2) 找 #32770 登录对话框
    print("\n[2/6] 查找登录对话框...")
    dlg_hwnd, dlg_rect = _find_dialog_hwnd(main_hwnd, game_hwnds)
    if not dlg_hwnd:
        print("  ✗ 未找到 #32770 登录对话框（不在登录界面？）")
        print("  提示：请先退登到登录界面再运行本测试")
        return False
    dlg_w = dlg_rect[2] - dlg_rect[0]
    dlg_h = dlg_rect[3] - dlg_rect[1]
    print(f"  ✓ 登录对话框 hwnd={dlg_hwnd} size={dlg_w}×{dlg_h} rect={dlg_rect}")

    # 3) 找控件
    print("\n[3/6] 查找登录控件...")
    combo_hwnd, combo_rect = _find_control_hwnd('ComboBox', game_hwnds)
    combolbox_hwnd, combolbox_rect = _find_control_hwnd('ComboLBox', game_hwnds)

    if combo_hwnd:
        cw = combo_rect[2] - combo_rect[0]
        ch = combo_rect[3] - combo_rect[1]
        print(f"  ✓ ComboBox hwnd={combo_hwnd} size={cw}×{ch} rect={combo_rect}")
    else:
        print("  ✗ 未找到 ComboBox")

    if combolbox_hwnd:
        cbw = combolbox_rect[2] - combolbox_rect[0]
        cbh = combolbox_rect[3] - combolbox_rect[1]
        print(f"  ✓ ComboLBox hwnd={combolbox_hwnd} size={cbw}×{cbh} rect={combolbox_rect}")
        print(f"    可见: {win32gui.IsWindowVisible(combolbox_hwnd) if 'win32gui' in dir() else '?'}")
    else:
        print("  △ ComboLBox 不可见或不存在（下拉列表收起态正常）")

    # 4) 初始化 OCR
    print("\n[4/6] 初始化 OCR 引擎...")
    ocr_engine = _init_ocr()
    if ocr_engine is None:
        print("  ✗ OCR 初始化失败，无法进行文本识别")
        return False
    print("  ✓ onnxocr 就绪")

    # 5) 捕获对话框帧 + OCR
    print("\n[5/6] 捕获登录对话框并 OCR...")
    frame, origin = _capture_hwnd(dlg_hwnd)
    if frame is None:
        print("  ✗ 对话框帧捕获失败")
        return False

    if save_screenshots:
        out_dir = os.path.join(_project_root, "test_out")
        os.makedirs(out_dir, exist_ok=True)
        import cv2
        ts = time.strftime("%H%M%S")
        img_path = os.path.join(out_dir, f"{ts}_login_dialog.png")
        cv2.imwrite(img_path, frame)
        print(f"  截图已保存: {img_path}")

    ocr_results = _ocr_frame(ocr_engine, frame)
    account_entries = [r for r in ocr_results if _is_account_text(r['text'])]
    login_entries = [r for r in ocr_results if _is_login_text(r['text'])]
    expanded = _count_account_entries(ocr_results) >= 2

    print(f"  OCR 共识别 {len(ocr_results)} 个文本框：")
    for r in ocr_results:
        tag = ""
        if _is_account_text(r['text']):
            tag = " ← 账号"
        elif _is_login_text(r['text']):
            tag = " ← 登录"
        print(f"    {r['text']!r}  conf={r['confidence']:.2f}  center={r['center']}{tag}")

    print(f"\n  账号条目: {len(account_entries)} 个  |  登录文本: {len(login_entries)} 个  |  展开态: {'是' if expanded else '否'}")

    # 关键判定
    login_ready = len(account_entries) >= 1 and len(login_entries) >= 1
    print(f"  do_find_account_drop_down 判定: {'✓ 就绪' if login_ready else '✗ 未就绪'}")

    if expanded:
        entry_texts = [r['text'] for r in account_entries]
        print(f"  _account_list_expanded 判定: ✓ 已展开（账号条目 {len(entry_texts)} 个: {entry_texts}）")
    else:
        print(f"  _account_list_expanded 判定: ✗ 未展开（账号条目 {len(account_entries)} 个）")

    # 交互模式先展开独立 ComboLBox，列出所有实际可见账号
    if not diag_only and not target and not expanded:
        if not combo_hwnd or not combo_rect:
            print("  ✗ 未找到 ComboBox，无法展开账号列表")
            return False
        cx = (combo_rect[0] + combo_rect[2]) // 2
        cy = (combo_rect[1] + combo_rect[3]) // 2
        print(f"  交互模式：展开账号列表 ({cx}, {cy})...")
        _screen_click(cx, cy)
        list_state = _wait_for_account_list(dlg_hwnd, ocr_engine, timeout=10)
        if list_state is None:
            print("  ✗ 10s 内未检测到展开的账号列表")
            return False
        frame, origin, ocr_results, game_hwnds = list_state
        account_entries = [r for r in ocr_results if _is_account_text(r['text'])]
        expanded = True

    # 6) 切换测试
    profiles = _load_profiles()

    # 识别每个可见账号对应的方案
    print(f"\n[6/6] 账号匹配分析...")
    visible_accounts = []
    for r in account_entries:
        name = r['text'].strip()
        matched_profile = None
        for profile_name, aliases in profiles.items():
            # 提取方案简称（如 A1、A3、B7）
            short = _short_name(profile_name)
            if name in aliases or any(alias in name for alias in aliases if len(alias) >= 4):
                matched_profile = profile_name
                break
            # 直接掩码匹配
            phone_re = re.compile(r'(1[3-9]\d{9})')
            m = phone_re.search(profile_name)
            if m:
                masked = m.group(1)[:3] + '****' + m.group(1)[-4:]
                if name == masked:
                    matched_profile = profile_name
                    break
        visible_accounts.append({
            'ocr_text': name,
            'profile': matched_profile,
            'short': _short_name(matched_profile) if matched_profile else None,
        })
        profile_tag = f" → {_short_name(matched_profile)}" if matched_profile else " → 未知"
        print(f"  {name}{profile_tag}")

    # 交互式选择目标
    if diag_only:
        print(f"\n{'=' * 70}")
        print("  诊断模式完成（未执行点击操作）")
        print(f"{'=' * 70}")
        return True

    if not target:
        # 交互式选择
        matched = [a for a in visible_accounts if a['profile']]
        if not matched:
            print("  ✗ 无法匹配任何已知方案")
            return False
        print(f"\n  可切换的账号：")
        for i, a in enumerate(matched):
            print(f"    [{i + 1}] {a['ocr_text']}  ({a['short']})")
        print()
        try:
            choice = input("  输入编号选择目标账号（或直接输入方案名如 A1/A3）：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  已取消")
            return False
        if choice.isdigit() and 1 <= int(choice) <= len(matched):
            target = matched[int(choice) - 1]['short']
        else:
            target = choice
        if not target:
            print("  ✗ 未选择目标")
            return False

    # 也支持直接输入 A1/A3 等简称
    target_profile = None
    target_aliases = []
    for profile_name, aliases in profiles.items():
        short = _short_name(profile_name)
        if short == target or profile_name == target or target in profile_name:
            target_profile = profile_name
            target_aliases = _get_aliases(profiles, profile_name)
            break
    if not target_profile:
        # 按别名匹配
        for profile_name, aliases in profiles.items():
            if target in aliases:
                target_profile = profile_name
                target_aliases = aliases
                break

    if not target_profile:
        print(f"  ✗ 未找到方案 '{target}'")
        print(f"  可用方案: {[_short_name(k) for k in profiles.keys()]}")
        return False

    target = _short_name(target_profile)
    print(f"\n  目标: {target}（{target_profile}）")
    print(f"  别名/身份: {target_aliases}")

    # 检查目标是否在可见列表中
    visible_match = [a for a in visible_accounts if a['short'] == target]
    if visible_match:
        print(f"  ✓ 在当前登录界面中找到 {target}（{visible_match[0]['ocr_text']}）")
    else:
        print(f"  ⚠ 当前登录界面中未找到 {target}，尝试切换但可能失败")
        print(f"  可见账号: {[a['ocr_text'] for a in visible_accounts]}")

    if not login_ready:
        print("  ✗ 登录界面未就绪，无法进行切换测试")
        return False

    print(f"\n开始切换测试（目标: {target}，轮数: {rounds}）...")

    for round_i in range(1, rounds + 1):
        print(f"\n  ---- 第 {round_i}/{rounds} 轮 ----")
        success = _do_switch(
            target,
            target_aliases,
            dlg_hwnd,
            ocr_engine,
            save_screenshots,
        )
        if success:
            print(f"  ✓ 第 {round_i} 轮切换成功")
            # 切换成功后游戏会进入主界面，需要再退登到登录界面（如果还有下一轮）
            if round_i < rounds:
                print(f"  退登回登录界面...")
                _go_back_to_login()
                refreshed = _wait_for_login_dialog(timeout=120)
                if refreshed is None:
                    print("  ✗ 120s 内未重新检测到登录对话框")
                    return False
                (main_hwnd, game_hwnds, dlg_hwnd, dlg_rect,
                 combo_hwnd, combo_rect) = refreshed
        else:
            print(f"  ✗ 第 {round_i} 轮切换失败")
            return False

    print(f"\n{'=' * 70}")
    print(f"  全部 {rounds} 轮切换测试通过 ✓")
    print(f"{'=' * 70}")
    return True


def _do_switch(target, target_aliases, dlg_hwnd, ocr_engine,
               save_screenshots, max_select_retries=3):
    """执行一次账号切换，并在不一致时重新选择目标账号。"""
    import cv2

    for attempt in range(1, max_select_retries + 1):
        print(f"  [Step1-4] 第 {attempt}/{max_select_retries} 次选择 {target}...")
        _main_hwnd, game_hwnds = _find_game_hwnd()
        list_hwnd, _list_rect = _find_control_hwnd('ComboLBox', game_hwnds)
        if not list_hwnd:
            combo_hwnd, combo_rect = _find_control_hwnd('ComboBox', game_hwnds)
            if not combo_hwnd or not combo_rect:
                print("  [Step2] 未找到 ComboBox，准备重试")
                time.sleep(1)
                continue
            cx = (combo_rect[0] + combo_rect[2]) // 2
            cy = (combo_rect[1] + combo_rect[3]) // 2
            print(f"  [Step2] 点击 ComboBox ({cx}, {cy})...")
            _screen_click(cx, cy)

        print("  [Step3] 等待独立 ComboLBox 展开...")
        list_state = _wait_for_account_list(dlg_hwnd, ocr_engine, timeout=10)
        if list_state is None:
            print("  [Step3] 10s 内未检测到账号列表，准备重试")
            continue
        frame, origin, ocr_results, _game_hwnds = list_state
        entry_count = _count_account_entries(ocr_results)
        print(f"  [Step3] ✓ 列表已展开（账号条目: {entry_count}）")
        if save_screenshots:
            out_dir = os.path.join(_project_root, "test_out")
            os.makedirs(out_dir, exist_ok=True)
            ts = time.strftime("%H%M%S")
            cv2.imwrite(os.path.join(out_dir, f"{ts}_expanded.png"), frame)

        print(f"  [Step4] 在列表中查找 {target}（别名: {target_aliases}）...")
        target_box = next(
            (r for r in ocr_results if _account_matches_alias(r['text'], target_aliases)),
            None,
        )
        if target_box is None:
            visible = [r['text'] for r in ocr_results if _is_account_text(r['text'])]
            print(f"  [Step4] 未找到 {target}；可见账号: {visible}，准备重试")
            continue

        sx, sy = _box_center_screen(target_box['box'], origin)
        print(f"  [Step4] 找到 {target_box['text']}，点击屏幕 ({sx}, {sy})...")
        _screen_click(sx, sy)
        time.sleep(1.5)

        matched, displayed, _frame, _origin = _selected_target_from_dialog(
            dlg_hwnd,
            ocr_engine,
            target_aliases,
        )
        if matched:
            print(f"  [Step4] ✓ 已核对目标账号，当前显示: {displayed}")
            break
        print(
            f"  [Step4] 当前显示 {displayed or ['未识别']} 与目标 {target} 不一致，"
            "重新展开并选择"
        )
    else:
        print(f"  [Step4] ✗ {max_select_retries} 次重试后仍无法确认 {target}，为防误登录已停止")
        return False

    # Step 5: 点击「登录」按钮
    print("  [Step5] 查找登录按钮...")
    time.sleep(1)
    frame, origin = _capture_hwnd(dlg_hwnd)
    if frame is None:
        print("  [Step5] ✗ 重新捕获对话框失败")
        return False
    ocr_results = _ocr_frame(ocr_engine, frame)
    login_box = next((r for r in ocr_results if _is_login_text(r['text'])), None)
    if login_box is None:
        print("  [Step5] ✗ 未找到登录按钮，为防止误点已停止")
        return False

    sx, sy = _box_center_screen(login_box['box'], origin)
    print(f"  [Step5] 点击登录按钮 ({sx}, {sy})...")
    _screen_click(sx, sy)

    print("  [Step6] 等待登录界面持续消失并确认游戏主窗口可见...")
    if not _wait_for_login_completion(timeout=180, stable_seconds=5):
        print("  [Step6] ✗ 180s 内未确认登录完成")
        return False
    print("  [Step6] ✓ 已确认离开登录界面")
    return True


def _go_back_to_login():
    """在游戏中按 ESC → 点退登 → 确认 → 等待登录界面。

    注意：这依赖于游戏的退登流程，可能需要根据实际情况调整。
    """
    import win32api
    import win32con

    print("    按 ESC...")
    win32api.keybd_event(0x1B, 0, 0, 0)  # ESC down
    time.sleep(0.05)
    win32api.keybd_event(0x1B, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(1.5)

    # 点击退登入口（左下角约 4% x, 96% y）
    import ctypes
    user32 = ctypes.windll.user32
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    _screen_click(int(sw * 0.04), int(sh * 0.96))
    time.sleep(1)

    # 点击确认退登（屏幕中央偏下）
    _screen_click(sw // 2, int(sh * 0.63))
    time.sleep(3)


def _parse_profiles(data):
    """从新旧 daily_profiles.json 结构解析方案名和识别别名。"""
    profiles = {}
    if not isinstance(data, dict):
        return profiles
    source = data.get('profiles', data)
    if not isinstance(source, dict):
        return profiles
    for name, content in source.items():
        if source is data and name in ('sequences', 'active_profile'):
            continue
        if not isinstance(content, dict):
            continue
        aliases = []
        phone = content.get('Account Name', '') or ''
        alias_text = content.get('备用识别名称内容', '') or ''
        old_aliases = content.get('account_aliases') or []
        if phone:
            aliases.append(str(phone).strip())
        if isinstance(alias_text, str):
            aliases.extend([
                a.strip() for a in re.split(r'[,，;；\r\n]+', alias_text) if a.strip()
            ])
        if isinstance(old_aliases, list):
            aliases.extend([str(a).strip() for a in old_aliases if str(a).strip()])
        profiles[name] = list(dict.fromkeys(aliases))
    return profiles


def _load_profiles():
    """读取 daily_profiles.json 中的方案名和别名。"""
    profile_path = os.path.join(_project_root, 'configs', 'daily_profiles.json')
    try:
        import json
        with open(profile_path, encoding='utf-8') as f:
            data = json.load(f)
        return _parse_profiles(data)
    except Exception as e:
        print(f"[WARN] 读取方案失败: {e}")
        return {}


def _get_aliases(profiles, profile_name):
    """获取指定方案的别名列表（含掩码/U账号/手机号）。"""
    # 支持简称匹配（A1 → 【A1-溅青-13097291243】）
    actual_name = None
    for k in profiles:
        if k == profile_name or _short_name(k) == profile_name or profile_name in k:
            actual_name = k
            break
    if not actual_name:
        return []

    aliases = list(profiles.get(actual_name, []))
    result = set(aliases)
    # 从方案名提取手机号并生成掩码
    phone_re = re.compile(r'(1[3-9]\d{9})')
    m = phone_re.search(actual_name)
    if m:
        phone = m.group(1)
        masked = phone[:3] + '****' + phone[-4:]
        result.add(masked)
        result.add(phone)
    # 从别名中的手机号也生成掩码
    for a in aliases:
        m2 = phone_re.search(a)
        if m2:
            phone = m2.group(1)
            result.add(phone[:3] + '****' + phone[-4:])
            result.add(phone)
    # 空字符串/无意义值过滤
    return [a for a in result if a and a != '无' and a.strip()]


# ========================= 入口 =========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="v1.04.0 账号切换功能测试")
    parser.add_argument('--target', '-t', type=str, default=None,
                        help='目标账号方案名或简称（如 A1、A3）。不指定则交互选择。')
    parser.add_argument('--rounds', '-n', type=int, default=1,
                        help='测试轮数（默认 1）')
    parser.add_argument('--diag', action='store_true',
                        help='仅诊断模式：检测登录界面 + OCR 结果，不做点击操作')
    parser.add_argument('--no-screenshots', action='store_true',
                        help='不保存截图')
    args = parser.parse_args()

    ok = run_test(
        target=args.target,
        rounds=args.rounds,
        diag_only=args.diag,
        save_screenshots=not args.no_screenshots,
    )
    sys.exit(0 if ok else 1)
