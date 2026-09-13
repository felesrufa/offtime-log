#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PWA 用アイコン(PNG)を外部ライブラリなしで生成する。

    python tools/make_icons.py

docs/icon-180.png (iOS ホーム画面用), icon-192.png, icon-512.png を書き出す。
絵柄: 濃い青緑の角丸背景に、白い U 字と小さな凹み。
"""
import math
import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "docs"
BG = (15, 118, 110)      # #0f766e
FG = (255, 255, 255)
SIZES = [180, 192, 512]
SUPERSAMPLE = 3


def coverage(px, py, n):
    """ピクセル中心 (px,py) が白い図形の内側なら 1.0、外なら 0.0（n = キャンバス幅）。"""
    # 座標を 0..1 に正規化
    x = px / n
    y = py / n
    cx, cy = 0.5, 0.44          # U 字の円弧の中心
    outer, inner = 0.34, 0.20   # 円弧の外径・内径
    top = cy - 0.14             # U 字の縦棒の上端
    dx, dy = x - cx, y - cy
    r = math.hypot(dx, dy)

    in_shape = False
    if y >= cy:
        # 下半分は円弧リング
        in_shape = inner <= r <= outer
    else:
        # 上半分は左右の縦棒
        in_shape = (inner <= abs(dx) <= outer) and (y >= top)

    if not in_shape:
        return 0.0

    # 歯を模した凹み: リングの内側寄りに小さな半円のくぼみを並べる
    mid = (inner + outer) / 2
    for k in range(-2, 3):
        ang = math.pi / 2 + k * 0.42  # 下側中心から左右へ
        tx, ty = cx + mid * math.cos(ang), cy + mid * math.sin(ang)
        if math.hypot(x - tx, y - ty) < 0.028:
            return 0.35  # 薄く抜く（完全には抜かない）
    for sx in (-1, 1):
        tx, ty = cx + sx * mid, top + 0.05
        if math.hypot(x - tx, y - ty) < 0.028:
            return 0.35
    return 1.0


def rounded_mask(px, py, n, radius_ratio=0.22):
    """角丸四角の内側か（iOS はさらに自前でマスクするが、他環境向けに角を落としておく）。"""
    r = n * radius_ratio
    x, y = px, py
    if x < r and y < r:
        return math.hypot(x - r, y - r) <= r
    if x > n - r and y < r:
        return math.hypot(x - (n - r), y - r) <= r
    if x < r and y > n - r:
        return math.hypot(x - r, y - (n - r)) <= r
    if x > n - r and y > n - r:
        return math.hypot(x - (n - r), y - (n - r)) <= r
    return True


def render(n, rounded):
    ss = SUPERSAMPLE
    rows = []
    for y in range(n):
        row = bytearray()
        for x in range(n):
            acc_r = acc_g = acc_b = acc_a = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    py = y + (sy + 0.5) / ss
                    if rounded and not rounded_mask(px, py, n):
                        continue
                    c = coverage(px, py, n)
                    r = BG[0] + (FG[0] - BG[0]) * c
                    g = BG[1] + (FG[1] - BG[1]) * c
                    b = BG[2] + (FG[2] - BG[2]) * c
                    acc_r += r
                    acc_g += g
                    acc_b += b
                    acc_a += 1.0
            k = ss * ss
            if acc_a == 0:
                row += bytes((0, 0, 0, 0))
            else:
                a = acc_a / k
                row += bytes((int(acc_r / acc_a + 0.5), int(acc_g / acc_a + 0.5), int(acc_b / acc_a + 0.5), int(a * 255 + 0.5)))
        rows.append(bytes(row))
    return rows


def write_png(path, n, rows):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + r for r in rows)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main():
    OUT_DIR.mkdir(exist_ok=True)
    for n in SIZES:
        # iOS の apple-touch-icon は不透明な正方形が推奨（角丸は iOS が付ける）
        rounded = n != 180
        rows = render(n, rounded)
        out = OUT_DIR / f"icon-{n}.png"
        write_png(out, n, rows)
        print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
