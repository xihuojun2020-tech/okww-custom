"""Prepare an independent uploader and transactionally migrate one installation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.runtime.diagnostic_policy import installation_id, POLICY, settings
from src.runtime.diagnostic_runtime import prepare_runtime, check_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Installed working directory; account files are not changed')
    parser.add_argument('--root', type=Path, help='Existing diagnostic spool (optional override)')
    parser.add_argument('--home', type=Path, help='Independent runtime parent directory, outside installation')
    parser.add_argument('--apply', action='store_true', help='Migrate the owned scheduled task after self-check')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    if not (source / 'main.py').is_file() or not (source / 'config.py').is_file():
        parser.error('--source must be an OK-WW working directory')
    root = (args.root or Path(os.environ['LOCALAPPDATA']) / 'okww-custom/diagnostics' / POLICY / installation_id(source)).resolve()
    bundle = prepare_runtime(source, home=args.home)
    check_runtime(bundle)
    print(json.dumps({'source': str(source), 'runtime': str(bundle), 'spool': str(root), 'apply': args.apply}, ensure_ascii=False))
    if args.apply:
        settings(root)
        script = Path(__file__).with_name('migrate_diagnostic_task.ps1')
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                        '-SourceRepo', str(source), '-Bundle', str(bundle), '-Root', str(root),
                        '-TaskName', 'okww-diagnostics-' + installation_id(source)], check=True, timeout=45,
                       creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    main()
