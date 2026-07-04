"use client";

import * as React from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import type { ChatMessage, TraceStatus } from "@/lib/types";
import {
  AlertTriangle,
  BookOpen,
  Check,
  Clock,
  Cpu,
  Database,
  Eye,
  FileText,
  Shield,
  ShieldOff,
  X,
} from "@/components/ui/feather-icons";

import { SqlBlock } from "./sql-block";
import { ForecastDisplay } from "./forecast-display";

interface InspectorProps {
  message: ChatMessage | null;
  onClose: () => void;
}

export function Inspector({ message, onClose }: InspectorProps) {
  if (!message || message.role !== "assistant" || !message.response) {
    return <EmptyInspector onClose={onClose} />;
  }

  const r = message.response;
  const totalTokens = r.tokensIn + r.tokensOut;
  // Toy cost estimate: €0.000018 per token (blend of input/output pricing).
  const costEur = (totalTokens * 0.000018)
    .toFixed(4)
    .replace(".", ",");
  const totalMs = r.steps.reduce((acc, s) => acc + s.durationMs, 0);
  const tokensInDisplay = r.tokensIn.toLocaleString("fr-FR").replace(/\s/g, "\u00A0");
  const tokensOutDisplay = r.tokensOut.toLocaleString("fr-FR").replace(/\s/g, "\u00A0");
  const totalTokensDisplay = totalTokens.toLocaleString("fr-FR").replace(/\s/g, "\u00A0");
  const latencyDisplay = `${(totalMs / 1000).toFixed(2).replace(".", ",")} s`;
  const totalMsDisplay = `${totalMs} ms`;

  // RAG mode = documentary response with cited sources. Distinguished from
  // analytical (SQL) responses so the inspector reads as a distinct trace.
  const isRag = !!r.sources && r.sources.length > 0;
  // Forecast mode = ML stock-shortage prediction via `forecast_tool`
  // (Phase 5). Distinct from both analytical (SQL) and documentary (RAG):
  // the trace shows feature engineering / prédiction ML / classement steps,
  // a "PRÉDICTIONS ML" block replaces the SQL block, and the security checks
  // include "Modèle ML valide" + "Features disponibles".
  const isForecast =
    r.toolCalls.includes("forecast_tool") &&
    !!r.forecastPredictions &&
    r.forecastPredictions.length > 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
          Trace de l&apos;agent
        </h3>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label="Fermer l'inspecteur"
        >
          <X size={16} />
        </button>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-6 p-4">
          {/* Status summary */}
          <section>
            <SectionLabel icon={<Cpu size={12} />}>Statut</SectionLabel>
            {r.refused ? (
              <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                <ShieldOff size={14} className="shrink-0" />
                <span className="font-body">
                  Action refusée — scoping violation
                </span>
              </div>
            ) : isRag ? (
              <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-xs">
                <FileText size={14} className="shrink-0 text-accent" />
                <span className="font-body text-foreground">
                  Réponse documentaire ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {r.sources?.length ?? 0}
                  </span>{" "}
                  source{(r.sources?.length ?? 0) > 1 ? "s" : ""} citée
                  {(r.sources?.length ?? 0) > 1 ? "s" : ""} ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {totalMs}
                  </span>{" "}
                  ms ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {totalTokensDisplay}
                  </span>{" "}
                  tokens
                </span>
              </div>
            ) : isForecast ? (
              <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-xs">
                <Cpu size={14} className="shrink-0 text-accent" />
                <span className="font-body text-foreground">
                  Prédiction ML ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {r.forecastPredictions?.length ?? 0}
                  </span>{" "}
                  produit{(r.forecastPredictions?.length ?? 0) > 1 ? "s" : ""} à
                  risque ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {totalMs}
                  </span>{" "}
                  ms ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {totalTokensDisplay}
                  </span>{" "}
                  tokens
                </span>
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-xs">
                <Check size={14} className="shrink-0 text-accent" />
                <span className="font-body text-foreground">
                  Réponse générée ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {totalMs}
                  </span>{" "}
                  ms ·{" "}
                  <span className="font-heading text-foreground tabular-nums">
                    {totalTokensDisplay}
                  </span>{" "}
                  tokens
                </span>
              </div>
            )}
          </section>

          {/* Steps — ledger-numbered */}
          <section>
            <SectionLabel icon={<Eye size={12} />}>
              Étapes du raisonnement
            </SectionLabel>
            <ol className="relative mt-2 space-y-2">
              {r.steps.map((step, idx) => {
                const num = String(idx + 1).padStart(2, "0");
                const isLast = idx === r.steps.length - 1;
                return (
                  <li
                    key={step.index}
                    className="relative flex gap-3 rounded-md border border-border bg-background p-2.5"
                  >
                    {/* Step number + connector */}
                    <div className="flex flex-col items-center">
                      <span className="font-heading text-sm text-accent tabular-nums">
                        {num}
                      </span>
                      {!isLast && (
                        <span className="mt-1 w-px flex-1 bg-border" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1 pb-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-sm font-medium text-foreground">
                          {step.title}
                        </span>
                        <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">
                          <span className="font-heading tabular-nums">
                            {step.durationMs > 0 ? step.durationMs : "—"}
                          </span>
                          {step.durationMs > 0 ? " ms" : ""}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">
                        {step.detail}
                      </p>
                    </div>
                    <StatusIcon status={step.status} />
                  </li>
                );
              })}
            </ol>
          </section>

          {/* SQL (analytical responses only — never co-renders with forecast
              since the forecast_tool returns sql: null) */}
          {r.sql && !isRag && !isForecast && (
            <section>
              <SectionLabel icon={<Database size={12} />}>
                SQL exécuté
              </SectionLabel>
              <div className="mt-2">
                <SqlBlock
                  sql={r.sql}
                  scopeClause={r.scopeClause}
                  refused={r.refused}
                  defaultOpen
                />
              </div>
            </section>
          )}

          {/* PRÉDICTIONS ML (forecast_tool responses only — Phase 5). Same
              block as in the chat message: probability bars per product,
              model card footer. Rendered with the `compact` variant so it
              fits the inspector's narrower column without duplicating the
              section header. */}
          {isForecast && r.forecastPredictions && r.forecastPredictions.length > 0 && (
            <section>
              <SectionLabel icon={<Cpu size={12} />}>
                Prédictions ML
              </SectionLabel>
              <div className="mt-2">
                <ForecastDisplay
                  predictions={r.forecastPredictions}
                  compact
                />
              </div>
              <p className="mt-2 text-[10px] text-muted-foreground">
                Modèle RandomForest · 100 arbres · entraîné sur 90 jours
                d&apos;historique
              </p>
            </section>
          )}

          {/* Documents retrouvés (RAG responses only) */}
          {isRag && r.sources && r.sources.length > 0 && (
            <section>
              <SectionLabel icon={<BookOpen size={12} />}>
                Documents retrouvés
              </SectionLabel>
              <ul className="mt-2 space-y-1.5">
                {r.sources.map((s, i) => (
                  <li
                    key={`${s.documentId}-${s.chunkIndex}-${i}`}
                    className="flex items-start gap-2 rounded-md border border-border bg-background p-2.5"
                  >
                    <FileText size={14} className="mt-0.5 shrink-0 text-accent" />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-medium text-foreground">
                        {s.title}
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        chunk{" "}
                        <span className="font-heading tabular-nums">
                          {s.chunkIndex}
                        </span>{" "}
                        · document_id{" "}
                        <span className="font-heading tabular-nums">
                          {s.documentId}
                        </span>
                      </div>
                    </div>
                    {typeof s.score === "number" && (
                      <div className="shrink-0 text-right">
                        <div className="font-heading text-sm tabular-nums text-foreground">
                          {(s.score * 100).toFixed(0)}%
                        </div>
                        <div className="text-[9px] uppercase tracking-wide text-muted-foreground">
                          score
                        </div>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Security checks */}
          <section>
            <SectionLabel icon={<Shield size={12} />}>Sécurité</SectionLabel>
            <ul className="mt-2 space-y-1.5">
              {r.securityChecks.map((c, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 rounded-md border border-border bg-background p-2.5"
                >
                  <StatusIcon status={c.status} />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-foreground">
                      {c.label}
                    </div>
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

          {/* Cost & tokens — ledger grid */}
          <section>
            <SectionLabel icon={<Clock size={12} />}>
              Coût &amp; tokens
            </SectionLabel>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Stat label="Tokens entrée" value={tokensInDisplay} />
              <Stat label="Tokens sortie" value={tokensOutDisplay} />
              <Stat label="Total" value={totalTokensDisplay} />
              <Stat label="Latence" value={latencyDisplay} />
              <Stat label="Coût estimé" value={`${costEur} €`} />
              <Stat label="Durée brute" value={totalMsDisplay} />
            </div>
          </section>

          <Separator />

          <p className="text-[10px] leading-relaxed text-muted-foreground">
            Trace simulée — en production, journalisée dans Langfuse.
          </p>
        </div>
      </ScrollArea>
    </div>
  );
}

function EmptyInspector({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
          Trace de l&apos;agent
        </h3>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label="Fermer l'inspecteur"
        >
          <X size={16} />
        </button>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="flex size-12 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
          <Eye size={20} />
        </div>
        <div>
          <p className="text-sm font-medium text-foreground">
            Sélectionnez un message pour voir la trace
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Cliquez sur une réponse de l&apos;agent pour inspecter le SQL
            exécuté, les vérifications de sécurité et le détail du raisonnement.
          </p>
        </div>
      </div>
    </div>
  );
}

function SectionLabel({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
      <span className="text-muted-foreground">{icon}</span>
      {children}
    </div>
  );
}

function StatusIcon({ status }: { status: TraceStatus }) {
  if (status === "ok") {
    return (
      <Check size={14} className="mt-0.5 shrink-0 text-accent" />
    );
  }
  if (status === "warning") {
    return (
      <AlertTriangle
        size={14}
        className="mt-0.5 shrink-0 text-muted-foreground"
      />
    );
  }
  return (
    <ShieldOff
      size={14}
      className="mt-0.5 shrink-0 text-muted-foreground"
    />
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-border bg-background p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-heading text-base text-foreground tabular-nums">
        {value}
      </div>
    </div>
  );
}
