"""Run each available Tiangong stage once, with feature-code-bound checkpoints."""
import time

from ok import TaskDisabledException
from src.combat.CombatCheck import CombatFlowInterrupt
from src.task.BaseCombatTask import BaseCombatTask, CombatStateUnknown, NotInCombatException, CharDeadException
from src.evidence.model import now_iso
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.character_trial import compact, exact_button, start_prompt
from src.task.tiangong_treasure import STAGES, Progress, hardest, stage_state, trial_numbers, zero_score


class TiangongResult(CombatFlowInterrupt):
    pass


class TiangongTreasureTask(WWOneTimeTask, BaseCombatTask):
    navigation_section = 'activities'
    TITLE = (.02, .035, .18, .095)
    CURRENT = (.65, .13, .85, .20)
    LEVEL = (.72, .82, .92, .875)
    START = (.66, .88, .96, .95)
    TRIAL = (.07, .10, .25, .145)
    CONFIRM = (.54, .80, .74, .90)
    RESULT = (.40, .25, .61, .34)
    INTERACT = (.60, .40, .89, .65)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '天工寻物'
        self.description = '从活动关卡页开始，使用三个试用角色挑战最高难度；每关每轮一次，按账号保存进度，最高款项达到80000后跳过。'
        self.group_name = '限时活动'
        self.supported_languages = ['zh_CN']
        self.support_schedule_task = False
        self.skip_combat_check = True
        self._verification = None
        self._fighting = False
        self._next_result_check = 0

    def _guard(self):
        self.executor.check_enabled()
        if self._verification is not None:
            self._verification.guard()

    def next_frame(self):
        self._guard()
        super().next_frame()
        frame = self.require_game_frame()
        if self._fighting and time.monotonic() >= self._next_result_check:
            self._next_result_check = time.monotonic() + .75
            if self._result(frame):
                raise TiangongResult()
        return frame

    def sleep_check(self):
        if self._fighting:
            self.next_frame()
        return super().sleep_check()

    def _button(self, frame, region, text):
        return exact_button(self.ocr(*region, frame=frame), text)

    def _page(self, frame):
        return bool(self._button(frame, self.TITLE, self.name))

    def _formation(self, frame):
        return bool(self._button(frame, self.TRIAL, '试用角色') and self._button(frame, self.START, '开始挑战'))

    def _result(self, frame):
        return bool(self._button(frame, self.RESULT, '挑战成功') and self._button(frame, self.CONFIRM, '确认挑战结果'))

    def _wait(self, probe, reason, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self.next_frame()
            value = probe(frame)
            if value:
                return value
            self.sleep(.2)
        raise RuntimeError(reason)

    def _click(self, x, y):
        self._guard()
        if abs(self.width/self.height - 16/9) > .02:
            raise RuntimeError('天工寻物需要16:9游戏画面')
        self.click_relative(x, y, after_sleep=.3)

    def _state(self, frame, index):
        y = .14 + index * .108
        boxes = self.ocr(.09, y, .29, y+.09, frame=frame)
        state = stage_state(boxes)
        if state is None and any(compact(b.name) == '最高款项:' for b in boxes) and zero_score(frame, index):
            return dict(status='pending', score=0)
        return state

    def _read(self, index):
        return self._wait(lambda f: self._state(f, index) if self._page(f) else None,
                          f'见习札记{STAGES[index]}最高款项或解锁状态无法读取')

    def _selected(self, frame, index):
        title = ''.join(compact(b.name) for b in self.ocr(*self.CURRENT, frame=frame))
        # Supplied stage-I screenshot is read as “见习札记！” by the actual engine.
        if title == '见习札记!':
            title = '见习札记I'
        return self._page(frame) and title == compact('见习札记' + STAGES[index])

    def _select(self, index):
        self._wait(self._page, '选关前无法确认天工寻物页面')
        self._click(.17, .185 + index*.108)
        self._wait(lambda f: self._selected(f, index), f'未切换到见习札记{STAGES[index]}')

    def _difficulty(self, index):
        frame = self.require_game_frame()
        if hardest(self.ocr(*self.LEVEL, frame=frame)):
            return
        if not self._selected(frame, index):
            raise RuntimeError('选择难度前关卡发生变化')
        # The opener is a position, independent of the currently selected text.
        self._click(.80, .785)
        self._wait(lambda f: any('困难' in compact(b.name) for b in self.ocr(.66, .51, .96, .74, frame=f)),
                   '最高难度选项未展开')
        self._click(.80, .697)
        self._wait(lambda f: hardest(self.ocr(*self.LEVEL, frame=f)), '最高难度未显示推荐等级90')

    def _choose_trials(self):
        self._wait(self._formation, '未进入试用角色编队页面')
        for index in range(3):
            frame = self.next_frame()
            if not self._formation(frame):
                raise RuntimeError('试用角色选择时编队页面丢失')
            if not trial_numbers(frame)[index]:
                self._click(.11 + index*.0837, .235)
                self._wait(lambda f: trial_numbers(f)[index] if self._formation(f) else None,
                           f'第{index+1}个试用角色未出现队伍数字')
        self._wait(lambda f: self._formation(f) and sorted(trial_numbers(f)) == [1, 2, 3],
                   '三个试用角色未全部加入队伍')

    def _enter(self, index):
        self._difficulty(index)
        self._wait(lambda f: self._button(f, self.START, '开始挑战') if self._selected(f, index)
                   and hardest(self.ocr(*self.LEVEL, frame=f)) else None, '最高难度开始按钮不可用')
        self._click(.80, .916)
        self._choose_trials()
        self._click(.87, .916)
        self._wait(lambda f: self.in_team_and_world(frame=f) and not self._formation(f),
                   '挑战地图加载失败', timeout=120)
        self._battle_roster_confirmed = False
        self.reset_to_false(reason='天工寻物新关卡地图')

    def _start(self):
        try:
            for _ in range(40):
                frame = self.next_frame()
                if start_prompt(self.ocr(*self.INTERACT, frame=frame), self.height):
                    self.send_key('f')
                    return
                if not self.in_team_and_world(frame=frame):
                    raise RuntimeError('寻找F开启挑战时地图状态丢失')
                self.send_key('w', down_time=.20)
                self.sleep(.15)
            raise RuntimeError('未找到F开启挑战，已停止前进')
        finally:
            self._release_combat_inputs()

    def revive_action(self):
        # Do not use farming teleport recovery inside a limited event map.
        return False

    def _fight(self):
        self._fighting = True
        self._next_result_check = 0
        self.skip_combat_check = False
        try:
            while True:
                try:
                    self.combat_once(wait_combat_time=12, target=True)
                except CharDeadException:
                    raise
                except (CombatStateUnknown, NotInCombatException):
                    # A gap between waves is not completion: wait for an observed state.
                    self._release_combat_inputs()
                state = self._wait(lambda f: 'result' if self._result(f) else 'combat' if self.in_combat() else None,
                                   '脱战后未确认结算或下一波', timeout=25)
                if state == 'result':
                    return
        except TiangongResult:
            self._battle_roster_confirmed = False
            self.reset_to_false(reason='天工寻物结算')
            return
        finally:
            self._fighting = False
            self.skip_combat_check = True
            self._release_combat_inputs()

    def _checkpoint(self, index, state):
        if self._verification.finish() != 'verified':
            raise RuntimeError('关卡进度保存前账号特征码核验未通过')
        self._progress.update(index, state)

    def _evidence(self, status, reason):
        from src.task.account_feature_verification import region
        frame = self.require_game_frame().copy()
        x, y, w, h = region(frame)
        frame[y:y+h, x:x+w] = 0
        return self._service.submit(dict(profile_id=self._verification.profile_id,
            project_id='tiangong_treasure', source='automatic', identity_source='feature_code',
            completion_status=status, reason=reason, captured_at=now_iso(),
            run_id=self._verification.run_id, event_id=self._verification.run_id,
            require_image=True, progress=dict(stages=self._progress.stages)), frame).result(timeout=20)

    def run(self):
        super().run()
        try:
            from src.task.account_feature_verification import current_feature_run
            from src.evidence.service import get_evidence_service
            from src.evidence.cycles import cycle_for
            self._verification = current_feature_run(self)
            self._service = getattr(self.executor, 'completion_evidence_service', None) or get_evidence_service()
            cycle = cycle_for('tiangong_treasure', cycles=self._service.repository.cycles())
            if cycle is None:
                raise RuntimeError('天工寻物本期有效期未确认或已经结束')
            self._progress = Progress(self._verification.profile_id, cycle['end_at'])
            self._wait(self._page, '请先打开天工寻物关卡页面')
            for index in range(6):
                self.info_set('活动阶段', f'检查见习札记{STAGES[index]}（{index+1}/6）')
                state = self._read(index)
                self._checkpoint(index, state)
                if state['status'] != 'pending':
                    continue
                self._select(index)
                self._enter(index)
                self._start()
                self.info_set('活动阶段', f'见习札记{STAGES[index]}自动战斗')
                self._fight()
                self._wait(self._result, '未确认挑战结算界面')
                try:
                    self.screenshot(f'tiangong_stage_{index+1}_result')
                except TaskDisabledException:
                    raise
                except Exception as error:
                    self.log_warning(f'结算截图未保存，继续确认结果和保存账号进度：{error}')
                self._click(.63, .855)
                self._wait(self._page, '确认挑战结果后未返回关卡页', timeout=120)
                state = self._read(index)
                state['challenged_at'] = now_iso()
                self._checkpoint(index, state)
            # Final game scores, rather than local attempted flags, determine completion.
            for index in range(6):
                state = self._read(index)
                previous = self._progress.stages[str(index+1)]
                self._checkpoint(index, {**previous, **state})
            complete = all(s['status'] == 'completed' for s in self._progress.stages.values())
            self._evidence('completed' if complete else 'partial',
                           '六关最高款项均达到80000' if complete else '本轮已结束；未达标或未解锁关卡下次继续')
            self.info_set('活动阶段', '六关全部达标，存档已保存' if complete else '本轮结束，账号进度已保存，下次继续未达标关卡')
        except TaskDisabledException:
            raise
        except Exception:
            try:
                self.screenshot('tiangong_treasure_failed')
            except Exception as error:
                self.log_warning(f'天工寻物故障截图不可用：{error}')
            raise
        finally:
            self._fighting = False
            self.skip_combat_check = True
            self._release_combat_inputs()
            self._verification = None
