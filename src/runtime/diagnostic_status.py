"""Read-only diagnostic snapshots and explicit, scoped queue operations."""
from collections import Counter
from datetime import datetime
import json
import time
from pathlib import Path

from src.runtime.diagnostic_export import safe_path, atomic_json, sanitize_text

STATUS = {'pending':'排队', 'uploading':'上传中', 'retrying':'等待重试', 'blocked':'被阻塞',
          'uploaded':'上传器已校验', 'logs_purged':'日志已按策略清理', 'unknown':'状态不可读',
          'copied':'已复制，待批次完成确认', 'partial':'部分截图尚未上传', 'missing':'未找到封存文件'}


def read_json(path, default=None):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else default
    except (OSError, ValueError, TypeError):
        return default


class DiagnosticIndex:
    """One worker at a time; cache immutable batches, return detached UI data."""
    def __init__(self, root, source=None):
        self.root = Path(root)
        self.cache = {}
        self.source = Path(source) if source is not None else None

    def snapshot(self):
        batches, files, incidents, warnings = [], [], {}, []
        present = set()
        for ready in self.root.glob('*/batches/*/_READY'):
            batch = ready.parent
            key = batch.parents[1].name + '--' + batch.name
            present.add(key)
            manifest = self.cache.get(key)
            if manifest is None:
                manifest = read_json(batch / 'manifest.json')
                if not isinstance(manifest, dict):
                    warnings.append(f'{key} 清单不可读')
                    continue
                members = manifest.get('files')
                if (not isinstance(members, list) or not isinstance(manifest.get('created_at',0),(int,float))
                        or any(not isinstance(f,dict) or not isinstance(f.get('size'),int)
                               or not isinstance(f.get('path'),str) for f in members)):
                    warnings.append(f'{key} 清单字段损坏')
                    continue
                self.cache[key] = manifest
            state_path = self.root / 'states' / (key + '.json')
            state = read_json(state_path, {'status':'unknown' if state_path.exists() else 'pending'})
            if not isinstance(state, dict):
                state = {'status':'unknown'}
            status = state.get('status', 'pending')
            row = dict(key=key, run_id=manifest.get('run_id'), batch_id=batch.name,
                       kind=manifest.get('kind'), created_at=manifest.get('created_at',0),
                       status=status, attempts=state.get('attempts',0), next_retry=state.get('next_retry',0),
                       uploaded_at=state.get('uploaded_at',0), error=sanitize_text(state.get('last_error') or ''),
                       size=sum(f.get('size',0) for f in manifest.get('files',[])),
                       count=len(manifest.get('files',[])), local=str(batch),
                       progress=read_json(batch/'transfer-progress.json', {}))
            batches.append(row)
            from src.runtime.diagnostic_uploader import control_directory
            from src.runtime.nas_location import DEFAULT_TARGET
            try:
                row['remote'] = str(Path(DEFAULT_TARGET) / '待分析' / control_directory(manifest))
            except (ValueError, KeyError, IndexError):
                row['remote'] = ''
            row['source_ranges'] = [r for r in manifest.get('source_ranges', []) if isinstance(r,dict)]
            for file_index, item in enumerate(manifest.get('files',[])):
                name = item.get('path','')
                try:
                    local = safe_path(batch, name)
                except (ValueError,OSError):
                    warnings.append(f'{key} 非法文件路径')
                    continue
                file_status = status
                if status not in ('uploaded', 'logs_purged') and file_index < row['progress'].get('completed_files', 0):
                    file_status = 'copied'
                files.append(dict(row, path=name, local=str(local), size=item.get('size',0), file_status=file_status,
                                  sha256=item.get('sha256',''), type='截图' if name.startswith('截图/') else '日志/索引'))
                if local.name == 'incident.json':
                    incident_key = key + ':incident'
                    incident = self.cache.get(incident_key)
                    if incident is None:
                        incident = read_json(local, {})
                        self.cache[incident_key] = incident
                    if not isinstance(incident, dict) or not incident.get('incident_id'):
                        continue
                    identity = (incident.get('run_id'),incident['incident_id'])
                    previous = incidents.get(identity)
                    if previous is None or incident.get('revision',0)>previous.get('revision',0):
                        incidents[identity] = dict(incident, batch_key=key, upload_status=status,
                                                  local=str(local), upload_error=row['error'])
        self.cache = {k:v for k,v in self.cache.items() if k.split(':')[0] in present}
        file_map = {f['path']: f for f in files}
        for incident in incidents.values():
            incident['frames'] = [dict(f) for f in incident.get('frames', [])]
            incomplete = False
            for frame in incident['frames']:
                item = file_map.get(frame.get('remote_path'))
                frame['upload_status'] = item['file_status'] if item else 'missing'
                incomplete |= frame['upload_status'] not in ('uploaded', 'logs_purged')
            if incomplete and incident['upload_status'] in ('uploaded', 'logs_purged'):
                incident['upload_status'] = 'partial'
        source_batches = {}
        for b in batches:
            for extent in b['source_ranges']:
                source_batches.setdefault(extent.get('source'), []).append(
                    dict(key=b['key'], status=b['status'], range=extent))
        cursors = read_json(self.root/'source-cursors.json', {})
        sources = []
        for name, value in cursors.items() if isinstance(cursors,dict) else []:
            if not isinstance(value, dict):
                warnings.append('来源游标不可读：' + name)
                continue
            sources.append(dict(source=name, size=value.get('size',0), offset=value.get('offset',0),
                                remaining=max(0,value.get('size',0)-value.get('offset',0)),
                                collected_at=value.get('collected_at',0), pre_policy=value.get('pre_policy',False),
                                failed=bool(value.get('failed_stamp')), run_id=value.get('run_id','')))
            sources[-1]['batches'] = source_batches.get(name, [])
            if self.source is not None:
                try:
                    from src.runtime.diagnostic_storage import storage_path
                    folder, relative = name.split('/', 1)
                    base = storage_path(folder, self.source / folder, repo=self.source) if folder == 'screenshots' else self.source / folder
                    path = safe_path(base, relative)
                    stat = path.stat()
                    same = stat.st_ino == value.get('inode') and stat.st_size >= value.get('offset', 0)
                    sources[-1].update(local=str(path), live_size=stat.st_size,
                        remaining=max(0, stat.st_size-value.get('offset', 0)) if same else None,
                        rotated=not same)
                except (OSError, ValueError):
                    sources[-1].update(live_size=None, remaining=None, source_error='源文件不可用或正在轮转')
        result = dict(updated_at=time.time(), batches=sorted(batches,key=lambda x:x['created_at'],reverse=True),
                      files=files, incidents=sorted(incidents.values(),key=lambda x:x.get('triggered_at',''),reverse=True),
                      sources=sources, warnings=warnings, counts=dict(Counter(x['status'] for x in batches)),
                      scheduler=read_json(self.root/'scheduler.json',{}),
                      collector=read_json(self.root/'collector-error.json',{}),
                      pending_bytes=sum(x['size'] for x in batches if x['status'] not in ('uploaded','logs_purged')))
        # No dictionaries shared with the worker cache or a producer reach Qt.
        return json.loads(json.dumps(result))


def retry_batches(root, keys):
    from src.runtime.diagnostic_session import FileLease
    from src.runtime.diagnostic_queue import queue_batch
    count = 0
    with FileLease(Path(root)/'.uploader.lock'):
        for key in keys:
            run,batch_id = key.split('--',1)
            batch = safe_path(root, f'{run}/batches/{batch_id}')
            if not (batch/'_READY').is_file():
                continue
            state_file = safe_path(root,'states/'+key+'.json')
            state = read_json(state_file)
            if state is None and state_file.exists():
                continue
            state = state or {}
            if state.get('status') not in ('pending','retrying',None):
                continue  # Never clear blocked corruption or interrupt a running transfer.
            state.update(status='pending',next_retry=0)
            atomic_json(state_file,state)
            queue_batch(batch)
            count += 1
    return count


def verify_batch(batch, target):
    from src.runtime.diagnostic_uploader import bounded_read, control_directory, validate_remote
    from src.runtime.diagnostic_export import digest
    from src.runtime.nas_location import DEFAULT_TARGET
    if str(target).rstrip('\\/') != DEFAULT_TARGET:
        raise ValueError('只允许核验173上的项目诊断目录')
    raw = bounded_read(Path(batch),'manifest.json',1024*1024)
    manifest = json.loads(raw)
    control = safe_path(Path(target)/'待分析',control_directory(manifest))
    marker_name = '_LOGS_PURGED' if (control/'_LOGS_PURGED').exists() else '_UPLOAD_COMPLETE'
    marker = bounded_read(control,marker_name,64).decode('ascii')
    if marker != digest(raw):
        raise ValueError('远端完成标记与本地清单不一致')
    verified = validate_remote(control)
    return {'verified_at':time.time(),'path':str(control),'files':len(verified['files']),
            'logs_purged': verified.get('logs_purged', False)}


def backfill_preview(source, start, end, limit=32*1024*1024):
    """Only timestamped plain log lines; no credentials/config JSON or cursor mutation."""
    import re
    if start>=end:
        raise ValueError('结束时间必须晚于开始时间')
    rows=[]; selected_bytes=0
    for path in (Path(source)/'logs').rglob('*.log'):
        if path.is_symlink() or any(p.is_junction() or p.is_symlink() for p in [path.parent,*path.parents] if p.exists()):
            continue
        if path.stat().st_size>limit:
            rows.append(dict(path=str(path),error='超过32MiB，请先按时间拆分日志'))
            continue
        selected=[]; include=False
        for line in path.read_text(encoding='utf-8',errors='replace').splitlines(keepends=True):
            match=re.match(r'^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)',line)
            if match:
                stamp=datetime.fromisoformat(match[1]+'T'+match[2])
                include=start<=stamp<end
            if include:selected.append(line)
        if selected:
            content=sanitize_text(''.join(selected))
            size=len(content.encode('utf-8'));selected_bytes+=size
            if selected_bytes>limit:
                raise ValueError('所选时间日志合计超过32MiB，请缩小范围')
            rows.append(dict(path=str(path),source='logs/'+path.relative_to(Path(source)/'logs').as_posix(),
                             bytes=size,content=content,start_time=start.isoformat(),end_time=end.isoformat()))
    if sum(x.get('bytes',0) for x in rows)>limit:
        raise ValueError('所选时间日志合计超过32MiB，请缩小范围')
    return rows


def enqueue_backfill(root, rows, version):
    import uuid
    from src.runtime.diagnostic_session import seal_run
    from src.runtime.diagnostic_policy import POLICY
    selected=[r for r in rows if r.get('content')]
    if not selected:raise ValueError('所选时间没有可补传日志')
    run=Path(root)/('manual-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    atomic_json(run/'metadata.json',dict(run_id=run.name,version=version,policy=POLICY,
                started_at=datetime.now().isoformat(),collector_only=True,process_status='exited'))
    sizes={}
    for n,row in enumerate(selected):
        path=run/f'collected-manual-{n}.log'
        path.write_text(row['content'],encoding='utf-8');sizes[path]=path.stat().st_size
    batch=seal_run(run,'manual_log_backfill',sizes=sizes,source_ranges=[{
        'source': r.get('source','logs/' + Path(r['path']).name), 'manual': True, 'bytes': r['bytes'],
        'start_time':r.get('start_time'), 'end_time':r.get('end_time'),
    } for r in selected])
    return str(batch)

def bounded_verify(batch, target):
    import os,subprocess,sys
    result=subprocess.run([sys.executable,'-m','src.runtime.diagnostic_status','--verify',str(batch),str(target)],
                          capture_output=True,text=True,encoding='utf-8',timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:raise RuntimeError(result.stderr[-1500:])
    return json.loads(result.stdout)


if __name__=='__main__':
    import sys
    if len(sys.argv)==4 and sys.argv[1]=='--verify':
        from src.runtime.diagnostic_policy import connect
        from src.runtime.nas_location import DEFAULT_TARGET
        if sys.argv[3]!=DEFAULT_TARGET:raise ValueError('只允许173')
        connect(DEFAULT_TARGET)
        print(json.dumps(verify_batch(sys.argv[2],DEFAULT_TARGET)))
