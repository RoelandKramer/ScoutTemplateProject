"""FC Den Bosch — Scout Rating Tool (Streamlit app)."""

import streamlit as st
from pptx_utils import TEMPLATES, fill_template, check_template_compatibility

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
    /* Background */
    [data-testid="stAppViewContainer"] {
        background: #f5f7fa;
    }

    /* Headings */
    h1 { color: #003087 !important; }
    h2, h3 { color: #003087 !important; }

    /* Variable label */
    .var-label {
        font-size: 15px;
        font-weight: 700;
        color: #003087;
        margin-bottom: 2px;
    }

    /* Star row */
    .star-row {
        font-size: 28px;
        letter-spacing: 4px;
        line-height: 1.2;
        margin-top: 0;
        margin-bottom: 12px;
    }

    /* Divider colour */
    hr { border-color: #003087 !important; }

    /* Primary button override */
    div.stButton > button[kind="primary"] {
        background-color: #003087;
        color: #FFD932;
        border: none;
        font-weight: 700;
        font-size: 16px;
        padding: 0.6rem 1.2rem;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #002060;
        color: #FFD932;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def star_selector(label: str, key: str) -> int:
    """Render a labelled slider (0–10) with a live star-display beneath it."""
    st.markdown(f'<div class="var-label">{label}</div>', unsafe_allow_html=True)

    value: int = st.slider(
        label,
        min_value=0,
        max_value=10,
        value=0,
        key=key,
        label_visibility="collapsed",
    )

    filled = "★" * value
    empty = "☆" * (10 - value)
    st.markdown(
        f'<div class="star-row">'
        f'<span style="color:#FFD932;">{filled}</span>'
        f'<span style="color:#CCCCCC;">{empty}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    return value


# ─── App ─────────────────────────────────────────────────────────────────────

st.title("⚽  FC Den Bosch — Scout Rating Tool")
st.caption("Select a player type, rate each competency, and download the filled report.")

tab_fill, tab_check = st.tabs(["📋  Fill Template", "🔍  Check Custom Template"])


# ── Tab 1 : Fill template ────────────────────────────────────────────────────
with tab_fill:
    st.header("Generate Scout Report")

    template_name: str = st.selectbox(
        "Player type / template:",
        list(TEMPLATES.keys()),
    )
    template_cfg = TEMPLATES[template_name]
    variables = template_cfg["variables"]

    st.markdown("---")
    st.subheader("Rate each competency — 0 to 10 stars")

    star_values: list[int] = []
    for i, var in enumerate(variables):
        val = star_selector(var, key=f"star_{template_name}_{i}")
        star_values.append(val)

    st.markdown("---")

    if st.button("Generate PowerPoint ▶", type="primary", use_container_width=True):
        with st.spinner("Building your scouting report …"):
            output = fill_template(template_cfg, star_values)

        st.success("Report is ready!")
        st.download_button(
            label="📥  Download PowerPoint",
            data=output,
            file_name=f"Scout_Report_{template_name.replace(' ', '_').replace('/', '_')}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
        )


# ── Tab 2 : Check template ───────────────────────────────────────────────────
with tab_check:
    st.header("Check Custom Template Compatibility")
    st.write(
        "Upload any `.pptx` file to verify it contains the expected star shapes "
        "and rating placeholder so this tool can fill it in."
    )

    uploaded = st.file_uploader("Upload a .pptx template", type=["pptx"])

    if uploaded is not None:
        with st.spinner("Analysing template …"):
            result = check_template_compatibility(uploaded)

        if result["compatible"]:
            st.success("✅  Template is compatible!")
            st.info(
                f"**Slide {result['slide_idx'] + 1}** — "
                f"{result['row_count']} rating rows × "
                f"{result['star_count'] // max(result['row_count'], 1)} stars each  |  "
                f"Rating placeholder: {'found ✓' if result['has_rating_placeholder'] else 'not found ✗'}"
            )
        else:
            st.error("❌  Template is **not** compatible with this tool.")
            st.subheader("Issues found:")
            for issue in result["issues"]:
                st.write(f"- {issue}")

            if result["star_count"] > 0:
                st.info(
                    f"Partial match — found {result['star_count']} stars "
                    f"in {result['row_count']} row(s) on slide {result['slide_idx'] + 1}."
                )
