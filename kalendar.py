# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4.0", "pillow>=10.0"]
# ///
"""Generátor nástěnného kalendáře pro onlineprinters (Wire-o, A4 na výšku, 13 listů).

Výstup:
  out/kalendar-<rok>.pdf        – tisková data (21,4 × 30,1 cm vč. 2 mm spadávky, bez značek)
  out/kalendar-<rok>-nahled.pdf – stejné + vodítka (ořez, bezpečná zóna, zóna vazby)

Spuštění:  uv run kalendar.py
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import sys
import tomllib
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pozadi  # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
CACHE = OUT / ".cache"

# --- geometrie (mm) ---------------------------------------------------------
BLEED = 2.0
TRIM_W, TRIM_H = 210.0, 297.0
PAGE_W, PAGE_H = TRIM_W + 2 * BLEED, TRIM_H + 2 * BLEED
SAFE = 4.0            # požadavek tiskárny: důležité prvky min. 4 mm od ořezu
BINDING = 13.0        # horní zóna pro Wire-o vazbu a otvor na háček
MARGIN = 12.0         # boční okraj obsahu
GUTTER = 3.0          # mezera mezi fotkami
DPI = 300

# měsíční stránka
PHOTO_TOP = 17.0
PHOTO_BOTTOM = 224.0
HEADER_BASELINE = 234.5
HEADER_PT = 17
WEEKDAY_TOP = 238.0
GRID_TOP = 242.5
ROW_H = 7.0
DAY_PT = 8.5
HOLIDAY_PT = 4.8

# titulní stránka
COVER_PHOTO_BOTTOM = 238.0

MESICE = ["Leden", "Únor", "Březen", "Duben", "Květen", "Červen", "Červenec",
          "Srpen", "Září", "Říjen", "Listopad", "Prosinec"]
DNY = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

GREY_LINE = HexColor("#D9D6D0")
GREY_TEXT = HexColor("#8A8680")
GREY_FAINT = HexColor("#C4C0B9")
PLACEHOLDER = HexColor("#E8E5E0")


# --- fonty ------------------------------------------------------------------
def register_fonts() -> None:
    f = ROOT / "fonts"
    pdfmetrics.registerFont(TTFont("Sans", f / "NotoSans-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("Sans-Bold", f / "NotoSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Serif", f / "NotoSerif-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("Serif-Bold", f / "NotoSerif-Bold.ttf"))


# --- svátky -----------------------------------------------------------------
def easter(year: int) -> dt.date:
    """Velikonoční neděle (anonymní gregoriánský algoritmus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def czech_holidays(year: int) -> dict[dt.date, str]:
    e = easter(year)
    fixed = {
        (1, 1): "Nový rok",
        (5, 1): "Svátek práce",
        (5, 8): "Den vítězství",
        (7, 5): "Cyril a Metoděj",
        (7, 6): "Mistr Jan Hus",
        (9, 28): "Den české státnosti",
        (10, 28): "Vznik Československa",
        (11, 17): "Den boje za svobodu",
        (12, 24): "Štědrý den",
        (12, 25): "1. svátek vánoční",
        (12, 26): "2. svátek vánoční",
    }
    out = {dt.date(year, m, d): n for (m, d), n in fixed.items()}
    out[e - dt.timedelta(days=2)] = "Velký pátek"
    out[e + dt.timedelta(days=1)] = "Velikonoční pondělí"
    return out


# --- pomocné ----------------------------------------------------------------
def X(x_trim: float) -> float:
    """x od levého okraje ořezu (mm) -> body PDF."""
    return (BLEED + x_trim) * mm


def Y(y_trim: float) -> float:
    """y od horního okraje ořezu (mm, dolů) -> body PDF (od spodu)."""
    return (PAGE_H - BLEED - y_trim) * mm


def photo_boxes(layout: str, top: float, bottom: float) -> list[tuple[float, float, float, float]]:
    """Rámečky fotek (x, y, w, h) v mm, y = horní hrana od horního okraje ořezu."""
    x0, w = MARGIN, TRIM_W - 2 * MARGIN
    y0, h = top, bottom - top
    g = GUTTER
    half_w, half_h = (w - g) / 2, (h - g) / 2
    if layout == "1":
        return [(x0, y0, w, h)]
    if layout == "2":
        return [(x0, y0, w, half_h), (x0, y0 + half_h + g, w, half_h)]
    if layout == "2v":
        return [(x0, y0, half_w, h), (x0 + half_w + g, y0, half_w, h)]
    if layout == "3":
        big = h * 0.58
        small = h - big - g
        return [(x0, y0, w, big),
                (x0, y0 + big + g, half_w, small),
                (x0 + half_w + g, y0 + big + g, half_w, small)]
    if layout == "3v":
        big = w * 0.6
        small = w - big - g
        return [(x0, y0, big, h),
                (x0 + big + g, y0, small, half_h),
                (x0 + big + g, y0 + half_h + g, small, half_h)]
    if layout == "4":
        return [(x0, y0, half_w, half_h), (x0 + half_w + g, y0, half_w, half_h),
                (x0, y0 + half_h + g, half_w, half_h),
                (x0 + half_w + g, y0 + half_h + g, half_w, half_h)]
    raise ValueError(f"Neznámé rozložení: {layout!r} (povolené: 1, 2, 2v, 3, 3v, 4)")


def crop_window(img_w: int, img_h: int, box_w: float, box_h: float,
                zoom: float = 1.0, fx: float = 0.5, fy: float = 0.5) -> tuple[int, int, int, int]:
    """Výřez fotky (left, top, right, bottom v px) pro rámeček box_w × box_h.

    zoom ≥ 1 přibližuje, (fx, fy) je střed výřezu jako podíl šířky/výšky fotky.
    Stejný výpočet používá editor (app.html → cropGeom).
    """
    zoom = max(1.0, zoom)
    ar = img_w / img_h
    if ar > box_w / box_h:
        dh = box_h * zoom
        dw = dh * ar
    else:
        dw = box_w * zoom
        dh = dw / ar
    cw, ch = img_w * box_w / dw, img_h * box_h / dh
    fx = min(max(fx, cw / (2 * img_w)), 1 - cw / (2 * img_w))
    fy = min(max(fy, ch / (2 * img_h)), 1 - ch / (2 * img_h))
    left, top = fx * img_w - cw / 2, fy * img_h - ch / 2
    return round(left), round(top), round(left + cw), round(top + ch)


def photo_spec(item) -> tuple[str, float, float, float]:
    """Položka z kalendar.toml: "fotky/x.jpg" nebo { soubor = "...", zoom = 1.3, x = 0.4, y = 0.5 }."""
    if isinstance(item, str):
        return item, 1.0, 0.5, 0.5
    return item["soubor"], float(item.get("zoom", 1.0)), float(item.get("x", 0.5)), float(item.get("y", 0.5))


def prepare_image(path: Path, w_mm: float, h_mm: float, warnings: list[str],
                  zoom: float = 1.0, fx: float = 0.5, fy: float = 0.5) -> Path:
    """Ořízne fotku podle rámečku a výřezu a zmenší na 300 dpi. Vrací cestu k JPEG v cache."""
    target = (round(w_mm / 25.4 * DPI), round(h_mm / 25.4 * DPI))
    key = hashlib.sha1(f"{path.resolve()}|{path.stat().st_mtime}|{target}|{zoom:.4f}|{fx:.4f}|{fy:.4f}".encode()).hexdigest()[:16]
    cached = CACHE / f"{key}.jpg"
    if cached.exists():
        return cached
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = im.crop(crop_window(im.width, im.height, w_mm, h_mm, zoom, fx, fy))
        if im.width < target[0] * 0.66:
            eff = round(im.width / (w_mm / 25.4))
            warnings.append(f"  ! {path.name}: nízké rozlišení (~{eff} dpi v rámečku {w_mm:.0f}×{h_mm:.0f} mm)")
        if im.width > target[0]:
            im = im.resize(target, Image.LANCZOS)
        CACHE.mkdir(parents=True, exist_ok=True)
        im.save(cached, "JPEG", quality=93, dpi=(DPI, DPI), subsampling=0)
    return cached


def draw_photos(c: canvas.Canvas, layout: str, photos: list, top: float, bottom: float,
                warnings: list[str]) -> None:
    boxes = photo_boxes(layout, top, bottom)
    if len(photos) > len(boxes):
        warnings.append(f"  ! rozložení {layout!r} má {len(boxes)} rámečky, zadáno {len(photos)} fotek – přebytečné ignoruji")
    for i, (x, y, w, h) in enumerate(boxes):
        px, py, pw, ph = X(x), Y(y + h), w * mm, h * mm
        spec = photo_spec(photos[i]) if i < len(photos) else None
        src = ROOT / spec[0] if spec and spec[0] else None
        if src is not None and src.exists():
            img = prepare_image(src, w, h, warnings, *spec[1:])
            c.drawImage(str(img), px, py, pw, ph)
            continue
        if src is not None:
            warnings.append(f"  ! fotka nenalezena: {spec[0]}")
        c.setFillColor(PLACEHOLDER)
        c.rect(px, py, pw, ph, stroke=0, fill=1)
        c.setFillColor(GREY_TEXT)
        cx, cy = px + pw / 2, py + ph / 2
        c.setFont("Sans-Bold", 11)
        c.drawCentredString(cx, cy + 4, f"Foto {i + 1}")
        c.setFont("Sans", 7.5)
        c.drawCentredString(cx, cy - 8, f"{w:.0f} × {h:.0f} mm  ·  ideálně {round(w / 25.4 * DPI)} × {round(h / 25.4 * DPI)} px")


def draw_month_grid(c: canvas.Canvas, year: int, month: int, holidays: dict[dt.date, str],
                    accent: Color, text: Color) -> None:
    x0, w = MARGIN, TRIM_W - 2 * MARGIN
    cw = w / 7

    # záhlaví: měsíc vlevo, rok vpravo
    c.setFillColor(text)
    c.setFont("Serif-Bold", HEADER_PT)
    c.drawString(X(x0), Y(HEADER_BASELINE), MESICE[month - 1])
    c.setFillColor(GREY_TEXT)
    c.setFont("Serif", HEADER_PT)
    c.drawRightString(X(x0 + w), Y(HEADER_BASELINE), str(year))

    # dny v týdnu
    c.setFont("Sans", 6)
    for i, d in enumerate(DNY):
        c.drawString(X(x0 + i * cw + 1.5), Y(WEEKDAY_TOP + 2.8), d.upper())

    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    tint = Color(accent.red, accent.green, accent.blue, alpha=0.10)

    for r, week in enumerate(weeks):
        top = GRID_TOP + r * ROW_H
        c.setStrokeColor(GREY_LINE)
        c.setLineWidth(0.4)
        c.line(X(x0), Y(top), X(x0 + w), Y(top))
        for i, day in enumerate(week):
            cx = x0 + i * cw
            in_month = day.month == month
            name = holidays.get(day) if in_month else None
            if name:
                c.setFillColor(tint)
                c.rect(X(cx + 0.4), Y(top + ROW_H - 0.4), (cw - 0.8) * mm, (ROW_H - 0.8) * mm, stroke=0, fill=1)
            base = top + ROW_H / 2 + DAY_PT * 0.353 * 0.36  # svisle na střed řádku
            if not in_month:
                c.setFillColor(GREY_FAINT)
                font = "Sans"
            elif name:
                c.setFillColor(accent)
                font = "Sans-Bold"
            else:
                c.setFillColor(text)
                font = "Sans"
            c.setFont(font, DAY_PT)
            num = str(day.day)
            c.drawString(X(cx + 1.5), Y(base), num)
            if name:
                # název svátku vedle čísla, na jeden řádek (případně zmenšit)
                nx = cx + 1.5 + pdfmetrics.stringWidth(num, font, DAY_PT) / mm + 1.2
                avail = (cx + cw - 0.8 - nx) * mm
                size = HOLIDAY_PT
                while pdfmetrics.stringWidth(name, "Sans", size) > avail and size > 3.6:
                    size -= 0.2
                c.setFont("Sans", size)
                c.drawString(X(nx), Y(base), name)
    bottom = GRID_TOP + len(weeks) * ROW_H
    c.setStrokeColor(GREY_LINE)
    c.line(X(x0), Y(bottom), X(x0 + w), Y(bottom))


def draw_guides(c: canvas.Canvas) -> None:
    c.saveState()
    # zóna vazby
    c.setFillColor(Color(0.2, 0.4, 0.9, alpha=0.08))
    c.rect(0, Y(BINDING), PAGE_W * mm, (BLEED + BINDING) * mm, stroke=0, fill=1)
    # ořez
    c.setStrokeColor(HexColor("#E0245E"))
    c.setLineWidth(0.5)
    c.rect(X(0), Y(TRIM_H), TRIM_W * mm, TRIM_H * mm, stroke=1, fill=0)
    # bezpečná zóna
    c.setStrokeColor(HexColor("#2F6FE0"))
    c.setDash(2, 2)
    c.rect(X(SAFE), Y(TRIM_H - SAFE), (TRIM_W - 2 * SAFE) * mm, (TRIM_H - 2 * SAFE) * mm, stroke=1, fill=0)
    c.setDash()
    c.setFillColor(HexColor("#2F6FE0"))
    c.setFont("Sans", 6)
    c.drawString(X(SAFE + 1), Y(BINDING - 2.5), "zóna vazby Wire-o / háček")
    c.restoreState()


def page_frames(year: int, page: int, layout: str, has_sub: bool = False):
    """Rámečky fotek a oblast textu (panel) pro stránku 0 = titulka, 1–12 = měsíce."""
    if page == 0:
        return (photo_boxes(layout, PHOTO_TOP, COVER_PHOTO_BOTTOM),
                (TRIM_W / 2 - 55, 249, 110, 34 if has_sub else 22))
    rows = len(calendar.Calendar(firstweekday=0).monthdatescalendar(year, page))
    top = HEADER_BASELINE - HEADER_PT * 0.353 * 0.85
    return (photo_boxes(layout, PHOTO_TOP, PHOTO_BOTTOM),
            (MARGIN, top, TRIM_W - 2 * MARGIN, GRID_TOP + rows * ROW_H - top))


def build(cfg: dict, out_path: Path, guides: bool, warnings: list[str]) -> None:
    year = cfg["rok"]
    accent = HexColor(cfg.get("barva_svatku", "#B4472F"))
    text = HexColor(cfg.get("barva_textu", "#2B2B2B"))
    holidays = czech_holidays(year)
    months = cfg.get("mesic", [])
    if len(months) != 12:
        sys.exit(f"V kalendar.toml musí být přesně 12 sekcí [[mesic]], je jich {len(months)}.")

    c = canvas.Canvas(str(out_path), pagesize=(PAGE_W * mm, PAGE_H * mm))
    c.setTitle(f"Kalendář {year}")
    c.setAuthor("kalendar.py")

    styl = cfg.get("pozadi", "zadne")

    def ctx(page: int, boxes, panel) -> pozadi.Ctx:
        return pozadi.Ctx(c=c, X=X, Y=Y, page=page, trim=(TRIM_W, TRIM_H), bleed=BLEED,
                          boxes=boxes, panel=panel)

    def page_bg(page: int, boxes, panel) -> pozadi.Ctx:
        c.setFillColorRGB(1, 1, 1)
        c.rect(0, 0, PAGE_W * mm, PAGE_H * mm, stroke=0, fill=1)
        cx = ctx(page, boxes, panel)
        pozadi.draw(cx, styl, "under")
        return cx

    # titulka
    t = cfg.get("titulka", {})
    lay = t.get("rozlozeni", "1")
    boxes, title_panel = page_frames(year, 0, lay, bool(t.get("podnadpis")))
    cx = page_bg(0, boxes, title_panel)
    draw_photos(c, lay, t.get("fotky", []), PHOTO_TOP, COVER_PHOTO_BOTTOM, warnings)
    c.setFillColor(text)
    c.setFont("Serif-Bold", 54)
    c.drawCentredString(X(TRIM_W / 2), Y(266), t.get("nadpis", str(year)))
    if t.get("podnadpis"):
        c.setFillColor(GREY_TEXT)
        c.setFont("Serif", 14)
        c.drawCentredString(X(TRIM_W / 2), Y(278), t["podnadpis"])
    pozadi.draw(cx, styl, "over")
    if guides:
        draw_guides(c)
    c.showPage()

    # měsíce
    for m, mc in enumerate(months, start=1):
        lay = mc.get("rozlozeni", "1")
        boxes, panel = page_frames(year, m, lay)
        cx = page_bg(m, boxes, panel)
        draw_photos(c, lay, mc.get("fotky", []), PHOTO_TOP, PHOTO_BOTTOM, warnings)
        draw_month_grid(c, year, m, holidays, accent, text)
        pozadi.draw(cx, styl, "over")
        if guides:
            draw_guides(c)
        c.showPage()
    c.save()


def config_path() -> Path:
    """kalendar.toml; při prvním spuštění se vytvoří z kalendar.example.toml."""
    cfg = ROOT / "kalendar.toml"
    if not cfg.exists():
        cfg.write_text((ROOT / "kalendar.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
    return cfg


def main() -> None:
    cfg = tomllib.loads(config_path().read_text(encoding="utf-8"))
    register_fonts()
    OUT.mkdir(exist_ok=True)
    year = cfg["rok"]
    warnings: list[str] = []
    print_pdf = OUT / f"kalendar-{year}.pdf"
    build(cfg, print_pdf, guides=False, warnings=warnings)
    build(cfg, OUT / f"kalendar-{year}-nahled.pdf", guides=True, warnings=[])
    print(f"Hotovo: {print_pdf.relative_to(ROOT)} (+ náhled s vodítky)")
    for w in dict.fromkeys(warnings):
        print(w)


if __name__ == "__main__":
    main()
