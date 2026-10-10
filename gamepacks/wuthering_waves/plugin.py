"""Metadata-only compatibility entrypoint; importing it never starts OK-WW."""

import json
import os
from pathlib import Path
import sys


class WutheringWavesPackage:
    def __init__(self):
        self.root = Path(__file__).resolve().parent
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))

    def legacy_command(self, task_id, data_dir):
        # The legacy application retains its installation-bound configuration.
        # data_dir belongs to GameFrame's process records, not its account store.
        task = next((item for item in self.manifest['tasks'] if item['id'] == task_id), None)
        if task is None:
            raise KeyError(f'Unknown Wuthering Waves task: {task_id}')
        source = (self.root / self.manifest['source_root']).resolve()
        if not (source / 'main.py').is_file():
            raise FileNotFoundError(f'Missing compatibility application: {source / "main.py"}')
        command = [sys.executable, str(self.root / 'bootstrap.py'), '--source-root', str(source)]
        if task_id != 'application':
            command += ['--task-class', task['class']]
        return {'command': command, 'cwd': str(source), 'env': dict(os.environ)}

    def run(self, task_id, context):
        raise RuntimeError('This compatibility package must run in its legacy application process')


def create_package():
    return WutheringWavesPackage()
