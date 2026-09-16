"""Image-only navigation for the fixed-camera resonance activity (1280x720 coordinates)."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import math
import re

import cv2
import numpy as np

ASSETS = Path(__file__).resolve().parents[2] / 'assets/images/activities/resonance_simulation'
DEFAULT_RULES = '奖励|行动资金\n奖励|共鸣因子\n下一关|藏宝地\n下一关|战斗区域'


def compact(text):
    return re.sub(r'\s+', '', str(text))


def rules_from_text(text):
    rules = []
    for line in str(text).splitlines():
        if not line.strip():
            continue
        parts = line.split('|')
        phase, word = ('通用', parts[0]) if len(parts) == 1 else parts if len(parts) == 2 else ('', '')
        phase, word = compact(phase), compact(word)
        if phase not in ('奖励', '下一关', '通用') or len(word) < 2 or len(word) > 40:
            raise ValueError('目标文字每行填写 阶段|关键词；阶段为奖励、下一关、通用，关键词为2至40字')
        rules.append((phase, word))
    if not rules or len(rules) > 30:
        raise ValueError('请填写1至30条目标文字')
    return rules


@dataclass(frozen=True)
class Target:
    kind: str
    name: str
    point: tuple
    rank: int = 0
    label: tuple = ()
    health_width: float = 0


def same_target(a, b):
    return bool(a and b and (a.kind, a.name) == (b.kind, b.name)
                and math.dist(a.point, b.point) < .10)


def movement(point, feet=(.51, .58), deadzone=.025):
    dx, dy = point[0]-feet[0], point[1]-feet[1]
    return tuple(k for v, k in ((dx, 'd'), (-dx, 'a'), (dy, 's'), (-dy, 'w')) if v > deadzone)


@lru_cache(maxsize=2)
def template(name):
    image = cv2.imread(str(ASSETS / (name+'.png')))
    if image is None:
        raise RuntimeError('缺少群声共振图像资产：'+name)
    return image


def world_point(x, y):
    # Mask only fixed HUD, keeping world objects near the right/left edge.
    return .09 < y < .81 and not (x < .24 and .20 < y < .34)


def resized(frame):
    return cv2.resize(frame, (1280,720), interpolation=cv2.INTER_AREA)


def scene_visible(frame):
    image = resized(frame)
    score = cv2.matchTemplate(image[12:62,12:78], template('hud'), cv2.TM_CCOEFF_NORMED).max()
    # Activity glyph plus the lower central player HP bar; excludes menus/loading.
    hsv = cv2.cvtColor(image[681:699, 525:742], cv2.COLOR_BGR2HSV)
    health = cv2.inRange(hsv, (0,0,150), (179,85,255))
    return bool(score >= .78 and np.count_nonzero(health) > 180)


def markers(image):
    result = []
    for size in (16,17,18,20):
        # Inner symbol avoids the terrain/glow outside the purple ring.
        patch=cv2.resize(template('marker')[5:22,5:22],(size,size))
        mask = cv2.matchTemplate(image, patch, cv2.TM_CCOEFF_NORMED)
        for _ in range(4):
            _, score, _, (x,y) = cv2.minMaxLoc(mask)
            if score < .78:
                break
            px,py = (x+size/2)/1280, (y+size/2)/720
            hsv=cv2.cvtColor(image[y:y+size,x:x+size],cv2.COLOR_BGR2HSV)
            purple=cv2.inRange(hsv,(115,45,90),(160,255,255))
            if (world_point(px,py) and np.count_nonzero(purple)>size*size*.12
                    and all(math.dist((px,py),t.point)>.025 for t in result)):
                result.append(Target('marker', '任务指引', (px,py)))
            mask[max(0,y-20):y+21,max(0,x-20):x+21] = -1
    return result


def blood_bars(image, previous=None):
    # Same enemy red range as CombatCheck, with shape and HUD exclusion.
    mask = cv2.inRange(image, (55,55,174), (76,85,225))
    contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    bars=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if 4 <= w <= 240 and 2 <= h <= 10 and w/h >= 2 and cv2.contourArea(contour)/(w*h) > .45:
            if world_point((x+w/2)/1280,y/720):
                target=Target('enemy','敌人',((x+w/2)/1280,min(.80,(y+h+38)/720)),health_width=w)
                if w >= 18 and w/h >= 5 or same_target(target,previous):
                    bars.append(target)
    return bars


def object_anchor(image, box):
    """Find the bright object below its label, aiming at its base rather than text."""
    x,y,w,h=box
    left=max(0,int(x+w/2-100));right=min(1280,int(x+w/2+100))
    top=max(0,int(y+h+4));bottom=min(583,int(y+h+220))
    if bottom <= top:
        return None
    crop=image[top:bottom,left:right]
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(12,60,165),(92,255,255))
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    parts=[]
    for c in contours:
        bx,by,bw,bh=cv2.boundingRect(c)
        if 16 <= bw <= 195 and 10 <= bh <= 205 and cv2.contourArea(c) >= 120:
            parts.append((bx,by,bw,bh))
    if not parts:
        return None
    # Prefer the lowest sizeable component (portal pedestal, or orb bottom).
    bx,by,bw,bh=max(parts,key=lambda b:b[1]+b[3])
    return ((left+bx+bw/2)/1280,(top+by+bh-min(12,bh*.2))/720)


def text_targets(frame, boxes, rules, phase, exact=False):
    image=resized(frame);height,width=frame.shape[:2]
    targets=[]
    for b in boxes:
        x,y,w,h=b.x*1280/width,b.y*720/height,b.width*1280/width,b.height*720/height
        if not world_point((x+w/2)/1280,(y+h/2)/720) or getattr(b,'confidence',1) < .65:
            continue
        name=compact(b.name)
        for rank,(scope,word) in enumerate(rules):
            # Rewards may remain after the objective advances; always collect first.
            if scope == '下一关' and phase != '下一关':
                continue
            if scope == '奖励' and phase not in ('奖励','下一关'):
                continue
            if (name == word if exact else word in name):
                point=object_anchor(image,(x,y,w,h))
                if point:
                    targets.append(Target('object',name,point,rank,(x/1280,y/720,(x+w)/1280,(y+h)/720)))
                break
    return targets


def choose(targets, previous=None, feet=(.51,.58)):
    if not targets:
        return None
    best_rank=min(t.rank for t in targets)
    choices=[t for t in targets if t.rank == best_rank]
    tracked=next((t for t in choices if same_target(t,previous)),None)
    return tracked or min(choices,key=lambda t: math.dist(t.point,feet))


class Tracker:
    """Two distinct capture tokens; disappearance never means completion."""
    def __init__(self):
        self.target=None
        self.token=None
        self.count=0

    def update(self,target,token):
        if token == self.token:
            return None
        self.token=token
        self.count=self.count+1 if same_target(target,self.target) else 1
        self.target=target
        return target if target is not None and self.count >= 2 else None
