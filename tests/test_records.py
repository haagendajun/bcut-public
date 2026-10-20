"""기록 관리 시험 (spec S7): 목록, 표시 모두 해제, 휴지통으로 옮기기·복원, 경로 보호."""

import json
from pathlib import Path

import pytest

from bcut.ui import records
from bcut.ui.marks import MarkStore
from bcut.ui.records import RecordError, handle, list_records
from bcut.ui.reviews import ReviewStore

KEY = "260223_EVENT_A_SJ"


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    events = d / "events"
    store = MarkStore(events)
    for n, kind in (("A.CR3", "pick"), ("B.CR3", "pick"), ("C.CR3", "maybe"), ("D.CR3", "discard")):
        store.set(KEY, n, 100, kind)
    (events / KEY / "event.json").write_text(json.dumps({"name": "260223 EVENT_A SJ"}),
                                             encoding="utf-8")
    ReviewStore(events).add(KEY, {
        "id": "review-0001", "scan_ref": "j", "started_at": "2026-10-20T10:00:00+09:00",
        "ended_at": "2026-10-20T10:10:00+09:00", "photos_seen": 40, "pick_count": 2,
        "maybe_count": 1, "discard_count": 1, "tool_version": "t"})
    cap = d / "capture-one" / KEY / "sejun.cosessiondb"
    (cap / "catalog-backups").mkdir(parents=True)
    (cap / "bcut-backup.json").write_text(json.dumps({
        "catalog": "sejun.cosessiondb", "created_at": "2026-10-20T11:00:00", "entries": [1, 2, 3]}),
        encoding="utf-8")
    (cap / "bcut-style-backup.json").write_text(json.dumps({"entries": {"x": {}, "y": {}}}),
                                                encoding="utf-8")
    return d


def lines(d):
    return (d / "events" / KEY / "marks.jsonl").read_text(encoding="utf-8").splitlines()


def test_list_shows_marks_reviews_cloud_and_capture_records(data):
    out = list_records(data)
    card = out["events"][0]
    assert card["name"] == "260223 EVENT_A SJ"
    assert card["marks"] == {"pick": 2, "maybe": 1, "discard": 1}
    assert card["reviews"]["count"] == 1 and card["reviews"]["seen"] == 40
    assert card["reviews"]["seconds"] == 600
    assert card["cloud_pending"] == 5  # 표시 4건 + 훑기 기록 1건이 아직 안 올라감
    cap = card["capture"][0]
    assert (cap["document"], cap["photos"], cap["style_photos"]) == ("sejun.cosessiondb", 3, 2)
    assert out["trash"] == [] and out["cloud"]["consented"] is False


def test_clear_marks_cancels_all_but_keeps_history(data):
    before = len(lines(data))
    assert records.clear_marks(MarkStore(data / "events"), KEY) == 4
    assert MarkStore(data / "events").active(KEY)[0] == []
    assert len(lines(data)) == before + 4  # 줄이 지워지지 않고 취소 줄만 늘었다
    assert records.clear_marks(MarkStore(data / "events"), KEY) == 0
    assert list_records(data)["events"][0]["marks"] == {"pick": 0, "maybe": 0, "discard": 0}


def test_trash_event_moves_and_restore_brings_it_back(data):
    tid = records.trash_event(data, KEY)
    assert not (data / "events" / KEY).exists() and list_records(data)["events"] == []
    assert (data / "trash" / tid / "event" / "marks.jsonl").exists()  # 파일은 그대로 있다
    assert list_records(data)["trash"][0]["id"] == tid
    assert records.restore(data, tid) == 1
    assert list_records(data)["events"][0]["marks"]["pick"] == 2
    assert list_records(data)["trash"] == []  # 복원한 항목은 지운 기록 목록에서 빠진다


def test_restore_refuses_when_the_original_place_is_taken(data):
    tid = records.trash_event(data, KEY)
    MarkStore(data / "events").set(KEY, "Z.CR3", 1, "pick")  # 같은 이름의 새 기록이 생겼다
    with pytest.raises(RecordError):
        records.restore(data, tid)
    assert (data / "trash" / tid / "event").exists()  # 휴지통의 것은 그대로


def test_trash_capture_moves_only_the_record_files(data):
    tid = records.trash_capture(data, KEY, "sejun.cosessiondb")
    cap = data / "capture-one" / KEY / "sejun.cosessiondb"
    assert not (cap / "bcut-backup.json").exists() and not (cap / "bcut-style-backup.json").exists()
    assert (cap / "catalog-backups").is_dir()  # 카탈로그 백업 폴더는 건드리지 않는다
    assert records.restore(data, tid) == 2 and (cap / "bcut-backup.json").exists()


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", "/etc", ".hidden", "", None, 5])
def test_names_that_could_escape_are_rejected(data, bad):
    with pytest.raises(RecordError):
        records.trash_event(data, bad)
    with pytest.raises(RecordError):
        records.restore(data, bad)
    with pytest.raises(RecordError):
        records.trash_capture(data, KEY, bad if isinstance(bad, str) and bad else "..")


def test_handle_statuses(data):
    store = MarkStore(data / "events")
    def call(method, path, body=None):
        return handle(store, data, method, path, body)

    assert call("GET", "/api/records")[0] == 200
    assert call("POST", "/api/records/clear-marks", {"event": KEY}) == (200, {"cleared": 4})
    assert call("POST", "/api/records/trash", {"kind": "x"})[0] == 400
    assert call("POST", "/api/records/trash", {"kind": "event", "event": ".."})[0] == 400
    assert call("POST", "/api/records/restore", {"id": "없는항목"})[0] == 400
    assert call("PUT", "/api/records")[0] == 405
    assert call("POST", "/api/records/nope", {})[0] == 404


def test_module_has_no_delete_calls():
    text = Path(records.__file__).read_text(encoding="utf-8")
    for call in ("unlink(", "rmtree(", "os.remove(", "rmdir("):
        assert call not in text
