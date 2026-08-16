from unittest.mock import MagicMock

from pipeline_py.screening.evaluate import Bar
from pipeline_py.setups.advance import compute_transitions, run

AS_OF = "2026-05-22"


def plan(**kw):
    base = {
        "id": 1, "code": "72030", "state": "armed",
        "trigger_price": 4250.0,
        "invalidation": {"type": "close_below", "level": 4080.0},
        "expires_on": "2026-05-29",
    }
    base.update(kw)
    return base


def bar(d, close, open_=None):
    o = open_ if open_ is not None else close
    return Bar(d, o, close + 1, close - 1, close)


class TestArmedTransitions:
    def test_close_at_or_above_trigger_fires_triggered(self):
        bars = {"72030": [bar("2026-05-21", 4200.0), bar(AS_OF, 4250.0)]}
        out = compute_transitions([plan()], bars, AS_OF)
        assert out == [
            {"id": 1, "patch": {"state": "triggered", "triggered_on": AS_OF, "triggered_price": 4250.0}}
        ]

    def test_close_just_below_trigger_does_not_fire(self):
        bars = {"72030": [bar(AS_OF, 4249.99)]}
        assert compute_transitions([plan()], bars, AS_OF) == []

    def test_close_at_or_below_invalidation_fires_invalidated(self):
        bars = {"72030": [bar("2026-05-21", 4100.0), bar(AS_OF, 4080.0)]}
        out = compute_transitions([plan()], bars, AS_OF)
        assert out == [{"id": 1, "patch": {"state": "invalidated"}}]

    def test_neither_trigger_nor_invalidation_but_expired_fires_expired(self):
        bars = {"72030": [bar(AS_OF, 4150.0)]}  # between the two levels
        out = compute_transitions(
            [plan(expires_on="2026-05-22")], bars, AS_OF
        )
        assert out == [{"id": 1, "patch": {"state": "expired"}}]

    def test_before_expiry_with_no_trigger_no_change(self):
        bars = {"72030": [bar(AS_OF, 4150.0)]}
        assert compute_transitions([plan(expires_on="2026-05-29")], bars, AS_OF) == []

    def test_a_plan_missing_a_bar_for_as_of_is_left_untouched(self):
        bars = {"72030": [bar("2026-05-20", 4150.0)]}  # stale, not as_of
        assert compute_transitions([plan()], bars, AS_OF) == []

    def test_a_code_with_no_bars_at_all_is_left_untouched(self):
        assert compute_transitions([plan()], {}, AS_OF) == []


class TestDraftTransitions:
    def test_draft_expires_on_its_own_schedule_without_ever_triggering(self):
        bars = {"72030": [bar(AS_OF, 4300.0)]}  # would have triggered if armed
        out = compute_transitions(
            [plan(state="draft", expires_on="2026-05-22")], bars, AS_OF
        )
        assert out == [{"id": 1, "patch": {"state": "expired"}}]

    def test_draft_before_its_expiry_is_untouched_regardless_of_price(self):
        bars = {"72030": [bar(AS_OF, 4300.0)]}
        out = compute_transitions(
            [plan(state="draft", expires_on="2026-05-29")], bars, AS_OF
        )
        assert out == []


class TestPriorityAndInvariants:
    def test_invalidation_and_trigger_cannot_both_fire_the_same_close(self):
        # resolve_plan_levels guarantees invalidation < trigger_price, so a
        # close that clears the trigger can never also be at/below
        # invalidation. This just documents that no branch double-fires.
        p = plan(trigger_price=4250.0, invalidation={"type": "close_below", "level": 4080.0})
        bars = {"72030": [bar(AS_OF, 4250.0)]}
        out = compute_transitions([p], bars, AS_OF)
        assert len(out) == 1
        assert out[0]["patch"]["state"] == "triggered"

    def test_multiple_plans_are_evaluated_independently(self):
        plans = [
            plan(id=1, code="A", trigger_price=100.0, invalidation={"type": "close_below", "level": 80.0}),
            plan(id=2, code="B", trigger_price=100.0, invalidation={"type": "close_below", "level": 80.0}),
        ]
        bars = {"A": [bar(AS_OF, 100.0)], "B": [bar(AS_OF, 80.0)]}
        out = compute_transitions(plans, bars, AS_OF)
        assert {t["id"]: t["patch"]["state"] for t in out} == {1: "triggered", 2: "invalidated"}


class TestRun:
    def test_persists_via_patch_not_upsert(self, monkeypatch):
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.select.side_effect = lambda table, params: [{"date": AS_OF}]

        def select_all(table, params):
            if table == "trade_plans":
                return [plan()]
            if table == "daily_quotes":
                return [{"code": "72030", "date": AS_OF, "open": 4249, "high": 4251, "low": 4248, "close": 4250.0}]
            raise AssertionError(table)

        db.select_all.side_effect = select_all
        monkeypatch.setattr("pipeline_py.setups.advance.SupabaseUpsertClient", lambda: db)

        transitions = run(persist=True)
        assert len(transitions) == 1
        db.update.assert_called_once_with(
            "trade_plans", {"id": "eq.1"}, {"state": "triggered", "triggered_on": AS_OF, "triggered_price": 4250.0}
        )

    def test_no_advancing_plans_is_a_normal_empty_result(self, monkeypatch):
        db = MagicMock()
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)
        db.select.side_effect = lambda table, params: [{"date": AS_OF}]
        db.select_all.side_effect = lambda table, params: [] if table == "trade_plans" else (_ for _ in ()).throw(AssertionError(table))
        monkeypatch.setattr("pipeline_py.setups.advance.SupabaseUpsertClient", lambda: db)

        assert run(persist=True) == []
        db.update.assert_not_called()
