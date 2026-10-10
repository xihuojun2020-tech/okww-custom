"""PID-bound Windows preferences; called only by the device's execution owner."""


class ProcessAudio:
    def __init__(self):
        import comtypes
        comtypes.CoInitialize()
        self.comtypes = comtypes

    def sessions(self, pid):
        from pycaw.pycaw import AudioUtilities
        return [(session.InstanceIdentifier, session.SimpleAudioVolume)
                for session in AudioUtilities.GetAllSessions() if session.ProcessId == pid]

    def close(self):
        self.comtypes.CoUninitialize()


class WindowsPreferences:
    def __init__(self, device, values, *, supported_ratio, min_size, resolutions, audio=None):
        self.device, self.values = device, values
        self.ratio, self.minimum, self.resolutions = supported_ratio, tuple(min_size), tuple(map(tuple, resolutions))
        self.audio = audio
        self.original_mutes = {}
        self.resize_applied = False
        self.process_identity = None

    def restore_audio(self):
        for identity, (volume, muted) in tuple(self.original_mutes.items()):
            volume.SetMute(muted, None)
            del self.original_mutes[identity]

    def close(self):
        try:
            self.restore_audio()
        finally:
            if self.audio is not None: self.audio.close()

    def poll(self):
        device = self.device
        window = device.window
        if self.process_identity is None:
            self.process_identity = (window._pid, window._process_created)
        if device.target_exited(self.process_identity):
            return bool(self.values['Exit App when Game Exits'])
        if not window.exists:
            return False
        if self.values['Auto Resize Game Window'] and not self.resize_applied:
            device.resize_client(self.resolutions, self.minimum, self.ratio)
            self.resize_applied = True
        if not self.values['Auto Resize Game Window']:
            self.resize_applied = False
        if self.values['Mute Game while in Background']:
            if self.audio is None: self.audio = ProcessAudio()
            background = device.foreground_pid() != window._pid
            for identity, volume in self.audio.sessions(window._pid):
                if identity not in self.original_mutes:
                    self.original_mutes[identity] = (volume, bool(volume.GetMute()))
                desired = True if background else self.original_mutes[identity][1]
                if bool(volume.GetMute()) != desired: volume.SetMute(desired, None)
        elif self.original_mutes:
            self.restore_audio()
        return False
