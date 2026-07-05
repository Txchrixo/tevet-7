"""OpsCopilotAgent - Phase 4 human-in-the-loop Ops assistant.

The agent pre-analyzes Drive Producteur producer-onboarding dossiers and
PROPOSES a decision (approve / reject / request_info). It NEVER approves or
rejects on its own - that decision is reserved for a human admin via the
``/api/approvals/{id}/decide`` endpoint. This is the core human-in-the-loop
(HITL) argument for the platform: the agent does the tedious pre-analysis
(SIRET check, document completeness, address consistency, cert expiry),
the admin does the final call.

Business rules (mirror the DP onboarding procedure seeded as a RAG document)
==========================================================================

For each onboarding dossier, the agent runs 5 deterministic checks:

1. **SIRET check.** Three sub-checks: 14 digits (format), Luhn algorithm
   (informational - surfaced as a warning if it fails but the SIRENE flag is
   OK), and ``siret_valid`` flag (authoritative - comes from the SIRENE API
   call done at ingest time by the Ops team). SIRET invalid (siret_valid=
   False) is a **legal blocker** → propose REJECT.
2. **Documents check.** All 5 required pieces must be present: legal_name,
   siret, rib_document, id_document, professional_certificate. Missing →
   propose REQUEST_INFO.
3. **Address consistency.** ``declared_address`` vs ``document_address``
   (the address printed on the uploaded ID document). Substring / token
   overlap heuristic - not perfect, just a flag for the human reviewer.
   Mismatch → propose REJECT.
4. **Cert expiry.** ``professional_certificate_expiry`` must be in the
   future. Expired → propose REJECT.
5. **Aggregation + recommendation.** Combine the issues, pick the
   ``proposed_decision`` per the priority:

       REJECT  > REQUEST_INFO > APPROVE

   (a single reject-grade issue is enough to reject; a single info-grade
   issue downgrades to request_info; no issues → approve).

Confidence: 100 % if no issues, -20 % per issue (floored at 0 %).

Tracing
=======

Every ``analyze_onboarding`` call opens a trace + a span
``ops_onboarding_analysis`` with 6 sub-steps (SIRET check, documents check,
address check, cert check, aggregation, recommendation). The trace_id is
stored on the corresponding ``approval_requests`` row (``trace_id`` column)
so the audit trail links the human decision back to the agent's pre-analysis.

No LLM
======

Phase 4 keeps the agent rule-based - the same design choice as Phase 1's
SQL generator. The rules are deterministic and auditable; an LLM can be
swapped in Phase 6 to draft the ``proposed_reason`` free-text without
touching the rule layer.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from app.tracing.base import Span, TraceContext, Tracer

logger = logging.getLogger("tevet7.ops_copilot")


# ─────────────────────────────────────────────────────────────────────────────
# No-op tracer fallback (mirrors orchestrator._NoopTracer)
# ─────────────────────────────────────────────────────────────────────────────


class _NoopTracer:
    """Fallback tracer used when callers don't supply one.

    The approvals API always passes the real tracer (LocalTracer or
    LangfuseTracer via :func:`app.tracing.get_tracer`); this class only
    exists so the agent can be constructed in scripts/tests/seed-time
    without a tracer.
    """

    def start_trace(self, user_message: str, identity: dict[str, Any]) -> TraceContext:
        return TraceContext(
            trace_id=TraceContext.new_trace_id(),
            user_message=user_message,
            identity=dict(identity),
        )

    def start_span(self, ctx: TraceContext, name: str, **metadata: Any) -> Span:
        span = Span(name=name, started_at=time.monotonic(), metadata=dict(metadata))
        ctx.spans.append(span)
        return span

    def end_span(
        self,
        ctx: TraceContext,
        span: Span,
        status: str = "ok",
        **metadata: Any,
    ) -> None:
        span.ended_at = time.monotonic()
        span.status = status
        if metadata:
            span.metadata.update(metadata)

    async def end_trace(self, ctx: TraceContext, result: dict[str, Any]) -> str:
        return ctx.trace_id

    def flush(self) -> None:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class OpsIssue:
    """One issue found during the onboarding pre-analysis.

    ``severity`` is one of:

    * ``"blocker"``   - legal/compliance problem → REJECT (SIRET invalid,
      cert expired, address mismatch).
    * ``"missing"``   - required piece absent → REQUEST_INFO (missing doc,
      missing field).
    * ``"warning"``   - informational (Luhn failed but SIRENE OK, etc.).

    ``code`` is a stable machine identifier so the admin UI can group /
    filter issues by type.
    """

    severity: str  # "blocker" | "missing" | "warning"
    code: str      # "siret_invalid_sirene" | "cert_expired" | ...
    message: str   # human-readable French


@dataclass
class OpsCheck:
    """One named check + its pass/warn/blocked status + detail string."""

    name: str
    status: str  # "ok" | "warning" | "blocked"
    detail: str


@dataclass
class OpsAnalysis:
    """Full structured result of ``analyze_onboarding``.

    Serialised 1:1 to JSON for the ``approval_requests.agent_analysis``
    column, the ``/api/approvals`` endpoints, and the chat-driven
    ``ops_analysis`` field on ``AgentResponse``.
    """

    issues: list[OpsIssue] = field(default_factory=list)
    proposed_decision: str = "approve"  # "approve" | "reject" | "request_info"
    proposed_reason: str = ""
    confidence: int = 100  # 0-100, 100 if no issues
    checks: list[OpsCheck] = field(default_factory=list)
    onboarding_id: int | None = None
    legal_name: str | None = None
    siret: str | None = None
    trace_id: str | None = None  # Langfuse trace_id of this analysis run
    analyzed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict (for DB storage + API responses)."""
        return {
            "issues": [asdict(i) for i in self.issues],
            "proposed_decision": self.proposed_decision,
            "proposed_reason": self.proposed_reason,
            "confidence": self.confidence,
            "checks": [asdict(c) for c in self.checks],
            "onboarding_id": self.onboarding_id,
            "legal_name": self.legal_name,
            "siret": self.siret,
            "trace_id": self.trace_id,
            "analyzed_at": self.analyzed_at,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SIRET Luhn check
# ─────────────────────────────────────────────────────────────────────────────


_SIRET_RE = re.compile(r"^\d{14}$")


def _luhn_valid(siret: str) -> bool:
    """Standard Luhn checksum on the 14 digits (SIRET convention).

    From the rightmost digit, double every second digit; sum all digits
    (splitting doubled values > 9 into their two digits). Valid iff the
    total is divisible by 10.
    """
    digits = [int(c) for c in siret]
    if len(digits) != 14:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:  # second, fourth, ... from the right
            d2 = d * 2
            total += d2 if d2 < 10 else (d2 // 10 + d2 % 10)
        else:
            total += d
    return total % 10 == 0


# ─────────────────────────────────────────────────────────────────────────────
# Address consistency heuristic
# ─────────────────────────────────────────────────────────────────────────────


_ADDRESS_STOPWORDS = frozenset({
    "de", "la", "le", "les", "du", "des", "et", "à", "a", "au", "aux",
    "rue", "avenue", "av", "bd", "boulevard", "chemin", "route", "place",
    "pl", "saint", "ste", "st", "the", "of", "for", "in",
})


def _address_tokens(addr: str) -> set[str]:
    """Tokenise an address into a comparable set.

    Lowercase, strip punctuation, drop French stopwords + 1-char tokens +
    pure numbers (house numbers shift between documents - we don't want a
    different street number to trigger a mismatch on its own; the human
    reviewer will catch those visually).
    """
    cleaned = re.sub(r"[^\w\s]", " ", (addr or "").lower())
    out: set[str] = set()
    for tok in cleaned.split():
        if len(tok) < 2:
            continue
        if tok in _ADDRESS_STOPWORDS:
            continue
        if tok.isdigit():
            continue
        out.add(tok)
    return out


def _addresses_consistent(declared: str | None, document: str | None) -> tuple[bool, str]:
    """Compare two free-text addresses.

    Returns ``(consistent, detail)``. Heuristic: token-overlap Jaccard ≥ 0.5
    OR one is a substring of the other. We deliberately err on the
    permissive side - false positives (flagging a matching address as
    inconsistent) waste the admin's time more than false negatives.
    """
    if not declared or not document:
        # If either is missing we can't check - treat as "skipped" (ok).
        return True, "Adresse document non fournie - check ignoré"
    if declared.strip().lower() == document.strip().lower():
        return True, "Adresses identiques"
    # Substring match (one direction catches "12 rue des Lilas" vs
    # "12 rue des Lilas, 75001 Paris").
    if declared.strip().lower() in document.strip().lower() or \
       document.strip().lower() in declared.strip().lower():
        return True, "Adresse document inclusive de l'adresse déclarée"
    a = _address_tokens(declared)
    b = _address_tokens(document)
    if not a or not b:
        return True, "Tokens insuffisants - check ignoré"
    inter = a & b
    union = a | b
    jaccard = len(inter) / len(union) if union else 0.0
    if jaccard >= 0.5:
        return True, f"Adresses cohérentes (Jaccard={jaccard:.2f})"
    return False, (
        f"Adresses incohérentes (Jaccard={jaccard:.2f}, "
        f"tokens communs={sorted(inter) or 'aucun'})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cert expiry
# ─────────────────────────────────────────────────────────────────────────────


def _parse_iso_date(value: str | None) -> date | None:
    """Parse a YYYY-MM-DD string (or None) into a ``date`` (or None)."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class OpsCopilotAgent:
    """Pre-analyzes a producer-onboarding dossier and PROPOSES a decision.

    The agent never approves or rejects - it only emits a
    ``proposed_decision`` + ``proposed_reason``. The human admin closes the
    loop via ``POST /api/approvals/{id}/decide``.

    Construction::

        agent = OpsCopilotAgent(tracer=get_tracer())
        analysis = await agent.analyze_onboarding(onboarding_dict)
    """

    def __init__(self, tracer: Tracer | None = None) -> None:
        self.tracer: Any = tracer if tracer is not None else _NoopTracer()

    async def analyze_onboarding(self, onboarding: dict[str, Any]) -> OpsAnalysis:
        """Run the 5-check pre-analysis on one onboarding dossier.

        ``onboarding`` is the dict projection of a ``producer_onboardings``
        row (legal_name, siret, siret_valid, declared_address,
        document_address, rib_document_present, id_document_present,
        professional_certificate_present,
        professional_certificate_expiry, ...).

        Traced: opens a trace + a span ``ops_onboarding_analysis`` with 6
        sub-spans (one per check + aggregation + recommendation). The
        returned ``OpsAnalysis.analyzed_at`` matches the trace timestamp.
        """
        legal_name = (onboarding.get("legal_name") or "").strip() or "<inconnu>"
        siret = (onboarding.get("siret") or "").strip()
        onboarding_id = onboarding.get("id")

        ctx = self.tracer.start_trace(
            f"ops_onboarding_analysis:{legal_name}",
            {
                "tenant_id": onboarding.get("tenant_id", "dp"),
                "onboarding_id": onboarding_id,
                "legal_name": legal_name,
                "siret": siret,
            },
        )
        root_span = self.tracer.start_span(
            ctx,
            "ops_onboarding_analysis",
            onboarding_id=onboarding_id,
            legal_name=legal_name,
        )

        issues: list[OpsIssue] = []
        checks: list[OpsCheck] = []

        # ── Sub-step 1: SIRET check ──
        siret_span = self.tracer.start_span(ctx, "ops_check_siret")
        siret_check = self._check_siret(onboarding, issues)
        checks.append(siret_check)
        self.tracer.end_span(
            ctx, siret_span,
            status="ok" if siret_check.status == "ok" else "warning",
            siret=siret,
            siret_valid_flag=onboarding.get("siret_valid"),
        )

        # ── Sub-step 2: documents check ──
        docs_span = self.tracer.start_span(ctx, "ops_check_documents")
        docs_check = self._check_documents(onboarding, issues)
        checks.append(docs_check)
        self.tracer.end_span(
            ctx, docs_span,
            status="ok" if docs_check.status == "ok" else "warning",
            missing=docs_check.detail,
        )

        # ── Sub-step 3: address consistency ──
        addr_span = self.tracer.start_span(ctx, "ops_check_address")
        addr_check = self._check_address(onboarding, issues)
        checks.append(addr_check)
        self.tracer.end_span(
            ctx, addr_span,
            status="ok" if addr_check.status == "ok" else "warning",
        )

        # ── Sub-step 4: cert expiry ──
        cert_span = self.tracer.start_span(ctx, "ops_check_cert_expiry")
        cert_check = self._check_cert_expiry(onboarding, issues)
        checks.append(cert_check)
        self.tracer.end_span(
            ctx, cert_span,
            status="ok" if cert_check.status == "ok" else "warning",
        )

        # ── Sub-step 5: aggregation ──
        agg_span = self.tracer.start_span(ctx, "ops_aggregation")
        confidence = max(0, 100 - 20 * len(issues))
        n_blockers = sum(1 for i in issues if i.severity == "blocker")
        n_missing = sum(1 for i in issues if i.severity == "missing")
        self.tracer.end_span(
            ctx, agg_span, status="ok",
            issues_count=len(issues),
            blockers=n_blockers,
            missing=n_missing,
            confidence=confidence,
        )

        # ── Sub-step 6: recommendation ──
        rec_span = self.tracer.start_span(ctx, "ops_recommendation")
        proposed_decision, proposed_reason = self._recommend(
            issues, checks, legal_name
        )
        self.tracer.end_span(
            ctx, rec_span, status="ok",
            proposed_decision=proposed_decision,
            confidence=confidence,
        )

        self.tracer.end_span(
            ctx, root_span, status="ok",
            proposed_decision=proposed_decision,
            confidence=confidence,
            issues_count=len(issues),
        )
        trace_id = await self.tracer.end_trace(
            ctx,
            {
                "answer": proposed_reason,
                "sql": None,
                "intent": "ops_onboarding_analysis",
                "refused": False,
                "tokens_in": 200,
                "tokens_out": 120,
                "latency_ms": 0,
                "tool_calls": [
                    {"name": "ops_copilot_analyze", "latency_ms": 0, "success": True}
                ],
                "steps": [
                    {"index": i + 1, "title": c.name, "detail": c.detail, "status": c.status}
                    for i, c in enumerate(checks)
                ],
            },
        )

        analysis = OpsAnalysis(
            issues=issues,
            proposed_decision=proposed_decision,
            proposed_reason=proposed_reason,
            confidence=confidence,
            checks=checks,
            onboarding_id=onboarding_id,
            legal_name=legal_name,
            siret=siret,
            trace_id=trace_id,
        )
        return analysis

    # ───────────────────────────────────────────────────────────────────────
    # Individual checks (sync helpers - easy to unit-test in isolation)
    # ───────────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_siret(
        onboarding: dict[str, Any], issues: list[OpsIssue]
    ) -> OpsCheck:
        siret = (onboarding.get("siret") or "").strip()
        siret_valid_flag = bool(onboarding.get("siret_valid"))
        if not _SIRET_RE.match(siret):
            issues.append(OpsIssue(
                severity="blocker",
                code="siret_format_invalid",
                message=(
                    f"Le SIRET « {siret} » ne respecte pas le format attendu "
                    "(14 chiffres)."
                ),
            ))
            return OpsCheck(
                name="SIRET",
                status="blocked",
                detail=f"Format invalide (14 chiffres requis), valeur='{siret}'",
            )
        luhn_ok = _luhn_valid(siret)
        if not siret_valid_flag:
            issues.append(OpsIssue(
                severity="blocker",
                code="siret_invalid_sirene",
                message=(
                    f"SIRET « {siret} » non validé par la base SIRENE "
                    "(établissement inexistant, en liquidation, ou activité "
                    "non agricole)."
                ),
            ))
            return OpsCheck(
                name="SIRET",
                status="blocked",
                detail="Validation SIRENE échouée (siret_valid=False)",
            )
        if not luhn_ok:
            # Luhn is informational only - the SIRENE flag is the
            # authoritative validity source (the SIRENE API does its own
            # algorithmic + existence checks). We surface the Luhn
            # inconsistency in the check detail so the human reviewer
            # can investigate, but we do NOT add an issue (so it does
            # not affect the proposed_decision or the confidence). This
            # also avoids double-penalising dossiers whose SIRET was
            # validated by SIRENE but happens to fail the local Luhn
            # checksum (e.g. seed data with placeholder SIRETs).
            return OpsCheck(
                name="SIRET",
                status="warning",
                detail="SIRENE OK, Luhn incohérent (vérification manuelle conseillée)",
            )
        return OpsCheck(
            name="SIRET",
            status="ok",
            detail=f"SIRET valide (14 chiffres, Luhn OK, SIRENE OK) - {siret}",
        )

    @staticmethod
    def _check_documents(
        onboarding: dict[str, Any], issues: list[OpsIssue]
    ) -> OpsCheck:
        required = [
            ("legal_name", "raison sociale"),
            ("siret", "SIRET"),
            ("rib_document_present", "RIB"),
            ("id_document_present", "pièce d'identité"),
            ("professional_certificate_present", "justificatif professionnel"),
        ]
        missing: list[str] = []
        for field_name, label in required:
            val = onboarding.get(field_name)
            if val is None or val == "" or val is False:
                missing.append(label)
        if missing:
            issues.append(OpsIssue(
                severity="missing",
                code="documents_missing",
                message=(
                    "Pièces manquantes : " + ", ".join(missing) + "."
                ),
            ))
            return OpsCheck(
                name="Documents",
                status="warning",
                detail=f"Manquants : {', '.join(missing)}",
            )
        return OpsCheck(
            name="Documents",
            status="ok",
            detail="Toutes les pièces obligatoires présentes (RIB, ID, cert, SIRET, raison sociale)",
        )

    @staticmethod
    def _check_address(
        onboarding: dict[str, Any], issues: list[OpsIssue]
    ) -> OpsCheck:
        declared = onboarding.get("declared_address")
        document = onboarding.get("document_address")
        consistent, detail = _addresses_consistent(declared, document)
        if not consistent:
            issues.append(OpsIssue(
                severity="blocker",
                code="address_inconsistent",
                message=(
                    f"Incohérence d'adresse entre l'adresse déclarée "
                    f"({declared!r}) et l'adresse du document d'identité "
                    f"({document!r}). {detail}."
                ),
            ))
            return OpsCheck(
                name="Adresse",
                status="blocked",
                detail=detail,
            )
        return OpsCheck(
            name="Adresse",
            status="ok",
            detail=detail,
        )

    @staticmethod
    def _check_cert_expiry(
        onboarding: dict[str, Any], issues: list[OpsIssue]
    ) -> OpsCheck:
        # If the cert is missing entirely, the documents check already
        # flagged it - don't double-report.
        present = bool(onboarding.get("professional_certificate_present"))
        if not present:
            return OpsCheck(
                name="Certificat pro",
                status="warning",
                detail="Certificat non fourni (signalé par le check Documents)",
            )
        expiry_raw = onboarding.get("professional_certificate_expiry")
        expiry = _parse_iso_date(expiry_raw)
        if expiry is None:
            issues.append(OpsIssue(
                severity="missing",
                code="cert_expiry_missing",
                message=(
                    "Date d'expiration du certificat professionnel non "
                    "renseignée - à demander au producteur."
                ),
            ))
            return OpsCheck(
                name="Certificat pro",
                status="warning",
                detail="Date d'expiration manquante",
            )
        today = date.today()
        if expiry < today:
            issues.append(OpsIssue(
                severity="blocker",
                code="cert_expired",
                message=(
                    f"Certificat professionnel expiré le "
                    f"{expiry.isoformat()} (date du jour : "
                    f"{today.isoformat()})."
                ),
            ))
            return OpsCheck(
                name="Certificat pro",
                status="blocked",
                detail=f"Expiré le {expiry.isoformat()}",
            )
        return OpsCheck(
            name="Certificat pro",
            status="ok",
            detail=f"Valide jusqu'au {expiry.isoformat()}",
        )

    @staticmethod
    def _recommend(
        issues: list[OpsIssue],
        checks: list[OpsCheck],
        legal_name: str,
    ) -> tuple[str, str]:
        """Pick the proposed_decision + build the French human-readable reason.

        Priority:
          1. Any blocker issue → REJECT.
          2. Any missing issue → REQUEST_INFO.
          3. Otherwise → APPROVE.

        The reason string is built from the checks (positive + negative)
        so the admin can scan it in one read.
        """
        blockers = [i for i in issues if i.severity == "blocker"]
        missing = [i for i in issues if i.severity == "missing"]
        warnings = [i for i in issues if i.severity == "warning"]

        if blockers:
            parts = [f"Rejet recommandé pour le dossier « {legal_name} » :"]
            for b in blockers:
                parts.append(f"  • {b.message}")
            if missing:
                parts.append("  Pièces également manquantes : "
                             + ", ".join(m.message for m in missing) + ".")
            if warnings:
                parts.append("  Avertissements : "
                             + "; ".join(w.message for w in warnings) + ".")
            parts.append(
                "Action requise : notifier le producteur et clôturer le dossier "
                "en rejet, sauf régularisation sous délai négocié."
            )
            return "reject", "\n".join(parts)

        if missing:
            parts = [f"Information complémentaire requise pour « {legal_name} » :"]
            for m in missing:
                parts.append(f"  • {m.message}")
            if warnings:
                parts.append("  Avertissements : "
                             + "; ".join(w.message for w in warnings) + ".")
            parts.append(
                "Action requise : demander les pièces manquantes au producteur "
                "puis relancer l'analyse."
            )
            return "request_info", "\n".join(parts)

        # Clean dossier → APPROVE.
        positives = [c for c in checks if c.status == "ok"]
        parts = [f"Dossier à valider : « {legal_name} »."]
        for c in positives:
            parts.append(f"  • {c.name} : {c.detail}.")
        if warnings:
            parts.append("Avertissements (non bloquants) : "
                         + "; ".join(w.message for w in warnings) + ".")
        parts.append(
            "Recommandation : approbation par l'administrateur Ops possible "
            "sans complément."
        )
        return "approve", "\n".join(parts)
