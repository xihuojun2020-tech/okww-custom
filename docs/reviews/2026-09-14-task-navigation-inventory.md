# 全任务稳定等待与重试：源码盘点附录

基线：3b75ddf1，2026-09-14，产品 1.70.07。文档生成时以 config.py 实际 AST 注册表和 src/task 下35个 *Task.py 为准。

本附录是定位索引：列出包含点击、按键、等待、滚动等调用的方法。未列方法也可能通过继承/委托产生输入；不把调用名扫描当作完整语义证明。适用性和策略以[设计方案](../references/task-navigation-reliability.md)为准。

统计：18个一次性入口、6个后台入口、5个公共基类文件、6个未注册文件。AutoDialogTask 位于 SkipDialogTask.py，BigMap 与 FarmMapTask 同文件。

本轮只读源码并编写文档，没有运行全任务实机测试，也未审阅诊断 ZIP。

## 文件与方法定位

### AutoAbyssTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/AutoAbyssTask.py)；注册类 `AutoAbyssTask`。

- `AutoAbyssTask._open_period_challenge`，基线行 899：`wait_ocr`, `wait_until`。
- `AutoAbyssTask._open_adversity_tower`，基线行 906：`_wait_content_deep_area`, `_wait_for_tower_screen`, `click_box`, `wait_ocr`。
- `AutoAbyssTask._select_adversity_tower`，基线行 917：`_wait_content_deep_area`, `click_box`, `wait_ocr`。
- `AutoAbyssTask._wait_content_deep_area`，基线行 930：`wait_ocr`。
- `AutoAbyssTask._wait_for_tower_screen`，基线行 941：`wait_until`。
- `AutoAbyssTask._return_from_result`，基线行 945：`click_box`。
- `AutoAbyssTask._open_tower`，基线行 986：`click_relative`, `wait_ocr`。
- `AutoAbyssTask._verify_floor_state`，基线行 1050：`click_relative`, `wait_until`。
- `AutoAbyssTask._click_start_challenge`，基线行 1115：`click_box`, `wait_until`。
- `AutoAbyssTask._prepare_challenge_map`，基线行 1165：`_wait_exact_text_or_fail`, `send_key`, `wait_in_team_and_world`。
- `AutoAbyssTask._wait_abyss_result`，基线行 1187：`wait_until`。
- `AutoAbyssTask._run_combat_and_wait_result`，基线行 1213：`_wait_abyss_result`。
- `AutoAbyssTask._fight_selected_tower`，基线行 1232：`_click_start_challenge`, `_run_combat_and_wait_result`, `_wait_exact_text`, `click_box`。
- `AutoAbyssTask._return_to_towers`，基线行 1282：`_wait_for_tower_screen`, `send_key`。
- `AutoAbyssTask._return_from_team_to_towers`，基线行 1290：`send_key`, `wait_until`。
- `AutoAbyssTask._enter_and_scan_characters`，基线行 1301：`_wait_character_list_page`, `_wait_exact_text`, `_wait_exact_text_or_fail`, `_wait_stable_character_frame`, `click_box`, `click_relative`。
- `AutoAbyssTask._scan_character_pages`，基线行 1342：`_scroll_to_second_character_page`, `_wait_stable_character_frame`, `scroll_relative`。
- `AutoAbyssTask._revisit_energy_page`，基线行 1393：`_wait_stable_character_frame`, `scroll_relative`。
- `AutoAbyssTask._fresh_record_energy`，基线行 1418：`_wait_stable_character_frame`。
- `AutoAbyssTask._wait_exact_text`，基线行 1459：`wait_until`。
- `AutoAbyssTask._wait_exact_text_or_fail`，基线行 1467：`_wait_exact_text`。
- `AutoAbyssTask._wait_character_list_page`，基线行 1474：`_wait_exact_text_or_fail`。
- `AutoAbyssTask._wait_stable_character_frame`，基线行 1478：`wait_until`。
- `AutoAbyssTask._scroll_to_second_character_page`，基线行 1503：`_wait_stable_character_frame`, `scroll_relative`。
- `AutoAbyssTask._show_character_page`，基线行 1527：`_wait_stable_character_frame`, `scroll_relative`。
- `AutoAbyssTask._wait_selection_marker`，基线行 1633：`wait_until`。
- `AutoAbyssTask._click_character_record`，基线行 1665：`_wait_selection_marker`, `click_relative`。
- `AutoAbyssTask._cancel_character_selection`，基线行 1718：`_wait_selection_marker`, `click_relative`。
- `AutoAbyssTask._select_planned_team`，基线行 1766：`_click_character_record`。
- `AutoAbyssTask._finish_team_formation`，基线行 1805：`_wait_exact_text_or_fail`, `click_box`。
- `AutoAbyssTask._recognize_character_screen`，基线行 2025：`_wait_stable_character_frame`。
- `AutoAbyssTask._click_period_challenge_icon`，基线行 2119：`click_relative`。

### AutoCombatTask.py（后台）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/AutoCombatTask.py)；注册类 `AutoCombatTask`。

- `AutoCombatTask.send_key_down`，基线行 111：`send_key_down`。
- `AutoCombatTask.send_key_up`，基线行 116：`send_key_up`。
- `AutoCombatTask.realm_perform`，基线行 232：`click`, `send_key`, `send_key_and_wait_animation`。

### AutoLoginTask.py（后台）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/AutoLoginTask.py)；注册类 `AutoLoginTask`。

- `AutoLoginTask.run`，基线行 17：`wait_login`。

### AutoPickTask.py（后台）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/AutoPickTask.py)；注册类 `AutoPickTask`。

- `AutoPickTask.send_fs`，基线行 23：`send_key`。

### BaseCombatTask.py（公共基类）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/BaseCombatTask.py)。

- `BaseCombatTask.send_key_and_wait_animation`，基线行 143：`send_key`。
- `BaseCombatTask.close_revive_popup`，基线行 220：`click`, `send_key`, `wait_click_feature`。
- `BaseCombatTask.revive_at_tower_and_heal`，基线行 264：`click`, `click_box`, `send_key`, `wait_until`。
- `BaseCombatTask.teleport_to_heal`，基线行 295：`send_key`。
- `BaseCombatTask._travel_to_nearest_waypoint`，基线行 304：`click`, `click_box`, `wait_feature`, `wait_in_team_and_world`。
- `BaseCombatTask.raise_not_in_combat`，基线行 324：`wait_feature`。
- `BaseCombatTask.wait_combat`，基线行 356：`middle_click`。
- `BaseCombatTask.combat_once`，基线行 395：`wait_combat`, `wait_in_team_and_world`。
- `BaseCombatTask.run_in_circle_to_find_echo`，基线行 425：`send_key_and_wait_f`。
- `BaseCombatTask.switch_next_char`，基线行 608：`_wait_switch_team`, `click`, `send_key`, `wait_switch`。

### BaseWWTask.py（公共基类）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/BaseWWTask.py)。

- `BaseWWTask.zoom_map`，基线行 141：`click_relative`, `send_key`。
- `BaseWWTask.find_f_with_text`，基线行 200：`scroll_relative`。
- `BaseWWTask._walk_direction`，基线行 275：`send_key_down`。
- `BaseWWTask._stop_last_direction`，基线行 282：`send_key_up`。
- `BaseWWTask.do_walk_to_box`，基线行 297：`send_key`, `send_key_down`, `send_key_up`, `wait_until`。
- `BaseWWTask.click`，基线行 426：`click`。
- `BaseWWTask.send_key`，基线行 458：`send_key`。
- `BaseWWTask.send_key_down`，基线行 462：`send_key_down`。
- `BaseWWTask.scroll`，基线行 470：`scroll`。
- `BaseWWTask.check_for_monthly_card`，基线行 474：`wait_until`。
- `BaseWWTask.walk_until_f`，基线行 505：`middle_click`, `send_key_and_wait_f`。
- `BaseWWTask.get_stamina`，基线行 524：`wait_ocr`。
- `BaseWWTask.use_stamina`，基线行 565：`click`, `click_dialog_left_button`, `click_dialog_right_button`, `wait_feature`。
- `BaseWWTask._confirm_stamina_used`，基线行 707：`wait_until`。
- `BaseWWTask.send_key_and_wait_f`，基线行 731：`send_key_down`, `send_key_up`, `wait_until`。
- `BaseWWTask.run_until`，基线行 755：`middle_click`, `send_key_down`, `send_key_up`。
- `BaseWWTask.handle_claim_button`，基线行 786：`send_key`, `wait_until`。
- `BaseWWTask.pick_echo`，基线行 843：`send_key`。
- `BaseWWTask.pick_f`，基线行 850：`send_key`。
- `BaseWWTask.yolo_find_echo`，基线行 880：`send_key`。
- `BaseWWTask.center_camera`，基线行 914：`click`。
- `BaseWWTask.turn_direction`，基线行 918：`send_key`。
- `BaseWWTask.wait_in_team_and_world`，基线行 944：`wait_until`。
- `BaseWWTask.esc_world_confirm`，基线行 951：`click_dialog_right_button`, `send_key`, `wait_in_team_and_world`。
- `BaseWWTask.click_dialog_right_button`，基线行 957：`click`。
- `BaseWWTask.esc_cancel`，基线行 967：`click_dialog_left_button`, `send_key`, `wait_in_team_and_world`。
- `BaseWWTask.click_dialog_left_button`，基线行 973：`click`。
- `BaseWWTask.ensure_main`，基线行 983：`wait_until`。
- `BaseWWTask.is_main`，基线行 992：`wait_login`。
- `BaseWWTask.wait_login`，基线行 1076：`_click_login_box`。
- `BaseWWTask._stop_movement`，基线行 1190：`send_key_up`。
- `BaseWWTask._navigate_based_on_angle`，基线行 1196：`middle_click`, `send_key_down`, `send_key_up`, `wait_until`。
- `BaseWWTask.handle_monthly_card`，基线行 1315：`click_relative`, `wait_until`。
- `BaseWWTask.open_esc_menu`，基线行 1343：`click_relative`, `send_key_down`, `send_key_up`。
- `BaseWWTask.open_boss_book`，基线行 1350：`click_relative`。
- `BaseWWTask.openF2Book`，基线行 1373：`click_box`, `click_relative`, `send_key`, `send_key_down`, `send_key_up`, `wait_book`。
- `BaseWWTask.click_traval_button`，基线行 1398：`click`, `click_confirm`, `wait_click_skip_dialog_confirm`, `wait_feature`。
- `BaseWWTask.click_confirm`，基线行 1419：`wait_click_feature`。
- `BaseWWTask.click_skip_dialog_confirm`，基线行 1426：`click`。
- `BaseWWTask.wait_click_skip_dialog_confirm`，基线行 1465：`wait_until`。
- `BaseWWTask.click_team_challenge`，基线行 1472：`wait_click_feature`, `wait_click_skip_dialog_confirm`。
- `BaseWWTask.wait_click_travel`，基线行 1476：`wait_until`。
- `BaseWWTask.wait_book`，基线行 1479：`wait_until`。
- `BaseWWTask.check_main`，基线行 1489：`click_relative`, `send_key`。
- `BaseWWTask.click_on_book_target`，基线行 1511：`_find_book_scroll_top`, `click`, `wait_feature`。
- `BaseWWTask.change_time_to_night`，基线行 1574：`click_relative`, `send_key`。
- `BaseWWTask.jump`，基线行 1595：`send_key`。

### ChangeEchoTask.py（未注册/隐藏）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/ChangeEchoTask.py)。

- `ChangeEchoTask.run`，基线行 44：`click`, `wait_click_ocr`, `wait_ocr`。
- `ChangeEchoTask.esc`，基线行 92：`send_key`。

### CharacterTrialTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/CharacterTrialTask.py)；注册类 `CharacterTrialTask`。

- `CharacterTrialTask.click`，基线行 82：`click`。
- `CharacterTrialTask.send_key`，基线行 86：`send_key`。
- `CharacterTrialTask.send_key_down`，基线行 90：`send_key_down`。
- `CharacterTrialTask.send_key_up`，基线行 95：`send_key_up`。
- `CharacterTrialTask._release`，基线行 110：`send_key_up`。
- `CharacterTrialTask._click_button`，基线行 142：`click`。
- `CharacterTrialTask._open`，基线行 178：`scroll_relative`, `send_key`。
- `CharacterTrialTask._select_activity`，基线行 206：`click`。
- `CharacterTrialTask._select`，基线行 255：`_drag_strip`, `click`。
- `CharacterTrialTask._claim`，基线行 274：`_click_button`, `click`。
- `CharacterTrialTask._enter`，基线行 299：`_wait_trial_map`, `click`。
- `CharacterTrialTask._wait_trial_map`，基线行 312：`send_key`。
- `CharacterTrialTask._start`，基线行 339：`send_key`, `send_key_down`。
- `CharacterTrialTask._leave`，基线行 446：`send_key`。
- `CharacterTrialTask._confirm_trial_exit`，基线行 457：`click`。

### DailyTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/DailyTask.py)；注册类 `DailyTask`。

- `DailyTask._open_record_page`，基线行 1979：`click`, `click_relative`, `send_key`, `send_key_down`, `send_key_up`, `wait_ocr`。
- `DailyTask.claim_battle_pass`，基线行 2009：`click`, `click_relative`, `send_key_down`, `send_key_up`, `wait_ocr`。
- `DailyTask.open_daily`，基线行 2034：`click`。
- `DailyTask.claim_daily`，基线行 2098：`click`。
- `DailyTask.claim_mail`，基线行 2119：`click`。

### DiagnosisTask.py（未注册/隐藏）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/DiagnosisTask.py)。

- `DiagnosisTask.choose_level`，基线行 54：`click_relative`, `wait_click_feature`。

### DomainTask.py（公共基类）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/DomainTask.py)。

- `DomainTask.revive_action`，基线行 21：`send_key`, `wait_click_feature`, `wait_in_team_and_world`。
- `DomainTask.make_sure_in_world`，基线行 43：`send_key`, `wait_click_feature`, `wait_in_team_and_world`。
- `DomainTask.farm_in_domain`，基线行 105：`click`, `wait_click_feature`, `wait_feature`, `wait_in_team_and_world`, `wait_until`。

### EchoesRemainTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/EchoesRemainTask.py)；注册类 `EchoesRemainTask`。

- `EchoesRemainTask._click`，基线行 59：`click_relative`。
- `EchoesRemainTask._click_transition`，基线行 82：`_click`。
- `EchoesRemainTask._open_quick`，基线行 140：`_click_transition`。
- `EchoesRemainTask._open_event`，基线行 170：`click`, `scroll_relative`, `send_key`。
- `EchoesRemainTask._navigate`，基线行 210：`_click_transition`。
- `EchoesRemainTask._choose`，基线行 232：`_click`。
- `EchoesRemainTask.run`，基线行 276：`_click`。

### EnhanceEchoTask.py（未注册/隐藏）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/EnhanceEchoTask.py)。

- `EnhanceEchoTask.run`，基线行 59：`click`, `click_skip_dialog_confirm`, `wait_click_ocr`, `wait_ocr`。
- `EnhanceEchoTask.find_add_mat`，基线行 267：`wait_ocr`。
- `EnhanceEchoTask.esc`，基线行 270：`send_key`。
- `EnhanceEchoTask.trash_and_esc`，基线行 276：`send_key`, `wait_ocr`。
- `EnhanceEchoTask.lock_and_esc`，基线行 307：`send_key`, `wait_ocr`。

### EventTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/EventTask.py)；注册类 `EventTask`。

- `EventTask.run`，基线行 145：`_click_restart`, `_wait_for_any`。
- `EventTask._handle_reward_screen`，基线行 346：`send_key`。
- `EventTask._select_and_confirm`，基线行 402：`_click_select`, `_wait_for_page_change`。
- `EventTask._click_select`，基线行 526：`_human_click`。
- `EventTask._handle_shop_screen`，基线行 538：`_click_buy_area`, `_click_lock`, `send_key`。
- `EventTask._handle_confirm_next_wave`，基线行 641：`_click_button_by_text`。
- `EventTask._click_button_by_text`，基线行 659：`_human_click`, `click`。
- `EventTask._click_lock`，基线行 739：`_human_click`。
- `EventTask._click_buy_area`，基线行 749：`_human_click`。
- `EventTask._click_restart`，基线行 864：`click`, `click_relative`。
- `EventTask._circle_strafe`，基线行 878：`send_key_down`, `send_key_up`。
- `EventTask._human_click`，基线行 967：`click_relative`。

### FarmEchoTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/FarmEchoTask.py)；注册类 `FarmEchoTask`。

- `FarmEchoTask.do_run`，基线行 113：`scroll_and_click_buttons`, `send_key`, `wait_click_feature`, `wait_in_team_and_world`, `wait_until`。
- `FarmEchoTask.teleport_to_configured_boss`，基线行 242：`click`, `click_configured_boss_level`, `click_on_book_target`, `click_team_challenge`, `wait_click_travel`, `wait_in_team_and_world`。
- `FarmEchoTask.walk_until_f_or_combat`，基线行 281：`middle_click`, `send_key_down`, `send_key_up`, `wait_until`。
- `FarmEchoTask.enter_configured_boss_realm_from_f`，基线行 307：`click`, `click_configured_boss_level`, `send_key`, `wait_in_team_and_world`, `wait_until`。
- `FarmEchoTask.click_configured_boss_level`，基线行 322：`click_box`, `wait_ocr`。
- `FarmEchoTask.handle_boss_restart_after_treasure`，基线行 334：`scroll_and_click_buttons`。
- `FarmEchoTask.manage_boss_interactions`，基线行 364：`scroll_and_click_buttons`, `send_key`, `wait_click_feature`, `wait_in_team_and_world`, `wait_until`。
- `FarmEchoTask._handle_unnamed_explorer`，基线行 424：`scroll_and_click_buttons`, `wait_until`。
- `FarmEchoTask.teleport_to_nearest_boss`，基线行 504：`click`, `click_box`, `send_key`, `wait_click_travel`, `wait_in_team_and_world`。
- `FarmEchoTask.click_boss_octagon`，基线行 531：`click`。
- `FarmEchoTask.teleport_to_octagon_boss`，基线行 602：`click`, `click_boss_octagon`, `click_box`, `send_key`, `wait_feature`, `wait_in_team_and_world`。
- `FarmEchoTask.scroll_and_click_buttons`，基线行 620：`scroll_relative`, `send_key`。
- `FarmEchoTask.choose_level`，基线行 639：`click_relative`, `wait_click_feature`。

### FarmMapTask.py（未注册/隐藏）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/FarmMapTask.py)。

- `BigMap.load_stars`，基线行 30：`click_relative`, `send_key`, `wait_in_team_and_world`。
- `FarmMapTask.go_to_star`，基线行 176：`middle_click`, `send_key`。

### FastTravelTask.py（后台）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/FastTravelTask.py)；注册类 `FastTravelTask`。

- `FastTravelTask.run`，基线行 17：`click_traval_button`。

### FiveToOneTask.py（未注册/隐藏）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/FiveToOneTask.py)。

- `FiveToOneTask.run`，基线行 50：`click_relative`, `wait_click_ocr`, `wait_ocr`。
- `FiveToOneTask.merge_set`，基线行 75：`click_box`, `click_relative`, `wait_click_ocr`, `wait_feature`, `wait_ocr`。

### ForgeryTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/ForgeryTask.py)；注册类 `ForgeryTask`。

- `ForgeryTask.purification_material`，基线行 50：`click_box`, `click_relative`, `send_key`, `wait_book`, `wait_until`。
- `ForgeryTask.teleport_into_domain`，基线行 64：`click`, `click_on_book_target`, `click_team_challenge`, `wait_in_team_and_world`。

### GardenTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/GardenTask.py)；注册类 `GardenTask`。

- `GardenTask.run`，基线行 29：`click`, `wait_book`, `wait_feature`。
- `GardenTask.open_garden_weekly_page`，基线行 85：`click`。
- `GardenTask._choose_first_blessing`，基线行 124：`click`。

### KRLauncherSwitchTask.py（未注册/隐藏）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/KRLauncherSwitchTask.py)。

- `KRLauncherSwitchTask._ensure_pc_login_screen`，基线行 628：`_mouse_click`, `send_key`。
- `KRLauncherSwitchTask._screen_tap_text`，基线行 734：`_mouse_click`。

### MaterialPlannerTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/MaterialPlannerTask.py)；注册类 `MaterialPlannerTask`。

- `MaterialPlannerTask._pages`，基线行 70：`scroll_relative`。
- `MaterialPlannerTask.scan_target`，基线行 143：`click`, `wait_ocr`。
- `MaterialPlannerTask.scan_inventory`，基线行 178：`click_relative`, `send_key`。
- `MaterialPlannerTask.enter_forgery`，基线行 236：`click`, `click_team_challenge`, `click_traval_button`, `scroll_relative`, `wait_feature`, `wait_in_team_and_world`。

### MergeEchoTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/MergeEchoTask.py)；注册类 `MergeEchoTask`。

- `MergeEchoTask.run`，基线行 20：`send_key`, `wait_click_skip_dialog_confirm`, `wait_until`。
- `MergeEchoTask.open_merge_page`，基线行 56：`click_relative`。
- `MergeEchoTask.merge_full_batch`，基线行 64：`click_relative`, `wait_click_feature`, `wait_click_skip_dialog_confirm`。

### MouseResetTask.py（后台）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/MouseResetTask.py)；注册类 `MouseResetTask`。

- 此扫描未发现直接匹配的输入方法；仍需按设计方案检查生产委托链或回调（如切号测试、鼠标复位）。

### MultiAccountDailyTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/MultiAccountDailyTask.py)；注册类 `MultiAccountDailyTask`。

- `MultiAccountDailyTask._evidence_click`，基线行 1228：`record_click`。
- `MultiAccountDailyTask._switch_to_login`，基线行 1280：`_click_main_login_box`, `send_key`。
- `MultiAccountDailyTask._wait_login_screen_stable`，基线行 1482：`_click_main_login_box`。
- `MultiAccountDailyTask._restart_game_once`，基线行 2058：`_wait_login_screen_stable`。
- `MultiAccountDailyTask._main_login_screen_click`，基线行 2143：`_screen_click`。
- `MultiAccountDailyTask._click_main_login_box`，基线行 2329：`_screen_click`。
- `MultiAccountDailyTask._dialog_open_account_list`，基线行 2512：`_screen_click`。
- `MultiAccountDailyTask._find_and_click_account_in_combo_list`，基线行 2549：`_screen_click`。
- `MultiAccountDailyTask._dialog_find_and_click_account`，基线行 2631：`_find_and_click_account_in_combo_list`, `_screen_click`。
- `MultiAccountDailyTask._dialog_click_login`，基线行 2673：`_screen_click`。
- `MultiAccountDailyTask._click_account_in_list`，基线行 2881：`_dialog_find_and_click_account`, `_screen_click`。
- `MultiAccountDailyTask._open_account_list`，基线行 3012：`_screen_click`, `_wait_account_list_expanded`。
- `MultiAccountDailyTask._wait_account_list_expanded`，基线行 3084：`wait_until`。
- `MultiAccountDailyTask._wait_for_account_selection_stable`，基线行 3097：`wait_until`。
- `MultiAccountDailyTask._select_account_with_retry`，基线行 3173：`_click_account_in_list`, `_wait_for_account_selection_stable`, `wait_until`。
- `MultiAccountDailyTask._click_login_for_target`，基线行 3310：`_dialog_click_login`, `_main_login_screen_click`, `wait_until`。
- `MultiAccountDailyTask._select_and_login_first_available`，基线行 3392：`_wait_login_screen_stable`, `wait_until`。
- `MultiAccountDailyTask.find_account_drop_down`，基线行 3476：`wait_until`。

### NightmareNestTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/NightmareNestTask.py)；注册类 `NightmareNestTask`。

- `NightmareNestTask.combat_nest`，基线行 114：`click`, `click_team_challenge`, `send_key`, `wait_feature`, `wait_in_team_and_world`, `wait_until`。
- `NightmareNestTask._should_continue_combat_after_pickup`，基线行 211：`wait_combat`。
- `NightmareNestTask._travel_to_nest_or_skip`，基线行 215：`click`, `wait_in_team_and_world`, `wait_until`。
- `NightmareNestTask.go_nightmare_scroll`，基线行 291：`click`。

### PianoTeachingTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/PianoTeachingTask.py)；注册类 `PianoTeachingTask`。

- `PianoTeachingTask._release_pressed`，基线行 43：`send_key_up`。
- `PianoTeachingTask._press_event`，基线行 52：`send_key_down`。
- `PianoTeachingTask.run`，基线行 84：`send_key`。

### SecondSolTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/SecondSolTask.py)；注册类 `SecondSolTask`。

- `SecondSolTask.run`，基线行 28：`send_key`, `send_key_up`。

### SimulationTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/SimulationTask.py)；注册类 `SimulationTask`。

- `SimulationTask.teleport_into_domain`，基线行 49：`click`, `click_relative`, `click_team_challenge`, `wait_in_team_and_world`。

### SkipBaseTask.py（公共基类）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/SkipBaseTask.py)。

- `SkipBaseTask.skip_confirm`，基线行 21：`click`, `click_skip_dialog_confirm`。
- `SkipBaseTask.try_click_skip`，基线行 44：`click_box`。
- `SkipBaseTask.check_skip`，基线行 52：`click`, `click_box`, `try_click_skip`, `wait_until`。

### SkipDialogTask.py（后台）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/SkipDialogTask.py)；注册类 `AutoDialogTask`。

- `AutoDialogTask.skip_message`，基线行 24：`click`。

### TacetTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/TacetTask.py)；注册类 `TacetTask`。

- `TacetTask.run`，基线行 43：`wait_in_team_and_world`。
- `TacetTask.farm_tacet`，基线行 49：`click_relative`, `click_team_challenge`, `wait_click_skip_dialog_confirm`, `wait_in_team_and_world`。
- `TacetTask.teleport_to_tacet`，基线行 115：`click_on_book_target`。

### TestAccountSwitchTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/TestAccountSwitchTask.py)；注册类 `TestAccountSwitchTask`。

- 此扫描未发现直接匹配的输入方法；仍需按设计方案检查生产委托链或回调（如切号测试、鼠标复位）。

### WeeklyBossTask.py（一次性）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/WeeklyBossTask.py)；注册类 `WeeklyBossTask`。

- `WeeklyBossTask._stable_value`，基线行 88：`_wait_for`。
- `WeeklyBossTask._open_weekly_book`，基线行 103：`_wait_for`。
- `WeeklyBossTask._confirm_list_top`，基线行 119：`click_relative`, `scroll_relative`。
- `WeeklyBossTask._select_first_target`，基线行 141：`_wait_for`, `click_box`。
- `WeeklyBossTask._select_target`，基线行 188：`_wait_for`, `click_box`, `click_relative`, `scroll_relative`。
- `WeeklyBossTask._enter_challenge`，基线行 266：`_wait_for`, `click_box`。
- `WeeklyBossTask._release_movement`，基线行 321：`send_key_up`。
- `WeeklyBossTask._fight`，基线行 326：`_wait_combat_phase`, `_wait_for`, `wait_until`。
- `WeeklyBossTask._confirm_claim_if_needed`，基线行 401：`_wait_for`, `click_box`。
- `WeeklyBossTask._fight_and_claim`，基线行 426：`_wait_for`, `send_key`。
- `WeeklyBossTask._leave_settlement`，基线行 454：`_wait_for`, `click_box`。

### WWOneTimeTask.py（公共基类）

[源码](https://github.com/xihuojun2020-tech/okww-custom/blob/v1.84.01/src/task/WWOneTimeTask.py)。

- 此扫描未发现直接匹配的输入方法；仍需按设计方案检查生产委托链或回调（如切号测试、鼠标复位）。


## 2026-09-14 / 1.72.00 实施进展

本轮接入后台分帧、共用传送、初露峥嵘、周本和部分深塔/事件导航，增加活动消费持久化核验与材料页面身份检查。40 个测试文件共 630 项通过。用户明确跳过领域结算、乐园周常、声骸融合；其他未迁移细目仍未完成，不勾选含未实现或实机验收的复合项。完整35文件状态、消费保护恢复与使用端验收见 [1.72.00 覆盖报告](2026-09-14-navigation-rollout-1.72.00.md)。


## 1.73.00 续作

完成简体中文六个指南页签核验、周本目标详情、深塔完成编队、仓库/培养目标滚动条端点检查，以及账号选择/深塔结算返回的工具页摘要。37个测试文件522项通过。三类用户跳过内容不变，其余未迁移项和实机限制见 [本轮覆盖报告](2026-09-14-navigation-rollout-1.73.00.md)。原复合验收项含未实现或实机部分的仍不勾选。
