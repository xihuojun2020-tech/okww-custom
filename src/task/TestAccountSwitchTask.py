# -*- coding: utf-8 -*-
"""🧪 账号切换测试任务（v1.03.74）。

独立测试多账号登录界面的账号切换功能（不跑完整每日任务）。
步骤：检测登录界面 → 展开下拉框 → OCR 列出所有账号 → 选择/自动选择目标 → 点击 → 点登录。
"""
import re
import time

from qfluentwidgets import FluentIcon as Icon

from ok import Logger
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.MouseResetTask import MouseResetTask

logger = Logger.get_logger(__name__)

# 账号模式（与 MultiAccountDailyTask 保持一致）
ACCOUNT_PATTERN = re.compile(r'\*\*\*\*')
SCAN_ACCOUNT_PATTERN = re.compile(r'^U[a-zA-Z0-9]+$', re.IGNORECASE)
PHONE_IN_NAME_RE = re.compile(r'(1[3-9]\d{9})')
SHORT_NAME_RE = re.compile(r'【([A-Z]\d+)[-.]')


def _short_name(profile_name):
    """从方案全名提取简称（如 A1、B7）。"""
    if not profile_name:
        return None
    m = SHORT_NAME_RE.search(profile_name)
    return m.group(1) if m else profile_name


class TestAccountSwitchTask(WWOneTimeTask, BaseWWTask):
    """独立测试账号切换功能（不跑完整每日任务）。

    在登录界面执行：检测 → 展开列表 → 列出账号 → 选择目标 → 点击 → 点登录。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🔄 账号切换测试"
        self.description = (
            "独立测试账号切换功能：检测登录界面 → 展开下拉框 → "
            "OCR 列出所有账号 → 选择目标 → 点击 → 点登录。"
            "不执行每日任务，仅验证切换流程。"
        )
        self.group_name = "🧪 测试功能"
        self.group_icon = Icon.DEVELOPER_TOOLS

        profile_names = self._get_profile_names()
        self.default_config = {
            '目标账号': '',
            '测试轮数': '1',
        }
        self.config_type = {
            '目标账号': {
                'type': 'drop_down',
                'options': ['（自动识别）'] + profile_names,
            },
            '测试轮数': {
                'type': 'drop_down',
                'options': ['1', '2', '3', '5', '10'],
            },
        }
        self.config_description = {
            '目标账号': '选择要切换到的账号方案。留空或「自动识别」= 列出登录界面所有账号后选择第一个可用',
            '测试轮数': '切换测试重复轮数（每轮：切换→进游戏→退登→下一轮）',
        }

    def _get_profile_names(self):
        """读取 daily_profiles.json 的方案名列表。"""
        try:
            from ok.util.file import get_relative_path, read_json_file
            profiles = read_json_file(get_relative_path('configs', 'daily_profiles.json'))
            if isinstance(profiles, dict) and 'profiles' in profiles:
                return list(profiles['profiles'].keys())
            elif isinstance(profiles, dict):
                return [k for k in profiles.keys() if k != 'sequences']
        except Exception:
            pass
        return []

    def _load_profiles(self):
        """读取 daily_profiles.json 返回 {方案名: [别名列表]}。"""
        profiles = {}
        try:
            from ok.util.file import get_relative_path, read_json_file
            data = read_json_file(get_relative_path('configs', 'daily_profiles.json'))
            if not isinstance(data, dict):
                return profiles
            raw = data.get('profiles', data)
            for name, content in raw.items():
                if not isinstance(content, dict) or name == 'sequences':
                    continue
                aliases = []
                # 手机号（从方案名提取）
                m = PHONE_IN_NAME_RE.search(name)
                if m:
                    phone = m.group(1)
                    aliases.append(phone[:3] + '****' + phone[-4:])
                    aliases.append(phone)
                # 备用识别名称
                alias_text = content.get('备用识别名称内容', '') or ''
                if alias_text:
                    for a in alias_text.split(','):
                        a = a.strip()
                        if a:
                            aliases.append(a)
                profiles[name] = aliases
        except Exception as e:
            self.log_error('读取方案失败', e)
        return profiles

    def _get_aliases_for(self, profiles, profile_name):
        """获取指定方案的所有可识别别名（含掩码/U 账号/手机号）。"""
        actual_name = None
        for k in profiles:
            if k == profile_name or _short_name(k) == profile_name or profile_name in k:
                actual_name = k
                break
        if not actual_name:
            return []
        result = set(profiles.get(actual_name, []))
        # 从方案名提取手机号生成掩码
        m = PHONE_IN_NAME_RE.search(actual_name)
        if m:
            phone = m.group(1)
            result.add(phone[:3] + '****' + phone[-4:])
            result.add(phone)
        return [a for a in result if a and a != '无' and a.strip()]

    def _is_account_text(self, text):
        if not text:
            return False
        return bool(ACCOUNT_PATTERN.search(text) or SCAN_ACCOUNT_PATTERN.match(text))

    def _is_login_text(self, text):
        return (text or '').strip() in ('登录', '登入', 'Log')

    def _count_account_entries(self, texts):
        count = 0
        for t in texts or []:
            name = (t.name or '').strip()
            if name and self._is_account_text(name):
                count += 1
        return count

    def _account_list_expanded(self):
        """账号下拉列表是否已展开（账号条目 ≥2）。"""
        if getattr(self, '_login_in_dialog', False):
            try:
                hwnd, rect = self._find_control_hwnd('ComboLBox')
                if hwnd:
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    if w >= 200 and h >= 100:
                        return True
            except Exception:
                pass
            dlg_texts = self._ocr_login_dialog()
            return bool(dlg_texts) and self._count_account_entries(dlg_texts) >= 2
        texts = self.ocr()
        return bool(texts) and self._count_account_entries(texts) >= 2

    def _detect_login_dialog(self):
        """检测登录对话框是否存在（#32770）。"""
        hwnd, _rect = self._find_login_dialog()
        if hwnd:
            self._login_in_dialog = True
            return True
        # 回退：主窗口有登录特征
        texts = self.ocr()
        login_boxes = self.find_boxes(texts, self._login_text_pattern())
        account_count = self._count_account_entries(texts)
        if login_boxes and account_count >= 1:
            self._login_in_dialog = False
            return True
        return False

    def _login_text_pattern(self):
        """返回 LOGIN_TEXTS 的匹配模式（兼容 BaseWWTask 的 LOGIN_TEXTS 定义）。"""
        from src.task.BaseWWTask import LOGIN_TEXTS
        return LOGIN_TEXTS

    def _find_login_dialog(self):
        """找 #32770 登录对话框（复用 MultiAccountDailyTask 的逻辑）。"""
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        return MultiAccountDailyTask._find_login_dialog(self)

    def _find_control_hwnd(self, class_name):
        """找控件（复用 MultiAccountDailyTask 的逻辑）。"""
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        return MultiAccountDailyTask._find_control_hwnd(self, class_name)

    def _ocr_login_dialog(self):
        """OCR 登录对话框帧。"""
        hwnd, _rect = self._find_login_dialog()
        if not hwnd:
            return None
        frame, _origin = self._capture_hwnd_client(hwnd)
        if frame is None:
            return None
        try:
            return self.ocr(frame=frame)
        except Exception:
            return None

    def _capture_hwnd_client(self, hwnd):
        """BitBlt 捕获窗口帧（复用 MultiAccountDailyTask 的逻辑）。"""
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        return MultiAccountDailyTask._capture_hwnd_client(self, hwnd)

    def _open_account_list(self):
        """点击 ComboBox 展开账号列表。"""
        hwnd, rect = self._find_control_hwnd('ComboBox')
        if not hwnd:
            self.log_warning('未找到账号下拉框（ComboBox）')
            return False
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        self.log_info(f'点击账号下拉框 ({cx}, {cy})')
        self._screen_click(cx, cy, after_sleep=2)
        return True

    def _screen_click(self, x, y, after_sleep=0.5):
        """系统级鼠标点击屏幕坐标。"""
        import win32api
        import win32con
        try:
            win32api.SetCursorPos((int(x), int(y)))
            time.sleep(0.1)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            if after_sleep:
                self.sleep(after_sleep)
            return True
        except Exception:
            return False

    def _box_center_screen(self, box, origin):
        """把 OCR Box 中心换算为屏幕坐标。"""
        cx = box.x + box.width / 2.0
        cy = box.y + box.height / 2.0
        return int(origin[0] + cx), int(origin[1] + cy)

    def _get_ocr_accounts(self):
        """获取当前登录界面的所有账号条目（对话框帧优先）。"""
        if getattr(self, '_login_in_dialog', False):
            dlg_texts = self._ocr_login_dialog()
            if dlg_texts:
                return [(t, (t.name or '').strip()) for t in dlg_texts if self._is_account_text((t.name or '').strip())]
        texts = self.ocr()
        return [(t, (t.name or '').strip()) for t in (texts or []) if self._is_account_text((t.name or '').strip())]

    def _match_account_to_profile(self, text, profiles):
        """把 OCR 账号文本匹配到方案名。"""
        for profile_name, aliases in profiles.items():
            short = _short_name(profile_name)
            # 直接别名匹配
            if text in aliases:
                return profile_name, short
            # 掩码/手机号匹配
            m = PHONE_IN_NAME_RE.search(profile_name)
            if m:
                phone = m.group(1)
                masked = phone[:3] + '****' + phone[-4:]
                if text == masked or text == phone:
                    return profile_name, short
            # U 账号匹配
            for alias in aliases:
                if len(alias) >= 4 and alias in text:
                    return profile_name, short
        return None, None

    def _click_login_button(self):
        """点击登录按钮。"""
        if getattr(self, '_login_in_dialog', False):
            frame, origin = self._dialog_capture()
            if frame is not None:
                try:
                    texts = self.ocr(frame=frame)
                    login_boxes = self.find_boxes(texts, self._login_text_pattern())
                    if login_boxes:
                        box = login_boxes[0]
                        sx, sy = self._box_center_screen(box, origin)
                        self.log_info(f'点击登录按钮（对话框，屏幕 {sx},{sy}）')
                        return self._screen_click(sx, sy, after_sleep=3)
                except Exception:
                    pass
        # 主窗口兜底
        texts = self.ocr()
        login_boxes = self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.8),
                                       match=self._login_text_pattern())
        if login_boxes:
            self.click(login_boxes, after_sleep=3)
            return True
        self.click_relative(0.5, 0.568, hcenter=True, vcenter=True, after_sleep=3)
        return True

    def _dialog_capture(self):
        """捕获 #32770 登录对话框帧。"""
        hwnd, _rect = self._find_login_dialog()
        if not hwnd:
            return None, None
        return self._capture_hwnd_client(hwnd)

    def run(self):
        WWOneTimeTask.run(self)

        # 关闭鼠标复位（避免干扰屏幕点击）
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()

        try:
            target_config = (self.config.get('目标账号') or '').strip()
            rounds = int(self.config.get('测试轮数') or '1')
            profiles = self._load_profiles()
            auto_mode = target_config in ('', '（自动识别）', '无')

            self.log_info(f'账号切换测试开始（目标: {"自动识别" if auto_mode else target_config}，轮数: {rounds}）', notify=True)

            for round_i in range(1, rounds + 1):
                self.log_info(f'=== 第 {round_i}/{rounds} 轮 ===')

                # 1. 检测登录界面
                self.log_info('检测登录界面...')
                if not self._detect_login_dialog():
                    self.log_error('未检测到登录界面，请先退登到登录界面')
                    self.screenshot('multi')
                    raise Exception('未检测到登录界面')

                self.log_info(f'登录界面检测成功（{"对话框模式" if getattr(self, "_login_in_dialog", False) else "主窗口模式"}）')

                # 2. OCR 识别当前账号
                accounts = self._get_ocr_accounts()
                self.log_info(f'当前识别到 {len(accounts)} 个账号：')
                matched_accounts = []
                for box, text in accounts:
                    profile_name, short = self._match_account_to_profile(text, profiles)
                    if profile_name:
                        self.log_info(f'  {text} → {short}（{profile_name}）')
                        matched_accounts.append((box, text, profile_name, short))
                    else:
                        self.log_info(f'  {text} → 未知方案')

                # 3. 确定目标
                if auto_mode:
                    if not matched_accounts:
                        self.log_error('未匹配到任何已知方案，无法自动选择')
                        self.screenshot('multi')
                        raise Exception('未匹配到任何已知方案')
                    # 自动选择第一个匹配的账号（排除当前账号）
                    box, text, profile_name, target_short = matched_accounts[0]
                    self.log_info(f'自动选择: {target_short}（{text}）')
                else:
                    # 按配置查找
                    target_short = target_config
                    target_box = None
                    for box, text, profile_name, short in matched_accounts:
                        if short == target_short or profile_name == target_config:
                            target_box = box
                            target_short = short
                            break
                    if target_box is None:
                        self.log_error(f'目标 {target_config} 未在当前登录界面中找到')
                        self.log_info(f'可见账号: {[text for _, text in accounts]}')
                        self.screenshot('multi')
                        raise Exception(f'目标账号 {target_config} 不在登录界面中')

                self.info_set('当前轮次', f'{round_i}/{rounds}')
                self.info_set('目标账号', target_short)

                # 4. 展开下拉框
                if self._account_list_expanded():
                    self.log_info('列表已展开，跳过点击下拉框')
                else:
                    self.log_info('点击下拉框展开账号列表...')
                    if not self._open_account_list():
                        self.log_error('点击下拉框失败')
                        self.screenshot('multi')
                        raise Exception('点击下拉框失败')

                # 5. 等待列表展开
                self.log_info('等待列表展开...')
                expanded = self.wait_until(self._account_list_expanded, time_out=10,
                                           settle_time=1, raise_if_not_found=False)
                if not expanded:
                    self.log_error('点击下拉框无效果（列表未展开）')
                    self.screenshot('multi')
                    raise Exception('click drop down no effect')

                self.log_info('列表已展开 ✓')

                # 6. 重新获取展开后的账号列表
                expanded_accounts = self._get_ocr_accounts()
                self.log_info(f'展开后识别到 {len(expanded_accounts)} 个账号')

                # 7. 点击目标账号
                if auto_mode:
                    # 重新匹配（展开后可能有更多账号）
                    expanded_matched = []
                    for box, text in expanded_accounts:
                        pn, sh = self._match_account_to_profile(text, profiles)
                        if pn:
                            expanded_matched.append((box, text, pn, sh))
                    if not expanded_matched:
                        self.log_error('展开后仍未找到可匹配账号')
                        self.screenshot('multi')
                        raise Exception('展开后未找到可匹配账号')
                    # 选择第一个
                    target_box, target_text, profile_name, target_short = expanded_matched[0]
                    self.log_info(f'选择: {target_short}（{target_text}）')
                else:
                    # 在展开列表中找目标
                    target_box = None
                    for box, text in expanded_accounts:
                        pn, sh = self._match_account_to_profile(text, profiles)
                        if sh == target_short or pn == target_config:
                            target_box = box
                            break
                    if target_box is None:
                        self.log_error(f'展开列表中未找到 {target_short}')
                        self.screenshot('multi')
                        raise Exception(f'展开列表中未找到 {target_short}')

                # 点击目标账号
                if getattr(self, '_login_in_dialog', False):
                    frame, origin = self._dialog_capture()
                    if frame is not None:
                        sx, sy = self._box_center_screen(target_box, origin)
                        self.log_info(f'点击 {target_short}（屏幕 {sx},{sy}）')
                        self._screen_click(sx, sy, after_sleep=2)
                    else:
                        self.log_error('对话框帧捕获失败')
                        self.screenshot('multi')
                        raise Exception('对话框帧捕获失败')
                else:
                    self.log_info(f'点击 {target_short}')
                    self.click(target_box, after_sleep=2)

                self.sleep(2)
                self.info_set('状态', '已选号，准备点登录')

                # 8. 点击登录按钮
                self.log_info('点击登录按钮...')
                self._click_login_button()

                # 9. 等待进入主界面
                self.log_info('等待进入游戏主界面...')
                self.logged_in = False
                self.ensure_main(time_out=180)
                self.log_info(f'✓ 已登录 {target_short}')
                self.info_set('状态', f'已登录 {target_short}')

                # 如果还有下一轮，退登
                if round_i < rounds:
                    self.log_info('退登回登录界面...')
                    self._switch_to_login_simple()

            self.log_info(f'全部 {rounds} 轮切换测试通过 ✓', notify=True)
            self.info_set('状态', '测试通过 ✓')

        finally:
            if mouse_reset_was_enabled:
                mouse_reset_task.enable()

    def _switch_to_login_simple(self):
        """简化版退登（复用 MultiAccountDailyTask 的逻辑）。"""
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        try:
            MultiAccountDailyTask._switch_to_login(self)
        except Exception as e:
            self.log_error('退登失败', e)
            # 兜底：按 ESC 后点退登
            self.send_key('esc', after_sleep=1.5)
            self.sleep(2)
            self.click_relative(0.04, 0.96, after_sleep=1)
            self.click_confirm(timeout=10)
            self.sleep(5)
