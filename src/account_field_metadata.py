"""Chinese presentation metadata for safe per-account task fields."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class AccountFieldMetadata:
    key: str
    label: str
    help_text: str
    editor_type: str
    options: tuple[Any, ...] = ()
    option_labels: tuple[str, ...] = ()
    affects_identity: bool = False
    read_only: bool = False


_LABELS = {
    "Which to Farm": ("体力用途", "每天优先消耗体力的副本类型。不会影响账号识别。"),
    "Which Tacet Suppression to Farm": ("无音区选择", "选择要刷取的无音区编号。不会影响账号识别。"),
    "Which Forgery Challenge to Farm": ("凝素领域选择", "选择要刷取的凝素领域编号。不会影响账号识别。"),
    "Material Selection": ("材料选择", "模拟领域中优先获取的材料。不会影响账号识别。"),
    "Farm Nightmare Nest for Daily Echo": ("每日刷取梦魇声骸", "开启后每日任务会尝试刷取梦魇声骸。"),
    "Nightmare Which to Farm": ("梦魇刷取目标", "选择梦魇巢穴目标；多个值保留为列表。"),
    "Tacet Discord Nests to Farm": ("残象聚落目标", "选择刷取的残象聚落；多个值保留为列表。"),
    "Auto Farm all Nightmare Nest": ("自动刷取全部梦魇", "开启后按现有任务规则遍历全部梦魇目标。"),
    "Weekly Garden Check Day": ("周常乐园检查日", "选择自动检查周常乐园的星期。"),
    "Merge Echo on Sunday": ("周日合成声骸", "开启后在周日执行声骸合成。"),
    "Logout After Daily Task": ("每日任务后自动退登", "单账号运行结束后的退登行为；多账号任务会临时接管。"),
}
_OPTIONS = {
    "Which to Farm": ("Tacet Suppression", "Forgery Challenge", "Simulation Challenge"),
    "Material Selection": ("Resonator EXP", "Weapon EXP", "Shell Credit"),
    "Weekly Garden Check Day": ("无", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"),
}
_VALUE_LABELS = {
    "Tacet Suppression": "无音区",
    "Forgery Challenge": "凝素领域",
    "Simulation Challenge": "模拟领域",
    "Resonator EXP": "共鸣者经验",
    "Weapon EXP": "武器经验",
    "Shell Credit": "贝币",
    "Nightmare Purification": "梦魇拔除",
    "Tacet Discord Nest": "残像聚落",
}
_STORAGE_VALUES = {label: value for value, label in _VALUE_LABELS.items()}
_IDENTITY = {"备用识别名称", "备用识别名称内容", "Account Name", "account_name", "账号名称"}


def localize_account_value(value: Any) -> Any:
    if isinstance(value, list):
        return [localize_account_value(item) for item in value]
    if isinstance(value, dict):
        return {key: localize_account_value(item) for key, item in value.items()}
    return _VALUE_LABELS.get(value, value)


def restore_account_value(value: Any) -> Any:
    if isinstance(value, list):
        return [restore_account_value(item) for item in value]
    if isinstance(value, dict):
        return {key: restore_account_value(item) for key, item in value.items()}
    return _STORAGE_VALUES.get(value, value)


def account_field_metadata(tasks: Mapping[str, Any]) -> tuple[AccountFieldMetadata, ...]:
    result = []
    for key, value in tasks.items():
        label, help_text = _LABELS.get(key, (str(key), "账号专属任务设置；不会改变账号 UUID。"))
        identity = key in _IDENTITY
        editor = "bool" if isinstance(value, bool) else "choice" if key in _OPTIONS else "json" if isinstance(value, (list, dict)) else "text"
        options = tuple(_OPTIONS.get(key, ()))
        result.append(AccountFieldMetadata(
            str(key), label, help_text, editor, options,
            tuple(str(localize_account_value(option)) for option in options), identity, identity))
    return tuple(result)


__all__ = ["AccountFieldMetadata", "account_field_metadata", "localize_account_value",
           "restore_account_value"]
