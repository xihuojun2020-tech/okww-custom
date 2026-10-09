"""Display-only account labels; persisted identity and selection keys stay stable."""
import re
from src.account_identity import masked_phone, short_profile_name


def parse_account_label(value):
    text = str(value or '').strip().strip('【】[]')
    match = re.fullmatch(r'([A-Za-z]\d+)-(.+)-(1[3-9]\d{9})', text)
    if not match:
        return {}
    code, nickname, phone = match.groups()
    return {'short_name': code.upper(), 'nickname': nickname.strip(),
            'phone': phone, 'masked_phone': masked_phone(phone)}


def account_display_label(account):
    legacy = parse_account_label(account.get('display_name'))
    from src.account_slots import account_slot, SLOT_KEY
    assignment = account_slot(account)
    code = (assignment['slot'] if assignment else '未分配' if SLOT_KEY in account.get('extensions', {})
            else short_profile_name(account.get('display_name')) or account.get('short_name') or '未命名账号')
    nickname = account.get('nickname') or legacy.get('nickname') or '未填昵称'
    phone = account.get('phone') or legacy.get('phone')
    masked = account.get('masked_phone') or (masked_phone(phone) if phone else '未填手机号')
    masked = re.sub(r'(?<!\d)(1[3-9]\d{9})(?!\d)', lambda m: masked_phone(m.group()), str(masked))
    return f'{code}-{nickname}-{masked}'


def account_sort_key(account, identity=''):
    """Order fixed positions numerically, independently of creation and participation."""
    from src.account_slots import account_slot
    assignment = account_slot(account)
    return (0 if assignment and assignment['sequence'] == '序列1' else 1 if assignment else 2,
            int(assignment['slot'][1:]) if assignment else 0,
            str(account.get('nickname') or '').casefold(), str(identity))


def account_option_items(values, *, sort=True):
    """Resolve labels and sort their original selection keys together in one read."""
    values = list(values)
    if not values:
        return []
    from src.account_repository import get_default_repository
    repository = get_default_repository()
    records = ()
    if repository is not None:
        from src.account_repository import AccountRepositoryError
        try:
            records = repository.list_profiles()
        except AccountRepositoryError:
            pass
    items = []
    for index, value in enumerate(values):
        if not value or value in ('无', '（自动识别）', '无序列'):
            items.append(((-1, index, '', ''), value, value))
            continue
        exact = [r for r in records if value in (r.profile_id, r.account.get('display_name'))]
        matches = exact or [r for r in records if value in (
            short_profile_name(r.account.get('display_name')), r.account.get('short_name'))]
        if len(matches) == 1:
            account = matches[0].account
            label = account_display_label(account)
            key = account_sort_key(account, matches[0].profile_id)
        elif len(matches) > 1:
            label, key = f'{value}-账号匹配不唯一', (2, 0, '', str(value))
        elif parse_account_label(value) or re.fullmatch(r'[A-Za-z]\d+', str(value)):
            account = {'display_name': value}
            label, key = account_display_label(account), account_sort_key(account, value)
        else:
            label, key = value, (2, 0, '', str(value))
        items.append((key, value, label))
    if sort:
        items.sort(key=lambda item: item[0])
    return [(value, label) for _, value, label in items]


def account_option_labels(values):
    """Keep caller order for labels used alongside persisted sequences."""
    return [label for _, label in account_option_items(values, sort=False)]


def account_option_label(value):
    return account_option_labels([value])[0]
