"""Rebuild sanitized NAS regression images from the explicitly reviewed archive."""
import argparse
import hashlib
from pathlib import Path
import zipfile
import cv2
import numpy as np

SHA256 = '7d012c5e2bf7631c68f917f4b9c058bef30132e69756329303bfe5471a81ad57'
FRAMES = {
    'before_scroll': 'b6ec65aec7ca4f87a44b76e2f4af13b8',
    'after_error': '262c74d8b289415b829fa0b455731921',
    'world': 'f6aaf8f858a548e79cbcd4fca14df9da',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    with args.archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != SHA256:
            raise ValueError('Archive SHA256 mismatch')
    root = Path('tests/images/daily_claim_stability')
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.archive) as archive:
        for label, identity in FRAMES.items():
            name = next(n for n in archive.namelist() if n.endswith('/'+identity+'.png'))
            im = cv2.imdecode(np.frombuffer(archive.read(name), np.uint8), 1)
            im[:24] = 0
            im[-45:] = 0
            cv2.imwrite(str(root / (label+'.png')), cv2.resize(im, (1280, 720)))


if __name__ == '__main__':
    main()
