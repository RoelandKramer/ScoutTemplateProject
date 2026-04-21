"""PNG-overlay preview renderer.

Draws app data on top of a role-specific PNG screenshot of the PowerPoint
template. Returns PNG bytes that the app can show with st.image().

The template image is 1920x1080 (16:9). Coordinates below were measured from
the Deep Lying Playmaker #06 screenshot in PNG-player Info/.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


PNG_DIR = Path(__file__).parent / "PNG-player Info"

# role / template name -> filename inside PNG_DIR
ROLE_TO_PNG: dict[str, str] = {
    "Deep Lying Playmaker": "nr#6 DLP.001.png",
}


# ─── Field coordinate map (1920x1080, DLP template) ──────────────────────
# Each entry: (x, y, w, h, anchor) where anchor is one of
#   "lm" left-middle, "mm" center-middle, "rm" right-middle.
# For multi-line wrapped text use box-shaped entries with anchor "tl".
FIELDS: dict[str, tuple[int, int, int, int, str]] = {
    # Left column — player info (gray boxes), left-padded
    "date_of_birth":     (298, 187, 270, 43, "lm"),
    "city_of_birth":     (298, 247, 270, 42, "lm"),
    "nationality":       (298, 306, 270, 43, "lm"),
    "height":            (298, 366, 270, 42, "lm"),
    "preferred_foot":    (298, 425, 270, 43, "lm"),
    "club":              (298, 484, 270, 42, "lm"),
    "league":            (298, 543, 270, 42, "lm"),
    "agency":            (298, 601, 270, 42, "lm"),
    "agent":             (298, 659, 270, 42, "lm"),

    # Stats grid (centered in each gray cell)
    "season_matches":    (885, 100, 162, 42, "mm"),
    "career_matches":    (1073, 100, 162, 42, "mm"),
    "season_minutes":    (885, 158, 162, 43, "mm"),
    "career_minutes":    (1073, 158, 162, 43, "mm"),
    "season_goals":      (885, 220, 162, 43, "mm"),
    "career_goals":      (1073, 220, 162, 43, "mm"),
    "season_assists":    (885, 281, 162, 43, "mm"),
    "career_assists":    (1073, 281, 162, 43, "mm"),

    # Circles — rating & availability (white circles)
    "rating":            (660, 404, 222, 222, "mm"),
    "availability":      (1001, 404, 222, 223, "mm"),

    # Transfer details — right column (left-aligned)
    "end_of_contract":   (1565, 776, 270, 44, "lm"),
    "transfer_value":    (1565, 836, 270, 44, "lm"),
    "prediction_year_1": (1565, 895, 270, 44, "lm"),
    "prediction_year_2": (1565, 954, 270, 44, "lm"),
    "next_step":         (1565, 1011, 270, 44, "lm"),

    # Physical stats — appended after the bullet labels in PLAYERS PROFILE box
    "total_distance":    (137, 915, 200, 26, "lm"),
    "hi_runs":           (123, 948, 200, 26, "lm"),
    "sprints":           (127, 981, 200, 26, "lm"),
    "top_speed":         (146, 1014, 200, 26, "lm"),

    # Summary scouting (multiline, top-left, wraps within box)
    "summary":           (660, 760, 830, 285, "tl"),

    # Player name (welcome bar) — currently NOT shown on this slide PNG.
}


# ─── Font resolution ──────────────────────────────────────────────────────
# The PowerPoint uses Helvetica Neue / Avenir Next Condensed. On Windows we
# fall back to Arial; on Linux (Streamlit Cloud) to Nimbus Sans / DejaVu.
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
    font, tw, th = _fit_one_line(draw, text, w - 4, h - 2, start_size, bold)
    if anchor == "lm":
        tx = x
        ty = y + (h - th) // 2 - 2
    elif anchor == "mm":
        tx = x + (w - tw) // 2
        ty = y + (h - th) // 2 - 2
    elif anchor == "rm":
        tx = x + w - tw
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
    color, start_size: int = 22,
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


# ─── Public renderer ──────────────────────────────────────────────────────

def get_template_png_path(role: str) -> Path | None:
    """Resolve the PNG file for a given role/template name."""
    fname = ROLE_TO_PNG.get(role)
    if not fname:
        # Fallback: try fuzzy match by lowercase token
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
    """Render the preview PNG by overlaying app data on the role template.

    `data` keys map to FIELDS keys above. Missing values are skipped.
    Returns PNG bytes, or None if no template image exists for the role.
    """
    png_path = get_template_png_path(role)
    if png_path is None:
        return None

    img = Image.open(png_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    white = (255, 255, 255)
    navy = (12, 35, 92)

    # Field-specific defaults
    long_text_keys = {"summary"}
    circle_keys = {"rating", "availability"}
    on_white_keys = {"rating", "availability", "total_distance",
                     "hi_runs", "sprints", "top_speed"}

    for key, val in data.items():
        if val is None or val == "":
            continue
        if key not in FIELDS:
            continue
        x, y, w, h, anchor = FIELDS[key]
        text = str(val)
        if key == "availability" and not text.endswith("%"):
            text = f"{text}%"
        if key in long_text_keys:
            _draw_multiline(draw, text, (x, y, w, h), white)
            continue
        # Color: white text on blue, navy on white circles, white on dark band
        if key in circle_keys:
            color = navy
            start = 110
        elif key in on_white_keys:
            color = white
            start = 26
        else:
            color = white
            start = 32
        _draw_anchored(draw, text, (x, y, w, h), anchor, color, start)

    if debug:
        for key, (x, y, w, h, _a) in FIELDS.items():
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=2)

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def collect_preview_data(
    *,
    player_data: dict | None,
    tm_stats: dict | None,
    transfer_details: dict | None,
    physical_data: dict | None,
    rating_value: float | None,
    summary_text: str | None,
) -> dict:
    """Gather the bits scattered across session_state into one flat dict."""
    out: dict = {}

    if player_data:
        for k in ("date_of_birth", "city_of_birth", "nationality", "height",
                  "preferred_foot", "club", "league", "agency", "agent"):
            v = player_data.get(k)
            if v:
                out[k] = v

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

    return out


# ─── Smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    sample = {
        "date_of_birth": "12-05-2003",
        "city_of_birth": "Amsterdam",
        "nationality": "Dutch",
        "height": "182 cm",
        "preferred_foot": "Right",
        "club": "FC Den Bosch",
        "league": "KKD",
        "agency": "ProSoccer",
        "agent": "Jan Jansen",
        "season_matches": "21",
        "career_matches": "84",
        "season_minutes": "1842",
        "career_minutes": "6710",
        "season_goals": "2",
        "career_goals": "11",
        "season_assists": "5",
        "career_assists": "23",
        "rating": "7.8",
        "availability": "92%",
        "end_of_contract": "Jun 2026",
        "transfer_value": "€750K",
        "prediction_year_1": "Top KKD",
        "prediction_year_2": "Eredivisie",
        "next_step": "FC Den Bosch",
        "total_distance": "11.4 km",
        "hi_runs": "62",
        "sprints": "21",
        "top_speed": "32.1 km/h",
        "summary": "Goed positiespel, schakelt snel om. Leesvermogen op niveau "
                   "voor de KKD; technisch in nauwe ruimtes nog wisselvallig.",
    }
    out = render_png_preview(sample, "Deep Lying Playmaker", debug="--debug" in sys.argv)
    if not out:
        print("No PNG template found for role.")
        sys.exit(1)
    Path("png_preview_smoke.png").write_bytes(out)
    print("wrote png_preview_smoke.png")
