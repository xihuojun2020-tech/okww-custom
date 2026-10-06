"""Idempotent policy upgrades applied to startup and imported account bundles."""
from copy import deepcopy
from src.task.forgery_quota_plan import FORGERY_GOALS, FORGERY_MODE


def migrate_task_policy(master):
    result = deepcopy(master)
    task_configs = [account.get('task_config', {}) for account in result.get('profiles', {}).values()]
    template = result.get('extensions', {}).get('new_profile_template')
    if isinstance(template, dict):
        task_configs.append(template)
    for tasks in task_configs:
        tasks['Merge Echo on Sunday'] = False
        tasks.pop('Merge Echo If discarded > 1000', None)
        tasks.setdefault(FORGERY_MODE, 'materials' if tasks.get(FORGERY_GOALS) else 'unlimited')
    return result, result != master
