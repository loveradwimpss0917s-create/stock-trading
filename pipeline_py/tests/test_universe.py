import pytest

from pipeline_py.ingest.universe import (
    is_operating_company,
    select_universe,
    sort_by_scale,
)

# Shapes taken from the live /equities/master response (2026-08-12).
TOYOTA = {"Code": "72030", "CoName": "トヨタ自動車", "S33": "3700", "ScaleCat": "TOPIX Core30"}
KYOKUYO = {"Code": "13010", "CoName": "極洋", "S33": "0050", "ScaleCat": "TOPIX Small 1"}
TOYOTA_BOSHOKU = {"Code": "31160", "CoName": "トヨタ紡織", "S33": "3700", "ScaleCat": "TOPIX Mid400"}
# ETFs sit in sector33 9999 with no scale category.
NEXT_FUNDS_ETF = {"Code": "13060", "CoName": "NEXT FUNDS TOPIX", "S33": "9999", "ScaleCat": "-"}
GROWTH_UNCLASSIFIED = {"Code": "130A0", "CoName": "Veritas In Silico", "S33": "3250", "ScaleCat": "-"}


def test_etf_is_not_an_operating_company():
    assert is_operating_company(NEXT_FUNDS_ETF) is False


def test_real_companies_are_operating_companies():
    assert is_operating_company(TOYOTA) is True
    assert is_operating_company(KYOKUYO) is True


def test_unscaled_listing_is_excluded():
    # Real sector but no TOPIX scale bucket — outside the index universe,
    # so excluded rather than silently ranked last.
    assert is_operating_company(GROWTH_UNCLASSIFIED) is False


def test_operating_universe_drops_etfs():
    rows = [TOYOTA, NEXT_FUNDS_ETF, KYOKUYO, GROWTH_UNCLASSIFIED]
    assert select_universe(rows, "operating") == [TOYOTA, KYOKUYO]


def test_core30_universe_selects_only_core30():
    rows = [TOYOTA, KYOKUYO, TOYOTA_BOSHOKU, NEXT_FUNDS_ETF]
    assert select_universe(rows, "core30") == [TOYOTA]


def test_topix500_includes_core30_large70_mid400_but_not_small():
    rows = [TOYOTA, KYOKUYO, TOYOTA_BOSHOKU]
    assert select_universe(rows, "topix500") == [TOYOTA, TOYOTA_BOSHOKU]


def test_all_universe_keeps_etfs():
    rows = [TOYOTA, NEXT_FUNDS_ETF]
    assert select_universe(rows, "all") == rows


def test_unknown_universe_raises():
    with pytest.raises(ValueError, match="unknown universe"):
        select_universe([TOYOTA], "nikkei225")


def test_sort_by_scale_puts_largest_caps_first():
    rows = [KYOKUYO, TOYOTA_BOSHOKU, TOYOTA]
    assert [r["Code"] for r in sort_by_scale(rows)] == ["72030", "31160", "13010"]
