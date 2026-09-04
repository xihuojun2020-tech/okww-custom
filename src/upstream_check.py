# -*- coding: utf-8 -*-
"""原版 okww 更新检测。

- 启动时（后台线程）检查原版仓库（ok-oldking/ok-wuthering-waves）最新提交
- 对比上次记录：有新提交 → 写入"有更新"标志，供首页（StartTab）显示提醒
- 每天最多检查一次（避免频繁请求）；无网络/失败时静默（不阻塞启动）
- 检测结果：configs/upstream_check.json
"""
import json
import os
import urllib.request

from auto_proxy import find_working_proxy

UPSTREAM_REPO = 'ok-oldking/ok-wuthering-waves'
CHECK_FILE = None  # 由 _init 设置

_api_url = f'https://api.github.com/repos/{UPSTREAM_REPO}/commits/master?per_page=1'


def _init():
    global CHECK_FILE
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # working 目录
    CHECK_FILE = os.path.join(base, 'configs', 'upstream_check.json')


def _load_record():
    try:
        if CHECK_FILE and os.path.isfile(CHECK_FILE):
            with open(CHECK_FILE, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_record(record):
    try:
        if CHECK_FILE:
            os.makedirs(os.path.dirname(CHECK_FILE), exist_ok=True)
            with open(CHECK_FILE, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _detect_proxy():
    """Return only a proxy that has passed a real GitHub request."""
    return find_working_proxy()


def _parse_commit(data):
    """从 API 响应（list 或单个 commit dict）提取 (sha, message)。"""
    try:
        if isinstance(data, dict) and 'sha' in data:
            item = data
        elif isinstance(data, list) and data:
            item = data[0]
        else:
            return None
        sha = item.get('sha', '')
        message = (item.get('commit') or {}).get('message', '')
        message = message.strip().splitlines()[0][:100] if message else ''
        return (sha, message) if sha else None
    except Exception:
        return None


def _fetch_latest():
    """获取原版最新 master 提交信息，返回 (sha, message) 或 None。"""
    proxy = _detect_proxy()
    proxies = {}
    if proxy:
        proxies['http'] = f'http://{proxy}'
        proxies['https'] = f'http://{proxy}'
    try:
        req = urllib.request.Request(_api_url, headers={'User-Agent': 'okww-custom', 'Accept': 'application/vnd.github+json'})
        if proxies:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
        else:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        result = _parse_commit(data)
        if result:
            return result
    except Exception:
        pass
    # 代理失败 → 直连重试一次
    try:
        req = urllib.request.Request(_api_url, headers={'User-Agent': 'okww-custom'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return _parse_commit(data)
    except Exception:
        pass
    return None


def check_upstream():
    """检查原版是否有更新（每天最多一次）。返回 True 表示发现新更新。"""
    try:
        _init()
        record = _load_record()
        today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
        if record.get('checked_date') == today:
            return bool(record.get('update_found'))
        result = _fetch_latest()
        if result is None:
            return bool(record.get('update_found'))
        sha, message = result
        old_sha = record.get('last_sha', '')
        update_found = bool(old_sha) and sha != old_sha
        record.update({
            'last_sha': sha,
            'last_message': message,
            'checked_date': today,
            'update_found': update_found,
            'update_found_date': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M') if update_found else record.get('update_found_date', ''),
        })
        _save_record(record)
        if update_found:
            print(f'[okww] 原版 okww 检测到新更新: {message}')
        return update_found
    except Exception:
        return False


def has_upstream_update():
    """供首页读取：是否有待提醒的原版更新。返回 (是否, 提交信息)。"""
    try:
        _init()
        record = _load_record()
        if record.get('update_found'):
            return True, record.get('last_message', ''), record.get('update_found_date', '')
    except Exception:
        pass
    return False, '', ''
