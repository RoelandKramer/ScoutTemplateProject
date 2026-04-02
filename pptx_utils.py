"""Utility functions for filling FC Den Bosch scouting PowerPoint templates."""

import copy
import io
import re
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.shapes.picture import Movie

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


def _stop_srgb(gs_element) -> str | None:
    """Return the uppercase srgbClr val from an <a:gs> stop, or None."""
    clr = gs_element.find(qn('a:srgbClr'))
    return clr.get('val', '').upper() if clr is not None else None


def _get_star_fill_value(shape) -> float:
    """Return 1.0 (full yellow), 0.5 (half-yellow gradient), or 0.0 (empty).

    Handles three fill representations:
      • solidFill srgbClr FFD932            → 1.0
      • solidFill srgbClr FFFFFF            → 0.0
      • our exact half-star gradFill        → 0.5
      • Keynote gradFill for yellow star    → 1.0  (has a FFD932 stop)
      • Keynote gradFill for white star     → 0.0  (all stops are FFFFFF)
      • solidFill with non-srgb color ref   → 1.0  (treat as filled; empty = white)
    """
    try:
        spPr = shape._element.spPr

        grad = spPr.find(qn('a:gradFill'))
        if grad is not None:
            gsLst = grad.find(qn('a:gsLst'))
            stops = gsLst.findall(qn('a:gs')) if gsLst is not None else []

            if len(stops) == 4:
                colors = [_stop_srgb(s) for s in stops]
                positions = [int(s.get('pos', '0')) for s in stops]
                # Our exact half-star: sharp FFD932→FFFFFF split at 50 %
                if (colors == ['FFD932', 'FFD932', 'FFFFFF', 'FFFFFF'] and
                        positions == [0, 49999, 50000, 100000]):
                    return 0.5

            # Any stop is yellow → Keynote-converted yellow star
            if any(_stop_srgb(s) == 'FFD932' for s in stops):
                return 1.0
            # All stops are explicitly white → empty star
            if stops and all(_stop_srgb(s) == 'FFFFFF' for s in stops):
                return 0.0
            # Unknown gradient (theme color, etc.) — assume filled
            return 1.0

        solid = spPr.find(qn('a:solidFill'))
        if solid is not None:
            clr = solid.find(qn('a:srgbClr'))
            if clr is not None:
                val = clr.get('val', '').upper()
                if val == 'FFD932':
                    return 1.0
                if val == 'FFFFFF':
                    return 0.0
                return 1.0  # any other explicit colour → treat as filled
            # schemeClr / sysClr / etc. — empty stars are always explicit white
            if len(solid) > 0:
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


def _is_rating_anchor(shape) -> bool:
    """True if this shape is the rating oval anchor (named 'xx').

    The anchor is the circle in the template.  Its name survives Keynote
    round-trips even when Keynote empties the text and adds a separate TextBox.
    """
    return shape.name.strip().lower() == "xx"


def _is_numeric_rating_text(text: str) -> bool:
    """True if text looks like a filled-in score value."""
    t = text.strip()
    if t.lower() == "xx":
        return True
    return bool(re.fullmatch(r"\d{1,2}([.,]\d{1,2})?", t))


def _is_rating_shape(shape) -> bool:
    """True if this shape holds (or is) the overall rating — used by compatibility check."""
    if _is_rating_anchor(shape):
        return True
    if shape.has_text_frame:
        return _is_numeric_rating_text(shape.text_frame.text)
    return False


def _restore_text_frame(shape) -> None:
    """Re-add a txBody to a shape that Keynote stripped of its text frame."""
    txBody_xml = (
        '<p:txBody xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:bodyPr anchor="ctr"/>'
        '<a:lstStyle/>'
        '<a:p><a:pPr algn="ctr"/><a:r>'
        '<a:rPr lang="nl-NL" sz="3600" b="1" dirty="0"/>'
        '<a:t></a:t>'
        '</a:r></a:p>'
        '</p:txBody>'
    )
    shape._element.append(etree.fromstring(txBody_xml))


def _find_rating_text_shape(slide):
    """Return the shape whose text should be overwritten with the rating.

    Handles all known layouts produced by Keynote round-trips:

      Case 1 — Original PPTX:
                The 'xx' oval has a text frame containing 'xx' or the score.

      Case 2 — Keynote blank export:
                Keynote wraps the oval in a GroupShape (still named 'xx').
                Inside the group: one circle child + one TextBox child with
                the score text (or empty if never filled).

      Case 3 — Keynote overlay export (filled-then-exported):
                The 'xx' oval is emptied and a separate floating TextBox
                is placed on top of it whose centre aligns with the oval.

    Returns None if nothing useful is found.
    """
    anchor = None
    for shape in slide.shapes:
        if _is_rating_anchor(shape):
            anchor = shape
            break

    if anchor is None:
        return None

    # Case 1 — oval with text frame (original or already filled by this tool)
    if anchor.has_text_frame:
        return anchor

    # Case 2 — Keynote converted oval to a GroupShape named 'xx'
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    if anchor.shape_type == MSO_SHAPE_TYPE.GROUP:
        # Find the TextBox child (the circle child never has useful text)
        for child in anchor.shapes:
            if child.shape_type == MSO_SHAPE_TYPE.TEXT_BOX and child.has_text_frame:
                return child
        # No TextBox child found — return the circle child so we can write into it
        for child in anchor.shapes:
            if child.has_text_frame:
                return child

    # Case 3 — oval emptied, floating TextBox placed on top
    a_cx = anchor.left + anchor.width  // 2
    a_cy = anchor.top  + anchor.height // 2
    margin = anchor.width // 4

    for shape in slide.shapes:
        if shape is anchor:
            continue
        if not shape.has_text_frame:
            continue
        text = shape.text_frame.text.strip()
        if not _is_numeric_rating_text(text):
            continue
        cx = shape.left + shape.width  // 2
        cy = shape.top  + shape.height // 2
        if abs(cx - a_cx) <= margin and abs(cy - a_cy) <= margin:
            return shape

    # Last resort — restore the anchor's text frame if Keynote stripped it
    if not anchor.has_text_frame:
        _restore_text_frame(anchor)
    return anchor


def read_current_star_values(slide) -> list[float]:
    """Return the current rating per row as floats (supports 0.5 for half-stars)."""
    rows = get_star_rows(slide)
    return [sum(_get_star_fill_value(star) for star in row) for row in rows]


def set_rating_text(slide, rating_value: float) -> bool:
    """Write the calculated rating into the rating shape (oval or overlaid TextBox).

    Handles three cases:
      1. Original PPTX  — oval has text frame, text is 'xx' or previous score.
      2. Keynote export — oval is empty, a TextBox sits on top with the score.
      3. Keynote blank  — oval had its text frame deleted entirely by Keynote;
                          we restore the txBody before writing.
    """
    target = _find_rating_text_shape(slide)
    if target is None:
        return False

    # Case 3: Keynote stripped the text frame — restore it first
    if not target.has_text_frame:
        _restore_text_frame(target)

    rating_str = f"{rating_value:.1f}"
    tf = target.text_frame
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


# ─── Detail slide: comment text ─────────────────────────────────────────────

def get_detail_comment(slide) -> str:
    """Read the scouting comment from TextBox 31 on a detail slide."""
    for shape in slide.shapes:
        if shape.name == "TextBox 31" and shape.has_text_frame:
            return shape.text_frame.text
    return ""


def set_detail_comment(slide, comment: str) -> bool:
    """Write comment text into TextBox 31, preserving its paragraph formatting."""
    for shape in slide.shapes:
        if shape.name == "TextBox 31" and shape.has_text_frame:
            tf = shape.text_frame
            txBody = tf._txBody
            # Keep the first paragraph (contains <a:pPr> with Century Gothic formatting)
            paras = txBody.findall(qn("a:p"))
            for p in paras[1:]:
                txBody.remove(p)
            first_p = paras[0]
            # Strip all runs / line-breaks from it
            for child in list(first_p):
                if child.tag.split("}")[-1] in ("r", "br"):
                    first_p.remove(child)
            lines = comment.split("\n") if comment else [""]
            # Add text to first paragraph
            if lines[0]:
                first_p.append(_make_run(lines[0]))
            # Append extra paragraphs for each additional line (clone formatting)
            for line in lines[1:]:
                new_p = copy.deepcopy(first_p)
                for child in list(new_p):
                    if child.tag.split("}")[-1] in ("r", "br"):
                        new_p.remove(child)
                if line:
                    new_p.append(_make_run(line))
                txBody.append(new_p)
            return True
    return False


def _make_run(text: str):
    """Return an <a:r> lxml element containing the given text."""
    return etree.fromstring(
        f'<a:r xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"<a:t>{text}</a:t></a:r>"
    )


# ─── Detail slide: video ─────────────────────────────────────────────────────

_VIDEO_MIMES = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/avi",
    "wmv": "video/x-ms-wmv",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
}


def _video_mime(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp4"
    return _VIDEO_MIMES.get(ext, "video/mp4")


def extract_first_frame_jpeg(video_bytes: bytes) -> bytes | None:
    """Return JPEG bytes of the first video frame, or None on failure."""
    import os, tempfile
    try:
        import cv2
    except ImportError:
        return None
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        tmp = f.name
    try:
        cap = cv2.VideoCapture(tmp)
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return bytes(buf) if ok else None
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _find_detail_placeholder(slide):
    """Return the large placeholder Picture on a detail slide (not the logo)."""
    for shape in slide.shapes:
        if shape.shape_type == 13 and "logo" not in shape.name.lower():  # PICTURE
            return shape
    return None


def get_video_from_slide(slide) -> tuple[bytes, str] | None:
    """Return (bytes, filename) for an embedded video on the slide, or None."""
    for shape in slide.shapes:
        if not isinstance(shape, Movie):
            continue
        # The videoFile element lives under nvPicPr/nvPr with an a: prefix
        nvPr = shape._element.nvPicPr.find(qn("p:nvPr"))
        if nvPr is None:
            continue
        vid = nvPr.find(qn("a:videoFile"))
        if vid is None:
            continue
        r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        rId = vid.get(f"{{{r_ns}}}link")
        if rId and rId in slide.part.rels:
            try:
                part = slide.part.rels[rId].target_part
                return part.blob, part.partname.split("/")[-1]
            except Exception:
                pass
    return None


def embed_video_on_slide(
    prs, slide_idx: int, video_bytes: bytes, video_filename: str
) -> bool:
    """Replace the placeholder picture on a detail slide with an embedded video.

    If the slide already has an embedded video it is removed first so we do not
    accumulate duplicate media entries on repeated fills.
    """
    slide = prs.slides[slide_idx]
    spTree = slide.shapes._spTree

    # Remove any existing Movie shapes
    for shape in list(slide.shapes):
        if isinstance(shape, Movie):
            spTree.remove(shape._element)

    # Find placeholder picture and read its geometry
    placeholder = _find_detail_placeholder(slide)
    if placeholder is None:
        return False

    left, top = placeholder.left, placeholder.top
    width, height = placeholder.width, placeholder.height
    spTree.remove(placeholder._element)

    poster_jpeg = extract_first_frame_jpeg(video_bytes)
    poster_io = io.BytesIO(poster_jpeg) if poster_jpeg else None

    slide.shapes.add_movie(
        io.BytesIO(video_bytes),
        left, top, width, height,
        poster_frame_image=poster_io,
        mime_type=_video_mime(video_filename),
    )
    return True


def _apply_ratings(
    prs,
    template_cfg: dict,
    star_values: list,
    comments: list[str] | None = None,
    video_data: list | None = None,
) -> None:
    """Apply stars, rating text, comments and videos to an open presentation."""
    rating = calculate_rating(star_values, template_cfg.get("weights"))
    main_slide = prs.slides[template_cfg["rating_slide_idx"]]
    color_stars(main_slide, star_values)
    set_rating_text(main_slide, rating)

    detail_idxs = template_cfg.get("detail_slides", [])
    for i, idx in enumerate(detail_idxs):
        slide = prs.slides[idx]
        if i < len(star_values):
            color_stars(slide, [star_values[i]])
        if comments and i < len(comments) and comments[i]:
            set_detail_comment(slide, comments[i])
        if video_data and i < len(video_data) and video_data[i] is not None:
            vb, vname = video_data[i]
            embed_video_on_slide(prs, idx, vb, vname)


def fill_template(
    template_cfg: dict,
    star_values: list,
    comments: list[str] | None = None,
    video_data: list | None = None,
) -> io.BytesIO:
    """Fill a blank template file and return the result as BytesIO."""
    prs = Presentation(template_cfg["file"])
    _apply_ratings(prs, template_cfg, star_values, comments, video_data)
    output = io.BytesIO()
    prs.save(output)
    output.seek(0)
    return output


def fill_from_bytes(
    file_bytes: bytes,
    template_cfg: dict,
    star_values: list,
    comments: list[str] | None = None,
    video_data: list | None = None,
) -> io.BytesIO:
    """Fill an uploaded PPTX (raw bytes) and return the result as BytesIO."""
    prs = Presentation(io.BytesIO(file_bytes))
    _apply_ratings(prs, template_cfg, star_values, comments, video_data)
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

    has_placeholder = _find_rating_text_shape(slide) is not None
    result["has_rating_placeholder"] = has_placeholder
    if not has_placeholder:
        result["issues"].append(
            "Rating circle not found. "
            "The file may be too heavily restructured to fill automatically."
        )

    result["current_star_values"]    = read_current_star_values(slide)
    result["matched_template_name"]  = detect_template_name(slide)
    result["compatible"]             = len(result["issues"]) == 0

    # Extract per-detail-slide data (comments + videos) when a template is matched
    matched = result["matched_template_name"]
    if matched and matched in TEMPLATES:
        detail_idxs = TEMPLATES[matched].get("detail_slides", [])
        comments, videos = [], []
        for idx in detail_idxs:
            if idx < len(prs.slides):
                ds = prs.slides[idx]
                comments.append(get_detail_comment(ds))
                videos.append(get_video_from_slide(ds))
            else:
                comments.append("")
                videos.append(None)
        result["current_comments"] = comments
        result["current_videos"]   = videos
    else:
        result["current_comments"] = []
        result["current_videos"]   = []

    return result
