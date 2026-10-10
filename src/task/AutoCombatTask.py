import time
import threading

from src.runtime.combat_api import TriggerTask, Logger
from src.runtime.combat_api import CaptureException
from src.runtime.game_runtime_errors import FrameUnavailable, GameProcessLost
from src.char.CharFactory import char_names
from src.scene.WWScene import WWScene
from src.task.BaseCombatTask import BaseCombatTask, NotInCombatException, CharDeadException

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    owns_switch_healer_config = True
    persistent_enabled = True
    use_original_multi_rotation = True
    solo_rotation_enabled = False
    combat_mode = 'multi'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.name = "⚔️ Auto Combat"
        self.description = "Auto combat stays enabled and retries errors until you manually turn it off."
        self.last_is_click = False
        self.default_config.update({
            'Auto Target': True,
            'Use Liberation': True,
            'Check Levitator': True,
            'Switch to Healer before and after Combat': True,
        })
        self.config_description = {
            'Auto Target': 'Turn off to enable auto combat only when manually target enemy using middle click',
            'Use Liberation': 'Do not use Liberation in Open World to Save Time',
            'Check Levitator': 'Toggle the levitator and verify if the character is floating',
            'Switch to Healer before and after Combat': 'Better Chance to Keep Character Alive',
        }
        self.op_index = 0
        self.char_features_warmed_up = False
        self._retry_at = 0.0
        self._error_count = 0
        self._manual_generation = 0
        self._manual_desired = None
        self._enable_pending = False
        self._capture_waiting = False
        self._enable_lock = threading.Lock()

    def on_create(self):
        super().on_create()
        self._manual_desired = self.enabled

    @property
    def recovery_status(self):
        if not self.enabled:
            return '已手动关闭'
        if self._capture_waiting:
            return '等待游戏窗口/截图恢复'
        if self._error_count or getattr(self, '_rotation_recovering', False):
            return '异常恢复中'
        return '自动战斗中' if self.running else '已开启，等待战斗'

    @property
    def retry_delay(self):
        return max(0.0, self._retry_at - time.monotonic())

    def disable(self):
        """Internal task termination must never cancel the user's combat preference."""
        self._release_combat_inputs()

    def set_enabled_from_ui(self, checked):
        self._manual_generation += 1
        generation = self._manual_generation
        self._manual_desired = bool(checked)
        self._retry_at = 0
        self._error_count = 0
        self._capture_waiting = False
        self._enable_pending = bool(checked)
        if not checked:
            super().disable()
            self._release_combat_inputs()
            self._release_combat_mode()
            return
        # Persist intent before device setup: a missing window is not a user stop.
        self.config['_enabled'] = True
        threading.Thread(target=self._enable_from_ui, args=(generation,), name='TaskEnable', daemon=True).start()

    def enable(self):
        if self._manual_desired is False:
            return  # An internal enable call cannot override a user's stop.
        self._enabled = True
        self.config['_enabled'] = True
        self._enable_pending = True
        try:
            self._prepare_combat_input()
        except Exception as error:
            self.handle_execution_error(error)
        finally:
            if self._manual_desired is False:
                super().disable()
            self._emit_state()

    def _prepare_combat_input(self):
        self.ensure_capture()
        self.executor.interaction.on_run()
        self._enable_pending = False

    def _enable_from_ui(self, generation):
        with self._enable_lock:
            if generation != self._manual_generation or not self._manual_desired:
                return
            try:
                self.enable()
            finally:
                if not self._manual_desired:
                    super().disable()
                self.executor._wake_executor()
                self._emit_state()

    def _emit_state(self):
        try:
            from src.runtime.combat_api import emit_task_state
            emit_task_state(self)
        except Exception:
            pass  # UI diagnostics cannot change the user's enabled preference.

    def should_trigger(self):
        return time.monotonic() >= self._retry_at and super().should_trigger()

    def handle_execution_error(self, error):
        self._release_combat_inputs()
        if isinstance(error, GameProcessLost):
            self._release_combat_mode()
        if not self.enabled:
            return True  # An explicit manual stop wins over a late exception.
        self._capture_waiting = isinstance(error, (FrameUnavailable, GameProcessLost, CaptureException))
        self._error_count += 1
        delay = min(30, 2 ** min(self._error_count, 5))
        self._retry_at = time.monotonic() + delay
        self.freeze_durations = []
        try:
            self.do_reset_to_false()
        except Exception:
            self._in_combat = False
        self.record_combat_error(error, self._error_count, delay)
        return True

    def warm_up_char_features(self):
        if self.char_features_warmed_up:
            return
        try:
            for char_name in char_names:
                self.get_feature_by_name(char_name)
        except Exception as e:
            logger.warning(f'warm_up_char_features failed: {e}')
            return
        self.char_features_warmed_up = True
        logger.info(f'warm_up_char_features loaded {len(char_names)} character templates')

    def run(self):
        try:
            self._release_combat_inputs()
            if self._combat_held_keys or self._combat_held_mouse:
                raise RuntimeError('自动战斗仍有未释放输入，等待输入后端恢复')
            if self._enable_pending:
                self._prepare_combat_input()
            if self._capture_waiting:
                logger.info('game capture restored; resume combat detection')
                self.info.pop('自动战斗保护', None)
                self._capture_waiting = False
                self._error_count = 0
                self._retry_at = 0
                self._last_combat_error = None
                self._suppressed_combat_errors = 0
            result = self._run_combat()
            if result and self._error_count:
                self._error_count = 0
                self._retry_at = 0
                self.info.pop('自动战斗保护', None)
                self._emit_state()
            return result
        finally:
            self._release_combat_inputs()
            try:
                self.finish_rotation_tracking('auto_combat_exit')
            except Exception as error:
                self.handle_execution_error(error)

    def _run_combat(self):
        self.warm_up_char_features()
        ret = False
        if not self.scene.in_team(self.in_team_and_world):
            self._release_combat_mode()
            return ret
        team = self.in_team()
        if not team[0] or not self._team_size_allowed(team[2]):
            if not team[0]:
                self._release_combat_mode()
            elif getattr(self.executor, '_background_combat_mode', None) == self.combat_mode and not self.in_combat():
                self._release_combat_mode()
            return ret
        owner = getattr(self.executor, '_background_combat_mode', None)
        if owner is not None and owner != self.combat_mode:
            return ret
        self.executor._background_combat_mode = self.combat_mode
        self.use_liberation = self.config.get('Use Liberation')
        if not self.use_liberation and not self.in_world():  # 仅大世界生效
            self.use_liberation = True
        combat_start = time.time()
        switched_to_healer = False
        combat_failed = False
        while self.combat_is_active():
            ret = True
            try:
                if not switched_to_healer:
                    self.switch_healer()
                    switched_to_healer = True
                self.perform_combat_rotation()
            except CharDeadException:
                combat_failed = True
                self.log_error(f'Characters dead', notify=True)
                break
            except NotInCombatException as e:
                if not self.is_expected_combat_end():
                    combat_failed = True
                    self.log_warning(f'combat interrupted; waiting for fresh detection: {e}')
                logger.debug(f'auto_combat_task_out_of_combat {e}')
                break
        if ret:
            if not combat_failed:
                reason = getattr(self, 'out_of_combat_reason', '') or 'combat_state_cleared'
                logger.info(f'combat ended normally duration={int(time.time() - combat_start)}s reason={reason}')
            self.combat_end()
            self.switch_healer()
            self._release_combat_mode()
        else:
            self._release_combat_mode()
        return ret

    def _team_size_allowed(self, count):
        return count in (2, 3)

    def _release_combat_mode(self):
        if getattr(self.executor, '_background_combat_mode', None) == self.combat_mode:
            self.executor._background_combat_mode = None

    def on_destroy(self):
        self._release_combat_mode()
        super().on_destroy()

    def realm_perform(self):
        if not self.last_is_click:
            if self.op_index % 10 == 0:
                self.send_key_and_wait_animation('4', self.in_illusive_realm, enter_animation_wait=0.2)
            else:
                self.click()
        else:
            if self.available('liberation'):
                self.send_key_and_wait_animation(self.get_liberation_key(), self.in_illusive_realm)
            elif self.available('echo'):
                self.send_key(self.get_echo_key())
            elif self.available('resonance'):
                self.send_key(self.get_resonance_key())
            elif self.is_con_full() and self.in_team()[0]:
                self.send_key_and_wait_animation('2', self.in_illusive_realm)
        self.last_is_click = not self.last_is_click
        self.op_index += 1
        self.sleep(0.02)


if __name__ == "__main__":
    from ok import run_task
    from config import config

    run_task(config, task=AutoCombatTask, debug=True)
