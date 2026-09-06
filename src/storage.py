# -*- coding: utf-8 -*-
"""数据仓库（ok仓库）：统一存放所有备份/输出文件。

在「设置 → 通用设置 → 数据仓库文件夹」选择一个根文件夹后，
自动在根下建立 ok仓库 目录，内含多个子目录：
- okww监控室：每日任务监控录像
- 配置备份：配置自动备份（替代原 configs_backup）
- 账号数据：导出的账号配置
未设置时各功能使用各自的默认位置（程序目录）。
"""
import os
from pathlib import Path


def resolve_config_backup_dir(root, *, warehouse_root='', legacy_backup_dir='') -> Path:
    """Resolve backup settings without reading configuration or creating files."""
    root = Path(root).resolve()
    warehouse_root = str(warehouse_root or '').strip()
    legacy_backup_dir = str(legacy_backup_dir or '').strip()
    candidate = (Path(warehouse_root) / 'ok仓库' / '配置备份' if warehouse_root else
                 Path(legacy_backup_dir) if legacy_backup_dir else root / 'configs_backup')
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    config = root / 'configs'
    if candidate == config or config in candidate.parents:
        return root / 'configs_backup'
    return candidate


def get_config_backup_dir(root=None) -> Path:
    """Shared settings adapter for startup, maintenance and task restore UI."""
    values = {}
    try:
        from ok import og
        global_config = og.executor.global_config
    except AttributeError:
        global_config = None
    for section, key in (('数据仓库文件夹', '数据仓库文件夹'), ('Config Backup', 'Config Backup Directory')):
        try:
            values[key] = (global_config.get_config(section) or {}).get(key, '')
        except (AttributeError, KeyError):
            values[key] = ''
    return resolve_config_backup_dir(
        root or os.getcwd(), warehouse_root=values['数据仓库文件夹'],
        legacy_backup_dir=values['Config Backup Directory'])


def get_ok_warehouse():
    """读取全局配置「数据仓库文件夹」，返回 ok仓库 路径（自动创建子目录）；未设置返回 None。"""
    try:
        from ok import og
        global_config = og.executor.global_config.get_config('数据仓库文件夹')
        root = (global_config or {}).get('数据仓库文件夹', '') or ''
    except Exception:
        root = ''
    root = (root or '').strip()
    if not root:
        return None
    wh = os.path.join(root, 'ok仓库')
    try:
        for sub in ('okww监控室', '配置备份', '账号数据'):
            os.makedirs(os.path.join(wh, sub), exist_ok=True)
    except Exception:
        pass
    return wh


def get_warehouse_sub(sub):
    """返回 ok仓库 下的子目录路径（如 okww监控室）；未设置数据仓库返回 None。"""
    wh = get_ok_warehouse()
    if wh is None:
        return None
    path = os.path.join(wh, sub)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path
