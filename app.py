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

    /* ── Cards / containers ── */
    [data-testid="stVerticalBlock"] { }

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
        width: 100%;
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
    [data-baseweb="select"] * {
        color: #1e3a8a !important;
    }

    /* Open dropdown menu */
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

# ─── Shared helper ────────────────────────────────────────────────────────────

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
    """Labelled slider (0–10, step 0.5) with a live half-star display.

    `default` is only used when the key is not yet in session_state.
    """
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


def rating_form(
    variables: list[str],
    key_prefix: str,
    generate_key: str,
    defaults: list[float] | None = None,
) -> list[float] | None:
    """Render the 7 star-selectors + generate button.

    `defaults` pre-populates sliders (used when re-uploading an already-filled file).
    Returns the list of star values when the button is pressed, else None.
    """
    if defaults is None:
        defaults = [0.0] * len(variables)
    st.subheader("Rate each competency on a scale of 0 to 10")
    values = [
        star_selector(var, key=f"{key_prefix}_{i}", default=defaults[i])
        for i, var in enumerate(variables)
    ]
    st.markdown("---")
    if st.button("Generate PowerPoint ▶", type="primary", use_container_width=True, key=generate_key):
        return values
    return None


# ─── App ─────────────────────────────────────────────────────────────────────

st.title("⚽ Rating Calculator for Scouting Reports")
st.caption(
    "This tool helps you fill out PowerPoint scouting report templates with star ratings. "
    "You can either start from an empty template or upload your current work to add ratings."
)
tab_empty, tab_upload = st.tabs([
    "📋  Fill Empty Template",
    "📂  Upload Current Work and Add Stars / Rating",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Fill an empty template from scratch
# ══════════════════════════════════════════════════════════════════════════════
with tab_empty:
    st.header("Fill Empty Template")
    st.caption("Choose a player type, rate each competency, and download the report with filled in stars & rating.")

    template_name: str = st.selectbox(
        "Player type / template:",
        list(TEMPLATES.keys()),
        key="empty_template_select",
    )
    template_cfg = TEMPLATES[template_name]

    st.markdown("---")
    values = rating_form(template_cfg["variables"], key_prefix="empty", generate_key="empty_generate")

    if values is not None:
        with st.spinner("Building your scouting report …"):
            output = fill_template(template_cfg, values)
        st.success("Report is ready!")
        st.download_button(
            label="📥  Download PowerPoint",
            data=output,
            file_name=f"Scout_Report_{template_name.replace(' ', '_').replace('/', '_')}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Upload an existing file, check it, fill stars + rating, download
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("Upload Current Work and Add Stars / Rating")
    st.caption(
        "Upload your existing PowerPoint. "
        "The tool checks it, then lets you add star ratings and the overall score."
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
            # Seed slider state with current star values so they pre-populate correctly
            for i, val in enumerate(check_result.get("current_star_values", [])):
                st.session_state[f"upload_{i}"] = float(val)

    # ── Show results (persists across reruns while sliders are adjusted) ──────
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
        # ── Compatible — resolve which template config to use ─────────────
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
            f"Rating placeholder {'found ✓' if check_result['has_rating_placeholder'] else 'not found ✗'}"
        )

        st.markdown("---")

        # ── Star rating form (pre-populated with existing values) ─────────
        current_values = check_result.get("current_star_values", [])
        values = rating_form(
            template_cfg["variables"],
            key_prefix="upload",
            generate_key="upload_generate",
            defaults=current_values,
        )

        if values is not None:
            with st.spinner("Filling your PowerPoint …"):
                output = fill_from_bytes(
                    st.session_state["upload_bytes"],
                    template_cfg,
                    values,
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
