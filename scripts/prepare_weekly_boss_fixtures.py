"""Keep only approved UI regions from the seven supplied weekly screenshots.

Run with a captures directory argument. Never copies full source screenshots.
Output retains original dimensions so production normalized ROIs can be tested.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('captures', type=Path)
    parser.add_argument('--victory', type=Path, help='Optional arena victory failure screenshot')
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'tests/images/weekly_boss'
    output.mkdir(parents=True, exist_ok=True)
    samples = {
        'list1': ('12_55_07', [(0.365, 0.13, 0.97, 0.89)]),
        'list2': ('12_55_13', [(0.365, 0.13, 0.97, 0.89)]),
        'list3': ('12_55_17', [(0.365, 0.13, 0.97, 0.89)]),
        'detail': ('11_08_08', [(0.02, 0.03, 0.38, 0.095), (0.78, 0.033, 0.89, 0.079),
                                  (0.63, 0.825, 0.97, 0.95)]),
        'team': ('11_08_14', [(0.775, 0.864, 0.95, 0.95)]),
        'claim': ('11_10_43', [(0.61, 0.47, 0.83, 0.56)]),
        'settlement': ('11_10_54', [(0.4, 0.265, 0.6, 0.325), (0.24, 0.46, 0.765, 0.595),
                                      (0.28, 0.81, 0.73, 0.95)]),
    }
    if args.victory:
        samples['victory'] = (args.victory, [(0.4, 0.235, 0.6, 0.315)])
    for name, (stamp, regions) in samples.items():
        source = stamp if isinstance(stamp, Path) else args.captures / f'鸣潮   2026_9_8 {stamp}.png'
        frame = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f'Cannot decode {source.name}')
        height, width = frame.shape[:2]
        sanitized = np.zeros_like(frame)
        for x1, y1, x2, y2 in regions:
            a, b, c, d = int(width*x1), int(height*y1), int(width*x2), int(height*y2)
            sanitized[b:d, a:c] = frame[b:d, a:c]
        ok, encoded = cv2.imencode('.png', sanitized)
        if not ok:
            raise ValueError('PNG encoding failed')
        encoded.tofile(output / f'{name}.png')
        print(f'{name}: sanitized UI only, {width}x{height}')


if __name__ == '__main__':
    main()
