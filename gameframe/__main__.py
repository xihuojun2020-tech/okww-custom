"""GameFrame metadata, execution and desktop launcher commands."""

import argparse
import json
from pathlib import Path

from gameframe.controller import Controller
from gameframe.packages import PackageManifest, discover, install_archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list', help='List installed packages without starting them')
    listing.add_argument('--packages', type=Path, default=Path.home() / '.gameframe' / 'gamepacks')
    inspect = commands.add_parser('inspect', help='Inspect metadata without importing game code')
    inspect.add_argument('package', type=Path)
    installing = commands.add_parser('install', help='Install a gamepack ZIP without replacing existing data')
    installing.add_argument('archive', type=Path)
    installing.add_argument('--packages', type=Path, default=Path.home() / '.gameframe' / 'gamepacks')
    running = commands.add_parser('run', help='Execute a selected package task')
    running.add_argument('package', type=Path)
    running.add_argument('--task', required=True)
    running.add_argument('--data-dir', type=Path, default=Path.home() / '.gameframe')
    running.add_argument('--device', type=json.loads)
    running.add_argument('--config', type=json.loads)
    running.add_argument('--session', action='store_true', help='Keep a shared service/task session running')
    managing = commands.add_parser('manage', help='Open the selected package management application')
    managing.add_argument('package', type=Path)
    managing.add_argument('--data-dir', type=Path, required=True)
    gui = commands.add_parser('gui', help='Open the framework launcher')
    gui.add_argument('--packages', type=Path, default=Path.home() / '.gameframe' / 'gamepacks')
    gui.add_argument('--data-dir', type=Path, default=Path.home() / '.gameframe')
    args = parser.parse_args(argv)
    if args.command == 'install':
        package = install_archive(args.archive, args.packages)
        print(json.dumps({'id': package.id, 'installed': str(package.root)}, ensure_ascii=False))
        return 0
    if args.command == 'list':
        for package in discover(args.packages):
            print(json.dumps({'id': package.id, 'title': package.title, 'version': package.version,
                              'tasks': len(package.tasks), 'execution': package.execution,
                              'license': package.license}, ensure_ascii=False))
        return 0
    if args.command == 'inspect':
        package = PackageManifest.read(args.package)
        print(json.dumps({'id': package.id, 'execution': package.execution,
                          'supports_session': package.supports_session, 'management': package.management,
                          'license': package.license, 'tasks': [
                              {'id': task.id, 'title': task.title, 'kind': task.kind,
                               'default_config': task.default_config,
                               'required_capabilities': sorted(task.required_capabilities)}
                              for task in package.tasks]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'gui':
        from gameframe.gui import run_gui
        return run_gui(args.packages, args.data_dir)
    controller = Controller()
    try:
        manifest = PackageManifest.read(args.package)
        if args.command == 'manage':
            process = controller.start_management(manifest, data_dir=args.data_dir)
        else:
            process = controller.start(manifest, args.task, data_dir=args.data_dir,
                                       config=args.config, device=args.device, session=args.session)
        for line in process.stdout:
            print(line, end='', flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        controller.close()


if __name__ == '__main__':
    raise SystemExit(main())
