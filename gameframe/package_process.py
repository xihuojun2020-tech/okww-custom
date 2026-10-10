"""Hold installed code while running its trusted Python module in this process."""

import argparse
from pathlib import Path
import runpy
import sys

from gameframe.packages import PackageManifest
from gameframe.process_locks import package_lease


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--module', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    with package_lease(options.package):
        manifest = PackageManifest.read(options.package)
        if manifest.version != options.expected_version:
            raise ValueError('Gamepack version changed before the process started')
        arguments = options.arguments
        if arguments[:1] == ['--']:
            arguments = arguments[1:]
        sys.argv = [options.module, *arguments]
        runpy.run_module(options.module, run_name='__main__', alter_sys=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
