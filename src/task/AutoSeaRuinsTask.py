"""Preset-only, evidence-checked Respawning Waters (7–11) automation."""
import re
import time
import cv2
import numpy as np
import win32api
import win32con
import win32gui

from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.BaseCombatTask import BaseCombatTask, CombatStateUnknown, NotInCombatException, CharDeadException
from src.task.AutoAbyssTask import AutoAbyssTask, exact_ocr_box, match_travel_button, char_names, char_dict
from src.task.sea_ruins import Preset, Token, choose_loadout, compact, parse_count, season_rule, scores_valid
from src.task import sea_ruins_vision as vision


class SeaPhaseEnded(Exception):
    pass


class AutoSeaRuinsTask(WWOneTimeTask, BaseCombatTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '自动冥歌海墟'
        self.description = '使用完整预设编队，按周期属性与可用信物自动挑战再生海域7至11层；不含无尽、凹分和领奖。'
        self.supported_languages = ['zh_CN']
        self.support_schedule_task = False
        self.default_config = {}
        self.skip_combat_check = True
        self._avatar_orb = cv2.ORB_create(nfeatures=300, edgeThreshold=5, fastThreshold=5)
        self._avatar_matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._character_descriptors = None
        self._observing_half = None
        self._next_observation = 0.
        self._phase_seen = 0
        self._deadline = None

    # Reuse the proven F2 template and avatar descriptor implementation only.
    def _character_template_descriptors(self):
        if self._character_descriptors is None:
            self._character_descriptors = []
            for name in char_names:
                feature = self.get_feature_by_name(name)
                if feature is None or feature.mat is None:
                    continue
                im = feature.mat
                scale = 76 / max(1, im.shape[0])
                _, descriptor = self._avatar_orb.detectAndCompute(
                    cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC), None)
                if descriptor is not None:
                    self._character_descriptors.append((char_dict[name]['canonical_name'], descriptor))
        return self._character_descriptors
    def _identify_character(self, avatar):
        scale = 180 / max(1, avatar.shape[0])
        return AutoAbyssTask._identify_character(self, cv2.resize(avatar, None, fx=scale, fy=scale))
    _find_period_challenge_icon = AutoAbyssTask._find_period_challenge_icon
    _click_period_challenge_icon = AutoAbyssTask._click_period_challenge_icon
    _open_period_challenge = AutoAbyssTask._open_period_challenge

    def _template(self, name):
        return AutoAbyssTask._template(name)

    def _status(self, message):
        self.info_set('海墟阶段', message)
        self.log_info(message)

    def _button(self, frame, region, text):
        return exact_ocr_box(self.ocr(*region, frame=frame), text)

    def _wait(self, probe, message, timeout=15, stable=2):
        end, count, previous = time.monotonic()+timeout, 0, None
        while time.monotonic() < end:
            self.executor.check_enabled()
            self.next_frame()
            value = probe(self.frame)
            signature = repr(value) if isinstance(value, (str, int, tuple)) else bool(value)
            count = count+1 if value and signature == previous else int(bool(value))
            previous = signature
            if value and count >= stable:
                return value
            self.sleep(.2)
        self.screenshot('sea_ruins_timeout')
        raise RuntimeError(message)

    def _release(self):
        # Release even when the executor was cancelled during a held key.
        for key in ('w', 'a', 's', 'd'):
            self.executor.interaction.send_key_up(self.validate_key(key))
        for key in ('left', 'right', 'middle'):
            self.executor.interaction.mouse_up(key=key)

    def next_frame(self):
        super().next_frame()
        if self._observing_half is not None:
            now = time.monotonic()
            if now > self._deadline:
                raise CombatStateUnknown('海墟单半场超过10分钟')
            if now >= self._next_observation:
                self._next_observation = now+.65
                ended = self._upper_end(self.frame) if self._observing_half == 0 else self._result(self.frame)
                self._phase_seen = self._phase_seen+1 if ended else 0
                if self._phase_seen >= 2:
                    raise SeaPhaseEnded()
        return self.frame

    def _detail(self, frame, floor=None):
        if not self._button(frame, (.025, .035, .15, .095), '海墟详情'):
            return False
        if floor is None:
            return True
        return str(floor) in self._small_text(frame, (.157, .12, .186, .168))

    def _small_text(self, frame, region):
        im = vision.crop(frame, region)
        im = cv2.resize(im, None, fx=4, fy=4)
        im = cv2.copyMakeBorder(im, 24, 24, 24, 24, cv2.BORDER_CONSTANT)
        return [compact(b.name) for b in self.ocr(0, 0, 1, 1, frame=im)]

    def _map(self, frame):
        return bool(self._button(frame, (.07, .58, .20, .67), '信物一览')
                    and self._button(frame, (.07, .70, .20, .77), '无尽记录'))

    def _seven_boat(self, frame):
        # Full-map OCR drops the stylized 7, even in the original fixture.
        # Anchor on the name, then match only the white digit above it.
        frame = cv2.resize(frame, (1280, 720))
        name = self._button(frame, (.15, .18, .83, .89), '险滩')
        if name is None:
            return None
        x, y = max(0, name.x-16), max(0, name.y-70)
        region = frame[y:name.y-5, x:min(1280, name.x+name.width+16)]
        if region.size == 0:
            return None
        def white(im):
            lo, hi = im.min(axis=2), im.max(axis=2)
            return ((lo > 190) & (hi-lo < 45)).astype(np.uint8)*255
        template = vision.reference('seven')
        if template is None or region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
            return None
        _, score, _, location = cv2.minMaxLoc(cv2.matchTemplate(white(region), white(template), cv2.TM_CCOEFF_NORMED))
        if score < .8:
            return None
        return ((x+location[0]+template.shape[1]/2)/1280+.12,
                (y+location[1]+template.shape[0]/2)/720+.02)

    def _open(self):
        self.openF2Book()
        self._open_period_challenge()
        card = self._wait(lambda f: self._button(f, (.02, .10, .35, .85), '冥歌海墟'), '未找到冥歌海墟入口')
        self.click_box(card)
        # Filter by exact 前往, not an arbitrary box to the right of the title.
        def source(frame):
            title = self._button(frame, (.20, .18, .65, .50), '再生海域')
            buttons = [b for b in self.ocr(.65, .18, .99, .55, frame=frame) if compact(b.name) == '前往']
            return match_travel_button(title, buttons, self.height*.14) if title else None
        self.navigate_ui('进入再生海域', source, self._map, timeout=120, attempts=1, identity='sea_ruins')
        boat = self._wait(lambda f: self._seven_boat(f) if self._map(f) else None,
                          '无法定位7/险滩船体，已停止，未翻动地图')
        self.click_relative(*boat)
        self._wait(lambda f: self._detail(f, 7), '船体点击后未确认7层')

    def _open_presets(self, half):
        self._wait(lambda f: self._detail(f, self._floor), '不是当前海墟详情页')
        self.click_relative(.645, (.39, .71)[half], after_sleep=.3)
        button = self._wait(lambda f: self._button(f, (.15, .11, .28, .17), '预设编队'), '未找到预设编队页签')
        self.click_box(button)
        self.scroll_relative(.20, .50, 30)
        self.sleep(.4)

    def _page_presets(self, frame):
        records = []
        for top in vision.preset_card_tops(frame):
            numbers = self._small_text(frame, (.042, top, .059, top+.029))
            if len(numbers) != 1 or not numbers[0].isdigit():
                continue
            number = int(numbers[0])
            top += .032
            members = []
            for portrait in vision.preset_portraits(frame, top):
                found = self._identify_character(portrait)
                members.append(found[0] if found else '')
            records.append((Preset(number, tuple(members)), top))
        return records

    def _scan_presets(self):
        self._open_presets(0)
        collected, previous, repeats = {}, None, 0
        for _ in range(32):
            self.next_frame()
            frame = self.frame
            records = self._page_presets(frame)
            for preset, _ in records:
                if preset.valid:
                    old = collected.get(preset.number)
                    if old and old.members != preset.members:
                        raise RuntimeError(f'预设{preset.number}跨页识别不一致')
                    collected[preset.number] = preset
                else:
                    self.log_warning(f'跳过空位或未知机制预设{preset.number}: {preset.members}')
            image = cv2.resize(vision.crop(frame, (.035, .18, .275, .85)), (80, 120))
            repeats = repeats+1 if previous is not None and np.mean(cv2.absdiff(previous, image)) < 1.5 else 0
            if repeats >= 2:
                break
            previous = image
            self.scroll_relative(.20, .50, -2)
            self.sleep(.35)
        else:
            raise RuntimeError('预设列表扫描超过32屏，未确认到底')
        if len(collected) < 2:
            raise RuntimeError('未识别到至少两支可用完整预设')
        self._status(f'已识别预设：{[(p.number, p.members) for p in collected.values()]}')
        self._close_presets()
        return list(collected.values())

    def _close_presets(self):
        # Preset sidebar hides the large floor digit. Do not treat its shared
        # 海墟详情 header as proof that we returned to the normal detail page.
        self.next_frame()
        if not self._detail(self.frame, self._floor):
            self.send_key('esc')
        self._wait(lambda f: self._detail(f, self._floor), '预设侧栏关闭后层号未确认')

    def _members_match(self, frame, half, preset):
        members = [self._identify_character(im) for im in vision.team_portraits(frame, half)]
        return all(hit and hit[0] == identity for hit, identity in zip(members, preset.members))

    def _apply_preset(self, half, preset):
        self._open_presets(half)
        for _ in range(32):
            self.next_frame()
            rows = self._page_presets(self.frame)
            for candidate, top in rows:
                if candidate.number == preset.number:
                    if candidate.members != preset.members:
                        raise RuntimeError('预设回位后成员变化，未点击')
                    self.click_relative(.16, top+.065)
                    self._wait(lambda f: self._members_match(f, half, preset), '预设应用后头像顺序未确认')
                    self._close_presets()
                    return
            self.scroll_relative(.20, .50, -2)
            self.sleep(.3)
        raise RuntimeError(f'未找回预设{preset.number}')

    def _token_page(self, frame):
        return bool(self._button(frame, (.015, .025, .20, .10), '信物一览')
                    and self._button(frame, (.68, .88, .97, .95), '携带'))

    def _open_tokens(self, half):
        self._wait(lambda f: self._detail(f, self._floor), '信物入口不在详情页')
        self.click_relative(.853, (.39, .71)[half], after_sleep=.3)
        self._wait(self._token_page, '未进入信物携带页')
        self.scroll_relative(.40, .50, 30)
        self.sleep(.4)

    def _read_token(self, rect):
        x, y, w, h = rect
        self.click_relative((x+w/2)/2048, (y+h/2)/1152, after_sleep=.25)
        def title(frame):
            return ''.join(b.name for b in self.ocr(.69, .125, .965, .185, frame=frame))
        name = self._wait(title, '信物详细名称未稳定', timeout=5)
        frame = self.frame
        # Description area excludes the flavour text below the divider.
        description = ''.join(b.name for b in self.ocr(.69, .40, .963, .565, frame=frame))
        count = self._token_count(frame, rect)
        return Token(compact(name), description, count, vision.token_locked(frame, rect))

    def _token_count(self, frame, rect):
        x, y, w, h = rect
        roi = vision.normalized(frame)[y+round(h*.55):y+round(h*.79), x+round(w*.70):x+w]
        if cv2.matchTemplate(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY),
                             cv2.cvtColor(vision.reference('infinity'), cv2.COLOR_BGR2GRAY),
                             cv2.TM_CCOEFF_NORMED).max() >= .80:
            return -1
        texts = self._small_text(frame, ((x+w*.72)/2048, (y+h*.55)/1152,
                                        (x+w)/2048, (y+h*.79)/1152))
        values = [parse_count(s) for s in texts if parse_count(s) is not None]
        return values[0] if len(values) == 1 else None

    def _scan_tokens(self):
        self._open_tokens(0)
        tokens, previous, repeats = {}, None, 0
        for _ in range(24):
            self.next_frame()
            for rect in vision.token_cards(self.frame):
                if vision.token_locked(self.frame, rect):
                    continue
                token = self._read_token(rect)
                if token:
                    tokens[token.name] = token
            self.next_frame()
            image = cv2.resize(vision.crop(self.frame, (.04, .17, .63, .86)), (120, 100))
            repeats = repeats+1 if previous is not None and np.mean(cv2.absdiff(previous, image)) < 2 else 0
            if repeats >= 2:
                break
            previous = image
            self.scroll_relative(.40, .50, -2)
            self.sleep(.35)
        else:
            raise RuntimeError('信物列表扫描超过24屏，未确认到底')
        self.send_key('esc')
        self._wait(lambda f: self._detail(f, self._floor), '信物扫描后未返回详情')
        self.log_info(f'信物扫描：{[(t.name, t.remaining, t.locked) for t in tokens.values()]}')
        return list(tokens.values())

    def _equip_token(self, half, target):
        self._open_tokens(half)
        for _ in range(24):
            self.next_frame()
            for rect in vision.token_cards(self.frame):
                if vision.token_locked(self.frame, rect):
                    continue
                token = self._read_token(rect)
                if token and token.name == target.name:
                    if not token.available:
                        raise RuntimeError(f'{target.name}已不可携带')
                    art = vision.token_art(self.frame, rect)
                    button = self._button(self.frame, (.68, .88, .97, .95), '携带')
                    if not button:
                        raise RuntimeError('携带按钮未确认')
                    self.click_box(button)
                    self._wait(lambda f: self._detail(f, self._floor), '携带后未返回详情')
                    # Full artwork differs in aspect ratio, so use local feature matching.
                    def equipped(frame):
                        y = (.34, .66)[half]
                        slot = vision.crop(frame, (.827, y, .88, y+.096))
                        return self._same_art(art, slot)
                    self._wait(equipped, f'{target.name}携带后槽图标未确认')
                    return
            self.scroll_relative(.40, .50, -2)
            self.sleep(.3)
        raise RuntimeError(f'未找回信物：{target.name}')

    def _same_art(self, a, b):
        # ORB tolerates card/slot rescaling and ignores the selection border.
        a, b = [cv2.resize(im, (180, 180)) for im in (a, b)]
        _, da = self._avatar_orb.detectAndCompute(a, None)
        _, db = self._avatar_orb.detectAndCompute(b, None)
        if da is None or db is None:
            return False
        return sum(len(p) == 2 and p[0].distance < .75*p[1].distance
                   for p in self._avatar_matcher.knnMatch(da, db, k=2)) >= 5

    def _prompt(self, frame, text):
        return vision.interaction_prompt(frame, self.ocr(.60, .40, .88, .62, frame=frame), text)

    def _upper_end(self, frame):
        boxes = self.ocr(.005, .23, .25, .32, frame=frame)
        text = ''.join(compact(b.name) for b in boxes)
        return '前往下半海域' in text and re.search(r'上半得分[:：]?[0-9]+', text) is not None

    def _result(self, frame):
        return bool(self._button(frame, (.40, .28, .59, .34), '挑战结束')
                    and self._button(frame, (.28, .84, .44, .91), '返回海墟'))

    def _start_combat(self):
        self._wait(lambda f: self.in_team_and_world(frame=f), '地图加载未完成', timeout=120)
        try:
            for _ in range(45):
                self.next_frame()
                if self.in_combat():
                    return
                if any(self._prompt(self.frame, t) for t in ('开启挑战', '开始挑战')):
                    self.send_key_up('w')
                    self.send_key('f')
                    self._wait(lambda f: self.in_combat(), '按F后未确认挑战启动', timeout=25)
                    return
                if not self.in_team_and_world(frame=self.frame):
                    raise RuntimeError('寻找开启挑战时失去地图状态')
                self.send_key('w', down_time=.20)
                self.sleep(.15)
            raise RuntimeError('未找到F开启挑战，停止前进')
        finally:
            self._release()

    def on_combat_check(self):
        return True  # never auto-press arbitrary F during combat

    def revive_action(self):
        return False

    def _fight(self, half):
        self._status(f'第{self._floor}层{"上" if half == 0 else "下"}半自动战斗')
        self._observing_half = half
        self._phase_seen = 0
        self._next_observation = 0
        self._deadline = time.monotonic()+600
        try:
            while True:
                self.skip_combat_check = False
                try:
                    self.combat_once(wait_combat_time=12, target=True)
                except CharDeadException:
                    raise RuntimeError('海墟角色死亡，停止本次挑战')
                except (CombatStateUnknown, NotInCombatException):
                    if time.monotonic() >= self._deadline:
                        raise
                finally:
                    self.skip_combat_check = True
                    self._release()
                # No enemies in a wave gap is not completion. next_frame observes
                # authoritative quest/result UI while waiting for the next wave.
                self._wait(lambda f: self.in_combat(), '脱战后未确认下一波或战后界面', timeout=40)
        except SeaPhaseEnded:
            pass
        finally:
            self._observing_half = None
            self._deadline = None
            self.skip_combat_check = True
            self._release()

    def _turn(self, delta):
        # UE camera consumes relative mouse input; WM_MOUSEMOVE is only a UI move.
        # Never send physical input to another application.
        self.executor.check_enabled()
        if not self.hwnd or win32gui.GetForegroundWindow() != self.hwnd.hwnd:
            raise RuntimeError('出口转镜头需要鸣潮处于前台，已停止输入')
        pixels = round(self.width * max(-.12, min(.12, delta)))
        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, pixels, 0, 0, 0)
        self.sleep(.2)

    def _enter_lower(self):
        self._wait(self._upper_end, '未确认前往下半海域')
        self._release()
        self.middle_click(after_sleep=.3)
        self._status('回正视角并寻找下半海域出口')
        deadline = time.monotonic()+60
        try:
            while time.monotonic() < deadline:
                self.next_frame()
                if self._prompt(self.frame, '进入下半海域'):
                    self._release()
                    self.send_key('f')
                    self._wait(lambda f: self.in_team_and_world(frame=f) and not self._upper_end(f)
                               and not self._prompt(f, '进入下半海域'), '进入下半海域后加载未确认', timeout=120)
                    return
                if not self._upper_end(self.frame):
                    raise RuntimeError('寻找出口时上半结束提示消失')
                marker = vision.exit_marker(self.frame)
                if marker is None:
                    self._turn(.10)
                elif abs(marker[0]-.5) > .045:
                    self._turn((marker[0]-.5)*.35)
                else:
                    self.send_key('w', down_time=.25)
                    self.sleep(.1)
            raise RuntimeError('60秒内未找到F进入下半海域')
        finally:
            self._release()

    def _check_world_team(self, preset):
        self.chars = [None, None, None]
        self.reset_to_false('海墟换半场，重新识别角色')
        def loaded(frame):
            self.load_chars()
            return len(self.chars) == 3 and all(c is not None for c in self.chars)
        self._wait(loaded, '未能读取当前战斗编队', timeout=20)
        observed = tuple(c.char_name for c in self.chars)
        if observed != preset.members:
            raise RuntimeError(f'场内角色与预设不符：{observed} / {preset.members}')

    def _read_result(self):
        self._wait(self._result, '下半结束后未确认结算')
        def number(frame, region):
            values = [compact(b.name) for b in self.ocr(*region, frame=frame)]
            nums = [int(s) for s in values if re.fullmatch(r'\d{1,5}', s)]
            return nums[0] if len(nums) == 1 else None
        def read(frame):
            if not self._result(frame):
                return None
            upper = number(frame, (.61, .36, .70, .41))
            lower = number(frame, (.61, .53, .70, .58))
            total = number(frame, (.44, .77, .56, .82))
            return (upper, lower, total) if scores_valid(upper, lower, total) else None
        values = self._wait(read, '上下半分数与总分未能一致确认')
        self.screenshot(f'sea_ruins_floor_{self._floor}_result')
        self.info_set(f'第{self._floor}层', f'上半{values[0]} 下半{values[1]} 总分{values[2]}')
        return values

    def _continue(self):
        expected = self._floor+1
        def source(frame):
            if not self._result(frame):
                return None
            text = ''.join(compact(b.name) for b in self.ocr(.55, .91, .76, .95, frame=frame))
            if not re.search(rf'第{expected}层', text):
                return None
            return self._button(frame, (.56, .84, .73, .91), '继续挑战')
        self.navigate_ui('海墟继续下一层', source, lambda f: self._detail(f, expected),
                         attempts=1, timeout=120, identity=('sea', expected))

    def run(self):
        WWOneTimeTask.run(self)
        self._observing_half = None
        self._floor = 7
        try:
            season_rule(7, 0)
            vision.normalized(self.require_game_frame())
            self._status('进入再生海域')
            self._open()
            for floor in range(7, 12):
                self._floor = floor
                self._wait(lambda f: self._detail(f, floor), '当前层号未确认')
                self._status(f'第{floor}层扫描预设与信物')
                presets = self._scan_presets()
                tokens = self._scan_tokens()
                plan = choose_loadout(presets, tokens, floor)
                for reason in plan.reasons:
                    self.log_info(reason)
                self._apply_preset(0, plan.upper)
                self._apply_preset(1, plan.lower)
                self._wait(lambda f: self._members_match(f, 0, plan.upper) and self._members_match(f, 1, plan.lower),
                           '两队应用后成员冲突或顺序不符')
                for half in (0, 1):
                    self._equip_token(half, plan.tokens[half])
                self.navigate_ui('海墟进入战斗地图',
                    lambda f: self._button(f, (.72, .88, .93, .95), '开启挑战') if self._detail(f, floor) else None,
                    lambda f: self.in_team_and_world(frame=f) and not self._detail(f),
                    attempts=1, timeout=120, identity=('sea_start', floor))
                self._check_world_team(plan.upper)
                self._start_combat()
                self._fight(0)
                self._enter_lower()
                self._check_world_team(plan.lower)
                self._start_combat()
                self._fight(1)
                self._read_result()
                if floor < 11:
                    self._continue()
            self.navigate_ui('海墟返回选关',
                lambda f: self._button(f, (.28, .84, .44, .91), '返回海墟') if self._result(f) else None,
                self._map, attempts=1, timeout=120, identity='sea_finished')
            self._status('7—11层挑战完成；未挑战无尽，未领取奖励')
        except Exception as error:
            self._observing_half = None
            self.screenshot('sea_ruins_failed')
            self._status(f'海墟停止：{error}')
            raise
        finally:
            self._observing_half = None
            self.skip_combat_check = True
            self._release()
