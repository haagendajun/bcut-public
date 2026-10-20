"""훑기 기록 시험 (spec FR-26): 덧붙이기만, 같은 번호는 한 번만, 잘못된 값은 거절."""

import json
from pathlib import Path

import pytest

from bcut.ui.reviews import ReviewStore, post_review

OK = {"id": "rev-0001-abcdef", "started_at": "2026-10-20T10:00:00+09:00",
      "ended_at": "2026-10-20T10:10:00+09:00", "seen": 120, "pick": 30, "maybe": 5, "discard": 8}


def post(store, tmp_path, **changes):
    return post_review(store, tmp_path / "행사", "job123", {**OK, **changes}, "0.1.0")


def test_a_review_is_saved_with_the_erd_column_names(tmp_path):
    store = ReviewStore(tmp_path / "events")
    status, out = post(store, tmp_path)
    assert status == 200 and out["saved"] is True and out["seconds"] == 600.0
    assert out["seconds_per_photo"] == 5.0  # 600초 ÷ 120장
    (line,) = (tmp_path / "events" / "행사" / "reviews.jsonl").read_text(encoding="utf-8").splitlines()
    item = json.loads(line)
    assert item == {"id": OK["id"], "scan_ref": "job123", "started_at": "2026-10-20T10:00:00+09:00",
                    "ended_at": "2026-10-20T10:10:00+09:00", "photos_seen": 120, "pick_count": 30,
                    "maybe_count": 5, "discard_count": 8, "tool_version": "0.1.0"}


def test_the_same_id_is_saved_once_and_the_file_only_grows(tmp_path):
    store = ReviewStore(tmp_path / "events")
    path = tmp_path / "events" / "행사" / "reviews.jsonl"
    assert post(store, tmp_path)[1]["saved"] is True
    before = path.read_text(encoding="utf-8")
    again = post(store, tmp_path, seen=999)  # 같은 번호를 다시 보내도 바뀌지 않는다
    assert again[0] == 200 and again[1]["saved"] is False and path.read_text(encoding="utf-8") == before
    assert post(store, tmp_path, id="rev-0002-abcdef")[1]["saved"] is True
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    assert [x["id"] for x in store.list("행사")] == [OK["id"], "rev-0002-abcdef"]


@pytest.mark.parametrize("changes", [
    {"id": ""}, {"id": "x"}, {"id": "bad id with spaces"}, {"id": 5},
    {"started_at": "어제"}, {"ended_at": None}, {"ended_at": "2026-10-20T09:00:00+09:00"},  # 끝이 시작보다 빠름
    {"seen": -1}, {"pick": "3"}, {"maybe": 1.5}, {"discard": True}, {"seen": 10**9},
])
def test_bad_values_are_refused_and_nothing_is_written(tmp_path, changes):
    store = ReviewStore(tmp_path / "events")
    status, out = post(store, tmp_path, **changes)
    assert status == 400 and "error" in out
    assert not (tmp_path / "events").exists()


def test_zero_photos_gives_no_per_photo_time_and_time_without_zone_is_accepted(tmp_path):
    store = ReviewStore(tmp_path / "events")
    status, out = post(store, tmp_path, seen=0, started_at="2026-10-20T10:00:00", ended_at="2026-10-20T10:00:30")
    assert status == 200 and out["seconds"] == 30.0 and out["seconds_per_photo"] is None


def test_broken_lines_are_skipped_when_reading(tmp_path):
    store = ReviewStore(tmp_path / "events")
    post(store, tmp_path)
    path = Path(tmp_path / "events" / "행사" / "reviews.jsonl")
    path.write_text(path.read_text(encoding="utf-8") + "깨진 줄\n[1,2]\n", encoding="utf-8")
    assert len(store.list("행사")) == 1
