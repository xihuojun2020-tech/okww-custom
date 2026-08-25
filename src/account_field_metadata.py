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
    "Weekly Garden Check Day": ("无", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"),
}
_IDENTITY = {"备用识别名称", "备用识别名称内容", "Account Name", "account_name", "账号名称"}


def account_field_metadata(tasks: Mapping[str, Any]) -> tuple[AccountFieldMetadata, ...]:
    result = []
    for key, value in tasks.items():
        label, help_text = _LABELS.get(key, (str(key), "账号专属任务设置；不会改变账号 UUID。"))
        identity = key in _IDENTITY
        editor = "bool" if isinstance(value, bool) else "choice" if key in _OPTIONS else "json" if isinstance(value, (list, dict)) else "text"
        result.append(AccountFieldMetadata(str(key), label, help_text, editor,
                                           tuple(_OPTIONS.get(key, ())), identity, identity))
    return tuple(result)


__all__ = ["AccountFieldMetadata", "account_field_metadata"]
