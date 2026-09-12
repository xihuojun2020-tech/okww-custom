"""UI-independent quantities: actual inventory, upward synthesis and observed rewards."""
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone

RARITIES = ('green', 'blue', 'purple', 'gold')
GAME_ZONE = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class Counts:
    green: int = 0
    blue: int = 0
    purple: int = 0
    gold: int = 0

    def __post_init__(self):
        if any(type(getattr(self, f.name)) is not int or getattr(self, f.name) < 0 for f in fields(self)):
            raise ValueError('Material counts must be nonnegative integers')

    def values(self):
        return tuple(getattr(self, r) for r in RARITIES)


@dataclass(frozen=True)
class Gap:
    missing: Counts
    synthesis: Counts


@dataclass(frozen=True)
class Drop:
    position: tuple[int, int]
    item_id: str
    group_id: str | None
    rarity: str
    amount: int

    def __post_init__(self):
        if type(self.amount) is not int or self.amount < 0:
            raise ValueError('Invalid drop amount')
        if len(self.position) != 2 or any(type(n) is not int or n < 0 for n in self.position):
            raise ValueError('Invalid drop position')


@dataclass(frozen=True)
class Settlement:
    claim_id: str
    profile_id: str
    target_revision: str
    target_group: str
    stamina: int | None
    complete: bool
    drops: tuple[Drop, ...]
    reward_units: int | None
    errors: tuple[str, ...] = ()

    def __post_init__(self):
        if self.stamina is not None and (type(self.stamina) is not int or self.stamina <= 0):
            raise ValueError('Stamina must be confirmed positive consumption or unknown')
        positions = [d.position for d in self.drops]
        if len(set(positions)) != len(positions):
            raise ValueError('Duplicate reward positions')
        if self.complete:
            units = count_reward_units(self.drops, self.target_group)
            if not units or units != self.reward_units or self.errors:
                raise ValueError('Complete settlement must have verified green reward slots')
        elif self.reward_units is not None:
            raise ValueError('Partial settlement cannot claim verified reward units')


def equivalent(counts):
    return sum(n * w for n, w in zip(counts.values(), (1, 3, 9, 27)))


def calculate_gap(stock, need):
    carry = 0
    missing, synthesis = [], []
    for available, required in zip(stock.values(), need.values()):
        synthesis.append(carry)
        balance = available + carry - required
        missing.append(max(-balance, 0))
        carry = max(balance, 0) // 3
    return Gap(Counts(*missing), Counts(*synthesis))


def is_satisfied(gap):
    return gap.missing == Counts()


def week_id(now=None):
    now = now or datetime.now(GAME_ZONE)
    if now.tzinfo is None:
        raise ValueError('Weekly scans require a timezone-aware timestamp')
    day = (now.astimezone(GAME_ZONE) - timedelta(hours=4)).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def count_reward_units(drops, target_group):
    return sum(d.group_id == target_group and d.rarity == 'green' for d in drops) or None


def summarize_target(drops, target_group):
    return Counts(*(sum(d.amount for d in drops if d.group_id == target_group and d.rarity == r)
                    for r in RARITIES))


def aggregate_settlements(records):
    """Input must be one latest parse per claim, of the same material group."""
    if len({r.claim_id for r in records}) != len(records):
        raise ValueError('Select one revision per claim before aggregating')
    if len({r.target_group for r in records}) > 1:
        raise ValueError('Different material groups must not be averaged together')
    valid = [r for r in records if r.complete]
    paid = [r for r in valid if r.stamina is not None]
    units = sum(r.reward_units for r in valid)
    stamina = sum(r.stamina for r in paid)
    counts = Counts(*(sum(getattr(summarize_target(r.drops, r.target_group), tier) for r in valid)
                      for tier in RARITIES))
    paid_eq = sum(equivalent(summarize_target(r.drops, r.target_group)) for r in paid)
    return dict(claims=len(valid), total_claims=len(records), reward_units=units,
                stamina=stamina, counts=counts, equivalent=equivalent(counts),
                per_unit=equivalent(counts) / units if units else None,
                per_stamina=paid_eq / stamina if stamina else None,
                incomplete_claims=len(records) - len(valid))
