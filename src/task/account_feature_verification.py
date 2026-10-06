"""Strict game identity verification; raw codes never enter evidence metadata."""
from dataclasses import dataclass, field
import hashlib
import re
import time
import unicodedata
from uuid import uuid4

import cv2
import numpy as np

from src.evidence.model import now_iso
from src.config_integrity import ConfigIntegrityBlocked

STATUS_LABELS = {'verified': '已核验', 'unreadable': '无法稳定读取', 'unbound': '未绑定',
                 'mismatch': '账号不一致', 'ambiguous': '重复绑定', 'context_invalid': '核验上下文失效'}


def parse_feature_code(text):
    text = unicodedata.normalize('NFKC', str(text)).strip()
    match = re.fullmatch(r'特[征徵][码碼]\s*[:：]?\s*([0-9]+)', text)
    return match.group(1) if match else None


def region(frame):
    from config import blur_area
    h, w = frame.shape[:2]
    box = blur_area(w, h)
    return int(box.x), int(box.y), int(box.width), int(box.height)


def read_code(task, frame):
    x, y, w, h = region(frame)
    crop = frame[y:y+h, x:x+w].copy()
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # Use the configured engine directly: framework text fixes and error screenshots
    # must never alter or publish a private identity crop.
    try:
        config = task.executor.config['ocr']
        kind = config.get('default', config).get('lib')
        engine = task.executor.ocr_lib('default')
        if kind == 'onnxocr':
            result = engine.ocr(crop)
            entries = result[0] if result and result[0] is not None else []
            values = [(item[0], item[1][0], item[1][1]) for item in entries]
        elif kind == 'rapidocr':
            result = engine(crop)
            values = list(zip(result.boxes, result.txts, result.scores)) if result.boxes is not None else []
        else:
            raise RuntimeError('unsupported engine')
        values.sort(key=lambda item: (item[0][0][1], item[0][0][0]))
        if any(float(confidence) < .8 for _, _, confidence in values):
            return None
        return parse_feature_code(''.join(text for _, text, _ in values))
    except Exception:
        raise RuntimeError('特征码 OCR 读取失败') from None


@dataclass
class Observation:
    status: str
    code: str | None = field(default=None, repr=False)
    captured_at: str = field(default_factory=now_iso)
    frame: object = field(default=None, repr=False)
    hashes: tuple = ()
    crop: tuple = ()

    def metadata(self):
        return dict(status=self.status, captured_at=self.captured_at,
                    frame_hashes=list(self.hashes), region=list(self.crop),
                    resolution=list(self.frame.shape[:2][::-1]) if self.frame is not None else None)


def observe(capture, decode, check, pause, *, timeout=5, clock=time.monotonic):
    deadline = clock() + timeout
    seen, hashes = set(), []
    previous, count, last = None, 0, None
    while clock() < deadline:
        check()
        frame = capture()
        check()
        if (not isinstance(frame, np.ndarray) or not frame.size or frame.dtype != np.uint8
                or frame.ndim != 3 or frame.shape[2] != 3):
            previous, count = None, 0
            pause(.1)
            continue
        last = frame.copy()
        digest = hashlib.sha256(memoryview(last)).hexdigest()
        if digest in seen:
            previous, count = None, 0
            pause(.1)
            continue
        seen.add(digest)
        code = decode(last)
        check()
        if clock() >= deadline:
            break
        count = count + 1 if code and code == previous else int(bool(code))
        previous = code
        hashes.append(digest)
        if count >= 3:
            return Observation('verified', code, frame=last, hashes=tuple(hashes[-3:]), crop=region(last))
        pause(.1)
    return Observation('unreadable', frame=last, hashes=tuple(hashes[-3:]), crop=region(last) if last is not None else ())


def resolve(observation, profiles, expected=None):
    if observation.status != 'verified':
        return observation.status, None
    matches = [record for record in profiles
               if str(record.account.get('game_feature_code') or '').strip() == observation.code]
    if len(matches) > 1:
        return 'ambiguous', None
    if not matches:
        return 'unbound', None
    record = matches[0]
    return ('mismatch' if expected and str(record.profile_id) != str(expected) else 'verified'), record


def window_id(task):
    window = task.executor.device_manager.hwnd_window
    if window is None or not window.exists:
        raise ConfigIntegrityBlocked('特征码核验：游戏窗口不可用')
    return window.hwnd


def expected_profile(task):
    current = task.executor.current_task
    if getattr(current, '_active_account_switch_capture', None) is not None:
        raise ConfigIntegrityBlocked('账号切换中，不能开始特征码核验')
    if type(current).__name__ in ('MultiAccountDailyTask', 'MultiAccountWeeklyGardenTask'):
        identity = getattr(current, '_current_profile_id', None)
        if not identity:
            raise ConfigIntegrityBlocked('多账号子任务尚未冻结期望账号')
        return identity
    verification = getattr(task.executor, '_account_feature_run', None)
    if verification is not None:
        verification.guard()
        return verification.profile_id
    from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_ACCOUNT
    owner = task.get_task_by_class(MultiAccountDailyTask)
    if owner is None:
        raise ConfigIntegrityBlocked('顶部账号选择不可用，已停止任务')
    name = owner.config.get(CURRENT_ACCOUNT) or ''
    selected = owner._load_profiles().get(name)
    if name not in owner.get_sequence_accounts() or not selected or not selected.get('profile_id'):
        raise ConfigIntegrityBlocked('请先在任务页顶部选择当前序列和账号')
    return selected['profile_id']


def begin_task_run(task):
    """Executor boundary: one verification per start; multi tasks verify each visit."""
    from src.gui.navigation_sections import classify_task, TASKS
    from src.task.MultiAccountDailyTask import MultiAccountDailyTask, CURRENT_SEQUENCE, CURRENT_ACCOUNT
    if classify_task(task) != TASKS:
        return
    task.executor._account_feature_run = None
    if isinstance(task, MultiAccountDailyTask):
        owner = task.get_task_by_class(MultiAccountDailyTask)
        if task is not owner:
            task.config[CURRENT_SEQUENCE] = owner.config[CURRENT_SEQUENCE]
            task.config[CURRENT_ACCOUNT] = owner.config[CURRENT_ACCOUNT]
        # Validate the common selection now, but read the game only after login.
        name = task.config.get(CURRENT_ACCOUNT) or ''
        if not name or name not in task.get_sequence_accounts():
            raise ConfigIntegrityBlocked('请先在任务页顶部选择当前序列和账号')
        return
    expected = expected_profile(task)
    from src.task.WWOneTimeTask import WWOneTimeTask
    WWOneTimeTask.run(task)
    task.ensure_main(time_out=180)
    verification = begin_account_visit(task, expected)
    from src.task.DailyTask import DailyTask
    daily = task.get_task_by_class(DailyTask)
    if daily is not None:
        # The common binding is also used by standalone material/weekly tasks.
        record = verification.record
        daily.bind_verified_profile(record.account['display_name'], expected_profile_id=record.profile_id,
                                    snapshot_profile={'profile_id': record.profile_id,
                                                      'account': record.account, 'tasks': record.tasks})


def begin_account_visit(task, expected):
    from src.account_repository import get_default_repository
    repository = get_default_repository()
    if repository is None:
        raise ConfigIntegrityBlocked('账号配置仓库不可用，不能核验真实账号')
    # Discard the previous visit before reading after an account switch.
    task.executor._account_feature_run = None
    try:
        verification = FeatureRun(task, repository, expected).begin()
    except RuntimeError as error:
        # Multi-account errors of this kind must stop the whole batch, rather
        # than be recorded as a farming failure and advance to another account.
        raise ConfigIntegrityBlocked(str(error)) from error
    task.executor._account_feature_run = verification
    return verification


def current_feature_run(task):
    verification = getattr(task.executor, '_account_feature_run', None)
    if verification is None:
        verification = begin_account_visit(task, expected_profile(task))
    verification.guard()
    return verification


class FeatureRun:
    def __init__(self, task, repository, expected=None):
        self.task, self.repository, self.expected = task, repository, expected
        self.run_id = str(uuid4())
        self.window = window_id(task)
        self.record = None
        self.start = self.end = None
        self.binding = None
        self.current = task.executor.current_task
        self.initial_bindings = {str(r.profile_id): str(r.account.get('game_feature_code') or '').strip()
                                 for r in repository.list_profiles()}
        self.profile_id = None

    def guard(self):
        self.task.executor.check_enabled()
        if window_id(self.task) != self.window or self.task.executor.current_task is not self.current:
            raise ConfigIntegrityBlocked('特征码核验上下文失效：窗口或任务变化')
        if getattr(self.current, '_active_account_switch_capture', None) is not None:
            raise ConfigIntegrityBlocked('特征码核验上下文失效：账号正在切换')
        if type(self.current).__name__ in ('MultiAccountDailyTask', 'MultiAccountWeeklyGardenTask') and getattr(self.current, '_current_profile_id', None) != self.expected:
            raise ConfigIntegrityBlocked('特征码核验上下文失效：期望账号变化')
        if not self.record:
            bindings = {str(r.profile_id): str(r.account.get('game_feature_code') or '').strip()
                        for r in self.repository.list_profiles()}
            if bindings != self.initial_bindings:
                raise ConfigIntegrityBlocked('读取期间绑定变化，请重新核验')
        if self.record:
            record = self.repository.load_profile(self.profile_id)
            if str(record.account.get('game_feature_code') or '').strip() != self.binding:
                raise ConfigIntegrityBlocked('特征码绑定已变化，本轮待核验')

    def observe(self):
        return observe(self.task.next_frame, lambda frame: read_code(self.task, frame),
                       self.guard, self.task.sleep)

    def begin(self):
        self.start = self.observe()
        status, record = resolve(self.start, self.repository.list_profiles(), self.expected)
        if status != 'verified':
            from src.account_display import account_display_label
            expected = next((r for r in self.repository.list_profiles() if str(r.profile_id) == str(self.expected)), None)
            message = STATUS_LABELS[status]
            if expected is not None:
                message += '｜期望' + account_display_label(expected.account)
            if record is not None:
                message += '｜实际' + account_display_label(record.account)
            self.task.info_set('账号核验', message)
            raise RuntimeError('任务开始前特征码核验未通过：' + message)
        self.record = record
        self.profile_id = str(record.profile_id)
        self.binding = self.start.code
        from src.account_display import account_display_label
        self.label = account_display_label(record.account)
        self.task.info_set('账号核验', f'当前账号{self.label}｜特征码已核验｜' +
                           ('与期望账号一致' if self.expected else '已匹配唯一绑定账号'))
        self.guard()
        return self

    def finish(self):
        self.end = self.observe()
        status, _ = resolve(self.end, self.repository.list_profiles(), self.profile_id)
        if status == 'verified' and self.end.code != self.binding:
            status = 'mismatch'
        self.end.status = status
        self.task.info_set('账号核验', f'当前账号{self.label}｜结束核验：' + STATUS_LABELS[status])
        return status

    def save(self, result, frame, status, reason):
        from config import version
        from src.evidence.service import get_evidence_service
        # Mask exactly the existing identity area in the persisted copy.
        if frame is None:
            raise RuntimeError('完成画面缺失，不能确认完成')
        safe = frame.copy()
        x, y, w, h = region(safe)
        safe[y:y+h, x:x+w] = 0
        metadata = dict(profile_id=self.profile_id, project_id='character_trial', source='automatic',
                        identity_source='feature_code', completion_status=status, reason=reason,
                        run_id=self.run_id, event_id=self.run_id, captured_at=now_iso(), version=version,
                        require_image=True, progress={key: value for key, value in result.items()
                                                     if key not in ('complete', 'evidence_id', 'evidence_pending')},
                        verification=dict(start=self.start.metadata(), end=self.end.metadata() if self.end else None))
        service = getattr(self.task.executor, 'completion_evidence_service', None) or get_evidence_service()
        saved = service.submit(metadata, safe).result(timeout=20)
        if saved.get('asset_status') != 'available':
            raise RuntimeError('图片未成功保存，不能确认完成')
        return saved
