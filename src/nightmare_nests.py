"""Shared ordered nest names used by account selection and farming."""
NEST_TOTALS_BY_NAME = {
    '梦枢天罗残象聚落': 48,
    '落渊南丘残象聚落': 41,
    '盲望之塌残象聚落': 48,
    '复生丘原残象聚落': 48,
    '陷足流川残象聚落': 24,
}
NEST_NAMES = list(NEST_TOTALS_BY_NAME)
# Preserve legacy implicit choices as well as explicitly saved selections.
DEFAULT_NEST_NAMES = NEST_NAMES[1:]
NIGHTMARE_NAMES = ['穗波市梦魇聚落', '三王峰梦魇聚落', '潮痕岩滩梦魇聚落', '受蚀地梦魇聚落']
_NIGHTMARE_GAME_NAMES = {name.replace('梦魇聚落', '梦魔聚落'): name for name in NIGHTMARE_NAMES}


def normalize_nest_text(value):
    normalized = ''.join(str(value).split()).translate(str.maketrans(
        {'像': '象', '夢': '梦', '樞': '枢', '羅': '罗', '淵': '渊',
         '殘': '残', '復': '复', '穂': '穗'}))
    return _NIGHTMARE_GAME_NAMES.get(normalized, normalized)


def canonical_nest_name(value):
    normalized = normalize_nest_text(value)
    return next((name for name in NEST_NAMES
                 if normalize_nest_text(name) == normalized), None)
