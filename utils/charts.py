"""📈 Графики для админки (PNG через Pillow — без matplotlib)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from utils.image import F_BOLD, F_REG, F_SEMI

W, H = 1200, 680
L, R, T, B = 110, 50, 150, 90
BG, GRID, TEXT, MUTED = (15, 17, 22), (40, 44, 54), (240, 242, 246), (140, 146, 160)


def _nice(v: float) -> float:
    if v <= 5:
        return 5
    for step in (1, 2, 2.5, 5):
        for mag in (1, 10, 100, 1000, 10000, 100000):
            if step * mag * 4 >= v:
                return step * mag * 4
    return v


def chart(title: str, subtitle: str, labels: list[str], bars: list[float] | None = None,
          line: list[float] | None = None, bar_color=(99, 140, 255), line_color=(61, 220, 132),
          bar_name: str = "", line_name: str = "") -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((L, 36), title, font=F_BOLD(44), fill=TEXT)
    d.text((L, 92), subtitle, font=F_REG(28), fill=MUTED)
    n = len(labels)
    pw, ph = W - L - R, H - T - B
    top = _nice(max([*(bars or [0]), *(line or [0]), 1]))
    for i in range(5):  # сетка и подписи по Y
        y = T + ph - ph * i / 4
        d.line((L, y, W - R, y), fill=GRID, width=1)
        val = top * i / 4
        s = f"{val:.0f}" if val >= 10 or val == int(val) else f"{val:.1f}"
        d.text((L - 16 - d.textlength(s, font=F_REG(24)), y - 14), s, font=F_REG(24), fill=MUTED)
    step = pw / max(n, 1)
    if bars:
        bw = max(4, step * 0.62)
        for i, v in enumerate(bars):
            if v <= 0:
                continue
            x = L + step * i + (step - bw) / 2
            h = ph * v / top
            d.rounded_rectangle((x, T + ph - h, x + bw, T + ph), radius=min(6, bw / 2), fill=bar_color)
    if line:
        pts = [(L + step * i + step / 2, T + ph - ph * v / top) for i, v in enumerate(line)]
        d.line(pts, fill=line_color, width=5, joint="curve")
        for x, y in pts[-1:]:
            d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=line_color)
            s = f"{line[-1]:.0f}"
            d.text((x - d.textlength(s, font=F_SEMI(26)) - 14, y - 44), s, font=F_SEMI(26), fill=line_color)
    every = max(1, n // 8)  # подписи по X
    for i, lab in enumerate(labels):
        if i % every == 0 or i == n - 1:
            x = L + step * i + step / 2
            d.text((x - d.textlength(lab, font=F_REG(22)) / 2, T + ph + 18), lab, font=F_REG(22), fill=MUTED)
    lx = W - R  # легенда
    for name, col in ((line_name, line_color), (bar_name, bar_color)):
        if not name or (col == line_color and not line) or (col == bar_color and not bars):
            continue
        tw = d.textlength(name, font=F_SEMI(24))
        lx -= tw + 40
        d.rounded_rectangle((lx, 50, lx + 22, 72), radius=5, fill=col)
        d.text((lx + 30, 46), name, font=F_SEMI(24), fill=TEXT)
        lx -= 20
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
