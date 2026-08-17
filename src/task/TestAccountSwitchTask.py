# -*- coding: utf-8 -*-
"""🧪 账号切换测试任务（v1.03.74）。

独立测试多账号登录界面的账号切换功能（不跑完整每日任务）。
直接复用 MultiAccountDailyTask 的切换方法，确保测试路径与正式流程一致。

步骤：自动检测界面 → 在主界面则退登 → find_account_drop_down →
      展开下拉框 → _click_account_in_list → 核对账号 → 点登录 → 进游戏。
"""
import re

from qfluentwidgets import FluentIcon as Icon

from ok import Logger
from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.MouseResetTask import MouseResetTask

logger = Logger.get_logger(__name__)

PHONE_IN_NAME_RE = re.compile(r'(1[3-9]\d{9})')
SHORT_NAME_RE = re.compile(r'【([A-Z]\d+)[-.]')


def _short_name(profile_name):
    if not profile_name:
        return None
    m = SHORT_NAME_RE.search(profile_name)
    return m.group(1) if m else profile_name


class TestAccountSwitchTask(WWOneTimeTask, BaseWWTask):
    """独立测试账号切换功能。

    直接调用 MultiAccountDailyTask 的切换方法，测试路径与正式流程一致。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🔄 账号切换测试"
        self.description = (
            "自动检测界面（主界面自动退登），复用多账号任务的切换流程测试账号切换。"
            "不执行每日任务，仅验证 登录识别→下拉框→选号→登录 全链路。"
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
            '目标账号': '选择要切换到的账号方案。留空或「自动识别」= 选登录界面中第一个可用账号',
            '测试轮数': '切换测试重复轮数（每轮：选号→登录→进游戏→退登→下一轮）',
        }

    def _get_profile_names(self):
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

    def _get_multi_account_task(self):
        """获取 MultiAccountDailyTask 实例（复用其方法）。"""
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        return self.executor.get_task_by_class(MultiAccountDailyTask)

    def run(self):
        WWOneTimeTask.run(self)

        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()

        try:
            target_config = (self.config.get('目标账号') or '').strip()
            rounds = int(self.config.get('测试轮数') or '1')
            auto_mode = target_config in ('', '（自动识别）', '无')

            self.log_info(f'账号切换测试开始（目标: {"自动识别" if auto_mode else target_config}，轮数: {rounds}）', notify=True)
            self.info_set('状态', '检测当前界面...')

            mat = self._get_multi_account_task()
            if mat is None:
                self.log_error('未找到 MultiAccountDailyTask 实例')
                raise Exception('MultiAccountDailyTask 未注册')

            # ============ 自动检测当前界面 ============
            self.log_info('自动检测当前界面...')
            detected_main = False
            detected_login = False
            for detect_try in range(1, 21):
                # 先查登录界面
                if mat.do_find_account_drop_down() is not None:
                    detected_login = True
                    self.log_info(f'检测到登录界面（第 {detect_try} 次检测）')
                    break
                # 再查主界面
                try:
                    if self.is_main(esc=False):
                        detected_main = True
                        self.log_info(f'检测到游戏主界面（第 {detect_try} 次检测）')
                        break
                except Exception:
                    pass
                if detect_try % 5 == 0:
                    self.log_info(f'界面检测中（第 {detect_try} 次，可能在加载/弹窗中）...')
                self.sleep(2)

            if not detected_main and not detected_login:
                self.log_error('20 次检测后仍未确认当前界面')
                self.screenshot('multi')
                raise Exception('无法确认当前界面')

            if detected_main:
                self.log_info('从主界面退登到登录界面...')
                self.info_set('状态', '退登中...')
                mat._switch_to_login()
                self.sleep(2)

            # ============ 循环测试 ============
            for round_i in range(1, rounds + 1):
                self.log_info(f'=== 第 {round_i}/{rounds} 轮 ===')
                self.info_set('当前轮次', f'{round_i}/{rounds}')

                if auto_mode:
                    # 自动模式：直接用 MultiAccountDailyTask 的完整切换流程
                    self.log_info('自动模式：复用 MultiAccountDailyTask._select_and_login_account')
                    self.info_set('状态', '等待登录界面 → 选号 → 登录...')
                    target = mat._select_and_login_account()
                    if target is None:
                        self.log_error('自动选择失败（_select_and_login_account 返回 None）')
                        self.screenshot('multi')
                        raise Exception('自动选择失败')
                    self.log_info(f'✓ 第 {round_i} 轮已登录 {target}')
                    self.info_set('状态', f'✓ 已登录 {target}')
                else:
                    # 指定目标模式
                    self.log_info(f'指定目标: {target_config}')
                    self.info_set('状态', f'等待登录界面 → 选 {target_config} → 登录...')

                    # 等待登录界面就绪
                    self.log_info('等待登录界面就绪...')
                    drop_down = mat.find_account_drop_down()
                    self.log_info(f'登录界面就绪（{"对话框" if getattr(mat, "_login_in_dialog", False) else "主窗口"}）')

                    # 展开下拉框
                    if mat._account_list_expanded():
                        self.log_info('列表已展开，跳过点击下拉框')
                    elif getattr(mat, '_login_in_dialog', False):
                        self.log_info('点击 ComboBox 展开账号列表...')
                        mat._dialog_open_account_list()
                    else:
                        self.log_info('点击下拉框...')
                        mat.click(drop_down, after_sleep=2)

                    # 等待展开
                    expanded = self.wait_until(mat._account_list_expanded, time_out=10,
                                               settle_time=1, raise_if_not_found=False)
                    if expanded:
                        self.log_info('列表已展开 ✓')
                    else:
                        self.log_warning('列表未展开，尝试继续...')

                    # 等待选中目标账号
                    self.info_set('状态', f'选择 {target_config}...')
                    account = self.wait_until(
                        lambda: mat._click_account_in_list(target_config),
                        time_out=10, raise_if_not_found=True
                    )
                    self.log_info(f'已点击 {target_config}')

                    # 核对
                    self.sleep(1)
                    current = mat._detect_current_account_from_login()
                    self.log_info(f'核对：目标={target_config}，当前显示={current}')

                    # 点登录
                    self.info_set('状态', '点击登录...')
                    self.sleep(3)
                    if getattr(mat, '_login_in_dialog', False):
                        shown = mat._detect_current_account_from_login()
                        if shown and not mat._same_account(shown, target_config):
                            self.log_error(f'防误登：显示 {shown} ≠ 目标 {target_config}')
                            self.screenshot('multi')
                            raise Exception('防误登：账号不一致')
                        mat._dialog_click_login()
                    else:
                        texts = self.ocr()
                        login_btn = self.find_boxes(texts, boundary=self.box_of_screen(0.3, 0.3, 0.7, 0.8),
                                                    match=self._login_text_pattern())
                        if login_btn:
                            shown = mat._detect_current_account_from_login()
                            if shown and not mat._same_account(shown, target_config):
                                self.log_error(f'防误登：显示 {shown} ≠ 目标 {target_config}')
                                self.screenshot('multi')
                                raise Exception('防误登：账号不一致')
                            self.click(login_btn, after_sleep=3)
                        else:
                            self.click_relative(0.5, 0.568, hcenter=True, vcenter=True, after_sleep=3)

                    # 等待进游戏
                    self.log_info('等待进入游戏...')
                    self.info_set('状态', '等待进入游戏...')
                    self.logged_in = False
                    self.ensure_main(time_out=180)
                    self.log_info(f'✓ 第 {round_i} 轮已登录 {target_config}')
                    self.info_set('状态', f'✓ 已登录 {target_config}')

                # 下一轮：退登
                if round_i < rounds:
                    self.log_info('退登回登录界面...')
                    self.info_set('状态', '退登中...')
                    mat._switch_to_login()
                    self.sleep(2)

            self.log_info(f'全部 {rounds} 轮切换测试通过 ✓', notify=True)
            self.info_set('状态', '测试通过 ✓')

        finally:
            if mouse_reset_was_enabled:
                mouse_reset_task.enable()

    def _login_text_pattern(self):
        from src.task.BaseWWTask import LOGIN_TEXTS
        return LOGIN_TEXTS
