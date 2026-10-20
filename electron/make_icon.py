"""bcut 앱 아이콘(1024px PNG): 파란 그라데이션 둥근 사각형 + 흰 폴더와 체크 표시. 사용: python make_icon.py out.png"""
import sys

from PIL import Image, ImageDraw

N, SS = 1024, 2
C0, C1 = (0x4F, 0x9B, 0xE0), (0x18, 0x5F, 0xA5)   # 그라데이션 시작/끝 (화면의 강조색)
W = N * SS


def s(v):
    return v * SS


def main(out: str) -> None:
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    grad = Image.new("RGBA", (W, W))
    gp = grad.load()
    for y in range(W):
        t = y / (W - 1)
        c = tuple(int(C0[i] + (C1[i] - C0[i]) * t) for i in range(3)) + (255,)
        for x in range(W):
            gp[x, y] = c
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle((s(64), s(64), s(960), s(960)), radius=s(200), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # 폴더: 뒤판 + 탭 + 앞판
    d.rounded_rectangle((s(220), s(330), s(804), s(780)), radius=s(46), fill=(255, 255, 255, 235))
    d.rounded_rectangle((s(220), s(270), s(470), s(380)), radius=s(40), fill=(255, 255, 255, 235))
    d.rounded_rectangle((s(220), s(400), s(804), s(780)), radius=s(46), fill=(255, 255, 255, 255))
    # 체크 표시
    pts = [(s(380), s(600)), (s(480), s(695)), (s(655), s(500))]
    for a, b in zip(pts, pts[1:]):
        d.line((a, b), fill=(0x18, 0x5F, 0xA5, 255), width=s(54))
    for p in pts:
        r = s(27)
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=(0x18, 0x5F, 0xA5, 255))
    img.resize((N, N), Image.LANCZOS).save(out)


if __name__ == "__main__":
    main(sys.argv[1])
