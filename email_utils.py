"""SMTP email notifications for share events.

Reads SMTP credentials from st.secrets:

    [smtp]
    host = "smtp.gmail.com"
    port = 587
    username = "youraddress@gmail.com"
    password = "your-app-password"
    from_addr = "youraddress@gmail.com"   # optional, defaults to username
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import streamlit as st

PLATFORM_URL = "https://scouttemplateproject-mfydbrjqsrwjmcv3xnzm98.streamlit.app"


def _get_smtp_config() -> dict | None:
    try:
        smtp = st.secrets.get("smtp", {})
    except Exception:
        return None
    if not smtp:
        return None
    return {
        "host": smtp.get("host", "smtp.gmail.com"),
        "port": int(smtp.get("port", 587)),
        "username": smtp.get("username", ""),
        "password": smtp.get("password", ""),
        "from_addr": smtp.get("from_addr") or smtp.get("username", ""),
    }


def _send(
    to_addr: str,
    subject: str,
    body: str,
    attachment: bytes | None = None,
    attachment_filename: str | None = None,
) -> tuple[bool, str | None]:
    cfg = _get_smtp_config()
    if not cfg or not cfg["username"] or not cfg["password"]:
        return False, "SMTP credentials not configured in secrets"
    if not to_addr:
        return False, "no recipient address"

    msg = MIMEMultipart()
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if attachment and attachment_filename:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_addr"], [to_addr], msg.as_string())
        return True, None
    except Exception as exc:
        return False, str(exc)


def send_share_email(
    sender_name: str,
    receiver_name: str,
    receiver_email: str,
    player_name: str,
    pptx_bytes: bytes,
    pptx_filename: str,
) -> tuple[bool, str | None]:
    """Email the generated PowerPoint to the receiver.

    Returns (ok, error_message).
    """
    safe_player = player_name or "—"

    if not receiver_email:
        return False, "no receiver email"

    subject = f"Scout report: {safe_player}"
    body = (
        f"Hi {receiver_name},\n\n"
        f"A scouting report for player {safe_player} has been "
        f"shared with you by {sender_name}.\n\n"
        f"The PowerPoint is attached to this email.\n\n"
        f"Best regards,\nScouting Rapport Pro+"
    )
    return _send(
        receiver_email, subject, body,
        attachment=pptx_bytes,
        attachment_filename=pptx_filename,
    )