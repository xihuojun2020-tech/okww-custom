import unittest
from datetime import date
from types import SimpleNamespace
from pathlib import Path
import cv2
import numpy as np
from src.task.sea_ruins import ENDLESS, Preset, Token, choose_loadout, token_score, season_rule, scores_valid, parse_count
from src.task import sea_ruins_vision as v

TODAY = date(2026, 9, 18)
ROOT = Path('tests/fixtures/sea_ruins')


class TestSeaRuins(unittest.TestCase):
    def setUp(self):
        self.wind = Preset(1, ('char_qingxiao', 'char_denia', 'char_verina'))
        self.ice = Preset(2, ('char_hiyuki', 'char_lucilla', 'char_suisui'))
        self.generic = Token('审判-遗落令旗', '施放变奏技能后暴击伤害提升40%', -1)

    def test_duplicate_roster_cannot_fill_both_halves(self):
        duplicate = Preset(3, tuple(reversed(self.wind.members)))
        with self.assertRaisesRegex(ValueError, '不重人'):
            choose_loadout([self.wind, duplicate], [self.generic], 7, TODAY)

    def test_registered_characters_without_special_rules_remain_usable(self):
        from unittest.mock import patch
        from src.char.CharFactory import char_dict
        from src.task.sea_ruins import PROFILES, character_profile
        with patch.dict(PROFILES, {}, clear=True):
            for identity, data in char_dict.items():
                self.assertIsNotNone(character_profile(identity), identity)
            self.assertIsNone(character_profile('unknown'))
        team = Preset(3, ('char_phrolova', 'char_cantarella', 'char_douling'))
        self.assertTrue(team.valid)
        self.assertGreater(token_score(team, Token('编造者', '', 2), 11), 15)
        self.assertEqual(character_profile('char_douling').element, '导电')
        self.assertFalse(character_profile('char_douling').triggers)
        self.assertIsNotNone(choose_loadout([team, self.wind], [self.generic], 8, TODAY))
        self.assertFalse(Preset(4, ('char_phrolova', '', 'char_douling')).valid)

    def test_floor_eight_avoids_fire_upper_and_spectro_lower(self):
        self.assertEqual(season_rule(8, 0, TODAY), ((), ('热熔',)))
        self.assertEqual(season_rule(8, 1, TODAY), ((), ('衍射',)))
        fire = Preset(3, ('char_encore', 'char_sanhua', 'char_baizhi'))
        spectro = Preset(4, ('char_jinhsi', 'char_zhezhi', 'char_douling'))
        plan = choose_loadout([fire, spectro], [self.generic], 8, TODAY)
        self.assertEqual((plan.upper, plan.lower), (spectro, fire))

    def test_current_cycle_resistances_for_floors_nine_to_eleven(self):
        for floor, element in ((9, '气动'), (10, '导电'), (11, '衍射')):
            with self.subTest(floor=floor):
                self.assertEqual(season_rule(floor, 0, TODAY), ((), (element,)))
                self.assertEqual(season_rule(floor, 1, TODAY), ((), (element,)))

    def test_endless_uses_neutral_unverified_rules(self):
        self.assertEqual(season_rule(ENDLESS, 0, TODAY), ((), ()))
        self.assertEqual(season_rule(ENDLESS, 1, TODAY), ((), ()))
        self.assertEqual(token_score(self.wind, self.generic, ENDLESS), 12)
        self.assertIsNotNone(choose_loadout([self.wind, self.ice], [self.generic], ENDLESS, TODAY))

    def test_locked_infinite_empty_unknown_and_single_use(self):
        for token in (Token('狂欢者', '', -1, True), Token('狂欢者', '', 0), Token('狂欢者', '', None), Token('狂欢者', '', 1)):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    choose_loadout([self.wind, self.ice], [token], 11, TODAY)
        plan = choose_loadout([self.wind, self.ice], [Token('狂欢者', '', 2)], 11, TODAY)
        self.assertEqual(plan.tokens[0], plan.tokens[1])

    def test_unknown_mode_does_not_assume_rupture_or_fusion_burst(self):
        team = Preset(1, ('char_aemeath', 'char_denia', 'char_verina'))
        self.assertEqual(token_score(team, Token('镌刻者', '', 2), 11), 15)
        self.assertEqual(token_score(team, Token('慰藉者', '', 2), 11), 15)
        self.assertEqual(token_score(team, Token('那丈量心魂的天平', '', 2), 11), 0)

    def test_partial_meta_team_still_has_self_trigger(self):
        self.assertGreater(token_score(self.wind, Token('那丈量心魂的天平', '', 2), 11), 20)
        non_meta = Preset(4, ('char_jingran', 'char_sanhua', 'char_baizhi'))
        self.assertGreater(token_score(non_meta, Token('那映照虚妄的灯', '', 2), 11), 20)

    def test_unknown_member_and_expired_cycle_stop(self):
        self.assertFalse(Preset(3, ('unknown', 'char_verina', 'char_denia')).valid)
        with self.assertRaisesRegex(ValueError, '失效'):
            season_rule(7, 0, date(2026, 9, 28))
        self.assertTrue(scores_valid(1410, 1490, 2900))
        self.assertFalse(scores_valid(1410, 1490, 290))
        self.assertFalse(scores_valid(None, 1490, 2900))
        self.assertEqual(parse_count('∞'), -1)
        self.assertIsNone(parse_count('2次'))

    def test_card_locks_and_unlocked_tokens(self):
        frame = cv2.imread(str(ROOT/'tokens.png'))
        cards = v.token_cards(frame)
        self.assertEqual(len(cards), 12)
        self.assertTrue(all(v.token_locked(frame, c) for c in cards[:5]))
        self.assertTrue(all(not v.token_locked(frame, c) for c in cards[5:]))

    def test_exit_marker_excludes_hud_at_multiple_resolutions(self):
        for height in (720, 1080, 1440):
            for name, expected_x in (('exit_front', .474), ('exit_side', .798), ('exit_prompt', .498)):
                frame = cv2.resize(cv2.imread(str(ROOT/f'{name}.png')), (height*16//9, height))
                marker = v.exit_marker(frame)
                self.assertIsNotNone(marker, (name, height))
                self.assertAlmostEqual(marker[0], expected_x, delta=.018)
                # Keep HUD, remove world-space marker: the left identical icon must not match.
                frame[:, round(frame.shape[1]*.18):] = 0
                self.assertIsNone(v.exit_marker(frame))

    def test_f_requires_exact_label_and_aligned_key(self):
        for height in (720, 1080, 1440):
            frame = cv2.resize(cv2.imread(str(ROOT/'exit_prompt.png')), (height*16//9, height))
            scale = height/1152
            label = SimpleNamespace(name='进入下半海域', x=1420*scale, y=580*scale, height=29*scale)
            self.assertTrue(v.interaction_prompt(frame, [label], '进入下半海域'))
            self.assertFalse(v.interaction_prompt(frame, [label], '开启挑战'))
            label.y -= 200*scale
            self.assertFalse(v.interaction_prompt(frame, [label], '进入下半海域'))
        self.assertIsNone(v.exit_marker(np.zeros((720, 1280, 3), np.uint8)))

    def test_user_exit_backgrounds(self):
        for i in range(4):
            sample = cv2.imread(str(ROOT/f'exit_sample_{i}.png'))
            frame = np.zeros((1152, 2048, 3), np.uint8)
            h, w = sample.shape[:2]
            frame[400:400+h, 1000:1000+w] = sample
            self.assertIsNotNone(v.exit_marker(frame), i)
            frame[:] = 0
            frame[300:300+h, 20:20+w] = sample
            self.assertIsNone(v.exit_marker(frame), i)

    def test_low_exit_marker_from_failed_run(self):
        for height in (720, 1080, 1440):
            frame = cv2.resize(cv2.imread(str(ROOT/'exit_low.png')), (height*16//9, height))
            marker = v.exit_marker(frame)
            self.assertIsNotNone(marker, height)
            self.assertAlmostEqual(marker[0], .595, delta=.018)
            self.assertAlmostEqual(marker[1], .769, delta=.018)
            frame[:, round(frame.shape[1]*.18):] = 0
            self.assertIsNone(v.exit_marker(frame))

    def test_left_exit_marker_from_failed_run(self):
        for height in (720, 1080, 1440):
            frame = cv2.resize(cv2.imread(str(ROOT/'exit_left_20260923.png')),
                               (height*16//9, height))
            marker = v.exit_marker(frame)
            self.assertIsNotNone(marker, height)
            self.assertAlmostEqual(marker[0], .195, delta=.015)
            frame[round(height*.43):round(height*.52),
                  round(frame.shape[1]*.15):round(frame.shape[1]*.25)] = 0
            self.assertIsNone(v.exit_marker(frame))

    def test_high_exit_marker_from_failed_run(self):
        for height in (720, 1080, 1440):
            frame = cv2.resize(cv2.imread(str(ROOT/'exit_high.png')), (height*16//9, height))
            marker = v.exit_marker(frame)
            self.assertIsNotNone(marker)
            self.assertAlmostEqual(marker[0], .497, delta=.015)
            self.assertAlmostEqual(marker[1], .128, delta=.015)
            # Keep all HUD and left quest; remove only the world marker.
            frame[round(.085*height):round(.16*height),
                  round(.47*frame.shape[1]):round(.52*frame.shape[1])] = 0
            self.assertIsNone(v.exit_marker(frame))
