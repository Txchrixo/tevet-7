"""Guardrails — prompt injection, PII detection, content moderation.

Deterministic (0 token, <1ms). Runs BEFORE the LLM is called.
  1. detect_prompt_injection — 12 regex patterns.
  2. detect_pii — email, phone, IBAN, SIRET, credit card (flags, redacts).
  3. moderate_content — harmful keyword blocklist.
  4. check_message — combined (injection→moderation→PII flag).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("tevet7.guardrails")


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""

    blocked: bool
    reason: str = ""
    category: str = ""

    @classmethod
    def pass_(cls) -> "GuardrailResult":
        return cls(blocked=False)

    @classmethod
    def block(cls, reason: str, category: str) -> "GuardrailResult":
        return cls(blocked=True, reason=reason, category=category)


_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I),
    re.compile(r"forget\s+(all\s+)?(your\s+)?(previous|prior|above)", re.I),
    re.compile(r"you\s+are\s+(now|no longer)\s+(an?\s+)?(ai|assistant|agent|admin|root|developer)", re.I),
    re.compile(r"system\s*:\s*", re.I),
    re.compile(r"<\s*system\s*>", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(a|an)?\s*(different|root|admin)", re.I),
    re.compile(r"act\s+as\s+(if\s+you\s+(are|were)\s+)?(root|admin|developer)", re.I),
    re.compile(r"(reveal|show|print|output)\s+(your\s+)?(system\s+)?prompt", re.I),
    re.compile(r"what\s+(are|is)\s+your\s+(instructions|rules|system\s+prompt)", re.I),
    re.compile(r"(access|query|select)\s+(all\s+)?(tenants|users|producers?\s+data|passwords?)", re.I),
    re.compile(r"bypass\s+(the\s+)?(scope|security|filter)", re.I),
]

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+33|0)\s*[1-9](?:[\s.-]*\d{2}){4}\b")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?\d{4}){5,7}\d?\b")
_SIRET_RE = re.compile(r"\b\d{14}\b")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_HARMFUL_KEYWORDS = (
    "bombe", "bomb", "explosif", "explosive", "attentat", "terroris",
    "arme à feu", "firearm", "munition", "drogue", "drug trafficking",
    "child abuse", "pédophilie", " pédophile",
)


def detect_prompt_injection(message: str) -> GuardrailResult:
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(message):
            return GuardrailResult.block(
                reason=f"Tentative d'injection de prompt détectée",
                category="prompt_injection",
            )
    return GuardrailResult.pass_()


def detect_pii(message: str) -> GuardrailResult:
    found: list[str] = []
    if _EMAIL_RE.search(message):
        found.append("email")
    if _PHONE_RE.search(message):
        found.append("phone")
    if _IBAN_RE.search(message):
        found.append("IBAN")
    if _SIRET_RE.search(message):
        found.append("SIRET")
    if _CREDIT_CARD_RE.search(message):
        found.append("credit_card")
    if found:
        return GuardrailResult(blocked=False, reason=f"PII: {', '.join(found)}", category="pii")
    return GuardrailResult.pass_()


def redact_pii(message: str) -> str:
    message = _EMAIL_RE.sub("[REDACTED_EMAIL]", message)
    message = _PHONE_RE.sub("[REDACTED_PHONE]", message)
    message = _IBAN_RE.sub("[REDACTED_IBAN]", message)
    message = _SIRET_RE.sub("[REDACTED_SIRET]", message)
    message = _CREDIT_CARD_RE.sub("[REDACTED_CC]", message)
    return message


def moderate_content(message: str) -> GuardrailResult:
    msg_lower = message.lower()
    for kw in _HARMFUL_KEYWORDS:
        if kw in msg_lower:
            return GuardrailResult.block(
                reason=f"Contenu potentiellement nuisible détecté",
                category="moderation",
            )
    return GuardrailResult.pass_()


def check_message(message: str) -> GuardrailResult:
    """Run all guardrail checks. Returns first BLOCK or pass."""
    result = detect_prompt_injection(message)
    if result.blocked:
        logger.warning("Guardrail BLOCK (injection): %s", result.reason)
        return result
    result = moderate_content(message)
    if result.blocked:
        logger.warning("Guardrail BLOCK (moderation): %s", result.reason)
        return result
    result = detect_pii(message)
    if result.category == "pii":
        logger.info("Guardrail PII flag: %s", result.reason)
    return GuardrailResult.pass_()
