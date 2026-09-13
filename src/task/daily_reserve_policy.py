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


def conversion_amount(boxes):
    # Only an explicitly labelled amount; resource balances are not conversion quantities.
    texts = [re.sub(r'\s+', '', b.name) for b in boxes]
    if not any(re.fullmatch(r'(?:备用结晶波片|備用結晶波片|备用体力)(?:转化|转换|轉換)?', t) for t in texts):
        return None
    if any(re.search(r'星声|星聲|月相|结晶溶剂|結晶溶劑', t) for t in texts):
        return None
    values=[]
    for text in texts:
        match=re.fullmatch(r'(?:转化数量|转换数量|兑换数量|轉換數量)[:：]?(\d{1,4})',text)
        if match:values.append(int(match[1]))
    return values[0] if len(values)==1 and values[0]>0 else None


def conversion_matches(before,after,amount):
    current,reserve,total=before
    a,b,c=after
    return (min(a,b,c)>=0 and b==reserve-amount and amount<=a-current<=amount+1
            and 0<=c-total<=1 and abs(a+b-c)<=1)
