"""Call the shared production bootstrap, without a second game implementation."""

import argparse
import importlib
import json
from pathlib import Path
import sys
import threading


def run(source_root, task_class=None, stop_event=None):
    source = Path(source_root).resolve()
    sys.path.insert(0, str(source))
    # OK parses --headless while constructing its singleton. It must be present
    # before importing the production entrypoint, not injected after creation.
    sys.argv = [str(source / 'main.py')]
    if task_class is not None:
        sys.argv.append('--headless')
    main = importlib.import_module('main')
    return main.run_application(task=task_class, stop_event=stop_event)


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
    args = parser.parse_args()
    stop = threading.Event()
    threading.Thread(target=listen_stop, args=(stop, sys.stdin), daemon=True).start()
    run(args.source_root, args.task_class, stop)


if __name__ == '__main__':
    main()
