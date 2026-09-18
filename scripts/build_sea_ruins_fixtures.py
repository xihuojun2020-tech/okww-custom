"""Build sanitized reference assets from the user's 2026-09-18 captures.

Run with the repository .venv. This is an image transformation, not runtime UI
capture. Original screenshots and their account identifier are never committed.
"""
from pathlib import Path
import cv2
import numpy as np

CAPTURES = Path('C:/Users/Administrator/Videos/Captures')
SOURCES = {
    'presets': '10_33_23', 'tokens': '12_15_22', 'map': '10_29_59',
    'detail': '10_31_14', 'exit_side': '12_22_50', 'exit_front': '12_22_55',
    'exit_prompt': '12_24_55', 'result': '12_28_26', 'next_floor': '12_29_31',
}


def write(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cv2.imencode('.png', frame)[1].tobytes())


def main():
    frames = {}
    for key, time in SOURCES.items():
        source = CAPTURES / f'鸣潮   2026_9_18 {time}.png'
        frame = cv2.imdecode(np.frombuffer(source.read_bytes(), np.uint8), 1)
        frame = cv2.resize(frame, (2048, 1152))
        frame[:24] = 0
        frame[1110:] = 0
        frames[key] = frame
        write(Path('tests/fixtures/sea_ruins') / f'{key}.png', cv2.resize(frame, (1280, 720)))
    root = Path('assets/images/sea_ruins')
    write(root / 'exit.png', frames['exit_front'][298:337, 951:991])
    write(root / 'exit_side.png', frames['exit_side'][433:473, 1615:1654])
    write(root / 'exit_close.png', frames['exit_prompt'][271:311, 1000:1040])
    write(root / 'lock.png', frames['tokens'][280:311, 228:258])
    write(root / 'f.png', frames['exit_prompt'][577:614, 1295:1333])
    write(root / 'infinity.png', frames['tokens'][845:868, 225:250])


if __name__ == '__main__':
    main()
