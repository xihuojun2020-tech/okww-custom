"""Explicit material identities. Unknown icons are never assumed farmable."""
import json
import re
from pathlib import Path
import cv2
import numpy as np
from src.materials.model import RARITIES

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / 'assets/materials/catalog.json'


class Catalog:
    def __init__(self, path=DEFAULT_CATALOG):
        self.path = Path(path)
        entries = json.loads(self.path.read_text(encoding='utf-8'))
        self.items = {}
        self.templates = []
        for item in entries:
            identity = item['item_id']
            if identity in self.items or item['rarity'] not in RARITIES:
                raise ValueError('Duplicate material identity or invalid rarity')
            self.items[identity] = item
            for relative in item['template_paths']:
                template_path = (self.path.parent / relative).resolve()
                if not template_path.is_relative_to(self.path.parent.resolve()):
                    raise ValueError('Template path outside catalog')
                tile = cv2.imdecode(np.frombuffer(template_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
                if tile is None:
                    raise ValueError(f'Invalid template: {identity}')
                self.templates.append((identity, self.icon(tile)))
        for group in self.groups:
            rows = [v for v in self.items.values() if v['group_id'] == group]
            if len(rows) != 4 or {v['rarity'] for v in rows} != set(RARITIES):
                raise ValueError(f'Incomplete material group {group}')

    @property
    def groups(self):
        return tuple(dict.fromkeys(v['group_id'] for v in self.items.values() if v['source_type']=='forgery'))

    def get(self, item_id):
        return self.items[item_id]

    def find_name(self, text):
        normalized = re.sub(r'\W+', '', text).casefold()
        matches = [v for v in self.items.values() if any(
            normalized == re.sub(r'\W+', '', n).casefold() for n in v['names'])]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def icon(tile):
        image = cv2.resize(tile, (96,96), interpolation=cv2.INTER_AREA)
        # Avoid top badges, rarity strip, quantity and selection frame.
        return image[23:75, 16:80]

    def match(self, tile, threshold=.70, margin=.055):
        icon = cv2.resize(tile, (96,96), interpolation=cv2.INTER_AREA)[15:80, 8:88]
        scores = []
        for identity, template in self.templates:
            score = float(cv2.matchTemplate(icon, template[5:45, 8:56], cv2.TM_CCOEFF_NORMED).max())
            scores.append((score, identity))
        scores.sort(reverse=True)
        if not scores or scores[0][0] < threshold or (len(scores)>1 and scores[0][0]-scores[1][0]<margin):
            return None, scores[:2]
        return self.get(scores[0][1]), scores[:2]
