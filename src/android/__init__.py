"""MuMu/Android device primitives and stage 01 preflight."""

from .actions import GameActions
from .bindings import BindingSnapshot, DeviceBinding, DeviceBindingError, DeviceBindingRepository
from .control import ControlBoundary, ControlMode, ControlState, ControlTransport, SafetyProof
from .deployment import (
    AdbError, AdbResult, AdbRunner, AgentIdentity, AgentArtifactInspector,
    AgentArtifactStatus, CombatAgentDeployment, DeploymentError, DevicePreflight,
    PortLeasePool, REMOTE_AGENT_JAR,
)
from .device import DeviceChannel, DeviceChannelRegistry, DeviceRegistry
from .mumu import MuMuCandidate, MuMuController, MuMuDiscovery, MuMuVersionProbe
from .nemu import NemuIpcError, NemuIpcFrameProvider
from .preflight import (
    DevicePreflightService,
    PackageCandidate,
    PackageDetector,
    PreflightError,
    PreflightReport,
)

__all__ = [
    "AdbError",
    "AdbResult",
    "AdbRunner", "AgentIdentity", "AgentArtifactInspector", "AgentArtifactStatus",
    "CombatAgentDeployment", "DeploymentError",
    "DevicePreflight", "PortLeasePool", "REMOTE_AGENT_JAR",
    "GameActions", "ControlBoundary", "ControlMode", "ControlState", "ControlTransport", "SafetyProof",
    "DeviceChannel", "DeviceChannelRegistry", "DeviceRegistry",
    "BindingSnapshot", "DeviceBinding", "DeviceBindingError", "DeviceBindingRepository",
    "MuMuCandidate",
    "MuMuDiscovery",
    "MuMuVersionProbe",
    "NemuIpcError", "NemuIpcFrameProvider",
    "DevicePreflightService",
    "PackageCandidate",
    "PackageDetector",
    "PreflightError",
    "PreflightReport",
]
