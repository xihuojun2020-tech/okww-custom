"""Persisted IDs stay stable when the game inserts two rows at the top."""
TACET_STRUCTURE = (4, 5, 5, 7)
TACET_IDS = (20, 21, *range(1, 20))
TACET_BUTTON_LABELS = ('前往', '直接挑战', '直接挑戰', 'Go', 'Go To', 'Direct Challenge')
TACET_NAMES = {
    20: '沉心域无音区', 21: '烬心域无音区',
    1: '方擎西峰无音区', 2: '玄幽东岳无音区',
    3: '落日堤屿无音区', 4: '冰原运输港无音区',
    5: '加拉尔冠阶无音区', 6: '隐咏深腹无音区',
    7: '陷足流川无音区', 8: '哀恸谷无音区',
    9: '贝奥海域无音区', 10: '黎乔利群岛无音区',
    11: '榛生半岛无音区', 12: '悲叹墓岛无音区',
    13: '中曲台地无音区', 14: '荒石高地无音区 I',
    15: '虎口山脉无音区', 16: '怨鸟泽无音区',
    17: '归墟港市无音区', 18: '荒石高地无音区 II',
    19: '无光之森无音区',
}


def tacet_serial(target_id):
    if type(target_id) is not int or target_id not in TACET_IDS:
        raise ValueError('请选择有效的无音区目标')
    return TACET_IDS.index(target_id) + 1


def tacet_label(target_id):
    tacet_serial(target_id)  # Validate the persisted ID independently of its display label.
    return TACET_NAMES[target_id]


TACET_OPTIONS = tuple((value, tacet_label(value)) for value in TACET_IDS)
