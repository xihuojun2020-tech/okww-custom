"""Daily reserve authorization. Full/unknown activity can only revoke permission."""
from dataclasses import dataclass
import re
import time


@dataclass
class DailyReservePolicy:
    profile_id: str
    full_seen: bool = False
    activity_ready: object = None
    observed_at: float = 0
    remaining: int = 0
    consumed: int = 0
    refresh_required: bool = False
    refresh: object = None
    pending_conversion: bool = False
    budget_initialized: bool = False
    resource_shortfall: object = None

    def observe(self, ready, now=None):
        self.full_seen |= ready is True
        self.activity_ready = ready
        self.observed_at = time.monotonic() if now is None else now

    def allowance(self, current, requested, now=None):
        now=time.monotonic() if now is None else now
        if self.full_seen or self.pending_conversion or self.activity_ready is not False or now-self.observed_at>30:
            return 0
        return max(0,min(requested-current,self.remaining-current))

    def spend(self, amount):
        self.consumed += amount
        self.remaining=max(0,self.remaining-amount)


def conversion_quantity_box(boxes):
    """A standalone amount must be uniquely adjacent to an explicit quantity label."""
    labels = [b for b in boxes if re.fullmatch(
        r'(?:转化数量|转换数量|兑换数量|轉換數量|轉化數量|ConversionQuantity|ConvertAmount)[:：]?',
        re.sub(r'\s+', '', b.name), re.I)]
    if len(labels) != 1:
        return None
    label = labels[0]
    if not all(hasattr(label, key) for key in ('x', 'y', 'width', 'height')):
        return None
    candidates = [b for b in boxes if re.fullmatch(r'\d{1,4}', b.name.strip())
                  and all(hasattr(b, key) for key in ('x', 'y', 'width', 'height'))
                  and label.x + label.width <= b.x <= label.x + label.width + label.width * 3
                  and abs(b.y + b.height / 2 - label.y - label.height / 2) <= max(label.height, b.height)]
    return candidates[0] if len(candidates) == 1 else None


def conversion_amount(boxes):
    # Only an explicitly labelled amount; resource balances are not conversion quantities.
    texts = [re.sub(r'\s+', '', b.name) for b in boxes]
    if not any(re.fullmatch(r'(?:备用结晶波片|備用結晶波片|备用体力|BackupWaveplates)(?:转化|转换|轉換)?', t, re.I) for t in texts):
        return None
    if any(re.search(r'星声|星聲|月相|结晶溶剂|結晶溶劑', t) for t in texts):
        return None
    values=[]
    for text in texts:
        match=re.fullmatch(r'(?:转化数量|转换数量|兑换数量|轉換數量|轉化數量|ConversionQuantity|ConvertAmount)[:：]?(\d{1,4})',text,re.I)
        if match:values.append(int(match[1]))
    if not values and (box := conversion_quantity_box(boxes)) is not None:
        values.append(int(box.name))
    return values[0] if len(values)==1 and values[0]>0 else None


def conversion_matches(before,after,amount):
    current,reserve,total=before
    a,b,c=after
    return (min(a,b,c)>=0 and b==reserve-amount and amount<=a-current<=amount+1
            and 0<=c-total<=1 and abs(a+b-c)<=1)
