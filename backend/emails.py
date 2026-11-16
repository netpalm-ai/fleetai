"""Send transactional email over SMTP."""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT_SECONDS = 10


def _send_link(to: str, subject: str, intro: str, path: str, token: str, valid_for: str) -> None:
    user = (os.getenv("SMTP_EMAIL_USER") or "").strip()
    sender = (os.getenv("NO_REPLY_EMAIL_ALIAS") or "").strip()
    base_url = (os.getenv("PRODUCT_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not user or not sender or not base_url:
        logger.warning(
            "email not sent: SMTP_EMAIL_USER, NO_REPLY_EMAIL_ALIAS and PRODUCT_PUBLIC_BASE_URL must be set"
        )
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to
    message.set_content(
        f"{intro}:\n\n{base_url}{path}?token={token}\n\nThe link is valid for {valid_for}.\n"
        "If you did not ask for this, ignore this email.\n"
    )
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            smtp.starttls()
            smtp.login(user, os.getenv("SMTP_PASSWORD") or "")
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError):
        logger.exception("email to %s failed", to)


def send_verification_email(product_name: str, to: str, token: str, valid_days: int) -> None:
    _send_link(
        to,
        f"Verify your {product_name} email",
        f"Confirm your email to finish creating your {product_name} account",
        "/verify",
        token,
        f"{valid_days} days",
    )


def send_password_reset_email(product_name: str, to: str, token: str, valid_minutes: int) -> None:
    _send_link(
        to,
        f"Reset your {product_name} password",
        f"Choose a new password for your {product_name} account",
        "/reset",
        token,
        f"{valid_minutes} minutes",
    )
