# -*- coding: utf-8 -*-
"""🧪 账号切换测试任务（v1.08.00）。

独立测试多账号登录界面的账号切换功能（不跑完整每日任务）。
直接复用 MultiAccountDailyTask 的切换方法，确保测试路径与正式流程一致。

步骤：自动检测界面 → 在主界面则退登 → 调用 MultiAccountDailyTask 的完整
      指定账号/首个可用账号登录流程，或连续模拟 A1→A3→A4 的切换链路。
"""
import re

from qfluentwidgets import FluentIcon as Icon
from ok import TaskDisabledException

from src.task.BaseWWTask import BaseWWTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.MouseResetTask import MouseResetTask
from src.config_integrity import get_default_service
from src.account_repository import AccountRepository


SINGLE_MODE = '单账号切换'
CONTINUOUS_MODE = '连续序列切换'
DEFAULT_CONTINUOUS_ORDER = 'A1,A3,A4'

class TestAccountSwitchTask(WWOneTimeTask, BaseWWTask):
    """独立测试账号切换功能。

    直接调用 MultiAccountDailyTask 的切换方法，测试路径与正式流程一致。
    """
    navigation_section = "tests"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "🔄 多账号每日任务：账号切换链路测试"
        self.description = (
            "自动检测界面（主界面自动退登），复用多账号任务的切换流程测试账号切换。"
            "不执行每日任务，仅验证 登录识别→下拉框→选号→登录 全链路。"
        )
        self.group_name = "🧪 测试功能"
        self.group_icon = Icon.DEVELOPER_TOOLS
        self._account_refresh_pending = False

        profile_names = self._get_profile_names()
        self.default_config = {
            '测试模式': SINGLE_MODE,
            '目标账号': '（自动识别）',
            '连续账号顺序': DEFAULT_CONTINUOUS_ORDER,
            '测试轮数': '1',
        }
        self.config_type = {
            '测试模式': {
                'type': 'drop_down',
                'options': [SINGLE_MODE, CONTINUOUS_MODE],
                'sub_configs': {
                    SINGLE_MODE: ['目标账号'],
                    CONTINUOUS_MODE: ['连续账号顺序'],
                },
            },
            '目标账号': {
                'type': 'drop_down',
                'options': ['（自动识别）'] + profile_names,
            },
            '连续账号顺序': {
                'type': 'line_edit',
            },
            '测试轮数': {
                'type': 'drop_down',
                'options': ['1', '2', '3', '5', '10'],
            },
        }
        self.config_description = {
            '测试模式': '单账号测试，或按顺序连续模拟账号完成每日任务后的切换部分',
            '目标账号': '选择要切换到的账号方案。留空或「自动识别」= 选登录界面中第一个可用账号',
            '连续账号顺序': '用逗号分隔账号短名；默认 A1,A3,A4，按此顺序精确解析并切换',
            '测试轮数': '单账号登录次数，或完整连续序列的重复轮数',
        }

    @staticmethod
    def _parse_continuous_order(order_text):
        """解析 A1,A3,A4 / 中文逗号 / 空白分隔的连续账号短名。"""
        return [value.upper() for value in re.split(r'[,，\s]+', order_text or '') if value]

    def _get_profile_names(self):
        try:
            service = get_default_service()
            if service is not None:
                repository = AccountRepository(paths=service.paths, integrity_service=service)
                projection = repository.get_detached_projection()
                profiles = projection.get('profiles', {}) if isinstance(projection, dict) else {}
                if isinstance(profiles, dict):
                    return list(profiles.keys())
                result = service.last_result or service.check()
                if result.master_valid and result.master:
                    return list(service.legacy_profile_projection(result.master).get('profiles', {}).keys())
                return []
            from ok.util.file import get_relative_path, read_json_file
            profiles = read_json_file(get_relative_path('configs', 'daily_profiles.json'))
            if isinstance(profiles, dict) and 'profiles' in profiles:
                return list(profiles['profiles'].keys())
            elif isinstance(profiles, dict):
                return [k for k in profiles.keys() if k != 'sequences']
        except Exception:
            pass
        return []

    def refresh_profile_options(self):
        """Refresh target-account options without rebuilding the test card."""
        if getattr(self, 'running', False):
            self._account_refresh_pending = True
            return False
        names = self._get_profile_names()
        self.config_type['目标账号']['options'] = ['（自动识别）'] + names
        try:
            from ok import og
            main_window = getattr(og, 'main_window', None)
            test_tab = getattr(main_window, 'test_hub_tab', None)
            for card in getattr(getattr(test_tab, 'task_tab', None), 'card_widgets', []):
                if getattr(card, 'task', None) is not self:
                    continue
                for widget in getattr(card, 'config_widgets', []):
                    if getattr(widget, 'key', None) != '目标账号' or not hasattr(widget, 'combo_box'):
                        continue
                    combo = widget.combo_box
                    current = self.config.get('目标账号') or '（自动识别）'
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItems(['（自动识别）'] + names)
                    combo.setCurrentText(current if current in names else '（自动识别）')
                    combo.blockSignals(False)
        except Exception:
            pass
        self._account_refresh_pending = False
        return True

    def _get_multi_account_task(self):
        """获取 MultiAccountDailyTask 实例（复用其方法）。"""
        from src.task.MultiAccountDailyTask import MultiAccountDailyTask
        return self.executor.get_task_by_class(MultiAccountDailyTask)

    def run(self):
        if getattr(self, '_account_refresh_pending', False):
            self.refresh_profile_options()
        service = get_default_service()
        if service is not None:
            service.guard_task_start()
        WWOneTimeTask.run(self)

        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_was_enabled = mouse_reset_task.enabled if mouse_reset_task else False
        if mouse_reset_was_enabled:
            mouse_reset_task.disable()

        try:
            test_mode = (self.config.get('测试模式') or SINGLE_MODE).strip()
            target_config = (self.config.get('目标账号') or '').strip()
            rounds = int(self.config.get('测试轮数') or '1')
            auto_mode = target_config in ('', '（自动识别）', '无')

            mat = self._get_multi_account_task()
            if mat is None:
                self.log_error('未找到 MultiAccountDailyTask 实例')
                raise Exception('MultiAccountDailyTask 未注册')

            continuous_mode = test_mode == CONTINUOUS_MODE
            sequence_targets = []
            if continuous_mode:
                short_names = self._parse_continuous_order(
                    self.config.get('连续账号顺序') or DEFAULT_CONTINUOUS_ORDER
                )
                snapshot = mat.create_run_snapshot(
                    short_names, sequence_id='账号切换测试', short_names=True
                )
                sequence_targets = mat._snapshot_profile_names(snapshot)
                self.log_info(
                    f'账号切换测试开始（连续顺序: {" → ".join(short_names)}，'
                    f'完整序列轮数: {rounds}）',
                    notify=True,
                )
            else:
                self.log_info(
                    f'账号切换测试开始（目标: {"自动识别" if auto_mode else target_config}，'
                    f'轮数: {rounds}）',
                    notify=True,
                )
            self.info_set('状态', '检测当前界面...')

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
                except TaskDisabledException:
                    raise
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

                if continuous_mode:
                    self.log_info('连续模式：仅模拟每日任务完成后的账号切换，不运行每日任务、不写完成进度')

                    def update_progress(index, total, target):
                        self.info_set('状态', f'连续切换 {index}/{total} → {target}')

                    logged_targets = mat._select_and_login_sequence(
                        sequence_targets,
                        progress_callback=update_progress,
                    )
                    target = logged_targets[-1]
                    self.log_info(f'✓ 第 {round_i} 轮连续序列切换完成')
                elif auto_mode:
                    # 自动模式不依赖多账号序列/完成状态，直接取登录列表第一个可用方案
                    self.log_info('自动模式：选择登录列表中的第一个可用账号')
                    self.info_set('状态', '等待登录界面 → 选号 → 登录...')
                    target = mat._select_and_login_first_available()
                else:
                    self.log_info(f'指定目标: {target_config}')
                    self.info_set('状态', f'等待登录界面 → 选 {target_config} → 登录...')
                    target = mat._select_and_login_specific(target_config)

                if not continuous_mode:
                    self.log_info(f'✓ 第 {round_i} 轮已登录 {target}')
                self.info_set('状态', f'✓ 第 {round_i} 轮结束，当前已登录 {target}')

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
