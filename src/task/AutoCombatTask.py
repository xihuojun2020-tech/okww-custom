import time
import threading

from ok import TriggerTask, Logger
from src.char.CharFactory import char_names
from src.scene.WWScene import WWScene
from src.task.BaseCombatTask import BaseCombatTask, NotInCombatException, CharDeadException

logger = Logger.get_logger(__name__)


class AutoCombatTask(BaseCombatTask, TriggerTask):
    owns_switch_healer_config = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_config = {'_enabled': True}
        self.trigger_interval = 0.1
        self.name = "⚔️ Auto Combat"
        self.description = "Enable auto combat in Abyss, Game World etc"
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
        # Session-only intent: startup/restored config must not count as a manual restart.
        self.manual_keep_enabled = False
        self._auto_disabled = False
        self._retry_at = 0.0
        self._error_count = 0
        self._last_error = None
        self._last_error_log = 0.0
        self._suppressed_errors = 0
        self._manual_generation = 0
        self._manual_desired = False
        self._enable_lock = threading.Lock()
        self._held_keys = {}
        self._held_mouse = {}

    @property
    def recovery_status(self):
        if not self.enabled:
            return '异常已关闭' if self._auto_disabled else ''
        if self.manual_keep_enabled:
            return '异常恢复中' if self._error_count else '手动保持开启'
        return ''

    @property
    def retry_delay(self):
        return max(0.0, self._retry_at - time.monotonic())

    def disable(self):
        if self.manual_keep_enabled:
            self._auto_disabled = False
        self.manual_keep_enabled = False
        self._manual_desired = False
        self._manual_generation += 1
        self._retry_at = 0
        self._error_count = 0
        super().disable()

    def set_enabled_from_ui(self, checked):
        """Only an explicit UI gesture arms protection; refresh/enable() cannot."""
        self._manual_generation += 1
        generation = self._manual_generation
        self._manual_desired = checked
        if not checked:
            self.manual_keep_enabled = False
            self._auto_disabled = False
            self._retry_at = 0
            self._error_count = 0
            self.disable()
            logger.info('auto combat manually disabled; session protection cleared')
            return
        self.manual_keep_enabled = self.manual_keep_enabled or self._auto_disabled
        self._retry_at = 0
        threading.Thread(target=self._enable_from_ui, args=(generation,), name='TaskEnable', daemon=True).start()

    def _enable_from_ui(self, generation):
        # Serialize workers, but never block the GUI's stop gesture on capture setup.
        with self._enable_lock:
            if generation != self._manual_generation or not self._manual_desired:
                return
            try:
                self.enable()
                logger.info(f'auto combat manually enabled; keep_enabled={self.manual_keep_enabled}')
            except Exception as error:
                if not self.handle_execution_error(error):
                    self.disable()
            finally:
                if not self._manual_desired:
                    self.disable()
                else:
                    self.config['_enabled'] = self.enabled
                from ok.gui.Communicate import communicate
                communicate.task.emit(self)

    def should_trigger(self):
        return time.monotonic() >= self._retry_at and super().should_trigger()

    def send_key_down(self, key, after_sleep=0):
        key = self.validate_key(key)
        self._held_keys[key] = self.executor.interaction
        return super().send_key_down(key, after_sleep)

    def send_key_up(self, key, after_sleep=0):
        key = self.validate_key(key)
        result = super().send_key_up(key, after_sleep)
        self._held_keys.pop(key, None)
        return result

    def mouse_down(self, x=-1, y=-1, name=None, key='left'):
        self._held_mouse[key] = self.executor.interaction
        return super().mouse_down(x, y, name, key)

    def mouse_up(self, name=None, key='left'):
        result = super().mouse_up(name, key)
        self._held_mouse.pop(key, None)
        return result

    def _release_combat_inputs(self):
        # Release only inputs held by this task, through their original backend.
        for held, method in ((self._held_keys, 'send_key_up'), (self._held_mouse, 'mouse_up')):
            for key, interaction in list(held.items()):
                try:
                    getattr(interaction, method)(key=key)
                    held.pop(key, None)
                except Exception:
                    pass  # Retain for the next recovery attempt; never send a new press.

    def handle_execution_error(self, error):
        self._release_combat_inputs()
        if not self.enabled:
            return True  # A manual stop that raced with the exception takes precedence.
        signature = (type(error).__name__, str(error))
        if not self.manual_keep_enabled:
            self._auto_disabled = True
            logger.warning(f'auto combat automatic disable: {signature}')
            return False  # Preserve the executor's normal error/notification path.
        self._error_count += 1
        delay = min(30, 2 ** min(self._error_count, 5))
        now = time.monotonic()
        self._retry_at = now + delay
        try:
            self.do_reset_to_false()
            self.chars = [None, None, None]
            self.freeze_durations = []
        except Exception:
            self._in_combat = False
        self.info_set('自动战斗保护', f'异常恢复中；第 {self._error_count} 次，{delay} 秒后重新检查')
        self.info_set('最近异常', f'{signature[0]}: {signature[1]}')
        if signature != self._last_error or now - self._last_error_log >= 30:
            logger.error(f'auto combat recovery; retry={self._error_count}, delay={delay}s, '
                         f'merged={self._suppressed_errors}', error)
            self._last_error_log = now
            self._suppressed_errors = 0
        else:
            self._suppressed_errors += 1
        self._last_error = signature
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
            if self._held_keys or self._held_mouse:
                raise RuntimeError('自动战斗仍有未释放输入，等待输入后端恢复')
            result = self._run_combat()
            if result and self._error_count:
                self._error_count = 0
                self.info_set('自动战斗保护', '已恢复；手动保持开启')
                from ok.gui.Communicate import communicate
                communicate.task.emit(self)
            return result
        finally:
            self._release_combat_inputs()

    def _run_combat(self):
        self.warm_up_char_features()
        ret = False
        if not self.scene.in_team(self.in_team_and_world):
            return ret
        self.use_liberation = self.config.get('Use Liberation')
        if not self.use_liberation and not self.in_world():  # 仅大世界生效
            self.use_liberation = True
        combat_start = time.time()
        switched_to_healer = False
        combat_failed = False
        while self.in_combat():
            ret = True
            try:
                if not switched_to_healer:
                    self.switch_healer()
                    switched_to_healer = True
                self.get_current_char().perform()
            except CharDeadException:
                combat_failed = True
                self.log_error(f'Characters dead', notify=True)
                break
            except NotInCombatException as e:
                logger.debug(f'auto_combat_task_out_of_combat {e}')
                break
        if ret:
            if not combat_failed:
                reason = getattr(self, 'out_of_combat_reason', '') or 'combat_state_cleared'
                logger.info(f'combat ended normally duration={int(time.time() - combat_start)}s reason={reason}')
            self.combat_end()
            self.switch_healer()
        return ret

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


from ok import run_task
from config import config

if __name__ == "__main__":
    run_task(config, task=AutoCombatTask, debug=True)
