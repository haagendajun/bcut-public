"""올릴 내용을 정하는 순수 규칙 시험 (네트워크 없음)."""

import json

from bcut.ui.cloud_plan import db_uuid, make_plan, read_event, review_row


def _write(folder, marks=(), reviews=(), name=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "marks.jsonl").write_text(
        "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in marks), encoding="utf-8")
    (folder / "reviews.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in reviews), encoding="utf-8")
    if name:
        (folder / "event.json").write_text(json.dumps({"name": name}), encoding="utf-8")


T0, T1, T5 = ("2026-10-20T10:00:00+09:00", "2026-10-20T10:01:00+09:00",
              "2026-10-20T10:05:00+09:00")
M1 = {"id": "a" * 32, "file": "A.CR3", "size": 10, "kind": "pick", "at": T0}
C1 = {"id": "c" * 32, "cancel": "a" * 32, "at": T1}
M2 = {"id": "b" * 32, "file": "A.CR3", "size": 10, "kind": "maybe", "at": T1}


def test_event_name_from_event_json_else_folder_key(tmp_path):
    _write(tmp_path / "k1", name="EVENT_B 145")
    _write(tmp_path / "k2")
    assert read_event(tmp_path / "k1").name == "EVENT_B 145"
    assert read_event(tmp_path / "k2").name == "k2"


def test_cancel_is_folded_into_the_mark_and_only_one_stays_active(tmp_path):
    _write(tmp_path / "e", [M1, C1, M2])
    ev = read_event(tmp_path / "e")
    assert [m.kind for m in ev.marks] == ["pick", "maybe"]
    assert ev.marks[0].cancelled_at == C1["at"] and ev.marks[1].cancelled_at is None


def test_broken_lines_are_skipped(tmp_path):
    folder = tmp_path / "e"
    _write(folder, [M1])
    with (folder / "marks.jsonl").open("a") as f:
        f.write("{깨짐\n" + json.dumps({"id": "x"}) + "\n")
    assert len(read_event(folder).marks) == 1


def test_plan_skips_already_uploaded_and_orders_cancel_before_insert(tmp_path):
    _write(tmp_path / "e", [M1, C1, M2])
    ev = read_event(tmp_path / "e")
    fresh = make_plan(ev, {}, set())
    assert len(fresh.inserts) == 2 and len(fresh.cancels) == 1 and fresh.pending == 2
    # 첫 표시는 올렸고(활성), 그 뒤에 취소·새 표시가 생긴 경우
    later = make_plan(ev, {"a" * 32: "a"}, set())
    assert [m.id for m in later.inserts] == ["b" * 32]
    assert [m.id for m in later.cancels] == ["a" * 32] and later.pending == 2
    done = make_plan(ev, {"a" * 32: "c", "b" * 32: "a"}, set())
    assert done.pending == 0


def test_review_ids_map_to_stable_uuids():
    assert db_uuid("0123456789abcdef0123456789abcdef") == "01234567-89ab-cdef-0123-456789abcdef"
    assert db_uuid("review-001") == db_uuid("review-001") != db_uuid("review-002")
    row = review_row({"id": "review-001", "started_at": "s", "ended_at": "e", "photos_seen": 3,
                      "pick_count": 1, "maybe_count": 1, "discard_count": 0}, "EV")
    assert row["event_id"] == "EV" and "scan_id" not in row


def test_nothing_that_is_a_path_or_photo_content_is_in_rows(tmp_path):
    _write(tmp_path / "e", [M1])
    plan = make_plan(read_event(tmp_path / "e"), {}, set())
    assert set(vars(plan.inserts[0])) == {"id", "file", "size", "kind", "at", "cancelled_at"}
