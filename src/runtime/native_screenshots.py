# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write native diagnostic PNGs without exposing the private identity region."""

from pathlib import Path

import cv2

from src.runtime.account_task_support import native_blur_area


def masked_native_frame(frame):
    """Copy the executor cache before applying the existing identity mask."""
    image = frame.copy()
    height, width = image.shape[:2]
    box = native_blur_area(width, height)
    image[max(0, box.y):min(height, box.y + box.height),
          max(0, box.x):min(width, box.x + box.width)] = 0
    return image


def save_native_screenshot(data_dir, name, frame):
    if name is None:
        raise ValueError('screenshot name cannot be None')
    root = (Path(data_dir) / 'okww监控室').resolve()
    destination = (root / f'{name}.png').resolve()
    if not destination.is_relative_to(root):
        raise ValueError('Screenshot name leaves the evidence directory')
    image = masked_native_frame(frame)
    success, encoded = cv2.imencode('.png', image)
    if not success:
        raise OSError(f'Unable to encode screenshot: {name}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded.tobytes())
    from src.runtime.native_diagnostics import screenshot_saved
    screenshot_saved(destination)
    return destination
