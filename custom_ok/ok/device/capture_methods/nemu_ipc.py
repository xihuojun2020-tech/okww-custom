"""MuMu Nemu IPC capture method compatibility shim.

The bundled ``ok`` implementation only knows the MuMu 12 DLL locations.  Keep
the public capture-method API intact while resolving the install root and the
versioned IPC runtime independently.
"""

import json
import os
import re

from ok.util.collection import deep_get
from ok.util.logger import Logger

from ok.device.capture_methods.base import BaseCaptureMethod

logger = Logger.get_logger(__name__)

_IPC_DLL = "external_renderer_ipc.dll"
_VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*)$")


class NemuIpcCaptureMethod(BaseCaptureMethod):
    name = "Nemu Ipc Capture"
    description = "mumu player 12/15"

    def __init__(self, device_manager, exit_event, width=0, height=0):
        super().__init__()
        self.device_manager = device_manager
        self.exit_event = exit_event
        self._connected = width != 0 and height != 0
        self.nemu_impl = None
        self.emulator = None

    def update_emulator(self, emulator):
        self.emulator = emulator
        logger.info(f"update_path_and_id {emulator}")
        if self.nemu_impl:
            self.nemu_impl.disconnect()
            self.nemu_impl = None

    def base_folder(self):
        """Return MuMu's installation root, not the IPC runtime root."""
        path = os.path.abspath(os.fspath(self.emulator.path))
        return os.path.dirname(os.path.dirname(path))

    @staticmethod
    def _version_key(name):
        match = _VERSION_RE.fullmatch(name)
        return tuple(int(part) for part in match.group(1).split(".")) if match else None

    def runtime_folder(self):
        """Find the DLL-bearing runtime root used by ``NemuIpc``.

        A missing DLL deliberately falls back to the install root so the
        bundled implementation retains its existing, actionable error.
        """
        install_root = self.base_folder()
        candidates = []
        root_dll = os.path.join(install_root, "shell", "sdk", _IPC_DLL)
        if os.path.isfile(root_dll):
            candidates.append((None, install_root, root_dll))

        versions_root = os.path.join(install_root, "nx_device")
        try:
            entries = os.listdir(versions_root)
        except OSError:
            entries = []
        for entry in entries:
            version = self._version_key(entry)
            if version is None:
                continue
            runtime = os.path.join(versions_root, entry)
            dll = os.path.join(runtime, "shell", "sdk", _IPC_DLL)
            if os.path.isfile(dll):
                candidates.append((version, runtime, dll))

        if not candidates:
            return install_root

        selected = max(candidates, key=lambda item: (item[0] is not None, item[0] or ()))
        if len(candidates) > 1:
            logger.info(
                f"Multiple MuMu Nemu IPC runtimes found; selected {selected[1]} "
                f"(DLL {selected[2]})",
            )
        return selected[1]

    def init_nemu(self):
        if not self.nemu_impl:
            self.check_mumu_app_keep_alive_400()
            from ok.capture.adb.nemu_ipc import NemuIpc

            self.nemu_impl = NemuIpc(
                nemu_folder=self.runtime_folder(),
                instance_id=self.emulator.player_id,
                display_id=0,
            )

    def _instance_folder_name(self):
        name = getattr(self.emulator, "name", None)
        if name is not None:
            name = os.fspath(name)
            if isinstance(name, bytes):
                name = os.fsdecode(name)
            if name and (name in (".", "..") or ".." in name or "/" in name or "\\" in name):
                raise ValueError(f"Unsafe MuMu emulator name: {name!r}")
            if name:
                return name
        return f"MuMuPlayer-12.0-{self.emulator.player_id}"

    def check_mumu_app_keep_alive_400(self):
        install_root = self.base_folder()
        instance_name = self._instance_folder_name()
        vms_root = os.path.abspath(os.path.join(install_root, "vms"))
        file = os.path.abspath(os.path.join(vms_root, instance_name, "configs", "customer_config.json"))
        try:
            if os.path.commonpath((vms_root, file)) != vms_root:
                raise ValueError(f"Unsafe MuMu emulator config path: {file}")
        except ValueError:
            raise ValueError(f"Unsafe MuMu emulator config path: {file}")

        try:
            with open(file, mode="r", encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            logger.warning(f"Failed to check app_keep_alive, file {file} not exists")
            return False
        value = deep_get(data, keys="customer.app_keptlive", default=None)
        if str(value).lower() == "true":
            logger.error("Please turn off enable background keep alive in MuMuPlayer settings")
            raise Exception("Please turn off enable background keep alive in MuMuPlayer settings")
        return True

    def close(self):
        super().close()
        if self.nemu_impl:
            self.nemu_impl.disconnect()
            self.nemu_impl = None

    def do_get_frame(self):
        if self.exit_event.is_set():
            return None
        self.init_nemu()
        if self.nemu_impl:
            return self.nemu_impl.screenshot(timeout=0.5)

    def connected(self):
        return True
