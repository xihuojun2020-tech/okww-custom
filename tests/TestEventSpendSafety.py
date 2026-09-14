import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ok import TaskDisabledException
from src.task.EventTask import EventTask

class TestEventSpendSafety(unittest.TestCase):
    def task(self, values):
        task=EventTask.__new__(EventTask);task.config={}
        task._executor=SimpleNamespace(check_enabled=Mock())
        task.next_frame=Mock(); task._guard_account_input=Mock()
        task._detect_page=Mock(return_value='shop')
        values=iter(values)
        task._read_currency=Mock(side_effect=lambda *a,**kw:next(values,None))
        self.clock=[0.]
        task.sleep=lambda dt:self.clock.__setitem__(0,self.clock[0]+dt)
        timer=patch('src.task.EventTask.time.monotonic',side_effect=lambda:self.clock[0]);timer.start();self.addCleanup(timer.stop)
        self.action=Mock()
        return task

    def spend(self,task,cost=20,reader=lambda:20):
        return task._spend_once('shop',cost,100,self.action,price_reader=reader)

    def test_confirmed_debit_allows_next_operation(self):
        task=self.task([100,100,80,80])
        self.assertEqual(self.spend(task),80)
        self.action.assert_called_once();self.assertFalse(task._event_spend_pending)

    def test_missing_or_unchanged_result_never_submits_twice(self):
        for values in ([100]+[100]*30,[100]+[None]*30):
            task=self.task(values)
            with self.assertRaisesRegex(RuntimeError,'结果未确认'):self.spend(task)
            with self.assertRaisesRegex(RuntimeError,'上笔'):self.spend(task)
            self.action.assert_called_once()

    def test_unknown_or_zero_price_no_input(self):
        for cost in (None,0,-1,101):
            task=self.task([100])
            with self.assertRaises(RuntimeError):self.spend(task,cost)
            self.action.assert_not_called()

    def test_changed_balance_or_price_stops_before_input(self):
        for values,reader in (([90],lambda:20),([100],lambda:25)):
            task=self.task(values)
            with self.assertRaises(RuntimeError):self.spend(task,reader=reader)
            self.action.assert_not_called()

    def test_changed_page_stops_before_input(self):
        task=self.task([100]);task._detect_page.return_value='arena'
        with self.assertRaises(RuntimeError):self.spend(task)
        self.action.assert_not_called()

    def test_uncertain_dispatch_remains_pending(self):
        task=self.task([100]);self.action.side_effect=OSError('dispatch')
        with self.assertRaises(OSError):self.spend(task)
        self.assertTrue(task._event_spend_pending)
        self.action.assert_called_once()

    def test_stop_is_propagated_without_replay(self):
        task=self.task([100]);self.action.side_effect=TaskDisabledException('stop')
        with self.assertRaises(TaskDisabledException):self.spend(task)
        self.action.assert_called_once()

    def test_unknown_page_is_not_reward_selection_success(self):
        task=self.task([]);task._detect_page.return_value='unknown'
        self.assertFalse(task._wait_for_page_change('reward',time_out=1))

    def test_reward_selection_is_single_submission(self):
        task=self.task([]);task._detect_page.return_value='reward'
        task._find_recommended_card=Mock(return_value=1)
        task._click_select=Mock();task._wait_for_page_change=Mock(return_value=False)
        self.assertFalse(task._select_and_confirm(1))
        task._click_select.assert_called_once_with(1)

    def test_new_task_reuses_unconfirmed_persistent_lock(self):
        task=self.task([100]);self.action.side_effect=OSError('uncertain')
        with self.assertRaises(OSError):self.spend(task)
        saved=dict(task.config)
        restarted=self.task([100]);restarted.config=saved
        with self.assertRaisesRegex(RuntimeError,'上笔'):self.spend(restarted)
        self.action.assert_not_called()

    def test_lock_already_set_never_toggles(self):
        task=self.task([]);task.require_game_frame=Mock();task._is_locked=Mock(return_value=True)
        task._click_lock=Mock();task._ensure_shop_locked(0);task._click_lock.assert_not_called()

    def test_uncertain_lock_is_not_toggled_again(self):
        task=self.task([]);task.require_game_frame=Mock();task._is_locked=Mock(return_value=False)
        task._has_recommend_at=Mock(return_value=True);task._click_lock=Mock()
        with self.assertRaisesRegex(RuntimeError,'锁定结果未确认'):task._ensure_shop_locked(0)
        task._click_lock.assert_called_once_with(0)


    def test_silent_config_write_failure_blocks_dispatch(self):
        import tempfile
        from pathlib import Path
        class SilentConfig(dict):pass
        task=self.task([100])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'event.json';path.write_text('{}',encoding='utf-8')
            task.config=SilentConfig();task.config.config_file=path
            with self.assertRaisesRegex(RuntimeError,'保护未成功保存'):self.spend(task)
        self.action.assert_not_called()

    def test_real_config_persists_before_uncertain_dispatch(self):
        import tempfile,json
        from pathlib import Path
        from ok.util.config import Config
        task=self.task([100]);self.action.side_effect=OSError('uncertain')
        with tempfile.TemporaryDirectory() as directory:
            task.config=Config('event',{'_pending_event_spend':{}},folder=directory)
            with self.assertRaises(OSError):self.spend(task)
            saved=json.loads(Path(task.config.config_file).read_text(encoding='utf-8'))
            self.assertEqual(saved['_pending_event_spend']['cost'],20)
            restarted=Config('event',{'_pending_event_spend':{}},folder=directory)
            self.assertEqual(restarted['_pending_event_spend'],saved['_pending_event_spend'])


if __name__=='__main__':unittest.main()
