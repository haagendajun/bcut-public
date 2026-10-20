"""표시(셀렉·보류·버릴 컷) 저장 시험 (spec FR-22, plan 2-2): 한 장에 하나, 덧붙이기만, 다시 열어도 남는다."""

import threading
from pathlib import Path

import pytest

from bcut.ui.marks import KINDS, MarkStore, event_key, file_size, list_marks, post_mark


def store(tmp_path):
    ticks = iter(f"2026-10-20T00:00:{i:02d}+09:00" for i in range(60))
    return MarkStore(tmp_path / "events", now=lambda: next(ticks))


def kinds(s, event="행사"):
    return {(m["file"], m["size"]): m["kind"] for m in s.active(event)[0]}


def test_new_store_has_no_marks(tmp_path):
    assert store(tmp_path).active("행사") == ([], 0)


def test_set_and_clear_a_mark(tmp_path):
    s = store(tmp_path)
    assert s.set("행사", "A.CR3", 10, "pick") == "pick"
    assert kinds(s) == {("A.CR3", 10): "pick"}
    assert s.set("행사", "A.CR3", 10, None) is None  # 같은 표시를 해제
    assert kinds(s) == {}


def test_one_mark_per_photo_new_mark_replaces_old(tmp_path):
    s = store(tmp_path)
    s.set("행사", "A.CR3", 10, "pick")
    s.set("행사", "A.CR3", 10, "discard")
    assert kinds(s) == {("A.CR3", 10): "discard"}  # 동시에 하나만


def test_same_mark_again_changes_nothing_in_the_file(tmp_path):
    s = store(tmp_path)
    s.set("행사", "A.CR3", 10, "maybe")
    path = tmp_path / "events" / "행사" / "marks.jsonl"
    before = path.read_text(encoding="utf-8")
    s.set("행사", "A.CR3", 10, "maybe")
    s.set("행사", "B.CR3", 10, None)  # 표시가 없는 사진을 해제해도 파일은 그대로
    assert path.read_text(encoding="utf-8") == before


def test_file_only_grows_and_keeps_cancelled_history(tmp_path):
    s = store(tmp_path)
    path = tmp_path / "events" / "행사" / "marks.jsonl"
    sizes = []
    for kind in ("pick", "maybe", None, "discard"):
        s.set("행사", "A.CR3", 10, kind)
        sizes.append(len(path.read_text(encoding="utf-8").splitlines()))
    assert sizes == [1, 3, 4, 5]  # 표시 1줄, 취소+표시 2줄, 취소 1줄, 표시 1줄 (줄어드는 일이 없다)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert sum('"cancel"' in x for x in lines) == 2  # 취소된 이력이 지워지지 않고 남는다


def test_marks_survive_reopening_and_are_per_event(tmp_path):
    s = store(tmp_path)
    s.set("행사", "A.CR3", 10, "pick")
    s.set("다른 행사", "A.CR3", 10, "discard")
    again = MarkStore(tmp_path / "events")  # 새로 열어도 (앱을 껐다 켜도) 남아 있다
    assert kinds(again, "행사") == {("A.CR3", 10): "pick"}
    assert kinds(again, "다른 행사") == {("A.CR3", 10): "discard"}


def test_same_name_but_different_size_is_a_different_photo(tmp_path):
    s = store(tmp_path)
    s.set("행사", "A.CR3", 10, "pick")
    s.set("행사", "A.CR3", 11, "maybe")
    assert kinds(s) == {("A.CR3", 10): "pick", ("A.CR3", 11): "maybe"}


def test_broken_lines_are_skipped_and_counted(tmp_path):
    s = store(tmp_path)
    s.set("행사", "A.CR3", 10, "pick")
    path = tmp_path / "events" / "행사" / "marks.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write("이건 JSON이 아니다\n" + '{"id":"x","file":"B.CR3","size":1,"kind":"bogus"}\n\n')
    marks, broken = s.active("행사")
    assert [m["file"] for m in marks] == ["A.CR3"] and broken == 2


def test_invalid_kind_is_refused(tmp_path):
    with pytest.raises(ValueError, match="kind"):
        store(tmp_path).set("행사", "A.CR3", 10, "like")
    assert set(KINDS) == {"pick", "maybe", "discard"}


def test_concurrent_marks_do_not_lose_lines(tmp_path):
    s = MarkStore(tmp_path / "events")
    threads = [threading.Thread(target=s.set, args=("행사", f"{i}.CR3", 1, "pick")) for i in range(30)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    marks, broken = s.active("행사")
    assert len(marks) == 30 and broken == 0


@pytest.mark.parametrize("name, key", [("260212_EVENT_B", "260212_EVENT_B"), ("행사 이름", "행사_이름"),
                                       ("..", "event"), ("a" * 200, "a" * 80), (".hidden", "hidden")])
def test_event_key_is_a_safe_folder_name(name, key):
    assert event_key(Path("/사진") / name) == key


def test_file_size_of_missing_file_is_none(tmp_path):
    assert file_size(tmp_path / "없음") is None
    (tmp_path / "a").write_bytes(b"123")
    assert file_size(tmp_path / "a") == 3


def test_post_mark_only_accepts_files_in_the_scan(tmp_path):
    (tmp_path / "A.CR3").write_bytes(b"x" * 7)
    s = store(tmp_path / "d")
    ok = post_mark(s, tmp_path, {"A.CR3"}, {"file": "A.CR3", "kind": "pick"})
    assert ok[0] == 200 and ok[1] == {"file": "A.CR3", "size": 7, "kind": "pick"}
    assert post_mark(s, tmp_path, {"A.CR3"}, {"file": "../B.CR3", "kind": "pick"})[0] == 404  # 경로 조작
    assert post_mark(s, tmp_path, {"A.CR3"}, {"file": "A.CR3", "kind": "bogus"})[0] == 400
    assert post_mark(s, tmp_path, {"A.CR3"}, {"kind": "pick"})[0] == 404
    listed = list_marks(s, tmp_path, {"A.CR3"})
    assert listed["marks"] == [{"file": "A.CR3", "size": 7, "kind": "pick"}]
    (tmp_path / "A.CR3").write_bytes(b"y" * 9)  # 같은 이름이지만 크기가 달라지면 다른 사진
    assert list_marks(s, tmp_path, {"A.CR3"})["marks"] == []
