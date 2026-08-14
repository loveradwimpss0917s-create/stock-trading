import math
import random

import pytest

from pipeline_py.stats.dsr import (
    deflated_sharpe,
    expected_max_sharpe,
    norm_cdf,
    norm_ppf,
    probabilistic_sharpe,
    sharpe_variance_across_trials,
)
from pipeline_py.stats.pbo import pbo_cscv, split_blocks
from pipeline_py.stats.purged_kfold import overlaps, purged_kfold


class TestNormal:
    def test_cdf_at_known_points(self):
        assert abs(norm_cdf(0.0) - 0.5) < 1e-12
        assert abs(norm_cdf(1.96) - 0.975) < 1e-3
        assert abs(norm_cdf(-1.96) - 0.025) < 1e-3

    def test_ppf_inverts_cdf(self):
        for p in (0.01, 0.25, 0.5, 0.75, 0.99):
            assert abs(norm_cdf(norm_ppf(p)) - p) < 1e-9

    def test_ppf_does_not_blow_up_at_the_boundaries(self):
        assert math.isfinite(norm_ppf(0.0))
        assert math.isfinite(norm_ppf(1.0))


class TestExpectedMaxSharpe:
    def test_grows_with_the_number_of_trials(self):
        # The whole premise of DSR: more trials, higher bar.
        v = 0.01
        assert expected_max_sharpe(v, 100) > expected_max_sharpe(v, 10)
        assert expected_max_sharpe(v, 1000) > expected_max_sharpe(v, 100)

    def test_zero_variance_across_trials_gives_a_zero_benchmark(self):
        assert expected_max_sharpe(0.0, 100) == 0.0

    def test_reproduces_the_papers_order_of_magnitude_for_1000_trials(self):
        # Bailey & López de Prado: with 1,000 independent backtests and a true
        # SR of zero, the expected maximum lands around 3.26 — for SRs with
        # unit variance at the trial level.
        assert 3.0 < expected_max_sharpe(1.0, 1000) < 3.5


class TestProbabilisticSharpe:
    def test_observed_equal_to_benchmark_is_a_coin_flip(self):
        assert abs(probabilistic_sharpe(0.1, 0.1, 500, 0.0, 3.0) - 0.5) < 1e-12

    def test_higher_observed_sharpe_raises_confidence(self):
        low = probabilistic_sharpe(0.05, 0.0, 500, 0.0, 3.0)
        high = probabilistic_sharpe(0.15, 0.0, 500, 0.0, 3.0)
        assert high > low > 0.5

    def test_longer_sample_raises_confidence_for_the_same_sharpe(self):
        short = probabilistic_sharpe(0.1, 0.0, 100, 0.0, 3.0)
        long = probabilistic_sharpe(0.1, 0.0, 1000, 0.0, 3.0)
        assert long > short

    def test_negative_skew_and_fat_tails_reduce_confidence(self):
        # Fat left tails make the same Sharpe less trustworthy.
        clean = probabilistic_sharpe(0.1, 0.0, 500, 0.0, 3.0)
        ugly = probabilistic_sharpe(0.1, 0.0, 500, -1.5, 12.0)
        assert ugly < clean

    def test_too_short_a_sample_declines_to_claim_significance(self):
        assert probabilistic_sharpe(5.0, 0.0, 1, 0.0, 3.0) == 0.5

    def test_degenerate_denominator_declines_rather_than_erroring(self):
        # Extreme skew can drive the variance term non-positive.
        assert probabilistic_sharpe(2.0, 0.0, 500, 5.0, 3.0) == 0.5


class TestDeflatedSharpe:
    def test_sharpe_matching_the_selection_benchmark_gives_dsr_of_half(self):
        var_sr = 0.004
        n_trials = 50
        sr0 = expected_max_sharpe(var_sr, n_trials)
        dsr, reported = deflated_sharpe(sr0, var_sr, n_trials, 500, 0.0, 3.0)
        assert abs(reported - sr0) < 1e-12
        assert abs(dsr - 0.5) < 1e-9

    def test_more_trials_deflate_the_same_observed_sharpe(self):
        few, _ = deflated_sharpe(0.12, 0.004, 5, 500, 0.0, 3.0)
        many, _ = deflated_sharpe(0.12, 0.004, 500, 500, 0.0, 3.0)
        assert many < few

    def test_a_losing_strategy_cannot_pass_the_gate(self):
        dsr, _ = deflated_sharpe(-0.05, 0.004, 4, 355, 0.0, 3.0)
        assert dsr < 0.95

    def test_variance_across_trials_needs_more_than_one_trial(self):
        assert sharpe_variance_across_trials([0.1]) == 0.0
        assert sharpe_variance_across_trials([0.1, 0.2, 0.3]) > 0


class TestSplitBlocks:
    def test_blocks_are_contiguous_and_cover_every_row(self):
        blocks = split_blocks(100, 10)
        assert len(blocks) == 10
        assert sorted(i for b in blocks for i in b) == list(range(100))
        for b in blocks:
            assert b == list(range(b[0], b[-1] + 1))

    def test_remainder_rows_are_not_dropped(self):
        blocks = split_blocks(103, 10)
        assert sorted(i for b in blocks for i in b) == list(range(103))

    def test_too_few_rows_yields_nothing(self):
        assert split_blocks(5, 10) == []


class TestPboCscv:
    def test_pure_noise_strategies_produce_pbo_near_one_half(self):
        """The blueprint's stated completion condition. If every strategy is
        noise, the in-sample winner is arbitrary and lands below the OOS
        median about half the time."""
        rng = random.Random(42)
        returns = [[rng.gauss(0, 0.01) for _ in range(8)] for _ in range(320)]
        result = pbo_cscv(returns, n_blocks=8)
        assert 0.3 < result["pbo"] < 0.7

    def test_a_genuinely_dominant_strategy_produces_low_pbo(self):
        """Column 0 has a real edge in every period, so the IS winner is also
        the OOS winner and lambda stays positive."""
        rng = random.Random(7)
        returns = []
        for _ in range(320):
            row = [rng.gauss(0.004, 0.01)]  # persistent positive drift
            row += [rng.gauss(0, 0.01) for _ in range(5)]
            returns.append(row)
        result = pbo_cscv(returns, n_blocks=8)
        assert result["pbo"] < 0.1

    def test_single_strategy_cannot_be_evaluated(self):
        returns = [[0.01] for _ in range(100)]
        result = pbo_cscv(returns, n_blocks=8)
        assert result["pbo"] is None
        assert "at least 2" in result["reason"]

    def test_odd_block_count_is_rejected(self):
        returns = [[0.01, 0.02] for _ in range(100)]
        with pytest.raises(ValueError, match="even"):
            pbo_cscv(returns, n_blocks=7)

    def test_too_short_a_series_reports_a_reason_instead_of_crashing(self):
        returns = [[0.01, 0.02] for _ in range(4)]
        result = pbo_cscv(returns, n_blocks=16)
        assert result["pbo"] is None
        assert result["reason"]

    def test_lambda_count_matches_the_combination_count(self):
        rng = random.Random(1)
        returns = [[rng.gauss(0, 0.01) for _ in range(3)] for _ in range(160)]
        result = pbo_cscv(returns, n_blocks=8)
        # C(8,4) = 70
        assert result["n_combinations"] == 70
        assert len(result["lambdas"]) == 70


class TestPurgedKFold:
    def test_every_sample_appears_in_exactly_one_test_fold(self):
        folds = list(purged_kfold(100, 5, label_span=0, embargo_pct=0.0))
        test_union = sorted(i for _, test in folds for i in test)
        assert test_union == list(range(100))

    def test_train_and_test_never_intersect(self):
        for train, test in purged_kfold(100, 5, label_span=3, embargo_pct=0.01):
            assert not set(train) & set(test)

    def test_purging_removes_samples_whose_labels_reach_the_test_fold(self):
        label_span = 5
        for train, test in purged_kfold(200, 4, label_span, embargo_pct=0.0):
            assert not overlaps(train, test, label_span)

    def test_a_longer_label_span_removes_more_training_data(self):
        short = sum(len(t) for t, _ in purged_kfold(200, 4, 1, 0.0))
        long = sum(len(t) for t, _ in purged_kfold(200, 4, 20, 0.0))
        assert long < short

    def test_embargo_removes_additional_samples_after_the_test_fold(self):
        without = sum(len(t) for t, _ in purged_kfold(200, 4, 2, 0.0))
        with_embargo = sum(len(t) for t, _ in purged_kfold(200, 4, 2, 0.10))
        assert with_embargo < without

    def test_degenerate_parameters_yield_no_folds(self):
        assert list(purged_kfold(10, 1, 0)) == []
        assert list(purged_kfold(3, 5, 0)) == []
