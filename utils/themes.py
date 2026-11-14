from __future__ import annotations

from dataclasses import dataclass, replace

RGB = tuple[int, int, int]


def hex2rgb(h: str) -> RGB:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a: RGB, b: RGB, k: float) -> RGB:
    return tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3))


def luminance(c: RGB) -> float:
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255


@dataclass(frozen=True)
class Theme:
    id: str
    bg: RGB
    bg2: RGB
    card: RGB | None
    card_now: RGB
    text: RGB
    muted: RGB
    accent: RGB
    accent2: RGB
    note: RGB
    line: RGB
    deco: str = "glow"
    outline: bool = False
    title_font: str = "Unbounded-Bold"
    subj_font: str = "Manrope-ExtraBold"
    subj_scale: float = 1.0


W, B = (255, 255, 255), (0, 0, 0)

THEMES: dict[str, Theme] = {
    "classic": Theme("classic", (15, 17, 22), (15, 17, 22), (27, 30, 38), (32, 44, 72), (240, 242, 246),
                     (146, 152, 166), (99, 140, 255), (168, 110, 255), (255, 205, 96), (44, 48, 58)),
    "neon": Theme("neon", (12, 5, 24), (30, 6, 46), (24, 12, 42), (48, 16, 70), (250, 240, 255),
                  (176, 150, 205), (255, 43, 214), (43, 240, 255), (255, 230, 80), (70, 30, 100),
                  deco="grid", outline=True),
    "pastel": Theme("pastel", (255, 241, 246), (240, 236, 255), (255, 255, 255), (255, 226, 238),
                    (61, 44, 62), (156, 138, 158), (255, 128, 176), (183, 156, 255), (214, 128, 0),
                    (240, 222, 232), deco="blobs"),
    "anime": Theme("anime", (255, 226, 236), (255, 250, 252), (255, 255, 255), (255, 214, 230),
                   (74, 36, 58), (170, 120, 145), (255, 92, 150), (255, 160, 200), (214, 90, 0),
                   (250, 210, 226), deco="sakura"),
    "minimal": Theme("minimal", W, W, (244, 244, 245), (228, 228, 231), (17, 17, 19), (113, 113, 122),
                     (17, 17, 19), (82, 82, 91), (180, 83, 9), (228, 228, 231), deco="none"),
    "notebook": Theme("notebook", (251, 250, 244), (251, 250, 244), None, (255, 241, 150), (35, 50, 94),
                      (98, 112, 150), (217, 71, 61), (35, 50, 94), (217, 71, 61), (201, 216, 238),
                      deco="paper", subj_font="Caveat-Bold", subj_scale=1.3),
    "newyear": Theme("newyear", (10, 26, 51), (6, 14, 30), (20, 40, 72), (30, 64, 60), (240, 246, 255),
                     (150, 170, 200), (255, 77, 94), (61, 220, 132), (255, 215, 90), (36, 58, 92),
                     deco="snow"),
    "halloween": Theme("halloween", (22, 11, 31), (8, 4, 12), (36, 20, 48), (70, 34, 20), (255, 240, 225),
                       (180, 150, 170), (255, 138, 31), (139, 92, 246), (180, 255, 90), (56, 34, 70),
                       deco="halloween"),
}


def build(theme_id: str | None, accent_hex: str | None = None, bg_hex: str | None = None) -> Theme:
    t = THEMES.get(theme_id or "classic", THEMES["classic"])
    if bg_hex:
        bg = hex2rgb(bg_hex)
        light = luminance(bg) > 0.6
        t = replace(
            t, bg=bg, bg2=mix(bg, B if light else W, 0.04),
            card=(mix(bg, B, 0.05) if light else mix(bg, W, 0.07)) if t.card is not None else None,
            text=(20, 22, 28) if light else (240, 242, 246),
            muted=(107, 114, 128) if light else (150, 156, 170),
            line=mix(bg, B if light else W, 0.12),
            note=(199, 119, 0) if light else (255, 205, 96),
        )
    if accent_hex:
        acc = hex2rgb(accent_hex)
        t = replace(t, accent=acc, accent2=mix(acc, W, 0.35))
    base = t.card or t.bg
    if t.deco != "paper":
        t = replace(t, card_now=mix(base, t.accent, 0.22))
    return t
