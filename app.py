"""FC Den Bosch / Pro Vercelli — Scout Rating Tool (Streamlit app)."""

import io
import os
import streamlit as st
from pptx_utils import (
    TEMPLATES, CLUBS, CLUB_LANGUAGES,
    get_template_config, fill_template, fill_from_bytes,
    check_template_compatibility,
)

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Scout Rating Tool",
    page_icon="⚽",
    layout="centered",
)

# ─── AI text improvement ────────────────────────────────────────────────────
_VIDEO_PREVIEW_LIMIT = 50 * 1024 * 1024  # 50 MB


def _get_anthropic_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        if key and not key.startswith("#"):
            return key
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY") or None


def improve_text(text: str) -> str:
    api_key = _get_anthropic_key()
    if not api_key:
        st.error("No Anthropic API key. Add ANTHROPIC_API_KEY to .streamlit/secrets.toml")
        return text
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": (
                    "Herschrijf de volgende scoutingnotitie naar een professionele, objectieve en formele stijl voor een officieel scoutingrapport. "
                    "Corrigeer taalfouten, vermijd informele woorden (zoals verkleinwoorden) en maak de tekst bondig, maar behoud de kern van de observatie. "
                    "Geef uitsluitend de verbeterde tekst terug, zonder introductie of uitleg.\n\n"
                    "Voorbeeld:\n"
                    "Input: Dit spelertje is goed met de bal in de handen\n"
                    "Output: De speler beschikt over een betrouwbare balbehandeling.\n\n"
                    f"Input: {text}\n"
                    "Output:"
                ),
            }],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        st.error(f"AI improvement failed: {exc}")
        return text


# ─── Dynamic styling ────────────────────────────────────────────────────────

_THEME_BLUE = {
    "bg":       "#f7f9fc", "sidebar": "#eef4ff",
    "tab_bg":   "#edf4ff", "tab_border": "#cfe0ff",
    "tab_hover": "#dbeafe", "tab_active": "#dbeafe", "tab_active_text": "#1d4ed8",
    "primary":  "#4a7fd4", "primary_hover": "#3a6ec0",
    "heading":  "#1f2937", "text": "#374151",
    "label":    "#1e3a8a",
    "select_bg": "#dbeafe", "select_border": "#3b82f6", "select_text": "#1e3a8a",
    "slider":   "#4a7fd4",
    "download_bg": "#2e7d4f", "download_hover": "#256040",
}

_THEME_RED = {
    "bg":       "#fdf7f7", "sidebar": "#ffeef0",
    "tab_bg":   "#fff0f0", "tab_border": "#ffccd0",
    "tab_hover": "#ffdde0", "tab_active": "#ffdde0", "tab_active_text": "#b91c1c",
    "primary":  "#c0392b", "primary_hover": "#a93226",
    "heading":  "#1f1010", "text": "#412020",
    "label":    "#7f1d1d",
    "select_bg": "#ffdde0", "select_border": "#ef4444", "select_text": "#7f1d1d",
    "slider":   "#c0392b",
    "download_bg": "#2e7d4f", "download_hover": "#256040",
}


def _apply_theme(club: str) -> None:
    t = _THEME_RED if club == "Pro Vercelli" else _THEME_BLUE
    st.markdown(f"""
    <style>
    [data-testid="stAppViewContainer"] {{ background: {t['bg']}; }}
    [data-testid="stHeader"]           {{ background: {t['bg']}; }}
    [data-testid="stSidebar"]          {{ background: {t['sidebar']}; }}
    h1, h2, h3, h4 {{ color: {t['heading']} !important; }}
    p, li, label, .stMarkdown {{ color: {t['text']} !important; }}

    [data-baseweb="tab-list"] {{
        background: {t['tab_bg']} !important;
        border: 1px solid {t['tab_border']} !important;
        border-radius: 10px !important; padding: 4px !important;
    }}
    [data-baseweb="tab"] {{
        background: transparent !important; color: #4b5563 !important;
        font-weight: 600; border-radius: 8px !important;
    }}
    [data-baseweb="tab"]:hover {{ background: {t['tab_hover']} !important; color: {t['tab_active_text']} !important; }}
    [aria-selected="true"] {{
        background: {t['tab_active']} !important; color: {t['tab_active_text']} !important;
        border-bottom: 2px solid {t['primary']} !important;
    }}

    .var-label {{ font-size:14px; font-weight:700; color:{t['label']}; margin-bottom:2px; letter-spacing:.3px; }}
    .star-row {{ width:60%; display:flex; justify-content:space-between; align-items:center; font-size:26px; line-height:1.2; margin-top:0; margin-bottom:10px; }}
    .star-row span {{ display:inline-block; text-align:center; }}
    hr {{ border-color: #dbe4f0 !important; }}

    [data-baseweb="select"] > div {{ background-color: {t['select_bg']} !important; border: 1px solid {t['select_border']} !important; border-radius: 8px !important; }}
    [data-baseweb="select"] * {{ color: {t['select_text']} !important; }}
    [data-baseweb="popover"] [role="listbox"] {{ background-color: #ffffff !important; border: 1px solid #cbd5e1 !important; border-radius: 8px !important; }}
    [data-baseweb="popover"] [role="option"] {{ background-color: #ffffff !important; color: #374151 !important; }}
    [data-baseweb="popover"] [role="option"]:hover {{ background-color: {t['tab_hover']} !important; color: {t['select_text']} !important; }}
    [data-baseweb="popover"] [aria-selected="true"] {{ background-color: {t['select_bg']} !important; color: {t['select_text']} !important; }}

    [data-testid="stSlider"] > div > div > div > div {{ background: {t['slider']} !important; }}
    [data-baseweb="slider"] [role="slider"] {{
        width:18px !important; height:18px !important;
        background-color:#ffffff !important; border:3px solid #000000 !important; box-shadow:none !important;
    }}

    div.stButton > button[kind="primary"] {{
        background-color:{t['primary']}; color:#ffffff; border:none;
        font-weight:700; font-size:15px; padding:.55rem 1.2rem; border-radius:6px;
    }}
    div.stButton > button[kind="primary"]:hover {{ background-color:{t['primary_hover']}; color:#ffffff; }}

    [data-testid="stDownloadButton"] > button {{
        background-color:{t['download_bg']} !important; color:#ffffff !important;
        border:none !important; font-weight:700 !important; border-radius:6px !important;
    }}
    [data-testid="stDownloadButton"] > button:hover {{ background-color:{t['download_hover']} !important; }}
    [data-testid="stAlert"] {{ border-radius: 6px; }}
    </style>
    """, unsafe_allow_html=True)


# ─── Shared UI helpers ───────────────────────────────────────────────────────

def _star_row_html(value: float) -> str:
    gold, dark = "#FFD932", "#3a4060"
    full = int(value)
    has_half = (value % 1) >= 0.5
    parts = []
    for i in range(10):
        if i < full:
            parts.append(f'<span style="color:{gold}">★</span>')
        elif i == full and has_half:
            parts.append(
                f'<span style="background:linear-gradient(to right,{gold} 50%,{dark} 50%);'
                f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
                f'background-clip:text;color:transparent;">★</span>'
            )
        else:
            parts.append(f'<span style="color:{dark}">★</span>')
    return f'<div class="star-row">{"".join(parts)}</div>'


def star_selector(label: str, key: str, default: float = 0.0) -> float:
    st.markdown(f'<div class="var-label">{label}</div>', unsafe_allow_html=True)
    if key not in st.session_state:
        st.session_state[key] = float(default)
    value: float = st.slider(label, 0.0, 10.0, step=0.5, key=key, label_visibility="collapsed")
    st.markdown(_star_row_html(value), unsafe_allow_html=True)
    return value


def competency_sections(variables, key_prefix, defaults_stars=None, defaults_comments=None, defaults_videos=None):
    n = len(variables)
    if defaults_stars is None:
        defaults_stars = [0.0] * n
    if defaults_comments is None:
        defaults_comments = [""] * n
    if defaults_videos is None:
        defaults_videos = [None] * n

    star_values, comments, video_data = [], [], []

    for i, var in enumerate(variables):
        video_key   = f"{key_prefix}_{i}_video"
        comment_key = f"{key_prefix}_{i}_comment"
        if comment_key not in st.session_state:
            st.session_state[comment_key] = defaults_comments[i] if i < len(defaults_comments) else ""
        if video_key not in st.session_state:
            st.session_state[video_key] = defaults_videos[i] if i < len(defaults_videos) else None

        with st.expander(f"📽  {var}", expanded=False):
            uploaded_video = st.file_uploader(
                "Upload video clip (mp4, mov, avi, wmv, mkv)",
                type=["mp4", "mov", "avi", "wmv", "mkv", "webm"],
                key=f"{key_prefix}_{i}_uploader",
            )
            if uploaded_video is not None:
                st.session_state[video_key] = (uploaded_video.getvalue(), uploaded_video.name)

            current_video = st.session_state[video_key]
            if current_video is not None:
                vbytes, vname = current_video
                size_mb = len(vbytes) / (1024 * 1024)
                st.caption(f"Video: **{vname}** ({size_mb:.1f} MB)")
                if len(vbytes) <= _VIDEO_PREVIEW_LIMIT:
                    st.video(vbytes)
                else:
                    st.info(f"Too large for preview ({size_mb:.0f} MB). Will still be embedded in the PowerPoint.")

            st.markdown("**Rating:**")
            val = star_selector(var, key=f"{key_prefix}_{i}", default=defaults_stars[i] if i < len(defaults_stars) else 0.0)

            st.text_area("Scouting notes", key=comment_key, height=90, placeholder="Add your notes here…")

            improve_key    = f"{key_prefix}_{i}_improve"
            suggestion_key = f"{key_prefix}_{i}_suggestion"
            col_btn, _ = st.columns([1, 4])
            with col_btn:
                if st.button("✨ Improve", key=improve_key, help="AI spelling & structure check"):
                    raw = st.session_state[comment_key]
                    if raw.strip():
                        with st.spinner("Improving…"):
                            st.session_state[suggestion_key] = improve_text(raw)
                    else:
                        st.warning("Nothing to improve yet.")
            if st.session_state.get(suggestion_key):
                suggestion = st.session_state[suggestion_key]
                st.markdown("**Suggested improvement:**")
                st.text_area("Suggested", value=suggestion, height=90, key=f"{key_prefix}_{i}_sug_display", label_visibility="collapsed")
                ca, cd = st.columns(2)
                with ca:
                    if st.button("Accept", key=f"{key_prefix}_{i}_accept", type="primary"):
                        st.session_state[comment_key] = suggestion
                        st.session_state[suggestion_key] = ""
                        st.rerun()
                with cd:
                    if st.button("Discard", key=f"{key_prefix}_{i}_discard"):
                        st.session_state[suggestion_key] = ""
                        st.rerun()

        star_values.append(val)
        comments.append(st.session_state[comment_key])
        video_data.append(st.session_state[video_key])

    return star_values, comments, video_data


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════

# ─── Club + Language selector (top of page) ──────────────────────────────────
col_club, col_lang = st.columns(2)
with col_club:
    club = st.selectbox("Club", CLUBS, key="club_select")
with col_lang:
    available_langs = CLUB_LANGUAGES[club]
    lang = st.selectbox("Language", available_langs, key="lang_select")

_apply_theme(club)

st.title("⚽ Scout Rating Tool")
st.caption(
    f"**{club}** — {'Nederlands' if lang == 'NL' else 'English'}  ·  "
    "Fill scouting reports with videos, star ratings and notes."
)

tab_empty, tab_upload = st.tabs(["📋  Fill Empty Template", "📂  Upload Current Work"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Fill empty template
# ══════════════════════════════════════════════════════════════════════════════
with tab_empty:
    st.header("Fill Empty Template")

    template_name = st.selectbox("Position:", list(TEMPLATES.keys()), key="empty_template_select")
    template_cfg = get_template_config(template_name, club, lang)

    # Reset on club / language / position change
    reset_key = f"{club}|{lang}|{template_name}"
    if st.session_state.get("empty_prev_key") != reset_key:
        for i in range(20):
            st.session_state[f"empty_{i}"]         = 0.0
            st.session_state[f"empty_{i}_video"]   = None
            st.session_state[f"empty_{i}_comment"] = ""
        st.session_state["empty_prev_key"] = reset_key

    st.markdown("---")
    st.subheader("Rate each competency")

    star_values, comments, video_data = competency_sections(
        template_cfg["variables"], key_prefix="empty",
    )

    st.markdown("---")
    if st.button("Generate PowerPoint ▶", type="primary", use_container_width=True, key="empty_gen"):
        with st.spinner("Building report …"):
            output = fill_template(template_cfg, star_values, comments, video_data)
        st.success("Report ready!")
        st.download_button(
            "📥  Download PowerPoint", data=output,
            file_name=f"Scout_Report_{template_name.replace(' ', '_')}_{club.replace(' ', '_')}_{lang}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            use_container_width=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Upload existing file
# ══════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.header("Upload Current Work")
    st.caption("Upload your existing PowerPoint to adjust stars, videos and notes.")

    uploaded = st.file_uploader("Upload .pptx", type=["pptx"], key="upload_widget")

    if uploaded is not None:
        file_key = f"{uploaded.name}_{uploaded.size}"
        if st.session_state.get("upload_file_key") != file_key:
            file_bytes = uploaded.getvalue()
            with st.spinner("Checking …"):
                check_result = check_template_compatibility(io.BytesIO(file_bytes))
            st.session_state["upload_file_key"]     = file_key
            st.session_state["upload_bytes"]        = file_bytes
            st.session_state["upload_filename"]     = uploaded.name
            st.session_state["upload_check_result"] = check_result
            for i, val in enumerate(check_result.get("current_star_values", [])):
                st.session_state[f"upload_{i}"] = float(val)
            for i, cmt in enumerate(check_result.get("current_comments", [])):
                st.session_state[f"upload_{i}_comment"] = cmt or ""
            for i, vid in enumerate(check_result.get("current_videos", [])):
                st.session_state[f"upload_{i}_video"] = vid

    check_result = st.session_state.get("upload_check_result")

    if check_result is None:
        st.info("Upload a .pptx file above to get started.")

    elif not check_result["compatible"]:
        st.error("❌  File **not compatible**.")
        for issue in check_result["issues"]:
            st.write(f"- {issue}")

    else:
        matched_name = check_result.get("matched_template_name")
        detected_club = check_result.get("matched_club", club)
        detected_lang = check_result.get("matched_language", lang)

        if matched_name and matched_name in TEMPLATES:
            st.success(f"✅  Detected: **{matched_name}** ({detected_club}, {detected_lang})")
            template_cfg = get_template_config(matched_name, detected_club, detected_lang)
        else:
            st.success("✅  Compatible.")
            st.warning("Could not auto-detect template. Select manually:")
            matched_name = st.selectbox("Position:", list(TEMPLATES.keys()), key="upload_tmpl_fallback")
            template_cfg = get_template_config(matched_name, club, lang)

        st.caption(
            f"Slide {check_result['slide_idx']+1} · {check_result['row_count']} rows · "
            f"{check_result['star_count']} stars · "
            f"Rating {'found ✓' if check_result['has_rating_placeholder'] else 'not found ✗'}"
        )

        st.markdown("---")
        st.subheader("Adjust competencies")

        star_values, comments, video_data = competency_sections(
            template_cfg["variables"],
            key_prefix="upload",
            defaults_stars=check_result.get("current_star_values", []),
            defaults_comments=check_result.get("current_comments", []),
            defaults_videos=check_result.get("current_videos", []),
        )

        st.markdown("---")
        if st.button("Generate PowerPoint ▶", type="primary", use_container_width=True, key="upload_gen"):
            with st.spinner("Filling …"):
                output = fill_from_bytes(
                    st.session_state["upload_bytes"], template_cfg,
                    star_values, comments, video_data,
                )
            st.success("Done!")
            fname = st.session_state.get("upload_filename", "report.pptx")
            st.download_button(
                "📥  Download Filled PowerPoint", data=output,
                file_name=f"Filled_{fname}",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )
