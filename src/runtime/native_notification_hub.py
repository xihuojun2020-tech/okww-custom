# SPDX-License-Identifier: AGPL-3.0-or-later
"""Task notification fanout; HTTP completion and desktop ownership stay separate."""

import cv2

from src.runtime.diagnostic_export import sanitize_text
from src.runtime.native_notifications import ROUTES
from src.runtime.native_screenshots import masked_native_frame


class NativeNotificationHub:
    def __init__(self, context, http, *, desktop=None):
        self.context, self.http, self.desktop = context, http, desktop

    def notify(self, title, message, images=(), *, cached_frame=None):
        http_enabled = any(self.http.config[key] for key in ROUTES.values())
        desktop_enabled = self.desktop is not None and any(self.http.config[key] for key in (
            'QQ Desktop Notification (Not Reliable)', 'WeChat Desktop Notification (Not Reliable)'))
        if not http_enabled and not desktop_enabled:
            return
        frames = list(images) if isinstance(images, (list, tuple)) else [images] if images is not None else []
        if cached_frame is not None:
            frames.append(cached_frame)
        encoded = []
        for frame in frames:
            if frame is None:
                continue
            success, png = cv2.imencode('.png', masked_native_frame(frame))
            if not success:
                raise OSError('Unable to encode notification image')
            encoded.append(png.tobytes())
        title, message = sanitize_text(title or ''), sanitize_text(message)
        if http_enabled:
            future = self.http.submit(title, message, encoded)
            future.add_done_callback(self._completed)
        if desktop_enabled:
            for future in self.desktop.submit(title, message, encoded):
                future.add_done_callback(lambda done: self._completed(done, single=True))

    def _completed(self, future, *, single=False):
        if future.cancelled():
            results = [{'route': 'desktop' if single else 'http', 'status': 'cancelled'}]
        else:
            try:
                value = future.result()
                results = [value] if single else value
            except Exception as error:
                results = [{'route': 'desktop' if single else 'http', 'status': 'failed', 'failure': type(error).__name__}]
        self.context.emit('notification-delivery', results=results)

    def close(self):
        try:
            if self.desktop is not None:
                self.desktop.close()
        finally:
            self.http.close()
