"""Preset-only, evidence-checked Respawning Waters (7–11) automation."""
import re
import time
import cv2
import numpy as np
from ok.feature.FeatureSet import FeatureSet

from src.task.WWOneTimeTask import WWOneTimeTask
from src.task.BaseCombatTask import BaseCombatTask, CombatStateUnknown, NotInCombatException, CharDeadException
from src.task.AutoAbyssTask import AutoAbyssTask, exact_ocr_box, match_travel_button, char_names, char_dict
from src.task.sea_ruins import Preset, Token, compact, parse_count, scores_valid
from src.task import sea_ruins_vision as vision
from src.task.sea_ruins_tokens import identify_token
from src.task.sea_ruins_recovery import SeaRuinsRecovery, SeaLoadoutChanged


class SeaPhaseEnded(Exception):
    pass


class SeaExitMarkerLost(Exception):
    pass


class AutoSeaRuinsTask(SeaRuinsRecovery, WWOneTimeTask, BaseCombatTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '自动冥歌海墟'
        self.description = '请从再生海域7至11层的海墟详情页启动；识别当前层后使用原有预设和适配信物挑战至11层，出错暂停接管。'
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
        self._token_artwork = {}
        self._handling_unlock = False

    # Reuse the proven F2 template and avatar descriptor implementation only.
    def _character_template_descriptors(self):
        if self._character_descriptors is None:
            self._character_descriptors = []
            # Do not upscale the shared 720p HUD thumbnail: its lost detail can
            # turn Shorekeeper into Zani. Keep this reference cache sea-local.
            features = FeatureSet(False, 'assets/coco_annotations.json', 0, 0)
            reference_frame = np.zeros((1440, 2560, 3), np.uint8)
            for name in char_names:
                feature = features.get_feature_by_name(reference_frame, name)
                if feature is None or feature.mat is None:
                    continue
                im = feature.mat
                scale = 130 / max(1, im.shape[0])
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
        if not self._handling_unlock and self._observing_half is None:
            self._dismiss_unlock()
        if self._observing_half is not None:
            now = time.monotonic()
            if now > self._deadline:
                raise CombatStateUnknown('海墟单半场超过10分钟')
            if now >= self._next_observation:
                self._next_observation = now+.65
                if not self._handling_unlock:
                    self._dismiss_unlock()
                ended = self._upper_end(self.frame) if self._observing_half == 0 else self._result(self.frame)
                self._phase_seen = self._phase_seen+1 if ended else 0
                if self._phase_seen >= 2:
                    raise SeaPhaseEnded()
        return self.frame

    def _unlock_popup(self, frame):
        return bool(self._button(frame, (.40, .33, .60, .42), '解锁信物')
                    and self._button(frame, (.38, .79, .62, .88), '点击空白处关闭'))

    def _dismiss_unlock(self):
        if not self._unlock_popup(self.frame):
            return False
        self._handling_unlock = True
        try:
            for _ in range(3):
                self.click_relative(.5, .84, after_sleep=.4)
                super().next_frame()
                if not self._unlock_popup(self.frame):
                    # The inventory is scanned afresh before every floor plan.
                    return True
            raise RuntimeError('解锁信物弹窗未能关闭，请手动关闭后继续')
        finally:
            self._handling_unlock = False

    def _detail(self, frame, floor=None):
        if floor is not None:
            return self._detail_floor(frame) == floor
        return bool(self._button(frame, (.025, .035, .15, .095), '海墟详情'))

    def _detail_floor(self, frame):
        if not self._button(frame, (.025, .035, .15, .095), '海墟详情'):
            return None
        numbers = [text for text in self._small_text(frame, (.150, .12, .195, .168)) if text.isdigit()]
        if len(numbers) == 1 and numbers[0] in ('7', '8', '9', '10', '11'):
            return int(numbers[0])
        if self._button(frame, (.12, .18, .23, .24), '险滩'):
            region = vision.crop(cv2.resize(frame, (1280, 720)), (.145, .105, .20, .19))
            template = vision.reference('detail_seven')
            score = cv2.minMaxLoc(cv2.matchTemplate(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(template, cv2.COLOR_BGR2GRAY), cv2.TM_CCOEFF_NORMED))[1]
            if score >= .85:
                return 7
        return None

    def _challenge_button(self, frame):
        if not self._detail(frame, self._floor):
            return None
        for label in ('开启挑战', '开始挑战', '再次挑战'):
            button = self._button(frame, (.72, .88, .93, .95), label)
            if button is not None:
                return button
        return None

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
            numbers = self._small_text(frame, (.042, top, .063, top+.036))
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
                    self.log_warning(f'跳过空位、重复或未识别角色预设{preset.number}: {preset.members}')
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
                        raise SeaLoadoutChanged('预设回位后成员变化，未点击；继续后重新规划')
                    self.click_relative(.16, top+.065)
                    self._wait(lambda f: self._members_match(f, half, preset), '预设应用后头像顺序未确认')
                    self._close_presets()
                    return
            self.scroll_relative(.20, .50, -2)
            self.sleep(.3)
        raise SeaLoadoutChanged(f'未找回预设{preset.number}，继续后重新规划')

    def _token_page(self, frame):
        return bool(self._button(frame, (.015, .025, .20, .10), '信物一览')
                    and vision.token_cards(frame))

    def _open_tokens(self, half):
        self._wait(lambda f: self._detail(f, self._floor), '信物入口不在详情页')
        self.click_relative(.853, (.39, .71)[half], after_sleep=.3)
        self._wait(self._token_page, '未进入信物携带页')
        self.scroll_relative(.40, .50, 30)
        self.sleep(.4)

    def _page_tokens(self, frame):
        records = []
        for rect in vision.token_cards(frame):
            rarity = vision.token_rarity(frame, rect)
            if rarity == 'green' or vision.token_locked(frame, rect):
                continue
            x, y, w, h = rect
            caption = ''.join(self._small_text(frame, ((x+5)/2048, (y+h*.79)/1152,
                                                       (x+w-5)/2048, (y+h*.99)/1152)))
            rule = identify_token(caption, rarity)
            if rule is None:
                raise RuntimeError(f'信物名称/品质未确认：{caption} / {rarity}，请调整列表后继续')
            count = self._token_count(frame, rect)
            if count is None:
                raise RuntimeError(f'{rule.name}数量未确认，请调整列表后继续')
            records.append((Token(rule.name, rule.effect, count), rect))
        return records

    def _inventory_page(self):
        error = RuntimeError('未确认信物列表')
        for attempt in range(3):
            self.next_frame()
            if self._token_page(self.frame):
                try:
                    return self._page_tokens(self.frame)
                except RuntimeError as read_error:
                    error = read_error
            if attempt < 2:
                self.sleep(.2)
        raise error

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
            for token, rect in self._inventory_page():
                old = tokens.get(token.name)
                if old is not None and old.remaining != token.remaining:
                    raise RuntimeError(f'{token.name}跨页库存不一致，请重新扫描')
                tokens[token.name] = token
                self._token_artwork[token.name] = vision.token_art(self.frame, rect)
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
        if self._token_equipped(self.frame, half, target):
            return
        self._open_tokens(half)
        for _ in range(24):
            for token, rect in self._inventory_page():
                if token.name == target.name:
                    if not token.available:
                        raise SeaLoadoutChanged(f'{target.name}已不可携带，继续后重新扫描库存')
                    art = vision.token_art(self.frame, rect)
                    x, y, w, h = rect
                    self.click_relative((x+w/2)/2048, (y+h/2)/1152, after_sleep=.25)
                    def selected(frame):
                        title = ''.join(b.name for b in self.ocr(.69, .125, .965, .185, frame=frame))
                        rule = identify_token(title)
                        return rule is not None and rule.name == target.name
                    self._wait(selected, f'{target.name}详细名称未确认', timeout=5)
                    self._token_artwork[target.name] = art
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
        raise SeaLoadoutChanged(f'未找回信物：{target.name}，继续后重新扫描库存')

    def _token_equipped(self, frame, half, target):
        art = self._token_artwork.get(target.name)
        if art is None or not self._detail(frame, self._floor):
            return False
        y = (.34, .66)[half]
        return self._same_art(art, vision.crop(frame, (.827, y, .88, y+.096)))

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

    def _enter_lower(self):
        self._wait(self._upper_end, '未确认前往下半海域')
        self._release()
        self.middle_click(after_sleep=.3)
        self._status('后台寻路前往下半海域出口')

        def arrived():
            if self._prompt(self.frame, '进入下半海域'):
                return True
            if not self._upper_end(self.frame):
                raise RuntimeError('寻找出口时上半结束提示消失')
            return False

        def target():
            marker = vision.exit_marker(self.frame)
            if marker is None:
                # The shared walker retains its last target. Stop keys before
                # raising, never walk using a stale marker.
                self._release()
                raise SeaExitMarkerLost()
            x, y, _ = marker
            return self.box_of_screen(x-.005, y-.005, x+.005, y+.005)

        try:
            deadline = time.monotonic() + 60
            reached = False
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    reached = self.walk_to_box(target, time_out=remaining, end_condition=arrived)
                    break
                except SeaExitMarkerLost:
                    self._release()
                    self._status('出口标记暂时丢失，停步重新识别')
                    # Restart the walker after recovery: its last_direction and
                    # cached target are invalid once movement keys are released.
                    for _ in range(10):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self.sleep(min(.3, remaining))
                        self.next_frame()
                        reached = arrived()
                        if reached or vision.exit_marker(self.frame) is not None:
                            break
                    else:
                        raise RuntimeError('出口标记丢失，停步重试后仍未识别')
                    if reached:
                        break
            if not reached:
                raise RuntimeError('60秒内未找到F进入下半海域')
            self._release()
            self.next_frame()
            if not self._prompt(self.frame, '进入下半海域'):
                raise RuntimeError('进入下半海域提示消失，未按F')
            self.send_key('f')
            self._wait(lambda f: self.in_team_and_world(frame=f) and not self._upper_end(f)
                       and not self._prompt(f, '进入下半海域'), '进入下半海域后加载未确认', timeout=120)
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
        self._observing_half = None
        self._run_sea_stages()
