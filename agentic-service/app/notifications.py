"""Email notifications - welcome, approval, billing events (Phase C4).

Sends transactional emails:
  - welcome (signup)
  - approval_request (Ops Copilot - a dossier needs review)
  - approval_decided (Ops Copilot - the admin approved/rejected)
  - billing_activated (Stripe checkout completed)

Transport: SMTP (via aiosmtplib) when SMTP_HOST is set. Otherwise, logs
the email to stdout (dev mode - the email content is visible in the logs
so the developer can verify the template + content without a mail server).

Templates: plain French text, minimal HTML. No external template engine -
keeps the dependency count low. Each template is a function that returns
``(subject, body_text, body_html)``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("tevet7.notifications")


@dataclass
class EmailMessage:
    to: str
    subject: str
    body_text: str
    body_html: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────────────────────


def welcome_email(name: str, email: str) -> EmailMessage:
    return EmailMessage(
        to=email,
        subject=f"Bienvenue sur Tevet-7, {name} !",
        body_text=(
            f"Bonjour {name},\n\n"
            f"Bienvenue sur Tevet-7 - la plateforme d'agents IA configurable.\n\n"
            f"Votre compte est créé. Prochaine étape : créez votre workspace "
            f"et connectez vos données pour activer votre agent.\n\n"
            f"- L'équipe Tevet-7"
        ),
        body_html=(
            f"<p>Bonjour {name},</p>"
            f"<p>Bienvenue sur <strong>Tevet-7</strong> - la plateforme d'agents IA configurable.</p>"
            f"<p>Votre compte est créé. Prochaine étape : créez votre workspace "
            f"et connectez vos données pour activer votre agent.</p>"
            f"<p>- L'équipe Tevet-7</p>"
        ),
    )


def approval_request_email(email: str, legal_name: str, proposed: str, confidence: int) -> EmailMessage:
    return EmailMessage(
        to=email,
        subject=f"[Tevet-7] Dossier à valider : {legal_name}",
        body_text=(
            f"Un nouveau dossier d'onboarding nécessite votre attention.\n\n"
            f"Producteur : {legal_name}\n"
            f"Recommandation : {proposed} (confiance {confidence}%)\n\n"
            f"Connectez-vous à Tevet-7 pour valider ou refuser ce dossier.\n\n"
            f"- L'équipe Tevet-7"
        ),
    )


def approval_decided_email(email: str, legal_name: str, decision: str) -> EmailMessage:
    return EmailMessage(
        to=email,
        subject=f"[Tevet-7] Dossier {decision} : {legal_name}",
        body_text=(
            f"Le dossier de {legal_name} a été {decision}.\n\n"
            f"- L'équipe Tevet-7"
        ),
    )


def billing_activated_email(email: str, plan: str) -> EmailMessage:
    return EmailMessage(
        to=email,
        subject=f"[Tevet-7] Abonnement {plan} activé",
        body_text=(
            f"Votre abonnement {plan} est actif.\n\n"
            f"Vous pouvez maintenant utiliser toutes les fonctionnalités Tevet-7.\n\n"
            f"- L'équipe Tevet-7"
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Transport
# ─────────────────────────────────────────────────────────────────────────────


async def send_email(msg: EmailMessage) -> bool:
    """Send an email. Returns True on success, False on failure.

    When SMTP_HOST is not set (dev mode), logs the email content to stdout
    instead of sending - the developer can verify templates without a mail
    server.
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    if not smtp_host:
        # Dev mode: log the email.
        logger.info(
            "📧 EMAIL (dev mode, not sent)\n  To: %s\n  Subject: %s\n  Body: %s",
            msg.to, msg.subject, msg.body_text[:200],
        )
        return True

    try:
        import aiosmtplib  # type: ignore[import-untyped]
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        message = MIMEMultipart("alternative")
        message["From"] = os.environ.get("SMTP_FROM", "noreply@tevet7.dev")
        message["To"] = msg.to
        message["Subject"] = msg.subject
        message.attach(MIMEText(msg.body_text, "plain", "utf-8"))
        if msg.body_html:
            message.attach(MIMEText(msg.body_html, "html", "utf-8"))

        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USER", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            start_tls=True,
        )
        logger.info("📧 Email sent to %s: %s", msg.to, msg.subject)
        return True
    except Exception as exc:
        logger.warning("Email send failed: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Convenience functions (fire-and-forget)
# ─────────────────────────────────────────────────────────────────────────────


def notify_welcome(name: str, email: str) -> None:
    """Send a welcome email (fire-and-forget, non-blocking)."""
    asyncio.create_task(send_email(welcome_email(name, email)))


def notify_approval_request(email: str, legal_name: str, proposed: str, confidence: int) -> None:
    asyncio.create_task(send_email(approval_request_email(email, legal_name, proposed, confidence)))


def notify_approval_decided(email: str, legal_name: str, decision: str) -> None:
    asyncio.create_task(send_email(approval_decided_email(email, legal_name, decision)))


def notify_billing_activated(email: str, plan: str) -> None:
    asyncio.create_task(send_email(billing_activated_email(email, plan)))
