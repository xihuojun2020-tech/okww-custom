# SPDX-License-Identifier: AGPL-3.0-or-later
"""Production account selection exposed as device-free package JSON."""

from src.account_change_lock import get_account_change_lock
from src.account_display import account_display_label
from src.config_integrity import ConfigIntegrityBlocked
from src.runtime.native_config import Config


UNREGISTERED_SUMMARY = '无序列 · 不认证、不写入账号进度（每日、海墟、深塔及多账号任务除外）'


class NativeAccountContext:
    def __init__(self, host, *, live_reader=None):
        self.host = host
        self.live_reader = live_reader

    def _owner(self):
        from src.runtime.native_metadata import task_id
        return next((task for task in self.host.tasks.values()
                     if task_id(task) == 'MultiAccountDailyTask'), None)

    def _foreground(self):
        from src.runtime.native_task import NativeTriggerTask
        return next((task for task in self.host.tasks.values()
                     if task.running and not isinstance(task, NativeTriggerTask)), None)

    def _live(self):
        reader = self.live_reader
        if reader is None:
            from src.runtime.native_live_status import NativeLiveReader
            reader = NativeLiveReader(self.host.context.data_dir)
        else:
            reader.reload()
        return next((value for value in reader.owners()
                     if value['running'] and value['foreground_task_id']), None)

    @staticmethod
    def _reload(owner):
        previous = owner.config
        owner.config = Config(previous.config_file.stem, owner.default_config,
                              folder=previous.config_file.parent, validator=previous.validator)
        owner.config.on_change = previous.on_change

    @staticmethod
    def _unavailable(reason):
        return {'available': False, 'readonly': True, 'reason': reason,
                'sequences': [], 'accounts': [], 'sequence': '', 'account': '',
                'saved_sequence': '', 'saved_account': '', 'verified_account': None,
                'running_account': None, 'foreground_task_id': '',
                'unregistered': False, 'summary': reason}

    def snapshot(self):
        owner = self._owner()
        if owner is None:
            return self._unavailable('当前任务包未注册多账号每日任务')
        with get_account_change_lock(owner.config.config_file.parent):
            service = owner.integrity_service
            if service is not None and not service.paths.master.exists() and not service.paths.working.exists():
                return self._unavailable('尚未建立可信账号配置，请建立首账号或导入账号配置包')
            if service is not None:
                integrity = service.check(record_incident=False)
                if not integrity.ok:
                    raise ConfigIntegrityBlocked(service.describe(integrity))
            foreground = self._foreground()
            live = self._live()
            if foreground is None:
                self._reload(owner)
            return self._snapshot(owner, foreground, live)

    def _snapshot(self, owner, foreground, live):
        from src.task.MultiAccountDailyTask import CURRENT_ACCOUNT, UNREGISTERED_ACCOUNT
        sequences = owner.get_sequence_names()
        saved_sequence = owner.get_current_sequence()
        saved_account = owner.config.get(CURRENT_ACCOUNT) or ''
        sequence, account = saved_sequence, saved_account
        profiles = owner._load_profiles()
        def identity(name):
            profile = profiles[name]
            return {'value': name, 'label': account_display_label(profile),
                    'profile_id': str(profile['profile_id'])}
        verified = None
        verification = getattr(self.host.executor, '_account_feature_run', None)
        if (foreground is not None and verification is not None
                and verification.current is foreground and verification.profile_id is not None):
            name = next(name for name, profile in profiles.items()
                        if str(profile['profile_id']) == str(verification.profile_id))
            verified = identity(name)
            account = name
            sequence = next((value for value in sequences if name in owner.get_sequence_accounts(value)), sequence)
        members = owner.get_sequence_accounts(sequence)
        # Only a verified production FeatureRun is labelled verified. Persisted
        # foreground profile status is useful context, not verification evidence.
        running = None
        if live is not None and live['live'].get('profile_id'):
            name = next(name for name, profile in profiles.items()
                        if str(profile['profile_id']) == live['live']['profile_id'])
            running = identity(name)
        readonly = foreground is not None or live is not None
        unregistered = account == UNREGISTERED_ACCOUNT
        choices = [{'value': '', 'label': '请选择账号', 'profile_id': None},
                   {'value': UNREGISTERED_ACCOUNT, 'label': UNREGISTERED_ACCOUNT, 'profile_id': None}]
        choices.extend(identity(name) for name in members)
        label = next((item['label'] for item in choices if item['value'] == account), '请选择账号')
        return {'available': True, 'sequences': [{'value': value, 'label': value} for value in sequences],
                'accounts': choices, 'sequence': sequence, 'account': account,
                'saved_sequence': saved_sequence, 'saved_account': saved_account,
                'verified_account': verified, 'running_account': running,
                'readonly': readonly, 'reason': '前台任务正在执行，账号上下文只读' if readonly else '',
                'foreground_task_id': type(foreground).__name__ if foreground is not None else
                    live['foreground_task_id'] if live is not None else '',
                'unregistered': unregistered,
                'summary': UNREGISTERED_SUMMARY if unregistered else f'{sequence} · {label}'}

    def set(self, **values):
        if not values or set(values) - {'sequence', 'account'} or any(type(value) is not str for value in values.values()):
            raise ValueError('账号上下文只接受sequence/account字符串')
        return self._set(values, {})

    def set_config(self, values):
        """Already metadata-validated task values commit with context in one write."""
        from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE, CURRENT_ACCOUNT
        keys = {CURRENT_SEQUENCE: 'sequence', CURRENT_ACCOUNT: 'account'}
        return self._set({keys[key]: value for key, value in values.items() if key in keys},
                         {key: value for key, value in values.items() if key not in keys})

    def _set(self, values, ordinary):
        from src.task.MultiAccountDailyTask import CURRENT_SEQUENCE, CURRENT_ACCOUNT, UNREGISTERED_ACCOUNT
        owner = self._owner()
        if owner is None:
            raise RuntimeError('当前任务包未注册多账号每日任务')
        with get_account_change_lock(owner.config.config_file.parent):
            current = self.snapshot()
            if current['readonly']:
                raise RuntimeError(current['reason'])
            sequence = values.get('sequence', current['saved_sequence'])
            if sequence not in owner.get_sequence_names():
                raise ValueError('当前序列不在可信账号配置中')
            members = owner.get_sequence_accounts(sequence)
            account = values.get('account', current['saved_account'])
            if account not in ('', UNREGISTERED_ACCOUNT) and account not in members:
                if 'account' in values:
                    raise ValueError('当前账号不属于所选序列')
                account = ''
            owner.config.update({**ordinary, CURRENT_SEQUENCE: sequence, CURRENT_ACCOUNT: account})
            return self.snapshot()
