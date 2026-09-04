# -*- coding: utf-8 -*-
"""Configure the packaged repository proxy before GitHub update checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


GITHUB_PROBE_URL = "https://github.com/robots.txt"
COMMON_PORTS = (7890, 10809, 1080, 7897)


def _normalise_endpoint(value: str) -> str | None:
    value = value.strip().rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value if "://" in value else f"http://{value}")
    try:
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or not port:
        return None
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{host}:{port}"


def parse_proxy_server(value: str | None) -> list[str]:
    """Return HTTP-capable endpoints, preferring HTTPS in WinINet maps."""
    if not value:
        return []
    mapped: dict[str, str] = {}
    plain: list[str] = []
    for item in value.split(";"):
        if "=" in item:
            protocol, endpoint = item.split("=", 1)
            mapped[protocol.strip().lower()] = endpoint.strip()
        else:
            plain.append(item)
    values = [mapped[key] for key in ("https", "http") if key in mapped] or plain
    result: list[str] = []
    for candidate in values:
        endpoint = _normalise_endpoint(candidate)
        if endpoint and endpoint not in result:
            result.append(endpoint)
    return result


def detect_system_proxy() -> str | None:
    """Read the enabled Windows user proxy without consulting stale env vars."""
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
        return str(server).strip() if enabled and server else None
    except (ImportError, OSError):
        return None


def probe_github(proxy: str | None, timeout: float = 3.0) -> bool:
    """Verify that GitHub itself is reachable through exactly this route."""
    proxies = {}
    if proxy:
        url = f"http://{proxy}"
        proxies = {"http": url, "https": url}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    request = urllib.request.Request(
        GITHUB_PROBE_URL,
        headers={"User-Agent": "okww-proxy-bootstrap"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            return 200 <= response.status < 500
    except Exception:
        return False


def find_working_proxy(
    *,
    system_proxy: str | None = None,
    common_ports: tuple[int, ...] = COMMON_PORTS,
    probe=probe_github,
    timeout: float = 3.0,
    on_attempt=None,
) -> str | None:
    """Return the first candidate that can actually reach GitHub."""
    raw_system_proxy = detect_system_proxy() if system_proxy is None else system_proxy
    candidates = parse_proxy_server(raw_system_proxy)
    candidates.extend(f"127.0.0.1:{port}" for port in common_ports)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        working = bool(probe(candidate, timeout))
        if on_attempt:
            on_attempt(candidate, working)
        if working:
            return candidate
    return None


def set_git_proxy(git_config: str | os.PathLike[str], proxy: str | None) -> None:
    """Set the canonical http.proxy and remove stale legacy https.proxy."""
    path = Path(git_config)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    output: list[str] = []
    in_http = False
    in_proxy_section = False
    found_http = False
    wrote_proxy = False
    section_re = re.compile(r"^\s*\[\s*http\s*]\s*$", re.IGNORECASE)
    legacy_https_re = re.compile(r"^\s*\[\s*https\s*]\s*$", re.IGNORECASE)
    proxy_re = re.compile(r"^\s*proxy\s*=", re.IGNORECASE)

    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.lstrip().startswith("["):
            if in_http and proxy and not wrote_proxy:
                output.append(f"\tproxy = http://{proxy}\n")
                wrote_proxy = True
            in_http = bool(section_re.match(stripped))
            in_proxy_section = in_http or bool(legacy_https_re.match(stripped))
            found_http = found_http or in_http
            output.append(line)
            continue
        if in_proxy_section and proxy_re.match(line):
            if in_http and proxy and not wrote_proxy:
                output.append(f"\tproxy = http://{proxy}\n")
                wrote_proxy = True
            continue
        output.append(line)

    if in_http and proxy and not wrote_proxy:
        output.append(f"\tproxy = http://{proxy}\n")
        wrote_proxy = True
    if proxy and not found_http:
        if output and output[-1].strip():
            output.append("\n")
        output.extend(("[http]\n", f"\tproxy = http://{proxy}\n"))

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="config.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.writelines(output)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def find_packaged_git_config(base_dir: str | os.PathLike[str]) -> Path | None:
    base = Path(base_dir).resolve()
    candidates = (
        base / "data" / "apps" / "okww-custom" / "repo" / ".git" / "config",
        base.parent / "repo" / ".git" / "config",
    )
    return next((path for path in candidates if path.is_file()), None)


def find_packaged_app_json(base_dir: str | os.PathLike[str]) -> Path | None:
    base = Path(base_dir).resolve()
    candidates = (
        base / "data" / "apps" / "okww-custom" / "app.json",
        base.parent / "app.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def find_bootstrap_log(base_dir: str | os.PathLike[str]) -> Path:
    base = Path(base_dir).resolve()
    if base.name == "working" and base.parent.name == "okww-custom":
        return base.parents[3] / "logs" / "proxy_bootstrap.log"
    return base / "logs" / "proxy_bootstrap.log"


def configure_repo_proxy(
    git_config: str | os.PathLike[str],
    *,
    log_path: str | os.PathLike[str] | None = None,
    system_proxy: str | None = None,
    probe=probe_github,
    timeout: float = 3.0,
) -> str | None:
    """Select a verified proxy, remove stale config if none works, and log it."""
    messages: list[str] = []

    def record(candidate: str, working: bool) -> None:
        messages.append(f"candidate={candidate} github={'ok' if working else 'failed'}")

    raw_system_proxy = detect_system_proxy() if system_proxy is None else system_proxy
    safe_system_proxies = parse_proxy_server(raw_system_proxy)
    messages.append(f"system_proxy={','.join(safe_system_proxies) or 'disabled'}")
    selected = find_working_proxy(
        system_proxy=raw_system_proxy or " ",
        probe=probe,
        timeout=timeout,
        on_attempt=record,
    )
    if selected:
        set_git_proxy(git_config, selected)
        messages.append(f"selected=http://{selected}")
    else:
        direct = bool(probe(None, timeout))
        set_git_proxy(git_config, None)
        messages.append(f"selected={'direct' if direct else 'offline'}")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rendered = f"[{stamp}] " + " | ".join(messages)
    print(f"[okww] {rendered}")
    if log_path:
        log = Path(log_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    return selected


def restore_auto_update(base_dir: str | os.PathLike[str]) -> None:
    app_json = find_packaged_app_json(base_dir)
    if app_json is None:
        return
    data = json.loads(app_json.read_text(encoding="utf-8"))
    data["update_method"] = "AUTO_UPDATE"
    app_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--configure-only", action="store_true")
    args = parser.parse_args(argv)
    base = Path(__file__).resolve().parent
    git_config = find_packaged_git_config(base)
    if git_config:
        configure_repo_proxy(git_config, log_path=find_bootstrap_log(base))
    else:
        print("[okww] 未找到打包仓库，跳过代理配置")
    restore_auto_update(base)

    executable = base / "okww-custom.exe"
    if not args.configure_only and executable.is_file():
        subprocess.Popen([os.fspath(executable)], cwd=base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
