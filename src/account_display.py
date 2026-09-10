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
    code = short_profile_name(account.get('display_name')) or account.get('short_name') or '未命名账号'
    nickname = account.get('nickname') or legacy.get('nickname') or '未填昵称'
    phone = account.get('phone') or legacy.get('phone')
    masked = account.get('masked_phone') or (masked_phone(phone) if phone else '未填手机号')
    masked = re.sub(r'(?<!\d)(1[3-9]\d{9})(?!\d)', lambda m: masked_phone(m.group()), str(masked))
    return f'{code}-{nickname}-{masked}'


def account_option_labels(values):
    """Resolve one display batch from one repository read; never rewrite its keys."""
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
    labels = []
    for value in values:
        if not value or value in ('无', '（自动识别）'):
            labels.append(value)
            continue
        exact = [r for r in records if value in (r.profile_id, r.account.get('display_name'))]
        matches = exact or [r for r in records if value in (
            short_profile_name(r.account.get('display_name')), r.account.get('short_name'))]
        if len(matches) == 1:
            labels.append(account_display_label(matches[0].account))
        elif len(matches) > 1:
            labels.append(f'{value}-账号匹配不唯一')
        elif parse_account_label(value) or re.fullmatch(r'[A-Za-z]\d+', str(value)):
            labels.append(account_display_label({'display_name': value}))
        else:
            labels.append(value)
    return labels


def account_option_label(value):
    return account_option_labels([value])[0]
