"""FC Den Bosch / Pro Vercelli — Scout Rating Tool (Streamlit app)."""

import io
import os
import time
import base64
from datetime import datetime
from pathlib import Path
import streamlit as st
from pptx_utils import (
    TEMPLATES, CLUBS, CLUB_LANGUAGES,
    get_template_config, fill_template, fill_from_bytes,
    check_template_compatibility,
)
import storage
from i18n import t, APP_LANGUAGES

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="Scout Rating Tool", page_icon="⚽", layout="centered")

_VIDEO_PREVIEW_LIMIT = 50 * 1024 * 1024

LOGO_DIR = Path(__file__).parent / "Logo's"
_LOGO_DB  = LOGO_DIR / "FC DEN BOSCH LOGO.png"
_LOGO_PV  = LOGO_DIR / "FC_Pro_Vercelli_1892.svg.png"
_LOGO_BFG = LOGO_DIR / "Logo-BFG-White.png"
_LOGO_BFG_B = LOGO_DIR / "Logo-BFG-Black.png"


def _img_b64(path: Path) -> str:
    if path.exists():
        return base64.b64encode(path.read_bytes()).decode()
    return ""


# ─── App language helper ────────────────────────────────────────────────────

def _lang() -> str:
    """Return current app UI language code."""
    return st.session_state.get("app_lang", "EN")


# ─── AI text improvement ────────────────────────────────────────────────────

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


# ─── Authentication ──────────────────────────────────────────────────────────

def _authenticate(login_input: str, password: str) -> str | None:
    """Authenticate by username or email. Returns the username if valid, else None."""
    try:
        users = st.secrets.get("users", {})
        # Direct username match
        user = users.get(login_input)
        if user and user.get("password") == password:
            return login_input
        # Email match: iterate all users
        for uname, udata in users.items():
            if udata.get("email", "").lower() == login_input.lower() and udata.get("password") == password:
                return uname
    except Exception:
        pass
    return None


def _login_page():
    """Render the login page."""
    L = _lang()
    db_b64 = _img_b64(_LOGO_DB)
    bfg_b64 = _img_b64(_LOGO_BFG_B)
    
    st.markdown(
        f"""
        <div style="text-align:center; padding: 2rem 0 1rem 0;">
            <img src="data:image/png;base64,{bfg_b64}" width="1280" style="margin-bottom: 10px;"/>
            <h1 style="color:#1e3a8a; margin:0; font-size:2rem;">Scout Rating Tool</h1>
            <p style="color:#6b7280; margin-top:4px; font-size:.95rem;">FC Den Bosch  &  Pro Vercelli</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        login_input = st.text_input(t("username", L))
        password = st.text_input(t("password", L), type="password")
        submitted = st.form_submit_button(t("log_in", L), type="primary", use_container_width=True)

    if submitted:
        matched_user = _authenticate(login_input, password)
        if matched_user:
            st.session_state["authenticated"] = True
            st.session_state["username"] = matched_user
            st.rerun()
        else:
            st.error(t("invalid_credentials", L))

    return False


# ─── Dynamic styling ────────────────────────────────────────────────────────

_THEME_BLUE = {
    "bg": "#f7f9fc", "sidebar": "#eef4ff",
    "tab_bg": "#edf4ff", "tab_border": "#cfe0ff",
    "tab_hover": "#dbeafe", "tab_active": "#dbeafe", "tab_active_text": "#1d4ed8",
    "primary": "#4a7fd4", "primary_hover": "#3a6ec0",
    "heading": "#1f2937", "text": "#374151",
    "label": "#1e3a8a",
    "select_bg": "#dbeafe", "select_border": "#3b82f6", "select_text": "#1e3a8a",
    "slider": "#4a7fd4",
    "download_bg": "#2e7d4f", "download_hover": "#256040",
    "card_bg": "#ffffff", "card_border": "#d1dff0",
}

_THEME_RED = {
    "bg": "#fdf7f7", "sidebar": "#ffeef0",
    "tab_bg": "#fff0f0", "tab_border": "#ffccd0",
    "tab_hover": "#ffdde0", "tab_active": "#ffdde0", "tab_active_text": "#b91c1c",
    "primary": "#c0392b", "primary_hover": "#a93226",
    "heading": "#1f1010", "text": "#412020",
    "label": "#7f1d1d",
    "select_bg": "#ffdde0", "select_border": "#ef4444", "select_text": "#7f1d1d",
    "slider": "#c0392b",
    "download_bg": "#2e7d4f", "download_hover": "#256040",
    "card_bg": "#ffffff", "card_border": "#f0d1d1",
}


def _apply_theme(club: str) -> None:
    th = _THEME_RED if club == "Pro Vercelli" else _THEME_BLUE
    st.markdown(f"""
    <style>
    [data-testid="stAppViewContainer"] {{ background: {th['bg']}; }}
    [data-testid="stHeader"]           {{ background: {th['bg']}; }}
    [data-testid="stSidebar"]          {{ background: {th['sidebar']}; }}
    h1, h2, h3, h4 {{ color: {th['heading']} !important; }}
    p, li, label, .stMarkdown {{ color: {th['text']} !important; }}

    [data-baseweb="tab-list"] {{
        background: {th['tab_bg']} !important;
        border: 1px solid {th['tab_border']} !important;
        border-radius: 10px !important; padding: 4px !important;
    }}
    [data-baseweb="tab"] {{
        background: transparent !important; color: #4b5563 !important;
        font-weight: 600; border-radius: 8px !important;
    }}
    [data-baseweb="tab"]:hover {{ background: {th['tab_hover']} !important; color: {th['tab_active_text']} !important; }}
    [aria-selected="true"] {{
        background: {th['tab_active']} !important; color: {th['tab_active_text']} !important;
        border-bottom: 2px solid {th['primary']} !important;
    }}

    .var-label {{ font-size:14px; font-weight:700; color:{th['label']}; margin-bottom:2px; letter-spacing:.3px; }}
    .star-row {{ width:60%; display:flex; justify-content:space-between; align-items:center; font-size:26px; line-height:1.2; margin-top:0; margin-bottom:10px; }}
    .star-row span {{ display:inline-block; text-align:center; }}
    hr {{ border-color: #dbe4f0 !important; }}

    [data-baseweb="select"] > div {{ background-color: {th['select_bg']} !important; border: 1px solid {th['select_border']} !important; border-radius: 8px !important; }}
    [data-baseweb="select"] * {{ color: {th['select_text']} !important; }}
    [data-baseweb="popover"] [role="listbox"] {{ background-color: #ffffff !important; border: 1px solid #cbd5e1 !important; border-radius: 8px !important; }}
    [data-baseweb="popover"] [role="option"] {{ background-color: #ffffff !important; color: #374151 !important; }}
    [data-baseweb="popover"] [role="option"]:hover {{ background-color: {th['tab_hover']} !important; color: {th['select_text']} !important; }}
    [data-baseweb="popover"] [aria-selected="true"] {{ background-color: {th['select_bg']} !important; color: {th['select_text']} !important; }}

    [data-testid="stSlider"] > div > div > div > div {{ background: {th['slider']} !important; }}
    [data-baseweb="slider"] [role="slider"] {{
        width:18px !important; height:18px !important;
        background-color:#ffffff !important; border:3px solid #000000 !important; box-shadow:none !important;
    }}

    div.stButton > button[kind="primary"] {{
        background-color:{th['primary']}; color:#ffffff; border:none;
        font-weight:700; font-size:15px; padding:.55rem 1.2rem; border-radius:6px;
    }}
    div.stButton > button[kind="primary"]:hover {{ background-color:{th['primary_hover']}; color:#ffffff; }}

    [data-testid="stDownloadButton"] > button {{
        background-color:{th['download_bg']} !important; color:#ffffff !important;
        border:none !important; font-weight:700 !important; border-radius:6px !important;
    }}
    [data-testid="stDownloadButton"] > button:hover {{ background-color:{th['download_hover']} !important; }}
    [data-testid="stAlert"] {{ border-radius: 6px; }}

    .report-card {{
        background: {th['card_bg']}; border: 1px solid {th['card_border']};
        border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: .8rem;
    }}
    .report-card h4 {{ margin: 0 0 4px 0; font-size: 1rem; }}
    .report-card .meta {{ color: #6b7280; font-size: .85rem; }}

    .player-info-card {{
        background: {th['card_bg']}; border: 1px solid {th['card_border']};
        border-radius: 10px; padding: 1.2rem; margin: 0.5rem 0;
    }}
    .player-info-card .info-row {{
        display: flex; padding: 4px 0; border-bottom: 1px solid #f0f0f0;
    }}
    .player-info-card .info-row:last-child {{ border-bottom: none; }}
    .player-info-card .info-label {{
        font-weight: 700; color: {th['label']}; min-width: 140px; font-size: 0.9rem;
    }}
    .player-info-card .info-value {{
        color: {th['text']}; font-size: 0.9rem;
    }}
    </style>
    """, unsafe_allow_html=True)


# ─── Header with logo ────────────────────────────────────────────────────────

def _render_header(club: str):
    L = _lang()
    logo_b64 = _img_b64(_LOGO_PV if club == "Pro Vercelli" else _LOGO_DB)
    bfg_b64 = _img_b64(_LOGO_BFG)
    club_color = "#b91c1c" if club == "Pro Vercelli" else "#1e3a8a"
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:16px; padding:0.5rem 0 0.3rem 0;">
            <img src="data:image/png;base64,{logo_b64}" width="55"/>
            <div style="flex:1;">
                <h1 style="margin:0; font-size:1.7rem; color:{club_color};">{t('scout_rating_tool', L)}</h1>
                <p style="margin:0; color:#6b7280; font-size:.9rem;">{club}</p>
            </div>
            <img src="data:image/png;base64,{bfg_b64}" width="100" style="opacity:.7;"/>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
    L = _lang()
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
                t("video_clip", L),
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
                    st.info(t("too_large_preview", L, mb=size_mb))

            st.markdown(f"**{t('rating', L)}:**")
            val = star_selector(var, key=f"{key_prefix}_{i}", default=defaults_stars[i] if i < len(defaults_stars) else 0.0)

            st.text_area(t("scouting_notes", L), key=comment_key, height=90, placeholder="…")

            improve_key    = f"{key_prefix}_{i}_improve"
            suggestion_key = f"{key_prefix}_{i}_suggestion"
            col_btn, _ = st.columns([1, 4])
            with col_btn:
                if st.button(f"✨ {t('improve', L)}", key=improve_key):
                    raw = st.session_state[comment_key]
                    if raw.strip():
                        with st.spinner(f"{t('improving', L)}"):
                            st.session_state[suggestion_key] = improve_text(raw)
                    else:
                        st.warning(t("nothing_to_improve", L))
            if st.session_state.get(suggestion_key):
                suggestion = st.session_state[suggestion_key]
                st.markdown(f"**{t('suggested_improvement', L)}**")
                st.text_area("Suggested", value=suggestion, height=90, key=f"{key_prefix}_{i}_sug_display", label_visibility="collapsed")
                col_spacer_left, col_accept, col_discard, col_spacer_right = st.columns([1, 1.5, 1.5, 1])
                with col_accept:
                    if st.button(t("accept", L), key=f"{key_prefix}_{i}_accept", type="primary", use_container_width=True):
                        st.session_state[comment_key] = suggestion
                        st.session_state[suggestion_key] = ""
                        st.rerun()
                with col_discard:
                    if st.button(t("discard", L), key=f"{key_prefix}_{i}_discard", use_container_width=True):
                        st.session_state[suggestion_key] = ""
                        st.rerun()

        star_values.append(val)
        comments.append(st.session_state[comment_key])
        video_data.append(st.session_state[video_key])

    return star_values, comments, video_data


def _ts_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M")


# ─── Collect current editor state ────────────────────────────────────────────

def _collect_editor_state(key_prefix: str, n_vars: int):
    """Read stars, comments and video_data back from session_state."""
    stars, comments, videos = [], [], []
    for i in range(n_vars):
        stars.append(st.session_state.get(f"{key_prefix}_{i}", 0.0))
        comments.append(st.session_state.get(f"{key_prefix}_{i}_comment", ""))
        videos.append(st.session_state.get(f"{key_prefix}_{i}_video"))
    return stars, comments, videos


# ─── SciSports UI section ───────────────────────────────────────────────────

def _scisports_section() -> dict | None:
    """Render SciSports player search/select UI. Returns player_data dict or None."""
    L = _lang()

    try:
        from scisports import require_secrets, get_token, search_players, fetch_player_data, SCISPORTS_TO_TEMPLATE
    except ImportError:
        return st.session_state.get("player_data")

    secrets = require_secrets()
    if not secrets:
        st.caption(t("scisports_not_configured", L))
        return st.session_state.get("player_data")

    st.markdown("---")
    st.subheader(f"🔍 {t('search_player', L)}")

    with st.form("scisports_search_form"):
        query = st.text_input(t("search", L), placeholder=t("search_placeholder", L), key="sci_query")
        search_submitted = st.form_submit_button(t("search", L), use_container_width=True)

    if search_submitted and query.strip():
        with st.spinner(t("connecting_scisports", L)):
            try:
                token = get_token()
                total, options = search_players(token, query)
                st.session_state["sci_token"] = token
                st.session_state["sci_options"] = options
                st.session_state["sci_total"] = total
            except Exception as exc:
                st.error(f"SciSports error: {exc}")

    options = st.session_state.get("sci_options", [])
    if options:
        labels = [opt.label() for opt in options]
        selected_idx = st.selectbox(
            t("select_player", L),
            range(len(labels)),
            format_func=lambda i: labels[i],
            key="sci_selected_idx",
        )

        if st.button(t("obtain_scisports", L), type="primary", use_container_width=True):
            chosen = options[selected_idx]
            token = st.session_state.get("sci_token")
            if not token:
                token = get_token()
            with st.spinner(t("fetching_data", L)):
                try:
                    pdata = fetch_player_data(token, chosen.player_id)
                    st.session_state["player_data"] = pdata
                except Exception as exc:
                    st.error(f"Error: {exc}")

    # Show player info card if we have data
    pdata = st.session_state.get("player_data")
    if pdata:
        _render_player_card(pdata)

    return st.session_state.get("player_data")


def _render_player_card(pdata: dict):
    """Render a styled player info card matching the PowerPoint layout."""
    L = _lang()
    name = pdata.get("name", "")
    st.markdown(f"### {t('player_info', L)}: {name}")

    fields = [
        ("date_of_birth", pdata.get("date_of_birth", "")),
        ("city_of_birth", pdata.get("city_of_birth", "")),
        ("nationality",   pdata.get("nationality", "")),
        ("height",        pdata.get("height", "")),
        ("preferred_foot", pdata.get("preferred_foot", "")),
        ("club_label",    pdata.get("club", "")),
        ("league",        pdata.get("league", "")),
        ("agency",        pdata.get("agency", "")),
        ("agent",         pdata.get("agent", "")),
    ]

    rows_html = ""
    for label_key, value in fields:
        rows_html += f"""
        <div class="info-row">
            <div class="info-label">{t(label_key, L)}</div>
            <div class="info-value">{value or '—'}</div>
        </div>"""

    st.markdown(f'<div class="player-info-card">{rows_html}</div>', unsafe_allow_html=True)

    # Show extra stats
    season_stats = f"{pdata.get('season_matches', '0')} matches · {pdata.get('season_goals', '0')} goals · {pdata.get('season_assists', '0')} assists"
    career_stats = f"{pdata.get('career_matches', '0')} matches · {pdata.get('career_goals', '0')} goals · {pdata.get('career_assists', '0')} assists"
    st.caption(f"Season: {season_stats}")
    st.caption(f"Career: {career_stats}")


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN GATE
# ══════════════════════════════════════════════════════════════════════════════

if not st.session_state.get("authenticated"):
    _login_page()
    st.stop()

username = st.session_state["username"]
L = _lang()

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — app language, club, template language, user info, logout, nav
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    # App language selector (flags) at top
    app_lang_labels = list(APP_LANGUAGES.keys())
    current_app_lang = _lang()
    current_idx = list(APP_LANGUAGES.values()).index(current_app_lang) if current_app_lang in APP_LANGUAGES.values() else 0
    selected_lang_label = st.radio(
        t("app_language", L),
        app_lang_labels,
        index=current_idx,
        horizontal=True,
        key="app_lang_radio",
    )
    new_app_lang = APP_LANGUAGES[selected_lang_label]
    if new_app_lang != st.session_state.get("app_lang"):
        st.session_state["app_lang"] = new_app_lang
        st.rerun()
    L = _lang()  # refresh after possible change

    st.markdown(f"**{t('logged_in_as', L)}:** {username}")
    if st.button(t("log_out", L), use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.markdown("---")
    club = st.selectbox(t("club", L), CLUBS, key="club_select")
    available_langs = CLUB_LANGUAGES[club]
    lang = st.selectbox(t("template_language", L), available_langs, key="lang_select")

    st.markdown("---")

    # Navigation — use _nav_override to avoid modifying widget key after instantiation
    nav_options = [t("dashboard", L), t("new_report", L), t("upload_edit", L)]
    nav_keys    = ["Dashboard", "New Report", "Upload & Edit"]

    nav_override = st.session_state.pop("_nav_override", None)
    default_idx = 0
    if nav_override and nav_override in nav_keys:
        default_idx = nav_keys.index(nav_override)

    selected_nav = st.radio(
        "Navigate",
        nav_options,
        index=default_idx,
        key="nav_page",
        label_visibility="collapsed",
    )
    page = nav_keys[nav_options.index(selected_nav)]

_apply_theme(club)
_render_header(club)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Dashboard
# ══════════════════════════════════════════════════════════════════════════════

if page == "Dashboard":
    st.markdown("---")

    # ── Drafts (in progress) ─────────────────────────────────────────────────
    st.subheader(f"📝  {t('in_progress', L)}")
    drafts = storage.list_drafts(username)
    if not drafts:
        st.caption(t("no_drafts", L))
    else:
        for d in drafts:
            rid = d["report_id"]
            with st.container():
                st.markdown(
                    f"""<div class="report-card">
                    <h4>{d['position']}  —  {d['club']} ({d['language']})</h4>
                    <div class="meta">{t('last_saved', L)}: {_ts_str(d['updated_at'])}  ·  ID: {rid[:8]}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    if st.button(t("continue_editing", L), key=f"cont_{rid}", type="primary", use_container_width=True):
                        st.session_state["edit_draft_id"] = rid
                        st.session_state["_nav_override"] = "New Report"
                        st.rerun()
                with c2:
                    if st.button(t("delete", L), key=f"del_draft_{rid}", use_container_width=True):
                        storage.delete_draft(username, rid)
                        st.rerun()

    st.markdown("---")

    # ── Finished reports ──────────────────────────────────────────────────────
    st.subheader(f"✅  {t('finished_reports', L)}")
    finished = storage.list_finished(username)
    if not finished:
        st.caption(t("no_finished", L))
    else:
        for f in finished:
            rid = f["report_id"]
            st.markdown(
                f"""<div class="report-card">
                <h4>{f['position']}  —  {f['club']} ({f['language']})</h4>
                <div class="meta">{t('finished_at', L)}: {_ts_str(f['finished_at'])}  ·  ID: {rid[:8]}</div>
                </div>""",
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([2, 1])
            with c1:
                pptx_bytes = storage.load_finished_pptx(username, rid)
                if pptx_bytes:
                    st.download_button(
                        f"📥  {t('download_pptx', L)}", data=pptx_bytes,
                        file_name=f"Scout_{f['position'].replace(' ','_')}_{f['club'].replace(' ','_')}_{rid[:8]}.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key=f"dl_{rid}", use_container_width=True,
                    )
            with c2:
                if st.button(t("delete", L), key=f"del_fin_{rid}", use_container_width=True):
                    storage.delete_finished(username, rid)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: New Report (also used for continuing a draft)
# ══════════════════════════════════════════════════════════════════════════════

elif page == "New Report":
    st.markdown("---")

    # ── Load draft if continuing ──────────────────────────────────────────────
    draft_id = st.session_state.pop("edit_draft_id", None)
    if draft_id and st.session_state.get("_loaded_draft") != draft_id:
        draft = storage.load_draft(username, draft_id)
        if draft:
            st.session_state["active_report_id"] = draft_id
            st.session_state["club_select"] = draft["club"]
            st.session_state["lang_select"] = draft["language"]
            st.session_state["empty_template_select"] = list(TEMPLATES.keys()).index(draft["position"])
            for i, v in enumerate(draft["star_values"]):
                st.session_state[f"empty_{i}"] = float(v)
            for i, c in enumerate(draft["comments"]):
                st.session_state[f"empty_{i}_comment"] = c or ""
            for i, vd in enumerate(draft.get("video_data", [])):
                st.session_state[f"empty_{i}_video"] = vd
            # Restore player data if present
            if draft.get("player_data"):
                st.session_state["player_data"] = draft["player_data"]
            st.session_state["_loaded_draft"] = draft_id
            st.rerun()

    # ── SciSports player search ──────────────────────────────────────────────
    player_data = _scisports_section()

    # ── Position selector (pre-select from SciSports if available) ───────────
    template_names = list(TEMPLATES.keys())
    sci_position = None
    if player_data and player_data.get("template_position"):
        sci_position = player_data["template_position"]
        if sci_position in template_names and "empty_template_select" not in st.session_state:
            st.session_state["empty_template_select"] = template_names.index(sci_position)

    st.markdown("---")
    template_name = st.selectbox(t("position", L) + ":", template_names, key="empty_template_select")
    template_cfg = get_template_config(template_name, club, lang)

    # Reset on club / language / position change
    reset_key = f"{club}|{lang}|{template_name}"
    if st.session_state.get("empty_prev_key") != reset_key:
        for i in range(20):
            st.session_state[f"empty_{i}"]         = 0.0
            st.session_state[f"empty_{i}_video"]   = None
            st.session_state[f"empty_{i}_comment"] = ""
        st.session_state["empty_prev_key"] = reset_key
        # Clear active report when switching context
        st.session_state.pop("active_report_id", None)
        st.session_state.pop("_loaded_draft", None)

    st.markdown("---")
    st.subheader(t("rate_each_competency", L))

    star_values, comments, video_data = competency_sections(
        template_cfg["variables"], key_prefix="empty",
    )

    st.markdown("---")

    col_save, col_gen = st.columns(2)
    with col_save:
        if st.button(f"💾  {t('save_draft', L)}", use_container_width=True):
            s, c, v = _collect_editor_state("empty", len(template_cfg["variables"]))
            rid = storage.save_draft(
                username,
                st.session_state.get("active_report_id"),
                template_name, club, lang, s, c, v,
                source="empty",
                player_data=st.session_state.get("player_data"),
            )
            st.session_state["active_report_id"] = rid
            st.success(f"{t('draft_saved', L)} (ID: {rid[:8]})")

    with col_gen:
        if st.button(f"{t('generate_pptx', L)} ▶", type="primary", use_container_width=True, key="empty_gen"):
            s, c, v = _collect_editor_state("empty", len(template_cfg["variables"]))
            with st.spinner(t("building_report", L)):
                output = fill_template(
                    template_cfg, s, c, v,
                    player_data=st.session_state.get("player_data"),
                )
            pptx_bytes = output.getvalue()

            # Auto-save as finished
            rid = st.session_state.get("active_report_id") or storage.save_draft(
                username, None, template_name, club, lang, s, c, v,
                source="empty",
                player_data=st.session_state.get("player_data"),
            )
            storage.save_finished(username, rid, template_name, club, lang, pptx_bytes)
            st.session_state.pop("active_report_id", None)

            st.success(t("report_ready", L))
            st.download_button(
                f"📥  {t('download_pptx', L)}", data=pptx_bytes,
                file_name=f"Scout_Report_{template_name.replace(' ', '_')}_{club.replace(' ', '_')}_{lang}.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                use_container_width=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Upload & Edit
# ══════════════════════════════════════════════════════════════════════════════

elif page == "Upload & Edit":
    st.markdown("---")
    st.caption(t("upload_caption", L))

    uploaded = st.file_uploader(t("upload_pptx", L), type=["pptx"], key="upload_widget")

    if uploaded is not None:
        file_key = f"{uploaded.name}_{uploaded.size}"
        if st.session_state.get("upload_file_key") != file_key:
            file_bytes = uploaded.getvalue()
            with st.spinner(t("checking", L)):
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
        st.info(t("upload_start", L))

    elif not check_result["compatible"]:
        st.error(f"❌  {t('not_compatible', L)}")
        for issue in check_result["issues"]:
            st.write(f"- {issue}")

    else:
        matched_name = check_result.get("matched_template_name")
        detected_club = check_result.get("matched_club", club)
        detected_lang = check_result.get("matched_language", lang)

        if matched_name and matched_name in TEMPLATES:
            st.success(f"✅  {t('detected', L)}: **{matched_name}** ({detected_club}, {detected_lang})")
            template_cfg = get_template_config(matched_name, detected_club, detected_lang)
        else:
            st.success(f"✅  {t('compatible', L)}")
            st.warning(t("select_manually", L))
            matched_name = st.selectbox(f"{t('position', L)}:", list(TEMPLATES.keys()), key="upload_tmpl_fallback")
            template_cfg = get_template_config(matched_name, club, lang)

        st.caption(
            f"Slide {check_result['slide_idx']+1} · {check_result['row_count']} rows · "
            f"{check_result['star_count']} stars · "
            f"Rating {'found ✓' if check_result['has_rating_placeholder'] else 'not found ✗'}"
        )

        st.markdown("---")
        st.subheader(t("adjust_competencies", L))

        star_values, comments, video_data = competency_sections(
            template_cfg["variables"],
            key_prefix="upload",
            defaults_stars=check_result.get("current_star_values", []),
            defaults_comments=check_result.get("current_comments", []),
            defaults_videos=check_result.get("current_videos", []),
        )

        st.markdown("---")
        col_save, col_gen = st.columns(2)
        with col_save:
            if st.button(f"💾  {t('save_draft', L)}", use_container_width=True, key="upload_save"):
                s, c, v = _collect_editor_state("upload", len(template_cfg["variables"]))
                rid = storage.save_draft(
                    username,
                    st.session_state.get("upload_active_report_id"),
                    matched_name or "Unknown", detected_club, detected_lang, s, c, v,
                    source="upload",
                    upload_bytes=st.session_state.get("upload_bytes"),
                    upload_filename=st.session_state.get("upload_filename"),
                )
                st.session_state["upload_active_report_id"] = rid
                st.success(f"{t('draft_saved', L)} (ID: {rid[:8]})")

        with col_gen:
            if st.button(f"{t('generate_pptx', L)} ▶", type="primary", use_container_width=True, key="upload_gen"):
                s, c, v = _collect_editor_state("upload", len(template_cfg["variables"]))
                with st.spinner(t("filling", L)):
                    output = fill_from_bytes(
                        st.session_state["upload_bytes"], template_cfg, s, c, v,
                    )
                pptx_bytes = output.getvalue()
                pos = matched_name or "Unknown"

                rid = st.session_state.get("upload_active_report_id") or storage.save_draft(
                    username, None, pos, detected_club, detected_lang, s, c, v,
                    source="upload",
                    upload_bytes=st.session_state.get("upload_bytes"),
                    upload_filename=st.session_state.get("upload_filename"),
                )
                storage.save_finished(username, rid, pos, detected_club, detected_lang, pptx_bytes)
                st.session_state.pop("upload_active_report_id", None)

                st.success(t("done", L))
                fname = st.session_state.get("upload_filename", "report.pptx")
                st.download_button(
                    f"📥  {t('download_filled', L)}", data=pptx_bytes,
                    file_name=f"Filled_{fname}",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True,
                )
