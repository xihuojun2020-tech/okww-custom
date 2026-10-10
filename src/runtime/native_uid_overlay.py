# SPDX-License-Identifier: AGPL-3.0-or-later
"""Process only the configured UID ROI from the current owner's cached frame."""
import base64
import time

import cv2
import numpy as np

from src.runtime.account_task_support import native_blur_area

class NativeUIDOverlay:
    def __init__(self, context, preferences, target_state, *, clock=time.monotonic):
        self.context, self.preferences, self.target_state = context, preferences, target_state
        self.clock = clock
        self.active = False
        self.next_update = 0

    def clear(self):
        active = self.active
        self.active = False
        self.next_update = 0
        if active:
            self.context.emit('overlay-clear', owner_id=self.context.run_id)

    def poll(self, frame):
        if (not self.preferences['Enable Blur'] or self.context.pause.is_set()
                or self.context.stop.is_set() or frame is None):
            self.clear()
            return
        try:
            target = self.target_state()
        except Exception:
            self.clear()
            raise
        height, width = frame.shape[:2]
        if target is None or target['width'] != width or target['height'] != height:
            self.clear()
            return
        now = self.clock()
        if now < self.next_update:
            return
        box = native_blur_area(width, height)
        x, y = max(0, int(box.x)), max(0, int(box.y))
        w, h = min(width, box.x + box.width)-x, min(height, box.y + box.height)-y
        w, h = int(w), int(h)
        if w <= 0 or h <= 0:
            self.clear()
            return
        if self.preferences['Blur Algorithm'] == 'Inpaint':
            left, top = max(0, x-10), max(0, y-10)
            right, bottom = min(width, x+w+10), min(height, y+h+10)
            source = frame[top:bottom, left:right]
            mask = np.zeros(source.shape[:2], np.uint8)
            mask[y-top:y-top+h, x-left:x-left+w] = 255
            patch = cv2.inpaint(source, mask, 5, cv2.INPAINT_TELEA)[y-top:y-top+h, x-left:x-left+w]
        else:
            small = cv2.resize(frame[y:y+h,x:x+w], (min(w,8),min(h,8)), interpolation=cv2.INTER_AREA)
            enlarged = cv2.resize(small,(w,h),interpolation=cv2.INTER_LINEAR)
            sigma = max(4.,min(w,h)/5.)
            patch = cv2.GaussianBlur(enlarged,(0,0),sigmaX=sigma,sigmaY=sigma)
        success, png = cv2.imencode('.png',patch)
        if not success:
            self.clear()
            raise OSError('Unable to encode UID overlay patch')
        self.active = True
        self.context.emit('overlay-update', owner_id=self.context.run_id, target=target,
                          patch={'x':x,'y':y,'width':w,'height':h,
                                 'png':base64.b64encode(png).decode('ascii')})
        self.next_update = now+self.preferences['Blur Interval']

    close = clear
