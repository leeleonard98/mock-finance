"""F6: subscription detection — pure-function algorithm.

Heuristic: group transactions by *normalised* description; if a group has
>=3 occurrences within the lookback window AND the amount is stable
(stdev / mean < tolerance), it's a subscription.

Lives in app/ (not app/tools/) so the F4 tool wrapper and any future
analytics surface can both depend on it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import mean, pstdev

from app.models import Transaction


@dataclass(frozen=True)
class DetectedSubscription:
    merchant: str
    monthly_amount: Decimal
    occurrences: int
    last_seen: date
    transaction_ids: tuple[int, ...]


_NORMALISE_RE = re.compile(r"[^a-z]+")


def _normalise(description: str) -> str:
    """Strip digits, punctuation; lowercase; collapse whitespace.

    'Netflix.com 12345' and 'NETFLIX.COM 99999' both → 'netflix com'.
    """
    s = description.lower()
    s = _NORMALISE_RE.sub(" ", s)
    return " ".join(s.split())


def detect(
    transactions: list[Transaction],
    *,
    min_occurrences: int = 3,
    amount_tolerance: float = 0.10,
) -> list[DetectedSubscription]:
    """Return the subscriptions detected in `transactions`."""
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        key = _normalise(tx.description)
        if not key:
            continue
        groups[key].append(tx)

    out: list[DetectedSubscription] = []
    for key, txs in groups.items():
        if len(txs) < min_occurrences:
            continue
        amounts = [float(t.amount) for t in txs]
        m = mean(amounts)
        if m == 0:
            continue
        sd = pstdev(amounts) if len(amounts) > 1 else 0.0
        if sd / m > amount_tolerance:
            continue
        last_seen = max(t.posted_at for t in txs)
        out.append(
            DetectedSubscription(
                merchant=key,
                monthly_amount=Decimal(str(round(m, 2))),
                occurrences=len(txs),
                last_seen=last_seen,
                transaction_ids=tuple(t.id for t in txs),
            )
        )
    return sorted(out, key=lambda s: s.merchant)
