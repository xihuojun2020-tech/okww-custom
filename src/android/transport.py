"""Persistent JSON-lines transport for an ADB-forwarded Combat Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import socket
from threading import Lock, RLock
import time
from typing import Callable

from .protocol import (
    AgentIdentityInfo, CombatMessage, CommandKind, MessageStatus, ProtocolError,
    decode_message, encode_message, parse_agent_identity,
)


DEFAULT_MAX_FRAME_BYTES = 64 * 1024
SocketFactory = Callable[[tuple[str, int], float], socket.socket]


def _validate_endpoint(host: str, port: int) -> tuple[str, int]:
    if not isinstance(host, str) or host.strip().lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Combat Agent transport only permits loopback hosts")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= 65535:
        raise ValueError("port must be an explicit integer in 1..65535")
    return host.strip(), port


def _validate_timeout(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a number")
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    return timeout


@dataclass
class _SocketLane:
    address: tuple[str, int]
    socket_factory: SocketFactory
    max_frame_bytes: int
    lock: Lock = field(default_factory=Lock)
    socket: socket.socket | None = None
    receive_buffer: bytearray = field(default_factory=bytearray)

    def request(self, message: CombatMessage, timeout: float) -> CombatMessage:
        with self.lock:
            sock = self._connect(timeout)
            try:
                sock.settimeout(timeout)
                # One send only: a failed request is never transparently retried.
                frame = (encode_message(message) + "\n").encode("utf-8")
                if len(frame) - 1 > self.max_frame_bytes:
                    self._close_socket()
                    raise ProtocolError("Combat Agent frame exceeds maximum size")
                sock.sendall(frame)
                deadline = time.monotonic() + timeout
                while True:
                    response = self._read_message(sock, deadline)
                    if response.session_token != message.session_token:
                        raise ProtocolError("Combat Agent response session token mismatch")
                    if response.command_id != message.command_id:
                        raise ProtocolError("Combat Agent response command_id mismatch")
                    if response.kind is not message.kind:
                        raise ProtocolError("Combat Agent response kind mismatch")
                    if response.status in {
                        MessageStatus.COMPLETED,
                        MessageStatus.CANCELLED,
                        MessageStatus.REJECTED,
                    }:
                        return response
                    # accepted/started are progress ACKs; keep reading until a
                    # terminal response for exactly this command arrives.
            except socket.timeout as exc:
                self._close_socket()
                raise TimeoutError("Combat Agent response timed out") from exc
            except TimeoutError:
                self._close_socket()
                raise
            except ProtocolError:
                self._close_socket()
                raise
            except (OSError, UnicodeError) as exc:
                self._close_socket()
                raise ConnectionError("Combat Agent socket failed") from exc

    def _connect(self, timeout: float) -> socket.socket:
        if self.socket is not None:
            return self.socket
        try:
            sock = self.socket_factory(self.address, timeout)
            if sock is None or not hasattr(sock, "sendall") or not hasattr(sock, "recv"):
                raise TypeError("socket_factory did not return a socket-like object")
            self.socket = sock
            self.receive_buffer.clear()
            return sock
        except (OSError, TypeError, ValueError) as exc:
            self._close_socket()
            raise ConnectionError("Combat Agent socket connection failed") from exc

    def _read_message(self, sock: socket.socket, deadline: float) -> CombatMessage:
        while True:
            separator = self.receive_buffer.find(b"\n")
            if separator >= 0:
                frame = bytes(self.receive_buffer[:separator])
                del self.receive_buffer[:separator + 1]
                if len(frame) > self.max_frame_bytes:
                    raise ProtocolError("Combat Agent frame exceeds maximum size")
                return decode_message(frame)
            if len(self.receive_buffer) > self.max_frame_bytes:
                raise ProtocolError("Combat Agent frame exceeds maximum size")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Combat Agent response timed out")
            sock.settimeout(remaining)
            try:
                chunk = sock.recv(min(4096, self.max_frame_bytes + 1))
            except socket.timeout:
                raise
            if not chunk:
                raise ConnectionError("Combat Agent closed the socket before a response")
            self.receive_buffer.extend(chunk)
            if len(self.receive_buffer) > self.max_frame_bytes:
                raise ProtocolError("Combat Agent frame exceeds maximum size")

    def close(self) -> None:
        # Do not wait for request's lock: close is allowed to interrupt recv.
        sock = self.socket
        self.socket = None
        self.receive_buffer.clear()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _close_socket(self) -> None:
        self.close()


class SocketCombatAgentTransport:
    """Two independent persistent TCP lanes for normal and safety commands."""

    def __init__(
        self,
        host: str,
        normal_port: int,
        emergency_port: int,
        *,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        socket_factory: SocketFactory | None = None,
    ) -> None:
        self.normal_address = _validate_endpoint(host, normal_port)
        self.emergency_address = _validate_endpoint(host, emergency_port)
        if isinstance(max_frame_bytes, bool) or not isinstance(max_frame_bytes, int) or max_frame_bytes <= 0:
            raise ValueError("max_frame_bytes must be a positive integer")
        self._socket_factory = socket_factory or self._create_socket
        self._normal = _SocketLane(self.normal_address, self._socket_factory, max_frame_bytes)
        self._emergency = _SocketLane(self.emergency_address, self._socket_factory, max_frame_bytes)
        self._state_lock = RLock()
        self._closed = False

    def request(self, message: CombatMessage, timeout: float) -> CombatMessage:
        return self._request(self._normal, message, timeout)

    def emergency_request(self, message: CombatMessage, timeout: float) -> CombatMessage:
        return self._request(self._emergency, message, timeout)

    def identity(self, session_token: str, timeout: float = 2.0) -> AgentIdentityInfo:
        """Perform a bounded identity handshake on the normal lane."""
        message = CombatMessage.new(session_token, CommandKind.HEARTBEAT, {"identity": True}, timeout=timeout)
        response = self.request(message, timeout)
        if response.status is not MessageStatus.COMPLETED:
            raise ProtocolError("identity handshake did not complete")
        payload = response.payload.get("identity", response.payload)
        return parse_agent_identity(payload)

    handshake = identity

    def _request(self, lane: _SocketLane, message: CombatMessage, timeout: float) -> CombatMessage:
        if not isinstance(message, CombatMessage):
            raise ProtocolError("transport accepts CombatMessage instances only")
        timeout = _validate_timeout(timeout)
        with self._state_lock:
            if self._closed:
                raise ConnectionError("Combat Agent transport is closed")
        return lane.request(message, timeout)

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
        self._normal.close()
        self._emergency.close()

    def __enter__(self) -> "SocketCombatAgentTransport":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _create_socket(address: tuple[str, int], timeout: float) -> socket.socket:
        return socket.create_connection(address, timeout=timeout)
