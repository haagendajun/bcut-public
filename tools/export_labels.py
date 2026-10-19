"""Capture One에서 표시한 컬러 태그와 별점을 읽어 CSV로 내보낸다.

읽기 전용. 사진, 설정 파일(.cos), 카탈로그를 수정하지 않는다.

- 컬러 태그: 카탈로그 파일(.cocatalogdb)의 ZVARIANTMETADATA.ZCOLOR_TAG_INDEX
  (파일럿으로 확인: 카탈로그 모드에서는 폴더의 .cos 파일에 태그가 저장되지 않는다)
- 별점: 카탈로그에는 .cos의 별점이 가져와지지 않는다(파일럿으로 확인). 그래서 별점은
  행사 폴더의 CaptureOne/Settings*/*.cos 에서 읽는다.

사용법 (Capture One을 종료한 뒤 실행):
    python3 tools/export_labels.py <행사 폴더> --catalog <카탈로그.cocatalog> [--out labels_raw.csv]
"""
import argparse
import csv
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# 컬러 태그 번호와 색 이름. 1~5는 파일럿에서 사용자가 붙인 순서로 확인했다
# (7652 빨강=1, 7653 주황=2, 7654 노랑=3, 7655 초록=4, 7658 파랑=5, 2026-10-19).
# 6(분홍), 7(보라)은 Capture One 기본 순서를 가정한 것이다. 보라를 "애매"로 쓸 때
# 본 작업 후 한 장으로 확인한다.
COLOR_NAMES: dict[int, str] = {
    1: "red", 2: "orange", 3: "yellow", 4: "green", 5: "blue", 6: "pink", 7: "purple",
}

CATALOG_QUERY = """
SELECT i.ZIMAGEFILENAME, MAX(COALESCE(m.ZCOLOR_TAG_INDEX, 0))
FROM ZIMAGE i
JOIN ZVARIANT v ON v.ZIMAGE = i.Z_PK
JOIN ZVARIANTLAYER l ON (l.Z_PK = v.ZADJUSTMENTLAYER
                         OR l.Z_PK = v.ZDEFAULTLAYER
                         OR l.Z_PK = v.ZCOMBINEDSETTINGS)
JOIN ZVARIANTMETADATA m ON m.ZLAYER = l.Z_PK
GROUP BY i.ZIMAGEFILENAME
"""


def read_catalog_colors(catalog: Path) -> dict[str, int]:
    db_files = sorted(catalog.glob("*.cocatalogdb"))
    if not db_files:
        raise FileNotFoundError(f"{catalog} 안에 .cocatalogdb가 없다")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "catalog.db"
        shutil.copy2(db_files[0], copy)
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            return {name: int(color) for name, color in conn.execute(CATALOG_QUERY)}
        finally:
            conn.close()


def read_cos_rating(cos_path: Path) -> str:
    """AL(현재 적용 설정)이 있으면 AL 값을, 없으면 DL(기본 설정) 값을 쓴다."""
    root = ET.parse(cos_path).getroot()
    values: dict[str, str] = {}
    for layer in ("DL", "AL"):
        for node in root.iter(layer):
            for e in node.findall("E"):
                if e.get("K") == "Basic_Rating":
                    values[layer] = e.get("V", "")
    return values.get("AL", values.get("DL", ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event_folder", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("labels_raw.csv"))
    args = parser.parse_args()

    colors = read_catalog_colors(args.catalog)

    ratings: dict[str, str] = {}
    for d in sorted(args.event_folder.glob("CaptureOne/Settings*")):
        for cos in sorted(d.glob("*.cos")):
            ratings[cos.name.removesuffix(".cos")] = read_cos_rating(cos)

    files = sorted(set(colors) | set(ratings))
    if not files:
        print("읽을 수 있는 파일이 없다.", file=sys.stderr)
        return 1

    rows = []
    for name in files:
        idx = colors.get(name, 0)
        rows.append({
            "file": name,
            "rating": ratings.get(name, ""),
            "color_tag_index": idx,
            "color_name": COLOR_NAMES.get(idx, "") if idx else "",
        })

    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "rating", "color_tag_index", "color_name"])
        writer.writeheader()
        writer.writerows(rows)

    rated5 = sum(1 for r in rows if r["rating"] == "5")
    tagged = sum(1 for r in rows if r["color_tag_index"])
    print(f"{len(rows)}장 읽음. 별점 5: {rated5}장, 컬러 태그 있음: {tagged}장 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
