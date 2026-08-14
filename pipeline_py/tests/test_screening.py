from pipeline_py.screening.scoring import (
    MIN_ATR_PCT_DAY,
    MIN_TURNOVER,
    STOP_ATR_MULT,
    TARGET_ATR_MULT,
    score_theme,
)

BREAKOUT = {
    "key": "breakout",
    "kind": "factor",
    "definition": {"weights": {"dist_52w_high": 1.0, "ret_20d": 0.8}},
}
SEMI = {"key": "semiconductor", "kind": "sector", "definition": {"sector33": ["3650"]}}


def row(**kw):
    base = {
        "close": 1000.0,
        "atr_14": 30.0,
        "turnover_value": 10_000_000_000,
        "sector33": "3650",
        "ret_1d": 0.0,
        "ret_5d": 0.0,
        "ret_20d": 0.0,
        "rsi_14": 50.0,
        "adx_14": 20.0,
        "vol_20d": 0.25,
        "dist_52w_high": -0.1,
        "ma_25": 990.0,
        "ma_75": 950.0,
    }
    base.update(kw)
    return base


def universe(**overrides):
    codes = {f"A{i}": row() for i in range(5)}
    codes.update(overrides)
    return codes


class TestRankingDirection:
    def test_breakout_prefers_names_nearest_their_high(self):
        rows = universe(
            NEAR=row(dist_52w_high=-0.01, ret_20d=0.15),
            FAR=row(dist_52w_high=-0.40, ret_20d=-0.15),
        )
        out = score_theme(rows, BREAKOUT, "swing", top_n=10)
        codes = [c.code for c in out]
        assert codes.index("NEAR") < codes.index("FAR")

    def test_day_reversal_prefers_the_biggest_one_day_loser(self):
        theme = {
            "key": "day_reversal",
            "kind": "factor",
            "definition": {"weights": {"ret_1d_neg": 1.0}},
        }
        rows = universe(
            DROPPED=row(ret_1d=-0.08),
            ROSE=row(ret_1d=0.08),
        )
        out = score_theme(rows, theme, "day", top_n=10)
        assert out[0].code == "DROPPED"

    def test_oversold_component_prefers_low_rsi(self):
        theme = {
            "key": "pullback",
            "kind": "factor",
            "definition": {"weights": {"rsi_oversold": 1.0}},
        }
        rows = universe(LOW=row(rsi_14=22.0), HIGH=row(rsi_14=78.0))
        out = score_theme(rows, theme, "swing", top_n=10)
        codes = [c.code for c in out]
        assert codes.index("LOW") < codes.index("HIGH")


class TestSectorThemes:
    def test_sector_theme_only_returns_its_own_sector(self):
        rows = {
            "SEMI1": row(sector33="3650"),
            "SEMI2": row(sector33="3650", ret_20d=0.2),
            "BANK": row(sector33="7050", ret_20d=0.5),
        }
        out = score_theme(rows, SEMI, "swing", top_n=10)
        assert {c.code for c in out} == {"SEMI1", "SEMI2"}

    def test_sector_theme_with_no_members_returns_nothing(self):
        rows = {"BANK": row(sector33="7050")}
        assert score_theme(rows, SEMI, "swing", top_n=10) == []


class TestRiskLevels:
    def test_stop_and_target_are_atr_multiples_of_the_reference_close(self):
        rows = universe(X=row(close=2000.0, atr_14=50.0, dist_52w_high=0.0))
        out = score_theme(rows, BREAKOUT, "swing", top_n=10)
        x = next(c for c in out if c.code == "X")
        assert abs(x.stop_price - (2000 - STOP_ATR_MULT["swing"] * 50)) < 1e-6
        assert abs(x.target_price - (2000 + TARGET_ATR_MULT["swing"] * 50)) < 1e-6

    def test_swing_levels_are_wider_than_day_levels(self):
        rows = universe(X=row(dist_52w_high=0.0))
        day = next(c for c in score_theme(rows, BREAKOUT, "day", top_n=10) if c.code == "X")
        swing = next(c for c in score_theme(rows, BREAKOUT, "swing", top_n=10) if c.code == "X")
        assert swing.stop_price < day.stop_price
        assert swing.target_price > day.target_price

    def test_reward_to_risk_is_reported_and_above_one(self):
        rows = universe(X=row(dist_52w_high=0.0))
        out = score_theme(rows, BREAKOUT, "swing", top_n=10)
        assert all(c.rr_ratio > 1.0 for c in out)

    def test_a_volatile_name_gets_a_wider_stop_than_a_quiet_one(self):
        rows = universe(
            CALM=row(atr_14=10.0, dist_52w_high=0.0),
            WILD=row(atr_14=80.0, dist_52w_high=0.0),
        )
        out = {c.code: c for c in score_theme(rows, BREAKOUT, "swing", top_n=10)}
        calm_risk = out["CALM"].entry_ref - out["CALM"].stop_price
        wild_risk = out["WILD"].entry_ref - out["WILD"].stop_price
        assert wild_risk > calm_risk


class TestFilters:
    def test_illiquid_names_are_excluded(self):
        rows = universe(THIN=row(turnover_value=MIN_TURNOVER - 1, dist_52w_high=0.0))
        assert "THIN" not in {c.code for c in score_theme(rows, BREAKOUT, "swing", top_n=10)}

    def test_day_horizon_excludes_names_without_enough_range(self):
        # ATR below the day-trade floor: cannot pay for its own spread.
        quiet = row(close=1000.0, atr_14=1000.0 * (MIN_ATR_PCT_DAY / 2), dist_52w_high=0.0)
        rows = universe(QUIET=quiet)
        day_codes = {c.code for c in score_theme(rows, BREAKOUT, "day", top_n=10)}
        swing_codes = {c.code for c in score_theme(rows, BREAKOUT, "swing", top_n=10)}
        assert "QUIET" not in day_codes
        assert "QUIET" in swing_codes  # the range floor is a day-trade rule only

    def test_missing_atr_is_skipped_rather_than_defaulted(self):
        rows = universe(NOATR=row(atr_14=None))
        assert "NOATR" not in {c.code for c in score_theme(rows, BREAKOUT, "swing", top_n=10)}

    def test_top_n_is_respected(self):
        rows = {f"C{i}": row(ret_20d=i / 100) for i in range(20)}
        assert len(score_theme(rows, BREAKOUT, "swing", top_n=3)) == 3


class TestRationale:
    def test_every_candidate_explains_which_components_drove_it(self):
        rows = universe(X=row(dist_52w_high=0.0, ret_20d=0.2))
        out = score_theme(rows, BREAKOUT, "swing", top_n=10)
        for c in out:
            assert c.rationale["components"]
            assert set(c.rationale["components"]) <= {"dist_52w_high", "ret_20d"}
            assert "atr_pct" in c.rationale

    def test_score_equals_the_sum_of_its_reported_components(self):
        rows = universe(X=row(dist_52w_high=0.0, ret_20d=0.2))
        for c in score_theme(rows, BREAKOUT, "swing", top_n=10):
            assert abs(c.score - sum(c.rationale["components"].values())) < 1e-3


class TestDegenerateInput:
    def test_empty_universe_returns_nothing(self):
        assert score_theme({}, BREAKOUT, "swing") == []

    def test_theme_without_weights_returns_nothing(self):
        theme = {"key": "x", "kind": "factor", "definition": {}}
        assert score_theme(universe(), theme, "swing") == []

    def test_identical_rows_do_not_crash_on_zero_variance(self):
        rows = {f"S{i}": row() for i in range(4)}
        out = score_theme(rows, BREAKOUT, "swing", top_n=10)
        assert len(out) == 4
        assert all(abs(c.score) < 1e-9 for c in out)


class TestSnapshotExcludesFunds:
    """ETFs reach the feature store (they have bars like anything else), and
    nothing downstream would keep them out of a factor theme: a TOPIX ETF
    clears the turnover filter by a wide margin and moves like a low-vol
    stock. The exclusion has to happen when the snapshot is built."""

    @staticmethod
    def _snapshot(sec_rows):
        from unittest.mock import MagicMock

        from pipeline_py.screening.run import load_snapshot

        db = MagicMock()
        codes = [s["code"] for s in sec_rows]
        db.select_all.side_effect = lambda table, _q: {
            "features": [
                dict(row(), code=c, atr_14=30.0) | {"ma_25": 990.0, "ma_75": 950.0}
                for c in codes
            ],
            "daily_quotes": [
                {"code": c, "close": 1000.0, "turnover_value": 50_000_000_000}
                for c in codes
            ],
            "securities_with_data": sec_rows,
        }[table]
        return load_snapshot(db, "2026-05-22")

    def test_etf_is_dropped_from_the_snapshot(self):
        snap = self._snapshot(
            [
                {
                    "code": "13060",
                    "name_ja": "ＴＯＰＩＸ連動型上場投信",
                    "sector33": "9999",
                    "scale_category": "-",
                },
                {
                    "code": "72030",
                    "name_ja": "トヨタ自動車",
                    "sector33": "3700",
                    "scale_category": "TOPIX Core30",
                },
            ]
        )
        assert set(snap) == {"72030"}

    def test_an_unclassified_listing_is_dropped_even_with_a_real_sector(self):
        # Sector alone is not enough: a fund can carry a plausible-looking
        # sector code, so the scale category has to agree it is a company.
        snap = self._snapshot(
            [
                {
                    "code": "99990",
                    "name_ja": "何らかのファンド",
                    "sector33": "3650",
                    "scale_category": "-",
                }
            ]
        )
        assert snap == {}


class TestSectorThemeCoverage:
    """0014 exists because the 0012 themes were derived from the sector33
    codes present when only 41 codes had bars. This pins the union so a
    future universe change surfaces as a failing test rather than as
    silently unreachable stocks."""

    SECTOR33_IN_TOPIX500 = {
        "0050", "1050", "2050", "3050", "3100", "3150", "3200", "3250",
        "3300", "3350", "3400", "3450", "3500", "3550", "3600", "3650",
        "3700", "3750", "3800", "4050", "5050", "5100", "5150", "5200",
        "5250", "6050", "6100", "7050", "7100", "7150", "7200", "8050",
        "9050",
    }

    @staticmethod
    def _seeded_sectors():
        import re
        from pathlib import Path

        covered: set[str] = set()
        migrations = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
        for path in sorted(migrations.glob("00*_*themes*.sql")) + sorted(
            migrations.glob("00*_sector_theme*.sql")
        ):
            for blob in re.findall(r'"sector33":\s*\[([^\]]*)\]', path.read_text()):
                covered |= set(re.findall(r'"(\d+)"', blob))
        return covered

    def test_every_operating_sector_belongs_to_some_theme(self):
        missing = self.SECTOR33_IN_TOPIX500 - self._seeded_sectors()
        assert not missing, f"sector33 codes with no theme: {sorted(missing)}"

    def test_funds_are_not_given_a_theme(self):
        assert "9999" not in self._seeded_sectors()
