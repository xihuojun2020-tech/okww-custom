"""Official translation keys shared by character display and OCR verification."""

CHARACTER_DISPLAY_NAMES = {
    'Douling': 'Buling',
    'Xigelika': 'Sigrika',
    'Linnai': 'Lynae',
    'Luhesi': 'Luuk Herssen',
    'Xiangliyao': 'Xiangli Yao',
    'ShoreKeeper': 'Shorekeeper',
    'HavocRover': 'Rover',
    'YangYangSp': 'Yangyang: Xuanling',
}


def character_display_name(character):
    if isinstance(character, str):
        return CHARACTER_DISPLAY_NAMES.get(character, character)
    if not isinstance(character, type):
        display = getattr(character, 'display_name', None)
        if display:
            return display
        character = type(character)
    return getattr(character, 'DISPLAY_NAME', None) or CHARACTER_DISPLAY_NAMES.get(
        character.__name__, character.__name__)
