"""Synthetic upload timings; never reads or modifies production batches."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.runtime import diagnostic_uploader as uploader
from src.runtime.diagnostic_export import atomic_json, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision')
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        module = uploader
        if args.revision:
            source = subprocess.check_output(['git', 'show', args.revision + ':src/runtime/diagnostic_uploader.py'])
            path = base / 'baseline.py'
            path.write_bytes(source)
            spec = importlib.util.spec_from_file_location('upload_baseline', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        target = (args.target / '测试/upload-benchmark' / uuid.uuid4().hex) if args.target else base / 'nas'
        for files, total in ((1, 0), (12, 26 * 1024**2)):
            for iteration in range(3):
                batch = base / uuid.uuid4().hex
                prefix = f'日志/okww-custom/2026-09-13/benchmark/{batch.name}'
                entries = []
                for i in range(files):
                    name = f'{prefix}/{i}.log'
                    data = (b'synthetic benchmark data\n' * (total // files // 25 + 1))[:total // files]
                    path = batch / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    entries.append({'path': name, 'size': len(data), 'sha256': digest(data)})
                atomic_json(batch / 'manifest.json', {'schema_version': 1, 'run_id': 'benchmark',
                    'batch_id': batch.name, 'files': entries})
                (batch / '_READY').write_text(digest((batch / 'manifest.json').read_bytes()))
                for mode in ('initial', 'reuse'):
                    started = time.perf_counter()
                    module.upload_one(batch, target)
                    results.append({'files': files, 'bytes': sum(i['size'] for i in entries),
                        'iteration': iteration, 'mode': mode, 'seconds': time.perf_counter()-started})
                # Remove only the synthetic completion marker, leaving payloads for interrupted-resume timing.
                marker = target / '待分析' / prefix / '_UPLOAD_COMPLETE'
                started = time.perf_counter()
                marker.unlink()
                cleanup_seconds = time.perf_counter() - started
                started = time.perf_counter()
                module.upload_one(batch, target)
                results.append({'files': files, 'bytes': sum(i['size'] for i in entries),
                    'iteration': iteration, 'mode': 'resume_before_marker',
                    'seconds': time.perf_counter()-started, 'test_marker_delete_seconds': cleanup_seconds})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'revision': args.revision or 'working-tree',
            'target': str(target), 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(args.output)


if __name__ == '__main__':
    main()
