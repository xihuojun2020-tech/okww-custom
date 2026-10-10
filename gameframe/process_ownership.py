"""Explicit device process identities excluded from forced worker cleanup."""

import json
import os
import tempfile
from pathlib import Path

import psutil


PROTECTED_PROCESSES_ENV = 'GAMEFRAME_PROTECTED_PROCESSES'


def register_device_process(process):
    path = os.environ.get(PROTECTED_PROCESSES_ENV)
    if path is None:
        return  # Standalone devices have no controller cleanup tree.
    path = Path(path)
    records = json.loads(path.read_text(encoding='utf-8'))
    record = {'pid': process.pid, 'created': process.create_time()}
    if record in records:
        return
    records.append(record)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(records, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def protected_process_identities(path):
    identities = set()
    for record in json.loads(Path(path).read_text(encoding='utf-8')):
        try:
            process = psutil.Process(record['pid'])
            if process.create_time() != record['created']:
                continue
            identities.add((process.pid, record['created']))
            for child in process.children(recursive=True):
                try:
                    identities.add((child.pid, child.create_time()))
                except psutil.NoSuchProcess:
                    continue
        except psutil.NoSuchProcess:
            continue  # An exited registered process cannot be terminated.
    return identities
