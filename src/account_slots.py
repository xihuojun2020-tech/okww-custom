"""Fixed execution positions, separate from stable account identity and participation."""
import copy
import re

from src.account_identity import short_profile_name

FIXED_SEQUENCES = {'序列1': ('序列一', 'A'), '序列2': ('序列二', 'B')}
SLOT_KEY = 'fixed_sequence_slot_v1'


def account_slot(account):
    extensions = account.get('extensions', {})
    if SLOT_KEY in extensions:
        value = extensions[SLOT_KEY]
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {'sequence', 'slot'}:
            raise ValueError('账号槽位格式无效')
        sequence, slot = value['sequence'], value['slot']
        if sequence not in FIXED_SEQUENCES or slot not in slots_for(sequence):
            raise ValueError('账号槽位与序列不匹配')
        return dict(value)
    short = short_profile_name(account.get('display_name') or account.get('short_name'))
    match = re.fullmatch(r'([AB])([1-9]|10)', short or '')
    if not match:
        return None
    return {'sequence': '序列1' if match[1] == 'A' else '序列2', 'slot': short}


def slots_for(sequence):
    return tuple(FIXED_SEQUENCES[sequence][1] + str(number) for number in range(1, 11))


def slot_owners(accounts, sequence):
    result = {}
    for identity, account in accounts.items():
        row = account_slot(account)
        if row and row['sequence'] == sequence:
            result.setdefault(row['slot'], []).append(identity)
    return result


def ordered_members(accounts, members, sequence):
    if sequence not in FIXED_SEQUENCES:
        return list(members)
    owners = slot_owners(accounts, sequence)
    positions = {}
    for identity in members:
        row = account_slot(accounts[identity])
        if not row or row['sequence'] != sequence:
            raise ValueError(f'{FIXED_SEQUENCES[sequence][0]}有账号归属待核对，请在账号总览设置槽位')
        if len(owners[row['slot']]) != 1:
            raise ValueError(f"{row['slot']} 槽位重复绑定，请核对账号归属")
        positions[identity] = int(row['slot'][1:])
    return sorted(members, key=positions.__getitem__)


def validate_assignment(accounts, identity):
    row = account_slot(accounts[identity])
    if row and len(slot_owners(accounts, row['sequence'])[row['slot']]) != 1:
        raise ValueError(f"{row['slot']} 已被其他账号占用，请选择空槽位")


def migrate_slots(raw):
    candidate = copy.deepcopy(raw)
    profiles = candidate.get('profiles', {})
    for account in profiles.values():
        extensions = account.setdefault('extensions', {})
        if SLOT_KEY not in extensions:
            extensions[SLOT_KEY] = account_slot(account)
    for sequence in FIXED_SEQUENCES:
        members = candidate.setdefault('sequences', {}).setdefault(sequence, [])
        try:
            candidate['sequences'][sequence] = ordered_members(profiles, members, sequence)
        except ValueError:
            pass  # Preserve ambiguous legacy selections; runtime requires explicit repair.
    candidate.setdefault('extensions', {})['fixed_account_slots_v1'] = True
    return candidate, candidate != raw
