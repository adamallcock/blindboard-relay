"""Regression checks for discrete score ranks, rather than float ties."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import relay_analysis as analysis


def test_equal_correct_key_differences_keep_equal_signed_ranks():
    counts = [0, 13, 17, 19, 2, 6, 10, 25]
    directions = [1, 1, 1, -1, -1, -1, -1, -1]
    a = {i: {"correct": n, "board_n": 26, "board_accuracy": n / 26}
         for i, n in enumerate(counts)}
    b = {i: {"correct": n + d, "board_n": 26, "board_accuracy": (n + d) / 26}
         for i, (n, d) in enumerate(zip(counts, directions))}
    expected = 2 * sum(math.comb(8, k) for k in range(4)) / 2**8
    result = analysis.paired_contrast(a, b)
    assert result["p_wilcoxon"] == expected
    assert result["p_sign"] == expected


def test_paired_ranks_reject_inconsistent_score_counts():
    a = {i: {"correct": 5, "board_n": 26, "board_accuracy": 5 / 26} for i in range(8)}
    b = {i: {"correct": 6, "board_n": 26, "board_accuracy": 5 / 26} for i in range(8)}
    with pytest.raises(ValueError, match="integer correct-key count"):
        analysis.paired_contrast(a, b)


def test_paired_ranks_reject_mixed_board_sizes():
    a = {i: {"correct": 5, "board_n": 26, "board_accuracy": 5 / 26} for i in range(8)}
    b = {i: {"correct": 5, "board_n": 39, "board_accuracy": 5 / 39} for i in range(8)}
    with pytest.raises(ValueError, match="one known board size"):
        analysis.paired_contrast(a, b)


def test_drift_sensitivity_disables_popularity_and_omits_terminal_note():
    first = "A" * 210 + "a" * 10
    second = "a" * 10 + "A" * 210
    cell = {0: {"_batons": [first, second, second, "terminal"],
                "_baton_turns": [(1, first), (2, second), (3, second), (4, "terminal")],
                "guess_turn": 4}}
    cells = {("luna", "freeform", "std", "800"): cell}
    original, _ = analysis.drift(cells)
    sensitivity = analysis.drift_sensitivity(cells)["luna|std|800"]
    assert sensitivity["same_pair_mean_noautojunk"] > original["luna", "std", "800"]["mean_sim"]
    assert sensitivity["n_changed_pairs"] > 0
    assert sensitivity["n_historical_pairs"] == 3
    assert sensitivity["actual_turn_pairs_without_terminal"] == 2


def test_drift_sensitivity_does_not_join_nonadjacent_turns():
    cells = {("luna", "freeform", "std", "100"): {
        0: {"_batons": ["A=Q", "B=Z", "terminal"],
            "_baton_turns": [(1, "A=Q"), (3, "B=Z"), (4, "terminal")], "guess_turn": 4}}}
    row = analysis.drift_sensitivity(cells)["luna|std|100"]
    assert row["n_historical_pairs"] == 2
    assert row["actual_turn_pairs_without_terminal"] == 0
    assert row["n_episodes"] == 0
    assert row["episode_mean_without_terminal"] is None
