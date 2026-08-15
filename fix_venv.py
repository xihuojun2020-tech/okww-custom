# -*- coding: utf-8 -*-
"""OK-WW 可移植启动自愈脚本（fix_venv.py）

背景：本项目 .venv 由 uv 创建，pyvenv.cfg 里的 home / executable 指向创建时
所在电脑的 Python（例如 C:\\Users\\xxx\\AppData\\Roaming\\uv\\python\\...）。
整个文件夹复制到另一台电脑后，该路径不存在，venv 的 python.exe 会报
"No Python at ..."，程序无法启动。

本项目采用"随项目携带 Python 运行时"方案：runtime/python/ 目录内是完整可
移植的 CPython（自带 vcruntime140.dll）。本脚本把 .venv/pyvenv.cfg 的
home / executable 重写为当前项目内 runtime/python 的绝对路径，使 venv
（包含全部依赖的 site-packages）在当前电脑上可用。

用法：<项目根>\\runtime\\python\\python.exe fix_venv.py
退出码：0=环境就绪，1=环境异常（启动脚本应中止并提示），2=运行时缺失
"""
import os
import subprocess
import sys

# 注意：不强制输出编码，让 Python 自动适配控制台代码页（bat 为 GBK 环境）

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME_PYTHON = os.path.join(PROJECT_ROOT, 'runtime', 'python')
VENV_PYVENV = os.path.join(PROJECT_ROOT, '.venv', 'pyvenv.cfg')
VENV_PYTHON = os.path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def main():
    # 1. 检查项目内 Python 运行时存在
    rt_exe = os.path.join(RUNTIME_PYTHON, 'python.exe')
    if not os.path.exists(rt_exe):
        print(f'[fix] 错误：项目内 Python 运行时缺失：{rt_exe}')
        print('[fix] 请确认复制的是完整文件夹（含 runtime/python 目录）。')
        return 2

    # 2. 读取现有 pyvenv.cfg
    version = '3.12.13'
    home_line = None
    executable_line = None
    lines = []
    if os.path.exists(VENV_PYVENV):
        with open(VENV_PYVENV, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines:
            if line.startswith('home ='):
                home_line = line.strip()
            elif line.startswith('executable ='):
                executable_line = line.strip()
            elif line.startswith('version ='):
                v = line.split('=', 1)[1].strip()
                if v:
                    version = v
    else:
        print('[fix] 警告：.venv/pyvenv.cfg 不存在，将重新生成。')

    expect_home = RUNTIME_PYTHON
    expect_exec = os.path.join(RUNTIME_PYTHON, 'python.exe')

    cur_home = home_line.split('=', 1)[1].strip() if home_line else ''
    cur_exec = executable_line.split('=', 1)[1].strip() if executable_line else ''

    if _norm(cur_home) == _norm(expect_home) and _norm(cur_exec) == _norm(expect_exec):
        print('[fix] .venv/pyvenv.cfg 已指向项目内运行时，无需修复')
    else:
        new_lines = [
            f'home = {expect_home}\n',
            'include-system-site-packages = false\n',
            f'version = {version}\n',
            f'executable = {expect_exec}\n',
            f'command = {expect_exec} -m venv {os.path.join(PROJECT_ROOT, ".venv")}\n',
        ]
        try:
            with open(VENV_PYVENV, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f'[fix] 已重写 .venv/pyvenv.cfg -> {expect_home}')
        except OSError as e:
            print(f'[fix] 错误：写入 .venv/pyvenv.cfg 失败：{e}')
            return 1

    # 3. 验证 venv 的 python 可用性（能 import 标准库即可）
    if not os.path.exists(VENV_PYTHON):
        print(f'[fix] 错误：{VENV_PYTHON} 不存在，venv 不完整')
        return 1
    try:
        r = subprocess.run(
            [VENV_PYTHON, '-c', 'import sys; print(sys.version)'],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            print(f'[fix] venv 验证通过：{r.stdout.strip().splitlines()[0]}')
            return 0
        print(f'[fix] 警告：venv python 不可用：{r.stderr.strip()[:300]}')
        return 1
    except Exception as e:
        print(f'[fix] 警告：venv 验证异常：{e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
