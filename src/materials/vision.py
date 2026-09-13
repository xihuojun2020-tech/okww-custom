"""Screen parsers in a normalized 2048x1152 space; unknowns remain observable."""
import hashlib
import re
from collections import defaultdict
import cv2
import numpy as np
from src.materials.model import Drop

SIZE = (2048,1152)


def normalize(frame):
    if frame is None or frame.size == 0:
        raise ValueError('Missing game frame')
    if frame.shape[:2] == (SIZE[1], SIZE[0]):
        return frame
    return cv2.resize(frame, SIZE, interpolation=cv2.INTER_AREA)


def text(ocr, crop, numeric=False):
    scale = 3 if numeric else 2
    crop = cv2.copyMakeBorder(cv2.resize(crop, None, fx=scale, fy=scale), 20,20,20,20,
                             cv2.BORDER_CONSTANT if numeric else cv2.BORDER_REPLICATE)
    result = ocr(crop)
    if isinstance(result, str):
        return result
    return ' '.join(str(getattr(b, 'name', b)) for b in result)


def parse_number(value):
    value = re.sub(r'\s+', '', value).replace('×','x').replace('X','x')
    match = re.fullmatch(r'x?(\d{1,8})', value)
    return int(match[1]) if match else None


def stripe_rects(frame, region, min_width=65):
    x1,y1,x2,y2 = region
    hsv = cv2.cvtColor(frame[y1:y2,x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv,(0,65,75),(179,255,255))
    mask = cv2.morphologyEx(mask,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(min_width,2)))
    rects = []
    for contour in cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
        x,y,w,h = cv2.boundingRect(contour)
        if w >= min_width and 2 <= h <= 35:
            rects.append((x+x1,y+y1,w,h))
    return rects


def rows_by_bottom(rects):
    groups=[]
    for rect in sorted(rects,key=lambda r:r[1]+r[3]):
        bottom=rect[1]+rect[3]
        group=next((g for g in groups if abs(g[0][1]+g[0][3]-bottom)<12),None)
        if group is None:
            groups.append([rect])
        else:
            group.append(rect)
    return groups


def _unknown_id(tile):
    # Fingerprint is a review identity only, never implies a farmable material.
    icon = cv2.resize(tile,(16,16))
    return 'unknown:'+hashlib.sha256(icon.tobytes()).hexdigest()[:16]


def parse_reward_frame(frame, ocr, catalog):
    frame=normalize(frame)
    cells=[]; errors=[]; partial=[]
    title=text(ocr,frame[300:395,780:1280])
    if not re.search(r'挑战成功|挑戰成功|Challenge\s*(?:Complete|Success)',title,re.I):
        return dict(scene='unknown',cells=[],errors=['not_settlement'],partial_cells=[],anchors={})
    rows=rows_by_bottom(stripe_rects(frame,(300,418,1740,830),120))
    for local_row, rects in enumerate(rows):
        bottom=max(y+h for x,y,w,h in rects)
        top=bottom-148
        for x,y,w,h in sorted(rects):
            column=round((x-318)/181)
            if not 0<=column<8:
                continue
            left=317+column*181
            if top<425 or bottom>827:
                partial.append((local_row,column)); continue
            tile=frame[top:bottom,left:left+149]
            item,scores=catalog.match(tile)
            amount=parse_number(text(ocr,frame[bottom-39:bottom-1,left+30:left+148]))
            if amount is None:
                errors.append(f'quantity:{local_row}:{column}')
            cells.append(dict(local_row=local_row,column=column,box=(left,top,left+149,bottom),
                item_id=item['item_id'] if item else _unknown_id(tile),
                group_id=item['group_id'] if item else None,
                rarity=item['rarity'] if item else 'unknown',amount=amount,
                signature=cv2.resize(tile[25:100,20:125],(32,24)),
                match_status='known' if item else 'unknown',scores=scores))
    return dict(scene='reward',cells=cells,errors=errors,partial_cells=partial,
                anchors=dict(first_top=min((c['box'][1] for c in cells),default=None),
                             last_bottom=max((c['box'][3] for c in cells),default=None)))


def _same_row(a,b):
    if [c['column'] for c in a] != [c['column'] for c in b]:
        return False
    for x,y in zip(a,b):
        if x['amount'] != y['amount']:
            return False
        if x['group_id'] and y['group_id']:
            if x['item_id'] != y['item_id']:
                return False
        elif float(cv2.matchTemplate(x['signature'],y['signature'][2:-2,2:-2],cv2.TM_CCOEFF_NORMED).max())<.85:
            return False
    return True


def stitch_reward_pages(pages):
    stitched=[]; errors=[]; frame_links=[]
    for index,page in enumerate(pages):
        errors.extend(page['errors'])
        local=defaultdict(list)
        for cell in page['cells']:
            local[cell['local_row']].append(cell)
        rows=[sorted(v,key=lambda c:c['column']) for _,v in sorted(local.items())]
        if not rows:
            errors.append('empty_page'); continue
        if not stitched:
            stitched=rows
            frame_links.append(dict(page=index,overlap=0))
            continue
        candidates=[n for n in range(1,min(len(stitched),len(rows))+1)
                    if all(_same_row(a,b) for a,b in zip(stitched[-n:],rows[:n]))]
        if len(candidates)!=1:
            errors.append('ambiguous_overlap' if candidates else 'missing_overlap')
            continue
        overlap=candidates[0]
        stitched.extend(rows[overlap:])
        frame_links.append(dict(page=index,overlap=overlap))
    complete=bool(pages and pages[0].get('at_top') and pages[-1].get('at_bottom') and not errors)
    drops=tuple(Drop((row,c['column']),c['item_id'],c['group_id'],c['rarity'],c['amount'])
                for row,cells in enumerate(stitched) for c in cells if c['amount'] is not None)
    return dict(complete=complete,drops=drops,frame_links=frame_links,errors=errors)


def parse_inventory_frame(frame, ocr, catalog):
    frame=normalize(frame)
    cells=[]; errors=[]; partial=[]
    title=text(ocr,frame[36:110,105:420])
    if not re.search(r'资源|資源|Resources',title,re.I):
        return dict(scene='unknown',cells=[],errors=['not_inventory'],partial_cells=[],anchors={})
    rows=rows_by_bottom([r for r in stripe_rects(frame,(180,135,1290,968),140) if r[2]<=195])
    grid_bottoms=[max(y+h for x,y,w,h in row) for row in rows
                  if len({round((r[0]+r[2]-345)/188.5) for r in row})>=4]
    for local_row,rects in enumerate(rows):
        bottom=max(y+h for x,y,w,h in rects)
        if not any(abs((bottom-anchor)/227-round((bottom-anchor)/227))*227<12 for anchor in grid_bottoms):
            continue
        for col in sorted({round((r[0]+r[2]-345)/188.5) for r in rects}):
            left=round(185+col*188.5)
            if not 0<=col<6:
                continue
            top=bottom-156
            if top<137 or bottom+38>970:
                partial.append((local_row,col)); continue
            tile=frame[top:bottom,left:left+156]
            item,scores=catalog.match(tile, threshold=.78)
            amount=parse_number(text(ocr,frame[bottom:bottom+38,left+90:left+160], numeric=True))
            if amount is None: errors.append(f'quantity:{local_row}:{col}')
            cells.append(dict(local_row=local_row,column=col,box=(left,top,left+156,bottom+38),
                item_id=item['item_id'] if item else _unknown_id(tile), group_id=item['group_id'] if item else None,
                rarity=item['rarity'] if item else 'unknown',amount=amount,match_status='known' if item else 'unknown',scores=scores,
                signature=cv2.resize(tile[25:100,20:125],(32,24))))
    count=re.search(r'(\d+)\s*/\s*\d+',title)
    return dict(scene='inventory',cells=cells,errors=errors,partial_cells=partial,
                anchors={'declared_count':int(count[1]) if count else None})


def parse_target_frame(frame, ocr, catalog):
    frame=normalize(frame)
    if not re.search(r'培养目标|培養目標', text(ocr,frame[145:240,295:570])):
        return dict(scene='unknown',cells=[],errors=['not_target'],partial_cells=[],anchors={},
                    weekly=[],records=[],has_echo_boundary=False,target_identity='')
    boundary_text=text(ocr,frame[140:1000,780:1160])
    # OCR caller can expose positioned text, otherwise keep row/category association local.
    stripes=[r for r in stripe_rects(frame,(1100,230,1650,1000),85) if r[2]<=110]
    cells=[]; errors=[]; weekly=[]; records=[]
    for row,rects in enumerate(rows_by_bottom(stripes)):
        bottom=max(y+h for x,y,w,h in rects)
        top=bottom-104
        if top<225 or bottom>990: continue
        label=text(ocr,frame[max(140,top):bottom,790:1135])
        if '声骸' in label or '聲骸' in label: continue
        if not any(t in label for t in ('素材','材料')): continue
        row_cells=[]
        for col,(x,y,w,h) in enumerate(sorted(rects)):
            left=x-2
            tile=frame[top:bottom,left:left+105]
            item,scores=catalog.match(tile)
            value=re.sub(r'\s+','',text(ocr,frame[bottom-29:bottom+2,left:left+105]))
            match=re.fullmatch(r'(\d{1,8})/(\d{1,8})',value)
            if not match:
                errors.append(f'target_quantity:{row}:{col}')
            cell=dict(local_row=row,column=col,box=(left,top,left+105,bottom),
                item_id=item['item_id'] if item else _unknown_id(tile),group_id=item['group_id'] if item else None,
                rarity=item['rarity'] if item else 'unknown',source_type=item['source_type'] if item else None,
                amount=int(match[1]) if match else None,
                need=int(match[2]) if match else None,label=label,match_status='known' if item else 'unknown')
            row_cells.append(cell); cells.append(cell)
        records.append(dict(label=label,cells=row_cells))
        if '技能升级材料' in label:
            weekly.append(dict(label=label,cells=row_cells))
    return dict(scene='target',cells=cells,errors=errors,partial_cells=[],anchors={},
                weekly=weekly,records=records,has_echo_boundary='声骸培养' in boundary_text,
                target_identity=text(ocr,frame[155:244,303:575]))


def target_totals(pages):
    """Only full four-tier forgery rows can drive spending; unknown rows block it."""
    values = {}; errors = []
    for page in pages:
        if page['scene'] != 'target':
            errors.append('not_target')
        for record in page.get('records', []):
            if '素材' not in record['label'] and not any(c.get('source_type')=='forgery' for c in record['cells']):
                continue
            for cell in record['cells']:
                if cell.get('source_type') == 'monster':
                    continue
                if cell.get('source_type') != 'forgery' or cell['amount'] is None or cell['need'] is None:
                    errors.append('unrecognized_target_material'); continue
                key = cell['item_id']; value = (cell['amount'], cell['need'])
                if key in values and values[key] != value:
                    errors.append('target_changed_during_scan')
                values[key] = value
    from src.materials.model import Counts, RARITIES
    groups = {}
    for key in values:
        group = key.rsplit('_',1)[0]
        if group in groups: continue
        if not all(group+'_'+r in values for r in RARITIES):
            errors.append('incomplete_material_group'); continue
        groups[group] = dict(stock=Counts(*(values[group+'_'+r][0] for r in RARITIES)),
                             need=Counts(*(values[group+'_'+r][1] for r in RARITIES)))
    if not groups:
        errors.append('no_verified_material_targets')
    return groups, sorted(set(errors))


def forgery_rows(frame, ocr, catalog):
    frame=normalize(frame)
    found=[]
    for rects in rows_by_bottom(stripe_rects(frame,(1285,210,1660,1015),80)):
        bottom=max(y+h for x,y,w,h in rects); top=bottom-104
        if top<220 or bottom>1010: continue
        label=text(ocr,frame[top:bottom,935:1260])
        hits=[]
        for x,y,w,h in rects:
            if w>110: continue
            item,_=catalog.match(frame[top:bottom,x-2:x+103])
            if item and item['source_type']=='forgery' and item['weapon_type'] in label:
                hits.append(item)
        groups={i['group_id'] for i in hits}
        if len(groups)==1 and len({i['rarity'] for i in hits})>=2:
            found.append(dict(group_id=next(iter(groups)),top=top,bottom=bottom))
    return found
