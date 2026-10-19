"""HTML 리포트의 화면 코드를 macOS의 자바스크립트 엔진(JavaScriptCore, osascript)으로 실제 실행해 검증한다.

브라우저가 없어도 필터·정렬·"살리기"·저장·파일 이름 처리를 확인할 수 있도록, 이 테스트 안에서
아주 작은 가짜 화면(DOM) 환경을 만들어 리포트의 코드를 돌린다.
"""

import json
import re
import shutil
import subprocess

import pytest

from bcut.report.html_report import render_html
from bcut.scan import PhotoResult

pytestmark = pytest.mark.skipif(shutil.which("osascript") is None, reason="osascript(macOS) 필요")

EVIL = 'x</script><img src=x onerror=alert(1)>"&.CR3'
JPEG = b"\xff\xd8\xff\xe0fake"


def r(name, status, score, note=None, faces=1, considered=1, thumb=None, error=None):
    return PhotoResult(file=name, status=status, score=score, note=note, face_count=faces,
                       faces_considered=considered, eye_width_frac=0.01, thumbnail=thumb,
                       error=error)


SAMPLE = [
    r("a.CR3", "candidate", 0.0814, thumb=JPEG),
    r("b.CR3", "review", 0.15, note="group", faces=3, considered=2, thumb=JPEG),
    r("c.CR3", "normal", 0.30),
    r("d.CR3", "no_face", None, faces=0, considered=0),
    r("e.CR3", "review", None, note="read_error", faces=0, considered=0, error="LibRawError: x"),
    r("f.CR3", "review", 0.12, note="small_eye", thumb=JPEG),
    r(EVIL, "candidate", 0.10, thumb=JPEG),
]

SHIM = r"""
function Node(tag){this.tag=tag;this.children=[];this.attrs={};this.dataset={};this.className='';
 this._text='';this.listeners={};this.id='';this.style={_p:{},setProperty:function(k,v){this._p[k]=v;}};}
Node.prototype.appendChild=function(c){this.children.push(c);return c;};
Object.defineProperty(Node.prototype,'textContent',{
 get:function(){return this._text+this.children.map(function(c){return c.textContent;}).join('');},
 set:function(v){this.children=[];this._text=String(v);}});
Node.prototype.setAttribute=function(k,v){this.attrs[k]=v;};
Node.prototype.addEventListener=function(ev,fn){(this.listeners[ev]=this.listeners[ev]||[]).push(fn);};
Node.prototype.remove=function(){};
Node.prototype.fire=function(ev,arg){var self=this;(this.listeners[ev]||[]).forEach(function(f){f(arg||{target:self});});};
Node.prototype.click=function(){
 if(this.tag==='a'){DOWNLOADS.push({name:this.download,blob:LASTBLOB});}
 this.fire('click');};
function walk(n,out,pred){n.children.forEach(function(c){if(pred(c))out.push(c);walk(c,out,pred);});return out;}
Node.prototype.querySelector=function(sel){var o=walk(this,[],function(c){return c.tag===sel;});return o[0]||null;};
Node.prototype.querySelectorAll=function(sel){return walk(this,[],function(c){return c.tag===sel;});};
var REG={};var DOWNLOADS=[];var LASTBLOB=null;
['title','meta','cards','tiers','notes','reasons','sort','size','grid','count','foot','dl-saved','dl-visible','clear-saved','data']
 .forEach(function(id){REG[id]=new Node('div');REG[id].id=id;});
REG['tiers'].tag='div';REG['notes'].tag='div';
var document={
 getElementById:function(id){return REG[id]||null;},
 createElement:function(t){return new Node(t);},
 body:new Node('body'),
 querySelectorAll:function(sel){var p=sel.split(' ');var root=REG[p[0].slice(1)];return root.querySelectorAll(p[1]);}
};
var STORE={};
var localStorage={getItem:function(k){return (k in STORE)?STORE[k]:null;},setItem:function(k,v){STORE[k]=String(v);}};
function Blob(parts,opts){this.parts=parts;this.opts=opts;}
var URL={createObjectURL:function(b){LASTBLOB=b;return 'blob:x';},revokeObjectURL:function(){}};
function setTimeout(){}
"""

DRIVER = r"""
function names(){return REG['grid'].children.map(function(it){
 return it.children.length>1?it.children[1].children[0].textContent:'(empty:'+it.textContent+')';});}
function clickTier(t){REG['tiers'].children.filter(function(b){return b.dataset.tier===t;})[0].click();}
function clickNote(n){var b=REG['notes'].children.filter(function(x){return x.dataset.note===n;})[0];b.click();return !!b;}
function setSort(v){REG['sort'].fire('change',{target:{value:v}});}
var obs={};
obs.initial=names();obs.countText=REG['count'].textContent;
obs.title=REG['title'].textContent;obs.meta=REG['meta'].textContent;obs.foot=REG['foot'].textContent;
obs.cards=REG['cards'].children.map(function(c){return c.children[0].textContent+':'+c.children[1].textContent;});
obs.tierLabels=REG['tiers'].children.map(function(b){return b.textContent;});
obs.noteLabels=REG['notes'].children.map(function(b){return b.textContent;});
clickTier('normal');obs.normal=names();
clickTier('other');obs.other=names();
clickTier('candidate');obs.candidate=names();
clickTier('review');obs.review=names();
clickTier('all');obs.allScore=names();
setSort('name');obs.allName=names();
setSort('faces');obs.allFaces=names();
setSort('score');
clickTier('flagged');
clickNote('group');obs.noteGroup=names();
clickNote('group');obs.noteCleared=names();
clickNote('small_eye');obs.noteSmall=names();
clickNote('small_eye');
clickNote('read_error');obs.noteRead=names();
clickNote('read_error');
// 살리기
var first=REG['grid'].children[0];
var btn=first.children[1].children[first.children[1].children.length-1];
obs.btnBefore=btn.textContent;btn.click();
obs.savedClass=REG['grid'].children[0].className;
obs.savedCount=REG['count'].textContent;
obs.storage=JSON.parse(STORE['bcut-saved:'+JSON.parse(REG['data'].textContent).id]);
// 내려받기
REG['dl-saved'].click();REG['dl-visible'].click();
obs.downloads=DOWNLOADS.map(function(d){return {name:d.name,text:d.blob.parts.join('')};});
// 크기 슬라이더
REG['size'].fire('input',{target:{value:'240'}});obs.gridWidth=REG['grid'].style._p['--w'];
// 모두 지우기
REG['clear-saved'].click();obs.afterClear=REG['count'].textContent;obs.storageAfterClear=JSON.parse(STORE['bcut-saved:'+JSON.parse(REG['data'].textContent).id]);
// 카드 내용
clickTier('all');
var card=REG['grid'].children.filter(function(it){return it.children[1].children[0].textContent==='b.CR3';})[0];
obs.cardB=card.children[1].children.map(function(c){return c.textContent;});
var cardE=REG['grid'].children.filter(function(it){return it.children[1].children[0].textContent==='e.CR3';})[0];
obs.cardE=cardE.children[1].children.map(function(c){return c.textContent;});
obs.imgA=REG['grid'].children[0].children[0].children.length;
JSON.stringify(obs);
"""


def run_report_js(html: str, saved_before: list[str] | None = None, driver: str | None = None) -> dict:
    data = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1)
    code = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    pre = ""
    if saved_before is not None:
        pre = "STORE['bcut-saved:" + json.loads(data)["id"] + "']=" + json.dumps(json.dumps(saved_before)) + ";"
    program = (
        SHIM
        + "REG['data']._text=" + json.dumps(data) + ";" + pre
        + "(0,eval)(" + json.dumps(code) + ");"
        + (driver or DRIVER)
    )
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "driver.js"
        path.write_text(program, encoding="utf-8")
        out = subprocess.run(["osascript", "-l", "JavaScript", str(path)], capture_output=True,
                             text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


@pytest.fixture(scope="module")
def obs():
    html = render_html(SAMPLE, folder_name="행사 A", generated_at="2026-10-19 18:00")
    return run_report_js(html)


def test_runs_without_error_and_shows_title_and_meta(obs):
    assert obs["title"] == "행사 A · 1차 컷 리포트"  # 제목에 행사 이름
    assert obs["meta"].startswith("눈 감김·노출 판정 · 사진 7장")  # 부제목에 판정 범위
    assert "만든 시각 2026-10-19 18:00" in obs["meta"]


def test_footer_says_normal_is_not_a_cut_grade(obs):
    assert "A컷이라는 뜻은 아니에요" in obs["foot"]
    assert "좋은 컷을 고르는 일은 사람이 해요" in obs["foot"]


def test_summary_cards(obs):
    assert obs["cards"] == ["2:B컷 후보", "3:사람이 확인", "1:정상", "1:얼굴 없음·판정 불가",
                            "4:눈 감김으로 올라온 컷", "0:노출로 올라온 컷"]


def test_default_view_shows_candidates_and_reviews_most_closed_first(obs):
    # 점수 낮은 순: a(0.0814), 악성 이름(0.10), f(0.12), b(0.15), e(점수 없음은 맨 뒤)
    assert obs["initial"] == ["a.CR3", EVIL, "f.CR3", "b.CR3", "e.CR3"]
    assert "보이는 컷 5장 / 전체 7장" in obs["countText"]


def test_tier_filters(obs):
    assert obs["normal"] == ["c.CR3"]
    assert obs["other"] == ["d.CR3"]
    assert obs["candidate"] == ["a.CR3", EVIL]
    assert obs["review"] == ["f.CR3", "b.CR3", "e.CR3"]


def test_tier_buttons_show_counts(obs):
    assert obs["tierLabels"] == ["후보+확인 5", "B컷 후보 2", "사람이 확인 3", "정상 1",
                                 "얼굴 없음·판정 불가 1", "전체 7"]


def test_sorting(obs):
    assert obs["allScore"] == ["a.CR3", EVIL, "f.CR3", "b.CR3", "c.CR3", "d.CR3", "e.CR3"]
    assert obs["allName"] == ["a.CR3", "b.CR3", "c.CR3", "d.CR3", "e.CR3", "f.CR3", EVIL]
    assert obs["allFaces"][0] == "b.CR3"  # 얼굴 3개가 맨 앞
    assert obs["allFaces"][-2:] == ["d.CR3", "e.CR3"]  # 얼굴 0개는 맨 뒤


def test_note_filters_toggle(obs):
    assert obs["noteLabels"][0] == "세부 사유"
    assert obs["noteLabels"][1:] == ["눈이 좁음 1", "단체 사진 1", "읽기 실패 1"]
    assert obs["noteGroup"] == ["b.CR3"]
    assert obs["noteCleared"] == obs["initial"]  # 한 번 더 누르면 해제
    assert obs["noteSmall"] == ["f.CR3"]
    assert obs["noteRead"] == ["e.CR3"]


def test_save_toggle_marks_card_counts_and_persists(obs):
    assert obs["btnBefore"] == "살리기"
    assert "saved" in obs["savedClass"]
    assert "내가 살린 컷 1장" in obs["savedCount"]
    assert obs["storage"] == ["a.CR3"]


def test_downloads_are_plain_file_name_lists(obs):
    saved, visible = obs["downloads"]
    assert saved == {"name": "bcut-saved.txt", "text": "a.CR3\n"}
    assert visible["name"] == "bcut-visible.txt"
    assert visible["text"].splitlines() == obs["initial"]


def test_size_slider_and_clear(obs):
    assert obs["gridWidth"] == "240px"
    assert "내가 살린 컷 0장" in obs["afterClear"]
    assert obs["storageAfterClear"] == []


def test_card_text_for_group_and_error_photos(obs):
    # 단체 사진: 등급 배지, 눈 감김 사유 배지, 세부 사유(단체 사진)가 차례로 나온다
    assert obs["cardB"] == ["b.CR3", "사람이 확인눈 감김단체 사진", "눈 점수 0.150 · 얼굴 3 (판정 2)", "살리기"]
    assert obs["cardE"][0] == "e.CR3"
    assert "점수 없음" in obs["cardE"][2] and "오류: LibRawError: x" in obs["cardE"]


def test_thumbnail_is_an_img_element(obs):
    assert obs["imgA"] == 1


def test_hostile_file_name_is_shown_as_text(obs):
    # 이름이 HTML로 해석됐다면 화면 코드가 이름 그대로를 돌려주지 못한다
    assert EVIL in obs["initial"]


def test_saved_choices_are_restored_from_storage():
    html = render_html(SAMPLE, folder_name="행사 A", generated_at="2026-10-19 18:00")
    restored = run_report_js(html, saved_before=["b.CR3"])
    assert "내가 살린 컷 1장" in restored["countText"]
    assert restored["initial"][3] == "b.CR3"


# ---- 사유(눈 감김, 노출) 필터 ---------------------------------------------------------


def rx(name, status, eyes_status, score, exposure_kind=None, p99=None, face_hi=None,
       global_hi=None, severity=None, note=None, faces=1, considered=None, face_count=None):
    return PhotoResult(
        file=name, status=status, score=score, note=note,
        face_count=faces if face_count is None else face_count,
        faces_considered=faces if considered is None else considered, eye_width_frac=0.01,
        thumbnail=None, eyes_status=eyes_status, exposure_kind=exposure_kind, exposure_p99=p99,
        exposure_face_hi=face_hi, exposure_global_hi=global_hi, exposure_severity=severity)


SAMPLE2 = [
    rx("a2.CR3", "candidate", "candidate", 0.08),
    rx("b2.CR3", "review", "normal", 0.30, "over_face", 255.0, 0.6, 0.1, 0.6),
    rx("c2.CR3", "review", "review", 0.15, "under", 90.0, 0.0, 0.0, 0.647, note="group",
       faces=3, considered=2),
    rx("d2.CR3", "review", "no_face", None, "under", 40.0, None, 0.0, 0.843, faces=0),
    rx("e2.CR3", "normal", "normal", 0.31),
    rx("f2.CR3", "review", "no_face", None, "over_global", 240.0, None, 0.5, 0.5, faces=0),
]

DRIVER2 = r"""
function names(){return REG['grid'].children.map(function(it){
 return it.children.length>1?it.children[1].children[0].textContent:'(empty)';});}
function clickTier(t){REG['tiers'].children.filter(function(b){return b.dataset.tier===t;})[0].click();}
function clickReason(k){REG['reasons'].children.filter(function(b){return b.dataset.reason===k;})[0].click();}
function setSort(v){REG['sort'].fire('change',{target:{value:v}});}
function card(n){return REG['grid'].children.filter(function(it){
 return it.children.length>1&&it.children[1].children[0].textContent===n;})[0];}
function body(n){return card(n).children[1].children.map(function(c){return c.textContent;});}
function badges(n){return card(n).children[1].children[1].children.map(function(c){return c.textContent;});}
var obs={};
obs.meta=REG['meta'].textContent;
obs.cards=REG['cards'].children.map(function(c){return c.children[0].textContent+':'+c.children[1].textContent;});
obs.reasonLabels=REG['reasons'].children.map(function(b){return b.textContent;});
obs.initial=names();
clickReason('eyes_closed');obs.eyes=names();obs.countEyes=REG['count'].textContent;
clickReason('eyes_closed');obs.cleared=names();
clickReason('exposure');obs.exposure=names();
setSort('exposure');obs.exposureBySeverity=names();
setSort('score');
clickTier('candidate');obs.exposureAndCandidate=names();
clickTier('flagged');clickReason('exposure');
clickTier('all');setSort('exposure');obs.allBySeverity=names();setSort('score');
obs.badges={};['a2.CR3','b2.CR3','c2.CR3','d2.CR3','f2.CR3'].forEach(function(n){obs.badges[n]=badges(n);});
obs.b2=body('b2.CR3');obs.d2=body('d2.CR3');obs.f2=body('f2.CR3');obs.a2=body('a2.CR3');
JSON.stringify(obs);
"""


@pytest.fixture(scope="module")
def obs2():
    html = render_html(SAMPLE2, folder_name="행사 B", generated_at="2026-10-19 18:00")
    return run_report_js(html, driver=DRIVER2)


def test_reason_cards_and_buttons(obs2):
    assert obs2["cards"] == ["1:B컷 후보", "4:사람이 확인", "1:정상", "0:얼굴 없음·판정 불가",
                             "2:눈 감김으로 올라온 컷", "4:노출로 올라온 컷"]
    assert obs2["reasonLabels"] == ["판정 종류", "눈 감김 2", "노출 4"]
    assert "노출 기준" in obs2["meta"] and "상위 1% 밝기" in obs2["meta"]


def test_reason_filter_by_eyes_closed(obs2):
    assert obs2["eyes"] == ["a2.CR3", "c2.CR3"]  # 눈 점수 낮은 순
    assert "보이는 컷 2장" in obs2["countEyes"]


def test_reason_filter_toggles_off(obs2):
    assert obs2["cleared"] == obs2["initial"]
    assert obs2["initial"] == ["a2.CR3", "c2.CR3", "b2.CR3", "d2.CR3", "f2.CR3"]


def test_reason_filter_by_exposure_includes_photos_with_both_reasons(obs2):
    # c2는 눈 감김과 노출이 함께 걸린 사진이라 두 필터 모두에 나온다
    assert set(obs2["exposure"]) == {"b2.CR3", "c2.CR3", "d2.CR3", "f2.CR3"}


def test_sort_by_exposure_severity(obs2):
    assert obs2["exposureBySeverity"] == ["d2.CR3", "c2.CR3", "b2.CR3", "f2.CR3"]
    # 전체에서 정렬하면 노출 이상이 없는 사진은 맨 뒤 (이름순)
    assert obs2["allBySeverity"] == ["d2.CR3", "c2.CR3", "b2.CR3", "f2.CR3", "a2.CR3", "e2.CR3"]


def test_reason_filter_combines_with_tier_filter(obs2):
    # 노출로 올라온 컷 중 후보 등급은 없다 (노출은 사람이 확인 전용)
    assert obs2["exposureAndCandidate"] == ["(empty)"]


def test_badges_show_each_reason(obs2):
    b = obs2["badges"]
    assert b["a2.CR3"] == ["B컷 후보", "눈 감김"]
    assert b["b2.CR3"] == ["사람이 확인", "노출: 얼굴이 하얗게 날아감"]
    assert b["c2.CR3"] == ["사람이 확인", "눈 감김", "노출: 너무 어두움", "단체 사진"]
    assert b["d2.CR3"] == ["사람이 확인", "노출: 너무 어두움"]  # 눈 감김 배지 없음
    assert b["f2.CR3"] == ["사람이 확인", "노출: 사진이 하얗게 날아감"]


def test_exposure_detail_line_depends_on_kind(obs2):
    assert obs2["b2"][3] == "상위 1% 밝기 255 · 얼굴 날아감 60%"
    assert obs2["d2"][3] == "상위 1% 밝기 40"  # 저노출은 "날아감" 표시 없음
    assert obs2["f2"][3] == "상위 1% 밝기 240 · 사진 날아감 50%"
    assert len(obs2["a2"]) == 4  # 이름, 배지, 눈 점수, 버튼 (노출 줄 없음)


def test_eye_score_line_for_photos_without_a_face(obs2):
    assert obs2["d2"][2] == "눈 점수 없음 · 얼굴 0"
