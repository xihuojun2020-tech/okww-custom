"""Local gamepack replacement and recovery; no game code or network imports."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from gameframe.packages import PackageManifest, extract_archive, verify_index
from gameframe.process_locks import package_lease


@dataclass(frozen=True)
class PreparedUpdate:
    transaction: Path
    package_id: str
    current_version: str
    target_version: str

    @property
    def installed(self):
        return self.transaction.parent.parent / self.package_id


@dataclass(frozen=True)
class UpdateOutcome:
    plan: PreparedUpdate
    status: str


def _write_journal(plan, phase):
    value = {'package_id': plan.package_id, 'current_version': plan.current_version,
             'target_version': plan.target_version, 'phase': phase}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=plan.transaction,
                                         prefix='.journal-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, plan.transaction / 'journal.json')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_journal(transaction):
    value = json.loads((transaction / 'journal.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', value['package_id']):
        raise ValueError('Invalid package ID in update journal')
    if value['phase'] not in {'prepared', 'switching', 'committed'}:
        raise ValueError('Invalid update journal phase')
    return PreparedUpdate(transaction, value['package_id'], value['current_version'],
                          value['target_version']), value['phase']


def _check_manifest(path, plan, version):
    manifest = PackageManifest.read(path)
    if manifest.id != plan.package_id or manifest.version != version:
        raise ValueError('Gamepack ID/version does not match the update transaction')
    return manifest


def _check_installed(plan):
    manifest = _check_manifest(plan.installed, plan, plan.current_version)
    if manifest.root != plan.installed or not (plan.installed / 'files.json').is_file():
        raise ValueError('Updates require an installed indexed gamepack; source checkout packages cannot be updated')


def _check_dependencies(installed, incoming):
    for name in ('requirements.txt', 'requirements-management.txt'):
        before, after = installed / name, incoming / name
        old = tuple(line.strip() for line in before.read_text(encoding='utf-8-sig').splitlines()
                    if line.strip() and not line.strip().startswith('#')) if before.is_file() else None
        new = tuple(line.strip() for line in after.read_text(encoding='utf-8-sig').splitlines()
                    if line.strip() and not line.strip().startswith('#')) if after.is_file() else None
        if old != new:
            raise ValueError(f'Gamepack {name} changed; a full environment upgrade is required')


def prepare_update(archive, packages_dir, *, package_id, current_version, target_version):
    """Stage an indexed archive, leaving the installed package untouched."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', package_id):
        raise ValueError('Invalid package ID')
    directory = Path(packages_dir).resolve()
    transaction = directory / '.gameframe-transactions' / uuid.uuid4().hex
    plan = PreparedUpdate(transaction, package_id, current_version, target_version)
    with package_lease(plan.installed):
        _check_installed(plan)
        extraction = transaction / 'extract'
        extraction.mkdir(parents=True)
        try:
            manifest = extract_archive(archive, extraction, require_index=True)
            _check_manifest(manifest.root, plan, target_version)
            _check_dependencies(plan.installed, manifest.root)
            manifest.root.rename(transaction / 'incoming')
            extraction.rmdir()
            _write_journal(plan, 'prepared')
        except BaseException:
            shutil.rmtree(transaction)
            raise
        return plan


def _rollback(plan):
    previous = plan.transaction / 'previous'
    incoming = plan.transaction / 'incoming'
    if previous.exists():
        _check_manifest(previous, plan, plan.current_version)
        if plan.installed.exists():
            _check_manifest(plan.installed, plan, plan.target_version)
            # Moving the new tree back first makes interrupted rollback recoverable.
            plan.installed.rename(incoming)
        previous.rename(plan.installed)
    else:
        # Interruption before the first rename, or after restoring the old tree.
        _check_manifest(plan.installed, plan, plan.current_version)
    shutil.rmtree(plan.transaction)


def apply_update(plan, *, ensure_idle, fault_hook=None):
    """Exclusively lease package code, then check the caller's owned processes.

    ensure_idle must raise while either worker or management owns the package;
    the launcher must serialize starting owners and this operation.
    Ordinary failures roll back. Process interruption leaves a recovery journal.
    """
    with package_lease(plan.installed, exclusive=True):
        stored, phase = _read_journal(plan.transaction)
        if stored != plan or phase != 'prepared':
            raise ValueError('Update transaction is not prepared')
        _check_installed(plan)
        incoming = plan.transaction / 'incoming'
        _check_manifest(incoming, plan, plan.target_version)
        verify_index(incoming, required=True)
        _check_dependencies(plan.installed, incoming)
        ensure_idle()
        _write_journal(plan, 'switching')
        committed = False
        try:
            ensure_idle()
            plan.installed.rename(plan.transaction / 'previous')
            if fault_hook is not None:
                fault_hook('after_old_rename')
            incoming.rename(plan.installed)
            if fault_hook is not None:
                fault_hook('after_new_rename')
            manifest = _check_manifest(plan.installed, plan, plan.target_version)
            verify_index(plan.installed, required=True)
            if fault_hook is not None:
                fault_hook('before_commit')
            _write_journal(plan, 'committed')
            committed = True
            if fault_hook is not None:
                fault_hook('after_commit')
            shutil.rmtree(plan.transaction)
            return manifest
        except Exception:
            if not committed:
                _rollback(plan)
            raise


def recover_updates(packages_dir, *, ensure_idle):
    """Recover directory swaps before discovering or launching any package."""
    directory = Path(packages_dir).resolve() / '.gameframe-transactions'
    outcomes = []
    for journal in sorted(directory.glob('*/journal.json')):
        # Read only the identity before locking; phase decisions use a locked reread.
        plan, _ = _read_journal(journal.parent)
        with package_lease(plan.installed):
            plan, phase = _read_journal(journal.parent)
            if phase == 'prepared':
                outcomes.append(UpdateOutcome(plan, 'prepared'))
                continue
        # Do not upgrade a shared lease: release it, then recheck under exclusive ownership.
        with package_lease(plan.installed, exclusive=True):
            plan, phase = _read_journal(journal.parent)
            if phase == 'prepared':
                outcomes.append(UpdateOutcome(plan, 'prepared'))
                continue
            ensure_idle()
            if phase == 'committed':
                _check_manifest(plan.installed, plan, plan.target_version)
                verify_index(plan.installed, required=True)
                shutil.rmtree(plan.transaction)
                status = 'committed'
            else:
                _rollback(plan)
                status = 'rolled_back'
            outcomes.append(UpdateOutcome(plan, status))
    return tuple(outcomes)
