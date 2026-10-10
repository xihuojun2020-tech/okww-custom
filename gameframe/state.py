"""Framework run records; game account ledgers remain owned by each package."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class RunStore:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, package_id TEXT NOT NULL, task_id TEXT NOT NULL,
                started_ns INTEGER NOT NULL, ended_ns INTEGER,
                status TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS preferences (
                package_id TEXT NOT NULL, task_id TEXT NOT NULL, enabled INTEGER NOT NULL,
                PRIMARY KEY(package_id, task_id));
        ''')

    def begin(self, run_id: str, package_id: str, task_id: str) -> None:
        with self.connection:
            self.connection.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?)',
                                    (run_id, package_id, task_id, time.time_ns(),
                                     None, 'running', '{}'))

    def finish(self, run_id: str, status: str, details: dict) -> None:
        with self.connection:
            self.connection.execute('UPDATE runs SET ended_ns=?,status=?,details=? WHERE id=?',
                                    (time.time_ns(), status, json.dumps(details, ensure_ascii=False), run_id))

    def history(self, limit: int = 50) -> list[dict]:
        cursor = self.connection.execute('SELECT id,package_id,task_id,status,details FROM runs '
                                         'ORDER BY started_ns DESC LIMIT ?', (limit,))
        return [dict(id=row[0], package_id=row[1], task_id=row[2], status=row[3],
                     details=json.loads(row[4])) for row in cursor]

    def enabled(self, package_id: str, task_id: str) -> bool:
        row = self.connection.execute('SELECT enabled FROM preferences WHERE package_id=? AND task_id=?',
                                     (package_id, task_id)).fetchone()
        return bool(row[0]) if row else False

    def set_enabled(self, package_id: str, task_id: str, enabled: bool) -> None:
        with self.connection:
            self.connection.execute('INSERT INTO preferences VALUES (?,?,?) '
                                    'ON CONFLICT(package_id,task_id) DO UPDATE SET enabled=excluded.enabled',
                                    (package_id, task_id, int(enabled)))

    def close(self) -> None:
        self.connection.close()
