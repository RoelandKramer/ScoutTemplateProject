"""PNG-overlay preview renderer.

Draws app data on top of a role-specific PNG screenshot of the PowerPoint
template. Returns PNG bytes that the app can show with st.image().

Templates are 1920x1080. Layout (gray boxes, circles, dark-navy box,
transfer column) is identical across roles — only the right-side competency
labels differ. Competency-row y-positions are detected per template and
cached at first use.
"""

from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps


PNG_DIR = Path(__file__).parent / "PNG-player Info"

# role / template name (TEMPLATES key) -> filename inside PNG_DIR
ROLE_TO_PNG: dict[str, str] = {
    "Goalkeeper":              "nr#1 GK.001.png",
    "Wingback":                "nr#25 WB.001.png",
    "Centerback":              "nr#34 CB.001.png",
    "Deep Lying Playmaker":    "nr#6 DLP.001.png",
    "Box-to-Box Midfielder":   "nr#8 BTB.001.png",
    "Scoring 10":              "nr#10 scoring 10.001.png",
    "Dribbling Winger":        "nr#7 DW.001.png",
    "Fast Winger":             "nr#7 FW.001.png",
    "Finisher":                "nr#9 finisher.001.png",
}


# ─── Field coordinate map (1920x1080) ────────────────────────────────────
# (x_left, y_top, w, h, anchor)  anchor in {"lm","mm","rm","tl"}
FIELDS: dict[str, tuple[int, int, int, int, str]] = {
    # Player info — left column gray boxes (text BLACK, centered vertically)
    "date_of_birth":     (293, 166, 274, 43, "mm"),
    "city_of_birth":     (293, 226, 274, 42, "mm"),
    "nationality":       (293, 285, 274, 43, "mm"),
    "height":            (293, 345, 274, 42, "mm"),
    "preferred_foot":    (293, 404, 274, 43, "mm"),
    "club":              (293, 463, 274, 42, "mm"),
    "league":            (293, 522, 274, 42, "mm"),
    "agency":            (293, 580, 274, 42, "mm"),
    "agent":             (293, 638, 274, 42, "mm"),

    # Stats grid — centered in each gray cell (text BLACK)
    "season_matches":    (885, 79, 162, 42, "mm"),
    "career_matches":    (1073, 79, 162, 42, "mm"),
    "season_minutes":    (885, 136, 162, 43, "mm"),
    "career_minutes":    (1073, 136, 162, 43, "mm"),
    "season_goals":      (885, 198, 162, 43, "mm"),
    "career_goals":      (1073, 198, 162, 43, "mm"),
    "season_assists":    (885, 259, 162, 43, "mm"),
    "career_assists":    (1073, 259, 162, 43, "mm"),

    # Circles — rating & availability (white circle, NAVY text)
    "rating":            (660, 404, 222, 222, "mm"),
    "availability":      (1001, 404, 222, 223, "mm"),

    # Transfer details — right column gray boxes (text BLACK, centered)
    "end_of_contract":   (1554, 754, 283, 44, "mm"),
    "transfer_value":    (1554, 814, 283, 44, "mm"),
    "prediction_year_1": (1554, 873, 283, 44, "mm"),
    "prediction_year_2": (1554, 932, 283, 44, "mm"),
    "next_step":         (1554, 989, 283, 44, "mm"),

    # Physical stats — value sits directly to the right of each label, on the
    # same line. Label x-ends detected from the templates:
    #   "Total Distance:" → 170 │ "HI Runs:" → 117
    #   "Sprints:"        → 114 │ "Top Speed:" → 139
    # We add a small gap so the value isn't glued to the colon.
    "total_distance":    (180, 916, 200, 24, "lm"),
    "hi_runs":           (127, 949, 200, 24, "lm"),
    "sprints":           (124, 982, 200, 24, "lm"),
    "top_speed":         (149, 1015, 200, 24, "lm"),

    # Summary scouting (multiline wrapped text, white on blue)
    "summary":           (660, 760, 830, 285, "tl"),

    # Player photo — circle in top-left
    "player_photo":      (37, 24, 110, 110, "tl"),

    # Player name — to the right of photo, above the gold divider line at y≈141
    "player_name":       (160, 50, 400, 80, "lm"),

    # Scouting sessions — inside the light-blue content box to the right of
    # the "SCOUTING / Sci Sports" header (TextBox 23 on the rating slide).
    "scouting_dates":    (1490, 55, 400, 220, "tl"),
}


# ─── Font resolution ──────────────────────────────────────────────────────
# PowerPoint uses Helvetica Neue; we fall back through Arial / Nimbus Sans.
_FONT_CANDIDATES_REGULAR = [
    "C:/Windows/Fonts/HelveticaNeue.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/urw-base35/NimbusSans-Regular.otf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_CANDIDATES_BOLD = [
    "C:/Windows/Fonts/HelveticaNeue-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/urw-base35/NimbusSans-Bold.otf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = _FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REGULAR
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ─── Drawing helpers ──────────────────────────────────────────────────────

def _measure(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_one_line(
    draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int,
    start_size: int, bold: bool = False,
) -> tuple[ImageFont.FreeTypeFont, int, int]:
    size = start_size
    while size > 8:
        font = _load_font(size, bold=bold)
        w, h = _measure(draw, text, font)
        if w <= max_w and h <= max_h:
            return font, w, h
        size -= 1
    font = _load_font(8, bold=bold)
    return (font, *_measure(draw, text, font))


def _draw_anchored(
    draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int],
    anchor: str, color, start_size: int, bold: bool = False,
) -> None:
    if not text:
        return
    x, y, w, h = box
    font, tw, th = _fit_one_line(draw, text, w - 6, h - 4, start_size, bold)
    if anchor == "lm":
        tx = x + 2
        ty = y + (h - th) // 2 - 2
    elif anchor == "mm":
        tx = x + (w - tw) // 2
        ty = y + (h - th) // 2 - 2
    elif anchor == "rm":
        tx = x + w - tw - 2
        ty = y + (h - th) // 2 - 2
    else:  # tl
        tx, ty = x, y
    draw.text((tx, ty), text, font=font, fill=color)


def _wrap_text(text: str, font, draw, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = f"{cur} {w}"
            if _measure(draw, trial, font)[0] <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _draw_multiline(
    draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int],
    color, start_size: int = 24,
) -> None:
    if not text:
        return
    x, y, w, h = box
    size = start_size
    while size > 10:
        font = _load_font(size)
        lines = _wrap_text(text, font, draw, w)
        line_h = _measure(draw, "Hg", font)[1] + 4
        if line_h * len(lines) <= h:
            break
        size -= 1
    font = _load_font(size)
    lines = _wrap_text(text, font, draw, w)
    line_h = _measure(draw, "Hg", font)[1] + 4
    cy = y
    for line in lines:
        draw.text((x, cy), line, font=font, fill=color)
        cy += line_h
        if cy + line_h > y + h:
            break


def _paste_circular_photo(canvas: Image.Image, photo_bytes: bytes,
                          box: tuple) -> None:
    """Crop photo to a circle and paste into the given square box.

    Accepts either (x, y, w, h) or (x, y, w, h, anchor) — anchor is ignored.
    """
    if not photo_bytes:
        return
    x, y, w, h = box[0], box[1], box[2], box[3]
    size = min(w, h)
    try:
        src = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    except Exception:
        return
    src = ImageOps.fit(src, (size, size), method=Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    src.putalpha(mask)
    canvas.paste(src, (x, y), src)


# ─── Per-template competency row detection (cached) ──────────────────────

_COMP_ROWS_CACHE: dict[str, list[int]] = {}
_COMP_ROWS_LOCK = threading.Lock()


def _detect_competency_rows(png_path: Path) -> list[int]:
    """Return list of mid-y positions (px) for each competency label row."""
    key = str(png_path)
    with _COMP_ROWS_LOCK:
        cached = _COMP_ROWS_CACHE.get(key)
        if cached is not None:
            return cached
    import numpy as np
    im = np.array(Image.open(png_path).convert("RGB"))
    r, g, b = im[:, :, 0], im[:, :, 1], im[:, :, 2]
    white = (r > 220) & (g > 220) & (b > 220)
    bands: list[int] = []
    in_run = False
    band_start = 0
    for y in range(340, 700):
        n = white[y, 1280:1900].sum()
        if n > 5 and not in_run:
            band_start = y
            in_run = True
        elif n <= 5 and in_run:
            if y - band_start > 5:
                bands.append((band_start + y) // 2)
            in_run = False
    with _COMP_ROWS_LOCK:
        _COMP_ROWS_CACHE[key] = bands
    return bands


def _draw_competency_stars(
    draw: ImageDraw.ImageDraw, png_path: Path, star_values: list[float],
) -> None:
    """Render a 10-star bar at the right of each competency row (0–10 → 10★)."""
    if not star_values:
        return
    rows = _detect_competency_rows(png_path)
    if not rows:
        return
    n = min(len(rows), len(star_values))
    star_count = 10
    star_size = 16
    gap = 3
    star_full = (240, 200, 60)     # gold
    star_empty = (90, 100, 130)    # muted

    for i in range(n):
        ymid = rows[i]
        val = star_values[i] or 0
        # Number of fully-lit stars (0..10) — round to nearest whole star.
        try:
            n_full = int(round(float(val)))
        except Exception:
            n_full = 0
        n_full = max(0, min(star_count, n_full))
        # Right-align star bar near the right edge of the scouting box (~1900)
        bar_w = star_count * star_size + (star_count - 1) * gap
        bx = 1900 - bar_w - 8
        by = ymid - star_size // 2
        for s in range(star_count):
            cx = bx + s * (star_size + gap)
            fill = star_full if s < n_full else star_empty
            _draw_star(draw, cx + star_size // 2, by + star_size // 2,
                       star_size // 2, fill)


def _draw_star(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill) -> None:
    """Draw a 5-pointed star centered at (cx, cy) with outer radius r."""
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    draw.polygon(pts, fill=fill)


# ─── Public renderer ──────────────────────────────────────────────────────

def get_template_png_path(role: str) -> Path | None:
    """Resolve the PNG file for a given role/template name."""
    fname = ROLE_TO_PNG.get(role)
    if not fname:
        target = role.lower().replace(" ", "")
        for k, v in ROLE_TO_PNG.items():
            if k.lower().replace(" ", "") == target:
                fname = v
                break
    if not fname:
        return None
    p = PNG_DIR / fname
    return p if p.exists() else None


def render_png_preview(
    data: dict,
    role: str,
    *,
    debug: bool = False,
) -> bytes | None:
    """Render the preview PNG by overlaying app data on the role template."""
    png_path = get_template_png_path(role)
    if png_path is None:
        return None

    img = Image.open(png_path).convert("RGBA")

    # Player photo first (so circular alpha shows the dot through if no photo)
    photo = data.get("player_photo_bytes") or data.get("player_photo")
    if photo:
        _paste_circular_photo(img, photo, FIELDS["player_photo"])

    draw = ImageDraw.Draw(img)

    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    NAVY = (12, 35, 92)

    # Field-specific render rules
    long_text_keys = {"summary", "scouting_dates"}
    on_white_keys = {"rating", "availability"}
    on_dark_keys = {"total_distance", "hi_runs", "sprints", "top_speed",
                    "summary", "player_name"}
    # scouting_dates sits on the light-blue content box — black text.
    on_light_keys = {"scouting_dates"}

    for key, val in data.items():
        if val is None or val == "":
            continue
        if key not in FIELDS:
            continue
        if key in {"player_photo_bytes", "player_photo"}:
            continue
        x, y, w, h, anchor = FIELDS[key]
        text = str(val)
        if key == "availability" and not text.endswith("%"):
            try:
                text = f"{int(round(float(text)))}%"
            except Exception:
                text = f"{text}%"
        if key in long_text_keys:
            start = 22 if key == "scouting_dates" else 24
            color = BLACK if key in on_light_keys else WHITE
            _draw_multiline(draw, text, (x, y, w, h), color, start_size=start)
            continue
        if key in on_white_keys:
            color = NAVY
            start = 96 if key in {"rating", "availability"} else 26
        elif key in on_dark_keys:
            color = WHITE
            start = 36 if key == "player_name" else 22
        else:
            color = BLACK
            start = 28
        bold = key == "player_name"
        _draw_anchored(draw, text, (x, y, w, h), anchor, color, start, bold=bold)

    # Scouting stars (per-template detected rows)
    stars = data.get("star_values")
    if stars:
        _draw_competency_stars(draw, png_path, stars)

    if debug:
        for key, (x, y, w, h, _a) in FIELDS.items():
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=2)
        for ymid in _detect_competency_rows(png_path):
            draw.line([(1280, ymid), (1900, ymid)], fill=(0, 255, 0), width=1)

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def collect_preview_data(
    *,
    player_data: dict | None,
    tm_stats: dict | None,
    transfer_details: dict | None,
    physical_data: dict | None,
    rating_value: float | None,
    summary_text: str | None,
    star_values: list[float] | None = None,
    player_photo_bytes: bytes | None = None,
    scouting_dates: list | None = None,
) -> dict:
    """Gather session_state pieces into one flat dict for render_png_preview."""
    out: dict = {}

    if player_data:
        for k in ("date_of_birth", "city_of_birth", "nationality", "height",
                  "preferred_foot", "club", "league", "agency", "agent"):
            v = player_data.get(k)
            if v:
                out[k] = v
        name = player_data.get("name")
        if name:
            out["player_name"] = name

    if tm_stats:
        for k in ("season_matches", "career_matches", "season_minutes",
                  "career_minutes", "season_goals", "career_goals",
                  "season_assists", "career_assists"):
            v = tm_stats.get(k)
            if v not in (None, ""):
                out[k] = v
        pct = tm_stats.get("availability_pct")
        if pct is not None:
            try:
                out["availability"] = f"{int(round(float(pct)))}%"
            except Exception:
                out["availability"] = str(pct)

    if transfer_details:
        for k in ("end_of_contract", "transfer_value", "prediction_year_1",
                  "prediction_year_2", "next_step"):
            v = transfer_details.get(k)
            if v:
                out[k] = v

    if physical_data:
        td = physical_data.get("total_distance")
        hi = physical_data.get("hi_runs")
        sp = physical_data.get("sprint_efforts")
        ts = physical_data.get("top_speed")
        if td is not None: out["total_distance"] = f"{td} km"
        if hi is not None: out["hi_runs"] = str(hi)
        if sp is not None: out["sprints"] = str(sp)
        if ts is not None: out["top_speed"] = f"{ts} km/h"

    if rating_value is not None:
        try:
            out["rating"] = f"{float(rating_value):.1f}"
        except Exception:
            out["rating"] = str(rating_value)

    if summary_text:
        out["summary"] = summary_text

    if star_values:
        out["star_values"] = list(star_values)

    if player_photo_bytes:
        out["player_photo_bytes"] = player_photo_bytes

    if scouting_dates:
        lines: list[str] = []
        for entry in scouting_dates:
            e = entry or {}
            label = (e.get("label") or "").strip()
            if label:
                lines.append(label)
                continue
            d = (e.get("date") or "").strip().replace("/", "-")
            ttype = (e.get("type") or "").strip()
            if d and ttype:
                lines.append(f"{d}: {ttype}")
            elif d:
                lines.append(d)
        if lines:
            out["scouting_dates"] = "\n".join(lines)

    return out


# ─── Smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample = {
        "player_name": "Aaron Bouwman",
        "date_of_birth": "28/07/2000",
        "city_of_birth": "Pontoise",
        "nationality": "Congo, France",
        "height": "1.85 M",
        "preferred_foot": "Right",
        "club": "FC Den Bosch",
        "league": "Keuken Kampioen Divisie",
        "agency": "ProSoccer",
        "agent": "Jan Jansen",
        "season_matches": 66, "career_matches": 100,
        "season_minutes": 5860, "career_minutes": 7936,
        "season_goals": 30, "career_goals": 32,
        "season_assists": 20, "career_assists": 22,
        "rating": "7.4",
        "availability": "92%",
        "end_of_contract": "30/06/2026",
        "transfer_value": "€150K",
        "prediction_year_1": "Top KKD",
        "prediction_year_2": "Eredivisie",
        "next_step": "Barcelona",
        "total_distance": "11.4 km",
        "hi_runs": "62",
        "sprints": "21",
        "top_speed": "32.1 km/h",
        "summary": "Goed positiespel, schakelt snel om. Leesvermogen op niveau "
                   "voor de KKD; technisch in nauwe ruimtes nog wisselvallig.",
        "star_values": [8.0, 7.0, 6.5, 9.0, 7.5, 6.0, 8.5, 7.0, 5.5],
    }
    role = sys.argv[1] if len(sys.argv) > 1 else "Deep Lying Playmaker"
    out = render_png_preview(sample, role, debug="--debug" in sys.argv)
    if not out:
        print(f"No PNG template for {role}")
        sys.exit(1)
    Path("png_preview_smoke.png").write_bytes(out)
    print(f"wrote png_preview_smoke.png ({role})")
