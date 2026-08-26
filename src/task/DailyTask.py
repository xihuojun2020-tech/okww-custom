import os
import re
import copy
import importlib
import inspect
from contextlib import contextmanager
from datetime import datetime


from ok import Logger, TaskDisabledException
from ok.util.file import get_relative_path, read_json_file, write_json_file
from src.task.BaseWWTask import number_re
from src.task.ForgeryTask import ForgeryTask
from src.task.GardenTask import GardenTask
from src.task.MergeEchoTask import MergeEchoTask
from src.task.NightmareNestTask import NightmareNestTask
from src.task.TacetTask import TacetTask
from src.task.SimulationTask import SimulationTask
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.BaseCombatTask import BaseCombatTask
from src.config_integrity import (
    PROTECTED_TASK_KEYS,
    ConfigIntegrityBlocked,
    ConfigWriteBlocked,
    get_default_service,
)
from src.account_repository import get_default_repository

logger = Logger.get_logger(__name__)

CHECK_WEEKLY_GARDEN = 'Check Weekly Garden'
AUTO_FARM_NIGHTMARE_NEST = 'Auto Farm all Nightmare Nest'
MERGE_ECHO_ON_SUNDAY = 'Merge Echo on Sunday'
# 备用识别名称（扫码登录 U 账号等）：可选无/使用，使用则输入（逗号分隔，输入即保存）
ALIAS_ENABLE = '备用识别名称'
ALIAS_TEXT = '备用识别名称内容'
# 每周乐园检查日（单选一天：周一~周六 + 无；周日固定检查、不显示）
GARDEN_CHECK_DAY = 'Weekly Garden Check Day'
# 旧版多选周几键，仅用于迁移旧配置
WEEKLY_GARDEN_CHECK_DAYS = 'Weekly Garden Check Days'
# 旧版"附加任务列表"键，仅用于迁移旧配置
ADDITIONAL_TASKS = 'Additional Tasks to Run After Daily Task'

DAILY_PROFILE = 'Daily Profile'
PROFILE_SEQUENCE = '方案序列'
MANAGE_PROFILES = 'Manage Daily Profiles'
EXPORT_PROFILES = 'Export Account Config'
IMPORT_PROFILES = 'Import Account Config'
PROFILE_FILE = get_relative_path('configs', 'daily_profiles.json')
# 账号配置导出文件的标识
ACCOUNT_CONFIG_TYPE = 'okww_account_config'
# 多账号每日任务的配置（序列账号等，随每日任务数据一同备份）
MULTI_ACCOUNT_CONFIG_FILE = get_relative_path('configs', 'MultiAccountDailyTask.json')
ACCOUNT_CONFIG_VERSION = 1

# 每周乐园检查日（周一~周日），随账号方案切换
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

# 每日任务卡片上的只读展示键：显示各子任务上次完成时间（数据存于方案文件中，不参与配置保存）
LC_TACET = 'Last Completed - Tacet Suppression'
LC_FORGERY = 'Last Completed - Forgery Challenge'
LC_SIMULATION = 'Last Completed - Simulation Challenge'
LC_NIGHTMARE = 'Last Completed - Nightmare Nest'
LC_AUTO_NIGHTMARE = 'Last Completed - Auto Farm Nightmare Nest'
LC_NEST = 'Last Completed - Tacet Discord Nest'
LC_GARDEN = 'Last Completed - Weekly Garden'
LC_MERGE = 'Last Completed - Merge Echo'

# 每日任务完成后录像（进度留档）：打开指定页面各录一段视频
RECORD_AFTER_DAILY = 'Record After Daily Task'
RECORD_PAGES = 'Record Pages'
RECORD_DURATION = 'Record Duration'
RECORD_PAGE_OPTIONS = ['任务页', '每周乐园', '战令', '残像聚落']
# 每日任务完成后自动退登 PC 端（取代"完成任务后退出应用"，为下一个账号扫码登录做准备）
LOGOUT_AFTER_DAILY = 'Logout PC After Daily Task'
# 只读标签键 → 子任务名（record_last_completed 使用的名称）
LC_SUB_KEYS = {
    LC_TACET: 'Tacet Suppression',
    LC_FORGERY: 'Forgery Challenge',
    LC_SIMULATION: 'Simulation Challenge',
    LC_NIGHTMARE: 'Nightmare Nest',
    LC_AUTO_NIGHTMARE: 'Nightmare Nest',
    LC_NEST: 'Nightmare Nest',
    LC_GARDEN: 'Weekly Garden',
    LC_MERGE: 'Merge Echo',
}

# 这些键属于"每日任务配置方案"，切换方案时会被保存/加载
PROFILE_KEYS = list(PROTECTED_TASK_KEYS)

# 方案文件中需要随方案一起保留、但不属于用户配置的数据字段（例如上次完成时间）
PROFILE_EXTRA_FIELDS = ('last_completed', 'account_aliases')

# 梦魇巢穴刷取选项
NIGHTMARE_OPTIONS = ['Nightmare Purification', 'Tacet Discord Nest']

# 残象聚落名称（合并进每日任务模块，随方案切换）
NEST_NAMES = ['落渊南丘残象聚落', '盲望之塌残象聚落', '复生丘原残象聚落', '陷足流川残象聚落']


class DailyTask(WWOneTimeTask, BaseCombatTask):

    def __getattr__(self, name):
        """Keep legacy object.__new__ test/helpers compatible.

        These values are optional only when the task was not initialized.  A
        real integrity service is never synthesized or bypassed here.
        """
        if name in ('integrity_service', '_verified_profile_id', '_verified_profile_name'):
            return None
        if name == '_runtime_overrides':
            return {}
        raise AttributeError(name)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Installed by the launcher before task construction; keeping this
        # early is important because config_type option setup reads profiles.
        self.integrity_service = get_default_service()
        self._runtime_overrides = {}
        self._verified_profile_id = None
        self._verified_profile_name = None
        self.name = "📅 每日任务"
        self.support_schedule_task = True
        self.support_tasks = ["Tacet Suppression", "Forgery Challenge", "Simulation Challenge"]
        self.default_config = {
            DAILY_PROFILE: '默认',
            PROFILE_SEQUENCE: '序列1',
            'Which to Farm': self.support_tasks[0],
            'Which Tacet Suppression to Farm': 1,  # starts with 1
            'Which Forgery Challenge to Farm': 1,  # starts with 1
            'Material Selection': 'Shell Credit',
            'Farm Nightmare Nest for Daily Echo': True,
            AUTO_FARM_NIGHTMARE_NEST: False,
            'Nightmare Which to Farm': ['Tacet Discord Nest'],
            'Tacet Discord Nests to Farm': list(NEST_NAMES),
            GARDEN_CHECK_DAY: '无',
            ALIAS_ENABLE: '无',
            ALIAS_TEXT: '',
            LC_GARDEN: '',
            MERGE_ECHO_ON_SUNDAY: False,
            RECORD_AFTER_DAILY: True,
            LOGOUT_AFTER_DAILY: True,
            RECORD_PAGES: list(RECORD_PAGE_OPTIONS),
            RECORD_DURATION: 1.5,
            # 只读展示标签（上次完成时间），不参与配置保存
            LC_TACET: '',
            LC_FORGERY: '',
            LC_SIMULATION: '',
            LC_NIGHTMARE: '',
            LC_AUTO_NIGHTMARE: '',
            LC_NEST: '',
            LC_MERGE: '',
        }
        self.config_description = {
            # 精简版：仅保留必要说明（勾选语义/关键行为），其余删除以节省空间
            DAILY_PROFILE: '',
            PROFILE_SEQUENCE: '先选账号序列，再在下拉中选择该序列内的账号方案（账号多时免翻页）',
            MANAGE_PROFILES: '',
            'Which Tacet Suppression to Farm': '',
            'Which Forgery Challenge to Farm': '',
            'Material Selection': 'Resonator EXP / Weapon EXP / Shell Credit',
            'Farm Nightmare Nest for Daily Echo': '',
            AUTO_FARM_NIGHTMARE_NEST: '勾选 = 刷取全部选中的梦魇巢穴',
            'Nightmare Which to Farm': '勾选 = 刷',
            'Tacet Discord Nests to Farm': '勾选 = 刷，取消勾选 = 跳过',
            GARDEN_CHECK_DAY: '周一~周六选一天检查（周日固定检查，不显示）',
            ALIAS_ENABLE: '备用识别名称：无 = 不设置；使用 = 填写扫码登录显示的账号标识',
            ALIAS_TEXT: '多个用逗号分隔（如 U123456，识别登录界面账号时与手机号掩码同等有效）',
            MERGE_ECHO_ON_SUNDAY: '勾选 = 开启',
            RECORD_AFTER_DAILY: '',
            LOGOUT_AFTER_DAILY: '',
            RECORD_PAGES: '',
            RECORD_DURATION: '',
        }
        material_option_list = ['Resonator EXP', 'Weapon EXP', 'Shell Credit']
        self.config_type = {
            DAILY_PROFILE: {'type': 'drop_down', 'options': self.get_profile_names(
                (self.get_profile_sequences() or ['序列1'])[0])},
            # 方案序列：选序列后「账号配置」下拉随之只显示该序列的方案（两级联动，避免翻页）
            PROFILE_SEQUENCE: {
                'type': 'drop_down',
                'options': self.get_profile_sequences(),
            },
            MANAGE_PROFILES: {'type': 'button', 'text': 'Manage Daily Profiles', 'callback': self.manage_daily_profiles},
            # 导出/导入账号配置已移到「设置 → 数据设置」分组
            # EXPORT_PROFILES: {'type': 'button', 'text': 'Export Account Config', 'callback': self.export_account_config},
            # IMPORT_PROFILES: {'type': 'button', 'text': 'Import Account Config', 'callback': self.import_account_config},
            'Which to Farm': {
                'type': "drop_down",
                'options': self.support_tasks,
                'sub_configs': {
                    'Tacet Suppression': ['Which Tacet Suppression to Farm', LC_TACET],
                    'Forgery Challenge': ['Which Forgery Challenge to Farm', LC_FORGERY],
                    'Simulation Challenge': [
                        'Material Selection', LC_SIMULATION],
                }
            },
            'Material Selection': {
                'type': 'drop_down',
                'options': material_option_list
            },
            'Farm Nightmare Nest for Daily Echo': {
                'sub_configs': {True: [LC_NIGHTMARE], False: []},
            },
            AUTO_FARM_NIGHTMARE_NEST: {
                'sub_configs': {
                    True: [LC_AUTO_NIGHTMARE, 'Nightmare Which to Farm', 'Tacet Discord Nests to Farm', LC_NEST],
                    False: [],
                },
            },
            'Nightmare Which to Farm': {
                'type': 'multi_selection',
                'options': NIGHTMARE_OPTIONS,
            },
            'Tacet Discord Nests to Farm': {
                'type': 'multi_selection',
                'options': NEST_NAMES,
            },
            # 每周乐园检查日：单选一天（周一~周六 + 无）；周日固定检查、不显示
            GARDEN_CHECK_DAY: {
                'type': 'drop_down',
                'options': ['无'] + WEEKDAYS[:6],
            },
            # 备用识别名称：无 / 使用（使用则显示输入框，输入即保存）
            ALIAS_ENABLE: {
                'type': 'drop_down',
                'options': ['无', '使用'],
                'sub_configs': {'使用': [ALIAS_TEXT]},
            },
            ALIAS_TEXT: {'type': 'line_edit'},
            MERGE_ECHO_ON_SUNDAY: {
                'sub_configs': {True: [LC_MERGE], False: []},
            },
            RECORD_AFTER_DAILY: {
                'sub_configs': {True: [RECORD_PAGES, RECORD_DURATION], False: []},
            },
            RECORD_PAGES: {
                'type': 'multi_selection',
                'options': RECORD_PAGE_OPTIONS,
            },
            LC_TACET: {'type': 'label', 'sub_key': 'Tacet Suppression'},
            LC_FORGERY: {'type': 'label', 'sub_key': 'Forgery Challenge'},
            LC_SIMULATION: {'type': 'label', 'sub_key': 'Simulation Challenge'},
            LC_NIGHTMARE: {'type': 'label', 'sub_key': 'Nightmare Nest'},
            LC_AUTO_NIGHTMARE: {'type': 'label', 'sub_key': 'Nightmare Nest'},
            LC_NEST: {'type': 'label', 'sub_key': 'Nightmare Nest'},
            LC_GARDEN: {'type': 'label', 'sub_key': 'Weekly Garden'},
            LC_MERGE: {'type': 'label', 'sub_key': 'Merge Echo'},
        }
        # Stable account intent is display-only.  Runtime selectors (the
        # active profile/sequence) remain controls; account task fields do not.
        if self.integrity_service is not None:
            for _profile_key in PROFILE_KEYS:
                self.config_type[_profile_key] = {'type': 'label'}
        # 迁移旧版"附加任务列表"配置到独立开关
        self._migrate_profiles()
        self.description = "登录、领取月卡、刷声骸并领取每日奖励"
        self._switching_profile = False
        # 启动即同步序列/方案选项（config 可能尚未创建，由 after_init 在配置就绪后真正同步）
        if self.config is not None:
            self._sync_sequence_options()

    def after_init(self, *args, **kwargs):
        """配置加载完成后同步序列/方案选项（修正启动期 config 未创建导致的同步失效）。"""
        try:
            result = super().after_init(*args, **kwargs)
            if self.config is not None:
                self._sync_sequence_options()
            return result
        except Exception as e:
            self.log_error('after_init 同步序列选项失败', e)
            return None

    def run(self):
        if self.integrity_service is not None:
            self.integrity_service.guard_task_start()
            self.ensure_daily_profiles()
        self.validate_daily_tasks()
        self.log_info(f'开始执行每日任务（账号：{self.get_active_profile_name()}）', notify=True)

        WWOneTimeTask.run(self)
        self.logged_in = False
        self.ensure_main(time_out=180)
        self.ensure_daily_profiles()
        self._sync_sequence_options()
        # Child farming tasks still accept the historical ``config`` mapping.
        # Give them a detached snapshot whose protected values come from the
        # validated master, never from stale Config fields.
        profile_runtime_config = self._readonly_profile_config()

        auto_farm = self._profile_get(AUTO_FARM_NIGHTMARE_NEST, False)
        daily_echo = self._profile_get('Farm Nightmare Nest for Daily Echo', False)

        self.log_info('正在领取每日奖励并检查体力进度...')
        used_stamina, daily_reward_ready = self.open_daily()
        need_stamina = not daily_reward_ready and used_stamina < 180
        need_nightmare = auto_farm or (
                daily_echo
                and not daily_reward_ready
                and self._profile_get('Which to Farm', self.support_tasks[0]) != self.support_tasks[0]
        )

        if need_nightmare:
            try:
                # 把合并到每日任务模块的梦魇配置同步给 NightmareNestTask
                nightmare_task = self.get_task_by_class(NightmareNestTask)
                nightmare_task.config['Which to Farm'] = list(
                    self._profile_get('Nightmare Which to Farm', ['Tacet Discord Nest']))
                nightmare_task.config['Tacet Discord Nests to Farm'] = list(
                    self._profile_get('Tacet Discord Nests to Farm', NEST_NAMES))
                # 劫持 NightmareNestTask.ensure_main 避免梦魇打完关书
                nightmare_task.ensure_main = lambda *args, **kwargs: None

                if auto_farm:
                    self.log_info('开始刷梦魇巢穴（打梦魇聚落）', notify=True)
                    self.run_task_by_class(NightmareNestTask)
                elif daily_echo:
                    self.log_info('开始刷梦魇巢穴（打梦魇聚落）', notify=True)
                    nightmare_task.run_capture_mode()
                self.record_last_completed('Nightmare Nest', profile_id=getattr(self, '_verified_profile_id', None))
            except TaskDisabledException:
                raise
            except ConfigIntegrityBlocked:
                raise
            except Exception as e:
                self.log_error("NightmareNestTask Failed", e)
                self.screenshot('NightmareNestTask')
                self.ensure_main(time_out=180)
            finally:
                # 还原 ensure_main，防范实例状态污染
                self.get_task_by_class(NightmareNestTask).__dict__.pop('ensure_main', None)

        if need_stamina:
            target = self._profile_get('Which to Farm', self.support_tasks[0])
            self.log_info(f'开始清体力（打 {target}）', notify=True)
            if target == self.support_tasks[0]:
                self.get_task_by_class(TacetTask).farm_tacet(daily=True, used_stamina=used_stamina,
                                                             config=profile_runtime_config)
            elif target == self.support_tasks[1]:
                self.get_task_by_class(ForgeryTask).farm_forgery(daily=True, used_stamina=used_stamina,
                                                                 config=profile_runtime_config)
            else:
                self.get_task_by_class(SimulationTask).farm_simulation(daily=True, used_stamina=used_stamina,
                                                                       config=profile_runtime_config)
            self.sleep(4)
            self.record_last_completed(target, profile_id=getattr(self, '_verified_profile_id', None))

        self.log_info('正在领取每日任务奖励...')
        self.claim_daily()

        self.claim_mail()
        self.sleep(1)
        self.log_info('正在领取战令奖励...')
        self.claim_battle_pass()
        self.log_info('正在检查每周乐园...')
        self.run_weekly_tasks()
        if self._profile_get(RECORD_AFTER_DAILY, True):
            self.record_progress()
        # 每日任务最后一个环节：自动退登 PC 端（默认开启，取代"完成任务后退出应用"）
        if self._profile_get(LOGOUT_AFTER_DAILY, True):
            try:
                self._logout_pc_after_daily()
            except Exception as e:
                self.log_error('自动退登 PC 端失败（不影响每日任务结果）', e)
        self.log_info('每日任务完成', notify=True)
        # 记录「今日每日任务已完成」到账号方案（多账号任务据此跳过今日已跑的账号）
        try:
            self.record_last_completed('Daily Task', profile_id=getattr(self, '_verified_profile_id', None))
        except ConfigIntegrityBlocked:
            raise

    def _logout_pc_after_daily(self):
        """每日任务完成后自动退登 PC 端，准备下一个账号登录（退登流程在 WWOneTimeTask 基类）。"""
        self.log_info('每日任务完成，自动退登 PC 端准备下一个账号')
        self._ensure_pc_login_screen()

    # ==================== 每日任务配置方案 (Profile) ====================

    def get_profile_names(self, sequence=None):
        """返回配置方案名称列表。

        指定序列时优先用显式归属（sequences 数据：序列→方案列表）；
        无归属数据时按方案名前缀（【X1-】字母）过滤兜底。
        """
        profiles = self.load_daily_profiles()
        names = [n for n in (list(profiles.keys()) or ['默认'])
                if n and str(n).strip().lower() not in ('null', 'none')]
        if sequence:
            seqs = self.get_sequences_data()
            if seqs:
                snames = [n for n in seqs.get(sequence, []) if n in profiles]
                return snames or ['（该序列暂无方案）']
            names = [n for n in names if self._sequence_of_profile(n) == sequence] or ['（该序列暂无方案）']
        return names

    def get_active_profile_name(self):
        """当前激活的配置方案名称。"""
        return self.config.get(DAILY_PROFILE, '默认')

    def _profile_get(self, key, default=None):
        """Read protected account intent from the validated snapshot only."""
        overrides = getattr(self, '_runtime_overrides', None) or {}
        override = overrides.get(key, None)
        if key in overrides:
            return override
        frozen = getattr(self, '_verified_profile_snapshot', None)
        if isinstance(frozen, dict) and key in frozen:
            return copy.deepcopy(frozen.get(key, default))
        if self.integrity_service is not None and key in PROFILE_KEYS:
            profiles = self.load_daily_profiles()
            profile = None
            verified_id = getattr(self, '_verified_profile_id', None)
            if verified_id:
                profile = next((item for item in profiles.values()
                                if isinstance(item, dict) and item.get('profile_id') == verified_id), None)
                if profile is None:
                    raise ConfigIntegrityBlocked(
                        f'validated profile snapshot disappeared: {verified_id}'
                    )
            else:
                # UI construction happens before a task run binds an ID; this
                # fallback is display-only.  Run paths call ensure/bind first.
                profile = profiles.get(getattr(self, '_verified_profile_name', None) or self.get_active_profile_name()) or {}
            return profile.get(key, default)
        return self.config.get(key, default)

    def get_readonly_config_value(self, key):
        return self._profile_get(key, self.config.get(key))

    def _readonly_profile_config(self):
        """Return a detached execution mapping for child task compatibility."""
        result = dict(self.config)
        for key in PROFILE_KEYS:
            result[key] = copy.deepcopy(self._profile_get(key))
        return result

    def bind_verified_profile(self, profile_name, expected_profile_id=None):
        """Bind this run to one validated profile ID, correcting stale labels."""
        profiles = self.load_daily_profiles()
        selected = profiles.get(profile_name) or {}
        profile_id = selected.get('profile_id')
        if not profile_id:
            raise ConfigIntegrityBlocked(f'validated account profile has no stable profile_id: {profile_name}')
        if expected_profile_id is not None and str(profile_id) != str(expected_profile_id):
            raise ConfigIntegrityBlocked(
                f'profile binding mismatch for {profile_name}: expected {expected_profile_id}, got {profile_id}'
            )
        self._verified_profile_name = profile_name
        self._verified_profile_id = str(profile_id)
        self._verified_profile_snapshot = copy.deepcopy(selected)
        return copy.deepcopy(selected)

    @contextmanager
    def runtime_config_override(self, key, value):
        """Temporarily override runtime behavior without touching Config."""
        overrides = getattr(self, '_runtime_overrides', None)
        if not isinstance(overrides, dict):
            overrides = {}
            self._runtime_overrides = overrides
        marker = object()
        old = overrides.get(key, marker)
        overrides[key] = value
        try:
            yield self
        finally:
            if old is marker:
                overrides.pop(key, None)
            else:
                overrides[key] = old

    def load_daily_profiles(self):
        """读取只读总配置的兼容投影；未安装门禁时仅作旧版只读读取。"""
        repository = get_default_repository()
        if repository is not None:
            loader = getattr(repository, 'get_detached_projection', None) or getattr(repository, 'legacy_profile_projection', None)
            if callable(loader):
                projection = loader()
                profiles = projection.get('profiles', {}) if isinstance(projection, dict) else {}
                return copy.deepcopy(profiles) if isinstance(profiles, dict) else {}
        if self.integrity_service is not None:
            result = self.integrity_service.last_result or self.integrity_service.check()
            if result.master_valid and result.master:
                return self.integrity_service.legacy_profile_projection(result.master).get('profiles', {})
            return {}
        data = read_json_file(PROFILE_FILE)
        if data is None:
            return {}
        profiles = data.get('profiles', {})
        return profiles if isinstance(profiles, dict) else {}

    def save_daily_profiles(self, profiles):
        """受保护账号方案禁止由任务代码保存。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account profile changes must be made in account_master_config.json outside the app')
        data = read_json_file(PROFILE_FILE) or {}
        data['profiles'] = profiles
        write_json_file(PROFILE_FILE, data)

    def get_sequences_data(self):
        """读取账号归属序列数据（sequences: {序列名: [方案名...]}）。"""
        # Account/sequence editors publish the master through AccountRepository.
        # Read that projection first so an already-created sequence is visible
        # immediately; the integrity service snapshot may still be from startup.
        repository = get_default_repository()
        if repository is not None:
            try:
                loader = getattr(repository, 'get_detached_projection', None) or getattr(
                    repository, 'legacy_profile_projection', None)
                if callable(loader):
                    projection = loader()
                    sequences = projection.get('sequences', {}) if isinstance(projection, dict) else {}
                    if isinstance(sequences, dict):
                        return copy.deepcopy(sequences)
            except Exception as exc:
                logger.warning(f'account repository sequence projection unavailable: {exc}')
        if self.integrity_service is not None:
            result = self.integrity_service.last_result or self.integrity_service.check()
            if result.master_valid and result.master:
                return self.integrity_service.legacy_profile_projection(result.master).get('sequences', {})
            return {}
        data = read_json_file(PROFILE_FILE)
        if not data:
            return {}
        seqs = data.get('sequences')
        return seqs if isinstance(seqs, dict) else {}

    def save_sequences_data(self, sequences):
        """保存账号归属序列数据到 daily_profiles.json 顶层。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account sequence changes must be made in the read-only master configuration')
        data = read_json_file(PROFILE_FILE) or {}
        data['sequences'] = sequences
        write_json_file(PROFILE_FILE, data)

    def collect_profile_config(self):
        """收集当前 config 中属于"每日任务配置方案"的键值（含梦魇巢穴设置）。"""
        return {key: self.config[key] for key in PROFILE_KEYS if key in self.config}

    def apply_profile_config(self, profile_config):
        """把一套方案的配置值应用到当前 config。"""
        if self.integrity_service is not None:
            # Protected account fields must never be copied into Config.  The
            # validated snapshot is read through _profile_get at execution.
            return False
        for key, value in profile_config.items():
            if key in self.config:
                self.config[key] = value
        return True

    def _merge_profile(self, existing, config_values):
        """把收集到的配置合并进方案，同时保留方案中的非配置数据（如上次完成时间）。"""
        merged = dict(config_values)
        if isinstance(existing, dict):
            for field in PROFILE_EXTRA_FIELDS:
                if field in existing:
                    merged[field] = existing[field]
        return merged

    # ==================== 账号别名（扫码登录的 U 开头账号等备用标识） ====================

    def get_profile_aliases(self, profile_name):
        """读取方案的账号别名列表（如扫码登录的 U 开头账号）。"""
        profiles = self.load_daily_profiles()
        profile = profiles.get(profile_name) or {}
        aliases = profile.get('account_aliases') or []
        return list(aliases) if isinstance(aliases, list) else []

    def set_profile_aliases(self, profile_name, aliases):
        """设置方案的账号别名列表（保存到 daily_profiles.json 的 account_aliases 字段）。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account aliases are read-only in the application')
        profiles = self.load_daily_profiles()
        if profile_name not in profiles:
            return False
        profile = profiles[profile_name]
        profile['account_aliases'] = [a.strip() for a in aliases if a and a.strip()]
        self.save_daily_profiles(profiles)
        return True

    def ensure_daily_profiles(self):
        """确保至少存在一个方案（默认），并保证当前激活方案有效。"""
        if self.integrity_service is not None:
            # Creation/defaulting is explicitly outside the main process.  The
            # startup guard handles missing/invalid master files before a task
            # can reach this method.
            if not self.integrity_service.is_safe:
                raise ConfigIntegrityBlocked(self.integrity_service.describe())
            profiles = self.load_daily_profiles()
            if not profiles:
                raise ConfigIntegrityBlocked('validated master configuration has no profiles')
            active = self.config.get(DAILY_PROFILE)
            if active not in profiles:
                self._switching_profile = True
                try:
                    self.config[DAILY_PROFILE] = next(iter(profiles))
                finally:
                    self._switching_profile = False
                active = self.config.get(DAILY_PROFILE)
            self.bind_verified_profile(active)
            return
        profiles = self.load_daily_profiles()
        if not profiles:
            profiles['默认'] = self._merge_profile(profiles.get('默认'), self.collect_profile_config())
            self.save_daily_profiles(profiles)
        if DAILY_PROFILE not in self.config:
            self._switching_profile = True
            try:
                self.config[DAILY_PROFILE] = '默认'
            finally:
                self._switching_profile = False
        active = self.config.get(DAILY_PROFILE)
        if active not in profiles:
            first = next(iter(profiles))
            self._switching_profile = True
            try:
                self.config[DAILY_PROFILE] = first
                self.apply_profile_config(profiles[first])
            finally:
                self._switching_profile = False

    def _migrate_profiles(self):
        """把旧版"附加任务列表"迁移为独立开关，并补齐各方案缺失的配置键。

        旧格式的 'Additional Tasks to Run After Daily Task' 列表会被转换：
        - Check Weekly Garden        → 若未设置检查日，则默认全部勾选
        - Auto Farm all Nightmare Nest → AUTO_FARM_NIGHTMARE_NEST = True
        - Merge Echo If discarded > 1000 → MERGE_ECHO_ON_SUNDAY = True
        迁移完成后删除旧键，避免污染新方案。
        """
        if self.integrity_service is not None:
            return
        try:
            profiles = self.load_daily_profiles()
            if not isinstance(profiles, dict) or not profiles:
                return
            changed = False
            defaults = {key: self.default_config.get(key) for key in PROFILE_KEYS}
            old_merge = 'Merge Echo If discarded > 1000'
            for profile in profiles.values():
                if not isinstance(profile, dict):
                    continue
                additional = profile.pop(ADDITIONAL_TASKS, None)
                if isinstance(additional, list):
                    changed = True
                    if CHECK_WEEKLY_GARDEN in additional and not profile.get(GARDEN_CHECK_DAY):
                        profile[GARDEN_CHECK_DAY] = '无'
                    if AUTO_FARM_NIGHTMARE_NEST in additional:
                        profile[AUTO_FARM_NIGHTMARE_NEST] = True
                    if old_merge in additional:
                        profile[MERGE_ECHO_ON_SUNDAY] = True
                # 迁移旧版多选周几 → 单选一天（取第一个非周日；全为周日/空 → 无）
                old_days = profile.get(WEEKLY_GARDEN_CHECK_DAYS)
                if isinstance(old_days, list):
                    day = next((d for d in old_days if d != WEEKDAYS[6]), '无')
                    profile[GARDEN_CHECK_DAY] = day
                    profile.pop(WEEKLY_GARDEN_CHECK_DAYS, None)
                    changed = True
                for key, default in defaults.items():
                    if key not in profile:
                        profile[key] = default
                        changed = True
            if changed:
                self.save_daily_profiles(profiles)
        except Exception as e:
            self.log_error('migrate daily profiles failed', e)

    def switch_profile(self, name):
        """切换到指定配置方案（保存当前配置到旧方案，加载新方案）。

        注意：从管理对话框调用时不在内部刷新 UI（模态窗口期间重建会白屏），
        由 manage_daily_profiles 在对话框关闭后统一刷新。
        """
        old = self.config.get(DAILY_PROFILE)
        if old == name:
            return
        self._switching_profile = True
        try:
            self._do_switch_profile(old, name)
            self.config[DAILY_PROFILE] = name
        finally:
            self._switching_profile = False

    def _do_switch_profile(self, old, new):
        if not new or str(new).strip().lower() in ('null', 'none'):
            # 空/None/"null" 不做切换（防下拉空白被当方案名，创建 null 方案并污染当前方案）
            return
        profiles = self.load_daily_profiles()
        if self.integrity_service is not None:
            if new not in profiles:
                raise ConfigIntegrityBlocked(f'unknown validated account profile: {new}')
            self.bind_verified_profile(new)
            return
        if old and old in profiles:
            profiles[old] = self._merge_profile(profiles.get(old), self.collect_profile_config())
        if new not in profiles:
            profiles[new] = self._merge_profile(profiles.get(new), self.collect_profile_config())
        # 调试日志：记录切换目标与实际加载内容（排查"选 A 出 B"）
        self.log_info(f'切换方案：{old} -> {new}（加载配置: 刷取={profiles[new].get("Which to Farm", "?")}, '
                      f'别名={(profiles[new].get("备用识别名称内容") or "")[:15]}）')
        self.apply_profile_config(profiles[new])
        self.save_daily_profiles(profiles)

    def create_profile(self, name):
        """用当前配置创建新方案，并切换到该方案（旧方案保持不变）。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account profiles are read-only in the application')
        if not name or name in self.get_profile_names():
            return False
        profiles = self.load_daily_profiles()
        profiles[name] = self._merge_profile(profiles.get(name), self.collect_profile_config())
        self.save_daily_profiles(profiles)
        # 直接切换到新方案，不把当前配置写回旧方案（旧方案保持原样）
        # 注意：不在此处刷新 UI——模态对话框打开期间重建任务列表会导致白屏，
        # 统一在 manage_daily_profiles 中对话框关闭后刷新
        self._switching_profile = True
        try:
            self.config[DAILY_PROFILE] = name
        finally:
            self._switching_profile = False
        return True

    def rename_profile(self, old, new):
        """重命名方案。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account profiles are read-only in the application')
        profiles = self.load_daily_profiles()
        if old not in profiles or not new or new in profiles:
            return False
        profiles[new] = profiles.pop(old)
        self.save_daily_profiles(profiles)
        if self.config.get(DAILY_PROFILE) == old:
            self._switching_profile = True
            try:
                self.config[DAILY_PROFILE] = new
            finally:
                self._switching_profile = False
        return True

    def delete_profile(self, name):
        """删除方案，若删除的是当前方案则切换到剩余第一个。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account profiles are read-only in the application')
        profiles = self.load_daily_profiles()
        if name not in profiles:
            return False
        del profiles[name]
        if self.config.get(DAILY_PROFILE) == name:
            remaining = list(profiles.keys())
            if remaining:
                self._switching_profile = True
                try:
                    self.apply_profile_config(profiles[remaining[0]])
                    self.config[DAILY_PROFILE] = remaining[0]
                finally:
                    self._switching_profile = False
            else:
                profiles['默认'] = self._merge_profile(profiles.get('默认'), self.collect_profile_config())
                self.config[DAILY_PROFILE] = '默认'
        self.save_daily_profiles(profiles)
        return True

    # ==================== 上次完成时间记录 ====================

    def _active_profile_id(self, profile_id=None):
        """Resolve a stable ID only for compatibility with old call sites."""
        if profile_id:
            return str(profile_id)
        value = getattr(self, '_verified_profile_id', None)
        return str(value) if value else None

    def _readonly_active_profile_id(self):
        verified_id = getattr(self, '_verified_profile_id', None)
        if verified_id:
            return verified_id
        profile = self.load_daily_profiles().get(self.get_active_profile_name()) or {}
        return profile.get('profile_id')

    def record_last_completed(self, task_name, profile_id=None):
        """Record completion in runtime state under an explicit stable profile ID."""
        try:
            if self.integrity_service is not None:
                resolved_id = self._active_profile_id(profile_id)
                if not resolved_id:
                    raise ConfigIntegrityBlocked('completion record requires a validated profile_id')
                self.integrity_service.record_completion(resolved_id, task_name)
                return
            profiles = self.load_daily_profiles()
            active = self.get_active_profile_name()
            profile = profiles.get(active)
            if not isinstance(profile, dict):
                profile = {}
            last = profile.get('last_completed')
            if not isinstance(last, dict):
                last = {}
            last[task_name] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            profile['last_completed'] = last
            profiles[active] = profile
            self.save_daily_profiles(profiles)
        except ConfigIntegrityBlocked:
            raise
        except Exception as e:
            self.log_error('record last completed failed', e)

    def get_last_completed(self, task_name):
        """Read completion from runtime state for the active stable profile."""
        try:
            if self.integrity_service is not None:
                profile_id = self._readonly_active_profile_id()
                return self.integrity_service.get_completion(profile_id, task_name) if profile_id else None
            profiles = self.load_daily_profiles()
            active = self.get_active_profile_name()
            profile = profiles.get(active) or {}
            last = profile.get('last_completed') or {}
            return last.get(task_name)
        except ConfigIntegrityBlocked:
            raise
        except Exception:
            return None

    def export_account_config(self, *args):
        """导出账号配置（全部方案 + 激活方案）为 JSON 文件，便于跨电脑迁移。"""
        try:
            service = self._get_account_bundle_service()
            default_name = f'okww_账号配置_{datetime.now():%Y%m%d_%H%M%S}.json'
            path = self._ask_save_path(default_name)
            if not path:
                return
            if service is not None:
                exported = self._invoke_bundle_service(
                    service, ('export_bundle', 'export'), path=path, task=self)
                master = exported.get('master_config', {}) if isinstance(exported, dict) else {}
                runtime = exported.get('runtime_data', {}) if isinstance(exported, dict) else {}
                profiles = master.get('profiles', {}) if isinstance(master, dict) else {}
                sequences = master.get('sequences', {}) if isinstance(master, dict) else {}
                completed = runtime.get('completed_at', {}) if isinstance(runtime, dict) else {}
                runtime_count = (sum(len(records) for records in completed.values()
                                     if isinstance(records, dict))
                                 if isinstance(completed, dict) else 0)
                self.log_info(
                    f'已从已验证总配置导出账号配置包 v2: {path}（{len(profiles)} 个账号、'
                    f'{len(sequences)} 个序列、{runtime_count} 条完成记录）', notify=True)
                return
            if self.integrity_service is not None:
                raise ConfigWriteBlocked('账号配置包 v2 服务不可用；未回退导出旧 v1 文件')
            profiles = self.load_daily_profiles()
            if not profiles:
                self.log_info('当前没有账号方案可导出')
                return
            active = self.get_active_profile_name()
            payload = {
                'type': ACCOUNT_CONFIG_TYPE,
                'version': ACCOUNT_CONFIG_VERSION,
                'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'active_profile': active if active in profiles else '',
                'profiles': profiles,
                'sequences': self.get_sequences_data(),
            }
            write_json_file(path, payload)
            self.log_info(f'账号配置已导出（兼容 v1）: {path}（{len(profiles)} 个方案）', notify=True)
        except Exception as e:
            self.log_error('导出账号配置失败', e)

    def import_account_config(self, *args):
        """从 JSON 文件导入账号配置（导入前自动备份现有配置）。"""
        try:
            service = self._get_account_bundle_service()
            path = self._ask_open_path()
            if not path:
                return
            if service is not None:
                summary = self._invoke_bundle_service(
                    service, ('preflight_import', 'preflight'), path=path, task=self)
                self.log_info(f'导入预检摘要: {self._bundle_summary_text(summary)}')
                summary_errors = (getattr(summary, 'errors', None)
                                  if not isinstance(summary, dict) else summary.get('errors'))
                summary_trust = (getattr(summary, 'trust_required', False)
                                 if not isinstance(summary, dict) else summary.get('trust_required', False))
                summary_ok = (getattr(summary, 'ok', True)
                              if not isinstance(summary, dict) else summary.get('ok', True))
                if summary_errors or (summary_ok is False and not summary_trust):
                    self.log_error('账号配置包预检失败，未写入任何文件')
                    return
                if not self._confirm_bundle_import(summary):
                    self.log_info('已取消账号配置包导入')
                    return
                self._invoke_bundle_service(
                    service, ('import_bundle', 'import_config', 'import_bundle_v2', 'import'),
                    path=path, task=self, confirmed=True, trust_external=bool(summary_trust),
                    preflight=summary)
                self.log_info(f'账号配置包已导入: {path}', notify=True)
                self._refresh_gui()
                return
            if self.integrity_service is not None:
                raise ConfigWriteBlocked(
                    'account profile imports are disabled; edit the master configuration outside the application'
                )
            data = read_json_file(path)
            if not data or data.get('type') != ACCOUNT_CONFIG_TYPE:
                self.log_error('文件格式不正确：不是有效的账号配置导出文件')
                return
            profiles = data.get('profiles') or {}
            if not isinstance(profiles, dict) or not profiles:
                self.log_error('导出文件中没有账号方案')
                return
            # 防污染：过滤空/null/none 方案键（防止导入时把异常方案写回配置）
            profiles = {k: v for k, v in profiles.items()
                        if k and str(k).strip().lower() not in ('null', 'none')}
            # 导入前备份现有配置（每日任务 + 多账号每日任务数据一同备份）
            try:
                import shutil
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                for f in (PROFILE_FILE, MULTI_ACCOUNT_CONFIG_FILE):
                    if os.path.exists(f):
                        backup = f + f'.bak_import_{ts}'
                        shutil.copy2(f, backup)
                        self.log_info(f'已备份: {backup}')
            except Exception as e:
                self.log_error('备份现有配置失败（继续导入）', e)
            # 写入新方案（含序列归属）
            self.save_daily_profiles(profiles)
            seqs = data.get('sequences')
            if isinstance(seqs, dict):
                self.save_sequences_data(seqs)
            # 设置激活方案（不保存旧方案——防止把当前（可能被污染的）配置写回覆盖刚导入的干净数据）
            active = data.get('active_profile', '')
            if active not in profiles:
                active = list(profiles.keys())[0]
            try:
                self._switching_profile = True
                try:
                    self.config[DAILY_PROFILE] = active
                    self.apply_profile_config(profiles.get(active) or {})
                finally:
                    self._switching_profile = False
            except Exception as e:
                self.log_error('切换激活方案失败', e)
            self.log_info(f'账号配置已导入: {path}（{len(profiles)} 个方案，激活 {active}）', notify=True)
            # 刷新界面
            try:
                self._sync_profile_options()
                self._refresh_gui()
            except Exception as e:
                self.log_error('导入后刷新界面失败', e)
        except Exception as e:
            self.log_error('导入账号配置失败', e)

    def _get_account_bundle_service(self):
        """Resolve the account bundle v2 service without a hard import edge."""
        injected = getattr(self, 'account_bundle_service', None)
        if injected is not None:
            return injected
        for module_name in ('src.account_config_bundle', 'src.account_bundle',
                            'src.account_bundle_service', 'src.services.account_bundle'):
            try:
                module = importlib.import_module(module_name)
            except (ImportError, ModuleNotFoundError):
                continue
            for factory_name in ('get_default_service', 'get_account_bundle_service'):
                factory = getattr(module, factory_name, None)
                if callable(factory):
                    return factory()
            for class_name in ('AccountBundleService', 'AccountConfigBundleService'):
                cls = getattr(module, class_name, None)
                if cls is not None:
                    try:
                        if class_name == 'AccountConfigBundleService':
                            return cls(transaction_snapshot_hook=self._transaction_snapshot_hook)
                        return cls()
                    except Exception as exc:
                        raise RuntimeError(f'账号配置包服务构造失败: {exc}') from exc
        return None

    def _transaction_snapshot_hook(self, _before=None):
        """Provide the core bundle service with the governed snapshot store."""
        snapshot = self._config_backup_service().create_transaction_snapshot()
        return snapshot.path

    @staticmethod
    def _invoke_bundle_service(service, method_names, **kwargs):
        for method_name in method_names:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue
            try:
                signature = inspect.signature(method)
            except (TypeError, ValueError):
                # Signature introspection can be unavailable for extension
                # methods. Make exactly one call; never retry after method
                # execution raises (imports/exports have side effects).
                positional = kwargs.get('path')
                return method(positional) if positional is not None else method()
            accepted = {k: v for k, v in kwargs.items() if k in signature.parameters}
            # Core adapter names are source/destination/confirm; the UI
            # intentionally speaks in path/confirmed terms.
            if 'path' in kwargs and 'destination' in signature.parameters:
                accepted['destination'] = kwargs['path']
            if 'path' in kwargs and 'source' in signature.parameters:
                accepted['source'] = kwargs['path']
            if 'confirmed' in kwargs and 'confirm' in signature.parameters:
                accepted['confirm'] = kwargs['confirmed']
            if any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values()):
                accepted = kwargs
            return method(**accepted)
        raise AttributeError(f'account bundle service has no supported method: {method_names}')

    @staticmethod
    def _bundle_summary_text(summary):
        if isinstance(summary, str):
            return summary
        if hasattr(summary, 'as_dict'):
            summary = summary.as_dict()
        elif hasattr(summary, '__dataclass_fields__'):
            summary = {name: getattr(summary, name) for name in summary.__dataclass_fields__}
        if isinstance(summary, dict):
            return ', '.join(f'{k}={v}' for k, v in summary.items()
                             if v not in (None, '', [], {}, False)) or '无差异'
        return str(summary)

    def _confirm_bundle_import(self, summary):
        """Show a second confirmation; integrations/tests may override this."""
        try:
            from PySide6.QtWidgets import QMessageBox
            from ok import og
            parent = getattr(og, 'main_window', None)
            trust_required = (summary.get('trust_required', False)
                              if isinstance(summary, dict)
                              else getattr(summary, 'trust_required', False))
            if trust_required:
                message = ('清单哈希已改变，文件可能在导出后被修改。\n'
                           f'{self._bundle_summary_text(summary)}\n'
                           '确认信任此外部修改并替换总配置、恢复运行数据？')
            else:
                message = (f'导入预检摘要：{self._bundle_summary_text(summary)}\n'
                           '确认替换总配置并恢复运行数据？')
            answer = QMessageBox.question(
                parent, '确认导入账号配置包',
                message,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return answer == QMessageBox.Yes
        except Exception:
            return False

    def _config_backup_service(self):
        from src.config_backup import ConfigBackupService
        backup_dir = os.path.join(os.getcwd(), 'configs_backup')
        try:
            from ok import og
            value = og.executor.global_config.get_config('Config Backup') or {}
            backup_dir = value.get('Config Backup Directory') or backup_dir
        except Exception:
            pass
        return ConfigBackupService(get_relative_path('configs'), backup_dir)

    def verify_backup(self, *args):
        """Verify a user-selected complete backup without changing config."""
        path = self._ask_backup_path(open_mode=True)
        if not path:
            return None
        result = self._config_backup_service().verify_snapshot(path)
        message = ('备份验证通过' if result.ok else '备份验证失败')
        self.log_info(f'{message}: {self._bundle_summary_text(result)}', notify=True)
        return result

    def restore_backup(self, *args):
        """Preflight and confirm a complete backup before transactional restore."""
        path = self._ask_backup_path(open_mode=True)
        if not path:
            return None
        service = self._config_backup_service()
        summary = service.preflight_restore(path)
        self.log_info(f'恢复预检摘要: {self._bundle_summary_text(summary)}')
        if not summary.ok or not self._confirm_backup_restore(summary):
            self.log_info('已取消或拒绝配置备份恢复')
            return summary
        service.restore(path, confirmed=True)
        self.log_info('配置备份已事务恢复，请重启程序后继续任务', notify=True)
        return summary

    def _confirm_backup_restore(self, summary):
        """Confirm a complete configs-tree replacement separately from import."""
        try:
            from PySide6.QtWidgets import QMessageBox
            from ok import og
            parent = getattr(og, 'main_window', None)
            answer = QMessageBox.question(
                parent, '确认恢复完整配置备份',
                f'恢复预检摘要：{self._bundle_summary_text(summary)}\n'
                '这会替换整个 configs 目录，恢复完成后必须重启程序。确认恢复？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return answer == QMessageBox.Yes
        except Exception:
            return False

    def repair_legacy_sequences(self, *args):
        """Inspect and explicitly confirm the core missing-sequence repair."""
        integrity = getattr(self, 'integrity_service', None)
        if integrity is None:
            self.log_info('完整性服务尚未安装；未写入任何文件')
            return None
        detection = integrity.detect_missing_sequences()
        self.log_info('遗漏序列预检: ' + self._bundle_summary_text(detection))
        if not detection.get('eligible'):
            self.log_info('当前没有可恢复的旧版遗漏序列；未写入任何文件')
            return None
        if not self._confirm_legacy_sequence_repair(detection):
            self.log_info('已取消旧版遗漏序列恢复')
            return None
        snapshot_path = self._transaction_snapshot_hook()
        self.log_info(f'遗漏序列恢复前事务快照已创建: {snapshot_path}')
        return integrity.repair_missing_sequences(confirm=True)

    def _confirm_legacy_sequence_repair(self, detection):
        try:
            from PySide6.QtWidgets import QMessageBox
            from ok import og
            parent = getattr(og, 'main_window', None)
            answer = QMessageBox.question(
                parent, '确认恢复旧版遗漏序列',
                f"发现 {detection.get('sequence_count', 0)} 个序列、"
                f"{detection.get('account_count', 0)} 个账号。确认恢复？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return answer == QMessageBox.Yes
        except Exception:
            return False

    def _ask_backup_path(self, open_mode=True):
        try:
            from PySide6.QtWidgets import QFileDialog
            from ok import og
            parent = getattr(og, 'main_window', None)
            return QFileDialog.getExistingDirectory(parent, '选择配置备份目录') or None
        except Exception:
            return None

    def _ask_save_path(self, default_name):
        """弹出保存对话框；默认路径为数据仓库（ok仓库/账号数据），无 GUI 环境时回退项目 export_accounts/。"""
        try:
            from PySide6.QtWidgets import QFileDialog
            from ok import og
            parent = None
            try:
                parent = og.main_window
            except Exception:
                pass
            initial = default_name
            try:
                from src.storage import get_warehouse_sub
                wh = get_warehouse_sub('账号数据')
                if wh:
                    initial = os.path.join(wh, default_name)
            except Exception:
                pass
            path, _ = QFileDialog.getSaveFileName(parent, '导出账号配置', initial, 'JSON (*.json)')
            return path if path else None
        except Exception:
            out_dir = get_relative_path('export_accounts')
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError:
                pass
            return os.path.join(out_dir, default_name)

    def _ask_open_path(self):
        """弹出打开对话框；无 GUI 环境时回退到项目 export_accounts/ 目录。"""
        try:
            from PySide6.QtWidgets import QFileDialog
            from ok import og
            parent = None
            try:
                parent = og.main_window
            except Exception:
                pass
            path, _ = QFileDialog.getOpenFileName(parent, '导入账号配置', '', 'JSON (*.json)')
            return path if path else None
        except Exception:
            fallback_dir = get_relative_path('export_accounts')
            if os.path.isdir(fallback_dir):
                files = sorted(os.listdir(fallback_dir))
                if files:
                    return os.path.join(fallback_dir, files[-1])
            return None

    def manage_daily_profiles(self, *args):
        """打开配置方案管理对话框，关闭后延迟刷新界面。"""
        if self.integrity_service is not None:
            self.log_info('账号方案由只读总配置管理；请在主程序外编辑并重新检查')
            return False
        from src.gui.DailyProfileDialog import DailyProfileDialog
        parent = None
        try:
            from ok import og
            parent = og.main_window
        except Exception:
            pass
        dlg = DailyProfileDialog(self, parent)
        dlg.exec()
        # 对话框关闭后延迟到事件循环稳定再刷新，
        # 避免模态窗口关闭瞬间重建任务列表导致界面空白
        from PySide6.QtCore import QTimer

        def _delayed_refresh():
            try:
                self._sync_profile_options()
                self._refresh_gui()
            except Exception as e:
                self.log_error('refresh daily profiles ui failed', e)

        QTimer.singleShot(200, _delayed_refresh)

    def _sync_profile_options(self):
        """同步下拉框的 options 列表。

        仅更新 config_type 中的选项列表（新建/重命名/删除方案后调用），
        不重建整个任务列表——重建在模态对话框场景下会导致界面空白。
        新方案会在下次进入任务页/重启程序时出现在下拉框中。
        """
        if DAILY_PROFILE in self.config_type and isinstance(self.config_type[DAILY_PROFILE], dict):
            self.config_type[DAILY_PROFILE]['options'] = self.get_profile_names()
        self._sync_sequence_options()

    def get_profile_sequences(self):
        """返回序列列表。

        优先用显式归属数据（sequences 的键，形如 序列1/序列2）；无归属数据时按
        方案名前缀字母映射兜底（【A1-】→序列1、【B1-】→序列2…）。
        """
        seqs = self.get_sequences_data()
        if seqs:
            return list(seqs.keys())
        profiles = self.load_daily_profiles()
        result = []
        for name in profiles.keys():
            label = self._sequence_of_profile(name)
            if label not in result:
                result.append(label)
        return result or ['序列1']

    def _sequence_of_profile(self, name):
        """返回方案名所属的序列显示名（【A1-…】前缀字母 → 序列N：A=序列1、B=序列2…）。"""
        m = re.match(r'【?([A-Za-z])', str(name))
        if not m:
            return '其他'
        letter = m.group(1).upper()
        idx = 'ABCDEFGHIJ'.find(letter)
        return f'序列{idx + 1}' if idx >= 0 else '其他'

    def _sync_sequence_options(self):
        """更新「方案序列」下拉 options，并按当前选择的序列过滤「账号配置」下拉 options。"""
        if self.config is None:
            return
        try:
            if PROFILE_SEQUENCE in self.config_type and isinstance(self.config_type[PROFILE_SEQUENCE], dict):
                seqs = self.get_profile_sequences()
                self.config_type[PROFILE_SEQUENCE]['options'] = seqs
            if DAILY_PROFILE in self.config_type and isinstance(self.config_type[DAILY_PROFILE], dict):
                seq = (self.config.get(PROFILE_SEQUENCE) or '').strip()
                if not seq:
                    seqs = self.get_profile_sequences()
                    seq = seqs[0] if seqs else ''
                    try:
                        self.config[PROFILE_SEQUENCE] = seq
                    except Exception:
                        pass
                self.config_type[DAILY_PROFILE]['options'] = self.get_profile_names(seq or None)
        except Exception as e:
            self.log_error('同步序列选项失败', e)

    def _update_dropdown_items(self, key, options):
        """直接更新任务卡片中指定下拉控件的选项（单控件更新，不重建——避免白屏）。"""
        try:
            from ok import og
            if not og.main_window or not hasattr(og.main_window, 'onetime_tab'):
                return
            for card in getattr(og.main_window.onetime_tab, 'card_widgets', []):
                if getattr(card, 'task', None) is not self:
                    continue
                for w in getattr(card, 'config_widgets', []):
                    if getattr(w, 'key', None) == key and hasattr(w, 'combo_box'):
                        combo = w.combo_box
                        # 同步 LabelAndDropDown 的 tr_dict/tr_options（显示文本→原始方案名 映射），
                        # 否则切换序列后下拉无法还原方案名、写入 None 导致切换失效
                        try:
                            if hasattr(w, 'tr_dict') and hasattr(w, 'tr_options'):
                                w.tr_dict = {og.app.tr(o): o for o in options}
                                w.tr_options = [og.app.tr(o) for o in options]
                        except Exception:
                            pass
                        display_options = w.tr_options if hasattr(w, 'tr_options') else options
                        try:
                            combo.blockSignals(True)
                            combo.clear()
                            combo.addItems(display_options)
                        finally:
                            # 无论成败都恢复信号（防 blockSignals 遗留导致下拉失灵/不触发保存）
                            combo.blockSignals(False)
                        # 防空白：当前方案在选项中则显示它，否则显示第一项（避免偶发空白/不显示）
                        try:
                            cur = self.config.get(DAILY_PROFILE) if key == DAILY_PROFILE else None
                            if cur and cur in options:
                                combo.setCurrentText(og.app.tr(cur))
                            elif options:
                                combo.setCurrentIndex(0)
                        except Exception:
                            pass
                        return
        except Exception:
            pass

    def _refresh_gui(self):
        """刷新当前任务卡片显示（安全版：只刷新控件值，不重建任务页——重建会导致界面空白）。

        注意：导入/新建方案后，新方案名要下次进入任务页/重启后才出现在下拉框中
        （重建任务页有白屏风险，故不采用）。
        """
        try:
            from ok import og
            if og.main_window and hasattr(og.main_window, 'onetime_tab'):
                for card in getattr(og.main_window.onetime_tab, 'card_widgets', []):
                    if getattr(card, 'task', None) is self:
                        card.update_config()
                        break
        except Exception as e:
            self.log_error('刷新界面失败', e)

    def validate_config(self, key, value):
        """当 Daily Profile 下拉框变化时，自动保存旧方案并加载新方案。

        注意：在 Config.__setitem__ 的 validate 阶段执行，config 尚未写入新值，
        因此 UI 刷新必须延迟到写入完成之后进行。
        """
        if self.config is None:
            return None
        if key == DAILY_PROFILE and not self._switching_profile:
            if not value:
                return None
            old = self.config.get(DAILY_PROFILE)
            # old 为 None/null（当前未选方案）时也必须加载新方案，
            # 否则主界面下拉切换不会触发 _do_switch_profile，界面显示旧配置（各账号"一样"）
            if old != value:
                self._switching_profile = True
                try:
                    self._do_switch_profile(old, value)
                finally:
                    self._switching_profile = False
                # 延迟刷新：等 __setitem__ 写入完成、事件循环稳定后再刷新控件显示
                from PySide6.QtCore import QTimer

                def _delayed_refresh():
                    try:
                        self._refresh_gui()
                    except Exception as e:
                        self.log_error('refresh daily profiles ui failed', e)

                QTimer.singleShot(0, _delayed_refresh)
        elif key == PROFILE_SEQUENCE and not self._switching_profile:
            # 切换序列 → 「账号配置」下拉随之只显示该序列的方案（即时更新单控件，不重建）
            seq = value or ''
            names = self.get_profile_names(seq or None)
            if DAILY_PROFILE in self.config_type and isinstance(self.config_type[DAILY_PROFILE], dict):
                self.config_type[DAILY_PROFILE]['options'] = names
            self._update_dropdown_items(DAILY_PROFILE, names)
        return None

    def validate_daily_tasks(self):
        if self._profile_get(AUTO_FARM_NIGHTMARE_NEST) and not self._profile_get('Nightmare Which to Farm'):
            # NightmareNestTask 已整合进每日任务模块，校验基于每日任务里的可见配置
            raise Exception(
                self.tr(
                    'Auto Farm all Nightmare Nest requires at least one "Which to Farm" option.'
                )
            )
        return True

    def run_weekly_tasks(self):
        # 每周乐园：所选日期 + 每周日（必跑）
        self.check_weekly_garden()
        # 声骸融合：每周日运行一次
        if self._profile_get(MERGE_ECHO_ON_SUNDAY) and WEEKDAYS[datetime.now().weekday()] == WEEKDAYS[6]:
            self.check_discarded_echo()

    def check_weekly_garden(self):
        self.info_set('current task', 'check weekly garden')
        self.log_info('正在检查每周乐园...')
        # 运行规则：每周日固定检查一次；此外可在所选的一天（周一~周六）检查。
        # 所选日检查到未完成时运行；若运行一半被关闭（未确认完成），下次启动到检查日会再次检查。
        check_day = (self._profile_get(GARDEN_CHECK_DAY) or '无').strip()
        today = WEEKDAYS[datetime.now().weekday()]
        if today == WEEKDAYS[6]:
            self.log_info('今天是周日，每周乐园强制检查')
        elif today != check_day:
            self.log_info(f'今天是 {today}，乐园检查日为 {check_day}，跳过')
            return
        try:
            garden_task = self.get_task_by_class(GardenTask)
            garden_task.open_garden_weekly_page()
            if garden_task.is_weekly_garden_completed():
                self.log_info('每周乐园已完成，跳过')
                self.record_last_completed('Weekly Garden', profile_id=getattr(self, '_verified_profile_id', None))
                return
            self.log_info('每周乐园未完成，开始打每周乐园', notify=True)
            self.run_task_by_class(GardenTask)
            self.record_last_completed('Weekly Garden', profile_id=getattr(self, '_verified_profile_id', None))
        except TaskDisabledException:
            raise
        except ConfigIntegrityBlocked:
            raise
        except Exception as e:
            self.log_error("GardenTask Failed", e)
            self.screenshot('GardenTask')
            self.ensure_main(time_out=180)

    def check_discarded_echo(self):
        self.info_set('current task', 'check discarded echo')
        self.log_info('check discarded echo')
        merge_echo_task = self.get_task_by_class(MergeEchoTask)
        old_notify_if_not_enough = merge_echo_task.notify_if_not_enough
        try:
            merge_echo_task.notify_if_not_enough = False
            self.run_task_by_class(MergeEchoTask)
            self.record_last_completed('Merge Echo', profile_id=getattr(self, '_verified_profile_id', None))
        except TaskDisabledException:
            raise
        except ConfigIntegrityBlocked:
            raise
        except Exception as e:
            self.log_error("MergeEchoTask Failed", e)
            self.screenshot('MergeEchoTask')
            self.ensure_main(time_out=180)
        finally:
            merge_echo_task.notify_if_not_enough = old_notify_if_not_enough

    # ==================== 每日任务完成后录像（进度留档） ====================

    def record_progress(self):
        """每日任务完成后，按选中顺序打开页面，把各页画面合成 1 个监控视频。

        视频只包含鸣潮游戏窗口画面（基于 WGC 捕获帧）。
        存储：okww监控室/【账号方案名】/【YYYY-MM-DD HH-MM-SS】.mp4
        同一天运行多次每日任务会生成多个时间文件（一天 1~3 段）。
        """
        import os

        import cv2
        from datetime import datetime

        pages = self._profile_get(RECORD_PAGES) or []
        if not pages:
            self.log_info('record pages empty, skip recording')
            return
        try:
            duration = int(float(self._profile_get(RECORD_DURATION, 3)))
        except (TypeError, ValueError):
            duration = 3
        fps = 5

        profile_name = self.get_active_profile_name() or '未命名'
        # 录像保存位置：优先数据仓库（设置 → 通用设置 → 数据仓库文件夹）→ ok仓库\okww监控室；未设置用程序目录
        out_dir = None
        try:
            from src.storage import get_warehouse_sub
            wh = get_warehouse_sub('okww监控室')
            if wh:
                out_dir = os.path.join(wh, profile_name)
        except Exception:
            pass
        if out_dir is None:
            out_dir = get_relative_path('okww监控室', profile_name)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            self.log_error(f'create monitor dir failed: {e}')
            return
        fname = os.path.join(out_dir, f'【{datetime.now():%Y-%m-%d %H-%M-%S}】.mp4')

        writer = None
        recorded_pages = []
        try:
            for page in pages:
                try:
                    if not self._open_record_page(page):
                        continue
                    frame = self.frame
                    if frame is None:
                        self.log_warning(f'record {page} skipped: no frame')
                        continue
                    if writer is None:
                        h, w = frame.shape[:2]
                        writer = cv2.VideoWriter(fname, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
                        if not writer.isOpened():
                            self.log_error(f'record writer open failed: {fname}')
                            return
                    for _ in range(max(1, duration) * fps):
                        frame = self.frame
                        if frame is not None:
                            writer.write(frame)
                        self.sleep(1.0 / fps)
                    recorded_pages.append(page)
                except Exception as e:
                    self.log_error(f'record page {page} failed', e)
                    self.screenshot(f'record_{page}')
                finally:
                    self.ensure_main(time_out=30)
        finally:
            if writer is not None:
                writer.release()
                if recorded_pages:
                    self.log_info(f'监控录像已保存: {fname}（{len(recorded_pages)} 页: {" / ".join(recorded_pages)}）', notify=True)
                else:
                    try:
                        os.remove(fname)
                    except OSError:
                        pass

    def _open_record_page(self, page):
        """打开指定页面并停留，返回是否成功。"""
        if page == '任务页':
            self.openF2Book('gray_book_quest')
            self.sleep(1.5)
            return True
        if page == '每周乐园':
            self.get_task_by_class(GardenTask).open_garden_weekly_page()
            return True
        if page == '残像聚落':
            # 与刷取任务一致：先 esc 回主界面 → F2 开首领书 → 点左侧「残像聚落」
            # （原实现未先开首领书，直接点坐标会导致画面不对/没录到残像聚落）
            self.send_key('esc', after_sleep=1)
            self.openF2Book("gray_book_boss")
            self.open_boss_book('canxiang')
            return True
        if page in ('大月卡', '战令'):
            # 大月卡：Alt + 左上角战令图标（与每日任务领取战令 claim_battle_pass 一致）
            self.send_key_down('alt')
            self.sleep(0.05)
            self.click_relative(0.86, 0.05)
            self.send_key_up('alt')
            self.sleep(2)
            return True
        self.log_warning(f'unknown record page {page}')
        return False

    def claim_battle_pass(self):
        self.log_info('battle pass')
        self.send_key_down('alt')
        self.sleep(0.05)
        self.click_relative(0.86, 0.05)
        self.send_key_up('alt')
        if not self.wait_ocr(0.2, 0.13, 0.32, 0.22, match=re.compile(r'\d+'), settle_time=1, raise_if_not_found=False):
            self.log_error('can not battle pass, maybe ended')
        else:
            self.click_relative(0.04, 0.3, after_sleep=1)
            self.click_relative(0.68, 0.91, hcenter=True, after_sleep=3)
            self.click_relative(0.04, 0.17, after_sleep=2)
            self.click_relative(0.68, 0.91, hcenter=True, after_sleep=2)
            self.wait_ocr(0.2, 0.13, 0.32, 0.22, match=re.compile(r'\d+'),
                          post_action=lambda: self.click(0.68, 0.91, after_sleep=1), settle_time=1,
                          raise_if_not_found=False)
        self.ensure_main()

    def open_daily(self):
        self.log_info('open_daily')
        self.openF2Book("gray_book_quest")
        self.click(0.17, 0.12, after_sleep=1)
        progress = self.ocr(0.1, 0.1, 0.5, 0.75, match=re.compile(r'^(\d+)/180$'))
        if not progress:
            self.click(0.974, 0.6, after_sleep=1)
            progress = self.ocr(0.1, 0.1, 0.5, 0.75, match=re.compile(r'^(\d+)/180$'))
        if progress:
            current = int(progress[0].name.split('/')[0])
        else:
            current = 0
        self.info_set('current daily progress', current)
        return current, self.get_total_daily_points() >= 100
        # 请注意：如果任务【累计消耗180点结晶波片】已完成，current 也可能为 0，因为翻页后也有可能识别不到已用体力。

    def get_total_daily_points(self):
        points_boxes = self.ocr(0.19, 0.8, 0.30, 0.93, match=number_re)
        if points_boxes:
            try:
                points = int(re.sub(r'\D', '', points_boxes[0].name))
            except Exception:
                points = 0
        else:
            points = 0
        self.info_set('total daily points', points)
        return points

    def claim_daily(self):
        self.info_set('current task', 'claim daily')
        self.openF2Book('gray_book_quest')
        if not self.find_one('boss_proceed', box=self.box_of_screen(0.803, 0.189, 0.960, 0.312)):
            self.log_info('no_boss_proceed, click claim')
            # Click [Guidebook] in [Terminal] interface
            self.click(0.885, 0.250, after_sleep=2)
        self.log_info(f'claim daily reward via  coordinate')
        self.click(0.930, 0.882, after_sleep=1)
        self.ensure_main(time_out=10)

    def claim_mail(self):
        self.info_set('current task', 'claim mail')
        self.back(after_sleep=1.5)
        self.click(0.64, 0.95, after_sleep=1)
        self.click(0.14, 0.9, after_sleep=1)
        self.ensure_main(time_out=10)


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=DailyTask, debug=True)
