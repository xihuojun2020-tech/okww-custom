# -*- coding: utf-8 -*-
"""生成 okww 功能更新包（主电脑运行，复制到另一台电脑解压覆盖即可）。

只打包「功能更新」文件：
  - 项目代码：src/、config.py、main.py、fix_venv.py、启动okww.bat、probe_mumu.py
  - 功能资源：COCO 特征定义、退登电源图标、版本说明与更新日志
  - 翻译：i18n/（po + mo）
  - 框架修改：.venv/Lib/site-packages/ok/gui/MainWindow.py、
    .venv/Lib/site-packages/ok/notification/windows_messenger.py（不含 .bak）
  - 功能配置：configs/Notification.json

【明确排除 - 目标机保留，绝不覆盖】：
  - configs/daily_profiles.json（账号方案 + 完成时间 = 账号数据）
  - configs/DailyTask.json（激活账号方案）
  - configs/ADBSwitchTask.json（模拟器地址等设备相关，目标机重新配置）
  - configs/devices.json、其他所有 configs/*.json（目标机个性化配置）
  - .venv/pyvenv.cfg 及 .venv 其余文件（避免破坏目标机的 Python 路径指向！）
  - recordings/、screenshots/、logs/、cache/、okww监控室/、.workbuddy-ai/、__pycache__

用法：python 打包更新.py [输出目录]
"""
import os
import sys
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))

# 同步文件/目录（相对项目根）
SYNC_ITEMS = [
    'src',
    'config.py',
    'main.py',
    'fix_venv.py',
    '启动okww.bat',
    'probe_mumu.py',
    'assets/coco_annotations.json',
    'assets/images/logout_power_icon.png',
    'custom_ok/ok/gui/about/AboutTab.py',
    '更新日志.md',
    'i18n',
    'configs/Notification.json',
    '.venv/Lib/site-packages/ok/gui/MainWindow.py',
    '.venv/Lib/site-packages/ok/notification/windows_messenger.py',
]

# 打包时排除的模式（防止误入）
EXCLUDE_SUFFIXES = ('.pyc', '.bak', '.tmp', '.log')
EXCLUDE_DIRS = ('__pycache__',)


def collect_files():
    """收集要打包的文件列表（相对路径, 绝对路径）。"""
    files = []
    for item in SYNC_ITEMS:
        abs_item = os.path.join(ROOT, item)
        if os.path.isfile(abs_item):
            files.append((item, abs_item))
        elif os.path.isdir(abs_item):
            for dirpath, dirnames, filenames in os.walk(abs_item):
                # 跳过 __pycache__ 等
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fname in filenames:
                    if fname.endswith(EXCLUDE_SUFFIXES):
                        continue
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, ROOT)
                    files.append((rel_path, abs_path))
        else:
            print(f'⚠️ 跳过（不存在）: {item}')
    return files


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else ROOT
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d')
    out_zip = os.path.join(out_dir, f'okww_更新包_{stamp}.zip')

    files = collect_files()
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_path, abs_path in sorted(files):
            zf.write(abs_path, rel_path)

    print(f'✅ 更新包已生成: {out_zip}')
    print(f'   共 {len(files)} 个文件')
    print()
    print('【安装到另一台电脑】')
    print('  1. 把 zip 拷到目标机，解压到 ok-wuthering-waves-master 文件夹根目录（覆盖）')
    print('  2. 解压时选择"全部覆盖/替换"')
    print('  3. 双击 启动okww.bat 即可')
    print()
    print('【不会动目标机的账号数据】')
    print('  - configs/daily_profiles.json（账号方案+完成时间）保留')
    print('  - configs/DailyTask.json（当前激活账号）保留')
    print('  - configs/ADBSwitchTask.json（模拟器地址）保留，目标机重新配置')
    print('  - .venv/pyvenv.cfg 不包含在包内，Python 路径指向不受影响')
    return 0


if __name__ == '__main__':
    sys.exit(main())
