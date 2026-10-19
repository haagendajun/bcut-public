"""설정: 사유, 운영 등급, 전용 키워드 이름.

운영 등급은 devplan 1-F의 "증거 기반 등급"을 따른다.
  candidate  B컷 후보 (확인 후 일괄 제외로 이어지는 앨범)
  review     사람이 확인 (사람이 직접 판단하는 앨범)
증거가 없는 사유는 review 전용으로 시작하고, 설정 파일에서 등급만 바꿔 승급한다.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REASONS = ("eyes_closed", "blur", "out_of_focus", "exposure")
TIERS = ("candidate", "review")

# 눈 감김만 실제 결함 48장으로 검증됐다. 나머지는 실제 결함 0장이라 review 전용.
DEFAULT_REASON_TIERS = {
    "eyes_closed": "candidate",
    "blur": "review",
    "out_of_focus": "review",
    "exposure": "review",
}

# 전용 키워드 접두어 (IA 가정 A4)
DEFAULT_KEYWORD_PREFIX = "bcut-"


class ConfigError(ValueError):
    """설정 값이 올바르지 않다."""


@dataclass(frozen=True)
class Config:
    reason_tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_REASON_TIERS))
    keyword_prefix: str = DEFAULT_KEYWORD_PREFIX
    config_version: str = "default-0"

    def tier_for(self, reason: str) -> str:
        try:
            return self.reason_tiers[reason]
        except KeyError:
            raise ConfigError(f"알 수 없는 사유: {reason}") from None


def _validate_tiers(tiers: dict[str, str]) -> None:
    for reason, tier in tiers.items():
        if reason not in REASONS:
            raise ConfigError(f"알 수 없는 사유: {reason}")
        if tier not in TIERS:
            raise ConfigError(f"{reason}의 등급이 올바르지 않다: {tier} (candidate 또는 review)")


def load_config(path: Path | None = None) -> Config:
    """설정 파일(TOML)을 읽는다. 파일이 없으면 기본값을 쓴다."""
    if path is None:
        return Config()
    with path.open("rb") as f:
        data = tomllib.load(f)
    tiers = dict(DEFAULT_REASON_TIERS)
    tiers.update(data.get("reason_tiers", {}))
    _validate_tiers(tiers)
    return Config(
        reason_tiers=tiers,
        keyword_prefix=data.get("keyword_prefix", DEFAULT_KEYWORD_PREFIX),
        config_version=str(data.get("config_version", path.name)),
    )
