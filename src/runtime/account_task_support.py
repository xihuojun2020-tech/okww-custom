# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account task file paths and privacy geometry for explicit native workers."""

import json
from pathlib import Path

from src.runtime.combat_api import is_native


def data_root():
    from src.runtime.account_runtime_bootstrap import get_account_runtime
    runtime = get_account_runtime()
    if runtime is None:
        raise RuntimeError('Native account runtime must be prepared before task import')
    return runtime.root


def get_relative_path(*parts):
    if not is_native():
        from ok.util.file import get_relative_path as legacy_path
        return legacy_path(*parts)
    return str(data_root().joinpath(*parts))


def read_json_file(path):
    if not is_native():
        from ok.util.file import read_json_file as legacy_read
        return legacy_read(path)
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def write_json_file(path, value):
    if not is_native():
        from ok.util.file import write_json_file as legacy_write
        return legacy_write(path, value)
    from src.config_integrity import atomic_write_json
    atomic_write_json(path, value, indent=4)
    return True


def blur_area(width, height):
    if not is_native():
        from config import blur_area as legacy_area
        return legacy_area(width, height)
    return native_blur_area(width, height)


def native_blur_area(width, height):
    from src.vision.boxes import Box
    blur_width = int(.12 * width)
    blur_height = int(.024 * height)
    return Box(width * .879, height * .976, blur_width * .973, blur_height * .994)


def program_version():
    if is_native():
        from src.runtime.account_runtime_bootstrap import get_account_runtime
        return get_account_runtime().program_version
    from config import version
    return version


def emit_config_changed(task):
    task.executor.context.emit('task-config-changed', task=type(task).__name__)


def is_close_to_pure_color(image, max_colors=5000, percent=.97):
    if not is_native():
        from ok.util.color import is_close_to_pure_color as legacy_check
        return legacy_check(image, max_colors=max_colors, percent=percent)
    # Same BGR color-count contract as the AGPL ok-script capture helper.
    import cv2
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    color_counts = {}
    total_pixels = image.shape[0] * image.shape[1]
    for row in image:
        for pixel in row:
            color = tuple(pixel)
            color_counts[color] = color_counts.get(color, 0) + 1
            if len(color_counts) > max_colors:
                return False
    return max(color_counts.values()) / total_pixels > percent
