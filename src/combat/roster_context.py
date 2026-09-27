"""Shared cache invalidation, not an authority for account authentication."""


def advance_roster_context(task, profile_id):
    executor = getattr(task, 'executor', None)
    if executor is not None:
        previous = executor.__dict__.get('_combat_roster_context', (None, 0))
        executor._combat_roster_context = (str(profile_id), previous[1] + 1)


def roster_context(task):
    executor = getattr(task, 'executor', None)
    shared = getattr(executor, '__dict__', {}).get('_combat_roster_context')
    identity = shared or getattr(task, '_verified_profile_id', None)
    return getattr(task.hwnd, 'hwnd', None), identity
