"""labels_raw.csv(export_labels.py 결과)를 최종 라벨 형식 labels.csv로 바꾼다.

색 -> 라벨 규칙은 docs/labeling-guide.md 2장과 같다.

사용법:
    python3 tools/build_labels.py eval/labels_raw.csv \
        --source "260212 EVENT_B STRX SJ" --out eval/labels.csv
"""
import argparse
import csv
from collections import Counter
from pathlib import Path

# 색 이름 -> (label, reason)
COLOR_TO_LABEL = {
    "red": ("B", "eyes_closed"),
    "orange": ("B", "blur"),
    "yellow": ("B", "out_of_focus"),
    "green": ("B", "exposure"),
    "blue": ("OK_EXPR", ""),
    "purple": ("UNSURE", ""),
    "": ("OK", ""),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_csv", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", type=Path, default=Path("eval/labels.csv"))
    parser.add_argument(
        "--first", help="이 파일명부터 (구간 라벨링일 때). 구간 밖 컷은 라벨에서 뺀다"
    )
    parser.add_argument("--last", help="이 파일명까지")
    args = parser.parse_args()

    rows, unknown = [], Counter()
    with args.raw_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if args.first and r["file"] < args.first:
                continue
            if args.last and r["file"] > args.last:
                continue
            color = r["color_name"]
            if color not in COLOR_TO_LABEL:
                unknown[color] += 1
                label, reason = "UNSURE", ""
            else:
                label, reason = COLOR_TO_LABEL[color]
            rows.append({
                "file": r["file"],
                "label": label,
                "reason": reason,
                "is_final_a": "1" if r["rating"] == "5" else "0",
                "source": args.source,
            })

    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "label", "reason", "is_final_a", "source"])
        w.writeheader()
        w.writerows(rows)

    counts = Counter(r["label"] for r in rows)
    print(f"{len(rows)}장 -> {args.out}")
    for label in ("B", "OK", "OK_EXPR", "UNSURE"):
        print(f"  {label}: {counts.get(label, 0)}")
    conflicts = [r["file"] for r in rows if r["is_final_a"] == "1" and r["label"] == "B"]
    print(f"  최종 선택(별점 5)인데 B로 표시된 컷: {len(conflicts)}장 {conflicts}")
    if unknown:
        print(f"  알 수 없는 색(UNSURE로 처리): {dict(unknown)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
