from ok.gui.tasks.LabelAndButtons import LabelAndButtons
from ok.gui.tasks.LabelAndDoubleSpinBox import LabelAndDoubleSpinBox
from ok.gui.tasks.LabelAndDropDown import LabelAndDropDown
from ok.gui.tasks.LabelAndFileSelector import LabelAndFileSelector
from ok.gui.tasks.LabelAndLabel import LabelAndLabel
from ok.gui.tasks.LabelAndGlobal import LabelAndGlobal
from ok.gui.tasks.LabelAndLineEdit import LabelAndLineEdit
from ok.gui.tasks.LabelAndMultiSelection import LabelAndMultiSelection
from ok.gui.tasks.LabelAndSpinBox import LabelAndSpinBox
from ok.gui.tasks.LabelAndSwitchButton import LabelAndSwitchButton
from ok.gui.tasks.LabelAndTextEdit import LabelAndTextEdit
from ok.gui.tasks.ModifyListItem import ModifyListItem


def _resolve_type(the_type, default_value):
    if not isinstance(the_type, dict):
        return None

    resolved_type = the_type.get('type')
    if resolved_type:
        return resolved_type
    if 'buttons' in the_type or 'callback' in the_type:
        return 'button'
    if 'options' in the_type:
        if isinstance(default_value, list):
            return 'multi_selection'
        return 'drop_down'
    return None


def config_widget(config_type, config_desc, config, key, value, task):
    the_type = config_type.get(key) if config_type is not None else None
    value = config.get_default(key)
    resolved_type = _resolve_type(the_type, value)
    if resolved_type:
        if resolved_type == 'drop_down':
            if isinstance(value, list) and 'options_available' in the_type:
                return ModifyListItem(
                    config_desc, config, key, options_available=the_type['options_available'],
                    allow_duplication=the_type.get('allow_duplication', False)
                )
            return LabelAndDropDown(config_desc, the_type['options'], config, key)
        elif resolved_type == 'integer_drop_down':
            from src.gui.LabelAndIntegerDropDown import LabelAndIntegerDropDown
            return LabelAndIntegerDropDown(config_desc, the_type['options'], config, key)
        elif resolved_type == 'multi_selection':
            return LabelAndMultiSelection(config_desc, the_type['options'], config, key)
        elif resolved_type == 'dropdown_multi_selection':
            # 项目级组件：下拉多选（如每周乐园检查日）
            try:
                from src.gui.LabelAndDropDownMultiSelect import LabelAndDropDownMultiSelect
                return LabelAndDropDownMultiSelect(config_desc, the_type['options'], config, key)
            except Exception as e:
                from ok.util.logger import Logger
                Logger.get_logger(__name__).error('LabelAndDropDownMultiSelect import failed', e)
                return LabelAndMultiSelection(config_desc, the_type['options'], config, key)
        elif resolved_type == 'account_sequence':
            # 项目级组件：账号序列（多账号每日任务的本轮账号列表）
            try:
                from src.gui.LabelAndAccountSequence import LabelAndAccountSequence
                return LabelAndAccountSequence(
                    config_desc, the_type['options'], config, key,
                    max_count=the_type.get('max_count', 10),
                    last_completed_provider=the_type.get('last_completed_provider'),
                )
            except Exception as e:
                from ok.util.logger import Logger
                Logger.get_logger(__name__).error('LabelAndAccountSequence import failed', e)
                return LabelAndTextEdit(config_desc, config, key)
        elif resolved_type == 'global':
            config = task.get_global_config(key)
            desc = task.get_global_config_desc(key)
            return LabelAndGlobal(desc, config, key)
        elif resolved_type == 'text_edit':
            return LabelAndTextEdit(config_desc, config, key)
        elif resolved_type == 'line_edit':
            return LabelAndLineEdit(config_desc, config, key, the_type)
        elif resolved_type == 'label':
            sub_key = the_type.get('sub_key') if isinstance(the_type, dict) else None
            return LabelAndLabel(config_desc, config, key, task, sub_key)
        elif resolved_type == 'file_selector':
            if not isinstance(value, str):
                raise ValueError("file_selector config type requires a string default value")
            return LabelAndFileSelector(config_desc, config, key, the_type)
        elif resolved_type == 'button':
            buttons = the_type.get('buttons')
            if not buttons:
                buttons = [the_type]
            return LabelAndButtons(config_desc, key, buttons)
        else:
            raise Exception('Unknown config type')
    if isinstance(value, bool):
        return LabelAndSwitchButton(config_desc, config, key)
    elif isinstance(value, list):
        options_available = the_type.get('options_available') if isinstance(the_type, dict) else None
        allow_duplication = the_type.get('allow_duplication', False) if isinstance(the_type, dict) else False
        return ModifyListItem(
            config_desc, config, key, options_available=options_available,
            allow_duplication=allow_duplication
        )
    elif isinstance(value, int):
        return LabelAndSpinBox(config_desc, config, key, the_type)
    elif isinstance(value, float):
        return LabelAndDoubleSpinBox(config_desc, config, key)
    elif isinstance(value, str):
        if value and len(value) > 16 or '\n' in value:
            return LabelAndTextEdit(config_desc, config, key)
        else:
            return LabelAndLineEdit(config_desc, config, key)
    else:
        raise ValueError(f"invalid type {type(value)}, value {value}")
