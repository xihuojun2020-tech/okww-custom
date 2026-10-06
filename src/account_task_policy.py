"""Idempotent policy upgrades applied to startup and imported account bundles."""
from copy import deepcopy
from src.task.forgery_quota_plan import FORGERY_MODE


def migrate_task_policy(master):
    result = deepcopy(master)
    task_configs = [account.get('task_config', {}) for account in result.get('profiles', {}).values()]
    template = result.get('extensions', {}).get('new_profile_template')
    if isinstance(template, dict):
        task_configs.append(template)
    for tasks in task_configs:
        tasks['Merge Echo on Sunday'] = False
        tasks.pop('Merge Echo If discarded > 1000', None)
        # A legacy farming choice carries no explicit quota-mode selection.
        tasks.setdefault(FORGERY_MODE, 'unlimited')
        from src.task.farming_task_queue import migrate_farming_tasks
        migrate_farming_tasks(tasks)
    return result, result != master
