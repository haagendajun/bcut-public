import pytest

from bcut.config import REASONS, Config, ConfigError, load_config


def test_default_tiers_follow_evidence_based_rule():
    cfg = Config()
    assert cfg.tier_for("eyes_closed") == "candidate"
    for reason in ("blur", "out_of_focus", "exposure"):
        assert cfg.tier_for(reason) == "review"


def test_every_reason_has_a_tier():
    cfg = Config()
    assert set(cfg.reason_tiers) == set(REASONS)


def test_load_none_gives_defaults():
    assert load_config(None) == Config()


def test_promote_reason_via_config_file(tmp_path):
    path = tmp_path / "bcut-config.toml"
    path.write_text(
        'config_version = "v2"\n[reason_tiers]\nexposure = "candidate"\n', encoding="utf-8"
    )
    cfg = load_config(path)
    assert cfg.tier_for("exposure") == "candidate"
    assert cfg.tier_for("blur") == "review"
    assert cfg.config_version == "v2"


def test_invalid_tier_is_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[reason_tiers]\nblur = "delete"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_unknown_reason_is_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[reason_tiers]\nsmile = "review"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_thresholds_default_and_override(tmp_path):
    assert Config().eyes.candidate_max == 0.134 and Config().sharpness.min_face_px == 420
    path = tmp_path / "c.toml"
    path.write_text("[eyes]\ncandidate_max = 0.12\n[sharpness]\nmin_face_px = 500\n"
                    "[exposure]\ndark_p99 = 100\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.eyes.candidate_max == 0.12 and cfg.eyes.review_max == 0.162  # 안 적은 값은 기본값
    assert cfg.sharpness.min_face_px == 500 and cfg.exposure.dark_p99 == 100


@pytest.mark.parametrize("body", [
    "[eyes]\ncandidate_maxx = 0.1\n",  # 오타
    "[eyes]\ncandidate_max = 0.5\nreview_max = 0.1\n",  # 값 관계 오류
    "[sharpness]\nbest_blur_min = 2\n",
    "[exposure]\nface_hi_frac = 0\n",
    "eyes = 3\n",
])
def test_bad_thresholds_rejected(tmp_path, body):
    path = tmp_path / "c.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
