"""Clear available event difficulties with verified trial characters and supports."""
import time
from pathlib import Path
from uuid import uuid4

from ok import TaskDisabledException
from src.activity_catalog import ACTIVITIES
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.character_trial import compact, exact_button
from src.task.echoes_remain import INITIAL, FINAL, inspect_roster, correction
from src.task.BaseCombatTask import BaseCombatTask
from src.task.echoes_continuation import EchoesContinuation


class EchoesRemainTask(EchoesContinuation, WWOneTimeTask, BaseCombatTask):
    navigation_section = 'activities'
    activity_category = '限时活动'
    LIST = (.08, .14, .23, .83)
    TITLE = (.75, .10, .99, .20)
    ENTER = (.76, .87, .99, .96)
    STAGE = (.63, .10, .98, .17)
    SINGLE = (.81, .87, .98, .96)
    QUICK = (.61, .87, .77, .96)
    DONE = (.76, .87, .95, .96)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = ACTIVITIES['echoes_remain']
        self.description = '复核试用角色并按定位装配支援声骸，依次通关浅梦和深梦；失败退出后停止，不领取奖励。'
        self.group_name = '限时活动'
        self.supported_languages = ['zh_CN']
        self.support_schedule_task = False
        self.skip_combat_check = True
        self._verification = None
        self.last_result = None
        self._battle_deadline = None
        self._held_keys = set()
        self._held_mouse = set()

    def _guard(self):
        self.executor.check_enabled()
        if self._verification is not None:
            self._verification.guard()

    def next_frame(self):
        self._guard()
        super().next_frame()
        frame = self.require_game_frame()
        self._battle_observe(frame)
        return frame

    def _button(self, frame, region, text):
        return exact_button(self.ocr(*region, frame=frame), text)

    def _wait(self, probe, reason, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self.next_frame()
            value = probe(frame)
            if value:
                return value
            self.sleep(.35)
        raise RuntimeError(reason)

    def _click(self, x, y):
        self._guard()
        if abs(self.width/self.height - 16/9) > .02:
            raise RuntimeError('本阶段需要16:9游戏画面')
        self.click_relative(x, y, after_sleep=.3)

    def _roster_page(self, frame):
        return bool(self._button(frame, (.053, .04, .14, .09), '详情') and self._button(frame, self.DONE, '完成'))

    def _formation_page(self, frame):
        return self._button(frame, self.QUICK, '快速编队')

    def _quick_capture(self, name, frame):
        try:
            safe = frame.copy()
            safe[:round(len(safe)*.025)] = 0
            safe[round(len(safe)*.975):] = 0
            self.screenshot(name, frame=safe)
        except TaskDisabledException:
            raise
        except Exception as error:
            self.log_warning(f'活动导航诊断截图失败：{type(error).__name__}')

    def _click_transition(self, label, key, source, target):
        self.info_set('活动阶段', f'等待页面稳定并点击{label}')
        entries = self.last_result.setdefault(f'{key}_entry_attempts', [])

        def capture_result(frame, result, save=True):
            if entries and 'result' not in entries[-1]:
                entry = entries[-1]
                entry['result'] = result
                entry['elapsed'] = round(time.monotonic()-entry.pop('_started'), 3)
                if save:
                    self._quick_capture(f'echoes_{key}_{entry["attempt"]}_after_{result}', frame)

        def click(button):
            frame = self.require_game_frame()
            capture_result(frame, 'still_formation' if key == 'quick' else 'still_source')
            x, y = button.center()
            h, w = frame.shape[:2]
            point = (x/w, y/h)
            attempt = len(entries)+1
            self._quick_capture(f'echoes_{key}_{attempt}_before', frame)
            entries.append(dict(attempt=attempt, at=time.time(), point=point, _started=time.monotonic()))
            self.log_info(f'{label}点击 attempt={attempt} normalized={point}')
            self._click(*point)

        def status(operation, state, machine, frame):
            if state in ('已到达目标', '停止/失败'):
                capture_result(frame, 'entered' if state == '已到达目标' else 'unconfirmed',
                               save=state == '已到达目标')

        return self.navigate_ui(label, source, target, action=click,
                                identity=self.last_result.get('stage'), on_status=status)

    def _open_quick(self):
        return self._click_transition('快速编队', 'quick', self._formation_page, self._roster_page)

    def _stage_name(self, frame):
        names = [compact(b.name).replace('・', '·') for b in self.ocr(*self.STAGE, frame=frame)]
        matches = [n for n in names if n.endswith(('浅梦', '深梦')) and len(n) > 2]
        return matches[0] if len(matches) == 1 else None

    def _event_page(self, frame):
        return bool(self._button(frame, self.TITLE, self.name) and self._button(frame, self.ENTER, '前往'))

    def _stage_page(self, frame):
        return (self._stage_name(frame) if self._button(frame, (.02, .03, .24, .10), self.name)
                and self._button(frame, self.SINGLE, '单人挑战') else None)

    def _single_button(self, frame, expected):
        name = self._stage_page(frame)
        if name and name != expected:
            raise RuntimeError('单人挑战前关卡已变化，停止点击')
        return self._button(frame, self.SINGLE, '单人挑战') if name == expected else None

    def _formation_for_stage(self, frame, expected):
        if self._formation_page(frame) is None:
            return False
        names = [compact(b.name).replace('・', '·') for b in self.ocr(.09, .085, .50, .16, frame=frame)]
        stages = [n for n in names if n.endswith(('浅梦', '深梦')) and len(n) > 2]
        if len(stages) == 1 and stages[0] != expected:
            raise RuntimeError('编队页关卡与进入前不一致，停止操作')
        return stages == [expected]

    def _open_event(self):
        frame = self.next_frame()
        if self._event_page(frame):
            return
        if not self._button(frame, (.02, .03, .19, .11), '推荐活动'):
            self.ensure_main(time_out=60)
            self._guard()
            self.send_key('f1')
            self._wait(lambda f: self._button(f, (.02, .03, .19, .11), '推荐活动'), '无法打开推荐活动')
        for direction in (1, -1):
            previous, unchanged = None, 0
            for _ in range(16):
                frame = self.next_frame()
                boxes = self.ocr(*self.LIST, frame=frame)
                target = exact_button(boxes, self.name)
                if target is not None:
                    for _ in range(3):
                        self._guard()
                        self.click(target, after_sleep=.3)
                        try:
                            self._wait(self._event_page, '活动详情未切换', timeout=3)
                            return
                        except RuntimeError as error:
                            if str(error) != '活动详情未切换':
                                raise
                            frame = self.next_frame()
                            target = self._button(frame, self.LIST, self.name)
                            if target is None:
                                raise RuntimeError('活动入口状态变化，停止重试')
                    raise RuntimeError('活动详情未切换')
                signature = tuple(compact(b.name) for b in boxes)
                unchanged = unchanged+1 if signature and signature == previous else 0
                if unchanged >= 3:
                    break
                previous = signature
                self._guard()
                self.scroll_relative(.15, .50, direction)
                self.sleep(.35)
        raise RuntimeError('活动列表中未找到若梦仍有回声')

    def _navigate(self):
        self.info_set('活动阶段', '进入当前关卡')
        frame = self.next_frame()
        # Resume only pages whose stage context is known. A bare roster is ambiguous.
        name = self._stage_page(frame)
        if not name:
            self._open_event()
            frame = self._click_transition('前往', 'event_enter',
                lambda f: self._button(f, self.ENTER, '前往') if self._event_page(f) else None,
                self._stage_page)
            name = self._stage_page(frame)
        self.last_result['stage'] = name
        if not self._selected_stage_pending(frame, name):
            if self.last_result.get('phase') != 'waiting_unlock':
                self.last_result['phase'] = 'available_stages_finished'
            self._audit_completion()
            return False
        self._click_transition('单人挑战', 'single',
            lambda f: self._single_button(f, name), lambda f: self._formation_for_stage(f, name))
        self._open_quick()

    def _observe_roster(self):
        frame = self.next_frame()
        if not self._roster_page(frame):
            raise RuntimeError('角色列表页面已变化，停止输入')
        return frame, inspect_roster(frame)

    def _choose(self):
        self.info_set('活动阶段', '检查前三人和试用时钟')
        before, state = self._observe_roster()
        if not state['valid'] or state['numbers'] not in (INITIAL, FINAL):
            self.sleep(.35)
            before, state = self._observe_roster()
        if not state['valid'] or state['numbers'] not in (INITIAL, FINAL):
            raise RuntimeError('初始编队、试用时钟或顶部位置不符，未执行换人')
        if state['numbers'] == INITIAL:
            self.info_set('活动阶段', '按位置换上试用角色')
            for index in range(6):
                self._click(.131 + .1221*index, .24)
        self.info_set('活动阶段', '复核试用角色和123顺序')
        frame, state = self._observe_roster()
        if not state['valid'] or state['numbers'] != FINAL:
            self.sleep(.35)
            frame, state = self._observe_roster()
        missing = correction(state['numbers']) if state['valid'] else None
        if missing is not None:
            self._click(.131 + .1221*missing, .24)
            frame, state = self._observe_roster()
        if not state['valid'] or state['numbers'] != FINAL:
            self.screenshot('echoes_remain_before_failed_selection', frame=before)
            raise RuntimeError('试用编队复核失败，未点击完成')
        self.last_result['formation'] = state
        return frame

    def _save_proof(self, frame):
        import cv2
        from PIL import Image
        from ok.gui.debug.Screenshot import Screenshot
        from src.runtime.diagnostic_storage import storage_path
        from src.runtime.diagnostic_export import atomic_json
        from src.evidence.model import now_iso
        self.last_result['captured_at'] = now_iso()
        folder = storage_path('screenshots', Path('screenshots')) / 'echoes_remain'
        folder.mkdir(parents=True, exist_ok=True)
        safe = frame.copy()
        safe[:round(len(safe)*.025)] = 0
        safe[round(len(safe)*.975):] = 0
        path = Screenshot.save_pil_image('formation_'+uuid4().hex, str(folder), Image.fromarray(cv2.cvtColor(safe, cv2.COLOR_BGR2RGB)))
        atomic_json(Path(path).with_suffix('.json'), self.last_result)
        self.last_result['proof'] = path

    def run(self):
        self._verification = None
        self.last_result = {'activity': 'echoes_remain', 'phase': 'preparing', 'activity_complete': False}
        super().run()
        try:
            from src.account_repository import get_default_repository
            from src.task.account_feature_verification import FeatureRun, expected_profile
            repository = get_default_repository()
            if repository is None:
                raise RuntimeError('账号配置仓库不可用')
            self._verification = FeatureRun(self, repository, expected_profile(self)).begin()
            self.last_result['profile_id'] = self._verification.profile_id
            self.last_result['run_id'] = self._verification.run_id
            if self._navigate() is not False:
                self._continue_event()
            # The activity page hides the feature code; verify back in the world.
            self.ensure_main(time_out=60)
            if self._verification.finish() != 'verified':
                raise RuntimeError('活动结束账号核验未通过')
            self._save_run_summary()
            self.log_info(str(self.last_result))
            status = {'challenge_failed': '挑战失败，已退出副本，本轮停止',
                      'waiting_unlock': '下一关尚未解锁，本轮结束',
                      'available_stages_finished': '当前选择已通关，本轮结束',
                      'round_limit_reached': '已达到本轮关卡上限'}
            message = ('所有关卡均已通关' if self.last_result['activity_complete'] else
                       status.get(self.last_result['phase'], '本轮结束'))
            self.info_set('活动阶段', message + '；未领取奖励')
        except TaskDisabledException:
            raise
        except Exception as failure:
            self.last_result['phase'] = 'failed'
            self.last_result['error'] = str(failure)
            try:
                self.screenshot('echoes_remain_failed')
                if self.last_result.get('profile_id') and self.last_result.get('run_id'):
                    self._save_run_summary()
            except Exception as error:
                self.log_warning(f'活动故障截图不可用：{error}')
            raise
        finally:
            self._battle_deadline = None
            self._release_event_inputs()
            self._verification = None
