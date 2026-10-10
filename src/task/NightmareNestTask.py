import json
import re
import time
import cv2
from dataclasses import dataclass

from ok import Logger, TaskDisabledException, WaitFailedException
from src.task.BaseCombatTask import BaseCombatTask, CombatStateUnknown, CharDeadException, CharRevivedException
from src.task.WWOneTimeTask import WWOneTimeTask
from src.task_status import publish_task_status

logger = Logger.get_logger(__name__)
TRAVEL_FEATURES = ['fast_travel_custom', 'gray_teleport']
CONFIRM_FEATURES = ['confirm_btn_hcenter_vcenter', 'confirm_btn_highlight_hcenter_vcenter']

# 残象聚落（Tacet Discord Nest）名称，按游戏内 F2 残象页面从上到下的顺序
from src.nightmare_nests import (NEST_NAMES, DEFAULT_NEST_NAMES, NIGHTMARE_NAMES, NEST_TOTALS_BY_NAME,
                                 canonical_nest_name, normalize_nest_text)
# 每个位置的聚落怪物总数（用于校验行位置是否对应正确，48 出现两次所以不能单独用总数定位）
NEST_TOTAL_BY_POSITION = list(NEST_TOTALS_BY_NAME.values())
# 可识别的聚落总数（保留 36 以兼容旧版本/历史数据）
NEST_TOTALS = {'24', '36', '41', '48'}
# 要刷的残象聚落（勾选 = 刷，不勾选 = 不打）
FARM_TACET_DISCORD_NESTS = 'Tacet Discord Nests to Farm'
FARM_NIGHTMARE_SETTLEMENTS = 'Nightmare Settlements to Farm'


@dataclass
class NestTarget:
    box: object
    cache_key: str
    display_name: str = '未知目标'
    ordinal: int = 0
    current: int = 0
    total: int = 0


class NightmareNestTask(WWOneTimeTask, BaseCombatTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.target_enemy_time_out = 10
        self.name = "🌙 Nightmare Nest Task"
        self.description = "Auto Farm all Nightmare Nest"
        self.support_schedule_task = True
        # 已整合进每日任务模块（经每日任务附加任务【自动刷梦魇巢穴】触发，配置合并到每日任务）。
        # 隐藏独立入口，任务列表不再单独显示本卡片；executor 仍注册实例，DailyTask 可照常调用。
        self.visible = False
        self.count_re = re.compile(r"(\d{1,2})/(\d{1,2})")
        self.queues = []
        self._capture_success = False
        self._capture_mode = False
        self._unreachable_nests = set()
        self._nest_progress = {}
        self._nest_stagnation = {}
        self._incomplete_targets = {}
        self.default_config.update({'Which to Farm': ['Nightmare Purification', 'Tacet Discord Nest']})
        self.config_type['Which to Farm'] = {'type': "multi_selection",
                                             'options': ['Nightmare Purification', 'Tacet Discord Nest']}
        # Preserve the old four implicit targets; the new location is opt-in.
        self.default_config.update({FARM_TACET_DISCORD_NESTS: list(DEFAULT_NEST_NAMES)})
        self.default_config.update({FARM_NIGHTMARE_SETTLEMENTS: []})
        self.config_type[FARM_TACET_DISCORD_NESTS] = {
            'type': 'multi_selection',
            'options': NEST_NAMES,
        }
        self.config_type[FARM_NIGHTMARE_SETTLEMENTS] = {
            'type': 'multi_selection',
            'options': NIGHTMARE_NAMES,
        }
        self.config_description = {
            FARM_TACET_DISCORD_NESTS: 'Tacet Discord Nests to farm (checked = farm, unchecked = skip).',
        }

    def run(self):
        publish_task_status(self, stage='刷梦魇巢穴', detail='正在打开 F2 梦魇页面')
        self._capture_mode = False
        self._capture_success = False
        self._unreachable_nests.clear()
        self._reset_progress_tracking()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
            if nest.cache_key.startswith('residual:'):
                self._nest_attempted.add(nest.cache_key)
        self._assert_selected_targets_complete()
        self.ensure_main(time_out=30)

    def run_capture_mode(self, verify_capture=None):
        publish_task_status(self, stage='刷梦魇巢穴', detail='正在打开 F2 梦魇页面')
        self._capture_mode = True
        self._capture_success = False
        self._unreachable_nests.clear()
        self._reset_progress_tracking()
        WWOneTimeTask.run(self)
        self.ensure_main(time_out=30)
        self._init_queue()
        self.log_info('opened gray_book_boss')
        while nest := self.get_nest_to_go():
            self.combat_nest(nest)
            if verify_capture is not None:
                # Pickup/search signals are candidates; daily progress is the result.
                self._capture_success = bool(verify_capture())
                self.ensure_main(time_out=30)
            if self._capture_success:
                break
            if nest.cache_key.startswith('residual:'):
                self._nest_attempted.add(nest.cache_key)
        self.ensure_main(time_out=30)
        if not self._capture_success:
            raise CombatStateUnknown('每日声骸未确认获取，保留待补跑')

    def on_combat_check(self):
        if self._capture_mode:
            self.pick_f(handle_claim=False)
            if self.has_echo_notification():
                return self.reset_to_false(reason='echo captured')
        return True

    def has_echo_notification(self):
        if self.ocr(.02, .40, .35, .65, match=re.compile(
                r'获得.*声骸|獲得.*聲骸|(?:Obtained|Acquired).*Echo|Echo.*(?:Obtained|Acquired)', re.I)):
            self._capture_success = True
        return self._capture_success

    def _enter_nest(self, nest):
        residual = isinstance(nest, NestTarget) and nest.cache_key.startswith('residual:')
        nightmare = isinstance(nest, NestTarget) and nest.cache_key.startswith('nightmare:')
        button = nest.box if isinstance(nest, NestTarget) else nest
        for attempt in range(3):
            if residual or nightmare:
                frame = self.require_game_frame()
                try:
                    if nightmare:
                        self._close_nightmare_filter(frame)
                        frame = self.require_game_frame()
                    rows = (self._nightmare_rows(frame) if nightmare else
                            self._residual_rows(frame, {nest.display_name}))
                    current, total, button = rows[nest.display_name]
                    if current == total:
                        self._nest_completed.add(nest.display_name)
                        return None
                    if button is None:
                        raise ValueError('前往按钮不唯一')
                    self.log_info(f'聚落入口 {attempt + 1}/3：{nest.display_name} '
                                  f'{current}/{total}，按钮=({button.x},{button.y})')
                except (ValueError, KeyError) as error:
                    self.screenshot('nest_entry_source_unknown', frame=frame)
                    raise RuntimeError(f'{nest.display_name}入口源页无法确认，停止重复点击') from error
            self.click(button, after_sleep=2)
            try:
                return self.wait_book_target_state()
            except WaitFailedException:
                if not (residual or nightmare) or attempt == 2:
                    raise
                self.log_warning(f'{nest.display_name}入口未切换，重新核对同一目标后重试 {attempt + 1}/2')

    def combat_nest(self, nest):
        target_name = nest.display_name if isinstance(nest, NestTarget) else '当前目标'
        publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在进入挑战')
        feature = self._enter_nest(nest)
        if feature is None:
            return
        is_team = feature.name in ('team_start_challenge', 'team_entry')
        if is_team:
            self.click_team_challenge()
            self.wait_in_team_and_world(time_out=120)
        else:
            publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在传送')
            if not self._travel_to_nest_or_skip(nest):
                return
            self.sleep(1)
            while self.find_f_with_text():
                self.send_key('f', after_sleep=1)
                self.wait_in_team_and_world(time_out=40, raise_if_not_found=False)
            self.sleep(2)
            publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在战斗')
            self.run_until(self.in_combat, 'w', time_out=10, running=False, target=True)
        wait_combat_time = 10
        combat_recovery_used = False
        while True:
            try:
                need_find = self.combat_once(wait_combat_time=wait_combat_time, target=True,
                                             raise_if_not_found=False)
            except CombatStateUnknown as error:
                state = self._recheck_nest_combat(nest)
                if state == 'combat' and not combat_recovery_used:
                    combat_recovery_used = True
                    self.log_warning('nightmare nest: target is still active, retry current combat once')
                    self.target_enemy(wait=True)
                    wait_combat_time = 1
                    continue
                if state != 'complete':
                    self.screenshot('nightmare_combat_unknown', frame=self.require_game_frame())
                    raise error
                need_find = True
            except CharRevivedException:
                self.log_info('nightmare nest: death recovered, re-enter from F2 book')
                return
            except CharDeadException:
                self.log_warning('nightmare nest: revive failed, restore world and retry from F2 book')
                publish_task_status(
                    self,
                    stage='刷梦魇巢穴',
                    detail=f'{target_name} · 角色阵亡，正在恢复后重试',
                )
                self.ensure_main(time_out=180)
                return
            captured_early = False
            if self._capture_mode:
                if self._capture_success or self.wait_until(self.has_echo_notification, time_out=3,
                                                          raise_if_not_found=False):
                    self.log_info("Captured echo during combat, skipping search.")
                    captured_early = True
            if not captured_early:
                publish_task_status(self, stage='刷梦魇巢穴', detail=f'{target_name} · 正在拾取声骸')
                self.sleep(3)
                if need_find and not self.walk_find_echo(time_out=5, backward_time=2.5):
                    dropped = self.yolo_find_echo(turn=True, use_color=False, time_out=30)[0]
                    logger.info(f'farm echo yolo find {dropped}')
                else:
                    dropped = True
                    self.log_info(f'farm echo walk find true')
                self._capture_success = dropped
            if not self._should_continue_combat_after_pickup():
                break
            self.log_info('nightmare nest: combat detected after pickup')
            wait_combat_time = 1
        # 与刷全部一致：退本后再结束 combat_nest，避免还在巢穴内回 Daily/开书
        if is_team:
            self.esc_world_confirm()
        self.sleep(1)

    def _recheck_nest_combat(self, nest, timeout=8):
        """Classify a transient combat exit without treating missing evidence as victory."""
        deadline = time.monotonic() + timeout
        while True:
            self.require_game_frame()
            if self.has_target() or self.check_health_bar():
                return 'combat'
            counts = self.ocr(0, 0.08, 0.5, 0.45, match=self.count_re) or []
            for count_box in counts:
                for match in re.finditer(self.count_re, count_box.name):
                    current, total = map(int, match.groups())
                    if not isinstance(nest, NestTarget) or not nest.total or total == nest.total:
                        if current < total:
                            return 'combat'
                        if current == total:
                            return 'complete'
            if time.monotonic() >= deadline:
                return 'unknown'
            self.executor.check_enabled()
            self.executor.next_frame(time_out=min(1, max(0.01, deadline - time.monotonic())))

    def _should_continue_combat_after_pickup(self):
        return not self._capture_mode and self.wait_combat(
            target=True, time_out=3, raise_if_not_found=False)

    def _travel_to_nest_or_skip(self, nest):
        travel = self.wait_until(self._find_travel_button, raise_if_not_found=False, time_out=3)
        if travel:
            self.click(travel, after_sleep=1)
            if confirm := self._find_first_feature(CONFIRM_FEATURES, threshold=0.6):
                self.click(confirm, after_sleep=1)

            button_gone = self.wait_until(
                lambda: not self.find_one(travel.name, threshold=0.7),
                time_out=5,
                raise_if_not_found=False,
            )
            if button_gone:
                if self.wait_in_team_and_world(time_out=120, raise_if_not_found=False):
                    return True
            elif self.wait_in_team_and_world(time_out=10, raise_if_not_found=False):
                return True

        if isinstance(nest, NestTarget):
            self._unreachable_nests.add(nest.cache_key)
            publish_task_status(
                self,
                stage='刷梦魇巢穴',
                detail=f'{nest.display_name} · 不可到达，已跳过',
            )
            self.log_info(f'nightmare nest unreachable, skip this run: {nest.cache_key}')
        else:
            publish_task_status(self, stage='刷梦魇巢穴', detail='当前目标 · 不可到达，已跳过')
            self.log_info('nightmare nest unreachable, skip this run')
        self.back(after_sleep=1)
        return False

    def _find_travel_button(self):
        return self._find_first_feature(TRAVEL_FEATURES, threshold=0.7)

    def _find_first_feature(self, feature_names, threshold):
        for feature_name in feature_names:
            if feature := self.find_one(feature_name, threshold=threshold):
                return feature

    def get_nest_to_go(self):
        self._open_book_with_retry("gray_book_boss")

        while self.queues:
            self.queues[0]()
            if nest := self.find_nest():
                return nest
            self.queues.pop(0)

    def _open_book_with_retry(self, feature, attempts=3):
        # openF2Book owns the bounded input budget. Never restart that budget
        # or escape an unknown page after a navigation/account failure.
        return self.openF2Book(feature)

    def _init_queue(self):
        quests = self.config.get('Which to Farm')
        if quests is None:
            quests = ['Nightmare Purification', 'Tacet Discord Nest']
        actions = []
        if 'Tacet Discord Nest' in quests:
            selected = self._selected_residual_names()
            if selected:
                actions.append(self.go_nest)
                if NEST_NAMES[-1] in selected:
                    actions.append(self.go_nest_scroll)
        if 'Nightmare Purification' in quests:
            actions.append(self.go_nightmare)
            actions.append(self.go_nightmare_scroll)
        self.queues = actions

    def go_nightmare(self):
        self.open_boss_book('mengyan')
        self._close_nightmare_filter(self.require_game_frame())
        self.scroll_relative(.75, .5, 20)
        self.sleep(.3)
        self.log_info('go nightmare')

    def go_nightmare_scroll(self):
        self.open_boss_book('mengyan')
        self._close_nightmare_filter(self.require_game_frame())
        self.scroll_relative(.75, .5, -20)
        self.sleep(.3)
        self.log_info('go nightmare scroll')

    def go_nest(self):
        self.open_boss_book('canxiang')
        # The book remembers its position after teleporting or changing tabs.
        self.scroll_relative(.75, .5, 20)
        self.sleep(.3)

    def go_nest_scroll(self):
        self.open_boss_book('canxiang')
        # Same right-hand scrollbar positioning used by click_on_book_target.
        self.click(.9730, .8806, after_sleep=.3)

    def _selected_residual_names(self):
        selected = self.config.get(FARM_TACET_DISCORD_NESTS)
        if selected is None:
            selected = DEFAULT_NEST_NAMES
        names = set()
        for value in selected:
            name = canonical_nest_name(value)
            if name is None:
                raise RuntimeError(f'无法识别配置中的残像聚落：{value}')
            names.add(name)
        return names

    def _residual_rows(self, frame, required=None, top=False):
        boxes = self.ocr(.35, .13, 1, .96, frame=frame) or []
        titles = [(box, canonical_nest_name(box.name)) for box in boxes]
        titles = [(box, name) for box, name in titles if name]
        if top and NEST_NAMES[0] not in {name for _, name in titles}:
            raise ValueError('未确认列表顶部的梦枢天罗')
        counts = [(box, match) for box in boxes
                  for match in re.finditer(self.count_re, box.name)]
        buttons = [box for box in boxes
                   if str(box.name).strip() in ('前往', '前往挑战', 'Go', 'Go To', 'Proceed')]
        rows = {}
        for title, name in titles:
            if required is not None and name not in required:
                continue
            # A count belongs below its title, before the next visible title.
            limit = min((other.y for other, _ in titles if other.y > title.y),
                        default=self.height_of_screen(.96))
            matched = [(box, match) for box, match in counts
                       if title.y <= box.y < limit
                       and box.y - title.y < self.height_of_screen(.12)]
            if len(matched) != 1 or name in rows:
                raise ValueError(f'{name} 的进度行无法唯一确认')
            count, match = matched[0]
            current, total = map(int, match.groups())
            if total != NEST_TOTALS_BY_NAME[name] or not 0 <= current <= total:
                raise ValueError(f'{name} 进度不符：{current}/{total}')
            controls = [button for button in buttons
                        if title.y <= button.y < limit
                        and abs(button.y - count.y) < self.height_of_screen(.07)]
            rows[name] = (current, total, controls[0] if len(controls) == 1 else None)
        return rows

    def _find_residual_nest(self):
        selected = self._selected_residual_names()
        bottom = self.queues[0].__name__ == 'go_nest_scroll'
        required = selected & ({NEST_NAMES[-1]} if bottom else set(NEST_NAMES[:-1]))
        if not required:
            return None
        detail = ''
        for attempt in range(3):
            frame = self.require_game_frame()
            try:
                rows = self._residual_rows(frame, required, top=not bottom)
                missing = required - rows.keys()
                if missing:
                    raise ValueError('未找到所选地点：' + '、'.join(sorted(missing)))
                if any(current < total and button is None
                       for name, (current, total, button) in rows.items() if name in required):
                    raise ValueError('所选地点的前往按钮无法唯一确认')
            except ValueError as error:
                detail = str(error)
                self.log_info(f'残像聚落识别重试 {attempt + 1}/3：{detail}')
                if attempt < 2:
                    if bottom:
                        self.scroll_relative(.75, .5, -4)
                    else:
                        self.scroll_relative(.75, .5, 20)
                    self.sleep(.3)
                continue
            for name in NEST_NAMES:
                if name not in required:
                    continue
                current, total, button = rows[name]
                key = 'residual:' + name
                if current == total:
                    self._nest_completed.add(name)
                    self._clear_target_progress(key)
                    continue
                self._nest_completed.discard(name)
                self._record_target_progress(key, name, current, total)
                if key in self._unreachable_nests:
                    continue
                publish_task_status(self, stage='刷梦魇巢穴', detail=f'当前目标：{name}')
                return NestTarget(button, key, name, NEST_NAMES.index(name) + 1, current, total)
            return None
        self.screenshot('residual_nest_identification_failed', frame=frame)
        raise RuntimeError(f'残像聚落识别失败：{detail}')

    def _nightmare_filter_open(self, frame):
        names = {'熔山裂谷', '彻空冥雷', '啸谷长风', '沉日劫明', '凌冽决断之心', '此间永驻之光'}
        observed = {normalize_nest_text(b.name) for b in (self.ocr(.72, .20, .97, .72, frame=frame) or [])}
        return len(names & observed) >= 3

    def _close_nightmare_filter(self, frame):
        if self._nightmare_filter_open(frame):
            self.click_relative(.60, .11, after_sleep=.3)
            if self._nightmare_filter_open(self.require_game_frame()):
                raise RuntimeError('梦魇合鸣筛选菜单未关闭，未点击目标入口')

    def _nightmare_rows(self, frame, diagnostic=None):
        if self._nightmare_filter_open(frame):
            raise ValueError('梦魇列表被合鸣筛选菜单遮挡')
        boxes = self.ocr(.35, .19, .97, .94, frame=frame) or []
        def describe(box):
            return {'text': str(box.name), 'box': [box.x, box.y, box.width, box.height]}
        if diagnostic is not None:
            diagnostic.update(ocr=[{**describe(b), 'normalized': normalize_nest_text(b.name),
                                    'title_result': ('matched' if normalize_nest_text(b.name).endswith('梦魇聚落')
                                                     else 'not_nightmare_title')}
                                   for b in boxes], rows=[])
        titles = [(b, normalize_nest_text(b.name)) for b in boxes
                  if normalize_nest_text(b.name).endswith('梦魇聚落')]
        rows = {}
        for title, name in titles:
            detail = None
            if diagnostic is not None:
                detail = {'title': describe(title), 'normalized': name}
                diagnostic['rows'].append(detail)
            if title.y < self.height_of_screen(.19):
                if detail is not None:
                    detail['result'] = 'title_above_scan_top'
                continue
            bottom = min((b.y for b, _ in titles if b.y > title.y), default=self.height_of_screen(.94))
            counts = [(b, m) for b in boxes if title.y <= b.y < bottom
                      and b.y - title.y < self.height_of_screen(.12)
                      for m in [self.count_re.search(b.name)] if m]
            buttons = [b for b in boxes if title.y <= b.y < bottom
                       and str(b.name).strip() in ('前往', '前往挑战', '直接挑战', '单人挑战')
                       and b.x >= self.width_of_screen(.80)]
            if detail is not None:
                detail.update(
                    row_bounds=[title.y, bottom],
                    progress_matches=len(counts),
                    title_occurrences=sum(n == name for _, n in titles),
                    button_matches=len(buttons),
                    progress=[{**describe(b), 'result': (
                        'outside_title_row' if not title.y <= b.y < bottom else
                        'too_far_below_title' if b.y - title.y >= self.height_of_screen(.12) else
                        'matched')} for b in boxes if self.count_re.search(b.name)],
                    buttons=[{**describe(b), 'result': (
                        'outside_title_row' if not title.y <= b.y < bottom else
                        'button_text_not_matched' if str(b.name).strip() not in
                        ('前往', '前往挑战', '直接挑战', '单人挑战') else
                        'left_of_button_region' if b.x < self.width_of_screen(.80) else
                        'matched')} for b in boxes if b.x >= self.width_of_screen(.80)
                             or str(b.name).strip() in ('前往', '前往挑战', '直接挑战', '单人挑战')])
            if len(counts) != 1 or sum(n == name for _, n in titles) != 1:
                if detail is not None:
                    detail['result'] = ('progress_not_unique' if len(counts) != 1 else
                                        'title_not_unique')
                continue
            current, total = map(int, counts[0][1].groups())
            if total != 36 or not 0 <= current <= total:
                if detail is not None:
                    detail['result'] = 'progress_total_not_36' if total != 36 else 'progress_out_of_range'
                continue
            rows[name] = (current, total, buttons[0] if len(buttons) == 1 else None)
            if detail is not None:
                detail.update(current=current, total=total,
                              result='accepted' if len(buttons) == 1 else 'button_not_unique')
        return rows

    def _find_nightmare_nest(self):
        selected = set(self.config.get(FARM_NIGHTMARE_SETTLEMENTS) or [])
        if not selected:
            return None
        frame = self.require_game_frame()
        self._close_nightmare_filter(frame)
        frame = self.require_game_frame()
        diagnostic = {}
        rows = self._nightmare_rows(frame, diagnostic)
        action = self.queues[0].__name__
        self._nightmare_scans[action] = (frame.copy(), diagnostic)
        for name in NIGHTMARE_NAMES:
            if name not in selected or name not in rows:
                continue
            current, total, button = rows[name]
            key = 'nightmare:' + name
            if current == total:
                self._nest_completed.add(name)
                self._clear_target_progress(key)
                continue
            self._record_target_progress(key, name, current, total)
            if key in self._unreachable_nests:
                continue
            if button is None:
                self._save_nightmare_scan_evidence({name})
                raise RuntimeError(f'{name}完整入口按钮未确认，未使用估算坐标')
            return NestTarget(button, key, name, NIGHTMARE_NAMES.index(name)+1, current, total)

    def _save_nightmare_scan_evidence(self, missing):
        self.log_warning('nightmare scan unconfirmed ' + json.dumps({
            'missing': sorted(missing),
            'selected': self.config.get(FARM_NIGHTMARE_SETTLEMENTS) or [],
            'completed': sorted(self._nest_completed),
            'unreachable': sorted(self._unreachable_nests),
            'task_source': __file__,
            'normalizer_source': normalize_nest_text.__code__.co_filename,
            'count_pattern': self.count_re.pattern,
        }, ensure_ascii=False))
        for action, (frame, diagnostic) in self._nightmare_scans.items():
            self.log_warning(f'nightmare scan action={action} ' +
                             json.dumps(diagnostic, ensure_ascii=False))
            self.screenshot(f'nightmare_scan_missing_{action}', frame=frame)

    def find_nest(self):
        if self.queues and self.queues[0].__name__ in ('go_nightmare', 'go_nightmare_scroll'):
            return self._find_nightmare_nest()
        if self.queues and self.queues[0].__name__ in ('go_nest', 'go_nest_scroll'):
            return self._find_residual_nest()
        counts = self.ocr(0.35, 0.13, 1, 0.96, match=self.count_re)
        candidates = [(box, match) for box in sorted(counts, key=lambda item: item.y)
                      for match in re.finditer(self.count_re, box.name)
                      if match.group(2) in NEST_TOTALS]
        action_name = self.queues[0].__name__ if self.queues else 'unknown'
        is_residual = action_name not in ('go_nightmare', 'go_nightmare_scroll')
        names = NEST_NAMES if is_residual else NIGHTMARE_NAMES
        selected = self.config.get(FARM_TACET_DISCORD_NESTS if is_residual else FARM_NIGHTMARE_SETTLEMENTS)
        selected = set(names if selected is None and is_residual else selected or [])
        offset = max(0, len(names) - len(candidates)) if action_name == 'go_nightmare_scroll' else 0
        for visible_index, (count_box, match) in enumerate(candidates):
            target_index = offset + visible_index
            if target_index >= len(names):
                continue
            nest_name = names[target_index]
            numerator, denominator = match.groups()
            expected_total = NEST_TOTAL_BY_POSITION[target_index] if is_residual else 36
            if int(denominator) != expected_total:
                self.log_info(f'warning: {nest_name} expected {expected_total} monsters but got {denominator}')
            current = int(numerator)
            total = int(denominator)
            display_name = nest_name
            cache_key = self._make_nest_cache_key(count_box, denominator)
            if current < total:
                if nest_name not in selected:
                    self._clear_target_progress(cache_key)
                    self.log_info(f'skip settlement {nest_name} (not selected to farm)')
                    continue
                self._record_target_progress(cache_key, display_name, current, total)
                if cache_key in self._unreachable_nests:
                    self.log_info(f'skip cached unreachable nightmare nest: {cache_key}')
                    continue
                self.log_info(f'{count_box} is not complete ({current}/{total})')
                count_box.x = self.width_of_screen(0.9)
                count_box.y -= count_box.height * 0.9
                count_box.height = 1
                count_box.width = 1
                publish_task_status(
                    self,
                    stage='刷梦魇巢穴',
                    detail=f'当前目标：{display_name}',
                )
                return NestTarget(
                    count_box,
                    cache_key,
                    display_name=display_name,
                    ordinal=target_index + 1,
                    current=current,
                    total=total,
                )
            self._clear_target_progress(cache_key)

    def _reset_progress_tracking(self):
        self._nest_progress = {}
        self._nest_stagnation = {}
        self._incomplete_targets = {}
        self._nest_completed = set()
        self._nest_attempted = set()
        # Retain only the latest top/bottom scan; write evidence at failure.
        self._nightmare_scans = {}

    def _record_target_progress(self, cache_key, display_name, current, total):
        progress = getattr(self, '_nest_progress', None)
        if progress is None:
            self._reset_progress_tracking()
            progress = self._nest_progress
        previous = progress.get(cache_key)
        if previous is None or current > previous:
            self._nest_stagnation[cache_key] = 0
        elif not cache_key.startswith('residual:') or cache_key in self._nest_attempted:
            self._nest_stagnation[cache_key] = self._nest_stagnation.get(cache_key, 0) + 1
        self._nest_attempted.discard(cache_key)
        progress[cache_key] = current
        self._incomplete_targets[cache_key] = (display_name, current, total)
        if self._nest_stagnation[cache_key] >= 3:
            raise RuntimeError(f'{display_name} 连续 3 次执行后进度未增长（{current}/{total}）')

    def _clear_target_progress(self, cache_key):
        getattr(self, '_incomplete_targets', {}).pop(cache_key, None)
        getattr(self, '_nest_stagnation', {}).pop(cache_key, None)
        getattr(self, '_nest_progress', {}).pop(cache_key, None)
        getattr(self, '_nest_attempted', set()).discard(cache_key)

    def _assert_selected_targets_complete(self):
        quests = self.config.get('Which to Farm')
        if quests is None:
            quests = ['Nightmare Purification', 'Tacet Discord Nest']
        if 'Tacet Discord Nest' in quests:
            missing = self._selected_residual_names() - self._nest_completed
            if missing:
                raise RuntimeError('所选残像聚落未确认完成：' + '、'.join(sorted(missing)))
        if 'Nightmare Purification' in quests:
            missing = set(self.config.get(FARM_NIGHTMARE_SETTLEMENTS) or []) - getattr(self, '_nest_completed', set())
            if missing:
                self._save_nightmare_scan_evidence(missing)
                raise RuntimeError('所选梦魇聚落未确认完成：' + '、'.join(sorted(missing)))
        incomplete = list(getattr(self, '_incomplete_targets', {}).values())
        if not incomplete:
            return
        detail = '、'.join(f'{name} {current}/{total}' for name, current, total in incomplete)
        raise RuntimeError(f'所选梦魇巢穴仍未完成：{detail}')

    def _make_nest_cache_key(self, count_box, denominator):
        action_name = self.queues[0].__name__ if self.queues else 'unknown'
        screen_height = max(self.height_of_screen(1), 1)
        row_y = (count_box.y + count_box.height / 2) / screen_height
        row_slot = round(row_y / 0.02)
        # 使用粗粒度行槽位，避免 OCR 坐标轻微抖动导致同一目标被重复点击。
        return f'{action_name}:{denominator}:{row_slot}'


def convert_image_to_negative(img):
    to_gray = False
    _mat = img
    if len(_mat.shape) == 3:
        to_gray = True
        _mat = cv2.cvtColor(_mat, cv2.COLOR_BGR2GRAY)
    _, _mat = cv2.threshold(_mat, 80, 255, cv2.THRESH_BINARY)
    _mat = cv2.bitwise_not(_mat)
    if to_gray:
        _mat = cv2.cvtColor(_mat, cv2.COLOR_GRAY2BGR)
    return _mat


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=NightmareNestTask, debug=True)
