"""Dekorativní pozadí stránek kalendáře.

Každý styl má dvě fáze:
  under(...) – kreslí se před fotkami a kalendáriem (barva, vzor, podkladové karty)
  over(...)  – kreslí se nakonec (např. washi pásky přes rohy fotek)

Souřadnice jsou v mm od levého horního rohu ořezu (záporné / větší hodnoty sahají do spadávky).
Barvy se mění podle ročního období (index stránky 0 = titulka, 1–12 = měsíce).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

STYLY = ["zadne", "konfety", "puntiky", "vlny", "scrapbook", "kresbicky"]

PALETY = {
    "zima":  ["#7FB3DE", "#B9D7EE", "#4E7FB0", "#F2C14E", "#C9B8E8"],
    "jaro":  ["#F4A7B9", "#9ED39A", "#FFD966", "#B9A7E8", "#7CC4C0"],
    "leto":  ["#FFB347", "#4FC3D9", "#FF7A6B", "#FFE066", "#7ED6A5"],
    "podzim": ["#E08A3C", "#B5523B", "#E9B949", "#8A9A5B", "#C47A5A"],
}


def paleta(page: int) -> list[Color]:
    if page == 0:
        names = ["#FF7A6B", "#4FC3D9", "#FFD966", "#9ED39A", "#B9A7E8"]
    else:
        season = {12: "zima", 1: "zima", 2: "zima", 3: "jaro", 4: "jaro", 5: "jaro",
                  6: "leto", 7: "leto", 8: "leto"}.get(page, "podzim")
        names = PALETY[season]
    return [HexColor(n) for n in names]


def season_of(page: int) -> str:
    if page == 0:
        return "mix"
    return {12: "zima", 1: "zima", 2: "zima", 3: "jaro", 4: "jaro", 5: "jaro",
            6: "leto", 7: "leto", 8: "leto"}.get(page, "podzim")


def tint(c: Color, amount: float) -> Color:
    """Zesvětlení barvy směrem k bílé (amount 0 = původní, 1 = bílá)."""
    return Color(c.red + (1 - c.red) * amount, c.green + (1 - c.green) * amount, c.blue + (1 - c.blue) * amount)


@dataclass
class Ctx:
    c: Canvas
    X: Callable[[float], float]
    Y: Callable[[float], float]
    page: int                                     # 0 titulka, 1–12 měsíce
    trim: tuple[float, float]
    bleed: float
    boxes: list[tuple[float, float, float, float]]  # rámečky fotek (x, y, w, h)
    panel: tuple[float, float, float, float] | None  # oblast kalendária / nadpisu (x, y, w, h)
    rng: random.Random = field(default_factory=random.Random)

    @property
    def pal(self) -> list[Color]:
        return paleta(self.page)

    # pomocné kreslení v mm
    def rect(self, x, y, w, h, fill: Color, r: float = 0, alpha: float | None = None):
        c = self.c
        c.saveState()
        c.setFillColor(fill)
        if alpha is not None:
            c.setFillAlpha(alpha)
        if r:
            c.roundRect(self.X(x), self.Y(y + h), w * mm, h * mm, r * mm, stroke=0, fill=1)
        else:
            c.rect(self.X(x), self.Y(y + h), w * mm, h * mm, stroke=0, fill=1)
        c.restoreState()

    def full(self, fill: Color):
        b = self.bleed
        self.rect(-b, -b, self.trim[0] + 2 * b, self.trim[1] + 2 * b, fill)

    def free_point(self, margin: float = 0.0, avoid_panel: bool = True) -> tuple[float, float] | None:
        """Náhodný bod mimo fotky (a případně mimo panel kalendária)."""
        tw, th = self.trim
        for _ in range(60):
            x = self.rng.uniform(-1, tw + 1)
            y = self.rng.uniform(-1, th + 1)
            rects = list(self.boxes) + ([self.panel] if (avoid_panel and self.panel) else [])
            if all(not (rx - margin < x < rx + rw + margin and ry - margin < y < ry + rh + margin)
                   for rx, ry, rw, rh in rects):
                return x, y
        return None


def white_panel(ctx: Ctx, pad: float = 3.0, alpha: float = 0.94):
    if ctx.panel:
        x, y, w, h = ctx.panel
        ctx.rect(x - pad, y - pad, w + 2 * pad, h + 2 * pad, HexColor("#FFFFFF"), r=3, alpha=alpha)


# --- 1. konfety --------------------------------------------------------------
def konfety_under(ctx: Ctx):
    ctx.full(HexColor("#FFFDF8"))
    c = ctx.c
    for _ in range(170):
        p = ctx.free_point(margin=1.5)
        if not p:
            continue
        x, y = p
        col = ctx.rng.choice(ctx.pal)
        kind = ctx.rng.random()
        c.saveState()
        c.translate(ctx.X(x), ctx.Y(y))
        c.rotate(ctx.rng.uniform(0, 360))
        c.setFillColor(col)
        s = ctx.rng.uniform(1.6, 3.4) * mm
        if kind < 0.4:
            c.circle(0, 0, s / 2, stroke=0, fill=1)
        elif kind < 0.8:
            c.rect(-s * 0.9, -s * 0.28, s * 1.8, s * 0.56, stroke=0, fill=1)
        else:
            p_ = c.beginPath()
            p_.moveTo(0, s * 0.6); p_.lineTo(-s * 0.55, -s * 0.4); p_.lineTo(s * 0.55, -s * 0.4); p_.close()
            c.drawPath(p_, stroke=0, fill=1)
        c.restoreState()
    white_panel(ctx)


# --- 2. puntíky --------------------------------------------------------------
def puntiky_under(ctx: Ctx):
    pal = ctx.pal
    ctx.full(tint(pal[1], 0.82))
    c = ctx.c
    step = 9.0
    tw, th = ctx.trim
    row = 0
    y = -ctx.bleed
    while y < th + ctx.bleed + step:
        x = -ctx.bleed + (step / 2 if row % 2 else 0)
        while x < tw + ctx.bleed + step:
            col = tint(pal[0] if (row + int(x / step)) % 3 else pal[2], 0.35)
            c.setFillColor(col)
            c.circle(ctx.X(x), ctx.Y(y), 1.5 * mm, stroke=0, fill=1)
            x += step
        y += step * 0.866
        row += 1
    white_panel(ctx, alpha=1.0)


# --- 3. vlny -----------------------------------------------------------------
def _wave(ctx: Ctx, y_base: float, amp: float, length: float, phase: float, fill: Color, down: bool):
    """Vlnitý pás od y_base ke spodnímu (down=True) nebo hornímu okraji stránky."""
    c = ctx.c
    tw, th = ctx.trim
    b = ctx.bleed
    p = c.beginPath()
    x = -b
    p.moveTo(ctx.X(x), ctx.Y(y_base + amp * math.sin(phase)))
    while x <= tw + b:
        x += 2
        p.lineTo(ctx.X(x), ctx.Y(y_base + amp * math.sin(phase + x / length * 2 * math.pi)))
    edge = th + b if down else -b
    p.lineTo(ctx.X(tw + b), ctx.Y(edge))
    p.lineTo(ctx.X(-b), ctx.Y(edge))
    p.close()
    c.setFillColor(fill)
    c.drawPath(p, stroke=0, fill=1)


def vlny_under(ctx: Ctx):
    pal = ctx.pal
    ctx.full(HexColor("#FFFFFF"))
    ph = ctx.rng.uniform(0, 6.28)
    # horní vlnky v zóně vazby
    _wave(ctx, 9, 2.0, 70, ph, tint(pal[1], 0.55), down=False)
    _wave(ctx, 5, 1.6, 55, ph + 1.7, tint(pal[0], 0.45), down=False)
    # spodní vlny za kalendáriem
    top = (ctx.panel[1] - 6) if ctx.panel else ctx.trim[1] - 60
    _wave(ctx, top, 3.0, 90, ph + 0.5, tint(pal[1], 0.80), down=True)
    _wave(ctx, top + 9, 2.6, 75, ph + 2.2, tint(pal[0], 0.84), down=True)
    _wave(ctx, ctx.trim[1] - 7, 2.2, 60, ph + 4.0, tint(pal[2], 0.55), down=True)
    _wave(ctx, ctx.trim[1] - 2.5, 1.8, 48, ph + 1.0, tint(pal[0], 0.35), down=True)


# --- 4. scrapbook ------------------------------------------------------------
def scrapbook_under(ctx: Ctx):
    ctx.full(HexColor("#F3EADB"))
    c = ctx.c
    # jemné skvrnky papíru
    tw, th = ctx.trim
    c.setFillColor(HexColor("#D9CBB3"))
    for _ in range(900):
        c.circle(ctx.X(ctx.rng.uniform(-2, tw + 2)), ctx.Y(ctx.rng.uniform(-2, th + 2)),
                 ctx.rng.uniform(0.08, 0.25) * mm, stroke=0, fill=1)
    # bílé okraje fotek (jako vytištěné fotky)
    for x, y, w, h in ctx.boxes:
        ctx.rect(x - 1.4, y - 1.4, w + 2.8, h + 2.8, HexColor("#FFFFFF"))
    white_panel(ctx, pad=3.5, alpha=1.0)


def _tape(ctx: Ctx, cx: float, cy: float, angle: float, col: Color, length: float = 24, width: float = 7.5):
    c = ctx.c
    c.saveState()
    c.translate(ctx.X(cx), ctx.Y(cy))
    c.rotate(angle)
    L, W = length * mm, width * mm
    c.setFillColor(col)
    c.setFillAlpha(0.82)
    p = c.beginPath()  # zubaté konce pásky
    p.moveTo(-L / 2, -W / 2)
    p.lineTo(L / 2, -W / 2)
    for i in range(6):
        p.lineTo(L / 2 + (0.6 * mm if i % 2 == 0 else 0), -W / 2 + W * (i + 1) / 6)
    p.lineTo(-L / 2, W / 2)
    for i in range(6):
        p.lineTo(-L / 2 - (0.6 * mm if i % 2 == 0 else 0), W / 2 - W * (i + 1) / 6)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    # proužky na pásce
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFillAlpha(0.35)
    x = -L / 2 + 1.5 * mm
    while x < L / 2 - 1.5 * mm:
        c.rect(x, -W / 2, 1.2 * mm, W, stroke=0, fill=1)
        x += 3.2 * mm
    c.restoreState()


def scrapbook_over(ctx: Ctx):
    pal = ctx.pal
    for i, (x, y, w, h) in enumerate(ctx.boxes):
        col = pal[i % len(pal)]
        if w > 60 and h > 60 and ctx.rng.random() < 0.5:
            _tape(ctx, x + w / 2 + ctx.rng.uniform(-10, 10), y + 0.5, ctx.rng.uniform(-6, 6), col, length=30)
        else:
            _tape(ctx, x + 4, y + 4, -38 + ctx.rng.uniform(-5, 5), col)
            _tape(ctx, x + w - 4, y + h - 4, -38 + ctx.rng.uniform(-5, 5), pal[(i + 2) % len(pal)])
    if ctx.panel:
        x, y, w, h = ctx.panel
        _tape(ctx, x + w / 2, y - 3.5, ctx.rng.uniform(-3, 3), pal[3], length=28)


# --- 5. kresbičky (sezónní doodles) -----------------------------------------
def _snowflake(c: Canvas, s: float):
    for k in range(3):
        c.saveState(); c.rotate(60 * k)
        c.line(-s, 0, s, 0)
        for sign in (-1, 1):
            c.line(sign * s * 0.55, 0, sign * s * 0.8, s * 0.22)
            c.line(sign * s * 0.55, 0, sign * s * 0.8, -s * 0.22)
        c.restoreState()


def _flower(c: Canvas, s: float, petal: Color, center: Color):
    c.setFillColor(petal)
    for k in range(5):
        a = k * 72 * math.pi / 180
        c.circle(math.cos(a) * s * 0.55, math.sin(a) * s * 0.55, s * 0.42, stroke=0, fill=1)
    c.setFillColor(center)
    c.circle(0, 0, s * 0.3, stroke=0, fill=1)


def _sun(c: Canvas, s: float):
    c.circle(0, 0, s * 0.45, stroke=0, fill=1)
    for k in range(8):
        c.saveState(); c.rotate(45 * k)
        c.line(s * 0.62, 0, s * 0.95, 0)
        c.restoreState()


def _leaf(c: Canvas, s: float, col: Color):
    p = c.beginPath()
    p.moveTo(0, -s)
    p.curveTo(s * 0.75, -s * 0.4, s * 0.6, s * 0.6, 0, s)
    p.curveTo(-s * 0.6, s * 0.6, -s * 0.75, -s * 0.4, 0, -s)
    c.setFillColor(col)
    c.drawPath(p, stroke=0, fill=1)
    c.setStrokeColor(HexColor("#FFFFFF"))
    c.setLineWidth(0.5)
    c.line(0, -s * 1.15, 0, s * 0.8)


def _heart(c: Canvas, s: float):
    p = c.beginPath()
    p.moveTo(0, -s * 0.8)
    p.curveTo(s * 1.1, 0, s * 0.6, s * 0.95, 0, s * 0.4)
    p.curveTo(-s * 0.6, s * 0.95, -s * 1.1, 0, 0, -s * 0.8)
    c.drawPath(p, stroke=0, fill=1)


def kresbicky_under(ctx: Ctx):
    pal = ctx.pal
    ctx.full(HexColor("#FFFEFA"))
    c = ctx.c
    season = season_of(ctx.page)
    for _ in range(70):
        p = ctx.free_point(margin=1.5)
        if not p:
            continue
        x, y = p
        s = ctx.rng.uniform(3.6, 6.2) * mm
        col = ctx.rng.choice(pal)
        kind = season if season != "mix" else ctx.rng.choice(["zima", "jaro", "leto", "podzim", "srdce"])
        c.saveState()
        c.translate(ctx.X(x), ctx.Y(y))
        c.rotate(ctx.rng.uniform(-30, 30))
        c.setStrokeColor(col); c.setFillColor(col); c.setLineWidth(1.0); c.setLineCap(1)
        if kind == "zima":
            if ctx.rng.random() < 0.8:
                _snowflake(c, s)
            else:
                c.circle(0, 0, s * 0.25, stroke=0, fill=1)
        elif kind == "jaro":
            _flower(c, s * 0.8, tint(col, 0.15), HexColor("#FFD966"))
        elif kind == "leto":
            if ctx.rng.random() < 0.5:
                _sun(c, s)
            else:
                c.circle(0, 0, s * 0.3, stroke=0, fill=1)  # bublinky
                c.circle(s * 0.5, s * 0.4, s * 0.16, stroke=0, fill=1)
        elif kind == "podzim":
            _leaf(c, s, col)
        else:
            _heart(c, s * 0.8)
        c.restoreState()
    white_panel(ctx)


UNDER = {"konfety": konfety_under, "puntiky": puntiky_under, "vlny": vlny_under,
         "scrapbook": scrapbook_under, "kresbicky": kresbicky_under}
OVER = {"scrapbook": scrapbook_over}


def draw(ctx: Ctx, styl: str, phase: str) -> None:
    if styl not in STYLY:
        raise ValueError(f"Neznámé pozadí {styl!r} (povolené: {', '.join(STYLY)})")
    fn = (UNDER if phase == "under" else OVER).get(styl)
    if fn:
        ctx.rng.seed(f"{styl}-{ctx.page}-{phase}")
        fn(ctx)
