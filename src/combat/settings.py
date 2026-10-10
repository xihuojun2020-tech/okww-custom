# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared production defaults, safe to read without loading a game application."""

HOTKEY_DEFAULTS = {'Echo Key': 'q',
 'Liberation Key': 'r',
 'Resonance Key': 'e',
 'Tool Key': 't',
 'Jump Key': 'space',
 'Dodge Key': 'lshift',
 'Wheel Key': 'tab',
 'Guidebook Key': 'f2',
 'Bag Key': 'b'}

CHARACTER_DEFAULTS = {'Iuno C6': False, 'Chisa DPS': False}

MONTHLY_CARD_DEFAULTS = {'Check Monthly Card': True, 'Monthly Card Time': 4}

TEMPLATE_MATCHING_DEFAULTS = {'default_horizontal_variance': 0.002,
 'default_vertical_variance': 0.002,
 'default_threshold': 0.8,
 'vcenter_features': ['monthly_card', 'skip_dialog_check'],
 'hcenter_features': ['monthly_card',
                      'suisui_forte3',
                      'message_dialog',
                      'claim_stamina_sign',
                      'skip_dialog_check',
                      'login_close',
                      'garden_confirm',
                      'garden_continue_game',
                      'garden_unpause',
                      'garden_get_gold',
                      'garden_get_purple',
                      'garden_get_skip',
                      'garden_not_interested_confirm',
                      'garden_not_interested',
                      'a_garden_back',
                      'garden_get_confirm_gray',
                      'the_garden_max',
                      'garden_shop_close',
                      'garden_new_stage',
                      'a_garden_restart',
                      'suisui_forte2',
                      'suisui_e1',
                      'e_forte',
                      'f_break_full']}

COMBAT_GLOBAL_DEFAULTS = {
    'Game Hotkey': HOTKEY_DEFAULTS,
    'Character Config': CHARACTER_DEFAULTS,
    'Monthly Card Config': MONTHLY_CARD_DEFAULTS,
}
