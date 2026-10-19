import pytest

from bcut.evaluation import (
    Item,
    b_runs,
    block_bounds,
    burst_recall,
    burst_recall_stat,
    cluster_bootstrap_ci,
    frame_recall_raised,
    merge,
    recall_candidate,
    recall_raised,
    summarize,
    wilson,
)


def it(label, status, note=None, final_a=False, name="x"):
    return Item(file=name, label=label, status=status, note=note, final_a=final_a)


def test_b_runs_finds_consecutive_runs():
    labels = ["OK", "B", "B", "OK", "B", "OK_EXPR", "B", "B", "B"]
    assert b_runs(labels) == [(1, 2), (4, 4), (6, 8)]


def test_b_runs_empty_and_no_b():
    assert b_runs([]) == []
    assert b_runs(["OK", "OK"]) == []


def test_block_bounds_cover_everything_in_order():
    labels = ["OK"] * 10
    bounds = block_bounds(labels, 4)
    assert bounds[0][0] == 0 and bounds[-1][1] == 10
    assert all(bounds[i][1] == bounds[i + 1][0] for i in range(3))


def test_block_bounds_do_not_cut_a_b_run():
    # 길이 10 중 4~6이 B 묶음. 2블록이면 경계가 5인데, 묶음 안이라 묶음 뒤(7)로 밀려야 한다
    labels = ["OK"] * 4 + ["B"] * 3 + ["OK"] * 3
    bounds = block_bounds(labels, 2)
    assert bounds == [(0, 7), (7, 10)]


def test_summarize_counts():
    items = [
        it("B", "candidate"), it("B", "review", note="small_eye"), it("B", "normal"),
        it("OK_EXPR", "candidate"), it("OK_EXPR", "review"), it("OK", "normal"),
        it("OK", "no_face"),
    ]
    s = summarize(items)
    assert (s["B"], s["B_candidate"], s["B_review"], s["B_missed"]) == (3, 1, 1, 1)
    assert s["B_review_small_eye"] == 1
    assert (s["neg"], s["neg_candidate"], s["neg_review"], s["neg_no_face"]) == (4, 1, 1, 1)
    assert (s["expr"], s["expr_candidate"], s["expr_review"]) == (2, 1, 1)
    assert recall_candidate(s) == pytest.approx(1 / 3)
    assert recall_raised(s) == pytest.approx(2 / 3)


def test_burst_recall_counts_a_burst_once():
    # 묶음 1: 3장 중 1장만 올라와도 묶음은 잡힌 것. 묶음 2: 한 장도 못 잡음
    items = [it("B", "normal"), it("B", "review"), it("B", "normal"), it("OK", "normal"),
             it("B", "normal")]
    s = summarize(items)
    assert (s["bursts"], s["bursts_raised"]) == (2, 1)
    assert burst_recall(s) == pytest.approx(0.5)


def test_final_a_counts():
    items = [it("OK", "candidate", final_a=True), it("OK", "review", final_a=True),
             it("OK", "normal", final_a=True), it("OK", "normal")]
    s = summarize(items)
    assert (s["final_a"], s["final_a_candidate"], s["final_a_review"]) == (3, 1, 1)


def test_merge_adds_integer_fields():
    a = summarize([it("B", "candidate")])
    b = summarize([it("B", "normal"), it("OK", "candidate")])
    m = merge([a, b])
    assert (m["B"], m["B_candidate"], m["neg_candidate"]) == (2, 1, 1)


def test_wilson_interval_contains_the_estimate_and_is_ordered():
    lo, hi = wilson(1, 350)
    assert 0 <= lo < 1 / 350 < hi < 0.05
    assert wilson(0, 100)[0] == 0
    assert wilson(0, 0) == (0.0, 1.0)


def test_wilson_is_wider_for_smaller_samples():
    narrow = wilson(5, 500)
    wide = wilson(1, 100)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_cluster_bootstrap_is_reproducible_and_bounded():
    items = []
    for caught in (True, False, True, True, False):  # 묶음 5개
        items.append(it("B", "review" if caught else "normal"))
        items.append(it("OK", "normal"))
    a = cluster_bootstrap_ci(items, frame_recall_raised, n_boot=500, seed=1)
    b = cluster_bootstrap_ci(items, frame_recall_raised, n_boot=500, seed=1)
    assert a == b
    assert 0 <= a[0] <= 0.6 <= a[1] <= 1


def test_cluster_bootstrap_with_no_b_is_nan():
    lo, hi = cluster_bootstrap_ci([it("OK", "normal")], burst_recall_stat, n_boot=10)
    assert lo != lo and hi != hi  # NaN
