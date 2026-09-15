"""Explicit, verified ZIP handoff; originals and sealed batches remain intact."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

from src.runtime.diagnostic_export import atomic_json, safe_path, validate_manifest
from src.runtime.diagnostic_session import FileLease
from src.runtime.diagnostic_policy import DEFAULT_TARGET, connect


def hash_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build_archive(root):
    root = Path(root).resolve()
    from src.runtime import diagnostic_lifecycle
    session = diagnostic_lifecycle._session
    if session is not None and session.root.resolve() == root and not session.closed_session:
        session.flush_for_archive()
    directory = root / 'archives'
    directory.mkdir(exist_ok=True)
    name = 'okww诊断证据_' + time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    archive = directory / (name + '.zip')
    receipt = archive.with_suffix('.json')
    pending = archive.with_suffix('.zip.partial')
    entries, logs, references = [], {}, []
    with FileLease(root / '.archive.lock'), FileLease(root / '.uploader.lock'):
        try:
            with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as package:
                for ready in sorted(root.glob('*/batches/*/_READY')):
                    batch = ready.parent
                    key = batch.parents[1].name + '--' + batch.name
                    state_path = root / 'states' / (key + '.json')
                    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
                    if state.get('status') in ('uploaded', 'logs_purged'):
                        continue
                    manifest_path = batch / 'manifest.json'
                    sha = hash_file(manifest_path)
                    if ready.read_text(encoding='ascii') != sha:
                        raise ValueError(f'批次尚未完整封存：{key}')
                    manifest = validate_manifest(batch, json.loads(manifest_path.read_text(encoding='utf-8')))
                    prefix = 'batches/' + key + '/'
                    package.write(manifest_path, prefix + 'manifest.json')
                    package.write(ready, prefix + '_READY')
                    for item in manifest['files']:
                        source = safe_path(batch, item['path'])
                        if source.name == 'incident.json':
                            incident = json.loads(source.read_text(encoding='utf-8'))
                            for frame in incident.get('frames', []):
                                if frame.get('remote_path') and frame.get('batch_id'):
                                    references.append((batch.parents[1].name, frame))
                        package.write(source, prefix + item['path'], compress_type=(
                            zipfile.ZIP_STORED if source.suffix == '.png' else zipfile.ZIP_DEFLATED))
                        if source.suffix in ('.log', '.txt', '.jsonl'):
                            logs.setdefault(batch.parents[1].name, []).append((manifest.get('created_at', 0), source))
                    entries.append({'key': key, 'manifest_sha256': sha})
                    if len(entries) % 32 == 0:
                        atomic_json(directory / 'progress.json', {'status': 'packing', 'batches': len(entries)})
                if not entries:
                    raise ValueError('没有尚未上传的已封存资料')
                dependencies, missing = [], []
                names = set(package.namelist())
                for run, frame in references:
                    relative = frame['remote_path']
                    key = run + '--' + frame['batch_id']
                    name = 'batches/' + key + '/' + relative
                    if name in names:
                        continue
                    source = safe_path(root, run + '/batches/' + frame['batch_id'] + '/' + relative)
                    if not source.is_file() or hash_file(source) != frame.get('sha256'):
                        missing.append({'run': run, 'path': relative, 'reason': '本地缺失或校验不匹配'})
                        continue
                    package.write(source, name, compress_type=zipfile.ZIP_STORED)
                    names.add(name)
                    dependencies.append({'path': name, 'sha256': frame['sha256']})
                for run, sources in logs.items():
                    with package.open(f'sessions/{run}/日志汇总.log', 'w', force_zip64=True) as out:
                        for _, source in sorted(sources, key=lambda item: (item[0], str(item[1]))):
                            out.write(('\n--- 来源：' + source.relative_to(root).as_posix() + ' ---\n').encode('utf-8'))
                            with source.open('rb') as stream:
                                shutil.copyfileobj(stream, out, 1024**2)
                package.writestr('说明.txt', '每次启动按会话分组。日志汇总为按批次时间排列的来源片段；原始日志和截图位于 batches。\n'
                    '运行中的会话仅覆盖打包时已封存范围；之后的记录保留下次上传。\n'
                    'SHA256 清单位于 manifest.json，可直接分析本 ZIP，无需展开到 NAS。')
                package.writestr('manifest.json', json.dumps({'schema': 1, 'created_at': time.time(),
                    'batches': entries, 'sessions': list(logs), 'image_dependencies': dependencies,
                    'missing_dependencies': missing}, ensure_ascii=False))
            with zipfile.ZipFile(pending) as package:
                broken = package.testzip()
                if broken:
                    raise ValueError('压缩包校验失败：' + broken)
            pending.replace(archive)
            atomic_json(receipt, {'schema': 1, 'root': str(root), 'sha256': hash_file(archive),
                                  'size': archive.stat().st_size, 'batches': entries, 'status': 'packed'})
            atomic_json(directory / 'progress.json', {'status': 'packed', 'archive': str(archive), 'batches': len(entries)})
            return archive
        finally:
            pending.unlink(missing_ok=True)


def upload_archive(archive, target=DEFAULT_TARGET):
    archive = Path(archive).resolve()
    receipt_path = archive.with_suffix('.json')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    root = Path(receipt['root']).resolve()
    if archive.parent != root / 'archives' or archive.stat().st_size != receipt['size']:
        raise ValueError('本地压缩包路径或大小校验失败')
    connect(target)
    destination = Path(target) / '待分析/压缩包'
    destination.mkdir(parents=True, exist_ok=True)
    remote = safe_path(destination, archive.name)
    partial = safe_path(destination, archive.name + '.partial')
    with FileLease(root / '.archive.lock'), FileLease(root / '.uploader.lock'):
        reviewed = safe_path(target, '已检查/压缩包/' + archive.name)
        if not remote.exists() and reviewed.exists():
            remote = reviewed
        if not remote.exists():
            complete_partial = partial.exists() and partial.stat().st_size == receipt['size']
            if not complete_partial:
                with archive.open('rb') as source, partial.open('wb') as out:
                    copied, updated = 0, 0
                    while block := source.read(4 * 1024**2):
                        out.write(block)
                        copied += len(block)
                        if time.monotonic() - updated >= 1:
                            updated = time.monotonic()
                            atomic_json(archive.parent / 'progress.json', {'status': 'uploading',
                                'copied': copied, 'total': receipt['size'], 'archive': str(archive)})
                    out.flush()
                    os.fsync(out.fileno())
            if partial.stat().st_size != receipt['size']:
                raise ValueError('NAS 压缩包大小校验失败')
            partial.replace(remote)
        if remote.stat().st_size != receipt['size']:
            raise ValueError('NAS 已有同名压缩包大小冲突')
        remote_receipt = remote.with_suffix('.json')
        uploaded_at = time.time()
        if remote_receipt.exists():
            uploaded_at = json.loads(remote_receipt.read_text(encoding='utf-8')).get('uploaded_at', uploaded_at)
        atomic_json(remote_receipt, {'sha256': receipt['sha256'], 'size': receipt['size'],
                                    'uploaded_at': uploaded_at})
        for item in receipt['batches']:
            run, batch_id = item['key'].split('--', 1)
            batch = safe_path(root, f'{run}/batches/{batch_id}')
            if hash_file(batch / 'manifest.json') != item['manifest_sha256']:
                raise ValueError('上传期间本地批次变化，未确认：' + item['key'])
            state_path = root / 'states' / (item['key'] + '.json')
            state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
            state.update(status='uploaded', transport='archive', archive=str(remote),
                         archive_sha256=receipt['sha256'], uploaded_at=time.time(), last_error=None)
            atomic_json(state_path, state)
            from src.runtime.diagnostic_queue import acknowledge
            acknowledge(batch)
        receipt.update(status='uploaded', remote=str(remote), uploaded_at=time.time())
        atomic_json(receipt_path, receipt)
        atomic_json(archive.parent / 'progress.json', {'status': 'uploaded', 'archive': str(remote)})
    return str(remote)


def send_archive(archive):
    archive = Path(archive)
    size = archive.stat().st_size
    timeout = min(3600, max(120, 60 + size / (512 * 1024)))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    result = subprocess.run([sys.executable, '-E', '-s', '-m', 'src.runtime.diagnostic_archive',
        '--upload', str(archive)], cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, timeout=timeout, creationflags=flags)
    if result.returncode:
        raise OSError('上传未完成，本地 ZIP 已保留：' + str(archive) + '\n' + result.stderr.decode('utf-8', errors='replace')[-500:])
    return json.loads(archive.with_suffix('.json').read_text(encoding='utf-8'))['remote']


def manual_upload(root):
    # Reuse the last intact local package after a failed/aborted upload before
    # packing new extents. No original or previous package is removed.
    root = Path(root)
    previous = None
    for receipt_path in sorted((root/'archives').glob('*.json'), reverse=True):
        if receipt_path.name == 'progress.json':
            continue
        value = json.loads(receipt_path.read_text(encoding='utf-8'))
        if value.get('status') in ('packed', 'oversized'):
            previous = send_archive(receipt_path.with_suffix('.zip'))
            break
    try:
        archive = build_archive(root)
    except ValueError as error:
        if previous and str(error) == '没有尚未上传的已封存资料':
            return previous
        raise
    return send_archive(archive)


def verify_archive(remote, expected):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    result = subprocess.run([sys.executable, '-E', '-s', '-m', 'src.runtime.diagnostic_archive',
        '--verify', str(remote), '--sha256', expected], cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, timeout=300, creationflags=flags)
    if result.returncode:
        raise ValueError('远端压缩包缺失或 SHA256 不匹配')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--upload', type=Path)
    mode.add_argument('--verify', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    if args.verify:
        connect(DEFAULT_TARGET)
        remote = args.verify
        if not remote.exists():
            remote = safe_path(DEFAULT_TARGET, '已检查/压缩包/' + remote.name)
        if hash_file(remote) != args.sha256:
            raise ValueError('checksum mismatch')
    else:
        upload_archive(args.upload)
