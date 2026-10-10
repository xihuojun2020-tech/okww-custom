# SPDX-License-Identifier: AGPL-3.0-or-later
"""Program options with real native consumers and one-time exact legacy migration."""
import json
import math
from pathlib import Path

from src.runtime.native_config import Config

NAME = 'Program Preferences'
DEFAULTS = {'Auto Resize Game Window': True, 'Mute Game while in Background': False,
            'Exit App when Game Exits': False, 'Trigger Interval': 1, 'Use DirectML': 'Auto',
            'Enable Blur': False, 'Blur Algorithm': 'Inpaint', 'Blur Interval': 1}


class NativeProgramPreferences:
    def __init__(self, data_root):
        folder = Path(data_root).resolve() / 'configs'
        first = not (folder / (NAME + '.json')).exists()
        legacy_path = folder / 'Basic Options.json'
        legacy = json.loads(legacy_path.read_text(encoding='utf-8')) if first and legacy_path.exists() else {}
        if not isinstance(legacy, dict):
            raise ValueError('Legacy Basic Options must contain a JSON object')
        values = {key: legacy[key] for key in DEFAULTS if key in legacy}
        for key, value in values.items():
            if key == 'Use DirectML':
                if value not in ('Yes', 'No', 'Auto'): raise ValueError('Invalid DirectML preference')
            elif key == 'Blur Algorithm':
                if value not in ('Blur', 'Inpaint'): raise ValueError('Invalid blur algorithm')
            elif key in ('Trigger Interval', 'Blur Interval'):
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid program interval: ' + key)
            elif type(value) is not bool:
                raise ValueError('Invalid boolean program preference: ' + key)
        self.config = Config(NAME, {**DEFAULTS, **values}, folder=str(folder))
        self.config.default = dict(DEFAULTS)
