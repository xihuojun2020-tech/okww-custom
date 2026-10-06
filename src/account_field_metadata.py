"""Chinese presentation metadata for safe per-account task fields."""

from dataclasses import dataclass
from typing import Any, Mapping
from src.task.weekly_boss import WEEKLY_BOSSES, WEEKLY_AUTO
from src.task.tacet_targets import TACET_IDS, TACET_OPTIONS
from src.task.forgery_targets import FORGERY_DOMAIN_OPTIONS

WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
GARDEN_MODE_DAILY = 'daily'
GARDEN_MODE_MULTI_ACCOUNT_WEEKLY = 'multi_account_weekly'
GARDEN_MODE_CLOSED = 'closed'
GARDEN_EXECUTION_MODES = (GARDEN_MODE_DAILY, GARDEN_MODE_MULTI_ACCOUNT_WEEKLY, GARDEN_MODE_CLOSED)
_WEEKDAY_ALIASES = {prefix + day: english for english, day in zip(WEEKDAYS, '一二三四五六日')
                    for prefix in ('星期', '周')}
_WEEKDAY_ALIASES.update({'星期天': 'Sunday', '周天': 'Sunday'})


def normalize_weekday(value: Any) -> str:
    value = '' if value is None else str(value).strip()
    if value in ('', '无'):
        return '无'
    if value in WEEKDAYS:
        return value
    if value in _WEEKDAY_ALIASES:
        return _WEEKDAY_ALIASES[value]
    raise ValueError('周常乐园检查日无效，请重新选择星期')


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
    'Forgery Material Goals': ('凝素材料目标', '输入已有材料与目标所需；按27/9/3/1折算缺口，达标后刷本账号无音区。'),
    'Forgery Limit Mode': ('凝素上限', '不限，或按已有库存与目标需求计算缺口。'),
    'World Boss Material Targets': ('世界首领突破材料', '按1→2→3累计领奖，0跳过；全部达标后跟随本账号体力用途。次数跨日保留，只计成功领取，不计材料产出数量。'),
    'Material Planner Enabled': ('养成材料规划', '按游戏培养目标刷凝素，材料满足后刷声骸；每周校准仓库，收益原图和统计永久保留。首版仅简体中文16:9。'),
    'Screenshot After Daily Task': ('每日任务后截图', '依次保存四页到完成检查；关闭录像仍可截图。'),
    'Record After Daily Task': ('每日任务后录像', ''),
    'Record Pages': ('录像页面（固定全选）', ''),
    'Record Duration': ('每页录像时长（秒）', ''),
    "Weekly Boss Target": ("每周周本", "无表示关闭；仅周一执行、周日独立复核，其他日期跳过。优先使用当前体力。"),
    "Weekly Boss Targets": ("周本优先级", "累计领取次数跨周保留；全部达标后领取游戏列表第一项。0跳过，不限保留旧行为。"),
    "Which to Farm": ("体力用途", "每天优先消耗体力的副本类型。不会影响账号识别。"),
    "Which Tacet Suppression to Farm": ("无音区选择", "选择要刷取的无音区。旧账号选择保留原关卡；前往后不可快速到达时，请先解锁地图。"),
    "Which Forgery Challenge to Farm": ("凝素领域选择", "选择要刷取的凝素领域。旧账号序号仍指向原关卡。"),
    "Material Selection": ("材料选择", "模拟领域中优先获取的材料。不会影响账号识别。"),
    "Farm Nightmare Nest for Daily Echo": ("每日刷取梦魇声骸", "开启后每日任务会尝试刷取梦魇声骸。"),
    "Nightmare Which to Farm": ("梦魇刷取目标", "选择梦魇巢穴目标；多个值保留为列表。"),
    "Tacet Discord Nests to Farm": ("残象聚落目标", "勾选哪些聚落就刷取哪些；全部取消则跳过残象聚落。"),
    "Nightmare Settlements to Farm": ("梦魇聚落目标", "补充刷取目标，默认全部不选。"),
    "Auto Farm all Nightmare Nest": ("自动刷取所选目标", "开启后依次刷取勾选的残象聚落和梦魇聚落。"),
    "Weekly Garden Check Day": ("周常乐园检查日", "仅在乐园执行安排为“随每日执行”时生效；无表示每日入口不执行乐园。"),
    "Garden Execution Mode": ("乐园执行安排", "随每日执行会按下方检查日及补检规则运行；跟随多账号每周乐园仅由独立周任务运行；关闭会跳过所有自动乐园入口。"),
    "Merge Echo on Sunday": ("周日合成声骸", "开启后在周日执行声骸合成。"),
    "Logout After Daily Task": ("每日任务后自动退登", "单账号运行结束后的退登行为；多账号任务会临时接管。"),
    "备用识别名称": ("使用备用识别名称", "选择“使用”后，下面填写的名称才参与登录账号识别。"),
    "备用识别名称内容": ("备用识别名称内容", "可填写 U…A 等登录页显示名称；停用时保留但不会用于识别。"),
}
_OPTIONS = {
    'Which Tacet Suppression to Farm': TACET_IDS,
    'Which Forgery Challenge to Farm': tuple(value for value, _ in FORGERY_DOMAIN_OPTIONS),
    "Weekly Boss Target": ("无", WEEKLY_AUTO, *(boss.key for boss in WEEKLY_BOSSES)),
    "Which to Farm": ("Tacet Suppression", "Forgery Challenge", "Simulation Challenge", "无"),
    "Material Selection": ("Resonator EXP", "Weapon EXP", "Shell Credit"),
    "Weekly Garden Check Day": ("无", *WEEKDAYS),
    "Garden Execution Mode": GARDEN_EXECUTION_MODES,
    "备用识别名称": ("无", "使用"),
}
_VALUE_LABELS = {
    'Forgery Material Goals': ('凝素材料目标', '输入本轮还需刷出的金、紫、蓝、绿数量；按27/9/3/1折算，完成两组后自动刷本账号无音区。'),
    **{boss.key: boss.name for boss in WEEKLY_BOSSES},
    **dict(zip(WEEKDAYS, ('星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'))),
    "Tacet Suppression": "无音区",
    "Forgery Challenge": "凝素领域",
    "Simulation Challenge": "模拟领域",
    "Resonator EXP": "共鸣者经验",
    "Weapon EXP": "武器经验",
    "Shell Credit": "贝币",
    "Nightmare Purification": "梦魇聚落",
    "Tacet Discord Nest": "残像聚落",
}
_VALUE_LABELS.update({GARDEN_MODE_DAILY: "随每日执行",
                      GARDEN_MODE_MULTI_ACCOUNT_WEEKLY: "跟随多账号每周乐园",
                      GARDEN_MODE_CLOSED: "关闭"})
_STORAGE_VALUES = {label: value for value, label in _VALUE_LABELS.items()}
_IDENTITY = {
    "phone", "masked_phone", "nickname", "alternate_login_name", "game_feature_code",
    "account_aliases", "Account Name", "account_name", "账号名称",
}


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


def legacy_garden_execution_mode(check_day: Any) -> str:
    """Conservatively map the old day selector; malformed/missing means closed."""
    try:
        day = normalize_weekday(check_day)
    except ValueError:
        return GARDEN_MODE_CLOSED
    return GARDEN_MODE_CLOSED if day == '无' else GARDEN_MODE_MULTI_ACCOUNT_WEEKLY


def migrate_garden_modes(master: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return a detached master with missing legacy modes mapped exactly once."""
    import copy

    result = copy.deepcopy(dict(master))
    profiles = result.get('profiles', {})
    if not isinstance(profiles, dict):
        return result, False
    changed = False
    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        tasks = profile.get('task_config')
        if not isinstance(tasks, dict):
            continue
        missing_mode = 'Garden Execution Mode' not in tasks
        if missing_mode:
            tasks['Garden Execution Mode'] = legacy_garden_execution_mode(
                tasks.get('Weekly Garden Check Day'))
            changed = True
        elif tasks.get('Garden Execution Mode') not in GARDEN_EXECUTION_MODES:
            continue
        if missing_mode:
            extensions = profile.setdefault('extensions', {})
            if isinstance(extensions, dict) and extensions.get('garden_execution_mode_migration') != 1:
                extensions['garden_execution_mode_migration'] = 1
    return result, changed


def account_field_metadata(tasks: Mapping[str, Any]) -> tuple[AccountFieldMetadata, ...]:
    result = []
    for key, value in tasks.items():
        label, help_text = _LABELS.get(key, (str(key), "账号专属任务设置；不会改变账号 UUID。"))
        identity = key in _IDENTITY
        editor = "bool" if isinstance(value, bool) else "choice" if key in _OPTIONS else "json" if isinstance(value, (list, dict)) else "text"
        options = tuple(_OPTIONS.get(key, ()))
        result.append(AccountFieldMetadata(
            str(key), label, help_text, editor, options,
            tuple(dict(TACET_OPTIONS)[option] if key == 'Which Tacet Suppression to Farm'
                  else dict(FORGERY_DOMAIN_OPTIONS)[option] if key == 'Which Forgery Challenge to Farm'
                  else str(localize_account_value(option)) for option in options), identity, identity or key == 'Record Pages'))
    return tuple(result)


__all__ = ["AccountFieldMetadata", "account_field_metadata", "localize_account_value",
           "restore_account_value", "GARDEN_MODE_DAILY", "GARDEN_MODE_MULTI_ACCOUNT_WEEKLY",
           "GARDEN_MODE_CLOSED", "GARDEN_EXECUTION_MODES", "legacy_garden_execution_mode",
           "migrate_garden_modes"]
