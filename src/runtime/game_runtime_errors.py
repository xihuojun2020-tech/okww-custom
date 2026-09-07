class GameProcessLost(RuntimeError):
    """The configured game window no longer exists or is disconnected."""


class FrameUnavailable(RuntimeError):
    """The game window exists, but no current capture frame is available."""


class StartupStateChanged(RuntimeError):
    """A login-start probe found the world; unwind capture before reclassifying."""
