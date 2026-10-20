import pytest

from bcut.bridge import albums as al
from bcut.bridge.albums import (
    AlbumSpec,
    album_specs,
    parse_albums,
    plan_albums,
    rules_xml,
)
from bcut.bridge.capture_one import CaptureOneBridge
from bcut.cli import main


def test_rules_xml_matches_the_format_capture_one_wrote():
    # 사람이 만든 스마트 앨범에서 읽은 규칙 (T0.5)과 같은 모양이어야 한다
    human = ('<?xml version="1.0"?><MatchOperator Kind="AND"><MatchOperator Kind="AND">'
             '<Condition Enabled="YES"><Key>IB_S_CONTENT_KEYWORDS</Key><Operator>0</Operator>'
             "<Criterion>bcut-test-kw</Criterion></Condition></MatchOperator></MatchOperator>")
    assert rules_xml(("bcut-test-kw",)) == human


def test_or_rules_match_the_format_of_a_human_made_or_album():
    # 사람이 만든 "키워드 bcut-candidate 또는 별점 0" 앨범에서 읽은 규칙 (T2.8)
    human = ('<?xml version="1.0"?><MatchOperator Kind="OR"><MatchOperator Kind="AND">'
             "<Condition Enabled=\"YES\"><Key>IB_S_CONTENT_KEYWORDS</Key><Operator>0</Operator>"
             "<Criterion>bcut-candidate</Criterion></Condition></MatchOperator>"
             '<MatchOperator Kind="AND"><Condition Enabled="YES"><Key>IB_I_BASIC_RATING</Key>'
             "<Operator>0</Operator><Criterion>0</Criterion></Condition></MatchOperator>"
             "</MatchOperator>")
    got = al.rules_from_groups(((al.has_keyword("bcut-candidate"),), (al.UNRATED,)), "OR")
    assert got == human


def test_rules_with_exclusion_uses_is_not_operator():
    xml = rules_xml((), ("bcut-candidate", "bcut-review"))
    assert xml.count("<Condition") == 2 and xml.count("<Operator>1</Operator>") == 2
    assert "<Operator>0</Operator>" not in xml
    both = rules_xml(("a",), ("b",))
    assert both.index("<Operator>0</Operator>") < both.index("<Operator>1</Operator>")


def test_rules_escape_xml_and_reject_empty():
    assert "&lt;&amp;" in rules_xml(("<&",))
    with pytest.raises(ValueError):
        rules_xml((), ())
    with pytest.raises(ValueError):
        al.rules_from_groups(((),), "AND")
    with pytest.raises(ValueError):
        al.rules_from_groups(((al.UNRATED,),), "XOR")


def test_rating_operators_are_the_verified_ones():
    assert al.UNRATED == ("IB_I_BASIC_RATING", 0, "0")
    assert al.RATED == ("IB_I_BASIC_RATING", 5, "0")  # 5 = 초과 (실기: 별점 2장 중 2장)


def test_album_specs_cover_tiers_normal_excluded_and_reasons():
    specs = {s.name: s for s in album_specs()}
    assert set(specs) == {"bcut 후보", "bcut 확인", "bcut 정상", "bcut 제외된 컷", "bcut 눈 감김",
                          "bcut 노출", "bcut 흔들림", "bcut 초점 실패"}
    # 별점이 우선: 후보·확인·사유별·제외된 컷은 모두 별점 없음 조건을 가진다
    for name, s in specs.items():
        if name != "bcut 정상":
            assert all(al.UNRATED in g for g in s.groups), name
    assert specs["bcut 후보"].groups == ((al.has_keyword("bcut-candidate"), al.UNRATED),)
    normal = specs["bcut 정상"]
    assert normal.top == "OR" and al.RATED in normal.groups[1]
    assert normal.groups[0] == (al.lacks_keyword("bcut-candidate"),
                                al.lacks_keyword("bcut-review"))
    excluded = specs["bcut 제외된 컷"]
    assert excluded.top == "OR" and len(excluded.groups) == 2
    assert album_specs("x-")[0].groups[0][0] == al.has_keyword("x-candidate")


def test_describe_is_readable():
    specs = {s.name: s for s in album_specs()}
    assert specs["bcut 후보"].describe() == "키워드 있음 bcut-candidate 그리고 별점 없음"
    assert "또는 별점 있음" in specs["bcut 정상"].describe()


def test_plan_creates_missing_keeps_existing_and_flags_changed_rules():
    specs = album_specs()
    existing = {specs[0].name: specs[0].rules,  # 같음 (공백만 달라도 같다)
                specs[1].name: "<other/>"}  # 이름만 같고 규칙이 다름
    existing[specs[0].name] = existing[specs[0].name].replace("><", "> <")
    p = plan_albums(existing, specs)
    assert p.existing == [specs[0].name, specs[1].name]
    assert p.rule_mismatch == [specs[1].name]
    assert [s.name for s in p.to_create] == [s.name for s in specs[2:]]


def test_plan_is_empty_when_everything_exists():
    specs = album_specs()
    p = plan_albums({s.name: s.rules for s in specs}, specs)
    assert p.to_create == [] and p.rule_mismatch == []


def test_parse_albums():
    assert parse_albums("a\t<x/>\nb\t<y/>\n\nnotab\n") == {"a": "<x/>", "b": "<y/>"}


def test_create_script_never_overwrites_and_checks_catalog():
    s = al.CREATE_ALBUM_SCRIPT
    assert 'if exists collection albumName of doc then return "exists"' in s
    assert "wrong catalog" in s and "delete" not in s
    assert "delete" not in al.LIST_ALBUMS_SCRIPT and "make new" not in al.LIST_ALBUMS_SCRIPT


def test_create_album_sends_name_and_rules_as_arguments():
    calls = []
    b = CaptureOneBridge("bcut-test", run=lambda s, a, **k: calls.append((s, list(a))) or "created")
    spec = AlbumSpec("bcut 후보", ((al.has_keyword("bcut-candidate"),),))
    assert al.create_album(b, spec) == "created"
    assert calls[0][1] == ["bcut-test", "bcut 후보", spec.rules]
    assert spec.rules not in calls[0][0]  # 규칙은 스크립트 글자가 아니라 인자로 간다


# ---- CLI -------------------------------------------------------------------------------

class FakeAlbumBridge:
    catalog_name = "bcut-test"

    def __init__(self, existing=None):
        self.albums = dict(existing or {})
        self.created = []

    def call(self, script, *extra):
        if script == al.LIST_ALBUMS_SCRIPT:
            return "".join(f"{n}\t{r}\n" for n, r in self.albums.items())
        name, rules = extra
        if name in self.albums:
            return "exists"
        self.albums[name] = rules
        self.created.append(name)
        return "created"


def test_cli_albums_preview_then_commit_then_idempotent(monkeypatch, capsys):
    import bcut.bridge.capture_one as co
    fake = FakeAlbumBridge()
    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: fake)
    assert main(["albums", "--catalog", "bcut-test"]) == 0
    out = capsys.readouterr().out
    assert "미리보기" in out and "만들 앨범: bcut 후보" in out and fake.created == []
    assert main(["albums", "--catalog", "bcut-test", "--commit"]) == 0
    assert len(fake.created) == 8 and "created" in capsys.readouterr().out
    assert main(["albums", "--catalog", "bcut-test", "--commit"]) == 0  # 다시 실행해도 그대로
    out = capsys.readouterr().out
    assert len(fake.created) == 8 and out.count("이미 있음") == 8


def test_cli_albums_reports_wrong_catalog(monkeypatch, capsys):
    import bcut.bridge.capture_one as co
    from bcut.bridge.osascript import AppleScriptError

    class Bad:
        catalog_name = "x"

        def call(self, *a):
            raise AppleScriptError("wrong catalog: 실제작업")

    monkeypatch.setattr(co, "CaptureOneBridge", lambda name, **k: Bad())
    assert main(["albums", "--catalog", "bcut-test", "--commit"]) == 1
    assert "지정한 것과 다르다" in capsys.readouterr().err


def test_unverified_operators_keys_and_values_are_refused_before_reaching_capture_one():
    # 잘못된 연산자는 Capture One에 깨진 컬렉션을 남긴다 -> 보내기 전에 막는다
    for bad in (("IB_I_BASIC_RATING", 6, "0"), ("IB_I_BASIC_RATING", 7, "0"),
                ("IB_S_CONTENT_KEYWORDS", 2, "x"), ("IB_UNKNOWN", 0, "x"),
                ("IB_I_BASIC_RATING", 0, "9"), ("IB_I_BASIC_RATING", 0, "abc"),
                ("IB_S_CONTENT_KEYWORDS", 0, " ")):
        with pytest.raises(ValueError):
            al.rules_from_groups(((bad,),))
    # 확인된 조합은 통과한다
    for op in (0, 1, 2, 3, 4, 5):
        assert "Operator>" in al.rules_from_groups((((al.KEY_RATING, op, "0"),),))


def test_all_default_albums_use_only_verified_conditions():
    for spec in album_specs():
        assert spec.rules.startswith("<?xml")  # 생성 중 ValueError가 나지 않는다
