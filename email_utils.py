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


def _send(to_addr: str, subject: str, body: str) -> tuple[bool, str | None]:
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

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_addr"], [to_addr], msg.as_string())
        return True, None
    except Exception as exc:
        return False, str(exc)


def send_share_emails(
    sender_name: str,
    sender_email: str,
    receiver_name: str,
    receiver_email: str,
    player_name: str,
) -> dict:
    """Send the two share notifications.

    Returns a dict like {"receiver": (ok, err), "sender": (ok, err)}.
    Missing email addresses silently skip that side.
    """
    results: dict = {}
    safe_player = player_name or "—"

    # 1. Email to the RECEIVER — with platform link
    if receiver_email:
        subject = f"New scout report received: {safe_player}"
        body = (
            f"Hi {receiver_name},\n\n"
            f"A new scouting report for player {safe_player} has just been "
            f"shared with you on the Scouting Rapport Pro+ platform.\n\n"
            f"View it here: {PLATFORM_URL}\n\n"
            f"Best regards,\n{sender_name}"
        )
        results["receiver"] = _send(receiver_email, subject, body)
    else:
        results["receiver"] = (False, "no receiver email")

    # 2. Email to the SENDER — confirmation, no link
    if sender_email:
        subject = f"Report of {safe_player} successfully shared"
        body = (
            f"Hi {sender_name},\n\n"
            f"Your scouting report for {safe_player} has been successfully "
            f"shared with scout {receiver_name}.\n\n"
            f"Best regards,\nScouting Rapport Pro+"
        )
        results["sender"] = _send(sender_email, subject, body)
    else:
        results["sender"] = (False, "no sender email")

    return results