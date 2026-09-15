"""Post-selection event flow: support equipment, combat and stage progression."""
import json
import re
import time
from pathlib import Path
from types import MethodType

import cv2

from src.char.CharFactory import char_dict, _apply_char_config, _get_buff_time
from src.char.BaseChar import CharType
from src.task.AutoAbyssTask import AutoAbyssTask, character_card_slots
from src.task.character_trial import compact
from src.task.echoes_remain import FINAL
from src.task.echoes_support import (SLOTS, KINDS, choose_support, support_point,
                                    equipped, enabled_start, selected_support, challenge_prompt_state)
from src.task.BaseCombatTask import CombatStateUnknown, NotInCombatException, CharDeadException
from src.char.character_names import character_display_name
from src.runtime.diagnostic_export import atomic_json
from src.runtime.diagnostic_storage import storage_path


class EventSettlement(Exception):
    pass


def activity_role(identity):
    if identity == 'char_chisa':
        return '辅助'
    info = char_dict.get(identity)
    if not info or 'char_type' not in info:
        raise RuntimeError(f'角色活动定位未登记：{identity}')
    return {CharType.MAIN_DPS: '输出', CharType.SUB_DPS: '辅助', CharType.HEALER: '治疗'}[info['char_type']]


def event_echo(char, duration=0, sleep_time=0, time_out=1):
    """Event supports replace native echoes; do not wait for native transformations."""
    if time.time() - char.last_echo < 1 or not char.echo_available():
        return False
    char.send_echo_key()
    char.record_echo_use()
    return True


class EchoesContinuation:
    _battle_deadline = None
    _next_result_check = 0

    def click(self, *args, **kwargs):
        self._guard()
        return super().click(*args, **kwargs)

    def send_key(self, *args, **kwargs):
        self._guard()
        return super().send_key(*args, **kwargs)

    def send_key_down(self, key, *args, **kwargs):
        self._guard()
        self._held_keys.add(key)
        return super().send_key_down(key, *args, **kwargs)

    def send_key_up(self, key):
        result = super().send_key_up(key)
        self._held_keys.discard(key)
        return result

    def mouse_down(self, *args, **kwargs):
        self._guard()
        self._held_mouse.add(kwargs.get('key', 'left'))
        return super().mouse_down(*args, **kwargs)

    def mouse_up(self, name=None, key='left'):
        result = super().mouse_up(name=name, key=key)
        self._held_mouse.discard(key)
        return result

    def _identify_team(self, frame):
        self._avatar_orb = cv2.ORB_create(nfeatures=300, edgeThreshold=5, fastThreshold=5)
        self._avatar_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._character_descriptors = None
        members = []
        for order, index in enumerate((3, 4, 5), 1):
            avatar = AutoAbyssTask._slot_crop(frame, character_card_slots()[index], (.02, .01, .98, .70))
            result = AutoAbyssTask._identify_character(self, avatar)
            if result is None:
                raise RuntimeError(f'第{order}位试用角色身份无法确认')
            identity, score = result
            info = char_dict[identity]
            name = character_display_name(info['cls'])
            members.append(dict(order=order, identity=getattr(identity, 'value', identity), name=self.tr(name),
                                role=activity_role(identity), confidence=score))
        if len({m['identity'] for m in members}) != 3:
            raise RuntimeError('三个试用角色身份重复，停止编队')
        self.last_result['members'] = members
        self.info_set('试用角色', '；'.join(f"{m['order']}.{m['name']}（{m['role']}）" for m in members))
        return members

    def _character_template_descriptors(self):
        return AutoAbyssTask._character_template_descriptors(self)

    def _verify_team_names(self, frame):
        if not self._formation_for_stage(frame, self.last_result['stage']):
            return False
        for index, member in enumerate(self.last_result['members']):
            x = (.28, .55, .85)[index]
            names = [compact(b.name) for b in self.ocr(x, .755, x+.10, .81, frame=frame)]
            if compact(member['name']) not in names:
                return False
        return True

    def _support_page(self, frame):
        return self._button(frame, (.02, .03, .25, .10), '选择支援声骸')

    def _support_selection_state(self, frame, index):
        # OCR can read simplified 控制型 as 控製型. Keep this alias local
        # to support categories; do not relax other page/button matching.
        texts = [compact(b.name) for b in self.ocr(.86, .10, .97, .18, frame=frame)]
        kinds = [{'控製型': '控制型'}.get(text, text) for text in texts]
        return dict(page=bool(self._support_page(frame)),
                    category=kinds.count(KINDS[index]) == 1,
                    selected=bool(selected_support(frame, index)),
                    expected=KINDS[index], observed=texts)

    def _equip_supports(self):
        self._wait(self._verify_team_names, '编队页姓名与选人复核不一致，未装配声骸')
        selected = []
        for slot, member in enumerate(self.last_result['members']):
            self.info_set('活动阶段', f"为第{slot+1}位{member['name']}装配{member['role']}声骸")
            frame = self.navigate_ui('打开支援声骸', self._verify_team_names, self._support_page,
                action=lambda _, slot=slot: self._click(*SLOTS[slot]), identity=(self.last_result['stage'], slot))
            index = choose_support(frame, member['role'])
            if index is None:
                raise RuntimeError(f"{member['name']}没有已确认解锁的{member['role']}声骸")
            self._click(*support_point(index))
            selection_state = {}
            def chosen(f):
                # Exact category and selected frame border must both agree.
                selection_state.update(self._support_selection_state(f, index))
                return all(selection_state[key] for key in ('page', 'category', 'selected'))
            try:
                self._wait(chosen, '声骸选中或类型未确认，未点击装配')
            except RuntimeError:
                self.log_warning(f'支援声骸复核失败 slot={slot+1} index={index} state={selection_state}')
                raise
            self.navigate_ui('装配支援声骸',
                lambda f: self._button(f, (.76, .86, .95, .96), '装配') if chosen(f) else None,
                lambda f: self._verify_team_names(f) and equipped(f, slot, index),
                identity=(self.last_result['stage'], slot, index))
            selected.append(index)
        frame = self._wait(lambda f: self._verify_team_names(f) and
            all(equipped(f, i, e) for i, e in enumerate(selected)) and enabled_start(f) and
            self._button(f, self.DONE, '开启挑战'), '三槽装配或开启挑战按钮未确认')
        self.last_result['supports'] = selected
        self._quick_capture('echoes_supports_verified', self.require_game_frame())

    def _settlement(self, frame):
        if not self._button(frame, (.27, .79, .46, .90), '退出副本'):
            return None
        if (self._button(frame, (.40, .45, .60, .55), '本次挑战失败')
                and self._button(frame, (.54, .79, .73, .90), '重新挑战')):
            return 'failed'
        for text, outcome in (('挑战成功', 'success'), ('挑战失败', 'failed')):
            if self._button(frame, (.32, .23, .68, .37), text):
                return outcome
        return None

    def _battle_observe(self, frame):
        if self._battle_deadline is None:
            return
        if time.monotonic() >= self._battle_deadline:
            raise CombatStateUnknown('活动战斗超过10分钟，停止本轮')
        if time.monotonic() < self._next_result_check:
            return
        self._next_result_check = time.monotonic() + .75
        outcome = self._settlement(frame)
        if outcome:
            self._event_outcome = outcome
            raise EventSettlement()

    def load_chars(self):
        # Identities were independently checked on the roster and formation page.
        self.load_hotkey()
        ready, current, count = self.in_team()
        if not ready or count != 3:
            return False
        self.chars = []
        for index, member in enumerate(self.last_result['members']):
            info = char_dict[member['identity']]
            char = info['cls'](self, index, char_name=info['canonical_name'],
                               confidence=member['confidence'], ring_index=info.get('ring_index', -1),
                               char_type=info['char_type'], buff_time=_get_buff_time(self, info))
            _apply_char_config(self, char, info)
            char.click_echo = MethodType(event_echo, char)
            char.is_current_char = index == current
            char.reset_state()
            self.chars.append(char)
        self.combat_start = time.time()
        return True

    def revive_action(self):
        # Event failure is not a farming death recovery; never teleport out.
        return False

    def _release_event_inputs(self):
        for key in tuple(getattr(self, '_held_keys', ())):
            try:
                self.executor.interaction.send_key_up(self.validate_key(key))
                self._held_keys.discard(key)
            except Exception as error:
                self.log_warning(f'活动释放按键失败：{error}')
        for key in tuple(getattr(self, '_held_mouse', ())):
            try:
                self.executor.interaction.mouse_up(key=key)
                self._held_mouse.discard(key)
            except Exception as error:
                self.log_warning(f'活动释放鼠标失败：{error}')

    def sleep_check(self):
        if self._battle_deadline is not None:
            self.next_frame()
        return super().sleep_check()

    def _recover_event_character(self):
        self._release_event_inputs()
        self.log_info('活动角色阵亡：尝试切换队友并等待自动复活')
        deadline = time.monotonic() + 25
        next_switch = 0
        slot = 0
        while time.monotonic() < deadline:
            frame = self.next_frame()  # Settlement observer interrupts immediately.
            if self._settlement(frame):
                return
            ready, current, count = self.in_team(frame=frame)
            if ready and count == 3:
                text = ''.join(compact(b.name) for b in self.ocr(.43, .94, .60, .98, frame=frame))
                hp = re.search(r'(\d+)/(\d+)', text)
                if hp and 0 < int(hp[1]) <= int(hp[2]):
                    self.chars = []
                    self.reset_to_false(reason='活动存活角色恢复后重新识别战斗状态')
                    self.log_info(f'活动存活/复活角色已确认 slot={current+1}，恢复战斗')
                    return
                if time.monotonic() >= next_switch:
                    self.send_key(str(slot + 1))
                    slot = (slot + 1) % 3
                    next_switch = time.monotonic() + 2
            self.sleep(.5)
        raise CombatStateUnknown('等待自动复活25秒后仍未确认存活角色或结算，停止本轮')

    def _fight_event(self):
        self._event_outcome = None
        self._next_result_check = 0
        self._battle_deadline = time.monotonic() + 600
        try:
            while True:
                self.skip_combat_check = False
                try:
                    self.combat_once(wait_combat_time=12, target=True)
                except CharDeadException:
                    self.skip_combat_check = True
                    self._recover_event_character()
                except (CombatStateUnknown, NotInCombatException):
                    # A wave gap is not completion; wait for enemies or settlement.
                    pass
                finally:
                    self.skip_combat_check = True
                    self._release_event_inputs()
                state = self._wait(lambda f: self._settlement(f) or self.in_combat(),
                                   '脱战后未确认结算或下一波', timeout=25)
                if state in ('success', 'failed'):
                    return state
        except EventSettlement:
            return self._event_outcome
        finally:
            self._battle_deadline = None
            self.skip_combat_check = True
            self._release_event_inputs()

    def _enter_event_map(self):
        def ready(frame):
            supports = self.last_result['supports']
            return (self._verify_team_names(frame) and enabled_start(frame) and
                    all(equipped(frame, i, e) for i, e in enumerate(supports)))
        self.navigate_ui('进入若梦战斗地图',
            lambda f: self._button(f, self.DONE, '开启挑战') if ready(f) else None,
            lambda f: self.in_team_and_world(frame=f) and not self._formation_page(f),
            attempts=1, timeout=120, identity=self.last_result['stage'])

    def _start_event_combat(self):
        started = False
        prompt_state = {}
        try:
            for _ in range(40):
                frame = self.next_frame()
                if self.in_combat():
                    return
                boxes = self.ocr(.60, .43, .86, .61, frame=frame)
                prompt_state = challenge_prompt_state(frame, boxes)
                if prompt_state['text'] and (prompt_state['key_ocr'] or prompt_state['key_template']):
                    self.send_key_up('w')
                    self.log_info(f'开启挑战提示已确认 state={prompt_state}')
                    self.send_key('f')
                    started = True
                    break
                if not self.in_team_and_world(frame=frame):
                    raise RuntimeError('开始挑战前失去地图队伍状态')
                self.send_key('w', down_time=.20)
                self.sleep(.15)
        finally:
            self.send_key_up('w')
        if not started:
            self.log_warning(f'开启挑战提示未确认 state={prompt_state}')
            raise RuntimeError('未找到F开启挑战提示，停止移动')

    def _challenge_event(self):
        limit = max(1, min(10, int(self.config.get('Event Max Attempts', 3))))
        self._enter_event_map()
        for attempt in range(1, limit + 1):
            self.info_set('活动阶段', f"{self.last_result['stage']}：第{attempt}/{limit}次尝试")
            self._start_event_combat()
            outcome = self._fight_event()
            self._wait(lambda f: self._settlement(f) == outcome, '结算页面不稳定')
            self._quick_capture(f'echoes_result_{outcome}_attempt_{attempt}', self.require_game_frame())
            self.last_result['outcome'] = outcome
            self.last_result['score'] = ' '.join(b.name for b in self.ocr(.40, .48, .60, .61))
            self.last_result.setdefault('attempts', []).append(dict(
                stage=self.last_result['stage'], attempt=attempt, outcome=outcome, at=time.time()))
            self._save_run_summary()
            if outcome == 'success' or attempt == limit:
                break
            self.navigate_ui('重新挑战若梦副本',
                lambda f: self._button(f, (.54, .79, .73, .90), '重新挑战')
                    if self._settlement(f) == 'failed' else None,
                lambda f: self._formation_for_stage(f, self.last_result['stage'])
                    or self.in_team_and_world(frame=f),
                attempts=1, timeout=120, identity=(self.last_result['stage'], attempt))
            frame = self.next_frame()
            if self._formation_for_stage(frame, self.last_result['stage']):
                self._equip_supports()
                self._enter_event_map()
            self.chars = []
            self.reset_to_false(reason='活动重新挑战，清理上一局战斗状态')
        self.navigate_ui('退出若梦副本',
            lambda f: self._button(f, (.27, .79, .46, .90), '退出副本') if self._settlement(f) == outcome else None,
            self._stage_page, timeout=120, identity=self.last_result['stage'])
        return outcome

    def _selected_stage_pending(self, frame, stage):
        difficulty = stage[-2:]
        labels = [b for b in self.ocr(.05, .12, .28, .85, frame=frame) if compact(b.name) == difficulty]
        if len(labels) != 1:
            # Only a lock message beside this selected stage is evidence of a lock.
            texts = self.ocr(.05, .10, .28, .86, frame=frame)
            title = stage[:-3]
            heads = [b for b in texts if compact(b.name) == title]
            if len(heads) == 1:
                y = heads[0].y / self.height
                nearby = ''.join(compact(b.name) for b in self.ocr(.05,y,.28,min(.95,y+.08),frame=frame))
                if '解锁' in nearby or '未开放' in nearby:
                    self.last_result['phase'] = 'waiting_unlock'
                    return False
            raise RuntimeError('当前难度的通关状态无法确认')
        top = labels[0].y / self.height
        text = ''.join(compact(b.name) for b in self.ocr(.05, top, .28, min(.95, top+.09), frame=frame))
        if '未通关' in text:
            return True
        if '最高分数' in text:
            score = re.search(r'最高分数[:：]?([0-9][0-9,，]*)', text)
            if score is None:
                raise RuntimeError('当前难度最高分数无法读取，不能判定已通关')
            return int(score.group(1).replace(',', '').replace('，', '')) == 0
        raise RuntimeError('当前难度未通关状态不明确')

    def _audit_completion(self):
        """Only all eight visible 2/2 records prove the entire activity complete."""
        roman = {name: index for index, name in enumerate(('I','II','III','IV','V','VI','VII','VIII'),1)}
        counts = {}
        previous, same = None, 0
        # Read-only scroll sweep; never click a stage or the rewards icon here.
        for direction in (1, -1):
            for _ in range(18):
                frame = self.next_frame()
                if not self._stage_page(frame):
                    raise RuntimeError('检查通关进度时离开了关卡页')
                boxes = self.ocr(.035,.10,.29,.85,frame=frame)
                for b in boxes:
                    key = compact(b.name)
                    if key not in roman:
                        continue
                    values = [v for v in boxes if re.fullmatch(r'[012]/2',compact(v.name))
                              and 0 <= (v.y-b.y)/self.height < .065 and v.x > b.x]
                    if len(values) == 1:
                        counts[roman[key]] = int(compact(values[0].name)[0])
                if len(counts)==8:
                    self.last_result['stage_counts'] = counts
                    self.last_result['activity_complete'] = all(v==2 for v in counts.values())
                    return
                signature=tuple((compact(b.name),round(b.y/self.height,2)) for b in boxes)
                same=same+1 if signature==previous else 0
                previous=signature
                if same>=2: break
                self._guard()
                self.scroll_relative(.20,.55,direction*3)
                self.sleep(.3)
            previous,same=None,0
        self.last_result['stage_counts'] = counts
        self.last_result['activity_complete'] = False

    def _progress_path(self):
        from uuid import UUID
        identity = str(UUID(self.last_result['profile_id']))
        return storage_path('logs', Path('logs')) / 'echoes_progress' / f'{identity}.json'

    def _record_stage_result(self):
        path = self._progress_path()
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        # Namespace prevents future activities reusing historical stage records.
        stages = data.setdefault('echoes_remain_202609', {})
        stages[self.last_result['stage']] = dict(outcome=self.last_result['outcome'],
            members=self.last_result['members'], supports=self.last_result['supports'],
            score=self.last_result['score'], proof=self.last_result.get('proof'), at=time.time())
        atomic_json(path, data)
        if self.last_result.get('proof'):
            atomic_json(Path(self.last_result['proof']).with_suffix('.json'), self.last_result)

    def _save_run_summary(self):
        from uuid import UUID
        path = self._progress_path().parent / 'runs' / f"{UUID(self.last_result['run_id'])}.json"
        atomic_json(path, self.last_result)

    def _continue_event(self):
        seen = set()
        rounds = []
        for _ in range(16):
            stage = self.last_result['stage']
            if stage in seen:
                raise RuntimeError('返回后仍选择同一关卡，停止重复挑战')
            seen.add(stage)
            frame = self._choose()
            members = self._identify_team(frame)
            if any(m['confidence'] < .6 for m in members):
                fresh, state = self._observe_roster()
                if not state['valid'] or state['numbers'] != FINAL:
                    raise RuntimeError('身份复读时选人状态变化')
                repeated = self._identify_team(fresh)
                if [m['identity'] for m in repeated] != [m['identity'] for m in members]:
                    raise RuntimeError('两次角色身份识别不一致')
                frame = fresh
            self._save_proof(frame)
            self._click_transition('完成编队', 'done',
                lambda f: self._button(f, self.DONE, '完成') if self._roster_page(f) else None,
                lambda f: self._formation_for_stage(f, stage))
            self._equip_supports()
            outcome = self._challenge_event()
            self._record_stage_result()
            rounds.append(dict(stage=stage, outcome=outcome))
            self.last_result['rounds'] = rounds
            if outcome == 'failed':
                self.last_result['phase'] = 'challenge_failed'
                return
            frame = self.next_frame()
            next_stage = self._stage_page(frame)
            if not next_stage:
                raise RuntimeError('退出后未确认自动选中的下一关')
            if not self._selected_stage_pending(frame, next_stage):
                if self.last_result.get('phase') != 'waiting_unlock':
                    self.last_result['phase'] = 'available_stages_finished'
                self._audit_completion()
                return
            if next_stage in seen:
                raise RuntimeError('成功后关卡未推进，停止重复挑战')
            self.last_result['stage'] = next_stage
            self._click_transition('单人挑战', 'single',
                lambda f: self._single_button(f, next_stage), lambda f: self._formation_for_stage(f, next_stage))
            self._open_quick()
        self.last_result['phase'] = 'round_limit_reached'
        self._audit_completion()
