"""Explicit legacy-label backfill; never rename profiles or change task records."""
import copy
from src.account_display import parse_account_label, account_display_label
from src.account_rebind_service import AccountRebindService
from src.account_repository import ProfileEditScope, ProfileRevisionConflict
from src.account_identity import AccountIdentityError


def plan_cleanup(repository):
    service = AccountRebindService(repository)
    plan = []
    for listed in repository.list_profiles():
        record = repository.load_profile(listed.profile_id)
        parsed = parse_account_label(record.account.get('display_name'))
        proposed, conflicts = {}, []
        for key in ('nickname', 'phone', 'masked_phone'):
            if key not in parsed:
                continue
            current = record.account.get(key)
            if not current:
                proposed[key] = parsed[key]
            elif current != parsed[key]:
                conflicts.append(key)
        if proposed and not conflicts:
            try:
                service.preview(record.profile_id, proposed)
            except AccountIdentityError:
                conflicts.append('身份冲突')
        plan.append({'record': record, 'changes': proposed, 'conflicts': conflicts,
                     'label': account_display_label(record.account)})
    return plan


def apply_cleanup(repository, plan):
    for entry in plan:
        record = entry['record']
        current = repository.load_profile(record.profile_id)
        if current.account != record.account or current.tasks != record.tasks:
            raise ProfileRevisionConflict('账号资料已变化，请重新生成整理清单')
    changed = []
    for entry in plan:
        if entry['conflicts'] or not entry['changes']:
            continue
        record = repository.load_profile(entry['record'].profile_id)
        if record.account != entry['record'].account or record.tasks != entry['record'].tasks:
            raise ProfileRevisionConflict('账号资料已变化，请重新生成整理清单')
        AccountRebindService(repository).preview(record.profile_id, entry['changes'])
        repository.backup_profile(record.profile_id, {
            'profile_id': record.profile_id, 'revision': record.revision,
            'account': copy.deepcopy(dict(record.account)), 'tasks': copy.deepcopy(dict(record.tasks)),
            'reason': 'legacy_label_backfill'})
        account = {**record.account, **entry['changes']}
        repository.publish_profile(ProfileEditScope(record.profile_id, record.revision),
                                   {'account': account, 'tasks': dict(record.tasks)})
        changed.append(entry['label'])
    return changed
