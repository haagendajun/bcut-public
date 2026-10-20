from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from bcut import scan as scan_module
from bcut.cli import main
from bcut.scan import (
    ALL_STATUSES,
    EXPOSURE,
    EYES_CLOSED,
    FLAGGED_STATUSES,
    PhotoResult,
    analyze_photo,
    combine_status,
    count_by_reason,
    count_by_status,
    list_photos,
    scan_folder,
)


def result(name, status="normal", score=0.3, note=None, thumb=None):
    return PhotoResult(file=name, status=status, score=score, note=note, face_count=1,
                       faces_considered=1, eye_width_frac=0.01, thumbnail=thumb)


def snapshot(folder: Path):
    return sorted((str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in folder.rglob("*"))


def test_list_photos_only_cr3_sorted_and_not_hidden(tmp_path):
    for name in ("b.CR3", "a.cr3", "c.jpg", ".hidden.CR3", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "z.CR3").write_bytes(b"x")  # 하위 폴더는 보지 않는다
    assert [p.name for p in list_photos(tmp_path)] == ["a.cr3", "b.CR3"]


def test_scan_folder_returns_results_in_file_order_and_passes_options(tmp_path):
    for name in ("b.CR3", "a.CR3", "c.CR3"):
        (tmp_path / name).write_bytes(b"x")
    seen = {}

    def fake(path, thumb_width, thumb_statuses, thresholds, **kw):
        seen[Path(path).name] = (thumb_width, thumb_statuses, thresholds, kw)
        return result(Path(path).name)

    out = scan_folder(tmp_path, workers=1, thumb_width=123, thumb_statuses=FLAGGED_STATUSES,
                      exposure_tier="candidate", analyze=fake)
    assert [r.file for r in out] == ["a.CR3", "b.CR3", "c.CR3"]
    assert seen["a.CR3"][0] == 123 and seen["a.CR3"][1] == FLAGGED_STATUSES
    assert seen["a.CR3"][3]["exposure_tier"] == "candidate"  # 노출 설정도 넘어간다
    assert "exposure_thresholds" in seen["a.CR3"][3]


def test_scan_folder_reports_progress(tmp_path):
    for name in ("a.CR3", "b.CR3"):
        (tmp_path / name).write_bytes(b"x")
    calls = []
    scan_folder(tmp_path, workers=1, analyze=lambda p, **k: result(Path(p).name),
                progress=lambda done, total: calls.append((done, total)))
    assert calls == [(1, 2), (2, 2)]


def test_scan_folder_never_writes_into_the_event_folder(tmp_path):
    for name in ("a.CR3", "b.CR3", "c.CR3", "d.CR3", "e.CR3"):
        (tmp_path / name).write_bytes(b"not a raw file")
    before = snapshot(tmp_path)
    scan_folder(tmp_path, workers=1)  # 진짜 분석기: 손상 파일이라 모두 read_error
    assert snapshot(tmp_path) == before


def test_corrupt_file_becomes_read_error_review_not_a_crash(tmp_path):
    bad = tmp_path / "bad.CR3"
    bad.write_bytes(b"this is not a raw file")
    r = analyze_photo(bad)
    assert (r.status, r.note) == ("review", "read_error")
    assert r.error and r.thumbnail is None
    assert r.file == "bad.CR3"


def test_one_corrupt_file_does_not_stop_the_scan(tmp_path):
    for name in ("a.CR3", "b.CR3"):
        (tmp_path / name).write_bytes(b"junk")
    out = scan_folder(tmp_path, workers=1)
    assert [r.note for r in out] == ["read_error", "read_error"]


def test_count_by_status_includes_all_keys():
    counts = count_by_status([result("a", "candidate"), result("b", "normal"),
                              result("c", "normal")])
    assert counts == {"candidate": 1, "review": 0, "normal": 2, "no_face": 0, "unscorable": 0}


def test_status_sets():
    assert FLAGGED_STATUSES < ALL_STATUSES
    assert "normal" not in FLAGGED_STATUSES


def test_cli_scan_writes_only_to_out_dir(tmp_path, monkeypatch, capsys):
    event = tmp_path / "event"
    event.mkdir()
    for name in ("a.CR3", "b.CR3"):
        (event / name).write_bytes(b"x")
    out = tmp_path / "out"
    before = snapshot(event)

    fake_results = [result("a.CR3", "candidate", 0.1, thumb=b"\xff\xd8\xff"),
                    result("b.CR3", "normal", 0.3)]
    monkeypatch.setattr(scan_module, "scan_folder", lambda *a, **k: fake_results)

    assert main(["scan", "--folder", str(event), "--out", str(out)]) == 0
    assert snapshot(event) == before  # 행사 폴더는 그대로
    names = sorted(p.name for p in out.iterdir())
    assert names == ["bcut-log.json", "bcut-report.csv", "bcut-report.html"]
    printed = capsys.readouterr().out
    assert "B컷 후보 1" in printed and "썸네일이 있다" in printed


# ---- 사유 합치기 (눈 감김 + 노출) ------------------------------------------------


@pytest.mark.parametrize(
    ("eyes", "flagged", "tier", "expected"),
    [
        ("candidate", False, "review", "candidate"),
        ("candidate", True, "review", "candidate"),  # 노출은 후보를 낮추지 않는다
        ("review", False, "review", "review"),
        ("review", True, "review", "review"),
        ("normal", False, "review", "normal"),
        ("normal", True, "review", "review"),  # 노출만 걸려도 사람이 확인
        ("no_face", True, "review", "review"),
        ("no_face", False, "review", "no_face"),  # 얼굴 없음은 그대로
        ("unscorable", False, "review", "unscorable"),
        ("unscorable", True, "review", "review"),
        ("normal", True, "candidate", "candidate"),  # 노출을 candidate로 승급한 경우
        ("no_face", True, "candidate", "candidate"),
    ],
)
def test_combine_status(eyes, flagged, tier, expected):
    assert combine_status(eyes, flagged, tier) == expected


def test_reasons_come_from_each_judgement():
    both = PhotoResult("a", "candidate", 0.1, None, 1, 1, 0.01, None, eyes_status="candidate",
                       exposure_kind="over_face")
    assert both.reasons == (EYES_CLOSED, EXPOSURE)
    exp_only = PhotoResult("b", "review", 0.3, None, 1, 1, 0.01, None, eyes_status="normal",
                           exposure_kind="under")
    assert exp_only.reasons == (EXPOSURE,)
    eyes_only = PhotoResult("c", "review", 0.15, "group", 2, 2, 0.01, None, eyes_status="review")
    assert eyes_only.reasons == (EYES_CLOSED,)
    clean = PhotoResult("d", "normal", 0.3, None, 1, 1, 0.01, None, eyes_status="normal")
    assert clean.reasons == ()


def test_read_error_is_not_a_reason():
    bad = PhotoResult("x", "review", None, "read_error", 0, 0, None, None, eyes_status="review")
    assert bad.reasons == ()


def test_reasons_fall_back_to_status_for_eyes_only_results():
    old_style = result("a", "candidate", 0.1)  # eyes_status를 안 준 눈 감김만의 결과
    assert old_style.reasons == (EYES_CLOSED,)
    assert result("b", "normal").reasons == ()


def test_count_by_reason():
    rs = [
        PhotoResult("a", "candidate", 0.1, None, 1, 1, 0.01, None, eyes_status="candidate"),
        PhotoResult("b", "review", 0.3, None, 1, 1, 0.01, None, eyes_status="normal",
                    exposure_kind="under"),
        PhotoResult("c", "candidate", 0.1, None, 1, 1, 0.01, None, eyes_status="candidate",
                    exposure_kind="over_face"),
        PhotoResult("d", "normal", 0.3, None, 1, 1, 0.01, None, eyes_status="normal"),
    ]
    assert count_by_reason(rs) == {"eyes_closed": 2, "exposure": 2, "blur": 0, "out_of_focus": 0,
                                   "both": 1}


def test_count_by_reason_includes_sharpness_reasons():
    rs = [
        PhotoResult("a", "review", 0.3, None, 1, 1, 0.01, None, eyes_status="normal",
                    sharpness_kind="blur"),
        PhotoResult("b", "candidate", 0.1, None, 1, 1, 0.01, None, eyes_status="candidate",
                    sharpness_kind="out_of_focus"),
    ]
    assert rs[0].reasons == ("blur",) and rs[1].reasons == ("eyes_closed", "out_of_focus")
    assert count_by_reason(rs) == {"eyes_closed": 1, "exposure": 0, "blur": 1, "out_of_focus": 1,
                                   "both": 1}


# ---- 사진 한 장 판정의 통합 동작 (가짜 사진·가짜 얼굴로, 실제 파일 없이) ---------------

W, H = 640, 480


def _face(eye_ratio: float):
    from bcut.detect.eyes import EyeOpenness
    from bcut.detect.types import Eye, Face
    eye = Eye(openness=EyeOpenness(ratio=eye_ratio, width_px=16.0), pupil=None, points=())
    # 이미지 가운데: 폭 160px(0.25), 높이 180px(0.375). 원점은 왼쪽 아래
    return Face(face_width_px=160, face_area=0.25 * 0.375, yaw_deg=0, roll_deg=0, confidence=1.0,
                left=eye, right=eye, bbox=(0.375, 0.3125, 0.25, 0.375), image_width_px=W)


def _image(base=120, blown_face=False, top_bright=True):
    arr = np.full((H, W, 3), base, dtype=np.uint8)
    if top_bright:
        arr[:20, :, :] = 240  # 밝은 하늘이 있는 보통 사진
    if blown_face:
        arr[150:330, 240:400, :] = 255
    return Image.fromarray(arr)


def _patch(monkeypatch, image, faces):
    from bcut.imageio.embedded import LoadedImage
    monkeypatch.setattr(scan_module, "read_embedded_jpeg",
                        lambda p, width=0: LoadedImage(image=image, full_width=W, full_height=H))
    monkeypatch.setattr(scan_module, "detect_faces", lambda im: faces)


def test_normal_photo_is_normal_with_no_reasons(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.30)])
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "normal" and r.reasons == () and r.exposure_kind is None
    assert r.eyes_status == "normal" and r.exposure_p99 is not None


def test_closed_eyes_only_is_candidate_for_eyes(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.08)])
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "candidate" and r.reasons == (EYES_CLOSED,)
    assert r.exposure_kind is None


def test_blown_face_only_is_review_for_exposure(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(blown_face=True), [_face(0.30)])
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "review" and r.reasons == (EXPOSURE,)
    assert r.exposure_kind == "over_face" and r.eyes_status == "normal"
    assert r.exposure_face_hi >= 0.9 and 0.9 <= r.exposure_severity <= 1.0
    assert r.thumbnail and r.thumbnail.startswith(b"\xff\xd8")


def test_closed_eyes_and_blown_face_report_both_reasons(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(blown_face=True), [_face(0.08)])
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "candidate"  # 눈 감김이 후보라 사진도 후보
    assert r.reasons == (EYES_CLOSED, EXPOSURE)


def test_dark_photo_without_face_is_review_for_exposure(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(base=30, top_bright=False), [])
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "review" and r.eyes_status == "no_face"
    assert r.exposure_kind == "under" and r.reasons == (EXPOSURE,)
    assert r.face_count == 0 and r.score is None


def test_no_face_normal_exposure_stays_no_face(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [])
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "no_face" and r.reasons == ()


def test_exposure_tier_can_promote_to_candidate(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(blown_face=True), [_face(0.30)])
    assert analyze_photo(tmp_path / "a.CR3", exposure_tier="candidate").status == "candidate"


def test_thumbnail_is_skipped_for_statuses_not_requested(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.30)])
    r = analyze_photo(tmp_path / "a.CR3", thumb_statuses=FLAGGED_STATUSES)
    assert r.status == "normal" and r.thumbnail is None
    _patch(monkeypatch, _image(blown_face=True), [_face(0.30)])
    assert analyze_photo(tmp_path / "a.CR3", thumb_statuses=FLAGGED_STATUSES).thumbnail


def test_blurry_photo_is_review_for_sharpness_only(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.30)])
    monkeypatch.setattr(scan_module, "best_tile_blur", lambda gray: 0.7)
    r = analyze_photo(tmp_path / "a.CR3")
    assert r.status == "review" and r.reasons == ("blur",) and r.sharpness_kind == "blur"
    assert r.eyes_status == "normal" and r.sharpness_severity == pytest.approx(0.7)


def test_sharpness_never_makes_candidate_by_default():
    assert combine_status("normal", False, "review", True, "review") == "review"
    assert combine_status("normal", False, "review", True, "candidate") == "candidate"
    assert combine_status("candidate", False, "review", True, "review") == "candidate"


def test_eyes_tier_review_demotes_candidate(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.05)])
    r = analyze_photo(tmp_path / "a.CR3", eyes_tier="review")
    assert r.status == "review" and r.eyes_status == "review" and r.reasons == (EYES_CLOSED,)
    assert analyze_photo(tmp_path / "a.CR3").status == "candidate"


def test_sharpness_tier_is_chosen_per_kind(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.30)])
    monkeypatch.setattr(scan_module, "best_tile_blur", lambda gray: 0.7)
    tiers = {"blur": "candidate", "out_of_focus": "review"}
    assert analyze_photo(tmp_path / "a.CR3", sharpness_tiers=tiers).status == "candidate"
    assert analyze_photo(tmp_path / "a.CR3", sharpness_tiers={"blur": "review"}).status == "review"


# ---- 확신도 ------------------------------------------------------------------------

def test_confidence_none_when_nothing_flagged(monkeypatch, tmp_path):
    _patch(monkeypatch, _image(), [_face(0.30)])
    assert analyze_photo(tmp_path / "a.CR3").confidence is None


def test_confidence_validated_reason_ranks_above_review_only(monkeypatch, tmp_path):
    from bcut.scan import confidence_of
    assert confidence_of([("candidate", 0.0)]) == 0.5
    assert confidence_of([("review", 1.0)]) == 0.5  # review 최대 = candidate 최소
    assert confidence_of([("candidate", 1.0), ("review", 1.0)]) == 1.0
    assert confidence_of([]) is None
    _patch(monkeypatch, _image(), [_face(0.02)])
    deep = analyze_photo(tmp_path / "a.CR3").confidence
    _patch(monkeypatch, _image(), [_face(0.13)])
    edge = analyze_photo(tmp_path / "a.CR3").confidence
    assert deep > edge >= 0.5


def test_eyes_strength_bands():
    from bcut.scan import eyes_strength
    from bcut.score.eyes import EyesThresholds
    t = EyesThresholds()
    assert eyes_strength(0.0, "candidate", t) == 1.0
    assert eyes_strength(t.candidate_max, "candidate", t) == 0.0
    assert eyes_strength(t.candidate_max, "review", t) == 1.0
    assert eyes_strength(t.review_max, "review", t) == 0.0
    assert eyes_strength(None, "review", t) == 0.0
