"""Call the shared production bootstrap, without a second game implementation."""

import argparse
import importlib
import json
from pathlib import Path
import sys
import threading


def run(source_root, task_class=None, stop_event=None, *, control_stream=None):
    source = Path(source_root).resolve()
    sys.path.insert(0, str(source))
    # OK parses --headless while constructing its singleton. It must be present
    # before importing the production entrypoint, not injected after creation.
    sys.argv = [str(source / 'main.py')]
    if task_class is not None:
        sys.argv.append('--headless')
    main = importlib.import_module('main')
    if control_stream is not None:
        # On Windows NumPy initializes through stdin's buffered lock. A blocking
        # listener must not acquire that lock before the extension is loaded.
        import numpy
        threading.Thread(target=listen_stop, args=(stop_event, control_stream), daemon=True).start()
    return main.run_application(task=task_class, stop_event=stop_event)


def _close_runtime_services():
    # Only close genuinely loaded services. An early production import failure
    # must not cause a new cleanup import that masks its original exception.
    evidence = sys.modules.get('src.evidence.service')
    diagnostics = sys.modules.get('src.runtime.diagnostic_lifecycle')
    try:
        if evidence is not None:
            evidence.close_existing_evidence_service()
    finally:
        if diagnostics is not None:
            diagnostics.finish_diagnostics(timeout=None)


def listen_stop(stop, stream):
    for line in stream:
        try:
            command = json.loads(line)['command']
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            print(json.dumps({'event': 'control-failed', 'error': str(error)}, ensure_ascii=False), flush=True)
            stop.set()
            return
        if command != 'stop':
            print(json.dumps({'event': 'control-failed', 'error': f'Unknown control command: {command}'},
                             ensure_ascii=False), flush=True)
        stop.set()
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--task-class')
    parser.add_argument('--expected-version')
    args = parser.parse_args()
    stop = threading.Event()
    from gameframe.packages import PackageManifest
    from gameframe.process_locks import data_lease, device_input_lease, package_lease
    with package_lease(Path(__file__).resolve().parent):
        manifest = PackageManifest.read(Path(__file__).resolve().parent)
        if args.expected_version is not None and manifest.version != args.expected_version:
            raise ValueError('Gamepack version changed before compatibility application started')
        with data_lease(args.source_root), device_input_lease({'type': 'windows'}):
            try:
                run(args.source_root, args.task_class, stop, control_stream=sys.stdin)
            finally:
                _close_runtime_services()


if __name__ == '__main__':
    main()
