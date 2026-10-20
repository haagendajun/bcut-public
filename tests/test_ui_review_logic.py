"""훑기 모드의 순수 로직(review_logic.js)을 JavaScriptCore(osascript)로 시험한다 (spec FR-21·22)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

LOGIC = Path(__file__).resolve().parents[1] / "src" / "bcut" / "ui" / "web" / "review_logic.js"

pytestmark = pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript 없음 (macOS 아님)")


def run_js(body: str, tmp_path: Path):
    f = tmp_path / "t.js"
    f.write_text(LOGIC.read_text(encoding="utf-8") + "\n" + body, encoding="utf-8")
    out = subprocess.run(["osascript", "-l", "JavaScript", str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


ROWS = """
var R = BcutReviewLogic;
var rows = [
 {file:'C.CR3', size:3, status:'normal'}, {file:'A.CR3', size:1, status:'normal'},
 {file:'B.CR3', size:2, status:'candidate'}, {file:'D.CR3', size:4, status:'review'},
 {file:'E.CR3', size:5, status:'normal'}, {file:'F.CR3', size:6, status:'no_face'}
];
var ord = R.order(rows);
"""


def test_order_is_by_file_name_and_does_not_change_the_input(tmp_path):
    r = run_js(ROWS + "JSON.stringify({o: ord.map(function(x){return x.file;}), first: rows[0].file});", tmp_path)
    assert r == {"o": ["A.CR3", "B.CR3", "C.CR3", "D.CR3", "E.CR3", "F.CR3"], "first": "C.CR3"}


def test_same_key_again_clears_and_other_key_replaces(tmp_path):
    r = run_js("var R = BcutReviewLogic; JSON.stringify([R.nextMark(null,'pick'), R.nextMark('pick','pick'),"
               " R.nextMark('pick','discard'), R.nextMark('maybe','maybe')]);", tmp_path)
    assert r == ["pick", None, "discard", None]


def test_keys_map_to_marks(tmp_path):
    r = run_js("var R = BcutReviewLogic; JSON.stringify({k: R.KEY_TO_KIND, l: Object.keys(R.MARKS).map("
               "function(k){return R.MARKS[k].label;})});", tmp_path)
    assert r["k"] == {"s": "pick", "m": "maybe", "x": "discard"} and r["l"] == ["셀렉", "보류", "버릴 컷"]


def test_suspects_are_flagged_and_marks_key_uses_name_and_size(tmp_path):
    r = run_js(ROWS + "JSON.stringify({s: ord.map(R.isSuspect), key: R.markKey(ord[0])});", tmp_path)
    assert r == {"s": [False, True, False, True, False, False], "key": "A.CR3|1"}


def test_move_stops_at_the_ends_and_skips_suspects_only_when_asked(tmp_path):
    r = run_js(ROWS + """
JSON.stringify({
  next: R.move(ord, 0, 1, false), nextSkip: R.move(ord, 0, 1, true),   // B가 의심 컷이라 건너뛴다
  prevSkip: R.move(ord, 4, -1, true), prev: R.move(ord, 4, -1, false),
  endStays: R.move(ord, 5, 1, false), startStays: R.move(ord, 0, -1, false),
  allSuspectStays: R.move([ord[1], ord[3]], 0, 1, true)
});""", tmp_path)
    assert r == {"next": 1, "nextSkip": 2, "prevSkip": 2, "prev": 3, "endStays": 5, "startStays": 0,
                 "allSuspectStays": 0}


def test_counts_and_marks_map(tmp_path):
    r = run_js(ROWS + """
var m = R.marksMap([{file:'A.CR3',size:1,kind:'pick'},{file:'B.CR3',size:2,kind:'discard'},
                    {file:'C.CR3',size:99,kind:'pick'}]);   // 크기가 다른 C는 다른 사진이라 세지 않는다
JSON.stringify({c: R.counts(ord, m), keys: Object.keys(m).sort()});""", tmp_path)
    assert r["c"] == {"pick": 1, "maybe": 0, "discard": 1, "none": 4, "total": 6}


def test_resume_index_is_after_the_last_marked_photo(tmp_path):
    r = run_js(ROWS + """
JSON.stringify({none: R.resumeIndex(ord, {}), some: R.resumeIndex(ord, {'B.CR3|2':'pick'}),
  last: R.resumeIndex(ord, {'F.CR3|6':'maybe'}), empty: R.resumeIndex([], {})});""", tmp_path)
    assert r == {"none": 0, "some": 2, "last": 5, "empty": 0}


def test_filmstrip_window_stays_inside_the_list(tmp_path):
    r = run_js("var R = BcutReviewLogic; JSON.stringify([R.windowRange(1500, 750, 12), R.windowRange(1500, 0, 12),"
               " R.windowRange(1500, 1499, 12), R.windowRange(5, 2, 12)]);", tmp_path)
    assert r == [[738, 763], [0, 13], [1487, 1500], [0, 5]]
