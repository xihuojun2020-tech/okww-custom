from __future__ import annotations

import hashlib
import hmac
import http.client
import os
import re
import socket
import ssl
import time
import urllib.parse
from pathlib import Path


class LanTransportError(RuntimeError):
    pass


class CertificatePinError(LanTransportError):
    pass


class FileShareClient:
    """Read a Windows-authenticated UNC share with the same bounded interface."""

    @staticmethod
    def get_bytes(path: str, *, max_bytes: int, deadline_seconds: float) -> bytes:
        source = Path(path)
        try:
            if source.stat().st_size > max_bytes:
                raise LanTransportError("NAS 响应超过大小限制")
            data = source.read_bytes()
        except OSError as exc:
            raise LanTransportError("无法读取 NAS 共享文件") from exc
        if len(data) > max_bytes:
            raise LanTransportError("NAS 响应超过大小限制")
        return data

    @staticmethod
    def download(path: str, destination: Path, *, expected_size: int, expected_sha256: str,
                 deadline_seconds: float = 120.0) -> Path:
        source, destination = Path(path), Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(destination.suffix + ".part")
        digest, count = hashlib.sha256(), 0
        deadline = time.monotonic() + deadline_seconds
        try:
            with source.open("rb") as reader, pending.open("wb") as writer:
                while chunk := reader.read(65536):
                    if time.monotonic() > deadline:
                        raise LanTransportError("NAS 下载超时")
                    count += len(chunk)
                    if count > expected_size:
                        raise LanTransportError("NAS 文件超过预期大小")
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if count != expected_size or not hmac.compare_digest(digest.hexdigest(), expected_sha256):
                raise LanTransportError("更新包长度或 SHA-256 不匹配")
            os.replace(pending, destination)
            return destination
        except OSError as exc:
            raise LanTransportError("无法下载 NAS 共享文件") from exc
        finally:
            pending.unlink(missing_ok=True)


class HttpsPinnedClient:
    def __init__(self, certificate_sha256: str, ca_file: Path | None = None, connect_timeout: float = 5.0):
        if not re.fullmatch(r"[0-9a-f]{64}", certificate_sha256 or ""):
            raise CertificatePinError("NAS 证书指纹无效")
        self.certificate_sha256 = certificate_sha256
        self.context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.connect_timeout = connect_timeout

    @staticmethod
    def _url(url: str) -> urllib.parse.SplitResult:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise LanTransportError("只允许无凭据的 HTTPS 更新地址")
        return parsed

    def _connection(self, parsed: urllib.parse.SplitResult) -> http.client.HTTPSConnection:
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=self.connect_timeout,
                                                 context=self.context)
        try:
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True)
        except (OSError, ssl.SSLError) as exc:
            connection.close()
            raise LanTransportError("无法建立可信 NAS HTTPS 连接") from exc
        actual = hashlib.sha256(certificate).hexdigest()
        if not hmac.compare_digest(actual, self.certificate_sha256):
            connection.close()
            raise CertificatePinError("NAS 证书指纹不匹配")
        return connection

    def _stream(self, url: str, sink, *, max_bytes: int, deadline_seconds: float) -> tuple[int, str]:
        parsed = self._url(url)
        deadline = time.monotonic() + deadline_seconds
        connection = self._connection(parsed)
        digest = hashlib.sha256()
        count = 0
        try:
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request("GET", target, headers={"Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status != 200:
                raise LanTransportError(f"NAS 返回 HTTP {response.status}")
            length = response.getheader("Content-Length")
            if length is not None:
                try:
                    advertised = int(length)
                except ValueError as exc:
                    raise LanTransportError("NAS 返回无效内容长度") from exc
                if advertised < 0 or advertised > max_bytes:
                    raise LanTransportError("NAS 响应超过大小限制")
            while True:
                if time.monotonic() > deadline:
                    raise LanTransportError("NAS 下载超时")
                chunk = response.read(min(65536, max_bytes - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    raise LanTransportError("NAS 响应超过大小限制")
                digest.update(chunk)
                sink.write(chunk)
            if length is not None and count != advertised:
                raise LanTransportError("NAS 响应被截断")
            return count, digest.hexdigest()
        except (OSError, socket.timeout, http.client.HTTPException) as exc:
            raise LanTransportError("NAS 下载失败") from exc
        finally:
            connection.close()

    def get_bytes(self, url: str, *, max_bytes: int, deadline_seconds: float) -> bytes:
        import io
        stream = io.BytesIO()
        self._stream(url, stream, max_bytes=max_bytes, deadline_seconds=deadline_seconds)
        return stream.getvalue()

    def download(self, url: str, destination: Path, *, expected_size: int, expected_sha256: str,
                 deadline_seconds: float = 120.0) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix(destination.suffix + ".part")
        try:
            with pending.open("wb") as output:
                size, digest = self._stream(url, output, max_bytes=expected_size, deadline_seconds=deadline_seconds)
                output.flush()
                os.fsync(output.fileno())
            if size != expected_size or not hmac.compare_digest(digest, expected_sha256):
                raise LanTransportError("更新包长度或 SHA-256 不匹配")
            os.replace(pending, destination)
            return destination
        finally:
            pending.unlink(missing_ok=True)
