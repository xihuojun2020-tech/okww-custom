"""Version-owned token catalogue. Runtime reads inventory, never effect text.

Sources/verification limits: docs/references/sea-ruins-tokens.md (2026-09-20).
Names are canonical; list captions may be truncated, but must match uniquely.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TokenRule:
    name: str
    rarity: str
    effect: str
    source: str


WIKI = 'https://wuwa.huijiwiki.com/wiki/'
CATALOG = (
    TokenRule('那映照虚幻的燃灯', 'gold', '获得护盾：自身热熔伤害加成+3%、重击最终伤害+2.5%，3秒，最多15层。', WIKI+'那映照虚幻的燃灯'),
    TokenRule('那凝望深渊的眼眸', 'gold', '敌人受到霜渐最终伤害+50%；附加霜渐使敌人受到冷凝最终伤害+50%，5秒。', 'https://phro.love/db/item/71500088?lang=zh'),
    TokenRule('那丈量心魂的天平', 'gold', '附加集谐·偏移后自身最终伤害+40%，30秒；谐度破坏后全队全属性加成+30%、气动额外+30%，30秒。', 'https://encore.moe/item/71500105?lang=zh-Hans'),
    TokenRule('眷属-珍奇契约', 'purple', '召唤声骸协同作战，不受玩家角色伤害。', WIKI+'眷属-珍奇契约'),
    TokenRule('狂欢者-船长印章', 'purple', '全属性伤害加深25%。', "https://wutheringwaves.fandom.com/wiki/Reveler_Captain%27s_Seal"),
    TokenRule('镌刻者-长夜孤灯', 'purple', '敌人受到最终伤害+15%、震谐伤害+50%。', 'tests/fixtures/sea_ruins/tokens.png'),
    TokenRule('希冀者-长夜孤灯', 'purple', '敌人受到最终伤害+15%；对集谐·干涉或偏移目标最终伤害+15%。', WIKI+'希冀者—长夜孤灯'),
    TokenRule('编造者-长夜孤灯', 'purple', '敌人受到最终伤害+15%，声骸技能最终伤害+25%。', 'https://www.encore.moe/item/71501003?lang=zh-Hans'),
    TokenRule('慰藉者-长夜孤灯', 'purple', '敌人受到最终伤害+15%；附加异常后自身最终伤害+15%，30秒。', WIKI+'慰藉者—长夜孤灯'),
    TokenRule('审判-遗落令旗', 'blue', '施放变奏后全队暴击伤害提升40%，15秒。', WIKI+'审判-遗落令旗'),
    TokenRule('布道-遗落令旗', 'blue', '造成普攻伤害后下次普攻伤害加深4%，最多5层，15秒。', WIKI+'布道-遗落令旗'),
    TokenRule('游猎-遗落令旗', 'blue', '造成伤害后下次重击伤害加深4%，最多5层，15秒。', WIKI+'游猎-遗落令旗'),
)


def name_key(text):
    return re.sub(r'[\s—–一\-·.…。]', '', text or '')


def identify_token(caption, rarity=None):
    key = name_key(caption)
    if len(key) < 3:
        return None
    matches = [r for r in CATALOG if (rarity is None or r.rarity == rarity)
               and name_key(r.name).startswith(key)]
    return matches[0] if len(matches) == 1 else None
