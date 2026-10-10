"""Native package execution. Merely importing this module never opens a device."""

import argparse
import json
import sys
import threading
from queue import Queue
from pathlib import Path

from gameframe.api import Cancelled
from gameframe.packages import PackageManifest
from gameframe.runtime import Runtime
from gameframe.state import RunStore


def json_object(text):
    value = json.loads(text)
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError('Expected a JSON object')
    return value


def create_device(options):
    kind = options['type']
    if kind == 'replay':
        from gameframe.devices.replay import ReplayDevice
        return ReplayDevice(options['frames'])
    if kind == 'windows':
        from gameframe.devices.windows import WindowsDevice
        return WindowsDevice(**{key: value for key, value in options.items() if key != 'type'})
    if kind == 'mumu':
        from gameframe.devices.mumu import MuMuDevice
        return MuMuDevice(**{key: value for key, value in options.items() if key != 'type'})
    if kind == 'adb':
        from gameframe.devices.adb import AdbDevice
        return AdbDevice(**{key: value for key, value in options.items() if key != 'type'})
    raise ValueError(f'Unknown device type: {kind}')


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def listen_stop(stop, pause, requests=None):
    for line in sys.stdin:
        try:
            message = json.loads(line)
            command = message['command']
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            emit({'event': 'control-failed', 'error': str(error)})
            stop.set()
            return
        if command == 'pause':
            pause.set()
            continue
        if command == 'resume':
            pause.clear()
            continue
        if requests is not None and command in {'run-task', 'set-service'}:
            requests.put(message)
            continue
        if command != 'stop':
            emit({'event': 'control-failed', 'error': f'Unknown control command: {command}'})
        stop.set()
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--device', type=json_object, required=True)
    parser.add_argument('--config', type=json_object, default={})
    parser.add_argument('--session', action='store_true')
    options = parser.parse_args(argv)
    stop = threading.Event()
    pause = threading.Event()
    requests = Queue() if options.session else None
    threading.Thread(target=listen_stop, args=(stop, pause, requests), daemon=True).start()
    device = None
    store = None
    try:
        manifest = PackageManifest.read(options.package)
        task = manifest.task(options.task)
        if manifest.execution != 'native':
            raise ValueError('Legacy packages use their explicit production bootstrap')
        if options.session and not manifest.supports_session:
            raise ValueError('This package does not provide a shared task session')
        package = manifest.load()
        prepare = getattr(package, 'prepare', None)
        if prepare is not None:
            prepare(task.id, options.data_dir)
        if stop.is_set():
            raise Cancelled('Task stopped before device creation')
        device = create_device(options.device)
        prepare_device = getattr(device, 'prepare', None)
        if prepare_device is not None:
            prepare_device(stop)
        store = RunStore(options.data_dir / 'runs.sqlite')
        runtime = Runtime(store, emit)
        if options.session:
            runtime.run(manifest, package, task.id, device, options.data_dir,
                        options.config, stop, pause, session=True, requests=requests)
        elif task.kind == 'service':
            # Launching a service is an explicit enable action; errors never clear it.
            store.set_enabled(manifest.id, task.id, True)
            runtime.run_service(manifest, package, task.id, device, options.data_dir,
                                stop=stop, pause=pause, config=options.config)
        else:
            runtime.run(manifest, package, task.id, device, options.data_dir,
                        options.config, stop, pause)
        if hasattr(device, 'save_actions'):
            device.save_actions(options.data_dir / 'actions.json')
        return 0
    except Cancelled:
        return 130
    except Exception as error:
        emit({'event': 'worker-failed', 'type': type(error).__name__, 'error': str(error)})
        return 1
    finally:
        try:
            if device is not None:
                device.close()
        finally:
            if store is not None:
                store.close()


if __name__ == '__main__':
    raise SystemExit(main())
