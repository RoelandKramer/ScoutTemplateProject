"""FC Den Bosch — Scout Rating Tool (Streamlit app)."""

import io
import streamlit as st
from pptx_utils import TEMPLATES, fill_template, fill_from_bytes, check_template_compatibility

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FC Den Bosch Scout Tool",
    page_icon="⚽",
    layout="centered",
)

# ─── Styling ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* ── Base ── */
    [data-testid="stAppViewContainer"] { background: #f7f9fc; }
    [data-testid="stHeader"]           { background: #f7f9fc; }
    [data-testid="stSidebar"]          { background: #eef4ff; }

    /* ── Typography ── */
    h1, h2, h3, h4 { color: #1f2937 !important; }
    p, li, label, .stMarkdown { color: #374151 !important; }

    /* ── Tabs ── */
    [data-baseweb="tab-list"] {
        background: #edf4ff !important;
        border: 1px solid #cfe0ff !important;
        border-radius: 10px !important;
        padding: 4px !important;
    }
    [data-baseweb="tab"] {
        background: transparent !important;
        color: #4b5563 !important;
        font-weight: 600;
        border-radius: 8px !important;
    }
    [data-baseweb="tab"]:hover {
        background: #dbeafe !important;
        color: #1d4ed8 !important;
    }
    [aria-selected="true"] {
        background: #dbeafe !important;
        color: #1d4ed8 !important;
        border-bottom: 2px solid #2563eb !important;
    }

    /* ── Variable label ── */
    .var-label {
        font-size: 14px;
        font-weight: 700;
        color: #1e3a8a;
        margin-bottom: 2px;
        letter-spacing: 0.3px;
    }

    /* ── Star row ── */
    .star-row {
        width: 60%;
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 26px;
        line-height: 1.2;
        margin-top: 0;
        margin-bottom: 10px;
    }
    .star-row span {
        display: inline-block;
        text-align: center;
    }

    /* ── Divider ── */
    hr { border-color: #dbe4f0 !important; }

    /* ── Select box / dropdown ── */
    [data-baseweb="select"] > div {
        background-color: #dbeafe !important;
        border: 1px solid #3b82f6 !important;
        border-radius: 8px !important;
    }
    [data-baseweb="select"] * { color: #1e3a8a !important; }

    [data-baseweb="popover"] [role="listbox"] {
        background-color: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 8px !important;
    }
    [data-baseweb="popover"] [role="option"] {
        background-color: #ffffff !important;
        color: #374151 !important;
    }
    [data-baseweb="popover"] [role="option"]:hover {
        background-color: #dbeafe !important;
        color: #1e3a8a !important;
    }
    [data-baseweb="popover"] [aria-selected="true"] {
        background-color: #bfdbfe !important;
        color: #1e3a8a !important;
    }

    /* ── Slider ── */
    [data-testid="stSlider"] > div > div > div > div {
        background: #4a7fd4 !important;
    }
    [data-baseweb="slider"] [role="slider"] {
        width: 18px !important;
        height: 18px !important;
        background-color: #ffffff !important;
        border: 3px solid #000000 !important;
        box-shadow: none !important;
    }

    /* ── Primary button ── */
    div.stButton > button[kind="primary"] {
        background-color: #4a7fd4;
        color: #ffffff;
        border: none;
        font-weight: 700;
        font-size: 15px;
        padding: 0.55rem 1.2rem;
        border-radius: 6px;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #3a6ec0;
        color: #ffffff;
    }

    /* ── Download button ── */
    [data-testid="stDownloadButton"] > button {
        background-color: #2e7d4f !important;
        color: #ffffff !important;
        border: none !important;
        font-weight: 700 !important;
        border-radius: 6px !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background-color: #256040 !important;
    }

    /* ── Info / success / error boxes ── */
    [data-testid="stAlert"] { border-radius: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _star_row_html(value: float) -> str:
    """Build an HTML star row for a given value (supports 0.5 half-stars)."""
    gold, dark = "#FFD932", "#3a4060"
    full = int(value)
    has_half = (value % 1) >= 0.5
    parts = []
    for i in range(10):
        if i < full:
            parts.append(f'<span style="color:{gold}">★</span>')
        elif i == full and has_half:
            parts.append(
                f'<span style="'
                f'background:linear-gradient(to right,{gold} 50%,{dark} 50%);'
                f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
                f'background-clip:text;color:transparent;">★</span>'
            )
        else:
            parts.append(f'<span style="color:{dark}">★</span>')
    return f'<div class="star-row">{"".join(parts)}</div>'


def star_selector(label: str, key: str, default: float = 0.0) -> float:
    """Labelled slider (0–10, step 0.5) with a live half-star display."""
    st.markdown(f'<div class="var-label">{label}</div>', unsafe_allow_html=True)
    if key not in st.session_state:
        st.session_state[key] = float(default)
    value: float = st.slider(
        label,
        min_value=0.0,
        max_value=10.0,
        step=0.5,
        key=key,
        label_visibility="collapsed",
    )
    st.markdown(_star_row_html(value), unsafe_allow_html=True)
    return value


def competency_sections(
    variables: list[str],
    key_prefix: str,
    defaults_stars: list[float] | None = None,
    defaults_comments: list[str] | None = None,
    defaults_videos: list | None = None,
) -> tuple[list[float], list[str], list]:
    """Render per-competency expanders (video + stars + comment).

    Returns (star_values, comments, video_data) where video_data is a list of
    (bytes, filename) tuples or None entries.
    """
    n = len(variables)
    if defaults_stars is None:
        defaults_stars = [0.0] * n
    if defaults_comments is None:
        defaults_comments = [""] * n
    if defaults_videos is None:
        defaults_videos = [None] * n

    star_values, comments, video_data = [], [], []

    for i, var in enumerate(variables):
        video_key    = f"{key_prefix}_{i}_video"
        comment_key  = f"{key_prefix}_{i}_comment"

        # Seed session state only on first encounter
        if comment_key not in st.session_state:
            st.session_state[comment_key] = defaults_comments[i]
        if video_key not in st.session_state:
            st.session_state[video_key] = defaults_videos[i]  # (bytes, name) or None

        with st.expander(f"📽  {var}", expanded=False):
            # ── Video ────────────────────────────────────────────────────
            existing_video = st.session_state[video_key]
            if existing_video is not None:
                vbytes, vname = existing_video
                st.caption(f"Current video: **{vname}**")
                st.video(vbytes)
                st.caption("Upload a new clip below to replace it.")

            uploaded_video = st.file_uploader(
                "Video clip (mp4, mov, avi, wmv, mkv)",
                type=["mp4", "mov", "avi", "wmv", "mkv", "webm"],
                key=f"{key_prefix}_{i}_uploader",
                label_visibility="collapsed" if existing_video is not None else "visible",
            )
            if uploaded_video is not None:
                new_entry = (uploaded_video.getvalue(), uploaded_video.name)
                st.session_state[video_key] = new_entry
                st.video(uploaded_video.getvalue())

            # ── Stars ────────────────────────────────────────────────────
            st.markdown("**Rating:**")
            val = star_selector(var, key=f"{key_prefix}_{i}", default=defaults_stars[i])

            # ── Comment ──────────────────────────────────────────────────
            st.text_area(
                "Scouting notes",
                key=comment_key,
                height=90,
                placeholder="Add your notes here…",
            )

        star_values.append(val)
        comments.append(st.session_state[comment_key])
        video_data.append(st.session_state[video_key])

    return star_values, comments, video_data


# ─── App ─────────────────────────────────────────────────────────────────────

st.title("⚽ Rating Calculator for Scouting Reports")
st.caption(
    "Fill out scouting report templates with videos, star ratings and comments. "
    "Start from an empty template or upload your current work to update it."
)
tab_empty, tab_upload = st.tabs([
    "📋  Fill Empty Template",
    "📂  Upload Current Work",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Fill an empty template from scratch
# ══════════════════════════════════════════════════════════════════════════════
with tab_empty:
    st.header("Fill Empty Template")
    st.caption("Choose a player type, fill in each competency, and download the report.")

    template_name: str = st.selectbox(
        "Player type / template:",
        list(TEMPLATES.keys()),
        key="empty_template_select",
    )
    template_cfg = TEMPLATES[template_name]

    # Reset all per-competency state when the template selection changes
    if st.session_state.get("empty_prev_template") != template_name:
        for i in range(20):
            st.session_state[f"empty_{i}"]         = 0.0
            st.session_state[f"empty_{i}_video"]   = None
            st.session_state[f"empty_{i}_comment"] = ""
        st.session_state["empty_prev_template"] = template_name

    st.markdown("---")
    st.subheader("Rate each competency (0–10), add a video clip and notes")

    star_values, comments, video_data = competency_sections(
        template_cfg["variables"],
        key_prefix="empty",
    )

    st.markdown("---")
    if st.button("Generate PowerPoint ▶", type="primary", use_container_width=True, key="empty_generate"):
        with st.spinner("Building your scouting report …"):
            output = fill_template(template_cfg, star_values, comments, video_data)
        st.success("Report is ready!")
        st.download_button(
            label="📥  Download PowerPoint",
            data=output,
            file_name=f"Scout_Report_{template_name.replace(' ', '_').replace('/', '_')}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Upload an existing file and update it
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("Upload Current Work")
    st.caption(
        "Upload your existing PowerPoint. "
        "The tool reads the current stars, videos and notes so you can adjust them."
    )

    uploaded = st.file_uploader("Upload your .pptx file", type=["pptx"], key="upload_widget")

    # ── Store bytes + run check whenever a new file arrives ──────────────────
    if uploaded is not None:
        file_key = f"{uploaded.name}_{uploaded.size}"
        if st.session_state.get("upload_file_key") != file_key:
            file_bytes = uploaded.getvalue()
            with st.spinner("Checking your file …"):
                check_result = check_template_compatibility(io.BytesIO(file_bytes))
            st.session_state["upload_file_key"]     = file_key
            st.session_state["upload_bytes"]        = file_bytes
            st.session_state["upload_filename"]     = uploaded.name
            st.session_state["upload_check_result"] = check_result
            # Seed star sliders from existing values
            for i, val in enumerate(check_result.get("current_star_values", [])):
                st.session_state[f"upload_{i}"] = float(val)
            # Seed comment and video state from PPTX
            for i, cmt in enumerate(check_result.get("current_comments", [])):
                st.session_state[f"upload_{i}_comment"] = cmt or ""
            for i, vid in enumerate(check_result.get("current_videos", [])):
                st.session_state[f"upload_{i}_video"] = vid  # (bytes, name) or None

    # ── Show results ─────────────────────────────────────────────────────────
    check_result = st.session_state.get("upload_check_result")

    if check_result is None:
        st.info("Upload a .pptx file above to get started.")

    elif not check_result["compatible"]:
        st.error("❌  This file is **not compatible** with the star-rating system.")
        for issue in check_result["issues"]:
            st.write(f"- {issue}")
        if check_result["star_count"] > 0:
            st.info(
                f"Partial match: found {check_result['star_count']} stars "
                f"in {check_result['row_count']} row(s) on slide "
                f"{check_result['slide_idx'] + 1}."
            )

    else:
        # ── Compatible — resolve template config ──────────────────────────
        matched_name = check_result.get("matched_template_name")

        if matched_name and matched_name in TEMPLATES:
            st.success(f"✅  File is compatible — detected template: **{matched_name}**")
            template_cfg = TEMPLATES[matched_name]
        else:
            st.success("✅  File is compatible.")
            st.warning("Could not auto-detect the template type. Please select it below.")
            matched_name = st.selectbox(
                "Select the matching template type:",
                list(TEMPLATES.keys()),
                key="upload_template_fallback",
            )
            template_cfg = TEMPLATES[matched_name]

        st.caption(
            f"Slide {check_result['slide_idx'] + 1} · "
            f"{check_result['row_count']} rows · "
            f"{check_result['star_count']} stars · "
            f"Rating circle {'found ✓' if check_result['has_rating_placeholder'] else 'not found ✗'}"
        )

        st.markdown("---")
        st.subheader("Adjust each competency — stars, video clip and notes")

        current_stars    = check_result.get("current_star_values", [])
        current_comments = check_result.get("current_comments", [])
        current_videos   = check_result.get("current_videos", [])

        star_values, comments, video_data = competency_sections(
            template_cfg["variables"],
            key_prefix="upload",
            defaults_stars=current_stars,
            defaults_comments=current_comments,
            defaults_videos=current_videos,
        )

        st.markdown("---")
        if st.button("Generate PowerPoint ▶", type="primary", use_container_width=True, key="upload_generate"):
            with st.spinner("Filling your PowerPoint …"):
                output = fill_from_bytes(
                    st.session_state["upload_bytes"],
                    template_cfg,
                    star_values,
                    comments,
                    video_data,
                )
            st.success("Done!")
            fname = st.session_state.get("upload_filename", "filled_report.pptx")
            st.download_button(
                label="📥  Download Filled PowerPoint",
                data=output,
                file_name=f"Filled_{fname}",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )
