"""Email delivery for the app (password reset links).

Uses stdlib ``smtplib`` so there are no extra dependencies. When no SMTP
host is configured the sender falls back to logging the message and returns
False, letting the caller surface the reset link in the UI instead.

Also supports SendGrid API (HTTPS) which works on platforms that block
outbound SMTP ports (e.g. Render free tier).

The ``send_password_reset`` method sends an HTML email with the
InventoryLogix logo embedded as a CID attachment so the image appears
directly in the user's email client without being blocked.
"""
from __future__ import annotations

import base64
import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import current_app

try:
    import sendgrid
    from sendgrid.helpers.mail import Mail, Email, To, Content
    _HAS_SENDGRID = True
except Exception:
    _HAS_SENDGRID = False

LOGGER = logging.getLogger(__name__)


class Mailer:
    """Minimal SMTP/SendGrid sender backed by app configuration."""

    @staticmethod
    def configured() -> bool:
        cfg = current_app.config
        return bool(cfg.get("SMTP_HOST") or cfg.get("SENDGRID_API_KEY"))

    @staticmethod
    def _embed_logo_img() -> MIMEImage:
        """Read the app logo SVG and return a MIMEImage with a CID."""
        svg_path = current_app.static_folder + "/img/logo.svg"
        with open(svg_path, "rb") as f:
            svg_bytes = f.read()
        img = MIMEImage(svg_bytes, _subtype="svg")
        # Content-ID must NOT include angle brackets; Mailer will add them.
        img.add_header("Content-ID", "<logo>")
        img.add_header("Content-Disposition", "inline", filename="logo.svg")
        return img

    @staticmethod
    def _send_via_sendgrid(to_email: str, username: str, reset_link: str) -> bool:
        cfg = current_app.config
        api_key = cfg.get("SENDGRID_API_KEY")
        if not api_key:
            return False
        try:
            sg = sendgrid.SendGridAPIClient(api_key=api_key)
            from_email = Email(cfg["MAIL_FROM"], "InventoryLogix")
            to_email_obj = To(to_email)
            subject = "Reset your InventoryLogix password"
            html = Mailer._html_body(username, reset_link)
            plain = (
                f"Hi {username},\n\n"
                "You asked to reset your InventoryLogix password. Use the link "
                "below to choose a new one:\n\n"
                f"{reset_link}\n\n"
                f"This link expires within "
                f"{current_app.config['PASSWORD_RESET_TTL_MINUTES']} minutes. If "
                "you didn't request this, you can safely ignore this email.\n\n"
                "— InventoryLogix"
            )
            mail = Mail(from_email, to_email_obj, subject, Content("text/plain", plain), Content("text/html", html))
            response = sg.client.mail.send.post(request_body=mail.get())
            return 200 <= response.status_code < 300
        except Exception as exc:
            LOGGER.exception("SendGrid send failed to %s: %s", to_email, exc)
            return False

    @staticmethod
    def send_password_reset(to_email: str, username: str, reset_link: str) -> bool:
        subject = "Reset your InventoryLogix password"
        html = Mailer._html_body(username, reset_link)
        plain = (
            f"Hi {username},\n\n"
            "You asked to reset your InventoryLogix password. Use the link "
            "below to choose a new one:\n\n"
            f"{reset_link}\n\n"
            f"This link expires within "
            f"{current_app.config['PASSWORD_RESET_TTL_MINUTES']} minutes. If "
            "you didn't request this, you can safely ignore this email.\n\n"
            "— InventoryLogix"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr(("InventoryLogix", current_app.config["MAIL_FROM"]))
        msg["To"] = to_email

        # Attach plain‑text version
        msg.attach(MIMEText(plain, "plain"))

        # Attach HTML version with embedded logo
        msg.attach(MIMEText(html, "html"))

        # Attach the logo as an inline image
        try:
            logo_img = Mailer._embed_logo_img()
            msg.attach(logo_img)
        except FileNotFoundError:
            LOGGER.warning("Logo file not found — sending without embedded image.")

        cfg = current_app.config
        
        # Try SendGrid first (HTTPS, works on free tier)
        if cfg.get("SENDGRID_API_KEY"):
            return Mailer._send_via_sendgrid(to_email, username, reset_link)

        # Fallback to SMTP
        if not cfg.get("SMTP_HOST"):
            LOGGER.warning(
                "SMTP not configured — password reset link for %s: %s",
                to_email,
                html,
            )
            return False

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

    @staticmethod
    def _html_body(username: str, reset_link: str) -> str:
        """Render the HTML email body with the embedded logo CID reference."""
        ttl = current_app.config.get("PASSWORD_RESET_TTL_MINUTES", 5)
        return f"""\
        <html>
        <body style="font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 1rem;">
            <div style="max-width: 600px; margin: 0 auto;">
                <a href="{{ url_for('ui.dashboard') }}" style="display: block; text-decoration: none; color: inherit;">
                    <img src="cid:logo" alt="InventoryLogix" style="width: 40px; margin: 1rem 0 0 0;">
                </a>
                <h2 style="color: #3d997c; text-align: center; margin: 1rem 0;">Reset your password</h2>
                <p style="color: #555; line-height: 1.5;">
                    Hi <strong>{username}</strong>,
                </p>
                <p style="color: #555; line-height: 1.5;">
                    You asked to reset your InventoryLogix password. Use the link
                    below to choose a new one:
                </p>
                <p style="margin: 1rem 0; text-align: center;">
                    <a href="{reset_link}"
                       style="background: #3d997c; color: #fff; padding: 0.75rem 1.5rem;
                              text-decoration: none; border-radius: 4px; font-size: 1rem;">
                        Reset Password
                    </a>
                </p>
                <p style="color: #888; font-size: 0.85rem; line-height: 1.5;">
                    This link expires within <strong>{ttl}</strong> minutes.
                    If you didn't request this, you can safely ignore this email.
                </p>
                <p style="color: #888; font-size: 0.85rem; line-height: 1.5; margin-top: 2rem;">
                    — InventoryLogix
                </p>
            </div>
        </body>
        </html>
        """

    @staticmethod
    def send(to_email: str, subject: str, plain_body: str) -> bool:
        """Legacy sender — kept for backward compatibility.

        Sends a plain‑text email only (no logo, no HTML). Use
        ``send_password_reset`` for the new HTML-with-logo version.
        """
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