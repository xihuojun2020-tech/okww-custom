"""Incremental collection of this installation's newly written log/image files."""
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from src.runtime.diagnostic_export import atomic_json, safe_path, digest, sanitize_file

LOG_TYPES = {'.log', '.txt', '.json', '.jsonl'}
IMAGE_TYPES = {'.png', '.jpg', '.jpeg'}


class FileCollector:
    def __init__(self, source, root, *, current_run_started_at=None):
        # Resolve Windows 8.3 aliases (RUNNER~1 vs runneradmin) before
        # comparing paths discovered by os.walk.
        self.source, self.root = Path(source).resolve(), Path(root)
        self.path = self.root / 'source-cursors.json'
        if self.path.exists():
            self.cursors = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            # Taken before the first new-policy run; never backfill old files.
            self.cursors = {name: dict(self.stamp(path), pre_policy=True) for name, path in self.files()}
            for name, path in self.files():
                if (current_run_started_at is not None and path.suffix.lower() in LOG_TYPES
                        and path.stat().st_mtime >= current_run_started_at - 5):
                    self.cursors[name].update(offset=0, prefix_size=0, prefix_hash=digest(b''),
                                              mtime=0, pre_policy=False)
            atomic_json(self.path, self.cursors)

    def files(self):
        for folder in ('logs', 'screenshots'):
            base = safe_path(self.source, folder)
            if folder == 'screenshots':
                from src.runtime.diagnostic_storage import storage_path
                base = storage_path('screenshots', base, repo=self.source)
            for directory, folders, names in os.walk(base, followlinks=False):
                folders[:] = [n for n in folders if not (Path(directory) / n).is_symlink()
                              and not (Path(directory) / n).is_junction()]
                for name in sorted(names):
                    path = Path(directory) / name
                    if path.suffix.lower() in LOG_TYPES | IMAGE_TYPES:
                        relative = folder + '/' + path.relative_to(base).as_posix()
                        yield relative, safe_path(base, path.relative_to(base).as_posix())

    @staticmethod
    def stamp(path):
        stat = path.stat()
        with path.open('rb') as stream:
            prefix = stream.read(min(4096, stat.st_size))
        return {'size': stat.st_size, 'mtime': stat.st_mtime_ns, 'inode': stat.st_ino,
                'offset': stat.st_size, 'prefix_size': len(prefix), 'prefix_hash': digest(prefix)}

    def collect(self, run):
        changed, failed = 0, False
        for name, path in self.files():
            if changed >= 32:
                break
            try:
                changed += bool(self._collect_file(run, name, path))
            except (OSError, ValueError) as error:
                failed = True
                # One malformed/newly-written file must not block the other evidence.
                from src.runtime.diagnostic_export import sanitize_text
                atomic_json(self.root / 'collector-error.json', {
                    'error': sanitize_text(error), 'file': sanitize_text(name), 'time': time.time()})
                try:
                    self.cursors.setdefault(name, {})['failed_stamp'] = self.stamp(path)
                    atomic_json(self.path, self.cursors)
                except OSError:
                    pass
        if changed:
            atomic_json(self.path, self.cursors)
            if not failed:
                (self.root / 'collector-error.json').unlink(missing_ok=True)

    def acknowledge(self, path):
        """Record a source file already captured directly by the session worker."""
        path = Path(path).resolve()
        try:
            relative = path.relative_to(self.source).as_posix()
        except ValueError:
            from src.runtime.diagnostic_storage import storage_path
            base = storage_path('screenshots', self.source / 'screenshots', repo=self.source).resolve()
            try:
                relative = 'screenshots/' + path.relative_to(base).as_posix()
            except ValueError:
                return False
        if not relative.startswith(('logs/', 'screenshots/')) or path.suffix.lower() not in LOG_TYPES | IMAGE_TYPES:
            return False
        self.cursors[relative] = self.stamp(path)
        atomic_json(self.path, self.cursors)
        return True

    def _collect_file(self, run, name, path):
        from src.runtime.diagnostic_session import seal_run
        previous = self.cursors.get(name, {})
        stat = path.stat()
        # Unchanged history needs no open/hash. Changed files still undergo the
        # prefix and identity checks below, including truncation/replacement.
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino) == (
                previous.get('size'), previous.get('mtime'), previous.get('inode')):
            return False
        current = self.stamp(path)
        if self.same_stamp(current, previous.get('failed_stamp', {})):
            return False
        current.update(pre_policy=previous.get('pre_policy', False), run_id=run.name,
                       collected_at=time.time())
        if all(current.get(k) == previous.get(k) for k in ('size', 'mtime', 'inode')):
            return False
        suffix = path.suffix.lower()
        staging = run / 'collecting'
        staging.mkdir(exist_ok=True)
        staged = staging / (digest(name.encode()) + suffix)
        if suffix in IMAGE_TYPES:
            folder = run / 'screenshots'
            folder.mkdir(exist_ok=True)
            stage = folder / (uuid.uuid4().hex + suffix)
            shutil.copyfile(path, staged)
            # If still being written, leave its cursor untouched for the next scan.
            if any(self.stamp(path)[key] != current[key] for key in ('size', 'mtime', 'inode')):
                staged.unlink()
                return False
            sanitize_file(staged, reviewed_image=True)
            staged.replace(stage)
            seal_run(run, 'screenshot', sizes={}, reviewed_images=[stage])
            self._mark_sealed(run, 'screenshots/' + stage.name, stage.stat().st_size)
        else:
            offset = previous.get('offset', 0)
            with path.open('rb') as stream:
                same_prefix = digest(stream.read(previous.get('prefix_size', 0))) == previous.get('prefix_hash')
            if suffix == '.json' or not same_prefix or current['inode'] != previous.get('inode') or current['size'] < offset:
                offset = 0
            with path.open('rb') as stream:
                stream.seek(offset)
                data = stream.read(min(current['size'] - offset, 32 * 1024 * 1024))
            if not data:
                return False
            if suffix != '.json' and not data.endswith(b'\n') and offset + len(data) < current['size']:
                end = data.rfind(b'\n')
                if end < 0:
                    return False
                data = data[:end + 1]
            stage = run / ('collected-' + uuid.uuid4().hex + suffix)
            staged.write_bytes(data)
            sanitize_file(staged)
            staged.replace(stage)
            seal_run(run, 'collected', sizes={stage: len(data)})
            self._mark_sealed(run, stage.name, len(data))
            current['offset'] = offset + len(data)
            if current['offset'] != current['size']:
                current['mtime'] = 0  # More data remains even if the source stops changing.
        self.cursors[name] = current

        return True

    @staticmethod
    def same_stamp(current, previous):
        return all(current.get(k) == previous.get(k) for k in ('size', 'mtime', 'inode'))

    def changed(self, name, path):
        stat = path.stat()
        current = {'size': stat.st_size, 'mtime': stat.st_mtime_ns, 'inode': stat.st_ino}
        previous = self.cursors.get(name, {})
        return not self.same_stamp(current, previous) and not self.same_stamp(current, previous.get('failed_stamp', {}))

    @staticmethod
    def _mark_sealed(run, name, size):
        path = run / 'sealed-offsets.json'
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        state[name] = size
        atomic_json(path, state)


def collect_after_exit(root, source):
    """The system task also collects files saved after the application's last flush."""
    if not (Path(root) / 'source-cursors.json').exists():
        return  # Only the actual first program start establishes the historical boundary.
    from src.runtime.diagnostic_session import DiagnosticSession, FileLease
    import re
    try:
        # Avoid even scanning while the main process owns the collector.
        with FileLease(Path(root) / '.collector.lock'):
            collector = FileCollector(source, root)
            changed = any(collector.changed(n, p) for n, p in collector.files())
        if not changed:
            return
        version = re.search(r'^version\s*=\s*"([0-9.]+)"', (Path(source) / 'config.py').read_text(encoding='utf-8'), re.M)
        session = DiagnosticSession(root, version[1] if version else 'unknown', source_root=source)
        session.metadata['collector_only'] = True
        session.finish(timeout=15)
    except OSError:
        return  # Another program start won the lease, or disk is unavailable.
