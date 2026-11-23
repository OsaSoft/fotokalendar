# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4.0", "pillow>=10.0"]
# ///
"""Jednoduchý editor kalendáře v prohlížeči.

Spuštění:  uv run app.py      (otevře http://127.0.0.1:8765)

- vlevo knihovna fotek ze složky fotky/ (sem lze přetáhnout i soubory z počítače)
- přetahuj fotky do rámečků stránek, měň rozložení
- vše se průběžně ukládá do kalendar.toml; tlačítkem se vygeneruje PDF
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import sys
import threading
import tomllib
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import kalendar  # noqa: E402
import pozadi  # noqa: E402

PHOTOS = ROOT / "fotky"
THUMBS = ROOT / "out" / ".thumbs"
CONFIG = ROOT / "kalendar.toml"
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
LAYOUTS = ["1", "2", "2v", "3", "3v", "4"]
PORT = int(os.environ.get("KALENDAR_PORT", "8765"))

_dims_cache: dict[tuple[str, float], tuple[int, int]] = {}
_build_lock = threading.Lock()


# --- data ---------------------------------------------------------------
def photo_dims(p: Path) -> tuple[int, int]:
    key = (p.name, p.stat().st_mtime)
    if key not in _dims_cache:
        with Image.open(p) as im:
            w, h = im.size
            orient = im.getexif().get(0x0112, 1)
            _dims_cache[key] = (h, w) if orient in (5, 6, 7, 8) else (w, h)
    return _dims_cache[key]


def list_photos() -> list[dict]:
    out = []
    for p in sorted(PHOTOS.iterdir(), key=lambda x: x.name.lower()):
        if p.suffix.lower() in EXTS and p.is_file():
            try:
                w, h = photo_dims(p)
            except Exception:
                continue
            out.append({"name": p.name, "w": w, "h": h})
    return out


def thumbnail(name: str) -> bytes:
    src = PHOTOS / name
    THUMBS.mkdir(parents=True, exist_ok=True)
    dst = THUMBS / f"{src.stem}-{int(src.stat().st_mtime)}-1000.jpg"
    if not dst.exists():
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1000, 1000))
            im.save(dst, "JPEG", quality=82)
    return dst.read_bytes()


def geometry() -> dict:
    k = kalendar
    return {
        "trim": [k.TRIM_W, k.TRIM_H],
        "layouts": LAYOUTS,
        "cover": {l: k.photo_boxes(l, k.PHOTO_TOP, k.COVER_PHOTO_BOTTOM) for l in LAYOUTS},
        "month": {l: k.photo_boxes(l, k.PHOTO_TOP, k.PHOTO_BOTTOM) for l in LAYOUTS},
        "header": k.HEADER_BASELINE, "gridTop": k.GRID_TOP, "rowH": k.ROW_H, "margin": k.MARGIN,
        "months": k.MESICE,
    }


def load_config() -> dict:
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    def strip(fs):
        out = []
        for f in fs:
            path, zoom, x, y = kalendar.photo_spec(f)
            out.append({"name": path.removeprefix("fotky/"), "zoom": zoom, "x": x, "y": y} if path else "")
        return out
    t = cfg.get("titulka", {})
    return {
        "rok": cfg.get("rok", 2027),
        "nadpis": t.get("nadpis", str(cfg.get("rok", 2027))),
        "podnadpis": t.get("podnadpis", ""),
        "pozadi": cfg.get("pozadi", "zadne"),
        "pages": [{"layout": t.get("rozlozeni", "1"), "photos": strip(t.get("fotky", []))}]
                 + [{"layout": m.get("rozlozeni", "1"), "photos": strip(m.get("fotky", []))}
                    for m in cfg.get("mesic", [])],
        "_raw": cfg,
    }


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON string == platný TOML basic string


def save_config(data: dict) -> None:
    raw = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    pages = data["pages"]
    if len(pages) != 13:
        raise ValueError("očekávám 13 stránek")

    def photos(p: dict) -> str:
        n = len(kalendar.photo_boxes(p["layout"], 0, 100))
        items = []
        for e in p["photos"][:n]:
            if not e:
                items.append('""')  # prázdný rámeček – zachovat pozici dalších fotek
                continue
            path = f"fotky/{e['name']}"
            zoom, x, y = float(e.get("zoom", 1)), float(e.get("x", .5)), float(e.get("y", .5))
            if abs(zoom - 1) < 1e-3 and abs(x - .5) < 1e-3 and abs(y - .5) < 1e-3:
                items.append(q(path))
            else:
                items.append(f"{{ soubor = {q(path)}, zoom = {zoom:.3f}, x = {x:.4f}, y = {y:.4f} }}")
        while items and items[-1] == '""':
            items.pop()
        if not items:
            return "[]"
        return "[\n  " + ",\n  ".join(items) + ",\n]"

    lines = [
        f"# Nastavení kalendáře {raw.get('rok', 2027)}",
        "# Upravuj v editoru (uv run app.py) nebo ručně; PDF: uv run kalendar.py",
        "",
        f"rok = {raw.get('rok', 2027)}",
        f"format = {q(raw.get('format', 'A4'))}",
        f"barva_svatku = {q(raw.get('barva_svatku', '#B4472F'))}",
        f"barva_textu = {q(raw.get('barva_textu', '#2B2B2B'))}",
        f"pozadi = {q(data.get('pozadi', raw.get('pozadi', 'zadne')))}   # zadne | konfety | puntiky | vlny | scrapbook | kresbicky",
        "",
        "# Rozložení: \"1\" celá plocha | \"2\" dvě nad sebou | \"2v\" dvě vedle sebe |",
        "#            \"3\" velká nahoře + dvě dole | \"3v\" velká vlevo + dvě vpravo | \"4\" mřížka 2×2",
        "",
        "[titulka]",
        f"nadpis = {q(data.get('nadpis', ''))}",
        f"podnadpis = {q(data.get('podnadpis', ''))}",
        f"rozlozeni = {q(pages[0]['layout'])}",
        f"fotky = {photos(pages[0])}",
    ]
    for i, p in enumerate(pages[1:]):
        lines += ["", f"[[mesic]]   # {kalendar.MESICE[i].lower()}",
                  f"rozlozeni = {q(p['layout'])}", f"fotky = {photos(p)}"]
    text = "\n".join(lines) + "\n"
    tomllib.loads(text)  # kontrola platnosti
    CONFIG.write_text(text, encoding="utf-8")


def render_background(styl: str, page: int, layout: str, has_sub: bool, phase: str) -> bytes:
    """Vykreslí jen pozadí (fázi under/over) jedné stránky do PNG pro náhled v editoru."""
    BGDIR = ROOT / "out" / ".bg"
    BGDIR.mkdir(parents=True, exist_ok=True)
    src_mtime = int((ROOT / "pozadi.py").stat().st_mtime)
    year = tomllib.loads(CONFIG.read_text(encoding="utf-8")).get("rok", 2027)
    png = BGDIR / f"{year}-{styl}-{page}-{layout}-{int(has_sub)}-{phase}-{src_mtime}.png"
    if png.exists():
        return png.read_bytes()
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.units import mm
    k = kalendar
    boxes, panel = k.page_frames(year, page, layout, has_sub)
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "bg.pdf"
        c = rl_canvas.Canvas(str(pdf), pagesize=(k.PAGE_W * mm, k.PAGE_H * mm))
        if phase == "under":
            c.setFillColorRGB(1, 1, 1)
            c.rect(0, 0, k.PAGE_W * mm, k.PAGE_H * mm, stroke=0, fill=1)
        ctx = pozadi.Ctx(c=c, X=k.X, Y=k.Y, page=page, trim=(k.TRIM_W, k.TRIM_H), bleed=k.BLEED,
                         boxes=boxes, panel=panel)
        pozadi.draw(ctx, styl, phase)
        c.showPage()
        c.save()
        # oříznout spadávku: 2 mm při 72 dpi
        dpi = 72
        off = round(k.BLEED / 25.4 * dpi)
        w, h = round(k.TRIM_W / 25.4 * dpi), round(k.TRIM_H / 25.4 * dpi)
        cmd = ["pdftocairo", "-png", "-singlefile", "-r", str(dpi), "-x", str(off), "-y", str(off),
               "-W", str(w), "-H", str(h)]
        if phase == "over":
            cmd.append("-transp")
        subprocess.run(cmd + [str(pdf), str(png.with_suffix(""))], check=True, capture_output=True)
    return png.read_bytes()


def run_build() -> str:
    buf = io.StringIO()
    with _build_lock, contextlib.redirect_stdout(buf):
        try:
            kalendar.main()
        except SystemExit as e:
            print(f"Chyba: {e}")
    return buf.getvalue()


SAFE_NAME = re.compile(r"[^\w.\- ]", re.UNICODE)


def safe_name(name: str) -> str:
    name = SAFE_NAME.sub("_", Path(name).name).strip() or "foto.jpg"
    stem, suf = Path(name).stem, Path(name).suffix.lower()
    cand, i = PHOTOS / f"{stem}{suf}", 1
    while cand.exists():
        cand, i = PHOTOS / f"{stem}-{i}{suf}", i + 1
    return cand.name


# --- HTTP ---------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # ticho
        pass

    def send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if "json" in ctype or "html" in ctype else "max-age=3600")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code: int = 200) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        try:
            if path == "/":
                self.send(200, (ROOT / "app.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/state":
                cfg = load_config()
                cfg.pop("_raw")
                self.json({"config": cfg, "photos": list_photos(), "geometry": geometry()})
            elif path.startswith("/thumb/"):
                name = Path(path.removeprefix("/thumb/")).name
                self.send(200, thumbnail(name), "image/jpeg")
            elif path == "/bg":
                qs = {k: v[0] for k, v in parse_qs(u.query).items()}
                styl, phase = qs.get("styl", "zadne"), qs.get("phase", "under")
                if styl not in pozadi.STYLY or phase not in ("under", "over") or qs.get("layout") not in LAYOUTS:
                    return self.send(400, b"bad request", "text/plain")
                page = int(qs.get("page", 0))
                if not 0 <= page <= 12:
                    return self.send(400, b"bad request", "text/plain")
                png = render_background(styl, page, qs["layout"], qs.get("sub") == "1", phase)
                self.send(200, png, "image/png")
            elif path.startswith("/out/") and path.endswith(".pdf"):
                f = ROOT / "out" / Path(path).name
                self.send(200, f.read_bytes(), "application/pdf")
            else:
                self.send(404, b"not found", "text/plain")
        except FileNotFoundError:
            self.send(404, b"not found", "text/plain")
        except Exception as e:
            self.json({"error": str(e)}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            if u.path == "/api/save":
                save_config(json.loads(self.body()))
                self.json({"ok": True})
            elif u.path == "/api/upload":
                name = parse_qs(u.query).get("name", ["foto.jpg"])[0]
                if Path(name).suffix.lower() not in EXTS:
                    return self.json({"error": f"nepodporovaný formát: {name}"}, 400)
                PHOTOS.mkdir(exist_ok=True)
                final = safe_name(name)
                (PHOTOS / final).write_bytes(self.body())
                self.json({"name": final})
            elif u.path == "/api/build":
                self.json({"log": run_build()})
            else:
                self.send(404, b"not found", "text/plain")
        except Exception as e:
            self.json({"error": str(e)}, 500)


def main() -> None:
    PHOTOS.mkdir(exist_ok=True)
    kalendar.config_path()  # vytvoří kalendar.toml z příkladu, pokud chybí
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Editor kalendáře běží na {url}  (ukončení: Ctrl+C)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
