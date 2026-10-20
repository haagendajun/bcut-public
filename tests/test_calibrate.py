import pytest

from bcut.calibrate import (
    CalibrationError,
    Sample,
    fit_eyes,
    read_labels,
    render_config,
    samples_from_results,
)
from bcut.config import load_config
from bcut.scan import PhotoResult
from bcut.score.eyes import EyesThresholds


def mk(pos, neg):
    return ([Sample(s, "B") for s in pos] + [Sample(s, "OK") for s in neg]
            + [Sample(0.40, "OK_EXPR")])


POS = [0.02 * i for i in range(1, 13)]            # 0.02 .. 0.24
NEG = [0.20 + 0.01 * i for i in range(40)]        # 0.20 .. 0.59


def test_candidate_is_just_below_lowest_negative():
    cal = fit_eyes(mk(POS, NEG))
    assert cal.thresholds.candidate_max < 0.20
    assert cal.thresholds.candidate_max == pytest.approx(0.20, abs=1e-6)
    # 학습 정상 중 후보가 되는 것은 0장 (오탐 0)
    assert sum(s <= cal.thresholds.candidate_max for s in NEG) == 0


def test_review_covers_requested_share_of_b_and_not_below_candidate():
    cal = fit_eyes(mk(POS, NEG), review_recall=0.95)
    assert cal.thresholds.review_max >= cal.thresholds.candidate_max
    assert cal.raised_recall >= 0.9
    assert cal.candidate_recall == pytest.approx(sum(s < 0.20 - 1e-6 for s in POS) / len(POS))
    low = fit_eyes(mk([0.01 * i for i in range(1, 13)], NEG))  # B가 모두 정상보다 낮다
    assert low.thresholds.review_max == low.thresholds.candidate_max
    assert low.candidate_recall == 1.0


def test_deterministic_and_version_depends_on_input():
    a, b = fit_eyes(mk(POS, NEG)), fit_eyes(mk(POS, NEG))
    assert a == b and render_config(a) == render_config(b)
    c = fit_eyes(mk(POS[:-1], NEG))
    assert a.version != c.version


def test_not_enough_labels():
    with pytest.raises(CalibrationError, match="B 라벨"):
        fit_eyes(mk(POS[:3], NEG))
    with pytest.raises(CalibrationError, match="정상 라벨"):
        fit_eyes(mk(POS, NEG[:5]))
    with pytest.raises(CalibrationError):
        fit_eyes(mk(POS, NEG), review_recall=0)


def test_rendered_config_loads_back(tmp_path):
    cal = fit_eyes(mk(POS, NEG))
    path = tmp_path / "bcut-config.toml"
    path.write_text(render_config(cal), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.eyes.candidate_max == pytest.approx(cal.thresholds.candidate_max, abs=1e-6)
    assert cfg.eyes.review_max == pytest.approx(cal.thresholds.review_max, abs=1e-6)
    assert cfg.config_version == cal.version
    assert cfg.sharpness == load_config(None).sharpness  # 나머지는 기본값


def test_read_labels_skips_unsure_and_blank(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("file,label,reason\na,B,eyes_closed\nb,OK,\nc,UNSURE,\nd,,\ne,OK_EXPR,\n",
                 encoding="utf-8-sig")
    assert read_labels(p) == {"a": "B", "b": "OK", "e": "OK_EXPR"}
    bad = tmp_path / "bad.csv"
    bad.write_text("name,tag\na,B\n", encoding="utf-8")
    with pytest.raises(CalibrationError):
        read_labels(bad)


def test_samples_skip_untrusted_scores():
    t = EyesThresholds()

    def r(name, score, frac=0.01, note=None):
        return PhotoResult(name, "normal", score, note, 1, 1, frac, None)

    results = [r("a", 0.3), r("b", 0.1, frac=t.min_eye_width_frac / 2), r("c", None),
               r("d", 0.2, note="read_error"), r("e", 0.25), r("zz", 0.5)]
    labels = {"a": "OK", "b": "B", "c": "B", "d": "B", "e": "B"}
    samples, skipped = samples_from_results(results, labels, t.min_eye_width_frac)
    assert [(s.score, s.label) for s in samples] == [(0.3, "OK"), (0.25, "B")]
    assert skipped == 3
