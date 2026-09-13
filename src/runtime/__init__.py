"""Small runtime service boundaries used by PC tasks."""

# Storage bootstrap imports this package before ok/config may initialize logs
# and repositories. Preserve the public API without eager application imports.
from importlib import import_module

_MODULES = {
    'account_selection_service': ('AccountSelectionService',),
    'account_verification_service': ('AccountVerificationService',),
    'login_flow_service': ('LoginFlowService',),
    'game_runtime_errors': ('FrameUnavailable', 'GameProcessLost'),
    'account_runtime_bootstrap': ('AccountRuntime', 'get_account_runtime', 'initialize_account_runtime',
                                'require_account_runtime_for_task', 'require_account_runtime_ready'),
    'sequence_snapshot_service': ('SequenceSnapshotService',),
    'task_run_coordinator': ('TaskRunCoordinator', 'TaskRunState'),
    'task_status_model': ('TaskStatusModel',),
}


def __getattr__(name):
    for module, names in _MODULES.items():
        if name in names:
            value = getattr(import_module('.' + module, __name__), name)
            globals()[name] = value
            return value
    raise AttributeError(name)

__all__ = [
    "AccountRuntime", "AccountSelectionService", "AccountVerificationService", "LoginFlowService",
    "FrameUnavailable", "GameProcessLost",
    "SequenceSnapshotService",
    "TaskRunCoordinator", "TaskRunState", "TaskStatusModel",
    "get_account_runtime", "initialize_account_runtime",
    "require_account_runtime_for_task", "require_account_runtime_ready",
]
