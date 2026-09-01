# -*- coding: utf-8 -*-
"""👥 多账号每日任务（增强版）：按序列逐账号跑每日任务，支持断点续跑。

运行机制（原版 + 增强）：
  1. 先从当前已登录账号开始跑一轮每日任务（第一轮即用户手动登录好的起始账号，如 A1）
  2. 跑完后退回登录界面，识别登录界面显示的账号（掩码 199****0005 或扫码 U 开头账号）
  3. 按「已完成记录」跳过今天已打过的账号，从断点账号继续
  4. 每完成一个账号立即写入进度文件（断电/断网/异常中断后恢复，不重复打已完成的账号）
  5. 全部账号完成后：登录回起始账号（不重复执行其每日任务），并提醒用户
  6. 提醒走预留模块 _notify_user（当前：桌面通知 + 日志；后续可扩展 QQ/微信等外部通道）

账号识别：
  - 掩码形式：手机号前3 + **** + 后4（如 199****0005），与方案名中的手机号匹配
  - 扫码登录形式：U 开头的一串字母数字（如 UTEST1001A），通过方案里的「账号别名」匹配
  - 两者都作为该账号的身份依据

进度持久化：configs/multi_account_progress.json（按天记录已完成账号方案名）
"""

import os
import re
import time
from contextlib import nullcontext

from ok import Box, Logger, TaskDisabledException
from ok.util.file import get_relative_path, read_json_file, write_json_file
from src.task.DailyTask import DailyTask, DAILY_PROFILE, LOGOUT_AFTER_DAILY as LOGOUT_AFTER_DAILY_KEY
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.BaseCombatTask import BaseCombatTask
from src.task.BaseWWTask import LOGIN_TEXTS
from src.task.MouseResetTask import MouseResetTask
from src.config_integrity import ConfigIntegrityBlocked, ConfigWriteBlocked, get_default_service
from src.account_switch_evidence import AccountSwitchEvidenceSession
from src.win32_login_input import force_foreground, send_input_click
from src.account_identity import (
    AccountIdentityError,
    masked_phone as _masked_phone,
    resolve_profile_short_names as _resolve_profile_short_names,
    short_profile_name as _short_profile_name,
)
from src.account_repository import AccountRepository, get_default_repository
from src.sequence_repository import SequenceRepository
from src.runtime.sequence_snapshot_service import SequenceSnapshotService
from src.runtime.task_run_coordinator import TaskRunCoordinator
from src.runtime.account_selection_service import AccountSelectionService
from src.runtime.account_verification_service import AccountVerificationService
from src.runtime.login_flow_service import LoginFlowService
from src.runtime.account_runtime_bootstrap import (
    initialize_account_runtime,
    require_account_runtime_for_task,
)
from src.task_status import publish_task_status
from src.logout_capture import AccountSwitchCaptureSession, CaptureSample, ObservedBox

logger = Logger.get_logger(__name__)

account_pattern = re.compile(r'\*\*\*\*')
# 扫码登录的 U 开头账号（如 UTEST1001A，也可能带其他前缀，宽松匹配）
scan_account_pattern = re.compile(r'^U[a-zA-Z0-9]+$', re.IGNORECASE)
LOGOUT_TEXTS = ('退出登录', '退出登入', '退出登錄', '登出', 'Log Out', 'Logout')
RETURN_LOGIN_TEXTS = ('返回登录', '返回登入', '返回登錄', 'Return to Login', 'Return Login')
LOGOUT_POWER_POSITION = (0.040, 0.942)
# 方案名中的 11 位手机号
phone_in_name_pattern = re.compile(r'(1[3-9]\d{9})')
# 方案短名只匹配开头的完整编号（A1、A3、A10 等），避免 A1 误命中 A10。
profile_short_name_pattern = re.compile(
    r'^\s*【?\s*([a-zA-Z]\d+)(?=[\s\-_.:：】]|$)',
    re.IGNORECASE,
)

CURRENT_SEQUENCE = '当前序列'
CURRENT_ACCOUNT = '当前执行账号'
MANAGE_SEQUENCES = '管理序列'
MAX_SEQUENCES = 10
SEQ_ACCOUNTS = ['序列 %d 账号' % i for i in range(1, MAX_SEQUENCES + 1)]
PROFILE_FILE = get_relative_path('configs', 'daily_profiles.json')
PROGRESS_FILE = get_relative_path('configs', 'multi_account_progress.json')


def normalize_account_name(account):
    """账号归一化（掩码/别名匹配用）：小写、0→o、.con→.com。"""
    if not account:
        return account
    return account.lower().replace('0', 'o').replace('.con', '.com')


def masked_phone(phone):
    """手机号掩码形式：前3 + **** + 后4。"""
    return _masked_phone(phone)


def profile_short_name(profile_name):
    """从完整方案名提取精确短名（如 A1/A10）；无法提取时返回 None。"""
    return _short_profile_name(profile_name)


def profile_status_label(profile_name):
    """Return the non-sensitive label allowed in task status UI."""
    return profile_short_name(profile_name) or '账号'


def _publish_status_safe(task, **values):
    publisher = getattr(task, '_publish_status', None)
    if callable(publisher):
        publisher(**values)
    else:
        publish_task_status(task, **values)


def _is_login_identity(task, name):
    """兼容最小化测试替身地判断账号身份；歧义异常继续向上传播。"""
    value = (name or '').strip()
    if not value:
        return False
    if account_pattern.search(value) or scan_account_pattern.match(value):
        return True
    matcher = getattr(task, 'match_profile_from_login', None)
    return bool(callable(matcher) and matcher(value) is not None)


class MultiAccountDailyTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.integrity_service = get_default_service()
        self.name = "👥 多账号每日任务"
        self.description = "按序列逐账号运行每日任务（支持断点续跑）"
        self.add_exit_after_config()
        self.done_set = set()
        self.all_accounts = set()
        self.support_schedule_task = True
        self._profile_cache = {}  # 方案名 → 方案内容（含手机号/别名），用于登录账号识别
        self._account_refresh_pending = False
        self.run_coordinator = TaskRunCoordinator()
        self.account_selection_service = AccountSelectionService()
        self.account_verification_service = AccountVerificationService(
            self.account_selection_service, strict_feature_code=False)
        self.login_flow_service = LoginFlowService(self)
        self._active_account_switch_capture = None
        # 当前执行序列（账号归属序列，序列列表来自 daily_profiles 的 sequences，可在下方管理增删）
        self.default_config[CURRENT_SEQUENCE] = '序列1'
        self.config_description[CURRENT_SEQUENCE] = '当前执行的账号序列（按该序列的账号执行；序列可增删）'
        seq_names = self.get_sequence_names()
        # 选择哪个序列，就只显示该序列的账号配置（sub_configs 联动）
        self.config_type[CURRENT_SEQUENCE] = {
            'type': 'drop_down',
            'options': seq_names,
            'sub_configs': {seq: [SEQ_ACCOUNTS[i]] for i, seq in enumerate(seq_names)},
        }
        # 每个序列的账号列表（独立选择、各自记住；账号可跨序列共享，当天已打的账号任何序列都会跳过）
        for i, seq in enumerate(seq_names):
            protected_accounts = self._read_sequences().get(seq, []) if self.integrity_service is not None else []
            self.default_config[SEQ_ACCOUNTS[i]] = list(protected_accounts)
            self.config_description[SEQ_ACCOUNTS[i]] = f'{seq} 包含的账号（按顺序，选过的不会重复出现；无 = 该位置没有账号）'
            self.config_type[SEQ_ACCOUNTS[i]] = {
                'type': 'label',
                'options': self.get_profile_names(),
                'last_completed_provider': self.get_profile_last_completed,
            }
        # 当前执行账号：选择后从该账号开始执行（选 A3 → A3..A10 完成后继续 A1..A2；留空 = 从当前登录账号开始）
        self.default_config[CURRENT_ACCOUNT] = ''
        self.config_description[CURRENT_ACCOUNT] = '选择从哪个账号开始执行（如选 A3 → A3、A4…A10 完成后继续 A1、A2；留空 = 自动从当前登录账号开始）'
        self.config_type[CURRENT_ACCOUNT] = {
            'type': 'drop_down',
            'options': [''] + self.get_profile_names(),
        }
        # 管理序列（增删/重命名账号归属序列）
        self.default_config[MANAGE_SEQUENCES] = ''
        self.config_description[MANAGE_SEQUENCES] = '增加/删除/重命名账号序列（账号归属随序列保存）'
        self.config_type[MANAGE_SEQUENCES] = (
            {'type': 'label'} if self.integrity_service is not None else
            {'type': 'button', 'text': '管理序列', 'callback': self.manage_sequences}
        )

    def get_profile_last_completed(self, profile_name):
        """返回账号方案的上次完成时间（last_completed 中最新时间，只读展示用）。"""
        try:
            profiles = self._load_profiles()
            profile = profiles.get(profile_name) or {}
            if self.integrity_service is not None:
                profile_id = profile.get('profile_id')
                values = self.integrity_service.get_profile_completions(profile_id).values()
                return max((str(v) for v in values if v), default='')
            lc = profile.get('last_completed') or {}
            if not isinstance(lc, dict):
                return ''
            times = [str(v) for v in lc.values() if v]
            return max(times) if times else ''
        except ConfigIntegrityBlocked:
            raise
        except Exception:
            return ''

    def get_current_sequence(self):
        """当前执行的序列名（仅作账号分类标识，按「当前序列」配置执行）。"""
        return (self.config.get(CURRENT_SEQUENCE) or '序列1').strip()

    def get_readonly_config_value(self, key):
        if key in SEQ_ACCOUNTS:
            try:
                index = SEQ_ACCOUNTS.index(key)
                sequence_names = self.get_sequence_names()
                sequence = sequence_names[index] if index < len(sequence_names) else key
                return self._read_sequences().get(sequence, [])
            except Exception:
                return []
        return self.config.get(key)

    def _sync_local_to_sequences(self):
        """把本任务勾选的序列账号同步到统一归属数据（sequences）。

        多账号任务为归属的编辑入口：用户在此勾选各序列包含的账号，
        同步后每日任务的「方案序列 → 账号配置」联动即可读取。
        """
        try:
            if self.integrity_service is not None:
                return
            seqs = self._read_sequences()
            if not seqs:
                seqs = {f'序列{i}': [] for i in range(1, 6)}
            changed = False
            for i in range(MAX_SEQUENCES):
                key = f'序列{i + 1}'
                if key not in seqs:
                    continue
                acc = [a for a in (self.config.get(SEQ_ACCOUNTS[i]) or []) if a and a != '无']
                if acc != seqs[key]:
                    seqs[key] = acc
                    changed = True
            if changed:
                self._write_sequences(seqs)
        except Exception as e:
            self.log_error('同步序列账号失败', e)

    def get_sequence_accounts(self, seq_name=None):
        """指定序列（默认当前序列）的账号列表（不含「无」）。

        优先读统一归属数据（daily_profiles 的 sequences）；无归属数据时回退自身配置。
        """
        name = seq_name or self.get_current_sequence()
        idx = self._seq_index(name)
        seq = self.config.get(SEQ_ACCOUNTS[idx]) or [] if idx is not None else []
        # 统一归属数据优先（多账号任务勾选时同步写入 sequences）
        try:
            seqs = self._read_sequences()
            if seqs and name in seqs:
                seq = seqs[name]
        except Exception:
            pass
        return [a for a in seq if a and a != '无']

    def _seq_index(self, seq_name):
        """序列名 → 配置索引（0..MAX-1）；非序列名返回 None。"""
        if not seq_name or not seq_name.startswith('序列'):
            return None
        try:
            n = int(re.search(r'(\d+)', seq_name).group(1))
            if 1 <= n <= MAX_SEQUENCES:
                return n - 1
        except Exception:
            pass
        return None

    def _read_sequences(self):
        """读取统一序列归属数据（daily_profiles.json 顶层 sequences）。"""
        # The account settings page writes through AccountRepository.  Do not
        # use the integrity service's startup snapshot here, otherwise newly
        # created sequences and membership edits stay invisible until restart.
        repository = get_default_repository()
        if repository is None and self.integrity_service is not None:
            repository = AccountRepository(paths=self.integrity_service.paths,
                                            integrity_service=self.integrity_service)
        if repository is not None:
            try:
                loader = getattr(repository, 'get_detached_projection', None) or getattr(
                    repository, 'legacy_profile_projection', None)
                if callable(loader):
                    projection = loader()
                    sequences = projection.get('sequences', {}) if isinstance(projection, dict) else {}
                    if isinstance(sequences, dict):
                        return sequences
            except Exception as exc:
                logger.warning(f'account repository sequence projection unavailable: {exc}')
        if self.integrity_service is not None:
            try:
                result = self.integrity_service.last_result or self.integrity_service.check()
                if result.master_valid and result.master:
                    return self.integrity_service.legacy_profile_projection(result.master).get('sequences', {})
            except Exception:
                pass
            return {}
        try:
            import json as _json
            if not os.path.isfile(PROFILE_FILE):
                return {}
            with open(PROFILE_FILE, encoding='utf-8') as f:
                data = _json.load(f)
            seqs = data.get('sequences')
            return seqs if isinstance(seqs, dict) else {}
        except Exception:
            return {}

    def _write_sequences(self, sequences):
        """保存统一序列归属数据。"""
        if self.integrity_service is not None:
            raise ConfigWriteBlocked('account sequence membership is read-only in the application')
        try:
            import json as _json
            data = {}
            if os.path.isfile(PROFILE_FILE):
                with open(PROFILE_FILE, encoding='utf-8') as f:
                    data = _json.load(f)
            data['sequences'] = sequences
            with open(PROFILE_FILE, 'w', encoding='utf-8') as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log_error('保存序列归属失败', e)

    def get_sequence_names(self):
        """返回序列名列表（统一归属数据的键；无数据时默认 序列1~序列5）。"""
        seqs = self._read_sequences()
        if seqs:
            return [str(k) for k in seqs.keys()]
        return [f'序列{i}' for i in range(1, 6)]

    def manage_sequences(self, *args):
        """管理序列：弹窗增删/重命名账号序列（改动写入统一归属数据并同步自身配置）。"""
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit, QMessageBox, QListWidget
            from ok import og

            seqs = self._read_sequences()
            if not seqs:
                seqs = {f'序列{i}': (self.config.get(SEQ_ACCOUNTS[i - 1]) or []) for i in range(1, 6)}

            dlg = QDialog(og.main_window if og.main_window else None)
            dlg.setWindowTitle('管理序列')
            dlg.resize(360, 420)
            lay = QVBoxLayout(dlg)
            lay.addWidget(QLabel('账号序列列表（账号归属随序列保存，每日任务联动使用）：'))
            self._seq_list = QListWidget()
            for k in seqs.keys():
                self._seq_list.addItem(f'{k}（{len(seqs[k])} 个账号）')
            lay.addWidget(self._seq_list)

            name_edit = QLineEdit()
            name_edit.setPlaceholderText('新序列名（如 序列6）')
            lay.addWidget(name_edit)

            btn_lay = QHBoxLayout()
            add_btn = QPushButton('增加序列')
            del_btn = QPushButton('删除选中')
            rename_btn = QPushButton('重命名')
            ok_btn = QPushButton('完成')
            for b in (add_btn, del_btn, rename_btn, ok_btn):
                btn_lay.addWidget(b)
            lay.addLayout(btn_lay)

            def _refresh_list():
                self._seq_list.clear()
                for k in seqs.keys():
                    self._seq_list.addItem(f'{k}（{len(seqs[k])} 个账号）')

            def _add():
                new = name_edit.text().strip() or f'序列{len(seqs) + 1}'
                if new in seqs:
                    QMessageBox.information(dlg, '提示', '该序列已存在')
                    return
                if len(seqs) >= MAX_SEQUENCES:
                    QMessageBox.warning(dlg, '提示', f'最多支持 {MAX_SEQUENCES} 个序列')
                    return
                seqs[new] = []
                name_edit.clear()
                _refresh_list()

            def _del():
                row = self._seq_list.currentRow()
                if row < 0:
                    QMessageBox.information(dlg, '提示', '请先选择要删除的序列')
                    return
                key = list(seqs.keys())[row]
                if len(seqs) <= 1:
                    QMessageBox.warning(dlg, '提示', '至少保留一个序列')
                    return
                del seqs[key]
                _refresh_list()

            def _rename():
                row = self._seq_list.currentRow()
                if row < 0:
                    QMessageBox.information(dlg, '提示', '请先选择要重命名的序列')
                    return
                new = name_edit.text().strip()
                if not new or new in seqs:
                    QMessageBox.information(dlg, '提示', '输入不重复的新序列名')
                    return
                old = list(seqs.keys())[row]
                seqs[new] = seqs.pop(old)
                name_edit.clear()
                _refresh_list()

            add_btn.clicked.connect(_add)
            del_btn.clicked.connect(_del)
            rename_btn.clicked.connect(_rename)
            ok_btn.clicked.connect(dlg.accept)

            if dlg.exec() == 0:
                return
            # 保存统一归属 + 同步自身配置（序列N账号）并刷新序列下拉选项
            self._write_sequences(seqs)
            seq_names = list(seqs.keys())
            for i, k in enumerate(seq_names):
                if i < MAX_SEQUENCES:
                    self.config[SEQ_ACCOUNTS[i]] = [a for a in seqs[k] if a and a != '无']
            self._sync_sequence_ui(seq_names)
            self.log_info(f'序列已更新：{seq_names}', notify=True)
        except Exception as e:
            self.log_error('管理序列失败', e)

    def _sync_sequence_ui(self, seq_names):
        """管理序列后同步「当前序列」下拉选项（含已存在的序列账号配置显示）。"""
        try:
            if CURRENT_SEQUENCE in self.config_type and isinstance(self.config_type[CURRENT_SEQUENCE], dict):
                self.config_type[CURRENT_SEQUENCE]['options'] = seq_names
                self.config_type[CURRENT_SEQUENCE]['sub_configs'] = {
                    seq: [SEQ_ACCOUNTS[i]] for i, seq in enumerate(seq_names)
                }
            # 更新「当前序列」下拉控件选项（单控件更新，不重建）
            from ok import og
            if og.main_window and hasattr(og.main_window, 'onetime_tab'):
                for card in getattr(og.main_window.onetime_tab, 'card_widgets', []):
                    if getattr(card, 'task', None) is not self:
                        continue
                    for w in getattr(card, 'config_widgets', []):
                        if getattr(w, 'key', None) == CURRENT_SEQUENCE and hasattr(w, 'combo_box'):
                            combo = w.combo_box
                            combo.blockSignals(True)
                            combo.clear()
                            combo.addItems(seq_names)
                            combo.blockSignals(False)
                            return
        except Exception:
            pass

    def refresh_account_options(self):
        """Refresh visible account/sequence controls without rebuilding cards."""
        if getattr(self, 'running', False):
            self._account_refresh_pending = True
            return False
        seq_names = self.get_sequence_names()
        profile_names = self.get_profile_names()
        current_sequence = (self.config.get(CURRENT_SEQUENCE) or '').strip()
        if current_sequence not in seq_names and seq_names:
            current_sequence = seq_names[0]
            self.config[CURRENT_SEQUENCE] = current_sequence
        self.config_type[CURRENT_SEQUENCE]['options'] = seq_names
        self.config_type[CURRENT_SEQUENCE]['sub_configs'] = {
            seq: [SEQ_ACCOUNTS[i]] for i, seq in enumerate(seq_names)
        }
        for i, _seq in enumerate(seq_names):
            if i >= len(SEQ_ACCOUNTS):
                break
            self.config_type[SEQ_ACCOUNTS[i]]['options'] = profile_names
        self.config_type[CURRENT_ACCOUNT]['options'] = [''] + profile_names
        try:
            from ok import og
            main_window = getattr(og, 'main_window', None)
            onetime_tab = getattr(main_window, 'onetime_tab', None)
            for card in getattr(onetime_tab, 'card_widgets', []):
                if getattr(card, 'task', None) is not self:
                    continue
                for widget in getattr(card, 'config_widgets', []):
                    key = getattr(widget, 'key', None)
                    if key == CURRENT_SEQUENCE and hasattr(widget, 'combo_box'):
                        combo = widget.combo_box
                        combo.blockSignals(True)
                        combo.clear()
                        combo.addItems(seq_names)
                        combo.setCurrentText(current_sequence)
                        combo.blockSignals(False)
                    elif key == CURRENT_ACCOUNT and hasattr(widget, 'combo_box'):
                        combo = widget.combo_box
                        current = self.config.get(CURRENT_ACCOUNT) or ''
                        combo.blockSignals(True)
                        combo.clear()
                        combo.addItems([''] + profile_names)
                        combo.setCurrentText(current if current in profile_names else '')
                        combo.blockSignals(False)
                    elif key in SEQ_ACCOUNTS and hasattr(widget, 'update_value'):
                        widget.update_value()
        except Exception:
            pass
        self._account_refresh_pending = False
        return True

    # ==================== 账号方案 ↔ 登录显示 匹配 ====================

    def _load_profiles(self):
        """加载全部方案（含手机号、账号别名）。"""
        try:
            repository = get_default_repository()
            if repository is None and self.integrity_service is not None:
                repository = AccountRepository(paths=self.integrity_service.paths,
                                                integrity_service=self.integrity_service)
            if repository is not None:
                projection = repository.get_detached_projection()
                profiles = projection.get('profiles', {}) if isinstance(projection, dict) else {}
                if isinstance(profiles, dict):
                    return profiles
            if self.integrity_service is not None:
                result = self.integrity_service.last_result or self.integrity_service.check()
                if result.master_valid and result.master:
                    return self.integrity_service.legacy_profile_projection(result.master).get('profiles', {})
                return {}
            from src.task.DailyTask import PROFILE_FILE
            data = read_json_file(PROFILE_FILE)
            profiles = (data or {}).get('profiles', {})
            return profiles if isinstance(profiles, dict) else {}
        except Exception as e:
            logger.error('load profiles failed', e)
            return {}

    def get_profile_names(self):
        """返回全部方案名。"""
        return list(self._load_profiles().keys())

    def resolve_profile_short_names(self, short_names):
        """按输入顺序把 A1/A3 等精确短名解析为完整方案名。

        短名必须唯一且全部存在。这里不使用前缀/包含匹配，防止 A1 误选 A10。
        """
        try:
            profiles = self._load_profiles() if hasattr(self, '_load_profiles') else self.get_profile_names()
            return _resolve_profile_short_names(short_names, profiles)
        except AccountIdentityError as exc:
            raise ValueError(str(exc)) from exc

    def create_run_snapshot(self, profile_names, *, sequence_id=None, short_names=False):
        """Resolve once and freeze the exact profiles used by this run."""
        repository = get_default_repository() or AccountRepository(
            paths=self.integrity_service.paths if self.integrity_service is not None else None,
            integrity_service=self.integrity_service,
        )
        sequences = SequenceSnapshotService(repository)
        members = (sequences.sequences.resolve_short_names(profile_names)
                   if short_names else list(profile_names or []))
        snapshot = sequences.create_for_profile_ids(
            members, sequence_id=sequence_id or self.get_current_sequence()
        )
        self._active_run_snapshot = snapshot
        self.run_coordinator.start(snapshot)
        return snapshot

    def request_coordinated_stop(self):
        """Publish a stop request without mutating the active run snapshot."""
        return self.run_coordinator.request_stop()

    @staticmethod
    def _snapshot_profile_names(snapshot):
        return [str(profile['account'].get('display_name') or profile['profile_id'])
                for profile in snapshot.profiles]

    def _profile_identities(self, profile_name):
        """返回方案的识别标识列表：手机号掩码 + 账号别名（归一化）。"""
        profiles = self._load_profiles()
        profile = profiles.get(profile_name) or {}
        ids = []
        m = phone_in_name_pattern.search(profile_name)
        if m:
            phone = m.group(1)
            ids.append(normalize_account_name(masked_phone(phone)))
        # 账号别名：兼容新旧字段，贯穿登录就绪、展开、选号和登录前核对。
        aliases = []
        if isinstance(profile, dict):
            for key in ('masked_phone', 'phone', 'nickname', 'alternate_login_name'):
                value = profile.get(key)
                if value:
                    normalized = normalize_account_name(str(value).strip())
                    if normalized and normalized not in ids:
                        ids.append(normalized)
            for key in ('备用识别名称内容', 'Account Name', 'account_name', '账号名称'):
                value = profile.get(key)
                if isinstance(value, (list, tuple, set)):
                    aliases.extend(value)
                elif value:
                    aliases.extend(a.strip() for a in re.split(r'[,，;；\r\n]+', str(value)) if a.strip())
            old = profile.get('account_aliases') or []
            if isinstance(old, (list, tuple, set)):
                aliases.extend(old)
            elif old:
                aliases.extend(a.strip() for a in re.split(r'[,，;；\r\n]+', str(old)) if a.strip())
        for a in aliases:
            if a:
                normalized = normalize_account_name(str(a).strip())
                if normalized and normalized not in ids:
                    ids.append(normalized)
        return ids

    def match_profile_from_login(self, login_text):
        """根据登录界面显示的账号文本（掩码或 U 开头）匹配方案名，未匹配返回 None。"""
        if not login_text:
            return None
        profiles = self._load_profiles()
        try:
            verifier = getattr(self, 'account_verification_service', None)
            if verifier is None:
                verifier = AccountVerificationService(AccountSelectionService())
            exact = verifier.resolve_observed(login_text, profiles)
        except AccountIdentityError as exc:
            raise ValueError(str(exc)) from exc
        if exact is not None:
            return exact
        wanted = normalize_account_name(str(login_text).strip())
        matches = [
            name for name in self.get_profile_names()
            if wanted in self._profile_identities(name)
        ]
        if len(matches) > 1:
            raise ValueError(
                f'登录身份 {login_text!r} 同时匹配多个账号方案：{", ".join(matches)}；'
                '为防止误登录已停止，请删除重复备用识别名'
            )
        if matches:
            return matches[0]
        return None

    def _is_login_account_text(self, name):
        """判断 OCR 文本是否可能是账号身份（含备用识别名）。"""
        value = (name or '').strip()
        if not value:
            return False
        if account_pattern.search(value) or scan_account_pattern.match(value):
            return True
        return _is_login_identity(self, value)

    # ==================== 断点持久化（今日已完成账号） ====================

    def _today(self):
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d')

    def _load_today_progress(self):
        """读取今天的已完成账号记录。"""
        if self.integrity_service is not None:
            values = self.integrity_service.get_progress(f'multi_account:{self._today()}', [])
            return list(values or [])
        try:
            data = read_json_file(PROGRESS_FILE) or {}
            return list(data.get(self._today(), []) or [])
        except Exception:
            return []

    def _save_today_progress(self):
        """把 done_set 持久化到今天记录（每完成一个账号立即调用，防中断丢失）。"""
        if self.integrity_service is not None:
            self.integrity_service.set_progress(f'multi_account:{self._today()}', sorted(self.done_set))
            return
        try:
            data = read_json_file(PROGRESS_FILE) or {}
            if not isinstance(data, dict):
                data = {}
            data[self._today()] = sorted(self.done_set)
            write_json_file(PROGRESS_FILE, data)
        except Exception as e:
            logger.error('save progress failed', e)

    # ==================== 提醒预留模块 ====================

    def _notify_user(self, title, message):
        """提醒用户（预留模块）。

        当前实现：日志 + 桌面通知（notify=True 走 okww 现有通知链路，
        若配置了 QQ 等外部通道也会一并发出）。后续可按需扩展更多通道。
        """
        self.log_info(f'{title}: {message}', notify=True)

    # ==================== 主流程 ====================

    def run(self):
        _publish_status_safe(self, stage='启动', detail='正在启动多账号任务')
        require_account_runtime_for_task(self)
        if getattr(self, '_account_refresh_pending', False):
            self.refresh_account_options()
        if self.integrity_service is not None:
            self.integrity_service.guard_task_start()
        WWOneTimeTask.run(self)
        self.done_set.clear()
        self.all_accounts.clear()
        # 把本任务勾选的序列账号同步到统一归属数据（多账号任务为归属编辑入口，每日任务联动读取）
        self._sync_local_to_sequences()

        # 临时关闭 DailyTask 的「每日任务完成后自动退登 PC 端」：
        # 多账号任务自己统一管理退登（_switch_to_login），避免重复退登冲突
        # （DailyTask 先退一次回到登录界面，MultiAccount 再按"在游戏内"退一次会误操作）
        daily_task = None
        try:
            daily_task = self.get_task_by_class(DailyTask)
            if daily_task is not None:
                # Multi-account owns the logout transition.  Use an in-memory
                # override so forced termination cannot leave a persisted
                # account option behind.
                self.log_info(f'多账号运行：临时关闭「每日任务完成后自动退登」')
        except Exception as e:
            self.log_error('关闭自动退登失败（继续运行）', e)

        try:
            if daily_task is not None:
                override = getattr(daily_task, 'runtime_config_override', None)
                context = override(LOGOUT_AFTER_DAILY_KEY, False) if callable(override) else nullcontext()
                with context:
                    self._run_inner()
            else:
                self._run_inner()
        except TaskDisabledException:
            self.run_coordinator.request_stop()
            raise
        except Exception as error:
            self.run_coordinator.fail(str(error))
            raise
        else:
            self.run_coordinator.request_stop()
        finally:
            if daily_task is not None and hasattr(daily_task, '_runtime_status_account'):
                del daily_task._runtime_status_account

    def _run_inner(self):
        # 本轮账号序列（配置）
        sequence = self.get_sequence_accounts()
        snapshot_maker = getattr(self, 'create_run_snapshot', None)
        if sequence and callable(snapshot_maker):
            snapshot = snapshot_maker(sequence, sequence_id=self.get_current_sequence())
            sequence = self._snapshot_profile_names(snapshot)
        if not sequence:
            self.log_info('未配置「本轮账号序列」，仅跑当前账号后结束', notify=True)

        # 断点恢复：加载今日已完成账号
        for done in self._load_today_progress():
            self.done_set.add(done)
        if self.done_set:
            self.log_info(f'检测到今日已完成账号（断点恢复）: {sorted(self.done_set)}', notify=True)

        # 记录真实起始账号（全部完成后登录回它）。主界面启动时必须先退登
        # 识别真实身份，不能用 CURRENT_ACCOUNT 或序列下一个账号冒充。
        first_account = None

        # 第一轮：主界面启动先退登并识别真实账号；登录界面启动则从序列选号。
        try:
            in_main = self.is_main(esc=False)
        except TaskDisabledException:
            raise
        except Exception:
            in_main = False
        if in_main:
            _publish_status_safe(self, stage='账号切换', detail='正在退出当前账号')
            self._switch_to_login()
            try:
                first_account = self._detect_current_account_from_login()
            except TaskDisabledException:
                raise
            except ValueError:
                raise
            except Exception as e:
                self.log_error('无法识别主界面启动时的真实账号', e)
                first_account = None
            if not first_account:
                self.log_error('主界面启动时无法唯一识别真实账号，为防止使用错误方案，停止运行')
                self.screenshot('multi')
                raise Exception(self.tr('Cannot identify the current account safely'))

            in_sequence = any(self._same_account(first_account, acc) for acc in sequence)
            if in_sequence and not self._is_done(first_account):
                _publish_status_safe(self,
                    account=first_account,
                    stage='账号切换',
                    detail=f'正在选择账号 {profile_status_label(first_account)}',
                )
                self.log_info(f'主界面启动识别到真实账号 {first_account}，重新登录后执行其每日任务', notify=True)
                self._select_and_login_specific(first_account)
                self._require_daily_profile(first_account)
                self.run_task_by_class(DailyTask)
                self.log_info(f'账号 {first_account} 每日任务完成', notify=True)
                self._mark_done(first_account)
                self._save_today_progress()
                self.ensure_main(time_out=100)
                self._switch_to_login()
            elif not sequence and not self._is_done(first_account):
                self.log_info(f'未配置账号序列，执行已识别的真实账号 {first_account}', notify=True)
                self._select_and_login_specific(first_account)
                self._require_daily_profile(first_account)
                self.run_task_by_class(DailyTask)
                self._mark_done(first_account)
                self._save_today_progress()
                self.ensure_main(time_out=100)
                self._switch_to_login()
            else:
                self.log_info(
                    f'真实起始账号 {first_account} 不在当前序列或今日已完成，'
                    '不运行其每日任务，继续选择序列中的下一个账号'
                )
                # 该账号不是本轮序列起点时，清除旧配置值，避免断点配置
                # 把序列旋转到一个与本次真实启动状态无关的位置。
                self.config[CURRENT_ACCOUNT] = ''
        else:
            _publish_status_safe(self, stage='账号切换', detail='正在识别当前账号')
            first_target = self._select_and_login_account()
            if first_target:
                _publish_status_safe(self,
                    account=first_target,
                    stage='每日任务',
                    detail=f'正在执行账号 {profile_status_label(first_target)}',
                )
                self.log_info(f'从登录界面选择下一个未完成账号：{first_target}，开始执行每日任务', notify=True)
                self._require_daily_profile(first_target)
                self.run_task_by_class(DailyTask)
                self.log_info(f'账号 {first_target} 每日任务完成', notify=True)
                self._mark_done(first_target)
                self._save_today_progress()
                self.ensure_main(time_out=100)
                self._switch_to_login()

            if first_target:
                first_account = first_target
            elif first_account is None:
                try:
                    first_account = self._detect_current_account_from_login()
                except TaskDisabledException:
                    raise
                except ValueError:
                    raise
                except Exception:
                    first_account = None
        if not first_account:
            self.log_error('无法确定本轮真实起始账号，停止运行以防止错误回登')
            raise Exception(self.tr('Cannot determine the starting account safely'))
        self.log_info(f'起始账号：{first_account}（全部完成后登录回）', notify=True)

        self.info_set('Completed', sorted({profile_status_label(item) for item in self.done_set}))

        while next_account := self._select_and_login_account():
            self.info_set('Completed', sorted({profile_status_label(item) for item in self.done_set}))
            _publish_status_safe(self,
                account=next_account,
                stage='每日任务',
                detail=f'正在执行账号 {profile_status_label(next_account)}',
            )
            self.log_info(f'开始执行账号 {next_account} 的每日任务', notify=True)
            self._require_daily_profile(next_account)
            self.run_task_by_class(DailyTask)
            self.log_info(f'账号 {next_account} 每日任务完成', notify=True)
            self._mark_done(next_account)
            self._save_today_progress()
            self.ensure_main(time_out=100)
            self._switch_to_login()

        # 全部账号完成：登录回起始账号（不重复执行其每日任务），并提醒
        self._login_back_to(first_account)

    def _mark_done(self, account):
        if account:
            self.done_set.add(self._profile_id_for(account) if self.integrity_service is not None else account)

    def _is_done(self, account):
        """账号是否已完成：多账号断点记录，或今天已单独跑过该账号的每日任务（方案文件 last_completed）。"""
        if self.integrity_service is not None:
            identity = self._profile_id_for(account)
            if account in self.done_set or identity in self.done_set:
                return True
            profiles = self._load_profiles()
            profile = profiles.get(account) or {}
            completion = self.integrity_service.get_completion(identity, 'Daily Task')
            return bool(str(completion or '').startswith(self._today()))
        identity = account
        if account in self.done_set or identity in self.done_set:
            return True
        try:
            from datetime import datetime
            profiles = self._load_profiles()
            profile = profiles.get(account) or {}
            lc = profile.get('last_completed') or {}
            today = datetime.now().strftime('%Y-%m-%d')
            if str(lc.get('Daily Task', '')).startswith(today):
                return True
        except Exception:
            pass
        return False

    def _same_account(self, left, right):
        return normalize_account_name(left) == normalize_account_name(right)

    def _guard_account_transition(self):
        """Freshly verify integrity before any account-transition interaction."""
        service = getattr(self, 'integrity_service', None)
        if service is None:
            return True
        result = service.check()
        if not getattr(result, 'ok', False):
            raise ConfigIntegrityBlocked(service.describe(result))
        return True

    def _publish_status(self, *, account=None, stage=None, detail=None):
        publish_task_status(
            self,
            account=profile_status_label(account) if account else None,
            stage=stage,
            detail=detail,
        )

    # ==================== 统一账号切换与失败证据 ====================

    def _begin_account_switch_evidence(self, target):
        """Start a bounded in-memory evidence session for one target switch."""
        try:
            blur_area = None
            config = getattr(self, 'config', None)
            if isinstance(config, dict):
                blur_area = config.get('blur_area')
            self._account_switch_evidence = AccountSwitchEvidenceSession(
                target, blur_area=blur_area,
            )
            self._account_switch_attempt = None
            self._account_switch_evidence.record_stage('start')
        except Exception:
            self._account_switch_evidence = None

    def _evidence_stage(self, stage, **kwargs):
        session = getattr(self, '_account_switch_evidence', None)
        if session is not None:
            try:
                frame = getattr(self, 'frame', None)
                session.record_stage(stage, frame=frame, **kwargs)
            except TaskDisabledException:
                raise
            except Exception:
                pass

    def _evidence_identity(self, account, **kwargs):
        session = getattr(self, '_account_switch_evidence', None)
        if session is not None:
            try:
                frame = getattr(self, 'frame', None)
                session.record_identity(account, frame=frame, **kwargs)
            except TaskDisabledException:
                raise
            except Exception:
                pass

    def _evidence_click(self, mode, point, **kwargs):
        session = getattr(self, '_account_switch_evidence', None)
        if session is not None:
            try:
                if 'attempt' not in kwargs:
                    kwargs['attempt'] = getattr(self, '_account_switch_attempt', None)
                frame = getattr(self, 'frame', None)
                session.record_click(mode, point, frame=frame, **kwargs)
            except TaskDisabledException:
                raise
            except Exception:
                pass

    def _evidence_sample(self, stage):
        session = getattr(self, '_account_switch_evidence', None)
        if session is not None:
            try:
                session.record_frame(getattr(self, 'frame', None), stage=stage)
            except TaskDisabledException:
                raise
            except Exception:
                pass

    def _finish_account_switch_evidence(self, success, reason=None, **kwargs):
        session = getattr(self, '_account_switch_evidence', None)
        self._account_switch_evidence = None
        self._account_switch_attempt = None
        if session is None:
            return None
        try:
            if success:
                return session.succeed()
            return session.fail(reason or 'account switch failed', **kwargs)
        except TaskDisabledException:
            raise
        except Exception as error:
            try:
                self.log_warning(f'账号切换失败证据保存失败：{error}')
            except Exception:
                pass
            return None

    def switch_to_account(self, profile_name, *, max_retries=5):
        """Public production account-switch entry point.

        This owns the complete login transition.  Callers only resolve a
        target profile; production and test tasks therefore share exactly the
        same wait/select/verify/login/ensure-main chain.
        """
        service = getattr(self, 'login_flow_service', None) or LoginFlowService(self)
        return service.switch_to_account(profile_name, max_retries=max_retries)

    def _switch_to_login(self):
        MultiAccountDailyTask._guard_account_transition(self)
        _publish_status_safe(self, stage='账号切换', detail='正在退出当前账号')
        self.log_info(self.tr('Switching back to login screen'))
        # 退登过程中窗口会短暂无 OCR 或闪烁，但输入必须由当前可见状态
        # 决定。可见状态的动作各自最多重试 3 次；窗口转换/加载只受
        # 45 秒截止时间限制，不能因为 OCR 轮询次数较多而提前失败。
        deadline = time.monotonic() + 45
        last_state = None
        last_meaningful_state = None
        check_count = 0
        action_counts = {'confirm': 0, 'setting': 0, 'main': 0}
        active_capture = getattr(self, '_active_account_switch_capture', None)
        session_factory = getattr(self, '_create_logout_capture_session', None)
        session_context = (
            nullcontext(active_capture)
            if active_capture is not None
            else (session_factory() if callable(session_factory) else nullcontext(None))
        )
        with session_context as capture_session:
          while time.monotonic() < deadline:
            check_count += 1
            state = (
                self._logout_state(capture_session)
                if capture_session is not None else self._logout_state()
            )
            if state in ('confirm', 'setting', 'main') and state != last_meaningful_state:
                # Retry budgets are consecutive-input budgets per observable
                # state; moving main -> setting -> confirm starts each budget
                # and the 45-second observation window afresh.  Input failures
                # do not consume a delivery count.
                action_counts[state] = 0
                last_meaningful_state = state
                deadline = time.monotonic() + 45
            last_state = state
            self.log_info(f'退登状态检查 {check_count}：{state}')
            try:
                _publish_status_safe(self, stage='账号切换', detail={
                    'confirm': '正在确认退出登录',
                    'setting': '正在点击退出登录',
                    'main': '正在打开设置页',
                    'unknown': '等待界面稳定',
                }.get(state, '等待界面稳定'))
                if state == 'login':
                    self.log_info('已在登录界面，跳过退登流程')
                    return True
                if state == 'confirm':
                    if action_counts[state] >= 3:
                        self.log_warning('退登确认框连续 3 次未消失，停止重复点击')
                        break
                    self.log_info('确认框仍在屏幕上，直接重试确认按钮，不发送 ESC')
                    observed = getattr(self, '_logout_confirm_target', None)
                    confirm_box = observed.box if isinstance(observed, ObservedBox) else None
                    confirmed = self._click_main_login_box(
                        confirm_box,
                        stage='logout_confirm',
                        after_sleep=0.2,
                        origin=observed.sample.origin if isinstance(observed, ObservedBox) else None,
                    ) if confirm_box is not None else False
                    if confirmed is not False:
                        action_counts[state] += 1
                    if confirmed is False:
                        self.log_warning('确认退登按钮本次未成功投递，继续检查确认框状态')
                    self.sleep(1)
                    continue
                if state == 'setting':
                    if action_counts[state] >= 3:
                        self.log_warning('ESC 设置页连续 3 次未消失，停止重复点击')
                        break
                    self.log_info('已在 ESC 设置页，直接点击退登入口，不发送 ESC')
                    finder = getattr(self, '_find_logout_button_target', None)
                    observed = finder(capture_session) if callable(finder) else None
                    logout_box = observed.box if isinstance(observed, ObservedBox) else (
                        self._find_logout_button_box() if not callable(finder) else None
                    )
                    delivered = self._click_main_login_box(
                        logout_box,
                        stage='logout_button',
                        after_sleep=1,
                        origin=observed.sample.origin if isinstance(observed, ObservedBox) else None,
                    ) if logout_box is not None else False
                    if delivered is not False:
                        action_counts[state] += 1
                    self.sleep(1)
                    continue
                if state == 'main':
                    if action_counts[state] >= 3:
                        self.log_warning('游戏主界面连续 3 次未进入设置页，停止重复发送 ESC')
                        break
                    self.log_info('当前为游戏主界面，发送 ESC 打开设置页')
                    delivered = self.send_key('esc', after_sleep=1)
                    if delivered is not False:
                        action_counts[state] += 1
                    self.sleep(1)
                    continue
                # 短暂无 OCR/窗口转换属于可恢复状态；只等待很短时间后
                # 重新识别，不在未知状态发键或点击。
                self.log_info('退登状态暂时无法确认，等待窗口转换后重新识别')
                self.sleep(0.5)
            except TaskDisabledException:
                raise
            except Exception as e:
                self.log_warning(f'退登状态动作失败（状态={state}）：{e}')
                self.sleep(0.5)

        try:
            self.screenshot('multi')
        except TaskDisabledException:
            raise
        except Exception:
            pass
        raise Exception(
            f'退登失败，状态循环已到上限；最后状态={last_state or "未知"}，'
            f'动作次数={action_counts}'
        )

    def _login_screen_feature_count(self, texts):
        """宽松统计登录界面特征数量：账号身份（含备用名）/登录文本。"""
        count = 0
        if not texts:
            return 0
        try:
            count += sum(1 for t in texts if _is_login_identity(self, getattr(t, 'name', '')))
        except TaskDisabledException:
            raise
        except ValueError:
            raise
        except Exception:
            pass
        try:
            exact = getattr(self, '_exact_login_button_boxes', None)
            login_boxes = exact(texts) if callable(exact) else self.find_boxes(texts, LOGIN_TEXTS)
            count += len(login_boxes or [])
        except Exception:
            pass
        return count

    def _find_connect_target(self, sample, texts):
        """Return an exact bottom-center connect entry bound to its sample."""
        if sample is None or not texts:
            return None
        finder = getattr(self, '_connect_button_boxes', None)
        if not callable(finder):
            return None
        boundary = self.box_of_screen(0.25, 0.75, 0.75, 1.0)
        boxes = finder(texts, boundary=boundary)
        return ObservedBox(boxes[0], sample) if boxes else None

    def _wait_login_screen_stable(self, time_out=120, settle=2):
        """抗闪烁等待登录界面稳定。

        游戏退登后登录界面有概率闪烁/短暂暗屏（窗口不可见、OCR 无文本），
        直接 60s 一刀切等待会把瞬时的暗屏当成永久失败。本方法分两阶段：
          阶段1 宽松探测：容忍暗屏/闪烁，持续等待登录界面任意特征出现
            - 窗口不可见 → 尝试 bring_to_front 恢复前台
            - OCR 为空 → 视为正常过渡，不限次失败（限频打日志）
            - 检测到启动器界面（KURO GAMES 公告/修复）→ 判为退过头，明确报错
            - 主窗口 OCR 无特征时，回退捕获 #32770 登录对话框窗口再 OCR
          阶段2 严格确认：特征出现后，确认账号下拉框（掩码或 U 账号）
        失败时输出诊断日志（窗口可见性 / OCR 文本数 / 最近文本）并截图。
        """
        self.log_info(f'等待登录界面（宽松探测，超时 {time_out}s，容忍闪烁/暗屏）')
        deadline = time.monotonic() + time_out
        last_log = 0.0
        connect_attempts = 0
        connect_exhausted_logged = False
        while time.monotonic() < deadline:
            try:
                sample = getattr(self, '_evidence_sample', None)
                if callable(sample):
                    sample('wait_login_screen')
                hwnd = getattr(self, 'hwnd', None)
                # 主窗口仍可见时先做同窗口 OCR；不可见时先查同进程登录
                # 对话框，确认不存在后才 bring_to_front，减少闪烁抢前台。
                dlg_texts = None
                if hwnd is None or not hwnd.visible:
                    dlg_texts = self._ocr_login_dialog()
                    if dlg_texts and self._login_screen_feature_count(dlg_texts) > 0:
                        self._login_in_dialog = True
                        self.log_info(f'已通过登录对话框窗口识别到登录界面（OCR {len(dlg_texts)} 文本）')
                        break
                if hwnd is not None and hwnd.exists and not hwnd.visible:
                    try:
                        hwnd.bring_to_front()
                        self.log_warning('未发现登录对话框且游戏窗口不可见，已尝试恢复前台')
                    except TaskDisabledException:
                        raise
                    except Exception:
                        pass
                    self.sleep(1)
                    continue
                reader = getattr(self, '_ocr_account_switch_main', None)
                texts, main_sample = reader() if callable(reader) else (self.ocr(), None)
                connect_target = self._find_connect_target(main_sample, texts)
                if connect_target is not None:
                    if connect_attempts < 3:
                        connect_attempts += 1
                        delivered = self._click_main_login_box(
                            connect_target.box,
                            stage='connect_entry',
                            after_sleep=1,
                            origin=connect_target.sample.origin,
                        )
                        record_stage = getattr(self, '_evidence_stage', None)
                        if callable(record_stage):
                            record_stage(
                                'connect_entry_result',
                                attempt=connect_attempts,
                                detail=f'delivered={bool(delivered)},confirmed=False',
                            )
                        self.log_info(
                            f'点击连接入口第 {connect_attempts}/3 次投递；'
                            f'等待新帧确认界面转换'
                        )
                        self.sleep(1)
                        continue
                    if not connect_exhausted_logged:
                        connect_exhausted_logged = True
                        self.log_warning('点击连接入口连续 3 次未消失，停止重复点击并等待超时')
                if self._login_screen_feature_count(texts) > 0:
                    self._login_in_dialog = False
                    record_stage = getattr(self, '_evidence_stage', None)
                    if connect_attempts and callable(record_stage):
                        record_stage(
                            'connect_entry_confirmed',
                            attempt=connect_attempts,
                            detail='delivered=True,confirmed=True',
                        )
                    break
                if dlg_texts is None:
                    dlg_texts = self._ocr_login_dialog()
                if dlg_texts and self._login_screen_feature_count(dlg_texts) > 0:
                    self._login_in_dialog = True
                    record_stage = getattr(self, '_evidence_stage', None)
                    if connect_attempts and callable(record_stage):
                        record_stage(
                            'connect_entry_confirmed',
                            attempt=connect_attempts,
                            detail='delivered=True,confirmed=True,window=dialog',
                        )
                    self.log_info(f'已通过登录对话框窗口识别到登录界面（OCR {len(dlg_texts)} 文本）')
                    break
                # 启动器兜底：退过头回到启动器（KURO GAMES 启动器界面，无登录特征）
                if texts and self._is_launcher_texts(texts):
                    self.log_error('检测到启动器界面（退过头到启动器），请手动重新进入游戏后再试')
                    try:
                        self.screenshot('multi')
                    except Exception:
                        pass
                    raise Exception(self.tr('Logged out to launcher, please re-enter the game'))
                now = time.monotonic()
                if now - last_log >= 30:
                    last_log = now
                    win_state = 'visible' if (hwnd is not None and hwnd.visible) else 'invisible'
                    self.log_info(f'登录界面暂不可见（闪烁/加载中）: 窗口={win_state}, OCR文本数={len(texts) if texts else 0}')
            except TaskDisabledException:
                # 停止任务必须立即终止等待；不能被闪烁容错逻辑吞掉后继续 OCR。
                raise
            except Exception as e:
                if 'launcher' in str(e).lower() or '启动器' in str(e):
                    raise
            self.sleep(1)
        # 阶段2：严格确认（掩码或 U 账号 + 登录特征）
        box = self.wait_until(self.do_find_account_drop_down, time_out=settle + 5,
                              settle_time=settle, raise_if_not_found=False)
        if box is None:
            try:
                self.screenshot('multi')
                reader = getattr(self, '_ocr_account_switch_main', None)
                texts, _sample = reader() if callable(reader) else (self.ocr(), None)
                hwnd = getattr(self, 'hwnd', None)
                win_state = 'visible' if (hwnd is not None and hwnd.visible) else 'invisible'
                snippet = ' | '.join(t.name[:20] for t in texts[:5]) if texts else ''
                self.log_error(f'登录界面等待超时: 窗口={win_state}, OCR文本数={len(texts) if texts else 0}, 最近文本: {snippet}')
            except TaskDisabledException:
                raise
            except ValueError:
                raise
            except Exception:
                pass
            raise Exception(self.tr('Timed out waiting for the login screen'))
        return box

    @staticmethod
    def _is_launcher_texts(texts):
        """启动器界面特征：含 KURO GAMES 且无登录特征（登录文本/U账号）。"""
        joined = ' '.join((t.name or '') for t in texts) if texts else ''
        if 'kuro' not in joined.lower() or not joined:
            return False
        if any((t.name or '') in ('登录', '登入', 'Log') for t in texts):
            return False
        if any(scan_account_pattern.match((t.name or '').strip()) for t in texts):
            return False
        return True

    def _find_login_dialog(self):
        """找可见的 #32770 登录对话框，返回 (hwnd, (left, top, right, bottom)) 或 (0, None)。

        排除占满全屏的隐藏背景对话框（如全黑 1920x1080 的那个），取面积最小/居中的 #32770。
        """
        import win32gui
        import win32process
        found = []
        _main_hwnd, main_pid = self._main_window_identity()
        # 无法锁定游戏主窗口 PID 时禁止系统级跨窗口点击，避免误操作
        # 其他 #32770 对话框；主窗口内嵌登录仍可走原路径。
        if not main_pid:
            return 0, None

        def cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetClassName(hwnd) != '#32770':
                    return True
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid != main_pid:
                    return True
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w <= 0 or h <= 0:
                    return True
                found.append((hwnd, rect, w * h))
            except Exception:
                pass
            return True
        win32gui.EnumWindows(cb, None)
        if not found:
            return 0, None
        # 取面积最小且非全屏的 #32770（登录对话框通常居中且小于屏幕）
        found = [f for f in found if f[2] > 0]
        found.sort(key=lambda f: f[2])
        best = found[0]
        return best[0], best[1]

    def _capture_hwnd_client(self, hwnd):
        """BitBlt 捕获指定窗口客户端区域，返回 (bgr_frame, 客户区屏幕原点 (ox,oy)) 或 (None, None)。"""
        import win32gui
        import win32ui
        import win32con
        try:
            import numpy as np
            import cv2
        except Exception:
            return None, None
        hwnd_dc = None
        mfc_dc = None
        save_dc = None
        bmp = None
        try:
            # ComboLBox 是独立弹出窗口，窗口边框可能位于列表客户区之外。
            # 使用客户区 DC + ClientToScreen，确保 OCR 框换算到屏幕时不依赖
            # 向上/向下展开方向或固定行号。
            client_rect = win32gui.GetClientRect(hwnd)
            w, h = client_rect[2] - client_rect[0], client_rect[3] - client_rect[1]
            if w <= 0 or h <= 0:
                return None, None
            origin = win32gui.ClientToScreen(hwnd, (0, 0))
            hwnd_dc = win32gui.GetDC(hwnd)
            if not hwnd_dc:
                return None, None
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)
            bits = bmp.GetBitmapBits(True)
            frame = np.frombuffer(bits, np.uint8).reshape(h, w, 4)
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR), origin
        except Exception:
            return None, None
        finally:
            try:
                if save_dc is not None:
                    save_dc.DeleteDC()
            except Exception:
                pass
            try:
                if mfc_dc is not None:
                    mfc_dc.DeleteDC()
            except Exception:
                pass
            try:
                if bmp is not None:
                    win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
            try:
                if hwnd_dc:
                    win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass

    def _dialog_capture(self):
        """捕获 #32770 登录对话框客户端区域，返回 (bgr_frame, 屏幕原点 (ox,oy)) 或 (None, None)。

        登录账号下拉框位于独立 #32770 对话框（非游戏主窗口），主窗口捕获/OCR 永远看不到它，
        因此登录界面的一切识别与操作都基于本方法捕获的对话框帧。
        """
        hwnd, _rect = self._find_login_dialog()
        if not hwnd:
            return None, None
        return self._capture_hwnd_client(hwnd)

    def _ocr_login_dialog(self):
        """回退方案：捕获 #32770 登录对话框并 OCR，返回文本列表；失败返回 None。"""
        frame, _origin = self._dialog_capture()
        if frame is None:
            return None
        try:
            return self.ocr(frame=frame)
        except TaskDisabledException:
            raise
        except Exception:
            return None

    def _find_control_hwnd(self, class_name):
        """找指定窗口类（ComboBox/ComboLBox/Button 等）的可见控件，返回 (hwnd, 屏幕rect) 或 (0, None)。

        用于登录对话框内控件的屏幕坐标定位（ComboBox=账号下拉框，ComboLBox=展开的账号列表）。
        """
        import win32gui
        import win32process
        _main_hwnd, main_pid = self._main_window_identity()
        if not main_pid:
            return 0, None
        dialog_hwnd, _dialog_rect = self._find_login_dialog()
        dialog_root = 0
        if dialog_hwnd:
            try:
                dialog_root = win32gui.GetAncestor(dialog_hwnd, 3) or dialog_hwnd
            except Exception:
                dialog_root = dialog_hwnd
        found = []

        def cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                if win32gui.GetClassName(hwnd) != class_name:
                    return True
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                if pid != main_pid:
                    return True
                rect = win32gui.GetWindowRect(hwnd)
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
                if width <= 0 or height <= 0:
                    return True
                in_dialog = bool(
                    dialog_hwnd
                    and (hwnd == dialog_hwnd or win32gui.IsChild(dialog_hwnd, hwnd))
                )
                root = win32gui.GetAncestor(hwnd, 3) or hwnd
                related = bool(in_dialog or (dialog_root and root == dialog_root))
                if dialog_hwnd and not related:
                    return True
                found.append((hwnd, rect, in_dialog, width * height))
            except Exception:
                pass
            return True
        if dialog_hwnd:
            try:
                win32gui.EnumChildWindows(dialog_hwnd, cb, None)
            except Exception:
                pass
        win32gui.EnumWindows(cb, None)
        if not found:
            return 0, None
        found.sort(key=lambda item: (0 if item[2] else 1, -item[3]))
        best = found[0]
        return best[0], best[1]

    def _screen_click(self, x, y, after_sleep=0.5, *, target_hwnd):
        """Deliver one verified SendInput click to an explicit login HWND."""
        if getattr(self, '_android_boundary', lambda: None)() is not None:
            raise RuntimeError('ADB 模式禁止使用 Windows 系统鼠标')
        executor = getattr(self, 'executor', None)
        check_enabled = getattr(executor, 'check_enabled', None)
        if callable(check_enabled):
            try:
                result = check_enabled()
            except TaskDisabledException:
                raise
            except Exception:
                return False
            if result is False:
                return False
        _main_hwnd, expected_pid = self._main_window_identity()
        if not expected_pid or not target_hwnd:
            self.log_warning('登录点击未投递：无法确认目标 HWND 或游戏 PID')
            return False
        delivery = send_input_click(
            int(target_hwnd),
            int(expected_pid),
            (int(x), int(y)),
        )
        self._last_login_click_delivery = delivery
        if not delivery.delivered:
            self.log_warning(
                f'登录点击未投递：{delivery.reason}；目标HWND={delivery.target_hwnd or "?"}，'
                f'前台HWND={delivery.foreground_hwnd or "?"}，命中HWND={delivery.hit_hwnd or "?"}'
            )
            return False
        if after_sleep:
            self.sleep(after_sleep)
        return True

    def _box_center_screen(self, box, origin):
        """把对话框帧 OCR 得到的 Box 中心换算为屏幕坐标。"""
        cx = box.x + box.width / 2.0
        cy = box.y + box.height / 2.0
        return int(origin[0] + cx), int(origin[1] + cy)

    def _log_account_click_delivery(self, mode, box, screen_point=None, hwnd=None, delivered=None):
        """记录账号点击投递诊断；诊断失败不能影响实际点击。"""
        try:
            delivery = getattr(self, '_last_login_click_delivery', None)
            if hwnd is None and delivery is not None:
                hwnd = delivery.target_hwnd
            if hwnd is None:
                hwnd_window = getattr(self, 'hwnd', None)
                hwnd = getattr(hwnd_window, 'top_hwnd', None) or getattr(hwnd_window, 'hwnd', None)
            class_name = '?'
            if hwnd:
                try:
                    import win32gui
                    class_name = win32gui.GetClassName(hwnd)
                except Exception:
                    class_name = '?'
            point = f'({box.x + box.width / 2:.1f},{box.y + box.height / 2:.1f})'
            if screen_point is not None:
                point += f' screen=({screen_point[0]},{screen_point[1]})'
            self.log_info(
                f'账号点击投递诊断：方式={mode}，目标HWND={hwnd or "?"}，'
                f'类={class_name}，坐标={point}，'
                f'前台HWND={getattr(delivery, "foreground_hwnd", 0) or "?"}，'
                f'命中HWND={getattr(delivery, "hit_hwnd", 0) or "?"}'
            )
            if delivered is not None:
                record_click = getattr(self, '_evidence_click', None)
                if callable(record_click):
                    record_click(
                        mode,
                        screen_point or (box.x + box.width / 2, box.y + box.height / 2),
                        target_box=box,
                        window_point=(box.x + box.width / 2, box.y + box.height / 2),
                        screen_point=screen_point,
                        hwnd=hwnd,
                        stage='select_account',
                        delivered=delivered,
                    )
        except TaskDisabledException:
            raise
        except Exception:
            pass

    def _refresh_hwnd_window_snapshot(self):
        """刷新 HwndWindow 的句柄/子窗口快照，失败时仅记录诊断。"""
        try:
            hwnd_window = getattr(self, 'hwnd', None)
            refresh = getattr(hwnd_window, 'do_update_window_size', None)
            if callable(refresh):
                refresh()
                self.log_info('账号点击未确认：已刷新 HwndWindow 句柄快照')
                return True
        except TaskDisabledException:
            raise
        except Exception as e:
            try:
                self.log_warning(f'刷新 HwndWindow 句柄快照失败（继续尝试）：{e}')
            except TaskDisabledException:
                raise
            except Exception:
                pass
        return False

    def _profile_id_for(self, profile_name):
        profile = (self._load_profiles() or {}).get(profile_name) or {}
        profile_id = profile.get('profile_id')
        if self.integrity_service is not None:
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise ConfigIntegrityBlocked(f'validated account profile has no stable profile_id: {profile_name}')
            return profile_id
        return profile_id or profile_name

    def _bring_account_window_to_front(self, target_hwnd=None):
        """Force and verify the exact main/dialog/control window foreground."""
        try:
            main_hwnd, expected_pid = self._main_window_identity()
            if not expected_pid:
                return False
            if not target_hwnd:
                if getattr(self, '_login_in_dialog', False):
                    target_hwnd, _rect = self._find_login_dialog()
                target_hwnd = target_hwnd or main_hwnd
            result = force_foreground(int(target_hwnd), int(expected_pid))
            self._last_login_foreground = result
            if not result.ready:
                self.log_warning(
                    f'账号窗口置前校验失败：{result.reason}；'
                    f'目标HWND={result.target_hwnd or "?"}，前台HWND={result.foreground_hwnd or "?"}'
                )
            return bool(result.ready)
        except TaskDisabledException:
            raise
        except Exception as e:
            try:
                self.log_warning(f'账号窗口置前失败（继续尝试）：{e}')
            except Exception:
                pass
        return False

    def _main_login_screen_click(self):
        """Refresh the WGC login frame and SendInput-click its OCR login button."""
        self._refresh_hwnd_window_snapshot()
        main_hwnd, _main_pid = self._main_window_identity()
        if not main_hwnd or not self._bring_account_window_to_front(main_hwnd):
            self.log_warning('登录按钮点击取消：无法确认游戏主窗口已置前')
            return False
        self.sleep(0.2)
        try:
            reader = getattr(self, '_ocr_account_switch_main', None)
            if callable(reader):
                texts, sample = reader()
            else:
                texts, sample = self.ocr(), None
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f'登录按钮 OCR 失败：{e}')
            return False
        boundary = self.box_of_screen(0.3, 0.3, 0.7, 0.8)
        exact = getattr(self, '_exact_login_button_boxes', None)
        login_boxes = (
            exact(texts, boundary=boundary)
            if callable(exact)
            else self.find_boxes(texts, boundary=boundary, match=LOGIN_TEXTS)
        )
        if not login_boxes:
            self.log_warning('登录按钮点击取消：当前 OCR 帧未找到登录按钮')
            return False
        button = login_boxes[0]
        screen_point = (
            self._box_center_screen(button, sample.origin)
            if sample is not None else self._main_box_center_screen(button)
        )
        if screen_point is None:
            self.log_warning('登录按钮点击取消：无法从当前 OCR 框安全换算屏幕坐标')
            return False
        self.log_info(
            f'登录按钮投递诊断：方式=系统屏幕，OCR框中心=({button.x + button.width / 2:.1f},'
            f'{button.y + button.height / 2:.1f})，屏幕={screen_point}'
        )
        clicked = self._screen_click(
            *screen_point,
            after_sleep=3,
            target_hwnd=main_hwnd,
        )
        record_click = getattr(self, '_evidence_click', None)
        if callable(record_click):
            record_click(
                '系统屏幕（登录按钮）', screen_point, target_box=button,
                screen_point=screen_point, stage='login_click', delivered=bool(clicked),
            )
        self._last_login_click_mode = 'screen_main' if clicked else 'screen_main_failed'
        if clicked:
            self.log_info(f'已发送登录按钮点击（方式=系统屏幕，屏幕 {screen_point[0]},{screen_point[1]}）')
        return bool(clicked)

    def _find_logout_button_box(self):
        """Find the visible logout text in a fresh lower-screen OCR frame."""
        main_hwnd, _main_pid = self._main_window_identity()
        if not main_hwnd or not self._bring_account_window_to_front(main_hwnd):
            return None
        self.sleep(0.2)
        try:
            texts = self.ocr()
            boxes = self.find_boxes(
                texts,
                boundary=self.box_of_screen(0.0, 0.72, 0.35, 1.0),
                match=LOGOUT_TEXTS,
            )
            return boxes[0] if boxes else None
        except TaskDisabledException:
            raise
        except Exception as error:
            self.log_warning(f'退出登录按钮 OCR 失败：{error}')
            return None

    def _create_account_switch_capture_session(self):
        if getattr(self, '_android_boundary', lambda: None)() is not None:
            return nullcontext(None)
        executor = getattr(self, 'executor', None)
        device_manager = getattr(executor, 'device_manager', None)
        hwnd_window = getattr(device_manager, 'hwnd_window', None)
        exit_event = getattr(executor, 'exit_event', None)
        if hwnd_window is None or exit_event is None:
            return nullcontext(None)
        try:
            return AccountSwitchCaptureSession(hwnd_window, exit_event)
        except Exception as error:
            try:
                self.log_warning(f'账号切换前台截图初始化失败，保留 WGC：{error}')
            except Exception:
                pass
            return nullcontext(None)

    def _create_logout_capture_session(self):
        """Compatibility wrapper for focused logout tests and older callers."""
        return self._create_account_switch_capture_session()

    def _capture_logout_main_sample(self, capture_session):
        main_hwnd, _pid = self._main_window_identity()
        if not main_hwnd:
            return None
        if capture_session is not None and self._bring_account_window_to_front(main_hwnd):
            self.sleep(0.2)
            sample = capture_session.capture_main()
            if sample is not None:
                return sample
            self.log_warning(
                f'账号切换前台截图不可用（{capture_session.last_reason}），本轮回退 WGC'
            )
        try:
            frame = self.next_frame()
        except TaskDisabledException:
            raise
        except Exception as error:
            self.log_warning(f'退登 WGC 截图失败：{error}')
            return None
        if frame is None:
            return None
        origin = self.hwnd.get_capture_origin()
        if not origin:
            return None
        return CaptureSample(
            frame=frame,
            origin=(int(origin[0]), int(origin[1])),
            hwnd=int(main_hwnd),
            source='wgc',
            captured_at=time.monotonic(),
        )

    def _capture_account_switch_main_sample(self):
        """Capture the main login surface through the active transition session."""
        return self._capture_logout_main_sample(
            getattr(self, '_active_account_switch_capture', None)
        )

    def _ocr_account_switch_main(self):
        """Return OCR text and the exact main-window sample that produced it."""
        if getattr(self, '_active_account_switch_capture', None) is None:
            return self.ocr(), None
        sample = self._capture_account_switch_main_sample()
        if sample is None:
            return None, None
        return self.ocr(frame=sample.frame), sample

    def _find_logout_button_target(self, capture_session=None):
        sample = self._capture_logout_main_sample(capture_session)
        if sample is None:
            return None
        power_icon = self.find_one('logout_power_icon', threshold=0.6, frame=sample.frame)
        if power_icon is not None:
            return ObservedBox(power_icon, sample)
        texts = self.ocr(frame=sample.frame)
        boxes = self.find_boxes(
            texts,
            boundary=self.box_of_screen(0.0, 0.72, 0.35, 1.0),
            match=LOGOUT_TEXTS,
        )
        if boxes:
            return ObservedBox(boxes[0], sample)

        try:
            setting = self.find_one('esc_setting', threshold=0.6, frame=sample.frame)
        except TaskDisabledException:
            raise
        except Exception as error:
            self.log_warning(f'电源图标点击取消：无法在同一帧复核设置页：{error}')
            return None
        if setting is None:
            self.log_warning('电源图标点击取消：当前捕获帧未确认处于 ESC 设置页')
            return None
        height, width = sample.frame.shape[:2]
        x = round(width * LOGOUT_POWER_POSITION[0])
        y = round(height * LOGOUT_POWER_POSITION[1])
        return ObservedBox(Box(x - 1, y - 1, 2, 2, name='logout_power_icon'), sample)

    def _click_main_login_box(self, box, *, stage, after_sleep=0.5, origin=None):
        """SendInput-click a recognized box from the current main-window frame."""
        if box is None:
            return False
        main_hwnd, _main_pid = self._main_window_identity()
        if not main_hwnd or not self._bring_account_window_to_front(main_hwnd):
            return False
        point = self._box_center_screen(box, origin) if origin is not None else self._main_box_center_screen(box)
        if point is None:
            self.log_warning(f'{stage} 点击取消：无法安全换算 OCR/特征框坐标')
            return False
        delivered = bool(self._screen_click(
            *point,
            after_sleep=after_sleep,
            target_hwnd=main_hwnd,
        ))
        record_click = getattr(self, '_evidence_click', None)
        if callable(record_click):
            record_click(
                f'SendInput（{stage}）', point, target_box=box,
                screen_point=point, hwnd=main_hwnd, stage=stage,
                delivered=delivered,
            )
        return delivered

    def _logout_state(self, capture_session=None):
        """Return the currently observable logout state without sending input.

        ``confirm`` is deliberately checked before ``setting`` and ``main``.  A
        dropped confirm click leaves the dialog on screen; pressing ESC in that
        state would dismiss the dialog and waste a retry (and can change the
        meaning of the next click).
        """
        try:
            try:
                login_hit = self.do_find_account_drop_down(prefer_dialog=True)
            except TypeError:
                login_hit = self.do_find_account_drop_down()
            if login_hit is not None:
                return 'login'
        except TaskDisabledException:
            raise
        except Exception:
            pass

        self._logout_confirm_box = None
        self._logout_confirm_target = None
        capture_helper = getattr(self, '_capture_logout_main_sample', None)
        sample = capture_helper(capture_session) if callable(capture_helper) else None
        frame = sample.frame if sample is not None else None

        def observe(method, *args, **kwargs):
            if frame is not None:
                kwargs['frame'] = frame
            try:
                return method(*args, **kwargs)
            except TypeError:
                kwargs.pop('frame', None)
                return method(*args, **kwargs)

        if sample is not None:
            try:
                texts = self.ocr(frame=sample.frame)
                return_login = self.find_boxes(
                    texts,
                    boundary=self.box_of_screen(0.45, 0.35, 0.95, 0.85),
                    match=RETURN_LOGIN_TEXTS,
                )
            except TaskDisabledException:
                raise
            except Exception:
                return_login = []
            if return_login:
                self._logout_confirm_box = return_login[0]
                self._logout_confirm_target = ObservedBox(return_login[0], sample)
                return 'confirm'

        confirm = None
        try:
            confirm = observe(self.find_one,
                ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                threshold=0.6,
            )
        except TaskDisabledException:
            raise
        except Exception:
            try:
                confirm = observe(self.wait_feature,
                    ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter'],
                    raise_if_not_found=False,
                    threshold=0.6,
                    time_out=0.2,
                )
            except TaskDisabledException:
                raise
            except Exception:
                confirm = None
        if confirm is not None:
            self._logout_confirm_box = confirm
            if sample is not None:
                self._logout_confirm_target = ObservedBox(confirm, sample)
            return 'confirm'

        setting = None
        try:
            setting = observe(self.find_one, 'esc_setting', threshold=0.6)
        except TaskDisabledException:
            raise
        except Exception:
            try:
                setting = observe(self.wait_feature, 'esc_setting', raise_if_not_found=False, time_out=0.2)
            except TaskDisabledException:
                raise
            except Exception:
                setting = None
        if setting is not None:
            return 'setting'

        try:
            # 状态检测必须只观察；is_main() 会继续调用 wait_login()，而后者
            # 可能点击登录按钮，破坏退登状态机的输入边界。
            if frame is not None:
                try:
                    in_world = self.in_team_and_world(frame=frame)
                except TypeError:
                    in_world = self.in_team_and_world()
            else:
                in_world = self.in_team_and_world()
            if in_world:
                return 'main'
        except TaskDisabledException:
            raise
        except Exception:
            pass
        return 'unknown'

    def _main_box_center_screen(self, box):
        """把主窗口 OCR 框转换为屏幕坐标；无法安全换算时返回 None。"""
        try:
            hwnd_window = getattr(self, 'hwnd', None)
            get_origin = getattr(hwnd_window, 'get_capture_origin', None)
            if not callable(get_origin):
                return None
            origin = get_origin()
            if not origin:
                return None
            return self._box_center_screen(box, origin)
        except Exception:
            return None

    def _dialog_open_account_list(self):
        """点击 #32770 登录对话框的账号下拉框（ComboBox）展开账号列表，返回是否成功。"""
        hwnd, rect = self._find_control_hwnd('ComboBox')
        if not hwnd:
            self.log_warning('未找到登录对话框的账号下拉框（ComboBox）')
            return False
        bring_to_front = getattr(self, '_bring_account_window_to_front', None)
        if not callable(bring_to_front):
            self.log_warning('打开账号列表取消：无法确认登录窗口已置前')
            return False
        try:
            if not bring_to_front(hwnd):
                self.log_warning('打开账号列表取消：无法确认登录窗口已置前')
                return False
            self.sleep(0.2)
        except TaskDisabledException:
            raise
        except Exception:
            self.log_warning('打开账号列表取消：窗口置前失败')
            return False
        hwnd, rect = self._find_control_hwnd('ComboBox')
        if not hwnd:
            self.log_warning('未找到登录对话框的账号下拉框（ComboBox）')
            return False
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        self.log_info(f'点击账号下拉框 ComboBox @({cx},{cy})')
        clicked = self._screen_click(cx, cy, after_sleep=2, target_hwnd=hwnd)
        record_click = getattr(self, '_evidence_click', None)
        if callable(record_click):
            record_click(
                '系统屏幕（ComboBox）', (cx, cy),
                screen_point=(cx, cy), hwnd=hwnd, stage='open_account_list',
                delivered=bool(clicked),
            )
        return clicked

    def _find_and_click_account_in_combo_list(self, profile_name):
        """从当前可见 ComboLBox 客户区 OCR 并点击目标账号。

        ComboLBox 是账号列表本身，不包含灰色 selector 当前账号栏，因此它
        是主窗口和 #32770 对话框两种登录形态的权威候选区域。返回
        ``(clicked, matched_name, attempted)``；``attempted`` 表示已找到目标
        并尝试了系统点击，调用方不能再降级为 PostMessage。
        """
        try:
            hwnd, _rect = self._find_control_hwnd('ComboLBox')
        except TaskDisabledException:
            raise
        except Exception:
            return False, None, False
        if not hwnd:
            return False, None, False
        bring_to_front = getattr(self, '_bring_account_window_to_front', None)
        if not callable(bring_to_front) or not bring_to_front(hwnd):
            self.log_warning('账号点击取消：无法确认 ComboLBox 已置前')
            return False, None, False
        self.sleep(0.2)
        hwnd, _rect = self._find_control_hwnd('ComboLBox')
        if not hwnd:
            return False, None, False
        try:
            frame, origin = self._capture_hwnd_client(hwnd)
        except TaskDisabledException:
            raise
        except Exception:
            return False, None, False
        if frame is None or not origin:
            return False, None, False
        try:
            texts = self.ocr(frame=frame)
        except TaskDisabledException:
            raise
        except Exception:
            return False, None, False

        candidates = []
        matched = None
        for box in texts or []:
            name = (getattr(box, 'name', '') or '').strip()
            if not name:
                continue
            try:
                mapped_profile = self.match_profile_from_login(name)
            except TaskDisabledException:
                raise
            except ValueError:
                raise
            except Exception:
                mapped_profile = None
            if _is_login_identity(self, name) or mapped_profile:
                candidates.append(box)
            if mapped_profile == profile_name and matched is None:
                matched = (box, name)
        if matched is None:
            return False, None, False

        box, name = matched
        try:
            center_y = box.y + box.height / 2.0
            last_y = max((item.y + item.height / 2.0 for item in candidates), default=center_y)
            self.log_info(
                f'ComboLBox 目标诊断：目标={profile_name}，OCR={name}，'
                f'列表末项={abs(center_y - last_y) < 1.0}'
            )
        except Exception:
            pass
        sx, sy = self._box_center_screen(box, origin)
        self._last_account_click_mode = 'screen_combobox'
        sent = self._screen_click(sx, sy, after_sleep=2, target_hwnd=hwnd)
        diagnose = getattr(self, '_log_account_click_delivery', None)
        if callable(diagnose):
            diagnose('系统屏幕（ComboLBox）', box, (sx, sy), hwnd, delivered=bool(sent))
        if sent:
            self.log_info(f'已发送账号点击（方式=系统屏幕，ComboLBox，屏幕 {sx},{sy}）')
            return True, name, True
        self._last_account_click_mode = 'screen_combobox_failed'
        return False, name, True

    def _dialog_find_and_click_account(self, profile_name):
        """在 #32770 登录对话框/展开的账号列表（ComboLBox）中找到目标账号并点击。

        返回 (是否点击成功, 找到的账号文本或 None)。账号可能是掩码（199****9002）或 U 扫码（UTEST9002A）。
        """
        # 1) 展开的账号列表（ComboLBox）优先
        ok, name, attempted = self._find_and_click_account_in_combo_list(profile_name)
        if attempted:
            return ok, name
        # 2) 对话框主体里找（当前显示的账号 / 列表内嵌）
        dialog_hwnd, _dialog_rect = self._find_login_dialog()
        if not dialog_hwnd or not self._bring_account_window_to_front(dialog_hwnd):
            return False, None
        self.sleep(0.2)
        frame, origin = self._capture_hwnd_client(dialog_hwnd)
        if frame is not None:
            try:
                texts = self.ocr(frame=frame)
                for t in texts or []:
                    name = (t.name or '').strip()
                    if self.match_profile_from_login(name) == profile_name:
                        sx, sy = self._box_center_screen(t, origin)
                        self._last_account_click_mode = 'screen_dialog'
                        sent = self._screen_click(
                            sx, sy, after_sleep=2, target_hwnd=dialog_hwnd,
                        )
                        diagnose = getattr(self, '_log_account_click_delivery', None)
                        if callable(diagnose):
                            diagnose(
                                'SendInput（登录对话框）', t, (sx, sy), dialog_hwnd,
                                delivered=bool(sent),
                            )
                        if sent:
                            self.log_info(f'已发送账号点击（方式=系统屏幕，对话框，屏幕 {sx},{sy}）')
                            return True, name
                        self._last_account_click_mode = 'screen_dialog_failed'
            except TaskDisabledException:
                raise
            except Exception:
                pass
        return False, None

    def _dialog_click_login(self):
        """在 #32770 登录对话框里点击「登录」按钮，返回是否成功。"""
        dialog_hwnd, _dialog_rect = self._find_login_dialog()
        if not dialog_hwnd:
            return False
        bring_to_front = getattr(self, '_bring_account_window_to_front', None)
        if not callable(bring_to_front):
            return False
        try:
            if not bring_to_front(dialog_hwnd):
                return False
            self.sleep(0.2)
        except TaskDisabledException:
            raise
        except ValueError:
            raise
        except Exception:
            return False
        dialog_hwnd, _dialog_rect = self._find_login_dialog()
        if not dialog_hwnd:
            return False
        frame, origin = self._capture_hwnd_client(dialog_hwnd)
        if frame is None:
            return False
        try:
            texts = self.ocr(frame=frame)
            exact = getattr(self, '_exact_login_button_boxes', None)
            login_boxes = (
                exact(texts)
                if callable(exact) else self.find_boxes(texts, LOGIN_TEXTS)
            )
            if not login_boxes:
                self.log_warning('登录对话框里未找到「登录」按钮')
                return False
            box = login_boxes[0]
            sx, sy = self._box_center_screen(box, origin)
            self.log_info(f'点击登录按钮（屏幕 {sx},{sy}）')
            clicked = self._screen_click(
                sx, sy, after_sleep=3, target_hwnd=dialog_hwnd,
            )
            record_click = getattr(self, '_evidence_click', None)
            if callable(record_click):
                record_click(
                    '系统屏幕（登录按钮）', (sx, sy), target_box=box,
                    screen_point=(sx, sy), stage='login_click', delivered=bool(clicked),
                )
            return clicked
        except TaskDisabledException:
            raise
        except ValueError:
            raise
        except Exception:
            return False

    def _detect_current_account_from_login(self):
        """识别登录界面当前显示的账号，返回方案名（掩码或扫码 U 账号均可识别）。

        v1.03.73：主窗口内嵌登录走原路径；#32770 对话框登录走对话框帧。
        """
        if getattr(self, '_login_in_dialog', False):
            frame, origin = self._dialog_capture()
            if frame is not None:
                try:
                    dlg_texts = self.ocr(frame=frame)
                    for t in dlg_texts or []:
                        name = (t.name or '').strip()
                        if _is_login_identity(self, name):
                            profile = self.match_profile_from_login(name)
                            if profile:
                                self.log_info(f'对话框识别当前账号: {name} -> {profile}')
                                return profile
                    if dlg_texts:
                        self.log_info(f'对话框未匹配到方案，账号文本: {[t.name for t in dlg_texts][:8]}')
                except TaskDisabledException:
                    raise
                except ValueError:
                    raise
                except Exception:
                    pass
            return None
        reader = getattr(self, '_ocr_account_switch_main', None)
        texts, _sample = reader() if callable(reader) else (self.ocr(), None)
        candidates = [
            t.name.strip() for t in (texts or [])
            if _is_login_identity(self, t.name)
        ]
        for c in candidates:
            profile = self.match_profile_from_login(c)
            if profile:
                self.log_info(self.tr('Current account: {account}').format(account=c))
                return profile
        if candidates:
            self.log_info(f'未匹配到方案，登录界面账号: {candidates}')
        return None

    def _next_target_account(self):
        """序列中第一个未完成的账号（从「当前执行账号」开始旋转：选 A3 → A3..A10, A1..A2）；全部完成返回 None。"""
        sequence = self.get_sequence_accounts()
        if not sequence:
            return None
        start = (self.config.get(CURRENT_ACCOUNT) or '').strip()
        if start:
            for i, acc in enumerate(sequence):
                if self._same_account(acc, start):
                    sequence = sequence[i:] + sequence[:i]
                    break
        for acc in sequence:
            if not self._is_done(acc):
                return acc
        return None

    def _link_daily_profile(self, profile_name):
        """联动：把每日任务（DailyTask）的激活方案切换到 profile_name（并同步本任务自身配置）。

        多账号任务与每日任务是两个独立 Config（各自 configs/*.json），直接改
        self.config[DAILY_PROFILE] 不会影响 DailyTask 实例（执行/界面仍用旧方案）。
        正确做法：调用 DailyTask.switch_profile()（保存旧方案 → 加载新方案配置 → 写 DAILY_PROFILE），
        再刷新每日任务卡片显示。返回是否成功。
        """
        if not profile_name:
            return False
        try:
            daily_task = self.get_task_by_class(DailyTask)
            if daily_task is None:
                self.log_warning(f'未找到 DailyTask 实例，无法联动方案 {profile_name}')
                return False
            if self.integrity_service is not None:
                # Always bind by ID even when the visible label already looks
                # correct; the label can be stale while the verified snapshot
                # belongs to another account (or no account at all).
                binder = getattr(daily_task, 'bind_verified_profile', None)
                if not callable(binder):
                    raise ConfigIntegrityBlocked('DailyTask cannot bind a verified profile ID')
                binder(profile_name)
                self.log_info(f'每日任务方案已按验证 ID 联动到 {profile_name}')
            elif daily_task.config.get(DAILY_PROFILE) == profile_name:
                self.log_info(f'每日任务方案已是 {profile_name}')
            else:
                daily_task.switch_profile(profile_name)
                self.log_info(f'每日任务方案已联动到 {profile_name}', notify=True)
            try:
                self.config[DAILY_PROFILE] = profile_name
            except Exception:
                pass
            try:
                if hasattr(daily_task, '_refresh_gui'):
                    daily_task._refresh_gui()
            except Exception:
                pass
            return True
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error(f'联动每日任务方案失败: {profile_name}', e)
            return False

    def _require_daily_profile(self, profile_name):
        """在执行每日任务前强制联动到已验证的账号方案。

        不允许在方案缺失或切换失败时沿用上一个账号的 DailyTask
        配置，否则即使登录账号正确，也可能按错误方案执行。
        """
        integrity_service = getattr(self, 'integrity_service', None)
        if integrity_service is not None:
            result = integrity_service.check()
            if not result.ok:
                raise ConfigWriteBlocked(integrity_service.describe(result))
        profiles = self._load_profiles()
        if not profile_name or profile_name not in profiles:
            raise Exception(f'账号方案不存在，已停止每日任务: {profile_name or "未识别"}')
        if not self._link_daily_profile(profile_name):
            raise Exception(f'无法联动每日任务方案，已停止执行: {profile_name}')
        # Repeat the binding at the execution boundary and verify the ID from
        # the same validated profile map used by this task.
        daily_task = getattr(self, 'get_task_by_class', lambda *_: None)(DailyTask)
        self.config[CURRENT_ACCOUNT] = profile_name
        profile_id = profiles[profile_name].get('profile_id')
        if integrity_service is not None and (not isinstance(profile_id, str) or not profile_id.strip()):
            raise ConfigIntegrityBlocked(f'validated account profile has no stable profile_id: {profile_name}')
        if integrity_service is not None:
            binder = getattr(daily_task, 'bind_verified_profile', None)
            if not callable(binder):
                raise ConfigIntegrityBlocked('DailyTask cannot bind a verified profile ID')
            binder(profile_name, expected_profile_id=profile_id)
        if daily_task is not None:
            daily_task._runtime_status_account = profile_status_label(profile_name)
        self._current_profile_id = profile_id
        return True

    def _click_account_in_list(self, profile_name, interaction_mode=None, require_expanded=False):
        """在登录界面账号列表中点击指定的方案账号，返回是否点击成功。

        ``True`` 只表示 SendInput 已投递；账号是否选择成功必须由
        ``_wait_for_account_selection_stable`` 另行确认。保留
        ``interaction_mode`` 形参只为兼容旧调用方，生产路径不再提供
        PostMessage 或其他点击模式。
        """
        del interaction_mode
        self._last_account_click_mode = None
        if require_expanded:
            try:
                if not self._account_list_expanded():
                    self.log_warning('账号点击取消：列表未保持展开')
                    return False
            except TaskDisabledException:
                raise
            except Exception:
                self.log_warning('账号点击取消：无法确认列表展开状态')
                return False
        if getattr(self, '_login_in_dialog', False):
            ok, name = self._dialog_find_and_click_account(profile_name)
            if ok:
                suffix = (' (U账号 %s)' % name) if name and name.startswith('U') else ''
                self.log_info('已发送账号点击（方式=系统屏幕，对话框）%s' % suffix)
                return True
            self.log_error(f'登录对话框中没有找到目标账号 {profile_name}')
            return False

        combo_helper = getattr(self, '_find_and_click_account_in_combo_list', None)
        if callable(combo_helper):
            combo_ok, combo_name, combo_attempted = combo_helper(profile_name)
            if combo_attempted:
                return bool(combo_ok)

        main_identity = getattr(self, '_main_window_identity', None)
        bring_to_front = getattr(self, '_bring_account_window_to_front', None)
        if not callable(main_identity) or not callable(bring_to_front):
            self.log_warning('账号点击取消：无法确认游戏主窗口身份')
            return False
        main_hwnd, _main_pid = main_identity()
        if not main_hwnd or not bring_to_front(main_hwnd):
            self.log_warning('账号点击取消：无法确认游戏主窗口已置前')
            return False
        self.sleep(0.2)

        # 主登录界面只取一帧 OCR，同时覆盖掩码手机号、U 扫码账号和备用识别名。
        # 两次 OCR 可能跨越登录器刷新，导致目标框与实际点击帧不一致。
        try:
            reader = getattr(self, '_ocr_account_switch_main', None)
            texts, main_sample = reader() if callable(reader) else (self.ocr(), None)
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_warning(f'读取登录账号列表 OCR 失败：{e}')
            texts = []
        entry_count = getattr(self, '_account_entry_count', None)
        if callable(entry_count):
            try:
                if entry_count(texts) < 2:
                    self.log_warning('账号点击取消：当前 OCR 帧未确认列表展开')
                    return False
            except TaskDisabledException:
                raise
            except Exception:
                return False
        elif not self._account_list_expanded():
            self.log_warning('账号点击取消：列表未保持展开')
            return False
        accounts = []
        for account in texts or []:
            name = (getattr(account, 'name', '') or '').strip()
            if not name:
                continue
            try:
                mapped_profile = self.match_profile_from_login(name)
                matched = mapped_profile == profile_name
            except TaskDisabledException:
                raise
            except ValueError:
                raise
            except Exception:
                mapped_profile = None
                matched = False
            is_account_text = bool(account_pattern.search(name) or scan_account_pattern.match(name))
            if is_account_text or mapped_profile:
                accounts.append(account)
            if matched:
                screen_point = (
                    self._box_center_screen(account, main_sample.origin)
                    if main_sample is not None else self._main_box_center_screen(account)
                )
                if screen_point is None:
                    self.log_warning('账号点击取消：无法从目标 OCR 框安全换算屏幕坐标')
                    return False
                sent = self._screen_click(
                    *screen_point,
                    after_sleep=2,
                    target_hwnd=main_hwnd,
                )
                diagnose = getattr(self, '_log_account_click_delivery', None)
                if callable(diagnose):
                    diagnose(
                        'SendInput（主登录窗口）', account, screen_point, main_hwnd,
                        delivered=bool(sent),
                    )
                self._last_account_click_mode = 'sendinput_main' if sent else 'sendinput_main_failed'
                if sent:
                    self.log_info(f'已投递账号点击（方式=SendInput，目标={profile_name}，OCR={name}）')
                return bool(sent)

        # 找不到目标账号：输出列表内容便于排查（记住列表里没有该账号 / 识别失败）
        visible = [a.name for a in accounts][:15]
        self.log_error(
            f'登录界面账号列表中没有找到目标账号 {profile_name}；'
            f'当前列表可见：{visible}（若目标不在列表，说明该账号未在本设备登录器记住，'
            f'或已被其他账号挤出记住列表，需要扫码登录）'
        )
        return False

    def _open_account_list(self):
        """确保登录账号列表处于展开状态，失败时返回 False。"""
        drop_down = self.find_account_drop_down()
        delivered = False
        if self._account_list_expanded():
            self.log_info('账号列表已展开，跳过再次点击下拉框')
        elif getattr(self, '_login_in_dialog', False):
            delivered = bool(self._dialog_open_account_list())
            if not delivered:
                self.log_warning('对话框模式下打开账号下拉框失败')
                return False
        else:
            main_hwnd, _main_pid = self._main_window_identity()
            if not main_hwnd or not self._bring_account_window_to_front(main_hwnd):
                self.log_warning('打开账号列表取消：无法确认游戏主窗口已置前')
                return False
            self.sleep(0.2)
            drop_down = self.do_find_account_drop_down()
            if drop_down is None:
                self.log_warning('打开账号列表取消：刷新帧未找到账号下拉框')
                return False
            if getattr(self, '_login_in_dialog', False):
                delivered = bool(self._dialog_open_account_list())
            else:
                screen_point = self._main_box_center_screen(drop_down)
                if screen_point is None:
                    self.log_warning('打开账号列表取消：无法安全换算账号下拉框坐标')
                    return False
                delivered = bool(self._screen_click(
                    *screen_point,
                    after_sleep=2,
                    target_hwnd=main_hwnd,
                ))
                record_click = getattr(self, '_evidence_click', None)
                if callable(record_click):
                    record_click(
                        'SendInput（主账号下拉框）', screen_point, target_box=drop_down,
                        screen_point=screen_point, hwnd=main_hwnd,
                        stage='open_account_list', delivered=delivered,
                    )
            if not delivered:
                return False

        expanded = self.wait_until(
            self._account_list_expanded,
            time_out=10,
            settle_time=1,
            raise_if_not_found=False,
        )
        record_stage = getattr(self, '_evidence_stage', None)
        if callable(record_stage):
            record_stage(
                'account_list_result',
                detail=f'delivered={bool(delivered)},confirmed={bool(expanded)}',
            )
        if not expanded:
            self.log_warning('账号列表未能展开')
            self.screenshot('multi')
            return False
        return True

    def _wait_for_account_selection_stable(self, target, time_out=20, consecutive=2):
        """等待点击账号后的登录界面稳定显示目标账号。

        游戏登录器在点击列表项后可能短暂保留下拉列表、返回空 OCR 帧，或先
        显示旧账号再切换到新账号。此处把这些状态视为过渡态，要求下拉列表已
        收起且目标账号连续识别 ``consecutive`` 次后才确认，避免把闪烁帧误判
        为账号选择失败并立即重复点击。

        返回 ``(是否稳定确认, 最后识别到的方案名)``，超时后由调用方决定是否
        重新展开列表；不在此方法中执行第二次点击，保证正式任务和测试路径共享
        同一套重试边界。
        """
        state = {
            'matches': 0,
            'last_current': None,
            'last_expanded': None,
        }

        def observe():
            try:
                expanded = bool(self._account_list_expanded())
            except TaskDisabledException:
                raise
            except Exception:
                # 某些登录器闪烁帧无法判断列表控件，继续用账号 OCR 做宽松探测。
                expanded = False

            previous_expanded = state['last_expanded']
            expanded_changed = previous_expanded is not expanded
            if expanded:
                state['matches'] = 0
                if expanded_changed:
                    self.log_info('账号选择后列表仍展开，等待界面收起并稳定')
                state['last_expanded'] = True
                return False

            state['last_expanded'] = False
            current = self._detect_current_account_from_login()
            record_identity = getattr(self, '_evidence_identity', None)
            if callable(record_identity):
                record_identity(current, stage='selection_confirmation')
            previous = state['last_current']
            state['last_current'] = current
            current_changed = not self._same_account(previous, current)
            if current_changed:
                self.log_info(
                    f'账号选择稳定检测：当前识别为 {current or "未识别"}，'
                    f'目标为 {target}'
                )
            if expanded_changed and previous_expanded is True:
                self.log_info('账号列表已收起，继续等待账号识别稳定')

            if self._same_account(target, current):
                state['matches'] += 1
                if state['matches'] >= consecutive:
                    return True
            else:
                if current_changed:
                    self.log_info('账号选择界面仍在闪烁或切换，继续等待稳定')
                state['matches'] = 0
            return False

        stable = self.wait_until(
            observe,
            time_out=time_out,
            settle_time=0,
            raise_if_not_found=False,
        )
        if stable:
            self.log_info(f'账号选择已稳定确认：{target}（连续 {consecutive} 次）')
        else:
            self.log_warning(
                f'账号选择稳定检测超时：目标 {target}，最后识别 '
                f'{state["last_current"] or "未识别"}，准备重新选择'
            )
        return bool(stable), state['last_current']

    def _select_account_with_retry(self, target, max_retries=5):
        """重复展开、选择并核对目标账号，确认成功后返回 True。

        OCR 显示账号与目标不一致时不会立即终止，而是重新展开列表并再次选择；
        达到重试上限仍无法确认时才安全停止，避免误登录其他账号。
        """
        last_current = None
        try:
            selector_expanded = bool(self._account_list_expanded())
        except TaskDisabledException:
            raise
        except Exception:
            selector_expanded = True
        if not selector_expanded:
            try:
                last_current = self._detect_current_account_from_login()
            except TaskDisabledException:
                raise
            except ValueError:
                raise
            except Exception:
                last_current = None
            if self._same_account(last_current, target):
                self.log_info('目标账号已处于选中状态，跳过重复点击')
                return True

        unconfirmed_deliveries = 0
        for attempt in range(1, max_retries + 1):
            self._account_switch_attempt = attempt
            record_stage = getattr(self, '_evidence_stage', None)
            if callable(record_stage):
                record_stage('select_attempt', attempt=attempt)
            self.sleep(1)
            if unconfirmed_deliveries:
                refresh = getattr(self, '_refresh_hwnd_window_snapshot', None)
                if callable(refresh):
                    refresh()
            if not self._open_account_list():
                self.log_warning(f'第 {attempt}/{max_retries} 次打开账号列表失败，准备重试')
                continue

            clicked = self.wait_until(
                lambda: self._click_account_in_list(target),
                time_out=10,
                raise_if_not_found=False,
            )
            actual_mode = getattr(self, '_last_account_click_mode', None) or 'sendinput'
            if not clicked:
                self.log_warning(
                    f'第 {attempt}/{max_retries} 次未能投递目标账号点击（方式={actual_mode}），准备重试'
                )
                if callable(record_stage):
                    record_stage(
                        'selection_result', attempt=attempt,
                        detail=f'{actual_mode}:delivered=False,confirmed=False,current=unknown',
                    )
                continue

            stable, last_current = self._wait_for_account_selection_stable(target)
            self.log_info(
                f'账号点击投递后确认：目标 {target}，方式={actual_mode}，'
                f'当前显示账号：{last_current}'
            )
            if callable(record_stage):
                record_stage(
                    'selection_result', attempt=attempt,
                    detail=(
                        f'{actual_mode}:delivered=True,confirmed={bool(stable)},'
                        f'current={last_current or "unknown"}'
                    ),
                )
            if stable:
                self.log_info(f'确认已选择账号：{target}')
                return True

            unconfirmed_deliveries += 1

            self.log_warning(
                f'账号选择不一致（目标 {target}，当前 {last_current or "未识别"}），'
                f'重新选择（{attempt}/{max_retries}）'
            )

        self.log_error(
            f'账号选择在 {max_retries} 次重试后仍失败；'
            f'目标 {target}，最后识别 {last_current or "未识别"}。为防止误登录已停止。'
        )
        self.screenshot('multi')
        raise Exception(self.tr('Failed to switch account'))

    def _confirm_target_before_login(self, target, max_retries=3):
        """点登录前再次核对目标；不一致时重新选择，而不是立即停止。"""
        last_shown = None
        for attempt in range(1, max_retries + 1):
            record_stage = getattr(self, '_evidence_stage', None)
            if callable(record_stage):
                record_stage('verify_before_login_attempt', attempt=attempt)
            last_shown = self._detect_current_account_from_login()
            record_identity = getattr(self, '_evidence_identity', None)
            if callable(record_identity):
                record_identity(last_shown, stage='verify_before_login')
            if self._same_account(last_shown, target):
                return True

            self.log_warning(
                f'登录前账号不一致（目标 {target}，当前 {last_shown or "未识别"}），'
                f'重新选择目标账号（{attempt}/{max_retries}）'
            )
            if attempt < max_retries:
                try:
                    self._select_account_with_retry(target, max_retries=2)
                except TaskDisabledException:
                    raise
                except Exception as e:
                    self.log_warning(f'重新选择目标账号失败，将继续重试: {e}')
                self.sleep(1)

        self.log_error(
            f'登录前经过 {max_retries} 次重试仍无法确认目标账号；'
            f'目标 {target}，当前 {last_shown or "未识别"}。为防止误登录已停止。'
        )
        self.screenshot('multi')
        raise Exception(self.tr('Login aborted: displayed account does not match target'))

    def _click_login_for_target(self, target):
        """确认当前账号后点击登录按钮，并确认登录界面开始转换。"""
        last_error = None
        for attempt in range(1, 4):
            self._account_switch_attempt = attempt
            record_stage = getattr(self, '_evidence_stage', None)
            if callable(record_stage):
                record_stage('login_click_attempt', attempt=attempt)
            try:
                self._confirm_target_before_login(target)
                if getattr(self, '_login_in_dialog', False):
                    clicked = self._dialog_click_login()
                else:
                    clicked = self._main_login_screen_click()
                if clicked is False:
                    if callable(record_stage):
                        record_stage(
                            'login_click_result', attempt=attempt,
                            detail='delivered=False,confirmed=False',
                        )
                    raise Exception('登录按钮点击未成功')

                # 主窗口和独立对话框都必须确认登录控件稳定消失；
                # 不能在按钮未命中时直接进入 180 秒空等。
                started = self.wait_until(
                    lambda: self.do_find_account_drop_down() is None,
                    time_out=5,
                    settle_time=1,
                    raise_if_not_found=False,
                )
                if callable(record_stage):
                    record_stage(
                        'login_click_result', attempt=attempt,
                        detail=f'delivered=True,confirmed={bool(started)}',
                    )
                if not started:
                    raise Exception('点击登录后登录界面状态未发生变化')
                return True
            except TaskDisabledException:
                raise
            except Exception as e:
                last_error = e
                self.log_warning(f'登录按钮点击第 {attempt}/3 次失败：{e}')
                if attempt < 3:
                    self.log_info('登录按钮未触发界面转换，下一次重新发现窗口并刷新 OCR')
                    self.sleep(1)
        self.log_error(f'登录按钮连续 3 次未成功：{last_error}')
        self.screenshot('multi')
        raise Exception(self.tr('Failed to click login button'))

    def _visible_login_profiles(self):
        """按登录列表显示顺序返回能映射到本地方案的账号名。"""
        texts = None
        if getattr(self, '_login_in_dialog', False):
            hwnd, _rect = self._find_control_hwnd('ComboLBox')
            if hwnd:
                frame, _origin = self._capture_hwnd_client(hwnd)
                if frame is not None:
                    try:
                        texts = self.ocr(frame=frame)
                    except TaskDisabledException:
                        raise
                    except Exception:
                        texts = None
            if not texts:
                texts = self._ocr_login_dialog()
        else:
            reader = getattr(self, '_ocr_account_switch_main', None)
            texts, _sample = reader() if callable(reader) else (self.ocr(), None)

        profiles = []
        for box in texts or []:
            name = (box.name or '').strip()
            if not name or not _is_login_identity(self, name):
                continue
            profile = self.match_profile_from_login(name)
            if profile and profile not in profiles:
                profiles.append(profile)
        return profiles

    def _select_and_login_first_available(self):
        """选择登录列表中第一个能映射到本地方案的账号并登录。"""
        MultiAccountDailyTask._guard_account_transition(self)
        self._wait_login_screen_stable(time_out=120)
        if not self._open_account_list():
            raise Exception(self.tr('Failed to open account list'))
        profiles = self.wait_until(
            self._visible_login_profiles,
            time_out=10,
            settle_time=1,
            raise_if_not_found=False,
        )
        if not profiles:
            self.log_error('登录列表中没有能映射到本地方案的账号')
            self.screenshot('multi')
            raise Exception('没有可用的已配置账号')
        target = profiles[0]
        self.log_info(f'自动识别登录列表中的第一个可用账号: {target}')
        switch = getattr(self, 'switch_to_account', None)
        return switch(target) if callable(switch) else MultiAccountDailyTask.switch_to_account(self, target)

    def _select_and_login_account(self):
        """从本轮序列取第一个未完成账号，在登录界面选择并登录；全部完成返回 None。"""
        MultiAccountDailyTask._guard_account_transition(self)
        target = self._next_target_account()
        if target is None:
            return None
        # Target resolution is the only responsibility left here.  The public
        # entry owns login-screen stabilization, OCR selection, retries, login,
        # and ensure_main for both production and test callers.
        switch = getattr(self, 'switch_to_account', None)
        return switch(target) if callable(switch) else MultiAccountDailyTask.switch_to_account(self, target)

    def _login_back_to(self, first_account):
        """全部完成后登录回起始账号，并提醒用户本轮结束。"""
        self.log_info(f'全部账号每日任务已完成，准备登录回起始账号 {first_account}', notify=True)
        if not first_account:
            self._notify_user('多账号每日任务完成', '本轮全部账号已完成')
            return
        try:
            self._select_and_login_specific(first_account)
            self.log_info(f'已登录回起始账号: {first_account}', notify=True)
            self._notify_user(
                '多账号每日任务完成',
                f'序列本轮全部完成，已登录回 {first_account}。可退出游戏进程切换下一个序列。',
            )
        except TaskDisabledException:
            raise
        except Exception as e:
            self.log_error('登录回起始账号失败，请手动登录', e)
            self._notify_user(
                '多账号每日任务完成（需手动处理）',
                f'序列本轮已完成，但登录回起始账号 {first_account} 失败，请手动登录。',
            )

    def _select_and_login_specific(self, profile_name):
        """在登录界面选择并登录指定账号（不执行每日任务）。"""
        switch = getattr(self, 'switch_to_account', None)
        return switch(profile_name) if callable(switch) else MultiAccountDailyTask.switch_to_account(self, profile_name)

    def _select_and_login_sequence(self, profile_names, progress_callback=None):
        """连续登录一组账号，只模拟每个账号每日任务完成后的切换部分。

        调用方应从登录界面开始。本方法不执行每日任务、不写完成进度；每次登录都
        复用正式的指定账号流程，并只在相邻账号之间退登。
        """
        targets = list(profile_names or [])
        if not targets:
            raise ValueError('连续切换账号列表不能为空')

        logged_profiles = []
        total = len(targets)
        for index, target in enumerate(targets, start=1):
            if progress_callback:
                progress_callback(index, total, target)
            self.log_info(f'连续切换 {index}/{total}：准备登录 {target}')
            logged_profiles.append(self._select_and_login_specific(target))
            if index < total:
                self.log_info(f'模拟 {target} 每日任务已完成，仅执行退登并切换下一个账号')
                self._switch_to_login()
                self.sleep(2)
        return logged_profiles

    def find_account_drop_down(self):
        return self.wait_until(self.do_find_account_drop_down, time_out=60, settle_time=2, raise_if_not_found=True)

    def _account_entry_count(self, texts):
        """OCR 文本中账号条目（掩码 199****0005 或 U 扫码账号）的框数量。

        同一账号文本出现在不同位置（收起态 ComboBox + 展开列表）各算一个，
        用于区分「收起态（1 个）」与「列表已展开（≥2 个）」。
        """
        count = 0
        for t in texts or []:
            name = (t.name or '').strip()
            if name and _is_login_identity(self, name):
                count += 1
        return count

    def _account_list_expanded(self):
        """账号下拉列表是否已展开（账号条目 ≥2）。

        对话框模式：优先检测可见且尺寸正常的 ComboLBox 控件；回退统计对话框帧 OCR 账号条目。
        主窗口模式：统计主窗口 OCR 账号条目。
        """
        if getattr(self, '_login_in_dialog', False):
            try:
                hwnd, rect = self._find_control_hwnd('ComboLBox')
                if hwnd:
                    w = rect[2] - rect[0]
                    h = rect[3] - rect[1]
                    if w >= 200 and h >= 100:
                        return True
            except TaskDisabledException:
                raise
            except ValueError:
                raise
            except Exception:
                pass
            dlg_texts = self._ocr_login_dialog()
            return bool(dlg_texts) and self._account_entry_count(dlg_texts) >= 2
        reader = getattr(self, '_ocr_account_switch_main', None)
        texts, _sample = reader() if callable(reader) else (self.ocr(), None)
        return bool(texts) and self._account_entry_count(texts) >= 2

    def do_find_account_drop_down(self, main_frame=None, prefer_dialog=False) -> object | None:
        """登录界面账号下拉框检测（v1.03.74：收起/展开状态都视为登录就绪）。

        命中条件：登录特征（登录/Log/登入）存在 且 至少 1 个账号条目（掩码或 U 扫码账号）。
        下拉列表展开态（账号条目 ≥2）同样命中——调用方用 _account_list_expanded() 区分
        展开态，避免把「列表已展开」误判为「点击下拉框无效果」。
        先查主窗口帧（登录界面内嵌变体），无则查 #32770 登录对话框帧（独立窗口变体），
        命中对话框帧时置 self._login_in_dialog = True，后续账号操作改用对话框帧。
        """
        def judge(texts, in_dialog):
            structural = list(self.find_boxes(texts, account_pattern))
            exact = getattr(self, '_exact_login_button_boxes', None)
            login_boxes = (
                exact(texts)
                if callable(exact) else self.find_boxes(texts, LOGIN_TEXTS)
            )
            entries = structural + [
                t for t in (texts or [])
                if t not in structural and _is_login_identity(self, (t.name or '').strip())
            ]
            if not login_boxes or len(entries) < 1:
                return None
            self._login_in_dialog = in_dialog
            return entries[0]

        ocr_dialog = getattr(self, '_ocr_login_dialog', None)
        def dialog_hit():
            dlg_texts = ocr_dialog() if callable(ocr_dialog) else None
            if dlg_texts:
                return judge(dlg_texts, True)
            return None

        prefer_dialog = bool(
            prefer_dialog
            or getattr(self, '_login_in_dialog', False)
            or getattr(self, '_active_account_switch_capture', None) is not None
        )
        if prefer_dialog:
            hit = dialog_hit()
            if hit is not None:
                return hit
        if main_frame is None:
            reader = getattr(self, '_ocr_account_switch_main', None)
            main_texts, _sample = reader() if callable(reader) else (self.ocr(), None)
        else:
            main_texts = self.ocr(frame=main_frame)
        hit = judge(main_texts, False)
        if hit is not None:
            return hit
        # 主窗口无特征 → #32770 登录对话框帧
        if not prefer_dialog:
            hit = dialog_hit()
            if hit is not None:
                return hit
        return None


from ok import run_task
from config import config

if __name__ == "__main__":
    initialize_account_runtime()
    run_task(config, task=MultiAccountDailyTask, debug=True)
