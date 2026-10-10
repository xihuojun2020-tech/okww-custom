"""Production color contracts extracted from ok-script into the AGPL game pack.

This module retains the existing BGR, mask and crop semantics. It deliberately
does not import Box, task classes, Qt, devices, ok or GameFrame.
"""

import cv2
import numpy as np


def color_range_to_bound(color_range):
    lower_bound = np.array([color_range['b'][0], color_range['g'][0], color_range['r'][0]], dtype='uint8')
    upper_bound = np.array([color_range['b'][1], color_range['g'][1], color_range['r'][1]], dtype='uint8')
    return lower_bound, upper_bound


def get_mask_in_color_range(image, color_range):
    lower_bound, upper_bound = color_range_to_bound(color_range)
    mask = cv2.inRange(image, lower_bound, upper_bound)
    return mask, np.count_nonzero(mask)


def mask_white(image, lower_white=255):
    if len(image.shape) == 2 or image.shape[2] == 1:
        lower_white = np.array([lower_white])
        upper_white = np.array([255])
    else:
        lower_white = np.array([lower_white, lower_white, lower_white])
        upper_white = np.array([255, 255, 255])
    return cv2.inRange(image, lower_white, upper_white)


def is_pure_black(frame):
    for channel in cv2.split(frame):
        if cv2.countNonZero(channel) > 0:
            return False
    return True


def calculate_color_percentage(image, color_ranges, box=None):
    if box is not None:
        if (box.x >= 0 and box.y >= 0
                and box.x + box.width <= image.shape[1]
                and box.y + box.height <= image.shape[0]
                and box.width > 0 and box.height > 0):
            image = image[box.y:box.y + box.height, box.x:box.x + box.width, :3]
        else:
            return 0
    else:
        image = image[:, :, :3]
    mask = cv2.inRange(image, (color_ranges['b'][0], color_ranges['g'][0], color_ranges['r'][0]),
                       (color_ranges['b'][1], color_ranges['g'][1], color_ranges['r'][1]))
    return cv2.countNonZero(mask) / (image.size / 3)
