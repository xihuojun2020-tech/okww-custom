"""Native package execution. Merely importing this module never opens a device."""

import argparse
import json
import sys
import threading
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


def listen_stop(stop):
    for line in sys.stdin:
        try:
            message = json.loads(line)
            command = message['command']
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            emit({'event': 'control-failed', 'error': str(error)})
            stop.set()
            return
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
    options = parser.parse_args(argv)
    manifest = PackageManifest.read(options.package)
    task = manifest.task(options.task)
    if manifest.execution != 'native':
        raise ValueError('Legacy packages use their explicit production bootstrap')
    package = manifest.load()
    stop = threading.Event()
    threading.Thread(target=listen_stop, args=(stop,), daemon=True).start()
    device = create_device(options.device)
    store = None
    try:
        store = RunStore(options.data_dir / 'runs.sqlite')
        runtime = Runtime(store, emit)
        if task.kind == 'service':
            # Launching a service is an explicit enable action; errors never clear it.
            store.set_enabled(manifest.id, task.id, True)
            runtime.run_service(manifest, package, task.id, device, options.data_dir,
                                stop=stop, config=options.config)
        else:
            runtime.run(manifest, package, task.id, device, options.data_dir,
                        options.config, stop)
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
            device.close()
        finally:
            if store is not None:
                store.close()


if __name__ == '__main__':
    raise SystemExit(main())
