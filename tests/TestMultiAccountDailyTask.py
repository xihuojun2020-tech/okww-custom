import unittest

from src.task.BaseWWTask import LOGIN_TEXTS
from src.task.MultiAccountDailyTask import (
    MultiAccountDailyTask,
    account_pattern,
    normalize_account_name,
)


class AccountBox:
    def __init__(self, name):
        self.name = name


def _fake_login_task(main_texts=None, dialog_texts=None):
    """构造可注入 OCR 文本的假任务（主窗口帧 + #32770 登录对话框帧两路）。

    find_boxes 按文本真实匹配：掩码账号匹配 account_pattern，登录文本匹配 LOGIN_TEXTS。
    """

    class FakeTask:
        def __init__(self):
            self._login_in_dialog = False

        _account_entry_count = MultiAccountDailyTask._account_entry_count

        def ocr(self):
            return [AccountBox(t) for t in (main_texts or [])]

        def find_boxes(self, texts, match):
            result = []
            for t in texts or []:
                name = (t.name or '').strip()
                if match == account_pattern and account_pattern.search(name):
                    result.append(t)
                elif match == LOGIN_TEXTS and name in ('登录', '登入', 'Log'):
                    result.append(t)
            return result

        def _ocr_login_dialog(self):
            if dialog_texts is None:
                return None
            return [AccountBox(t) for t in dialog_texts]

        def log_info(self, *args, **kwargs):
            pass

        def log_warning(self, *args, **kwargs):
            pass

        def log_error(self, *args, **kwargs):
            pass

        def screenshot(self, *args, **kwargs):
            pass

    return FakeTask()


class TestMultiAccountDailyTask(unittest.TestCase):

    def test_account_dropdown_accepts_multiple_login_text_matches(self):
        account_box = object()

        class FakeTask:
            def ocr(self):
                return []

            def find_boxes(self, texts, match):
                if match == account_pattern:
                    return [account_box]
                if match == LOGIN_TEXTS:
                    return [object(), object()]
                return []

        self.assertIs(MultiAccountDailyTask.do_find_account_drop_down(FakeTask()), account_box)

    def test_account_name_normalization_groups_common_ocr_variants(self):
        self.assertEqual(
            normalize_account_name("cc****33@demo.com.hk"),
            normalize_account_name("cc****33@dem0.com.hk"),
        )
        self.assertEqual(
            normalize_account_name("bb****02@example.com"),
            normalize_account_name("bb****02@example.con"),
        )

    def test_click_account_list_selects_visible_third_account_after_first_two_are_done(self):
        class FakeTask:
            def __init__(self):
                self.done_set = {
                    normalize_account_name("aa****01@example.com"),
                    normalize_account_name("bb****02@example.com"),
                }
                self.all_accounts = set()
                self.clicked = []

            _is_done = MultiAccountDailyTask._is_done

            def ocr(self, match=None):
                return [
                    AccountBox("aa****01@example.com"),
                    AccountBox("aa****01@example.com"),
                    AccountBox("bb****02@example.com"),
                    AccountBox("cc****03@example.com.hk"),
                ]

            def info_set(self, *args):
                pass

            def click(self, account, after_sleep=0):
                self.clicked.append(account.name)

            def log_info(self, *args):
                pass

            def tr(self, message):
                return message

        task = FakeTask()

        selected = MultiAccountDailyTask._click_account_in_list(task)

        self.assertEqual(selected, "cc****03@example.com.hk")
        self.assertEqual(task.clicked, ["cc****03@example.com.hk"])

    # ============ v1.03.74：下拉框收起/展开状态判定 ============

    def test_dropdown_ready_collapsed_single_mask_account(self):
        task = _fake_login_task(main_texts=['180****1088', '登录'])
        box = MultiAccountDailyTask.do_find_account_drop_down(task)
        self.assertIsNotNone(box)
        self.assertFalse(task._login_in_dialog)

    def test_dropdown_ready_expanded_multiple_accounts(self):
        # 列表已展开：账号条目 ≥2（掩码 + U 账号），仍视为登录就绪（返回下拉框）
        task = _fake_login_task(main_texts=['153****9621', 'U550500484A', '180****1088', '登入'])
        self.assertIsNotNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_dropdown_not_ready_without_login_text(self):
        task = _fake_login_task(main_texts=['180****1088'])
        self.assertIsNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_dropdown_dialog_fallback_sets_login_in_dialog(self):
        # 主窗口无特征 → 回退 #32770 登录对话框帧（U 扫码账号 + 登录文本）
        task = _fake_login_task(main_texts=[], dialog_texts=['U550500484A', '登录'])
        box = MultiAccountDailyTask.do_find_account_drop_down(task)
        self.assertIsNotNone(box)
        self.assertTrue(task._login_in_dialog)

    def test_dropdown_dialog_not_ready_when_only_launcher_texts(self):
        # 启动器界面（KURO GAMES / 修复，无登录文本无账号）→ 不命中
        task = _fake_login_task(main_texts=['KURO GAMES', '公告', '修复'])
        self.assertIsNone(MultiAccountDailyTask.do_find_account_drop_down(task))

    def test_account_list_expanded_true_with_two_entries(self):
        task = _fake_login_task(main_texts=['153****9621', 'U550500484A', '登入'])
        self.assertTrue(MultiAccountDailyTask._account_list_expanded(task))

    def test_account_list_expanded_false_with_single_entry(self):
        task = _fake_login_task(main_texts=['153****9621', '登入'])
        self.assertFalse(MultiAccountDailyTask._account_list_expanded(task))


if __name__ == "__main__":
    unittest.main()
