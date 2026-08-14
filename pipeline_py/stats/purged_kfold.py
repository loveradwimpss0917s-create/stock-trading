"""Purged K-Fold cross-validation with embargo (López de Prado 2018).

Plain K-fold leaks in financial data. A label at time t depends on prices
through t + label_span, so a training sample just before the test window
already contains the test window's outcome. Purging drops those overlapping
samples; the embargo drops a further slice immediately after the test fold
to break the serial correlation that survives purging.
"""
from __future__ import annotations

from typing import Iterator


def purged_kfold(
    n_samples: int, k: int, label_span: int, embargo_pct: float = 0.01
) -> Iterator[tuple[list[int], list[int]]]:
    """Yields (train_idx, test_idx) per fold, both sorted ascending."""
    if k < 2 or n_samples < k:
        return

    fold_size = n_samples // k
    embargo = int(n_samples * embargo_pct)

    for f in range(k):
        test_start = f * fold_size
        test_end = n_samples if f == k - 1 else test_start + fold_size
        test = list(range(test_start, test_end))

        # Purge anything whose label window reaches into the test fold, and
        # embargo the samples immediately after it.
        purge_lo = test_start - label_span
        purge_hi = test_end + label_span + embargo

        train = [i for i in range(n_samples) if i < purge_lo or i >= purge_hi]
        yield train, test


def overlaps(train: list[int], test: list[int], label_span: int) -> bool:
    """True if any training sample's label window touches the test fold —
    what purging exists to prevent."""
    if not train or not test:
        return False
    test_lo, test_hi = min(test), max(test)
    return any(test_lo <= i + label_span and i <= test_hi for i in train)
