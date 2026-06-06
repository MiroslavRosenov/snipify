from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger as log

from app.config import Config


class SMTPClient:
    instance: Optional["SMTPClient"] = None
    _jinja_env: Optional[Environment] = None

    def __init__(
        self,
        server: str,
        port: int,
        login: str,
        password: str,
        use_ssl: bool = False,
    ) -> None:
        self._server = server
        self._port = port
        self._login = login
        self._password = password
        self._use_ssl = use_ssl

    # ── Lifecycle ───────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> Optional["SMTPClient"]:
        if cls.instance is not None:
            return cls.instance

        if not Config.smtp_configured():
            log.warning("SMTP not configured – email sending is disabled")
            return None

        cls.instance = cls(
            server=Config.SMTP_SERVER,
            port=Config.SMTP_PORT,
            login=Config.SMTP_LOGIN,
            password=Config.SMTP_PASSWORD,
            use_ssl=Config.SMTP_USE_SSL,
        )
        log.info(
            "SMTPClient initialised ({}:{}, ssl={})",
            Config.SMTP_SERVER,
            Config.SMTP_PORT,
            Config.SMTP_USE_SSL,
        )
        return cls.instance

    @classmethod
    async def cleanup(cls) -> None:
        if cls.instance:
            log.info("SMTPClient cleaned up")
            cls.instance = None

    # ── Template rendering ──────────────────────────────────────────────────

    @classmethod
    def _get_jinja_env(cls) -> Environment:
        if cls._jinja_env is None:
            cls._jinja_env = Environment(
                loader=FileSystemLoader(Path(__file__).parent / "templates" / "emails"),
                autoescape=select_autoescape(["html"]),
            )
        return cls._jinja_env

    @classmethod
    def render(cls, template_name: str, **context: object) -> str:
        return cls._get_jinja_env().get_template(template_name).render(**context)

    # ── Sending ─────────────────────────────────────────────────────────────

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        from_name: str = "Snipify",
        from_email: str,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._send_sync,
                to=to,
                subject=subject,
                html=html,
                from_name=from_name,
                from_email=from_email,
            )
        except Exception as exc:
            log.opt(exception=exc).error(
                "send() failed for '{}' → {} – {}", subject, to, exc
            )
            raise

    def _send_sync(
        self, *, to: str, subject: str, html: str, from_name: str, from_email: str
    ) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))

        try:
            if self._use_ssl:
                with smtplib.SMTP_SSL(self._server, self._port) as smtp:
                    smtp.login(self._login, self._password)
                    smtp.sendmail(self._login, to, msg.as_string())
            else:
                with smtplib.SMTP(self._server, self._port) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.login(self._login, self._password)
                    smtp.sendmail(self._login, to, msg.as_string())

            log.success("Email '{}' sent to {}", subject, to)

        except Exception as exc:
            log.opt(exception=exc).error(
                "Failed to send email '{}' to {} – {}", subject, to, exc
            )
            raise

    async def send_template(
        self,
        *,
        to: str,
        subject: str,
        template: str,
        context: dict,
        from_name: str,
        from_email: str,
    ) -> None:
        html = self.render(template, **context)
        await self.send(
            to=to,
            subject=subject,
            html=html,
            from_name=from_name,
            from_email=from_email,
        )
