"""Reproducibly copy owner-supplied fixtures and crop the forty observed icons."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TIMES = ('13_28_49', '13_33_40', '13_33_47', '13_33_50',
         '17_02_22', '17_02_46', '17_03_02', '17_03_16',
         '17_29_37', '17_29_48', '17_29_52', '17_29_58', '17_30_02',
         '17_40_00', '17_40_05')


def prepare(source):
    fixtures = ROOT / 'tests/images/materials'
    templates = ROOT / 'assets/materials/templates'
    fixtures.mkdir(parents=True, exist_ok=True)
    templates.mkdir(parents=True, exist_ok=True)
    images, manifest = {}, {}
    for stamp in TIMES:
        path = source / f'鸣潮   2026_9_11 {stamp}.png'
        raw = path.read_bytes()
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        images[stamp] = cv2.resize(image, (2048, 1152), interpolation=cv2.INTER_AREA)
        safe = images[stamp].copy()
        safe[1100:, 1450:] = 0  # account feature code outside all recognition regions
        safe[:22] = 0  # desktop performance overlay
        fixture = cv2.resize(safe, (1280, 720), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(fixtures / f'{stamp}.png'), fixture)
        manifest[stamp] = dict(source_basename=path.name, source_sha256=hashlib.sha256(raw).hexdigest(),
                               source_size=[image.shape[1], image.shape[0]], fixture_size=[1280, 720])
    catalog = []
    for row, (weapon, key) in enumerate(zip(('迅刀','音感仪','长刃','臂铠','佩枪'),
                                           ('sword','rectifier','broadblade','gauntlet','pistol'))):
        for series in ('a', 'b'):
            for rarity in ('green', 'blue', 'purple', 'gold'):
                if series == 'a':
                    stamp = '17_02_46' if rarity == 'green' else '17_02_22'
                    x = dict(green=1617, blue=1581, purple=1461, gold=1341)[rarity]
                    y = 290 + row * 163
                else:
                    stamp = '17_03_02' if rarity == 'gold' else '17_03_16'
                    x = dict(green=1596, blue=1475, purple=1355, gold=1461)[rarity]
                    y = (274 if rarity == 'gold' else 286) + row * 163
                tile = images[stamp][y-50:y+50, x-50:x+50]
                item_id = f'{key}_{series}_{rarity}'
                cv2.imwrite(str(templates / f'{item_id}.png'), cv2.resize(tile, (96,96)))
                catalog.append(dict(item_id=item_id, group_id=f'{key}_{series}', weapon_type=weapon,
                                    rarity=rarity, source_type='forgery', names=[],
                                    template_paths=[f'templates/{item_id}.png'], source_frame=stamp))
    monster_frame = cv2.resize(cv2.imread(str(fixtures/'13_33_47.png')),(2048,1152),interpolation=cv2.INTER_AREA)
    for group,rarity,cx,cy in (
            ('monster_star','green',1198,389),('monster_star','blue',1319,389),
            ('monster_star','purple',1440,389),('monster_star','gold',1561,389),
            ('monster_necklace','blue',1319,550),('monster_necklace','purple',1440,550),
            ('monster_necklace','gold',1561,550)):
        identity=f'{group}_{rarity}'
        cv2.imwrite(str(templates/f'{identity}.png'),monster_frame[cy-52:cy+52,cx-52:cx+52])
        catalog.append(dict(item_id=identity,group_id=group,weapon_type='',rarity=rarity,
                            source_type='monster',names=[],template_paths=[f'templates/{identity}.png']))
    manifest['settlement_1740'] = dict(frames=['17_40_00','17_40_05'],
        expected=dict(counts=[13,16,3,0], reward_units=2, stamina=80, equivalent=88, slots=22,
                      target_group='rectifier_b', overlap_rows=[[1,0]]))
    (fixtures / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (ROOT / 'assets/materials/catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    prepare(parser.parse_args().source)
