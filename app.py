"""FC Den Bosch / Pro Vercelli — Scouting Report Platform (Streamlit app)."""

import io
import os
import uuid
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
st.set_page_config(page_title="Scouting Report Platform", page_icon="", layout="centered")

_VIDEO_PREVIEW_LIMIT = 50 * 1024 * 1024

LOGO_DIR = Path(__file__).parent / "Logo's"
_LOGO_DB  = LOGO_DIR / "FC DEN BOSCH LOGO.png"
_LOGO_PV  = LOGO_DIR / "FC_Pro_Vercelli_1892.svg.png"
_LOGO_BFG = LOGO_DIR / "Logo-BFG-White.png"
_LOGO_BFG_B = LOGO_DIR / "Logo-BFG-Black.png"

# Session persistence directory
_SESSION_DIR = Path(__file__).parent / "data" / ".sessions"


def _img_b64(path: Path) -> str:
    if path.exists():
        return base64.b64encode(path.read_bytes()).decode()
    return ""


# ─── Session persistence across browser refresh ────────────────────────────

def _save_session(username: str):
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    (_SESSION_DIR / f"{token}.txt").write_text(username, encoding="utf-8")
    st.query_params["s"] = token


def _restore_session() -> str | None:
    token = st.query_params.get("s")
    if token:
        p = _SESSION_DIR / f"{token}.txt"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return None


def _clear_session():
    token = st.query_params.get("s")
    if token:
        p = _SESSION_DIR / f"{token}.txt"
        if p.exists():
            p.unlink(missing_ok=True)
    st.query_params.clear()


# ─── App language helper ────────────────────────────────────────────────────

def _lang() -> str:
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
        st.error("No Anthropic API key.")
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
                  "Spelling/Structuur check! "
                  "Geef uitsluitend de verbeterde tekst terug, zonder introductie of uitleg.\n\n"
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
    try:
        users = st.secrets.get("users", {})
        user = users.get(login_input)
        if user and user.get("password") == password:
            return login_input
        for uname, udata in users.items():
            if udata.get("email", "").lower() == login_input.lower() and udata.get("password") == password:
                return uname
    except Exception:
        pass
    return None


def _login_page():
    L = _lang()
    db_b64 = _img_b64(_LOGO_DB)
    bfg_b64 = _img_b64(_LOGO_BFG_B)
    st.markdown(
        f"""
        <div style="text-align:center; padding: 2rem 0 1rem 0;">
            <img src="data:image/png;base64,{bfg_b64}" width="320" style="margin-bottom: 10px;"/>
            <h1 style="color:#1e3a8a; margin:0; font-size:2rem;">{t('login_title', L)}</h1>
            <p style="color:#6b7280; margin-top:4px; font-size:.95rem;">{t('login_subtitle', L)}</p>
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
            _save_session(matched_user)
            st.rerun()
        else:
            st.error(t("invalid_credentials", L))


# ─── Dynamic styling (matching PDF layouts) ─────────────────────────────────

_THEME_BLUE = {
    "bg": "#eef2f9", "sidebar": "#e4ecf7", "content_bg": "#f5f7fb",
    "primary": "#1a3370", "primary_light": "#3b5ba8", "primary_hover": "#15295a",
    "heading": "#1a3370", "text": "#2c3e5a",
    "label": "#1a3370",
    "border": "#b8c9e2", "border_light": "#d1dff0",
    "select_bg": "#1a3370", "select_border": "#1a3370", "select_text": "#ffffff",
    "btn_border": "#1a3370", "btn_text": "#1a3370", "btn_bg": "#ffffff",
    "btn_primary_bg": "#1a3370", "btn_primary_text": "#ffffff",
    "slider": "#1a3370",
    "card_bg": "#ffffff", "card_border": "#b8c9e2",
    "flag_active_bg": "#1a3370", "flag_active_text": "#ffffff",
    "flag_bg": "#ffffff", "flag_text": "#1a3370", "flag_border": "#b8c9e2",
}

_THEME_RED = {
    "bg": "#f9eeed", "sidebar": "#f5e3e2", "content_bg": "#fdf6f5",
    "primary": "#7a1a1a", "primary_light": "#a63030", "primary_hover": "#5a1010",
    "heading": "#7a1a1a", "text": "#4a2020",
    "label": "#7a1a1a",
    "border": "#d4a0a0", "border_light": "#e8c8c8",
    "select_bg": "#7a1a1a", "select_border": "#7a1a1a", "select_text": "#ffffff",
    "btn_border": "#7a1a1a", "btn_text": "#7a1a1a", "btn_bg": "#ffffff",
    "btn_primary_bg": "#7a1a1a", "btn_primary_text": "#ffffff",
    "slider": "#7a1a1a",
    "card_bg": "#ffffff", "card_border": "#d4a0a0",
    "flag_active_bg": "#7a1a1a", "flag_active_text": "#ffffff",
    "flag_bg": "#ffffff", "flag_text": "#7a1a1a", "flag_border": "#d4a0a0",
}


def _apply_theme(club: str) -> None:
    th = _THEME_RED if club == "Pro Vercelli" else _THEME_BLUE
    st.markdown(f"""
    <style>
    /* Page backgrounds */
    [data-testid="stAppViewContainer"] {{ background: {th['content_bg']}; }}
    [data-testid="stHeader"]           {{ background: {th['content_bg']}; }}
    [data-testid="stSidebar"]          {{ background: {th['sidebar']}; }}

    /* Typography */
    h1, h2, h3, h4 {{ color: {th['heading']} !important; }}
    p, li, label, .stMarkdown {{ color: {th['text']} !important; }}

    /* Sidebar labels */
    [data-testid="stSidebar"] label {{ color: {th['label']} !important; font-weight: 600; font-size: 0.85rem; }}

    /* Selectboxes — themed background */
    [data-baseweb="select"] > div {{
        background-color: {th['select_bg']} !important;
        border: 1px solid {th['select_border']} !important;
        border-radius: 8px !important;
    }}
    [data-baseweb="select"] * {{ color: {th['select_text']} !important; }}
    [data-baseweb="select"] svg {{ fill: #ef4444 !important; }}
    [data-baseweb="popover"] [role="listbox"] {{ background-color: #ffffff !important; border: 1px solid #cbd5e1 !important; border-radius: 8px !important; }}
    [data-baseweb="popover"] [role="option"] {{ background-color: #ffffff !important; color: #374151 !important; }}
    [data-baseweb="popover"] [role="option"]:hover {{ background-color: {th['bg']} !important; color: {th['heading']} !important; }}

    /* Radio buttons (navigation) */
    [data-testid="stSidebar"] [role="radiogroup"] label {{ color: {th['text']} !important; }}

    /* Slider */
    [data-testid="stSlider"] > div > div > div > div {{ background: {th['slider']} !important; }}
    [data-baseweb="slider"] [role="slider"] {{
        width:18px !important; height:18px !important;
        background-color:#ffffff !important; border:3px solid #000000 !important; box-shadow:none !important;
    }}

    /* All buttons — outlined style by default */
    div.stButton > button {{
        background-color: {th['btn_bg']} !important; color: {th['btn_text']} !important;
        border: 2px solid {th['btn_border']} !important;
        font-weight: 600; font-size: 14px; padding: .5rem 1rem; border-radius: 10px;
    }}
    div.stButton > button:hover {{
        background-color: {th['bg']} !important; color: {th['primary']} !important;
    }}
    /* Primary buttons — filled */
    div.stButton > button[kind="primary"] {{
        background-color: {th['btn_primary_bg']} !important; color: {th['btn_primary_text']} !important;
        border: 2px solid {th['btn_primary_bg']} !important;
    }}
    div.stButton > button[kind="primary"]:hover {{
        background-color: {th['primary_hover']} !important; color: #ffffff !important;
        border-color: {th['primary_hover']} !important;
    }}

    /* Download buttons — outlined */
    [data-testid="stDownloadButton"] > button {{
        background-color: {th['btn_bg']} !important; color: {th['btn_text']} !important;
        border: 2px solid {th['btn_border']} !important; font-weight: 600 !important; border-radius: 10px !important;
    }}
    [data-testid="stDownloadButton"] > button:hover {{
        background-color: {th['bg']} !important;
    }}

    /* Expanders — themed border */
    [data-testid="stExpander"] {{
        border: 1px solid {th['border']} !important;
        border-radius: 10px !important;
        background: {th['card_bg']} !important;
    }}

    /* Text inputs and text areas */
    [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {{
        border: 1px solid {th['border']} !important;
        border-radius: 10px !important;
    }}

    /* Dividers */
    hr {{ border-color: {th['border_light']} !important; }}

    /* Star row */
    .var-label {{ font-size:14px; font-weight:700; color:{th['label']}; margin-bottom:2px; letter-spacing:.3px; }}
    .star-row {{ width:60%; display:flex; justify-content:space-between; align-items:center; font-size:26px; line-height:1.2; margin-top:0; margin-bottom:10px; }}
    .star-row span {{ display:inline-block; text-align:center; }}

    /* Report cards */
    .report-card {{
        background: {th['card_bg']}; border: 1px solid {th['card_border']};
        border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: .8rem;
    }}
    .report-card h4 {{ margin: 0 0 4px 0; font-size: 1rem; }}
    .report-card .meta {{ color: #6b7280; font-size: .85rem; }}

    /* Player info card */
    .player-info-card {{
        background: {th['card_bg']}; border: 1px solid {th['card_border']};
        border-radius: 10px; padding: 1.2rem; margin: 0.5rem 0;
    }}
    .player-info-card .info-row {{
        display: flex; padding: 5px 0; border-bottom: 1px solid {th['border_light']};
    }}
    .player-info-card .info-row:last-child {{ border-bottom: none; }}
    .player-info-card .info-label {{
        font-weight: 700; color: {th['label']}; min-width: 140px; font-size: 0.9rem;
    }}
    .player-info-card .info-value {{
        color: {th['text']}; font-size: 0.9rem;
    }}

    /* File uploader */
    [data-testid="stFileUploader"] {{
        border: 1px solid {th['border']} !important;
        border-radius: 10px !important;
    }}
    </style>
    """, unsafe_allow_html=True)


# ─── Header (matches PDF layout) ────────────────────────────────────────────

def _render_header(club: str, tmpl_lang: str):
    L = _lang()
    logo_b64 = _img_b64(_LOGO_PV if club == "Pro Vercelli" else _LOGO_DB)
    club_color = "#7a1a1a" if club == "Pro Vercelli" else "#1a3370"
    # Map template language code to display name
    lang_display = {"NL": "Nederlands", "ENG": "English"}.get(tmpl_lang, tmpl_lang)
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:18px; padding:0.8rem 0 0.5rem 0;">
            <img src="data:image/png;base64,{logo_b64}" width="65"/>
            <div>
                <h1 style="margin:0; font-size:1.6rem; color:{club_color}; letter-spacing:1px; text-transform:uppercase;">
                    {t('scout_rating_tool', L)}
                </h1>
                <p style="margin:0; color:{club_color}; font-size:.85rem; opacity:.7;">
                    {club} — {lang_display}
                </p>
            </div>
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
                _, col_accept, col_discard, _ = st.columns([1, 1.5, 1.5, 1])
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


def _report_title(meta: dict) -> str:
    player_name = meta.get("player_name") or ""
    if not player_name:
        pd = meta.get("player_data")
        if pd and isinstance(pd, dict):
            player_name = pd.get("name", "")
    pos = meta.get("position", "?")
    return f"{player_name} — {pos}" if player_name else pos


def _current_player_name() -> str:
    pd = st.session_state.get("player_data")
    if pd and isinstance(pd, dict):
        return pd.get("name", "")
    return ""


def _collect_editor_state(key_prefix: str, n_vars: int):
    stars, comments, videos = [], [], []
    for i in range(n_vars):
        stars.append(st.session_state.get(f"{key_prefix}_{i}", 0.0))
        comments.append(st.session_state.get(f"{key_prefix}_{i}_comment", ""))
        videos.append(st.session_state.get(f"{key_prefix}_{i}_video"))
    return stars, comments, videos


# ─── Editable player info card ──────────────────────────────────────────────

_PLAYER_FIELDS = [
    ("date_of_birth", "date_of_birth"),
    ("city_of_birth", "city_of_birth"),
    ("nationality", "nationality"),
    ("height", "height"),
    ("preferred_foot", "preferred_foot"),
    ("club_label", "club"),
    ("league", "league"),
    ("agency", "agency"),
    ("agent", "agent"),
]


def _render_player_card(pdata: dict, editable: bool = True, key_prefix: str = "pinfo"):
    """Render player info card. If editable=True, shows an edit toggle."""
    L = _lang()
    name = pdata.get("name", "")
    st.markdown(f"### {t('player_info', L)}: {name}")

    edit_key = f"{key_prefix}_editing"
    is_editing = st.session_state.get(edit_key, False)

    if editable:
        if is_editing:
            # Editable form
            for label_key, data_key in _PLAYER_FIELDS:
                pdata[data_key] = st.text_input(
                    t(label_key, L),
                    value=pdata.get(data_key, ""),
                    key=f"{key_prefix}_{data_key}",
                )
            # Update name too
            pdata["name"] = st.text_input(
                "Name",
                value=pdata.get("name", ""),
                key=f"{key_prefix}_name",
            )
            if st.button(f"💾 {t('save_info', L)}", key=f"{key_prefix}_save", type="primary"):
                st.session_state["player_data"] = pdata
                st.session_state[edit_key] = False
                st.rerun()
        else:
            # Read-only display
            rows_html = ""
            for label_key, data_key in _PLAYER_FIELDS:
                value = pdata.get(data_key, "")
                rows_html += f"""
                <div class="info-row">
                    <div class="info-label">{t(label_key, L)}</div>
                    <div class="info-value">{value or '—'}</div>
                </div>"""
            st.markdown(f'<div class="player-info-card">{rows_html}</div>', unsafe_allow_html=True)

            season_stats = f"{pdata.get('season_matches', '0')} matches · {pdata.get('season_goals', '0')} goals · {pdata.get('season_assists', '0')} assists"
            career_stats = f"{pdata.get('career_matches', '0')} matches · {pdata.get('career_goals', '0')} goals · {pdata.get('career_assists', '0')} assists"
            st.caption(f"Season: {season_stats}")
            st.caption(f"Career: {career_stats}")

            if st.button(f"✏️ {t('edit_info', L)}", key=f"{key_prefix}_edit"):
                st.session_state[edit_key] = True
                st.rerun()
    else:
        rows_html = ""
        for label_key, data_key in _PLAYER_FIELDS:
            value = pdata.get(data_key, "")
            rows_html += f"""
            <div class="info-row">
                <div class="info-label">{t(label_key, L)}</div>
                <div class="info-value">{value or '—'}</div>
            </div>"""
        st.markdown(f'<div class="player-info-card">{rows_html}</div>', unsafe_allow_html=True)


# ─── SciSports UI section ───────────────────────────────────────────────────

def _scisports_section(key_prefix: str = "sci") -> dict | None:
    """Render SciSports player search/select UI. Returns player_data dict or None."""
    L = _lang()

    try:
        from scisports import require_secrets, get_token, search_players, fetch_player_data
    except ImportError:
        return st.session_state.get("player_data")

    secrets = require_secrets()
    if not secrets:
        with st.expander(f"⚙️ {t('configure_scisports', L)}", expanded=False):
            st.info(t("scisports_setup_info", L))
            st.code(
                '[scisports]\n'
                'username = "your_username"\n'
                'password = "your_password"\n'
                'client_id = "your_client_id"\n'
                'client_secret = "your_client_secret"\n'
                'scope = "api recruitment performance"',
                language="toml",
            )
        return st.session_state.get("player_data")

    st.subheader(f"{t('search_player', L)}")

    with st.form(f"{key_prefix}_search_form"):
        query = st.text_input(t("search", L), placeholder=t("search_placeholder", L), key=f"{key_prefix}_query")
        search_submitted = st.form_submit_button(t("search", L), use_container_width=True)

    if search_submitted and query.strip():
        with st.spinner(t("connecting_scisports", L)):
            try:
                token = get_token()
                total, options = search_players(token, query)
                st.session_state[f"{key_prefix}_token"] = token
                st.session_state[f"{key_prefix}_options"] = options
            except Exception as exc:
                st.error(f"SciSports error: {exc}")

    options = st.session_state.get(f"{key_prefix}_options", [])
    if options:
        labels = [opt.label() for opt in options]
        selected_idx = st.selectbox(
            t("select_player", L),
            range(len(labels)),
            format_func=lambda i: labels[i],
            key=f"{key_prefix}_selected_idx",
        )

        if st.button(t("obtain_scisports", L), type="primary", use_container_width=True, key=f"{key_prefix}_obtain"):
            chosen = options[selected_idx]
            token = st.session_state.get(f"{key_prefix}_token")
            if not token:
                token = get_token()
            with st.spinner(t("fetching_data", L)):
                try:
                    pdata = fetch_player_data(token, chosen.player_id)
                    st.session_state["player_data"] = pdata
                except Exception as exc:
                    st.error(f"Error: {exc}")

    pdata = st.session_state.get("player_data")
    if pdata:
        _render_player_card(pdata, editable=True, key_prefix=f"{key_prefix}_card")

    return st.session_state.get("player_data")


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN GATE — restore session on refresh
# ══════════════════════════════════════════════════════════════════════════════

if not st.session_state.get("authenticated"):
    restored_user = _restore_session()
    if restored_user:
        st.session_state["authenticated"] = True
        st.session_state["username"] = restored_user
    else:
        _login_page()
        st.stop()

username = st.session_state["username"]
L = _lang()

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown(f"**{t('logged_in_as', L)}:** {username}")

    # ── Language flags ───────────────────────────────────────────────────────
    st.caption(t("choose_language", L))
    _FLAG_MAP = {"NL": "NL", "EN": "ENG", "IT": "ITA", "ZH": "CH"}
    current_app_lang = _lang()
    flag_cols = st.columns(len(_FLAG_MAP))
    for idx, (code, label) in enumerate(_FLAG_MAP.items()):
        with flag_cols[idx]:
            btn_type = "primary" if code == current_app_lang else "secondary"
            if st.button(label, key=f"flag_{code}", type=btn_type, use_container_width=True):
                if code != current_app_lang:
                    st.session_state["app_lang"] = code
                    st.rerun()
    L = _lang()

    # ── Club & template language ─────────────────────────────────────────────
    club = st.selectbox(t("choose_club", L), CLUBS, key="club_select")
    available_langs = CLUB_LANGUAGES[club]
    lang = st.selectbox(t("choose_template_language", L), available_langs, key="lang_select")

    st.markdown("---")

    # ── Navigation (default = New Report) ────────────────────────────────────
    nav_options = [t("new_report", L), t("dashboard", L), t("upload_edit", L)]
    nav_keys    = ["New Report", "Dashboard", "Upload & Edit"]

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

    # ── Logout at bottom ─────────────────────────────────────────────────────
    st.markdown("")
    st.markdown("")
    st.markdown("")
    if st.button(f"{t('log_out', L)}", use_container_width=True, key="logout_btn"):
        _clear_session()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

_apply_theme(club)
_render_header(club, lang)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: Dashboard
# ══════════════════════════════════════════════════════════════════════════════

if page == "Dashboard":
    st.markdown("---")

    st.subheader(f"📝  {t('in_progress', L)}")
    all_drafts = storage.list_drafts(username)
    drafts = [d for d in all_drafts if d.get("club") == club]
    if not drafts:
        st.caption(t("no_drafts", L))
    else:
        for d in drafts:
            rid = d["report_id"]
            title = _report_title(d)
            st.markdown(
                f"""<div class="report-card">
                <h4>{title}</h4>
                <div class="meta">{d['club']} ({d['language']}) · {t('last_saved', L)}: {_ts_str(d['updated_at'])}</div>
                </div>""",
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([2, 1])
            with c1:
                if st.button(t("continue_editing", L), key=f"cont_{rid}", type="primary", use_container_width=True):
                    st.session_state["edit_draft_id"] = rid
                    st.session_state["_nav_override"] = "New Report"
                    # Clear nav_page so radio picks up the override index
                    st.session_state.pop("nav_page", None)
                    st.rerun()
            with c2:
                if st.button(t("delete", L), key=f"del_draft_{rid}", use_container_width=True):
                    storage.delete_draft(username, rid)
                    st.rerun()

    st.markdown("---")

    st.subheader(f"✅  {t('finished_reports', L)}")
    all_finished = storage.list_finished(username)
    finished = [f for f in all_finished if f.get("club") == club]
    if not finished:
        st.caption(t("no_finished", L))
    else:
        for f in finished:
            rid = f["report_id"]
            title = _report_title(f)
            st.markdown(
                f"""<div class="report-card">
                <h4>{title}</h4>
                <div class="meta">{f['club']} ({f['language']}) · {t('finished_at', L)}: {_ts_str(f['finished_at'])}</div>
                </div>""",
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([2, 1])
            with c1:
                pptx_bytes = storage.load_finished_pptx(username, rid)
                if pptx_bytes:
                    st.download_button(
                        f"📥  {t('download_pptx', L)}", data=pptx_bytes,
                        file_name=f"Scout_{title.replace(' ','_').replace('—','_')}_{rid[:8]}.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key=f"dl_{rid}", use_container_width=True,
                    )
            with c2:
                if st.button(t("delete", L), key=f"del_fin_{rid}", use_container_width=True):
                    storage.delete_finished(username, rid)
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: New Report
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
            pos_list = list(TEMPLATES.keys())
            if draft["position"] in pos_list:
                st.session_state["empty_template_select"] = pos_list.index(draft["position"])
            st.session_state["empty_prev_key"] = f"{draft['club']}|{draft['language']}|{draft['position']}"
            for i, v in enumerate(draft["star_values"]):
                st.session_state[f"empty_{i}"] = float(v)
            for i, c in enumerate(draft["comments"]):
                st.session_state[f"empty_{i}_comment"] = c or ""
            for i, vd in enumerate(draft.get("video_data", [])):
                st.session_state[f"empty_{i}_video"] = vd
            if draft.get("player_data"):
                st.session_state["player_data"] = draft["player_data"]
            st.session_state["_loaded_draft"] = draft_id
            st.rerun()

    # ── SciSports player search ──────────────────────────────────────────────
    player_data = _scisports_section(key_prefix="sci")

    st.markdown("---")

    # ── Role selector (pre-select from SciSports) ───────────────────────────
    template_names = list(TEMPLATES.keys())
    if player_data and player_data.get("template_position"):
        sci_position = player_data["template_position"]
        if sci_position in template_names and "empty_template_select" not in st.session_state:
            st.session_state["empty_template_select"] = template_names.index(sci_position)

    template_name = st.selectbox(t("role_label", L), template_names, key="empty_template_select")
    template_cfg = get_template_config(template_name, club, lang)

    # Reset on club / language / position change
    reset_key = f"{club}|{lang}|{template_name}"
    if st.session_state.get("empty_prev_key") != reset_key:
        for i in range(20):
            st.session_state[f"empty_{i}"]         = 0.0
            st.session_state[f"empty_{i}_video"]   = None
            st.session_state[f"empty_{i}_comment"] = ""
        st.session_state["empty_prev_key"] = reset_key
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
        if st.button(f"{t('save_draft', L)}", use_container_width=True):
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
        if st.button(f"{t('generate_pptx', L)}", type="primary", use_container_width=True, key="empty_gen"):
            s, c, v = _collect_editor_state("empty", len(template_cfg["variables"]))
            with st.spinner(t("building_report", L)):
                output = fill_template(
                    template_cfg, s, c, v,
                    player_data=st.session_state.get("player_data"),
                )
            pptx_bytes = output.getvalue()

            rid = st.session_state.get("active_report_id") or storage.save_draft(
                username, None, template_name, club, lang, s, c, v,
                source="empty",
                player_data=st.session_state.get("player_data"),
            )
            storage.save_finished(username, rid, template_name, club, lang, pptx_bytes,
                                  player_name=_current_player_name())
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

        # Switch theme if detected club differs from sidebar selection
        if detected_club and detected_club != club:
            _apply_theme(detected_club)
            _render_header(detected_club, detected_lang)

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

        # ── Player info section for Upload & Edit ────────────────────────────
        st.markdown("---")
        upload_player_data = _scisports_section(key_prefix="upload_sci")

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
            if st.button(f"{t('save_draft', L)}", use_container_width=True, key="upload_save"):
                s, c, v = _collect_editor_state("upload", len(template_cfg["variables"]))
                rid = storage.save_draft(
                    username,
                    st.session_state.get("upload_active_report_id"),
                    matched_name or "Unknown", detected_club, detected_lang, s, c, v,
                    source="upload",
                    upload_bytes=st.session_state.get("upload_bytes"),
                    upload_filename=st.session_state.get("upload_filename"),
                    player_data=st.session_state.get("player_data"),
                )
                st.session_state["upload_active_report_id"] = rid
                st.success(f"{t('draft_saved', L)} (ID: {rid[:8]})")

        with col_gen:
            if st.button(f"{t('generate_pptx', L)}", type="primary", use_container_width=True, key="upload_gen"):
                s, c, v = _collect_editor_state("upload", len(template_cfg["variables"]))
                with st.spinner(t("filling", L)):
                    output = fill_from_bytes(
                        st.session_state["upload_bytes"], template_cfg, s, c, v,
                        player_data=st.session_state.get("player_data"),
                    )
                pptx_bytes = output.getvalue()
                pos = matched_name or "Unknown"

                rid = st.session_state.get("upload_active_report_id") or storage.save_draft(
                    username, None, pos, detected_club, detected_lang, s, c, v,
                    source="upload",
                    upload_bytes=st.session_state.get("upload_bytes"),
                    upload_filename=st.session_state.get("upload_filename"),
                    player_data=st.session_state.get("player_data"),
                )
                storage.save_finished(username, rid, pos, detected_club, detected_lang, pptx_bytes,
                                      player_name=_current_player_name())
                st.session_state.pop("upload_active_report_id", None)

                st.success(t("done", L))
                fname = st.session_state.get("upload_filename", "report.pptx")
                st.download_button(
                    f"📥  {t('download_filled', L)}", data=pptx_bytes,
                    file_name=f"Filled_{fname}",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    use_container_width=True,
                )
