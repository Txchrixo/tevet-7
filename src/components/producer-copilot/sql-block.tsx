"use client";

import * as React from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDown, Database, Shield } from "@/components/ui/feather-icons";

// SQL keywords we colour distinctly inside the code block.
const SQL_KEYWORDS = new Set([
  "SELECT",
  "FROM",
  "WHERE",
  "JOIN",
  "LEFT",
  "RIGHT",
  "INNER",
  "OUTER",
  "ON",
  "GROUP",
  "BY",
  "ORDER",
  "HAVING",
  "LIMIT",
  "AND",
  "OR",
  "IN",
  "NOT",
  "AS",
  "DESC",
  "ASC",
  "COUNT",
  "SUM",
  "COALESCE",
  "DISTINCT",
  "DATE_TRUNC",
  "CURRENT_DATE",
  "INTERVAL",
  "CASE",
  "WHEN",
  "THEN",
  "ELSE",
  "END",
]);

interface SqlBlockProps {
  sql: string;
  /** The exact clause injected by the scoping layer, e.g. "WHERE p.producer_id = 42". */
  scopeClause: string | null;
  /** When true the agent refused to run the query - not shown for refusals. */
  refused?: boolean;
  /** Start expanded or collapsed. */
  defaultOpen?: boolean;
}

/**
 * Renders a SQL snippet in a dark "editor" style block, with the row-level
 * security clause (producer_id scoping) highlighted in the accent color so
 * the multi-tenant isolation argument is visible at a glance.
 *
 * The highlighter scans for the substring `producer_id = <number>` (with an
 * optional alias like `p.producer_id`) anywhere inside a WHERE clause and
 * wraps that exact span in accent. If no scope clause is present (admin),
 * no highlight is applied and the badge reads "Full access".
 */
export function SqlBlock({
  sql,
  scopeClause,
  refused = false,
  defaultOpen = false,
}: SqlBlockProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  const hasScope = scopeClause != null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="w-full">
      <div className="overflow-hidden rounded-md border border-border bg-background">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-secondary/40"
          >
            <div className="flex min-w-0 items-center gap-2">
              <Database size={14} className="shrink-0 text-muted-foreground" />
              <span className="truncate text-[11px] font-body uppercase tracking-wide text-muted-foreground">
                SQL exécuté
              </span>
              {hasScope ? (
                <span className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-1.5 py-0 text-[10px] font-body uppercase tracking-wide text-accent">
                  <Shield size={10} />
                  Scoping appliqué
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary px-1.5 py-0 text-[10px] font-body uppercase tracking-wide text-muted-foreground">
                  Full access
                </span>
              )}
            </div>
            <ChevronDown
              size={14}
              className={cn(
                "shrink-0 text-muted-foreground transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="border-t border-border">
            <HighlightedSql sql={sql} hasScope={hasScope} refused={refused} />
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

function HighlightedSql({
  sql,
  hasScope,
  refused,
}: {
  sql: string;
  hasScope: boolean;
  refused: boolean;
}) {
  const lines = sql.split("\n");

  return (
    <pre className="overflow-x-auto bg-[#232E25] p-4 font-mono text-[12.5px] leading-relaxed">
      <code className="block">
        {lines.map((line, idx) => (
          <div key={idx} className="flex">
            <span className="w-7 shrink-0 select-none pr-3 text-right font-heading text-[11px] text-muted-foreground/70 tabular-nums">
              {idx + 1}
            </span>
            <span className="flex-1 whitespace-pre">
              {hasScope ? renderScopedLine(line) : renderTokens(line)}
            </span>
          </div>
        ))}
      </code>

      {refused && (
        <div className="mt-3 flex items-center gap-2 rounded-md border border-dashed border-border bg-background px-2 py-1.5 text-[11px] text-muted-foreground">
          <Shield size={14} className="shrink-0" />
          Action refusée - la requête a été rejetée par la couche de scoping
          avant exécution.
        </div>
      )}
    </pre>
  );
}

/**
 * Scan the line for a `producer_id = <number>` clause (with optional alias
 * like `p.producer_id`), wrap that exact span in the accent color, and
 * tokenize the rest.
 */
function renderScopedLine(line: string): React.ReactNode {
  // Match optional-alias producer_id, optional whitespace, =, optional
  // whitespace, and a number. Case-insensitive on identifiers.
  const re = /([A-Za-z_][A-Za-z0-9_]*\.)?producer_id\s*=\s*\d+/i;
  const m = re.exec(line);
  if (!m) return renderTokens(line);
  const start = m.index;
  const end = start + m[0].length;
  const before = line.slice(0, start);
  const scope = line.slice(start, end);
  const after = line.slice(end);
  return (
    <>
      {renderTokens(before)}
      <span className="font-medium text-accent">{scope}</span>
      {renderTokens(after)}
    </>
  );
}

/**
 * Lightweight SQL tokenizer: keywords → accent-tinted, strings → foreground,
 * numbers → Caudex muted, identifiers → foreground, comments → muted.
 * Good enough for a polished code block without a full grammar engine.
 */
function renderTokens(text: string): React.ReactNode {
  if (!text) return null;
  const tokenRe =
    /(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|([(),.;*=<>+\-/]+)|(\s+)|([^\s])/g;

  const nodes: React.ReactNode[] = [];
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = tokenRe.exec(text)) !== null) {
    const [full, comment, str, num, ident, punct, ws] = m;
    if (comment) {
      nodes.push(
        <span key={key++} className="italic text-muted-foreground/70">
          {comment}
        </span>,
      );
    } else if (str) {
      nodes.push(
        <span key={key++} className="text-foreground/90">
          {str}
        </span>,
      );
    } else if (num) {
      nodes.push(
        <span key={key++} className="font-heading text-muted-foreground tabular-nums">
          {num}
        </span>,
      );
    } else if (ident) {
      const upper = ident.toUpperCase();
      if (SQL_KEYWORDS.has(upper)) {
        nodes.push(
          <span key={key++} className="font-medium text-accent/90">
            {ident}
          </span>,
        );
      } else {
        nodes.push(
          <span key={key++} className="text-foreground">
            {ident}
          </span>,
        );
      }
    } else if (punct) {
      nodes.push(
        <span key={key++} className="text-muted-foreground">
          {punct}
        </span>,
      );
    } else if (ws) {
      nodes.push(ws);
    } else {
      nodes.push(full);
    }
  }
  return nodes;
}
