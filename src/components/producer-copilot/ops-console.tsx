"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import type {
  ApprovalCheck,
  ApprovalIssue,
  ApprovalSummary,
  OnboardingDossier,
  ProposedDecision,
} from "@/lib/types";
import type { ApprovalDecision } from "@/lib/api";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle,
  Clock,
  FileText,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  XCircle,
} from "@/components/ui/feather-icons";

// ---------------------------------------------------------------------------
// Ops Console — human-in-the-loop approval queue (Phase 4)
// ---------------------------------------------------------------------------
//
// 2-zone layout (list left, detail right) shown only when the admin switches
// to the "ops" view. Replaces the chat thread in the main content area — the
// sidebar + footer + header stay the same.
//
// On mobile the layout stacks: list on top (in a Sheet-style panel), detail
// below. We don't bother with a Sheet here — a simple responsive flex stack
// is enough since the inspector-style sheet pattern is already used for the
// chat inspector.

export function OpsConsole() {
  const approvals = useCopilotStore((s) => s.approvals);
  const loading = useCopilotStore((s) => s.approvalsLoading);
  const loadApprovals = useCopilotStore((s) => s.loadApprovals);
  const selectedApprovalId = useCopilotStore((s) => s.selectedApprovalId);
  const selectApproval = useCopilotStore((s) => s.selectApproval);
  const detail = useCopilotStore((s) => s.selectedApprovalDetail);
  const decisionInFlight = useCopilotStore((s) => s.decisionInFlight);

  // Defensive: producers should never mount this component, but if they do
  // (e.g. via a stale Zustand state), we kick off the load anyway and let
  // `loadApprovals`'s admin guard return an empty list.
  React.useEffect(() => {
    void loadApprovals();
  }, [loadApprovals]);

  // Sort: pending first (most-recent first), then decided (most-recent first).
  const sorted = React.useMemo(() => {
    const pending = approvals
      .filter((a) => a.status === "pending")
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    const decided = approvals
      .filter((a) => a.status !== "pending")
      .sort((a, b) => (b.decided_at ?? b.created_at).localeCompare(a.decided_at ?? a.created_at));
    return [...pending, ...decided];
  }, [approvals]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Top bar — title + manual refresh + counters */}
      <div className="flex items-center gap-3 border-b border-border bg-background px-3 py-2.5 sm:px-4">
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-md border border-border bg-secondary text-accent">
            <ShieldCheck size={14} />
          </span>
          <div>
            <h2 className="font-heading text-sm leading-tight text-foreground">
              Ops Console
            </h2>
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              File d&apos;approbation · Human-in-the-loop
            </p>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <CountPill
            label="En attente"
            value={approvals.filter((a) => a.status === "pending").length}
            tone="accent"
          />
          <CountPill
            label="Décidés"
            value={approvals.filter((a) => a.status !== "pending").length}
            tone="muted"
          />
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => void loadApprovals()}
            disabled={loading}
            aria-label="Rafraîchir"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </Button>
        </div>
      </div>

      {/* Body — list (left) + detail (right) */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* List */}
        <div className="flex max-h-[42vh] shrink-0 flex-col border-b border-border md:max-h-none md:w-[340px] md:border-b-0 md:border-r md:min-h-0">
          <ScrollArea className="flex-1">
            <div className="space-y-1.5 p-2.5">
              {loading && approvals.length === 0 ? (
                <ListSkeleton />
              ) : sorted.length === 0 ? (
                <EmptyList />
              ) : (
                sorted.map((a) => (
                  <ApprovalRow
                    key={a.id}
                    approval={a}
                    active={a.id === selectedApprovalId}
                    onClick={() => void selectApproval(a.id)}
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Detail */}
        <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
          {detail ? (
            <ApprovalDetailPanel
              detail={detail}
              deciding={decisionInFlight}
            />
          ) : selectedApprovalId !== null ? (
            <DetailSkeleton />
          ) : (
            <EmptyDetail />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Counters + skeletons + empty states
// ---------------------------------------------------------------------------

function CountPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "accent" | "muted";
}) {
  return (
    <span className="hidden items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-[11px] uppercase tracking-wide sm:inline-flex">
      <span
        className={cn(
          "font-heading tabular-nums",
          tone === "accent" ? "text-accent" : "text-muted-foreground",
        )}
      >
        {value}
      </span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-1.5">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="rounded-md border border-border bg-background p-3"
        >
          <div className="h-3 w-2/3 animate-pulse rounded-sm bg-muted" />
          <div className="mt-2 h-2 w-1/2 animate-pulse rounded-sm bg-muted/60" />
        </div>
      ))}
    </div>
  );
}

function EmptyList() {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border bg-background px-4 py-10 text-center">
      <CheckCircle size={22} className="text-accent" />
      <p className="text-sm font-medium text-foreground">File vide</p>
      <p className="max-w-[240px] text-xs text-muted-foreground">
        Aucun dossier d&apos;onboarding en attente d&apos;approbation. Les
        nouvelles soumissions apparaîtront ici automatiquement.
      </p>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-3 p-4">
      <div className="h-5 w-1/3 animate-pulse rounded-sm bg-muted" />
      <div className="h-3 w-1/4 animate-pulse rounded-sm bg-muted/60" />
      <div className="h-24 w-full animate-pulse rounded-md bg-muted/40" />
      <div className="h-24 w-full animate-pulse rounded-md bg-muted/40" />
    </div>
  );
}

function EmptyDetail() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <div className="flex size-12 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
        <FileText size={20} />
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">
          Sélectionnez un dossier dans la liste.
        </p>
        <p className="mt-1 max-w-md text-xs text-muted-foreground">
          Chaque ligne affiche la pré-analyse de l&apos;agent (décision proposée,
          confiance, problèmes détectés). Cliquez pour voir le détail complet
          et enregistrer votre décision.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// List rows
// ---------------------------------------------------------------------------

function ApprovalRow({
  approval,
  active,
  onClick,
}: {
  approval: ApprovalSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active}
      className={cn(
        "group w-full rounded-md border bg-background p-2.5 text-left transition-colors",
        active
          ? "border-accent/60 ring-1 ring-accent/30"
          : "border-border hover:border-accent/40 hover:bg-secondary/30",
        approval.status === "pending" && !active && "border-l-2 border-l-accent/70",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-heading text-sm text-foreground">
            {approval.legal_name}
          </div>
          <div className="mt-0.5 font-heading text-[11px] tabular-nums text-muted-foreground">
            SIRET {formatSiret(approval.siret)}
          </div>
        </div>
        <ConfidencePct value={approval.confidence} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <ProposedDecisionBadge decision={approval.proposed_decision} />
        <StatusBadge status={approval.status} />
      </div>

      {approval.agent_analysis.issues.length > 0 && (
        <div className="mt-1.5 flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          <AlertCircle size={10} className="text-muted-foreground" />
          <span>
            {approval.agent_analysis.issues.length} problème
            {approval.agent_analysis.issues.length > 1 ? "s" : ""}
          </span>
        </div>
      )}
    </button>
  );
}

function ConfidencePct({ value }: { value: number }) {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <span className="shrink-0 text-right">
      <span
        className={cn(
          "font-heading text-sm tabular-nums",
          pct >= 80 ? "text-accent" : "text-foreground",
        )}
      >
        {pct}
      </span>
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        %
      </span>
    </span>
  );
}

function ProposedDecisionBadge({
  decision,
}: {
  decision: ProposedDecision;
}) {
  if (decision === "approve") {
    return (
      <Badge
        variant="outline"
        className="gap-1 border-accent/40 bg-accent/10 text-[10px] uppercase tracking-wide text-accent"
      >
        <CheckCircle size={10} />
        Approuver
      </Badge>
    );
  }
  if (decision === "request_info") {
    return (
      <Badge
        variant="outline"
        className="gap-1 border-border bg-secondary text-[10px] uppercase tracking-wide text-muted-foreground"
      >
        <AlertCircle size={10} />
        Info requise
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="gap-1 border-dashed border-border bg-background text-[10px] uppercase tracking-wide text-muted-foreground"
    >
      <XCircle size={10} />
      Rejeter
    </Badge>
  );
}

function StatusBadge({ status }: { status: ApprovalSummary["status"] }) {
  switch (status) {
    case "pending":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-border bg-background text-[10px] uppercase tracking-wide text-muted-foreground"
        >
          <Clock size={10} />
          En attente
        </Badge>
      );
    case "approved":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-accent/40 bg-accent/10 text-[10px] uppercase tracking-wide text-accent"
        >
          <CheckCircle size={10} />
          Approuvé
        </Badge>
      );
    case "rejected":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-dashed border-border bg-background text-[10px] uppercase tracking-wide text-muted-foreground"
        >
          <XCircle size={10} />
          Rejeté
        </Badge>
      );
    case "overridden":
      return (
        <Badge
          variant="outline"
          className="gap-1 border-border bg-secondary text-[10px] uppercase tracking-wide text-foreground"
        >
          <AlertTriangle size={10} className="text-foreground" />
          Outrepassé
        </Badge>
      );
  }
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function ApprovalDetailPanel({
  detail,
  deciding,
}: {
  detail: NonNullable<ReturnType<typeof useCopilotStore.getState>["selectedApprovalDetail"]>;
  deciding: boolean;
}) {
  const { approval, onboarding } = detail;
  return (
    <ScrollArea className="h-full">
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18 }}
        className="mx-auto max-w-3xl space-y-5 p-4"
      >
        <DetailHeader approval={approval} onboarding={onboarding} />
        <AgentAnalysisSection approval={approval} />
        <ChecksSection checks={approval.agent_analysis.checks} />
        <IssuesSection issues={approval.agent_analysis.issues} />
        <DossierSection onboarding={onboarding} />
        {approval.status === "pending" ? (
          <DecisionSection approvalId={approval.id} deciding={deciding} />
        ) : (
          <DecisionHistory approval={approval} />
        )}
      </motion.div>
    </ScrollArea>
  );
}

function DetailHeader({
  approval,
  onboarding,
}: {
  approval: ApprovalSummary;
  onboarding: OnboardingDossier;
}) {
  return (
    <div className="rounded-md border border-border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="font-heading text-xl text-foreground">
            {approval.legal_name}
          </h2>
          <p className="mt-1 font-heading text-xs tabular-nums text-muted-foreground">
            SIRET {formatSiret(approval.siret)}
            {onboarding.siret_valid ? (
              <span className="ml-2 inline-flex items-center gap-1 text-accent">
                <Check size={11} /> valide
              </span>
            ) : (
              <span className="ml-2 inline-flex items-center gap-1 text-muted-foreground">
                <XCircle size={11} /> invalide
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <ProposedDecisionBadge decision={approval.proposed_decision} />
          <StatusBadge status={approval.status} />
        </div>
      </div>

      <Separator className="my-3" />

      <div className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
        <Meta label="Soumis le" value={formatDate(onboarding.submitted_at)} />
        <Meta label="Email" value={onboarding.email || "—"} />
        <Meta label="Téléphone" value={onboarding.phone || "—"} />
        <Meta
          label="Certificat"
          value={
            onboarding.professional_certificate_present
              ? onboarding.professional_certificate_expiry
                ? `Exp. ${formatDate(onboarding.professional_certificate_expiry)}`
                : "Présent"
              : "Manquant"
          }
        />
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 truncate font-body text-xs text-foreground">
        {value}
      </div>
    </div>
  );
}

function AgentAnalysisSection({ approval }: { approval: ApprovalSummary }) {
  const analysis = approval.agent_analysis;
  const pct = Math.round(analysis.confidence * 100);
  return (
    <section className="rounded-md border border-border bg-background p-4">
      <SectionLabel icon={<ShieldCheck size={12} />}>
        Analyse de l&apos;agent
      </SectionLabel>

      <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-md border border-border bg-secondary/30 p-2.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Décision proposée
          </div>
          <div className="mt-1.5">
            <ProposedDecisionBadge decision={analysis.proposed_decision} />
          </div>
        </div>
        <div className="rounded-md border border-border bg-secondary/30 p-2.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Confiance
          </div>
          <div className="mt-1">
            <span
              className={cn(
                "font-heading text-2xl tabular-nums",
                pct >= 80 ? "text-accent" : "text-foreground",
              )}
            >
              {pct}
            </span>
            <span className="text-xs text-muted-foreground">%</span>
          </div>
        </div>
        <div className="rounded-md border border-border bg-secondary/30 p-2.5 sm:col-span-1 col-span-2">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Demandé le
          </div>
          <div className="mt-1 font-heading text-sm tabular-nums text-foreground">
            {formatDate(approval.created_at)}
          </div>
        </div>
      </div>

      {analysis.proposed_reason && (
        <div className="mt-3 rounded-md border border-border bg-muted/30 px-3 py-2.5">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            Justification de l&apos;agent
          </div>
          <p className="whitespace-pre-wrap font-body text-xs leading-relaxed text-foreground">
            {analysis.proposed_reason}
          </p>
        </div>
      )}
    </section>
  );
}

function ChecksSection({ checks }: { checks: ApprovalCheck[] }) {
  if (checks.length === 0) return null;
  return (
    <section className="rounded-md border border-border bg-background p-4">
      <SectionLabel icon={<Check size={12} />}>Vérifications</SectionLabel>
      <ul className="mt-2 space-y-1.5">
        {checks.map((c, i) => (
          <li
            key={`${c.name}-${i}`}
            className="flex items-start gap-2 rounded-md border border-border bg-background px-2.5 py-2"
          >
            <CheckStatusIcon status={c.status} />
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium text-foreground">{c.name}</div>
              {c.detail && (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {c.detail}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CheckStatusIcon({ status }: { status: ApprovalCheck["status"] }) {
  if (status === "ok") {
    return <Check size={14} className="mt-0.5 shrink-0 text-accent" />;
  }
  if (status === "warning") {
    return (
      <AlertTriangle
        size={14}
        className="mt-0.5 shrink-0 text-muted-foreground"
      />
    );
  }
  return <ShieldOff size={14} className="mt-0.5 shrink-0 text-muted-foreground" />;
}

function IssuesSection({ issues }: { issues: ApprovalIssue[] }) {
  if (issues.length === 0) {
    return (
      <section className="rounded-md border border-border bg-background p-4">
        <SectionLabel icon={<CheckCircle size={12} />}>
          Problèmes détectés
        </SectionLabel>
        <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
          <CheckCircle size={13} className="text-accent" />
          Aucun problème détecté par l&apos;agent.
        </div>
      </section>
    );
  }
  return (
    <section className="rounded-md border border-border bg-background p-4">
      <SectionLabel icon={<AlertCircle size={12} />}>
        Problèmes détectés
      </SectionLabel>
      <ul className="mt-2 space-y-1.5">
        {issues.map((iss, i) => (
          <li
            key={`${iss.code}-${i}`}
            className={cn(
              "flex items-start gap-2 rounded-md border bg-background px-2.5 py-2",
              iss.severity === "critical"
                ? "border-dashed border-border"
                : iss.severity === "warning"
                  ? "border-accent/40 bg-accent/5"
                  : "border-border bg-muted/30",
            )}
          >
            <SeverityIcon severity={iss.severity} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-heading text-[10px] uppercase tracking-wide text-muted-foreground tabular-nums">
                  {iss.code}
                </span>
                <SeverityTag severity={iss.severity} />
              </div>
              <p className="mt-0.5 text-xs leading-relaxed text-foreground">
                {iss.message}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SeverityIcon({
  severity,
}: {
  severity: ApprovalIssue["severity"];
}) {
  if (severity === "critical") {
    return <ShieldOff size={14} className="mt-0.5 shrink-0 text-foreground" />;
  }
  if (severity === "warning") {
    return (
      <AlertTriangle
        size={14}
        className="mt-0.5 shrink-0 text-accent"
      />
    );
  }
  return <AlertCircle size={14} className="mt-0.5 shrink-0 text-muted-foreground" />;
}

function SeverityTag({ severity }: { severity: ApprovalIssue["severity"] }) {
  const label =
    severity === "critical" ? "Critique" : severity === "warning" ? "Avertissement" : "Info";
  const cls =
    severity === "critical"
      ? "border-dashed border-border text-muted-foreground"
      : severity === "warning"
        ? "border-accent/40 bg-accent/10 text-accent"
        : "border-border bg-secondary text-muted-foreground";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border px-1 text-[9px] uppercase tracking-wide",
        cls,
      )}
    >
      {label}
    </span>
  );
}

function DossierSection({ onboarding }: { onboarding: OnboardingDossier }) {
  return (
    <section className="rounded-md border border-border bg-background p-4">
      <SectionLabel icon={<FileText size={12} />}>
        Dossier d&apos;onboarding
      </SectionLabel>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <DossierField
          label="Adresse déclarée"
          value={onboarding.declared_address || "—"}
        />
        <DossierField
          label="Adresse document"
          value={onboarding.document_address || "—"}
        />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <DocFlag label="RIB" present={onboarding.rib_document_present} />
        <DocFlag label="Identité" present={onboarding.id_document_present} />
        <DocFlag
          label="Certificat"
          present={onboarding.professional_certificate_present}
        />
        <DocFlag label="SIRET" present={onboarding.siret_valid} />
      </div>
    </section>
  );
}

function DossierField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-secondary/30 p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-body text-xs text-foreground">{value}</div>
    </div>
  );
}

function DocFlag({ label, present }: { label: string; present: boolean }) {
  return (
    <div
      className={cn(
        "rounded-md border px-2 py-1.5 text-center",
        present
          ? "border-accent/40 bg-accent/10"
          : "border-dashed border-border bg-background",
      )}
    >
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-0.5 flex items-center justify-center gap-1 text-[11px] font-medium",
          present ? "text-accent" : "text-muted-foreground",
        )}
      >
        {present ? <Check size={11} /> : <XCircle size={11} />}
        {present ? "Présent" : "Manquant"}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decision (HITL) section
// ---------------------------------------------------------------------------

function DecisionSection({
  approvalId,
  deciding,
}: {
  approvalId: number;
  deciding: boolean;
}) {
  const decide = useCopilotStore((s) => s.decide);
  const [reason, setReason] = React.useState("");
  const trimmed = reason.trim();

  const submit = (decision: ApprovalDecision) => {
    if (deciding) return;
    // Reason is required for override, optional but encouraged otherwise.
    // We default to a minimal placeholder so the backend always gets a
    // non-empty string (its contract says `reason: str`).
    const finalReason =
      trimmed.length > 0
        ? trimmed
        : decision === "approve"
          ? "Approbation confirmée par l'admin"
          : decision === "reject"
            ? "Rejet confirmé par l'admin"
            : "Outrepassé par l'admin";
    void decide(approvalId, decision, finalReason);
    setReason("");
  };

  return (
    <section className="rounded-md border border-accent/40 bg-accent/5 p-4">
      <SectionLabel icon={<ShieldCheck size={12} />}>
        Décision humaine
      </SectionLabel>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
        Vous êtes le seul à pouvoir valider ou invalider la recommandation de
        l&apos;agent. Votre décision, votre identité et l&apos;horodatage sont
        journalisés.
      </p>

      <div className="mt-3">
        <label
          htmlFor="decision-reason"
          className="text-[10px] font-body uppercase tracking-wide text-muted-foreground"
        >
          Motif {trimmed.length === 0 && "(optionnel, sauf pour outrepasser)"}
        </label>
        <Textarea
          id="decision-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Précisez le motif de votre décision…"
          rows={3}
          disabled={deciding}
          className="mt-1 resize-none bg-background text-xs"
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => submit("approve")}
          disabled={deciding}
          className="gap-1.5"
        >
          <CheckCircle size={14} />
          Approuver
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => submit("reject")}
          disabled={deciding}
          className="gap-1.5 border border-dashed border-border text-muted-foreground hover:text-foreground"
        >
          <XCircle size={14} />
          Rejeter
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => submit("override")}
          disabled={deciding}
          title="Outrepasser = invalider la recommandation de l'agent"
          className="gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <AlertTriangle size={14} />
          Outrepasser
        </Button>
        <span className="self-center text-[10px] uppercase tracking-wide text-muted-foreground">
          Outrepasser = invalider la recommandation de l&apos;agent
        </span>
      </div>
    </section>
  );
}

function DecisionHistory({ approval }: { approval: ApprovalSummary }) {
  const decidedAt = approval.decided_at
    ? formatDate(approval.decided_at)
    : "—";
  const actor = approval.decided_by ?? "admin";
  const verb =
    approval.final_decision === "approve"
      ? "Approuvé"
      : approval.final_decision === "reject"
        ? "Rejeté"
        : approval.final_decision === "override"
          ? "Outrepassé"
          : "Décidé";

  return (
    <section className="rounded-md border border-border bg-muted/30 p-4">
      <SectionLabel icon={<Clock size={12} />}>
        Décision enregistrée
      </SectionLabel>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Meta label="Action" value={verb} />
        <Meta label="Décidé par" value={actor} />
        <Meta label="Horodatage" value={decidedAt} />
      </div>
      {approval.human_reason && (
        <div className="mt-2 rounded-md border border-border bg-background px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Motif humain
          </div>
          <p className="mt-0.5 whitespace-pre-wrap font-body text-xs text-foreground">
            {approval.human_reason}
          </p>
        </div>
      )}
      {approval.onboarding_id && approval.status === "rejected" && (
        <p className="mt-2 text-[10px] uppercase tracking-wide text-muted-foreground">
          Le dossier d&apos;onboarding a été marqué comme rejeté côté
          backend — le producteur a été notifié.
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function SectionLabel({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
      <span className="text-muted-foreground">{icon}</span>
      {children}
    </div>
  );
}

function formatSiret(siret: string): string {
  // SIRET is 14 digits — group as 3 3 3 5 for legibility (Caudex, tabular).
  if (!siret) return "—";
  const digits = siret.replace(/\D/g, "");
  if (digits.length !== 14) return siret;
  return `${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(
    6,
    9,
  )} ${digits.slice(9)}`;
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("fr-FR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
