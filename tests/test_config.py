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
