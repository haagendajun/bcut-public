import csv
import json
import re

import pytest

from bcut.report.csv_report import COLUMNS, reason_for, write_csv
from bcut.report.html_report import render_html
from bcut.scan import PhotoResult
from bcut.score.eyes import EyesThresholds

JPEG = b"\xff\xd8\xff\xe0fakejpeg"


def r(name, status="normal", score=0.3, note=None, faces=1, considered=1, thumb=None, error=None):
    return PhotoResult(file=name, status=status, score=score, note=note, face_count=faces,
                       faces_considered=considered, eye_width_frac=0.0102, thumbnail=thumb,
                       error=error)


SAMPLE = [
    r("a.CR3", "candidate", 0.0814, thumb=JPEG),
    r("b.CR3", "review", 0.15, note="group", faces=3, considered=2, thumb=JPEG),
    r("c.CR3", "normal", 0.3),
    r("d.CR3", "no_face", None, faces=0, considered=0),
    r("e.CR3", "review", None, note="read_error", faces=0, considered=0, error="LibRawError: x"),
]


def html(results=SAMPLE, **kw):
    kw.setdefault("folder_name", "행사 A")
    kw.setdefault("generated_at", "2026-10-19 18:00")
    return render_html(results, **kw)


def payload(text: str) -> dict:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.S)
    assert m, "데이터 블록이 없다"
    return json.loads(m.group(1))


# ---- HTML ------------------------------------------------------------------


def test_html_is_self_contained_with_no_external_resources():
    text = html()
    for banned in ("http://", "https://", "<link", "<script src", "src=\"//", "@import",
                   "fetch(", "XMLHttpRequest", "WebSocket", "import(", "sendBeacon", "<iframe"):
        assert banned not in text, banned
    assert "url(" not in text  # CSS가 외부 이미지를 부르지 않는다


def test_html_payload_round_trips():
    data = payload(html())
    assert data["folder"] == "행사 A"
    assert [p["f"] for p in data["photos"]] == ["a.CR3", "b.CR3", "c.CR3", "d.CR3", "e.CR3"]
    a = data["photos"][0]
    assert (a["st"], a["sc"], a["nt"], a["fc"]) == ("candidate", 0.0814, None, 1)
    b = data["photos"][1]
    assert (b["nt"], b["fc"], b["cc"]) == ("group", 3, 2)
    assert data["photos"][4]["er"] == "LibRawError: x"


def test_thumbnails_are_embedded_as_data_uris_only_when_present():
    photos = payload(html())["photos"]
    assert photos[0]["th"].startswith("data:image/jpeg;base64,")
    assert photos[2]["th"] is None


def test_thresholds_are_in_the_payload():
    data = payload(html(thresholds=EyesThresholds(candidate_max=0.1, review_max=0.2)))
    assert data["thresholds"]["candidate"] == 0.1 and data["thresholds"]["review"] == 0.2


def test_hostile_file_names_cannot_break_out_of_the_data_block():
    evil = 'x</script><img src=x onerror=alert(1)>"&.CR3'
    text = html([r(evil, "candidate", 0.1)])
    assert "</script><img" not in text  # 데이터 블록을 닫지 못한다
    assert text.count("</script>") == 2  # 데이터 블록과 코드 블록, 이 둘뿐이다
    assert payload(text)["photos"][0]["f"] == evil  # 값은 그대로 복원된다


def test_title_is_escaped():
    text = html(title="<b>제목</b> & 끝")
    assert "<title>&lt;b&gt;제목&lt;/b&gt; &amp; 끝</title>" in text


def test_default_title_has_event_name_and_first_cut_wording():
    text = html(folder_name="260223 EVENT_A SJ 구간")
    assert "<title>260223 EVENT_A SJ 구간 · 1차 컷 리포트</title>" in text
    assert payload(text)["title"] == "260223 EVENT_A SJ 구간 · 1차 컷 리포트"


def test_reports_of_different_events_have_different_titles():
    a = payload(html(folder_name="EVENT_A"))["title"]
    b = payload(html(folder_name="EVENT_B"))["title"]
    assert a != b


def test_title_does_not_claim_to_pick_the_best_cuts():
    text = html()
    assert "A컷 판정" not in text and "B컷 후보 리포트" not in text
    assert "1차 컷" in text


def test_scope_is_in_payload_and_can_be_extended():
    assert payload(html())["scope"] == "눈 감김·노출 판정"
    assert payload(html(scope="눈 감김·흔들림 판정"))["scope"] == "눈 감김·흔들림 판정"


def test_hostile_folder_name_is_escaped_in_the_title_tag():
    text = html(folder_name="</title><script>alert(1)</script>")
    assert "<title></title><script>" not in text
    assert "&lt;/title&gt;" in text


def test_file_names_are_rendered_as_text_not_html():
    # 화면 코드는 textContent만 쓴다. innerHTML을 쓰면 파일 이름이 HTML로 해석될 수 있다
    text = html()
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text
    assert "document.write" not in text and "eval(" not in text


def test_html_has_privacy_banner_and_filters():
    text = html()
    assert "다른 사람에게 보내지 마세요" in text
    for needle in ("B컷 후보", "사람이 확인", "가장 감긴 순", "살리기", "bcut-saved"):
        assert needle in text


def test_empty_results_still_render():
    data = payload(html([]))
    assert data["photos"] == []


# ---- CSV -------------------------------------------------------------------


def test_csv_has_bom_columns_and_rows(tmp_path):
    path = tmp_path / "bcut-report.csv"
    write_csv(SAMPLE, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # 엑셀에서 한글이 깨지지 않게 BOM
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    assert list(rows[0].keys()) == COLUMNS
    assert len(rows) == 5
    assert rows[0]["file"] == "a.CR3" and rows[0]["status"] == "candidate"
    assert rows[0]["score"] == "0.0814" and rows[0]["reason"] == "eyes_closed"
    assert rows[1]["note"] == "group" and rows[1]["faces_considered"] == "2"
    assert rows[3]["score"] == "" and rows[3]["reason"] == ""
    assert rows[4]["error"] == "LibRawError: x"


@pytest.mark.parametrize(
    ("status", "note", "expected"),
    [("candidate", None, "eyes_closed"), ("review", "group", "eyes_closed"),
     ("review", "small_eye", "eyes_closed"), ("review", "read_error", ""),
     ("normal", None, ""), ("no_face", None, ""), ("unscorable", None, "")],
)
def test_reason_mapping(status, note, expected):
    assert reason_for(r("x", status, 0.1, note=note)) == expected


# ---- 노출 사유 (눈 감김 + 노출) -----------------------------------------------------


def rx(name, status, eyes_status, score, exposure_kind=None, p99=None, face_hi=None, global_hi=None,
       severity=None, note=None, faces=1):
    return PhotoResult(file=name, status=status, score=score, note=note, face_count=faces,
                       faces_considered=faces, eye_width_frac=0.01, thumbnail=None,
                       eyes_status=eyes_status, exposure_kind=exposure_kind, exposure_p99=p99,
                       exposure_face_hi=face_hi, exposure_global_hi=global_hi,
                       exposure_severity=severity)


EXPOSURE_SAMPLE = [
    rx("a.CR3", "candidate", "candidate", 0.08),
    rx("b.CR3", "review", "normal", 0.30, "over_face", 255.0, 0.6, 0.1, 0.6),
    rx("c.CR3", "review", "review", 0.15, "under", 90.0, 0.0, 0.0, 0.647, note="group", faces=3),
]


def test_payload_has_reason_and_exposure_fields():
    photos = payload(html(EXPOSURE_SAMPLE))["photos"]
    assert photos[0]["rs"] == ["eyes_closed"] and photos[0]["xk"] is None
    assert photos[1]["rs"] == ["exposure"] and photos[1]["es"] == "normal"
    assert (photos[1]["xk"], photos[1]["xp"], photos[1]["xf"], photos[1]["xs"]) == (
        "over_face", 255.0, 0.6, 0.6)
    assert photos[2]["rs"] == ["eyes_closed", "exposure"] and photos[2]["xk"] == "under"


def test_payload_has_exposure_thresholds():
    from bcut.score.exposure import ExposureThresholds
    data = payload(html(exposure_thresholds=ExposureThresholds(face_hi_frac=0.3, dark_p99=100)))
    assert data["thresholds"]["exposureFaceHi"] == 0.3
    assert data["thresholds"]["exposureDarkP99"] == 100


def test_html_has_reason_filter_and_exposure_sort():
    text = html(EXPOSURE_SAMPLE)
    for needle in ("판정 종류", "노출 이상이 심한 순", "눈 감김", "노출"):
        assert needle in text


def test_csv_has_exposure_columns_and_joined_reasons(tmp_path):
    path = tmp_path / "bcut-report.csv"
    write_csv(EXPOSURE_SAMPLE, path)
    rows = list(csv.DictReader(path.read_bytes().decode("utf-8-sig").splitlines()))
    assert list(rows[0].keys()) == COLUMNS
    for col in ("exposure", "exposure_p99", "exposure_face_hi", "exposure_global_hi"):
        assert col in COLUMNS
    assert rows[0]["reason"] == "eyes_closed" and rows[0]["exposure"] == ""
    assert rows[1]["reason"] == "exposure" and rows[1]["exposure"] == "over_face"
    assert rows[1]["exposure_p99"] == "255.0" and rows[1]["exposure_face_hi"] == "0.6000"
    assert rows[2]["reason"] == "eyes_closed;exposure"  # 두 사유가 함께 걸림
    assert rows[2]["note"] == "group" and rows[2]["exposure"] == "under"


def test_reason_for_joins_reasons():
    assert reason_for(EXPOSURE_SAMPLE[2]) == "eyes_closed;exposure"
    assert reason_for(EXPOSURE_SAMPLE[1]) == "exposure"
