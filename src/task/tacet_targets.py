"""Persisted IDs stay stable when the game inserts two rows at the top."""
TACET_STRUCTURE = (4, 5, 5, 7)
TACET_IDS = (20, 21, *range(1, 20))
TACET_BUTTON_LABELS = ('前往', '直接挑战', '直接挑戰', 'Go', 'Go To', 'Direct Challenge')
TACET_NAMES = {20: '沉心域无音区', 21: '烬心域无音区',
               1: '方擎西峰无音区', 2: '玄幽东岳无音区'}


def tacet_serial(target_id):
    if type(target_id) is not int or target_id not in TACET_IDS:
        raise ValueError('请选择有效的无音区目标')
    return TACET_IDS.index(target_id) + 1


def tacet_label(target_id):
    tacet_serial(target_id)  # Validate the persisted ID independently of its display label.
    return TACET_NAMES[target_id] if target_id in (20, 21) else f'第{target_id}个无音区'


TACET_OPTIONS = tuple((value, tacet_label(value)) for value in TACET_IDS)
