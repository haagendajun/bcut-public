"""화면의 순수 로직(logic.js)을 macOS의 JavaScriptCore(osascript)로 시험한다. DOM은 쓰지 않는다."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

LOGIC = Path(__file__).resolve().parents[1] / "src" / "bcut" / "ui" / "web" / "logic.js"

pytestmark = pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript 없음 (macOS 아님)")


def run_js(body: str, tmp_path: Path):
    script = LOGIC.read_text(encoding="utf-8") + "\n" + body
    f = tmp_path / "t.js"
    f.write_text(script, encoding="utf-8")
    out = subprocess.run(["osascript", "-l", "JavaScript", str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


ROWS = """
var rows = [
 {file:'A', status:'candidate', reasons:['eyes_closed'], score:0.05, confidence:0.9, note:null, faces:1},
 {file:'B', status:'candidate', reasons:['eyes_closed'], score:0.10, confidence:0.7, note:null, faces:2},
 {file:'C', status:'review', reasons:['exposure','eyes_closed'], score:0.15, confidence:0.3, note:'group', faces:3},
 {file:'D', status:'normal', reasons:[], score:0.3, confidence:null, note:null, faces:1},
 {file:'E', status:'no_face', reasons:[], score:null, confidence:null, note:null, faces:0},
 {file:'F', status:'unscorable', reasons:[], score:null, confidence:null, note:'small_eye', faces:1}
];
var L = BcutLogic;
"""


def test_tiers_and_rescue_rule(tmp_path):
    r = run_js(ROWS + """
var res = {a: L.tierOf(rows[0], {}), a2: L.tierOf(rows[0], {A:true}), c: L.tierOf(rows[2], {C:true}),
  d: L.tierOf(rows[3], {D:true}), e: L.tierOf(rows[4], {}), f: L.tierOf(rows[5], {}),
  rescuedFlag: L.isRescued(rows[3], {D:true}), rescuedFlag2: L.isRescued(rows[0], {A:true})};
JSON.stringify(res);""", tmp_path)
    assert r == {"a": "candidate", "a2": "rescued", "c": "rescued", "d": "normal", "e": "other",
                 "f": "other", "rescuedFlag": False, "rescuedFlag2": True}  # 정상 컷은 살리기 대상이 아니다


def test_filter_by_tier_reason_note_and_rescued_leave_flagged(tmp_path):
    r = run_js(ROWS + """
function names(f, resc){return L.filterRows(rows, resc||{}, f).map(function(x){return x.file;});}
JSON.stringify({
  flagged: names({tier:'flagged'}), cand: names({tier:'candidate'}), rev: names({tier:'review'}),
  normal: names({tier:'normal'}), other: names({tier:'other'}), all: names({tier:'all'}),
  eyes: names({tier:'flagged', reason:'eyes_closed'}), expo: names({tier:'flagged', reason:'exposure'}),
  grp: names({tier:'all', note:'group'}),
  afterRescue: names({tier:'flagged'}, {A:true, C:true}),
  rescuedTier: names({tier:'rescued'}, {A:true, C:true}),
  eyesAfterRescue: names({tier:'flagged', reason:'eyes_closed'}, {A:true})
});""", tmp_path)
    assert r["flagged"] == ["A", "B", "C"] and r["cand"] == ["A", "B"] and r["rev"] == ["C"]
    assert r["normal"] == ["D"] and r["other"] == ["E", "F"] and len(r["all"]) == 6
    assert r["eyes"] == ["A", "B", "C"] and r["expo"] == ["C"] and r["grp"] == ["C"]
    assert r["afterRescue"] == ["B"] and r["rescuedTier"] == ["A", "C"]
    assert r["eyesAfterRescue"] == ["B", "C"]  # 살린 컷은 사유에서도 빠진다


def test_sorting(tmp_path):
    r = run_js(ROWS + """
function order(k){return L.sortRows(rows, k).map(function(x){return x.file;});}
var before = rows.map(function(x){return x.file;}).join('');
var o = {conf: order('confidence'), score: order('score'), name: order('name'), faces: order('faces')};
o.untouched = rows.map(function(x){return x.file;}).join('') === before;
JSON.stringify(o);""", tmp_path)
    assert r["conf"] == ["A", "B", "C", "D", "E", "F"]  # 확신도 높은 순, 없는 것은 뒤(이름순)
    assert r["score"] == ["A", "B", "C", "D", "E", "F"]  # 눈 점수 낮은 순, 없는 것은 뒤
    assert r["name"] == ["A", "B", "C", "D", "E", "F"]
    assert r["faces"] == ["C", "B", "A", "D", "F", "E"]
    assert r["untouched"] is True  # 원래 목록을 바꾸지 않는다


def test_counts_and_rescued_names(tmp_path):
    r = run_js(ROWS + """
var c0 = L.counts(rows, {}), c1 = L.counts(rows, {A:true});
JSON.stringify({c0: c0, c1: c1, names: L.rescuedNames(rows, {A:true, D:true, C:true})});""", tmp_path)
    assert r["c0"]["candidate"] == 2 and r["c0"]["review"] == 1 and r["c0"]["normal"] == 1
    assert r["c0"]["other"] == 2 and r["c0"]["total"] == 6 and r["c0"]["reasons"] == {
        "eyes_closed": 3, "exposure": 1}
    assert r["c1"]["rescued"] == 1 and r["c1"]["candidate"] == 1 and r["c1"]["reasons"]["eyes_closed"] == 2
    assert r["names"] == ["A", "C"]  # 정상 컷(D)은 살린 컷으로 세지 않는다


def test_viewer_step_and_labels(tmp_path):
    r = run_js(ROWS + """
JSON.stringify({s: [L.step(5,0,-1), L.step(5,0,1), L.step(5,4,1), L.step(5,2,-1), L.step(0,0,1)],
  b0: L.badges(rows[0], {}), b1: L.badges(rows[0], {A:true}), b2: L.badges(rows[2], {}),
  plan: L.planLines({counts: {'후보': 3, '정상': 7}}), bytes: [L.formatBytes(2.5e9), L.formatBytes(4e8)]});""", tmp_path)
    assert r["s"] == [0, 1, 4, 1, -1]
    assert r["b0"] == [{"cls": "b-candidate", "text": "버릴 것 같은 컷"},
                       {"cls": "b-review", "text": "눈 감김"}]
    assert r["b1"] == [{"cls": "b-normal", "text": "남긴 컷"}]  # 남기면 이상 없음 색, 문제 배지 없음
    assert [b["text"] for b in r["b2"]] == ["직접 확인", "너무 밝거나 어두움", "눈 감김", "여러 명 사진"]
    assert "직접 확인" in r["b2"][3]["tip"]  # 꼬리표에는 마우스를 올리면 보이는 설명이 있다
    assert r["plan"] == ["후보: 3장", "정상: 7장"] and r["bytes"] == ["2.5GB", "400MB"]


def test_plain_language_explanations_replace_numbers(tmp_path):
    r = run_js(ROWS + """
var e = function(i, resc){ return L.explain(rows[i], resc || {}); };
JSON.stringify({a: e(0), c: e(2), d: e(3), e: e(4), f: e(5), rescued: e(0, {A:true}),
  expo: L.explain({status:'review', reasons:['exposure'], exposure:'under'}, {}),
  blur: L.explain({status:'review', reasons:['blur','out_of_focus']}, {}),
  readErr: L.explain({status:'review', reasons:[], note:'read_error'}, {}),
  s: [L.suspicion(0.9), L.suspicion(0.7), L.suspicion(0.5), L.suspicion(0.4), L.suspicion(0.1), L.suspicion(null)]});""", tmp_path)
    assert r["a"] == ["눈이 거의 감긴 것 같아요."]  # 후보 등급은 "거의 감김"
    assert r["c"] == ["눈이 감겼을 수도 있어요.", "너무 밝거나 어두워요."]  # 직접 확인 등급은 "감겼을 수도"
    assert r["d"] == ["눈이 떠 있고 큰 문제가 안 보여요."]
    assert r["e"] == ["얼굴이 없어서 눈은 보지 않았어요."] and r["f"] == ["눈을 판단하기 어려웠어요."]
    assert r["rescued"] == ["남기기로 했어요. 나누어 담으면 이상 없음 폴더로 가요."]
    assert r["expo"] == ["사진 전체가 너무 어두워요."]
    assert r["blur"] == ["사진 전체가 흔들린 것 같아요.", "얼굴에 초점이 안 맞은 것 같아요."]
    assert r["readErr"] == ["사진을 읽지 못해서 직접 확인이 필요해요."]
    assert r["s"] == ["높음", "높음", "보통", "보통", "낮음", ""]


def test_no_jargon_in_visible_labels(tmp_path):
    r = run_js(ROWS + """
var all = [];
Object.keys(L.STATUS).forEach(function(k){ all.push(L.STATUS[k]); });
Object.keys(L.NOTE).forEach(function(k){ all.push(L.NOTE[k]); all.push(L.NOTE_TIP[k]); });
Object.keys(L.REASON).forEach(function(k){ all.push(L.REASON[k]); });
L.TIERS.forEach(function(t){ all.push(t[1]); });
JSON.stringify(all);""", tmp_path)
    text = " ".join(r)
    for jargon in ("B컷", "판정", "사유", "확신도", "썸네일", "복제", "리포트", "APFS", "살린", "살리기"):
        assert jargon not in text, jargon


def test_priority_groups_order_and_sorting(tmp_path):
    r = run_js(ROWS + """
var g = L.priorityGroups(rows, {});
var g2 = L.priorityGroups(rows, {A:true});
JSON.stringify({ids: g.map(function(x){return x.id;}), ranks: g.map(function(x){return x.rank;}),
  files: g.map(function(x){return x.rows.map(function(r){return r.file;});}),
  files2: g2.map(function(x){return x.rows.map(function(r){return r.file;});}),
  order: L.visibleOrder(g, {candidate:true, review:true, normal:false, other:false, rescued:false}).map(function(r){return r.file;}),
  order2: L.visibleOrder(g, {candidate:false, review:false, normal:true, other:true, rescued:false}).map(function(r){return r.file;})});""", tmp_path)
    assert r["ids"] == ["candidate", "review", "rescued", "normal", "other"]
    assert r["ranks"] == [1, 2, 0, 3, 3]  # 1순위가 맨 위, 이상 없음·얼굴 없음은 맨 아래
    # 1순위는 의심 정도가 높은 순 (A 0.9 > B 0.7), 이상 없음·기타는 이름순
    assert r["files"] == [["A", "B"], ["C"], [], ["D"], ["E", "F"]]
    assert r["files2"] == [["B"], ["C"], ["A"], ["D"], ["E", "F"]]  # 남긴 컷은 1순위에서 빠져 '남긴 컷'으로
    assert r["order"] == ["A", "B", "C"] and r["order2"] == ["D", "E", "F"]


def test_filter_by_my_marks_and_counts(tmp_path):
    r = run_js(ROWS + """
var marks = {A:'pick', C:'maybe', E:'discard'};
function names(f){return L.filterRows(rows, {}, f).map(function(x){return x.file;});}
var res = {pick: names({tier:'all', mark:'pick', marks:marks}), none: names({tier:'all', mark:'none', marks:marks}),
  both: names({tier:'candidate', mark:'pick', marks:marks}), flaggedMaybe: names({tier:'flagged', mark:'maybe', marks:marks}),
  nomark: names({tier:'all'}).length, counts: L.markCounts(rows, marks), noMarks: L.markCounts(rows, undefined)};
JSON.stringify(res);
""", tmp_path)
    assert r["pick"] == ["A"] and r["none"] == ["B", "D", "F"]
    assert r["both"] == ["A"] and r["flaggedMaybe"] == ["C"]
    assert r["nomark"] == 6  # mark를 안 주면 걸러지지 않는다
    assert r["counts"] == {"pick": 1, "maybe": 1, "discard": 1, "none": 3}
    assert r["noMarks"]["none"] == 6
