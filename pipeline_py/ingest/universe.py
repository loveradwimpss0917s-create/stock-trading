"""Which securities to backfill.

/equities/master returns all ~4,446 listed codes, but roughly a third are
ETFs/ETNs/REITs rather than operating companies. A quant research universe
built from those is meaningless — momentum/value/quality factors don't apply
to an index tracker — so the default universe excludes them.

Classification is by the live-confirmed master fields: operating companies
carry a real Sector33 code and a TOPIX scale category, while funds sit in
S33 '9999' (その他) with ScaleCat '-'.
"""
from __future__ import annotations

from typing import Any, Iterable

# TOPIX scale buckets, largest first. Operating companies carry one of these;
# funds and unclassified listings carry '-'.
SCALE_ORDER = [
    "TOPIX Core30",
    "TOPIX Large70",
    "TOPIX Mid400",
    "TOPIX Small 1",
    "TOPIX Small 2",
]

SECTOR33_OTHER = "9999"

UNIVERSES = ("core30", "large100", "topix500", "operating", "all")


def _scale(raw: dict[str, Any]) -> str:
    return (raw.get("ScaleCat") or raw.get("scale_category") or "").strip()


def _sector33(raw: dict[str, Any]) -> str:
    return (raw.get("S33") or raw.get("sector33") or "").strip()


def is_operating_company(raw: dict[str, Any]) -> bool:
    """True for actual companies, False for ETFs/ETNs and other funds."""
    return _sector33(raw) != SECTOR33_OTHER and _scale(raw) in SCALE_ORDER


def select_universe(securities: Iterable[dict[str, Any]], universe: str) -> list[dict[str, Any]]:
    rows = list(securities)
    if universe == "all":
        return rows

    companies = [s for s in rows if is_operating_company(s)]
    if universe == "operating":
        return companies
    if universe == "core30":
        wanted = {"TOPIX Core30"}
    elif universe == "large100":
        wanted = {"TOPIX Core30", "TOPIX Large70"}
    elif universe == "topix500":
        wanted = {"TOPIX Core30", "TOPIX Large70", "TOPIX Mid400"}
    else:
        raise ValueError(f"unknown universe: {universe!r} (expected one of {UNIVERSES})")

    return [s for s in companies if _scale(s) in wanted]


def sort_by_scale(securities: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Largest caps first, so a run cut short by its time budget has still
    covered the most useful names."""
    rank = {name: i for i, name in enumerate(SCALE_ORDER)}
    return sorted(
        securities,
        key=lambda s: (rank.get(_scale(s), len(SCALE_ORDER)), s.get("Code") or s.get("code") or ""),
    )
