import ast
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from gameframe.api import Cancelled, Frame, TaskContext
from src.runtime.game_runtime_errors import FrameUnavailable
from src.runtime.native_combat_executor import NativeCombatExecutor, SessionPreempted


class Stopped(Exception):
    pass


class MemoryDevice:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.actions = []
        self.held = set()
        self.releases = 0
        self.cursor = (0, 0)

    def get_cursor_pos(self):
        return self.cursor

    def set_cursor_pos(self, position):
        self.cursor = position

    def next_frame(self, timeout=1):
        return next(self.frames, None)

    def submit(self, action):
        self.actions.append(action)
        if action.kind == 'move_client':
            self.cursor = (action.values['x'], action.values['y'])
        if action.kind.endswith('_down'):
            identity = (action.kind.split('_')[0], next(iter(action.values.values())))
            self.held.add(identity)
        elif action.kind.endswith('_up'):
            identity = (action.kind.split('_')[0], next(iter(action.values.values())))
            self.held.discard(identity)

    def release_all(self):
        self.releases += 1
        self.held.clear()


def production_method(path, class_name, name, globals_):
    """Execute the unchanged production method without importing its application."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, 'exec'), globals_)
    return globals_[name]


class TestNativeCombatExecutor(unittest.TestCase):
    def test_session_preemption_bypasses_business_exception_recovery(self):
        executor, _ = self.make_executor()
        def preempt():
            raise SessionPreempted()
        executor.session_checkpoint = preempt
        recovery = Mock()
        with self.assertRaises(SessionPreempted):
            try:
                executor.check_enabled()
            except Exception:
                recovery()
        recovery.assert_not_called()

    def test_raw_identity_ocr_uses_explicit_engine(self):
        from src.task.account_feature_verification import read_code
        executor, _ = self.make_executor()
        executor.config = {'ocr': {'lib': 'onnxocr'}}
        executor.ocr_engine = SimpleNamespace(ocr=Mock(return_value=[[
            ([[0, 0], [20, 0], [20, 10], [0, 10]], ('特征码：12345', .98))]]))
        with patch('src.task.account_feature_verification.region', return_value=(0, 0, 10, 10)):
            self.assertEqual(read_code(SimpleNamespace(executor=executor),
                                       np.zeros((20, 30, 3), dtype=np.uint8)), '12345')
        self.assertEqual(executor.ocr_engine.ocr.call_args.args[0].shape, (30, 30, 3))
        with self.assertRaisesRegex(ValueError, 'no OCR engine named'):
            executor.ocr_lib('other')

    def test_explicit_key_activation_uses_actual_device_action(self):
        executor, device = self.make_executor()
        executor.send_key_down('e', activate=False)
        executor.send_key_up('e')
        executor.send_key_down('q', activate=True)
        executor.send_key_up('q')
        self.assertEqual([action.kind for action in device.actions],
                         ['key_down', 'key_up', 'activate', 'key_down', 'key_up'])

    def test_pause_releases_held_key_then_resume_can_send_next_key(self):
        executor, device = self.make_executor()
        executor.send_key_down('w')
        self.assertTrue(device.held)
        executor.pause()
        self.assertFalse(device.held)
        self.assertEqual(device.releases, 1)
        executor.check_enabled(check_pause=False)
        self.assertEqual(device.releases, 1)
        executor.unpause()
        executor.send_key('e', 0)
        self.assertEqual([action.values['key'] for action in device.actions], ['w', 'e', 'e'])
        executor.exit_event.set()
        with self.assertRaises(Stopped):
            executor.send_key('f', 0)

    def test_foreground_pause_retains_call_stack_until_resume(self):
        executor, device = self.make_executor()
        executor.wait_on_pause = True
        executor.pause()
        completed = threading.Event()
        worker = threading.Thread(target=lambda: (executor.send_key('f', 0), completed.set()))
        worker.start()
        self.assertFalse(completed.wait(.05))
        self.assertFalse(device.actions)
        executor.unpause()
        worker.join(1)
        self.assertTrue(completed.is_set())
        self.assertEqual([action.kind for action in device.actions], ['key_down', 'key_up'])

    def test_foreground_pause_remains_interruptible_by_stop(self):
        executor, device = self.make_executor()
        executor.wait_on_pause = True
        executor.pause()
        errors = []
        def work():
            try:
                executor.send_key('f', 0)
            except Stopped as error:
                errors.append(error)
        worker = threading.Thread(target=work)
        worker.start()
        executor.exit_event.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertFalse(device.actions)

    def make_executor(self, sizes=((12, 20), (24, 40)), **kwargs):
        frames = [Frame(i, np.full((h, w, 3), i, dtype=np.uint8), time.monotonic_ns())
                  for i, (h, w) in enumerate(sizes, 1)]
        device = MemoryDevice(frames)
        context = TaskContext(device, {}, Path('.'), threading.Event(), 'test', Mock())
        executor = NativeCombatExecutor(context, stop_exception=Stopped, **kwargs)
        return executor, device

    def test_frame_cache_invalidation_geometry_and_capture_loss(self):
        scene = SimpleNamespace(reset=Mock())
        executor, _ = self.make_executor(scene=scene)
        first = executor.frame
        self.assertIs(executor.frame, first)
        self.assertIs(executor.nullable_frame(), first)
        self.assertEqual((executor.width, executor.height), (20, 12))
        executor.send_key_down('space')
        self.assertIsNone(executor.nullable_frame())
        second = executor.frame
        self.assertEqual(int(second[0, 0, 0]), 2)
        self.assertEqual((executor.width, executor.height), (40, 24))
        with self.assertRaises(FrameUnavailable):
            executor.next_frame(time_out=0)
        self.assertIsNone(executor.nullable_frame())
        self.assertFalse(executor.connected)
        self.assertGreaterEqual(scene.reset.call_count, 3)

    def test_sleep_hook_propagates_failure_and_resets_hook_state(self):
        executor, _ = self.make_executor()
        task = SimpleNamespace(_enabled=True, sleep_check_interval=.4,
                               last_sleep_check_time=0, in_sleep_check=False,
                               sleep_check=Mock(side_effect=ValueError('battle lost')))
        executor.current_task = task
        with self.assertRaisesRegex(ValueError, 'battle lost'):
            executor.sleep(1)
        self.assertFalse(task.in_sleep_check)
        self.assertGreater(task.last_sleep_check_time, 0)
        task.sleep_check.assert_called_once()

    def test_stop_during_capture_does_not_return_frame(self):
        executor, device = self.make_executor()
        original = device.next_frame
        def capture(timeout):
            result = original(timeout)
            executor.exit_event.set()
            return result
        device.next_frame = capture
        with self.assertRaises(Stopped):
            executor.next_frame()
        self.assertIsNone(executor.nullable_frame())

    def test_context_cancellation_is_translated_and_release_allowed(self):
        executor, device = self.make_executor()
        executor.send_key_down('lshift')
        executor.context.act = Mock(side_effect=Cancelled('stop raced'))
        with self.assertRaisesRegex(Stopped, 'stop raced'):
            executor.send_key_down('space')
        executor.exit_event.set()
        executor.send_key_up('lshift')
        self.assertFalse(device.held)
        with self.assertRaises(Stopped):
            executor.mouse_down()
        self.assertEqual(device.releases, 0)

    def test_production_heavy_attack_sends_real_device_actions(self):
        executor, device = self.make_executor()
        task = SimpleNamespace(mouse_down=executor.mouse_down, mouse_up=executor.mouse_up)
        character = SimpleNamespace(task=task, check_combat=Mock(), logger=Mock(), sleep=executor.sleep)
        method = production_method('src/char/BaseChar.py', 'BaseChar', 'heavy_attack', {})
        method(character, duration=.001)
        self.assertEqual([a.kind for a in device.actions], ['button_down', 'button_up'])
        self.assertFalse(device.held)
        character.check_combat.assert_called_once()

    def test_stop_during_held_key_sleep_unwinds_release(self):
        executor, device = self.make_executor()
        executor.context.sleep = Mock(side_effect=Cancelled('sleep stopped'))
        with self.assertRaisesRegex(Stopped, 'sleep stopped'):
            executor.send_key('space', down_time=1)
        self.assertEqual([action.kind for action in device.actions], ['key_down', 'key_up'])
        self.assertFalse(device.held)
        self.assertEqual(device.releases, 0)

    def test_pause_preserves_task_intent_and_allows_input_release(self):
        pause = threading.Event()
        executor, device = self.make_executor(pause=pause)
        task = SimpleNamespace(_enabled=True)
        executor.current_task = task
        executor.send_key_down('w')
        pause.set()
        with self.assertRaises(Stopped):
            executor.frame
        executor.send_key_up('w')
        self.assertTrue(task._enabled)
        self.assertFalse(device.held)
        pause.clear()
        self.assertEqual(executor.frame.shape[:2], (12, 20))

    def test_production_recovery_catch_does_not_consume_stop(self):
        executor, _ = self.make_executor()
        executor.exit_event.set()
        names = ('TaskDisabledException', 'FinishedException', 'CombatFlowInterrupt',
                 'NotInCombatException', 'ConfigIntegrityBlocked', 'ConfigWriteBlocked')
        globals_ = {name: type(name, (Exception,), {}) for name in names}
        globals_['TaskDisabledException'] = Stopped
        method = production_method('src/task/BaseCombatTask.py', 'BaseCombatTask',
                                   'combat_is_active', globals_)
        task = SimpleNamespace(in_combat=executor.check_enabled,
                               record_combat_error=Mock(), _release_combat_inputs=Mock(),
                               _wait_combat_recovery=Mock())
        with self.assertRaises(Stopped):
            method(task)
        task.record_combat_error.assert_not_called()
        task._wait_combat_recovery.assert_not_called()

    def test_wait_condition_preserves_results_and_post_action_order(self):
        executor, _ = self.make_executor()
        seen = []
        marker = object()
        def condition():
            seen.append(('condition', int(executor.frame[0, 0, 0])))
            return marker if executor.frame[0, 0, 0] == 2 else None
        result = executor.wait_condition(condition, pre_action=lambda: seen.append('pre'),
                                         post_action=lambda: seen.append('post'))
        self.assertIs(result, marker)
        self.assertEqual(seen, ['pre', ('condition', 1), 'post', 'pre', ('condition', 2)])

    def test_legacy_click_movement_flags_have_explicit_semantics(self):
        executor, device = self.make_executor()
        executor.click(10, 20, move=False, down_time=0)
        self.assertEqual([action.kind for action in device.actions], ['move_client', 'button_down', 'button_up'])
        device.actions.clear()
        executor.click(10, 20, move=True, down_time=0)
        self.assertEqual([action.kind for action in device.actions],
                         ['move_client', 'button_down', 'button_up'])
        device.actions.clear()
        device.cursor = (90, 100)
        executor.click(10, 20, move_back=True, down_time=0)
        self.assertEqual(device.cursor, (90, 100))

    def test_stop_during_inflight_capture_releases_held_input_at_owner(self):
        executor, device = self.make_executor()
        executor.send_key_down('w')
        entered_capture = threading.Event()
        budgets = []
        def waiting_capture(timeout):
            budgets.append(timeout)
            entered_capture.set()
            time.sleep(timeout)
            return None
        device.next_frame = waiting_capture
        def stop_when_capture_starts():
            entered_capture.wait(1)
            executor.exit_event.set()
        stopper = threading.Thread(target=stop_when_capture_starts)
        stopper.start()
        started = time.monotonic()
        try:
            with self.assertRaises(Stopped):
                executor.next_frame(time_out=6)
        finally:
            device.release_all()
            stopper.join(1)
        self.assertLess(time.monotonic() - started, 1)
        self.assertLessEqual(max(budgets), .1)
        self.assertFalse(device.held)
        self.assertEqual(device.releases, 1)


if __name__ == '__main__':
    unittest.main()
