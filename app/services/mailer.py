"""Email delivery for the app (password reset links).

Uses stdlib ``smtplib`` so there are no extra dependencies. When no SMTP
host is configured the sender falls back to logging the message and returns
False, letting the caller surface the reset link in the UI instead.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import current_app

LOGGER = logging.getLogger(__name__)


class Mailer:
    """Minimal SMTP sender backed by app configuration."""

    @staticmethod
    def configured() -> bool:
        return bool(current_app.config.get("SMTP_HOST"))

    @staticmethod
    def send_password_reset(to_email: str, username: str, reset_link: str) -> bool:
        subject = "Reset your InventoryLogix password"
        body = (
            f"Hi {username},\n\n"
            "You asked to reset your InventoryLogix password. Use the link "
            "below to choose a new one:\n\n"
            f"{reset_link}\n\n"
            "This link expires within "
            f"{current_app.config['PASSWORD_RESET_TTL_MINUTES']} minutes. If "
            "you didn't request this, you can safely ignore this email.\n\n"
            "— InventoryLogix"
        )
        return Mailer.send(to_email, subject, body)

    @staticmethod
    def send(to_email: str, subject: str, plain_body: str) -> bool:
        cfg = current_app.config
        if not Mailer.configured():
            LOGGER.warning(
                "SMTP not configured — password reset link for %s: %s",
                to_email,
                plain_body,
            )
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr(("InventoryLogix", cfg["MAIL_FROM"]))
        msg["To"] = to_email
        msg.attach(MIMEText(plain_body, "plain"))

        try:
            with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=10) as server:
                if cfg.get("MAIL_USE_TLS"):
                    server.starttls()
                if cfg.get("SMTP_USERNAME"):
                    server.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
                server.sendmail(cfg["MAIL_FROM"], [to_email], msg.as_string())
        except (OSError, smtplib.SMTPException) as exc:
            LOGGER.exception("Failed to send email to %s: %s", to_email, exc)
            return False
        return True