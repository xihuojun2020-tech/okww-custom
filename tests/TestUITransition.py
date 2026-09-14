"""Fault injection for bounded navigation; no game or GUI required."""
import unittest
from src.task.ui_transition import (Observation, PageState as S, Policy, Transition,
    TransitionContextChanged, TransitionTimeout, present, run_transition)


class TestUITransition(unittest.TestCase):
    def drive(self, observe, *, action=None, guard=lambda: None, notify=None, token=None, **kwargs):
        clock = [0.]
        actions = []
        sequence = [0]
        def capture():
            sequence[0] += 1
            return clock[0], token if token is not None else sequence[0]
        def act(value):
            actions.append(clock[0])
            if action:
                action(value)
        self.actions = actions
        self.clock = clock
        return run_transition(capture, lambda frame: observe(clock[0], len(actions)), act, guard,
            clock=lambda: clock[0], pause=lambda dt: clock.__setitem__(0, clock[0]+dt), notify=notify, **kwargs)

    def test_lost_first_input_recovers_after_fresh_stability(self):
        _, machine = self.drive(lambda t,n: Observation(S.TARGET if n == 2 else S.SOURCE, 'stage', (.8,.9)))
        self.assertEqual(machine.attempts, 2)
        self.assertGreaterEqual(self.actions[1]-self.actions[0], 3)

    def test_loading_then_delayed_target_never_reclicks(self):
        self.drive(lambda t,n: Observation(S.TARGET if t > 6 else S.LOADING if n else S.SOURCE, 'stage'))
        self.assertEqual(len(self.actions), 1)

    def test_already_target_zero_input(self):
        self.drive(lambda t,n: Observation(S.TARGET))
        self.assertEqual(self.actions, [])

    def test_duplicate_capture_cannot_accumulate_stability(self):
        with self.assertRaises(TransitionTimeout):
            self.drive(lambda t,n: Observation(S.SOURCE), token=1, policy=Policy(timeout=2))
        self.assertEqual(self.actions, [])

    def test_unknown_page_never_clicks(self):
        with self.assertRaises(TransitionTimeout):
            self.drive(lambda t,n: Observation(S.UNKNOWN), policy=Policy(timeout=1))
        self.assertEqual(self.actions, [])

    def test_max_three_inputs(self):
        with self.assertRaises(TransitionTimeout):
            self.drive(lambda t,n: Observation(S.SOURCE))
        self.assertEqual(len(self.actions), 3)

    def test_shared_deadline_not_restarted(self):
        with self.assertRaises(TransitionTimeout):
            self.drive(lambda t,n: Observation(S.SOURCE), deadline=.6)
        self.assertLessEqual(self.clock[0], .6)
        self.assertEqual(self.actions, [])

    def test_identity_changes_stop_even_before_first_input(self):
        with self.assertRaises(TransitionContextChanged):
            self.drive(lambda t,n: Observation(S.SOURCE, 'A' if t == 0 else 'B'))
        self.assertEqual(self.actions, [])

    def test_invalid_coordinates_stop(self):
        for point in ((1.1,.5), (float('nan'),.5)):
            with self.subTest(point=point), self.assertRaises(TransitionContextChanged):
                self.drive(lambda t,n: Observation(S.SOURCE, point=point))
            self.assertEqual(self.actions, [])

    def test_drifting_button_never_clicks(self):
        with self.assertRaises(TransitionTimeout):
            self.drive(lambda t,n: Observation(S.SOURCE, point=(.1+t*.02,.5)), policy=Policy(timeout=2))
        self.assertEqual(self.actions, [])

    def test_dispatch_error_never_replayed(self):
        def fail(_): raise OSError('dispatch uncertain')
        with self.assertRaisesRegex(OSError, 'uncertain'):
            self.drive(lambda t,n: Observation(S.SOURCE), action=fail)
        self.assertEqual(len(self.actions), 1)

    def test_diagnostic_failure_is_best_effort(self):
        def fail(*_): raise OSError('disk offline')
        self.drive(lambda t,n: Observation(S.TARGET if n else S.SOURCE), notify=fail)
        self.assertEqual(len(self.actions), 1)

    def test_guard_cancel_before_input(self):
        def cancel():
            if self.clock[0] >= .7: raise InterruptedError('stop')
        with self.assertRaises(InterruptedError):
            self.drive(lambda t,n: Observation(S.SOURCE), guard=cancel)
        self.assertEqual(self.actions, [])

    def test_cancel_in_diagnostic_is_not_swallowed(self):
        def cancel(*_): raise InterruptedError('stop')
        with self.assertRaises(InterruptedError):
            self.drive(lambda t,n: Observation(S.SOURCE), notify=cancel, cancel_errors=(InterruptedError,))
        self.assertEqual(self.actions, [])

    def test_predicate_values(self):
        for value in (None, False, 0, [], ''):
            self.assertFalse(present(value))
        self.assertTrue(present(object()))
        class Image: shape = (1080,1920,3)
        with self.assertRaises(TypeError): present(Image())

    def test_tick_is_nonblocking_and_requires_submission(self):
        machine = Transition(Policy(stable_samples=1), 0)
        self.assertEqual(machine.tick(Observation(S.SOURCE), 1, 0), 'act')
        machine.submitted(0)
        self.assertEqual(machine.tick(Observation(S.SOURCE), 2, 1), 'wait')
        self.assertEqual(machine.tick(Observation(S.TARGET), 3, 2), 'done')


if __name__ == '__main__': unittest.main()
