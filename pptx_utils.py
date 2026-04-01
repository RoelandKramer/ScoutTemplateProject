"""Utility functions for filling FC Den Bosch scouting PowerPoint templates."""

import io
import re
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn

YELLOW = RGBColor(0xFF, 0xD9, 0x32)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)

# Maximum dimension (EMU) a shape can have to be considered a star.
# Real stars are ~3–5 mm; decorative bars/ovals are much larger.
_MAX_STAR_DIM = 600_000   # ≈ 6.5 mm
_ROW_TOLERANCE = 200_000  # ≈ 2.2 mm  — vertical grouping tolerance


# ─── Template definitions ────────────────────────────────────────────────────
# variables: ordered list matching top-to-bottom star rows on the rating card.
# weights:   Vermenigvuldigingsfactor per variable (same order).
# detail_slides: indices of per-competency slides (filled with 1 row each).

TEMPLATES = {
    "Goalkeeper": {
        "file": "Template/1 Goalkeeper Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Balbehandeling",
            "Voorkomen vs verdedigen",
            "Bal verwerking",
            "Wendbaarheid",
            "Moed",
            "Onverstoorbaarheid",
        ],
        "weights": [1.1, 1.1, 1.0, 1.1, 1.1, 1.0],
        "detail_slides": list(range(7, 13)),
    },
    "Wingback": {
        "file": "Template/2  5 Wingbacks Scouting Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Overlap/Underlap",
            "Voorzetten",
            "Dribbelen met bal",
            "Snelheid",
            "Uithoudingsvermogen",
            "Wendbaarheid",
            "Doorzettingsvermogen",
        ],
        "weights": [1.1, 1.0, 1.0, 1.1, 1.0, 1.0, 1.0],
        "detail_slides": list(range(7, 14)),
    },
    "Centerback": {
        "file": "Template/3  4 Centerbacks Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Positie kiezen (V)",
            "Defensief koppen",
            "Passing",
            "Dribbelen met bal",
            "Duelkracht",
            "Snelheid",
            "Doorzettingsvermogen",
        ],
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.1, 1.0],
        "detail_slides": list(range(7, 14)),
    },
    "Deep Lying Playmaker": {
        "file": "Template/6 Deep lying playmaker Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Passing",
            "Positie kiezen (V)",
            "Dribbelen met bal",
            "Positie kiezen (A)",
            "Duelkracht",
            "Uithoudingsvermogen",
            "Snelheid",
            "Doorzettingsvermogen",
            "Onverstoorbaarheid",
        ],
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.1, 1.0, 1.1, 1.0],
        "detail_slides": list(range(8, 17)),
    },
    "Box-to-Box Midfielder": {
        "file": "Template/#8 Box-to-Box midfielder Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Passing",
            "Positie kiezen (V)",
            "Voorbij spelen tegenstander",
            "Positie kiezen (A)",
            "Duelkracht",
            "Uithoudingsvermogen",
            "Snelheid",
            "Doorzettingsvermogen",
        ],
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.1, 1.0, 1.1],
        "detail_slides": list(range(8, 16)),
    },
    "Scoring 10": {
        "file": "Template/#10 Scoring 10 Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Doelgerichtheid",
            "Diepte loopacties",
            "Positie kiezen (A)",
            "Duelkracht",
            "Uithoudingsvermogen",
            "Doorzettingsvermogen",
        ],
        "weights": [1.1, 1.0, 1.0, 1.1, 1.0, 1.1],
        "detail_slides": list(range(8, 14)),
    },
    "Dribbling Winger": {
        "file": "Template/07  11 Dribbling winger Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Voorbij tegenstander",
            "Doelgericht",
            "Voorzetten",
            "Afstandsschot",
            "Wendbaarheid",
            "Snelheid",
            "Flair",
            "Moed",
        ],
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.0, 1.1, 1.0],
        "detail_slides": list(range(7, 15)),
    },
    "Fast Winger": {
        "file": "Template/07  11 Fast winger Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Voorbij tegenstander",
            "Diepte loopacties",
            "Doelgericht",
            "Afstandsschot",
            "Snelheid",
            "Wendbaarheid",
            "Moed",
            "Flair",
        ],
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.1, 1.1, 1.0],
        "detail_slides": list(range(7, 15)),
    },
    "Finisher": {
        "file": "Template/#9 Finisher Scouting FC Den Bosch (NL).pptx",
        "rating_slide_idx": 3,
        "variables": [
            "Doelgerichtheid",
            "Positie kiezen (A)",
            "Combinatie spel",
            "Offensief koppen",
            "Duelkracht",
            "Flair",
            "Doorzettingsvermogen",
        ],
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.1, 1.0],
        "detail_slides": list(range(7, 14)),
    },
}


# ─── Star detection ──────────────────────────────────────────────────────────

def _is_star_shape(shape) -> bool:
    """Return True if the shape is a star (auto_shape type 92 OR small FREEFORM)."""
    try:
        if shape.auto_shape_type == 92:
            return True
    except (ValueError, AttributeError):
        pass
    if shape.shape_type == 5:  # FREEFORM
        return shape.width <= _MAX_STAR_DIM and shape.height <= _MAX_STAR_DIM
    return False


def get_star_rows(slide) -> list[list]:
    """Return star rows sorted top-to-bottom, each row sorted left-to-right.

    Handles both auto_shape type-92 stars (old templates) and small FREEFORM
    stars (newer templates).  Rows are identified by grouping shapes whose
    vertical positions are within _ROW_TOLERANCE of each other.
    """
    stars = [s for s in slide.shapes if _is_star_shape(s)]
    if not stars:
        return []

    row_map: dict = {}
    for star in stars:
        matched = False
        for rep_top in list(row_map.keys()):
            if abs(star.top - rep_top) < _ROW_TOLERANCE:
                row_map[rep_top].append(star)
                matched = True
                break
        if not matched:
            row_map[star.top] = [star]

    # Only keep rows that have at least 5 stars (filter out decorative singletons)
    rows = {top: shapes for top, shapes in row_map.items() if len(shapes) >= 5}

    return [
        sorted(rows[top], key=lambda s: s.left)
        for top in sorted(rows.keys())
    ]


# ─── Core operations ─────────────────────────────────────────────────────────

# OOXML gradient XML for a sharp left-half-yellow / right-half-white split.
# ang="0" in OOXML means the gradient flows left-to-right (constant-colour
# lines are vertical), so pos=0 is the left edge and pos=100000 the right.
_HALF_STAR_GRAD_XML = (
    '<a:gradFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    ' rotWithShape="1">'
    '<a:gsLst>'
    '<a:gs pos="0"><a:srgbClr val="FFD932"/></a:gs>'
    '<a:gs pos="49999"><a:srgbClr val="FFD932"/></a:gs>'
    '<a:gs pos="50000"><a:srgbClr val="FFFFFF"/></a:gs>'
    '<a:gs pos="100000"><a:srgbClr val="FFFFFF"/></a:gs>'
    '</a:gsLst>'
    '<a:lin ang="0" scaled="0"/>'
    '</a:gradFill>'
)


def _apply_half_star_fill(shape) -> None:
    """Replace the shape's fill with a sharp left-yellow / right-white gradient."""
    # Let python-pptx create the solidFill element in the correct position
    shape.fill.solid()
    shape.fill.fore_color.rgb = YELLOW  # placeholder; will be replaced below

    spPr = shape._element.spPr
    solid = spPr.find(qn('a:solidFill'))
    if solid is None:
        return
    idx = list(spPr).index(solid)
    spPr.remove(solid)
    spPr.insert(idx, etree.fromstring(_HALF_STAR_GRAD_XML))


def _get_star_fill_value(shape) -> float:
    """Return 1.0 (full yellow), 0.5 (half-yellow gradient), or 0.0 (empty)."""
    try:
        spPr = shape._element.spPr
        if spPr.find(qn('a:gradFill')) is not None:
            return 0.5
        solid = spPr.find(qn('a:solidFill'))
        if solid is not None:
            clr = solid.find(qn('a:srgbClr'))
            if clr is not None and clr.get('val', '').upper() == 'FFD932':
                return 1.0
    except Exception:
        pass
    return 0.0


def color_stars(slide, star_values: list) -> None:
    """Colour stars from each row according to values (supports 0.5 increments).

    For a value of 7.5: stars 0-6 are full yellow, star 7 is half yellow,
    stars 8-9 are white.
    """
    rows = get_star_rows(slide)
    for row_stars, value in zip(rows, star_values):
        full  = int(value)
        half  = (value % 1) >= 0.5
        for j, star in enumerate(row_stars):
            if j < full:
                star.fill.solid()
                star.fill.fore_color.rgb = YELLOW
            elif j == full and half:
                _apply_half_star_fill(star)
            else:
                star.fill.solid()
                star.fill.fore_color.rgb = WHITE


def _is_rating_shape(shape) -> bool:
    """True if this shape holds the rating value ('xx' or a filled decimal)."""
    if not shape.has_text_frame:
        return False
    text = shape.text_frame.text.strip()
    return text.lower() == "xx" or bool(re.fullmatch(r"\d+\.\d", text))


def read_current_star_values(slide) -> list[float]:
    """Return the current rating per row as floats (supports 0.5 for half-stars)."""
    rows = get_star_rows(slide)
    return [sum(_get_star_fill_value(star) for star in row) for row in rows]


def set_rating_text(slide, rating_value: float) -> bool:
    """Write the calculated rating into the 'xx' placeholder oval."""
    rating_str = f"{rating_value:.1f}"
    for shape in slide.shapes:
        if not _is_rating_shape(shape):
            continue
        tf = shape.text_frame
        first = True
        for para in tf.paragraphs:
            for run in para.runs:
                if first:
                    run.text = rating_str
                    first = False
                else:
                    run.text = ""
        if first:
            para = tf.paragraphs[0]
            para.clear()
            para.add_run().text = rating_str
        return True
    return False


def calculate_rating(values: list[int], weights: list[float] | None = None) -> float:
    """Weighted average: sum(v*w) / sum(w), rounded to one decimal."""
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        weights = [1.0] * len(values)
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return round(sum(v * w for v, w in zip(values, weights)) / total_weight, 1)


def _apply_ratings(prs, template_cfg: dict, star_values: list[int]) -> None:
    """Internal: apply star colours and rating text to an open presentation."""
    rating = calculate_rating(star_values, template_cfg.get("weights"))
    main_slide = prs.slides[template_cfg["rating_slide_idx"]]
    color_stars(main_slide, star_values)
    set_rating_text(main_slide, rating)
    if template_cfg.get("detail_slides"):
        for i, idx in enumerate(template_cfg["detail_slides"]):
            if i < len(star_values):
                color_stars(prs.slides[idx], [star_values[i]])


def fill_template(template_cfg: dict, star_values: list[int]) -> io.BytesIO:
    """Fill a blank template file and return the result as BytesIO."""
    prs = Presentation(template_cfg["file"])
    _apply_ratings(prs, template_cfg, star_values)
    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output


def fill_from_bytes(
    file_bytes: bytes,
    template_cfg: dict,
    star_values: list[int],
) -> io.BytesIO:
    """Fill an uploaded PPTX (raw bytes) and return the result as BytesIO."""
    prs = Presentation(io.BytesIO(file_bytes))
    _apply_ratings(prs, template_cfg, star_values)
    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output


# ─── Template detection & compatibility ─────────────────────────────────────

def detect_template_name(slide) -> str | None:
    """Return the best-matching TEMPLATES key for this slide, or None."""
    slide_text = " ".join(
        shape.text_frame.text.lower()
        for shape in slide.shapes
        if shape.has_text_frame
    )
    best_name: str | None = None
    best_count = 0
    for name, cfg in TEMPLATES.items():
        matches = sum(1 for v in cfg["variables"] if v.lower() in slide_text)
        if matches > best_count:
            best_count = matches
            best_name = name
    return best_name if best_count >= 3 else None


def check_template_compatibility(file_obj) -> dict:
    """Inspect an uploaded PPTX and return a compatibility report.

    Keys: compatible, star_count, row_count, slide_idx,
          has_rating_placeholder, matched_template_name,
          current_star_values, issues
    """
    result = {
        "compatible": False,
        "star_count": 0,
        "row_count": 0,
        "slide_idx": None,
        "has_rating_placeholder": False,
        "matched_template_name": None,
        "current_star_values": [],
        "issues": [],
    }

    try:
        prs = Presentation(file_obj)
    except Exception as exc:
        result["issues"].append(f"Could not open file: {exc}")
        return result

    # Find the slide with the most star rows
    best_slide_idx = None
    best_rows: list = []
    for idx, slide in enumerate(prs.slides):
        rows = get_star_rows(slide)
        if len(rows) > len(best_rows):
            best_rows = rows
            best_slide_idx = idx

    if not best_rows:
        result["issues"].append("No star shapes found in any slide.")
        return result

    slide = prs.slides[best_slide_idx]
    result["slide_idx"]  = best_slide_idx
    result["row_count"]  = len(best_rows)
    result["star_count"] = sum(len(r) for r in best_rows)

    bad_rows = [i + 1 for i, r in enumerate(best_rows) if len(r) != 10]
    if bad_rows:
        result["issues"].append(
            f"Expected 10 stars per row; rows {bad_rows} have a different count."
        )

    has_placeholder = any(_is_rating_shape(s) for s in slide.shapes)
    result["has_rating_placeholder"] = has_placeholder
    if not has_placeholder:
        result["issues"].append(
            "No rating placeholder found ('xx' or an existing score)."
        )

    result["current_star_values"]    = read_current_star_values(slide)
    result["matched_template_name"]  = detect_template_name(slide)
    result["compatible"]             = len(result["issues"]) == 0
    return result
