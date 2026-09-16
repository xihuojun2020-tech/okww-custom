import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
from ok import TaskDisabledException
from src.task.ResonanceSimulationTask import ResonanceSimulationTask
from src.task.resonance_simulation import *


class TestResonanceSimulation(unittest.TestCase):
    def test_rules_and_scopes(self):
        self.assertEqual(rules_from_text('奖励 | 共鸣因子\n藏宝地'),[('奖励','共鸣因子'),('通用','藏宝地')])
        for text in ('','下一关|','错|藏宝地','a|b|c','一'):
            with self.subTest(text=text),self.assertRaises(ValueError):rules_from_text(text)

    def test_directions_use_feet_not_screen_center(self):
        self.assertEqual(movement((.51,.53)),('w',))
        self.assertEqual(movement((.8,.4)),('d','w'))
        self.assertEqual(movement((.2,.8)),('a','s'))
        self.assertEqual(movement((.52,.59)),())

    def test_new_object_at_same_location_requires_new_frames(self):
        tracker=Tracker();a=Target('object','行动资金',(.6,.5));b=Target('object','战斗区域',(.6,.5))
        self.assertIsNone(tracker.update(a,1))
        self.assertIsNone(tracker.update(a,1))
        self.assertEqual(tracker.update(a,2),a)
        self.assertIsNone(tracker.update(b,3))
        self.assertEqual(tracker.update(b,4),b)
        self.assertIsNone(tracker.update(None,5))
        self.assertIsNone(tracker.update(a,6))

    def test_priority_and_tracking(self):
        near=Target('object','战斗区域',(.52,.57),3)
        far=Target('object','行动资金',(.8,.4),0)
        self.assertEqual(choose([near,far],near),far)
        a=Target('enemy','敌人',(.7,.4));b=Target('enemy','敌人',(.6,.55))
        self.assertEqual(choose([a,b],a),a)

    def task(self):
        task=ResonanceSimulationTask.__new__(ResonanceSimulationTask)
        task._held_keys=set();task._held_mouse=set();task._duration=.05
        task._executor=SimpleNamespace(interaction=Mock())
        task._input_ready=Mock(return_value=True)
        return task

    def test_partial_key_failure_releases_all_attempted_keys(self):
        task=self.task();interaction=task.executor.interaction
        interaction.send_key_down.side_effect=[None,RuntimeError('backend')]
        with self.assertRaises(RuntimeError):task._pulse(('w','d'),True)
        self.assertEqual({c.args[0] for c in interaction.send_key_up.call_args_list},{'w','d'})
        self.assertFalse(task._held_keys)

    def test_focus_or_pause_releases_before_waiting(self):
        task=self.task();task._input_ready.side_effect=[True,True,True,False]
        task._pulse(('w',),True)
        task.executor.interaction.send_key_up.assert_called_once_with('w')
        task.executor.interaction.mouse_up.assert_called_once_with(key='left')

    def test_stop_during_pulse_releases_input(self):
        task=self.task();task._input_ready.side_effect=[True,True,True,TaskDisabledException()]
        with self.assertRaises(TaskDisabledException):task._pulse(('w',),True)
        task.executor.interaction.send_key_up.assert_called_once_with('w')
        task.executor.interaction.mouse_up.assert_called_once_with(key='left')

    def test_cleanup_attempts_remaining_keys_if_release_fails(self):
        task=self.task();task._held_keys={'w','d'};task._held_mouse={'left'}
        task.executor.interaction.send_key_up.side_effect=RuntimeError('release')
        with self.assertRaises(RuntimeError):task._release()
        self.assertEqual(task.executor.interaction.send_key_up.call_count,2)
        task.executor.interaction.mouse_up.assert_called_once()

    def test_stuck_navigation_is_bounded(self):
        task=self.task();task._feet=(.51,.58);task._stall=3;task._progress_id=None
        task._best_distance=10;task._recoveries=0
        target=Target('object','藏宝地',(.8,.6))
        self.assertIsNone(task._progress(target,0))
        self.assertEqual(task._progress(target,3),'break')
        self.assertEqual(task._progress(target,6),'sidestep')
        with self.assertRaises(RuntimeError):task._progress(target,9)

    def test_run_rechecks_replacement_and_never_moves_on_unknown_page(self):
        from itertools import count
        task=self.task()
        defaults=ResonanceSimulationTask(executor=Mock(scene=None),app=None).default_config
        task.config=dict(defaults);task.info_set=Mock();task.sleep=Mock();task._pulse=Mock()
        task.executor.check_enabled=Mock();task.next_frame=Mock()
        task.executor._last_frame_time=None
        frame=cv2.imread('tests/fixtures/resonance_simulation/portal.png')
        task.require_game_frame=Mock(side_effect=[frame.copy() for _ in range(7)]+[TaskDisabledException()])
        a=Target('object','行动资金',(.8,.5),0)
        b=Target('object','战斗区域',(.8,.5),3)
        task._phase=Mock(return_value='下一关')
        task._objects=Mock(side_effect=[[a],[a],[b],[b],[],[b]])
        with patch('src.task.ResonanceSimulationTask.time.monotonic',side_effect=count()), \
                patch('src.task.ResonanceSimulationTask.scene_visible',side_effect=[True]*4+[False]+[True]*2), \
                patch('src.task.ResonanceSimulationTask.markers',return_value=[]):
            with self.assertRaises(TaskDisabledException):task.run()
        # One pulse for each confirmed object; never on the first/replaced/missing frame.
        self.assertEqual(task._pulse.call_count,2)

    def test_real_input_guard_rejects_pause_background_and_exit(self):
        task=self.task();del task._input_ready
        task._guard_account_input=Mock();task._foreground=Mock(return_value=True)
        task.executor.check_enabled=Mock();task.executor.paused=False
        task.executor.exit_event=Mock(is_set=Mock(return_value=False))
        self.assertTrue(task._input_ready())
        task.executor.paused=True
        self.assertFalse(task._input_ready())
        task.executor.paused=False;task._foreground.return_value=False
        self.assertFalse(task._input_ready())
        task._foreground.return_value=True;task.executor.exit_event.is_set.return_value=True
        self.assertFalse(task._input_ready())

    def test_phase_exact_matching_and_hud_text_rejection(self):
        frame=cv2.imread('tests/fixtures/resonance_simulation/portal.png')
        box=SimpleNamespace(name='战斗区域',x=938,y=98,width=80,height=23,confidence=.99)
        rules=[('下一关','战斗')]
        self.assertEqual(text_targets(frame,[box],rules,'奖励'),[])
        self.assertEqual(text_targets(frame,[box],rules,'下一关',exact=True),[])
        self.assertEqual(len(text_targets(frame,[box],rules,'下一关')),1)
        box.x=25;box.y=184
        self.assertEqual(text_targets(frame,[box],rules,'下一关'),[])

    def test_negative_menus_are_not_activity_scenes(self):
        for name in ('initial','event','formation'):
            frame=cv2.imread('tests/fixtures/echoes_remain/'+name+'.png')
            self.assertFalse(scene_visible(frame))

    def test_low_health_target_is_tracked_but_red_specks_do_not_start_combat(self):
        image=np.zeros((720,1280,3),np.uint8)
        image[200:204,600:608]=(65,70,205)
        self.assertFalse(blood_bars(image))
        previous=Target('enemy','敌人',(604/1280,242/720),health_width=60)
        self.assertEqual(len(blood_bars(image,previous)),1)

    def test_damage_counts_as_combat_progress(self):
        task=self.task();task._feet=(.51,.58);task._stall=3;task._progress_id=None
        task._best_distance=10;task._recoveries=0
        for at,width in ((0,60),(4,55),(8,50),(12,45)):
            self.assertIsNone(task._progress(Target('enemy','敌人',(.51,.58),health_width=width),at))

    def test_registered_without_placeholder_and_not_normal_combat(self):
        from config import config
        from src.gui.activity_catalog import PLACEHOLDERS
        from src.task.BaseCombatTask import BaseCombatTask
        self.assertIn(['src.task.ResonanceSimulationTask','ResonanceSimulationTask'],config['onetime_tasks'])
        self.assertFalse(any(p=='resonance_simulation' for p,_ in PLACEHOLDERS))
        self.assertFalse(issubclass(ResonanceSimulationTask,BaseCombatTask))

    def test_user_images_and_resolution_scaling(self):
        root=Path('tests/fixtures/resonance_simulation')
        for height in (720,1080,1440):
            for p in root.glob('*.png'):
                with self.subTest(height=height,name=p.stem):
                    f=cv2.resize(cv2.imread(str(p)),(height*16//9,height))
                    self.assertTrue(scene_visible(f))
                    image=resized(f)
                    self.assertEqual(bool(blood_bars(image)),p.stem=='combat')
                    if p.stem in ('marker','reward_far','currency'):
                        self.assertTrue(markers(image))
        self.assertFalse(scene_visible(np.zeros((720,1280,3),np.uint8)))


if __name__=='__main__':unittest.main()
