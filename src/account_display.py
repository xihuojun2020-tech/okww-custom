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


def account_option_label(value):
    if not value or value == '无':
        return value
    from src.account_repository import get_default_repository
    repository = get_default_repository()
    if repository is not None:
        from src.account_repository import AccountRepositoryError
        try:
            records = repository.list_profiles()
            exact = [r for r in records if value in (r.profile_id, r.account.get('display_name'))]
            matches = exact or [r for r in records if short_profile_name(r.account.get('display_name')) == value]
            if len(matches) == 1:
                return account_display_label(matches[0].account)
        except AccountRepositoryError:
            pass
    return account_display_label({'display_name': value}) if parse_account_label(value) else value
