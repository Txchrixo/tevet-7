"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";
import type { ForecastPrediction } from "@/lib/types";
import { Cpu } from "@/components/ui/feather-icons";

interface ForecastDisplayProps {
  predictions: ForecastPrediction[];
  /**
   * Compact variant — used inside the inspector's narrower column. Hides
   * the section header + footer (the inspector provides its own labels
   * around the block) and tightens the vertical rhythm.
   */
  compact?: boolean;
}

// ---------------------------------------------------------------------------
// Visual tiers — the bar fill + % text color track three probability bands.
// Stays strictly inside the Tevet-7 palette (accent / muted-foreground),
// never falls back to indigo/blue or Tailwind default color scales.
// ---------------------------------------------------------------------------

type RiskBand = "low" | "mid" | "high";

function bandFor(probability: number): RiskBand {
  if (probability > 0.75) return "high";
  if (probability >= 0.5) return "mid";
  return "low";
}

const BAR_FILL: Record<RiskBand, string> = {
  // <50 % — muted neutral so the row reads "informational, not urgent".
  low: "bg-muted-foreground/55",
  // 50–75 % — solid accent.
  mid: "bg-accent",
  // >75 % — accent + a 1px ring so the high-risk rows visually pop without
  // leaving the palette (no orange/red, no Tailwind scale).
  high: "bg-accent ring-1 ring-accent/60",
};

const PCT_TEXT: Record<RiskBand, string> = {
  low: "text-muted-foreground",
  mid: "text-foreground",
  high: "text-accent",
};

const ROW_BORDER: Record<RiskBand, string> = {
  low: "border-border",
  mid: "border-border",
  high: "border-accent/40",
};

/**
 * Renders the ML stock-shortage predictions returned by the `forecast_tool`
 * (Phase 5). Distinct from the SQL block: instead of "SQL exécuté" the user
 * sees "PRÉDICTIONS ML" with a horizontal probability bar per product.
 *
 * Sorted by probability descending so the highest-risk product sits at the
 * top. The footer carries the model card so the producer can see WHAT made
 * the prediction (RandomForest, 100 arbres, 90 jours d'historique).
 */
export function ForecastDisplay({
  predictions,
  compact = false,
}: ForecastDisplayProps) {
  // Defensive copy before sorting — never mutate the prop in place (the
  // inspector + chat-message share the same array reference).
  const sorted = React.useMemo(
    () =>
      [...predictions].sort((a, b) => b.probability - a.probability),
    [predictions],
  );

  if (sorted.length === 0) return null;

  return (
    <div
      className={cn(
        "rounded-md border border-border bg-background",
        compact ? "p-3" : "p-4",
      )}
    >
      {!compact && (
        <div className="mb-3 flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
          <Cpu size={12} className="text-accent" />
          Prédictions ML
        </div>
      )}

      <ul className={cn(compact ? "space-y-2" : "space-y-3")}>
        {sorted.map((p, i) => {
          const band = bandFor(p.probability);
          const pct = Math.round(p.probability * 100);
          const pctLabel = String(pct).replace(
            /\s/g,
            "\u00A0",
          );
          return (
            <li
              key={`${p.product_name}-${i}`}
              className={cn(
                "rounded-md border bg-secondary/20 px-3 py-2.5",
                ROW_BORDER[band],
              )}
            >
              {/* Row 1 — product name (Caudex) + % (Caudex, accent if >75 %) */}
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 flex-1 truncate font-heading text-sm text-foreground">
                  {p.product_name}
                </span>
                <span
                  className={cn(
                    "shrink-0 font-heading text-base tabular-nums",
                    PCT_TEXT[band],
                  )}
                >
                  {pctLabel}
                  <span className="text-xs">%</span>
                </span>
              </div>

              {/* Row 2 — probability bar (animated width on mount) */}
              <div
                className="mt-2 h-2 w-full overflow-hidden rounded-md bg-muted/40"
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Probabilité de rupture — ${p.product_name}`}
              >
                <motion.div
                  className={cn("h-full rounded-md", BAR_FILL[band])}
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.55, ease: "easeOut", delay: i * 0.05 }}
                />
              </div>

              {/* Row 3 — feature context (Manrope caption muted) */}
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <span className="uppercase tracking-wide">Stock</span>
                  <span className="font-heading tabular-nums text-foreground">
                    {p.stock_available.toLocaleString("fr-FR").replace(/\s/g, "\u00A0")}
                  </span>
                </span>
                <span className="text-muted-foreground/40">·</span>
                <span className="inline-flex items-center gap-1">
                  <span className="uppercase tracking-wide">Ventes 7j</span>
                  <span className="font-heading tabular-nums text-foreground">
                    {p.sales_7d.toLocaleString("fr-FR").replace(/\s/g, "\u00A0")}
                  </span>
                </span>
                <span className="text-muted-foreground/40">·</span>
                <span className="inline-flex items-center gap-1">
                  <span className="uppercase tracking-wide">Facteur</span>
                  <span className="text-foreground/90">{p.top_factor}</span>
                </span>
              </div>
            </li>
          );
        })}
      </ul>

      {!compact && (
        <p className="mt-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
          Modèle RandomForest · 100 arbres · entraîné sur 90 jours
          d&apos;historique
        </p>
      )}
    </div>
  );
}
