"""Launch update workers with the running application's resolved import paths."""
import os
import sys


def worker_command(module: str, *arguments: str) -> list[str]:
    # -E retains isolation from external Python settings; explicitly inherit the
    # paths already initialized by main.py, including pywin32's .pth directories.
    paths = [os.path.abspath(path) for path in sys.path]
    bootstrap = ("import sys,runpy,os,importlib.util; sys.path[:]= " + repr(paths)
                 + "; __import__('pywin32_bootstrap') if os.name == 'nt' and "
                   "importlib.util.find_spec('pywin32_bootstrap') else None"
                 + "; runpy.run_module(sys.argv.pop(1),run_name='__main__')")
    return [sys.executable, '-E', '-s', '-c', bootstrap, module, *arguments]


def error_detail(error: BaseException) -> str:
    from src.observability import redact_message
    return redact_message(error)[:600] or type(error).__name__
