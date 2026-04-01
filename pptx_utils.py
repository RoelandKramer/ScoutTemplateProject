"""Utility functions for filling FC Den Bosch scouting PowerPoint templates."""

import io
import collections
from pptx import Presentation
from pptx.dml.color import RGBColor

YELLOW = RGBColor(0xFF, 0xD9, 0x32)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

TEMPLATES = {
    "TEST (Roeland)": {
        "file": "Template/Roeland test rating.pptx",
        "rating_slide_idx": 0,
        "variables": [
            "Doelgerichtheid",
            "Positie kiezen (A)",
            "Combinatie spel",
            "Offensief koppen",
            "Duelkracht",
            "Flair",
            "Doorzettingsvermogen",
        ],
        # Vermenigvuldigingsfactor per variable (must match variable order above)
        "weights": [1.1, 1.1, 1.0, 1.0, 1.1, 1.1, 1.0],
        "detail_slides": None,
    },
    "Wingback": {
        "file": "Template/#2 #5 Wingbacks Scouting Den Bosch (NL).pptx",
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
        # Equal weights until a Wingback factor table is provided
        "weights": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        "detail_slides": [7, 8, 9, 10, 11, 12, 13],
    },
}


def get_star_rows(slide):
    """Return list of star-shape rows, each sorted left-to-right.

    Stars are 5-point star auto-shapes (auto_shape_type == 92).
    Rows are identified by grouping shapes with similar top positions
    (within 150 000 EMU ≈ 4 mm tolerance).
    """
    stars = []
    for shape in slide.shapes:
        try:
            if shape.auto_shape_type == 92:
                stars.append(shape)
        except (ValueError, AttributeError):
            pass

    if not stars:
        return []

    tolerance = 150_000  # EMU (~4 mm)
    row_map: dict = {}

    for star in stars:
        matched = False
        for rep_top in list(row_map.keys()):
            if abs(star.top - rep_top) < tolerance:
                row_map[rep_top].append(star)
                matched = True
                break
        if not matched:
            row_map[star.top] = [star]

    return [
        sorted(row_map[top], key=lambda s: s.left)
        for top in sorted(row_map.keys())
    ]


def color_stars(slide, star_values: list[int]) -> None:
    """Colour the first N stars in each row yellow, the rest white.

    Args:
        slide: pptx slide object.
        star_values: list of integers (0–10), one per rating row.
    """
    rows = get_star_rows(slide)
    for row_stars, value in zip(rows, star_values):
        for j, star in enumerate(row_stars):
            star.fill.solid()
            star.fill.fore_color.rgb = YELLOW if j < value else WHITE


def set_rating_text(slide, rating_value: float) -> bool:
    """Find the 'xx' oval placeholder and replace its text with the rating.

    Returns True if the placeholder was found and updated.
    """
    rating_str = f"{rating_value:.1f}"
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        if shape.text_frame.text.strip().lower() == "xx":
            tf = shape.text_frame
            first = True
            for para in tf.paragraphs:
                for run in para.runs:
                    if first:
                        run.text = rating_str
                        first = False
                    else:
                        run.text = ""
            # If no runs existed, add text via the first paragraph
            if first:
                para = tf.paragraphs[0]
                para.clear()
                para.add_run().text = rating_str
            return True
    return False


def calculate_rating(values: list[int], weights: list[float] | None = None) -> float:
    """Weighted average of star values (each 0–10), rounded to one decimal.

    Formula: sum(value_i * weight_i) / sum(weight_i)
    Falls back to a simple average when no weights are provided.
    """
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        weights = [1.0] * len(values)
    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0
    return round(sum(v * w for v, w in zip(values, weights)) / total_weight, 1)


def fill_template(template_cfg: dict, star_values: list[int]) -> io.BytesIO:
    """Fill a scouting template with star ratings and calculated overall rating.

    Returns a BytesIO object containing the modified presentation.
    """
    prs = Presentation(template_cfg["file"])
    rating = calculate_rating(star_values, template_cfg.get("weights"))

    # --- Main rating card ---
    main_slide = prs.slides[template_cfg["rating_slide_idx"]]
    color_stars(main_slide, star_values)
    set_rating_text(main_slide, rating)

    # --- Individual competency detail slides (Wingback template) ---
    if template_cfg.get("detail_slides"):
        for i, idx in enumerate(template_cfg["detail_slides"]):
            if i < len(star_values):
                color_stars(prs.slides[idx], [star_values[i]])

    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output


def detect_template_name(slide) -> str | None:
    """Return the name of the best-matching TEMPLATES entry for this slide, or None."""
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


def fill_from_bytes(
    file_bytes: bytes,
    template_cfg: dict,
    star_values: list[int],
) -> io.BytesIO:
    """Fill an uploaded PPTX (supplied as raw bytes) with star ratings and rating.

    Uses the same logic as fill_template but opens from bytes instead of a path.
    """
    prs = Presentation(io.BytesIO(file_bytes))
    rating = calculate_rating(star_values, template_cfg.get("weights"))

    main_slide = prs.slides[template_cfg["rating_slide_idx"]]
    color_stars(main_slide, star_values)
    set_rating_text(main_slide, rating)

    if template_cfg.get("detail_slides"):
        for i, idx in enumerate(template_cfg["detail_slides"]):
            if i < len(star_values):
                color_stars(prs.slides[idx], [star_values[i]])

    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output


def check_template_compatibility(file_obj) -> dict:
    """Inspect an uploaded PPTX to see if it can be filled by this tool.

    Returns a dict with keys:
        compatible (bool), star_count (int), row_count (int),
        slide_idx (int|None), has_rating_placeholder (bool),
        matched_template_name (str|None), issues (list[str])
    """
    result = {
        "compatible": False,
        "star_count": 0,
        "row_count": 0,
        "slide_idx": None,
        "has_rating_placeholder": False,
        "matched_template_name": None,
        "issues": [],
    }

    try:
        prs = Presentation(file_obj)
    except Exception as exc:
        result["issues"].append(f"Could not open file: {exc}")
        return result

    # Find the slide with the most stars
    best_slide_idx = None
    best_rows: list = []

    for idx, slide in enumerate(prs.slides):
        rows = get_star_rows(slide)
        if len(rows) > len(best_rows):
            best_rows = rows
            best_slide_idx = idx

    if not best_rows:
        result["issues"].append("No star shapes (5-point stars) found in any slide.")
        return result

    result["slide_idx"] = best_slide_idx
    result["row_count"] = len(best_rows)
    result["star_count"] = sum(len(r) for r in best_rows)

    if len(best_rows) != 7:
        result["issues"].append(
            f"Expected 7 rating rows, found {len(best_rows)}."
        )

    bad_rows = [i + 1 for i, r in enumerate(best_rows) if len(r) != 10]
    if bad_rows:
        result["issues"].append(
            f"Expected 10 stars per row; rows {bad_rows} have a different count."
        )

    # Check for the 'xx' rating placeholder
    slide = prs.slides[best_slide_idx]
    has_xx = any(
        shape.has_text_frame
        and shape.text_frame.text.strip().lower() == "xx"
        for shape in slide.shapes
    )
    result["has_rating_placeholder"] = has_xx
    if not has_xx:
        result["issues"].append(
            "No 'xx' rating placeholder found on the slide."
        )

    result["matched_template_name"] = detect_template_name(slide)
    result["compatible"] = len(result["issues"]) == 0
    return result
