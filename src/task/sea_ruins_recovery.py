"""In-process checkpoints for sea ruins, using the framework's existing pause UI."""
from ok import TaskDisabledException
from src.task.sea_ruins import ENDLESS, choose_loadout, floor_label, next_floor, season_rule
from src.task import sea_ruins_vision as vision
from src.task.WWOneTimeTask import WWOneTimeTask


STAGES = ('open', 'presets', 'tokens', 'plan', 'team_upper', 'team_lower',
          'token_upper', 'token_lower', 'enter', 'start_upper', 'fight_upper',
          'enter_lower', 'start_lower', 'fight_lower', 'result', 'next', 'finish', 'done')
LABELS = ('识别当前海墟详情', '扫描预设', '扫描信物库存', '选择编队与信物', '应用上半编队', '应用下半编队',
          '携带上半信物', '携带下半信物', '进入战斗地图', '开启上半挑战', '上半战斗',
          '进入下半海域', '开启下半挑战', '下半战斗', '读取结算', '进入下一层', '返回选关', '完成')


class SeaLoadoutChanged(RuntimeError):
    """The observed roster/inventory no longer supports the saved plan."""


class SeaRuinsRecovery:
    def _pause_for_sea_error(self, error):
        self._observing_half = None
        self._deadline = None
        self.skip_combat_check = True
        try:
            self._release()
        except Exception as release_error:
            self.log_warning(f'暂停时释放移动输入失败：{release_error}')
        # Combat can fail inside a held skill. Cleanup bypasses task pause guards
        # and attempts every key, even if the game window has disappeared.
        for name in ('Echo Key', 'Liberation Key', 'Resonance Key', 'Tool Key', 'Jump Key', 'Dodge Key'):
            try:
                key = self.key_config.get(name)
                if key:
                    self.executor.interaction.send_key_up(self.validate_key(key))
            except Exception as release_error:
                self.log_warning(f'暂停时释放{name}失败：{release_error}')
        location = floor_label(self._floor) if self._floor is not None else '当前层待识别'
        self.info_set('海墟待接管', f'{location} / {LABELS[STAGES.index(self._sea_stage)]}：{error}')
        self.log_error(f'海墟已暂停：{error}。请处理当前界面后点击继续；停止按钮仍可终止任务。', notify=True)
        try:
            self.screenshot('sea_ruins_paused')
        except TaskDisabledException:
            raise
        except Exception as screenshot_error:
            self.log_warning(f'暂停截图失败：{screenshot_error}')
        # pause() blocks on the executor thread; the foreground task remains
        # current, so background trigger tasks cannot take over the scheduler.
        old_interval = self.sleep_check_interval
        self.sleep_check_interval = -1
        try:
            self.pause()
        finally:
            self.sleep_check_interval = old_interval
        self.executor.check_enabled()
        self.executor.reset_scene()
        self.reset_to_false('海墟人工接管后重新识别')
        self.info_set('海墟待接管', '继续后正在核对当前页面')

    def _resume_sea_stage(self):
        self.next_frame()
        f = self.frame
        stage = self._sea_stage
        if stage == 'open':
            # Re-enter the same read-only start check, including season expiry.
            return 'open'
        if self._token_page(f):
            self.send_key('esc')
            self._wait(lambda frame: self._detail(frame, self._floor), '请返回当前层编队页后继续')
            f = self.frame
        elif self._detail(f) and not self._detail(f, self._floor):
            if self._page_presets(f):
                self._close_presets()
                f = self.frame
        if self._detail(f, self._floor):
            if self._sea_replan or stage in ('open', 'plan') or STAGES.index(stage) > STAGES.index('enter'):
                self._sea_plan = None
                self._sea_replan = False
                self._token_artwork.clear()
                return 'presets'
            if stage == 'enter' and not (
                    self._members_match(f, 0, self._sea_plan.upper)
                    and self._members_match(f, 1, self._sea_plan.lower)
                    and self._token_equipped(f, 0, self._sea_plan.tokens[0])
                    and self._token_equipped(f, 1, self._sea_plan.tokens[1])):
                self._sea_plan = None
                self._token_artwork.clear()
                return 'presets'
            return stage  # each application checks whether it is already done
        if stage == 'next' and self._detail(f, next_floor(self._floor)):
            self._floor = next_floor(self._floor)
            self._sea_plan = None
            self._token_artwork.clear()
            return 'presets'
        if stage == 'finish' and self._map(f):
            return 'done'
        if self._sea_plan is not None and STAGES.index(stage) >= STAGES.index('enter'):
            if self._result(f):
                return 'result'
            if self._upper_end(f):
                return 'enter_lower'
            if vision.sea_world(f) and self.in_team_and_world(frame=f):
                # The non-overlapping rosters distinguish halves, without
                # treating absence of an upper-end message as lower-half proof.
                self.chars = [None, None, None]
                self.load_chars()
                members = tuple(c.char_name if c else '' for c in self.chars)
                if members == self._sea_plan.upper.members:
                    return 'start_upper'
                if members == self._sea_plan.lower.members:
                    return 'start_lower'
        raise RuntimeError('无法确认当前层或上下半，请回到本层编队页、战斗场景或结算页后继续')

    def _sea_step(self):
        stage, plan = self._sea_stage, self._sea_plan
        if stage == 'open':
            WWOneTimeTask.run(self)
            vision.normalized(self.require_game_frame())
            floor = self._wait(self._detail_floor, '请进入再生海域7至11层或无尽深渊的海墟详情页后继续；未确认关卡名称')
            season_rule(floor, 0)
            self._floor = self._start_floor = floor
        elif stage == 'presets':
            self._wait(lambda f: self._detail(f, self._floor), '当前层号未确认')
            self._sea_presets = self._scan_presets()
        elif stage == 'tokens':
            self._sea_tokens = self._scan_tokens()
        elif stage == 'plan':
            self._sea_plan = choose_loadout(self._sea_presets, self._sea_tokens, self._floor)
            for reason in self._sea_plan.reasons:
                self.log_info(reason)
        elif stage in ('team_upper', 'team_lower'):
            half = int(stage == 'team_lower')
            preset = (plan.upper, plan.lower)[half]
            self.next_frame()
            if not self._members_match(self.frame, half, preset):
                self._apply_preset(half, preset)
            if half == 1:
                self._wait(lambda f: self._members_match(f, 0, plan.upper)
                           and self._members_match(f, 1, plan.lower), '两队应用后成员冲突或顺序不符')
        elif stage in ('token_upper', 'token_lower'):
            half = int(stage == 'token_lower')
            self.next_frame()
            self._equip_token(half, plan.tokens[half])
        elif stage == 'enter':
            self._wait(lambda f: self._members_match(f, 0, plan.upper)
                       and self._members_match(f, 1, plan.lower)
                       and self._token_equipped(f, 0, plan.tokens[0])
                       and self._token_equipped(f, 1, plan.tokens[1]), '开战前编队或信物与计划不符')
            self.navigate_ui('海墟进入战斗地图', self._challenge_button,
                             lambda f: self.in_team_and_world(frame=f) and not self._detail(f),
                             attempts=1, timeout=120, identity=('sea_start', self._floor))
        elif stage in ('start_upper', 'start_lower'):
            self._check_world_team(plan.upper if stage == 'start_upper' else plan.lower)
            self._start_combat()
        elif stage in ('fight_upper', 'fight_lower'):
            self._fight(int(stage == 'fight_lower'))
        elif stage == 'enter_lower':
            self._enter_lower()
        elif stage == 'result':
            self._read_result()
            return 'finish' if self._floor == ENDLESS else 'next'
        elif stage == 'next':
            self._continue()
            self._floor = next_floor(self._floor)
            self._sea_plan = None
            self._token_artwork.clear()
            return 'presets'
        elif stage == 'finish':
            self.navigate_ui('海墟返回选关',
                             lambda f: self._button(f, (.28, .84, .44, .91), '返回海墟') if self._result(f) else None,
                             self._map, attempts=1, timeout=120, identity='sea_finished')
        return STAGES[STAGES.index(stage)+1]

    def _run_sea_stages(self):
        self._floor, self._start_floor = None, None
        self._sea_stage, self._sea_plan = 'open', None
        self._sea_replan = False
        self._token_artwork.clear()
        recovering = False
        try:
            while self._sea_stage != 'done':
                try:
                    self.executor.check_enabled()
                    if recovering:
                        self._sea_stage = self._resume_sea_stage()
                        recovering = False
                        if self._sea_stage == 'done':
                            break
                    location = floor_label(self._floor) if self._floor is not None else '当前层待识别'
                    self._status(f'{location}：{LABELS[STAGES.index(self._sea_stage)]}')
                    self._sea_stage = self._sea_step()
                except TaskDisabledException:
                    raise
                except Exception as error:
                    if isinstance(error, SeaLoadoutChanged):
                        self._sea_replan = True
                    self._pause_for_sea_error(error)
                    recovering = True
            self.info_set('海墟待接管', '')
            self._status(f'{floor_label(self._start_floor)}至无尽深渊挑战完成；未领取奖励')
        finally:
            self._observing_half = None
            self._deadline = None
            self.skip_combat_check = True
            self._release()
