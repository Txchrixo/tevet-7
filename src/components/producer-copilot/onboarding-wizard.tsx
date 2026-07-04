"use client";

import * as React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle,
  ChevronDown,
  Database,
  FileText,
  Plus,
  RefreshCw,
  Trash,
  Upload,
} from "@/components/ui/feather-icons";
import {
  Checkbox,
} from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  OnboardingApiError,
  connectCsv,
  connectPostgres,
  detectSchema,
  saveRoles,
  saveSchema,
} from "@/lib/onboarding-api";
import type {
  OnboardingRole,
  OnboardingSchemaColumn,
  OnboardingSchemaTable,
} from "@/lib/types";

import { BrandMark } from "./brand-mark";
import { Footer } from "./footer";

// ---------------------------------------------------------------------------
// Main wizard shell
// ---------------------------------------------------------------------------

interface OnboardingWizardProps {
  /** Tenant the wizard is operating on (the active tenant). */
  tenantId: string;
}

const STEP_LABELS = [
  "Connecter les données",
  "Détecter le schéma",
  "Définir les rôles",
  "Workspace prêt",
] as const;

/**
 * 4-step onboarding wizard shown when the active tenant is authenticated but
 * not yet onboarded (`activeTenant.onboarded === false`).
 *
 * Steps:
 *   1. Connect data — PostgreSQL URL or CSV upload
 *   2. Detect schema — pick tables/columns + scope columns (RLS)
 *   3. Define roles — admin + user defaults + user-added
 *   4. Ready — summary + "Accéder à l'agent" completes onboarding
 *
 * All API calls go through the relative `/api/tenants/{id}/onboarding/*`
 * paths (proxied by Next.js to localhost:8001). The wizard never talks to
 * the backend directly.
 *
 * Design: Tevet-7 dark-green palette, Caudex headings, Manrope body, Feather
 * icons, bordered cards (no heavy shadows), max-w-2xl centered card.
 */
export function OnboardingWizard({ tenantId }: OnboardingWizardProps) {
  const step = useCopilotStore((s) => s.onboardingStep);
  const startOnboarding = useCopilotStore((s) => s.startOnboarding);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);

  // Ensure the wizard is active for this tenant on mount — the store's
  // `startOnboarding` resets draft state and sets step=1.
  React.useEffect(() => {
    if (step === 0) startOnboarding(tenantId);
    // We intentionally only run this on mount — `startOnboarding` is
    // idempotent but calling it on every step change would wipe draft state.
  }, [tenantId, step, startOnboarding]);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <main className="flex flex-1 items-start justify-center px-4 py-8 sm:py-12">
        <div className="w-full max-w-2xl">
          {/* Brand header */}
          <div className="mb-6 flex flex-col items-center text-center">
            <div className="flex size-12 items-center justify-center rounded-md border border-border bg-background text-accent">
              <BrandMark size={28} />
            </div>
            <h1 className="mt-4 font-heading text-2xl tracking-tight text-foreground sm:text-3xl">
              Configuration du workspace
            </h1>
            <p className="mt-1.5 max-w-md font-body text-sm text-muted-foreground">
              Connectez vos données, configurez le schéma de l&apos;agent et
              définissez les rôles. Quelques minutes suffisent.
            </p>
          </div>

          {/* Progress indicator — 4 dots */}
          <ProgressIndicator step={step} labels={STEP_LABELS} />

          {/* Step card */}
          <div className="mt-6 rounded-md border border-border bg-background p-5 sm:p-6">
            <AnimatePresence mode="wait">
              <motion.div
                key={step}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.18 }}
              >
                {step === 1 && <Step1Connect tenantId={tenantId} />}
                {step === 2 && <Step2Schema tenantId={tenantId} />}
                {step === 3 && <Step3Roles tenantId={tenantId} />}
                {step === 4 && <Step4Ready tenantId={tenantId} />}
                {step === 0 && (
                  <p className="text-center text-sm text-muted-foreground">
                    Initialisation…
                  </p>
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Back button — hidden on step 1 + step 4 (final) */}
          {step > 1 && step < 4 && (
            <button
              type="button"
              onClick={() => setOnboardingStep(step - 1)}
              className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft size={13} />
              Étape précédente
            </button>
          )}
        </div>
      </main>

      <Footer />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress indicator
// ---------------------------------------------------------------------------

function ProgressIndicator({
  step,
  labels,
}: {
  step: number;
  labels: readonly string[];
}) {
  return (
    <div className="flex items-center justify-center gap-2 sm:gap-3">
      {labels.map((label, i) => {
        const stepNum = i + 1;
        const isActive = step === stepNum;
        const isDone = step > stepNum;
        return (
          <React.Fragment key={label}>
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn(
                  "flex size-7 items-center justify-center rounded-full border font-heading text-xs transition-colors sm:size-8 sm:text-sm",
                  isActive &&
                    "border-accent bg-accent text-accent-foreground",
                  isDone && "border-accent text-accent",
                  !isActive && !isDone && "border-border text-muted-foreground",
                )}
                aria-current={isActive ? "step" : undefined}
              >
                {isDone ? <Check size={13} /> : stepNum}
              </div>
              <span
                className={cn(
                  "hidden text-center text-[10px] uppercase tracking-wide sm:block",
                  isActive ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {label}
              </span>
            </div>
            {i < labels.length - 1 && (
              <div
                className={cn(
                  "h-px w-8 sm:w-12",
                  step > stepNum ? "bg-accent/60" : "bg-border",
                )}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Connect data
// ---------------------------------------------------------------------------

function Step1Connect({ tenantId }: { tenantId: string }) {
  const setOnboardingData = useCopilotStore((s) => s.setOnboardingData);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const setOnboardingLoading = useCopilotStore((s) => s.setOnboardingLoading);
  const setOnboardingError = useCopilotStore((s) => s.setOnboardingError);
  const loading = useCopilotStore((s) => s.onboardingLoading);
  const error = useCopilotStore((s) => s.onboardingError);
  const data = useCopilotStore((s) => s.onboardingData);

  const [connectorType, setConnectorType] = React.useState<
    "postgres" | "csv" | null
  >(data.connectorType);
  const [connectionUrl, setConnectionUrl] = React.useState(data.connectionUrl);
  const [csvFile, setCsvFile] = React.useState<File | null>(null);
  const [testedOk, setTestedOk] = React.useState(false);
  const [tablesCount, setTablesCount] = React.useState(data.tablesCount);

  // Reset the "tested ok" flag whenever the user edits the form.
  React.useEffect(() => {
    setTestedOk(false);
  }, [connectorType, connectionUrl, csvFile]);

  const handlePick = (kind: "postgres" | "csv") => {
    if (loading) return;
    setConnectorType(kind);
    setOnboardingError(null);
    setTestedOk(false);
  };

  const handleTestPostgres = async () => {
    if (loading || !connectionUrl.trim()) return;
    setOnboardingLoading(true);
    setOnboardingError(null);
    try {
      const result = await connectPostgres(tenantId, connectionUrl.trim());
      if (result.ok) {
        setTestedOk(true);
        setTablesCount(result.tables_count);
        setOnboardingData({
          connectorType: "postgres",
          connectionUrl: connectionUrl.trim(),
          csvFileName: null,
          tablesCount: result.tables_count,
        });
        toast.success("Connexion Postgres validée", {
          description: `${result.tables_count} table(s) détectée(s).`,
        });
      } else {
        setOnboardingError(
          result.error ?? "Connexion impossible — vérifiez l'URL.",
        );
      }
    } catch (err) {
      const message =
        err instanceof OnboardingApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      setOnboardingError(message);
    } finally {
      setOnboardingLoading(false);
    }
  };

  const handleUploadCsv = async () => {
    if (loading || !csvFile) return;
    setOnboardingLoading(true);
    setOnboardingError(null);
    try {
      const result = await connectCsv(tenantId, csvFile);
      if (result.ok) {
        setTestedOk(true);
        setTablesCount(result.tables_count);
        setOnboardingData({
          connectorType: "csv",
          connectionUrl: "",
          csvFileName: csvFile.name,
          tablesCount: result.tables_count,
        });
        toast.success("CSV importé", {
          description: `${result.tables_count} table(s) détectée(s).`,
        });
      } else {
        setOnboardingError(
          result.error ?? "Import impossible — vérifiez le fichier.",
        );
      }
    } catch (err) {
      const message =
        err instanceof OnboardingApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      setOnboardingError(message);
    } finally {
      setOnboardingLoading(false);
    }
  };

  const handleContinue = () => {
    if (!testedOk) return;
    setOnboardingError(null);
    setOnboardingStep(2);
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-heading text-xl text-foreground">
          1 · Connecter les données
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Choisissez une source de données. L&apos;agent Tevet-7 ne lira qu&apos;en
          lecture seule, sur les tables que vous sélectionnerez à l&apos;étape
          suivante.
        </p>
      </div>

      {/* Connector cards */}
      <div className="grid gap-3 sm:grid-cols-2">
        <ConnectorCard
          active={connectorType === "postgres"}
          onClick={() => handlePick("postgres")}
          icon={<Database size={20} className="text-accent" />}
          title="PostgreSQL"
          description="Connectez une base existante via son URL."
        />
        <ConnectorCard
          active={connectorType === "csv"}
          onClick={() => handlePick("csv")}
          icon={<FileText size={20} className="text-accent" />}
          title="CSV"
          description="Importez un fichier CSV (une table)."
        />
      </div>

      {/* Connector-specific form */}
      {connectorType === "postgres" && (
        <div className="space-y-3 rounded-md border border-border bg-secondary/20 p-4">
          <label className="block">
            <span className="mb-1 block text-[11px] font-body uppercase tracking-wide text-muted-foreground">
              URL de connexion PostgreSQL
            </span>
            <input
              type="text"
              value={connectionUrl}
              onChange={(e) => setConnectionUrl(e.target.value)}
              placeholder="postgresql://user:pass@host:5432/dbname"
              disabled={loading}
              className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-xs text-foreground outline-none transition-colors focus:border-accent/50 disabled:opacity-50"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <p className="text-[11px] text-muted-foreground">
            Format : <code className="text-foreground">postgresql://user:pass@host:5432/db</code>.
            Stockée chiffrée côté backend, jamais exposée au navigateur après envoi.
          </p>
          <button
            type="button"
            onClick={handleTestPostgres}
            disabled={loading || !connectionUrl.trim()}
            className={cn(
              "inline-flex items-center gap-2 rounded-md border border-border bg-background px-4 py-2 font-body text-sm text-foreground transition-colors",
              "hover:border-accent/50 hover:bg-secondary/30 disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {loading ? (
              <>
                <RefreshCw size={14} className="animate-spin text-muted-foreground" />
                Test en cours…
              </>
            ) : (
              <>
                <Database size={14} className="text-accent" />
                Tester la connexion
              </>
            )}
          </button>
        </div>
      )}

      {connectorType === "csv" && (
        <div className="space-y-3 rounded-md border border-border bg-secondary/20 p-4">
          <label className="block">
            <span className="mb-1 block text-[11px] font-body uppercase tracking-wide text-muted-foreground">
              Fichier CSV
            </span>
            <input
              type="file"
              accept=".csv,text/csv"
              disabled={loading}
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setCsvFile(f);
                setTestedOk(false);
              }}
              className="block w-full text-xs text-muted-foreground file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1.5 file:text-foreground file:transition-colors hover:file:border-accent/50"
            />
          </label>
          {csvFile && (
            <p className="text-[11px] text-muted-foreground">
              Fichier sélectionné :{" "}
              <span className="text-foreground">{csvFile.name}</span>{" "}
              ({(csvFile.size / 1024).toFixed(1)} Ko)
            </p>
          )}
          <button
            type="button"
            onClick={handleUploadCsv}
            disabled={loading || !csvFile}
            className={cn(
              "inline-flex items-center gap-2 rounded-md border border-border bg-background px-4 py-2 font-body text-sm text-foreground transition-colors",
              "hover:border-accent/50 hover:bg-secondary/30 disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {loading ? (
              <>
                <RefreshCw size={14} className="animate-spin text-muted-foreground" />
                Import en cours…
              </>
            ) : (
              <>
                <Upload size={14} className="text-accent" />
                Importer le CSV
              </>
            )}
          </button>
        </div>
      )}

      {/* Status / error */}
      {testedOk && (
        <div className="flex items-center gap-2 rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-accent">
          <CheckCircle size={14} />
          <span>
            Connexion validée · {tablesCount} table(s) détectée(s).
          </span>
        </div>
      )}
      {error && (
        <ErrorBanner message={error} />
      )}

      {/* Continue */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleContinue}
          disabled={!testedOk || loading}
          className={cn(
            "inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 font-body text-sm font-medium text-foreground transition-colors",
            "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          Continuer
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}

function ConnectorCard({
  active,
  onClick,
  icon,
  title,
  description,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-2 rounded-md border p-4 text-left transition-colors",
        active
          ? "border-accent bg-accent/5"
          : "border-border bg-background hover:border-accent/40 hover:bg-secondary/20",
      )}
      aria-pressed={active}
    >
      <div
        className={cn(
          "flex size-9 items-center justify-center rounded-md border",
          active ? "border-accent" : "border-border",
        )}
      >
        {icon}
      </div>
      <div>
        <div className="font-heading text-sm text-foreground">{title}</div>
        <p className="mt-0.5 text-[11px] text-muted-foreground">{description}</p>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Detect schema
// ---------------------------------------------------------------------------

function Step2Schema({ tenantId }: { tenantId: string }) {
  const setOnboardingData = useCopilotStore((s) => s.setOnboardingData);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const setOnboardingLoading = useCopilotStore((s) => s.setOnboardingLoading);
  const setOnboardingError = useCopilotStore((s) => s.setOnboardingError);
  const loading = useCopilotStore((s) => s.onboardingLoading);
  const error = useCopilotStore((s) => s.onboardingError);
  const data = useCopilotStore((s) => s.onboardingData);

  const [tables, setTables] = React.useState<OnboardingSchemaTable[]>(
    data.schemaDraft,
  );
  const [hasDetected, setHasDetected] = React.useState(data.schemaDraft.length > 0);

  const handleDetect = async () => {
    setOnboardingLoading(true);
    setOnboardingError(null);
    try {
      const result = await detectSchema(tenantId);
      setTables(result.tables);
      setHasDetected(true);
      setOnboardingData({ schemaDraft: result.tables });
      toast.success("Schéma détecté", {
        description: `${result.tables.length} table(s) trouvée(s).`,
      });
    } catch (err) {
      const message =
        err instanceof OnboardingApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      setOnboardingError(message);
    } finally {
      setOnboardingLoading(false);
    }
  };

  const updateTable = (name: string, patch: Partial<OnboardingSchemaTable>) => {
    setTables((prev) =>
      prev.map((t) => (t.name === name ? { ...t, ...patch } : t)),
    );
  };

  const updateColumn = (
    tableName: string,
    colName: string,
    patch: Partial<OnboardingSchemaColumn>,
  ) => {
    setTables((prev) =>
      prev.map((t) =>
        t.name === tableName
          ? {
              ...t,
              columns: t.columns.map((c) =>
                c.name === colName ? { ...c, ...patch } : c,
              ),
            }
          : t,
      ),
    );
  };

  const selectedCount = tables.filter((t) => t.selected).length;

  const handleContinue = async () => {
    if (selectedCount === 0) {
      setOnboardingError("Sélectionnez au moins une table.");
      return;
    }
    setOnboardingLoading(true);
    setOnboardingError(null);
    try {
      // Commit the latest tables state to the store before saving.
      setOnboardingData({ schemaDraft: tables });
      await saveSchema(tenantId, {
        tables,
        forbidden_tables: [],
        metadata: {},
      });
      setOnboardingStep(3);
      toast.success("Schéma enregistré", {
        description: `${selectedCount} table(s) conservée(s).`,
      });
    } catch (err) {
      const message =
        err instanceof OnboardingApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      setOnboardingError(message);
    } finally {
      setOnboardingLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="font-heading text-xl text-foreground">
            2 · Détecter le schéma
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            L&apos;agent détecte les tables et colonnes de votre source. Vous
            sélectionnez celles qu&apos;il peut lire + la colonne de scope
            (RLS) pour chaque table.
          </p>
        </div>
        <button
          type="button"
          onClick={handleDetect}
          disabled={loading}
          className={cn(
            "inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 font-body text-xs text-foreground transition-colors",
            "hover:border-accent/50 hover:bg-secondary/30 disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {loading && hasDetected ? (
            <>
              <RefreshCw size={12} className="animate-spin text-muted-foreground" />
              Détection…
            </>
          ) : (
            <>
              <RefreshCw size={12} className="text-accent" />
              {hasDetected ? "Re-détecter" : "Détecter le schéma"}
            </>
          )}
        </button>
      </div>

      {!hasDetected && (
        <div className="rounded-md border border-dashed border-border bg-secondary/20 px-4 py-8 text-center">
          <Database size={24} className="mx-auto text-muted-foreground" />
          <p className="mt-2 text-sm text-muted-foreground">
            Cliquez sur <span className="text-foreground">« Détecter le schéma »</span>{" "}
            pour analyser votre source de données.
          </p>
        </div>
      )}

      {hasDetected && tables.length === 0 && (
        <div className="rounded-md border border-dashed border-border bg-secondary/20 px-4 py-6 text-center text-sm text-muted-foreground">
          Aucune table détectée. Vérifiez votre connexion à l&apos;étape 1.
        </div>
      )}

      {tables.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted-foreground">
            <span>{tables.length} tables détectées</span>
            <span>{selectedCount} sélectionnée(s)</span>
          </div>
          <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
            {tables.map((table) => (
              <TableSchemaRow
                key={table.name}
                table={table}
                onUpdateTable={(patch) => updateTable(table.name, patch)}
                onUpdateColumn={(col, patch) =>
                  updateColumn(table.name, col, patch)
                }
              />
            ))}
          </div>
        </div>
      )}

      {error && <ErrorBanner message={error} />}

      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleContinue}
          disabled={loading || selectedCount === 0}
          className={cn(
            "inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 font-body text-sm font-medium text-foreground transition-colors",
            "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {loading ? "Enregistrement…" : "Continuer"}
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}

function TableSchemaRow({
  table,
  onUpdateTable,
  onUpdateColumn,
}: {
  table: OnboardingSchemaTable;
  onUpdateTable: (patch: Partial<OnboardingSchemaTable>) => void;
  onUpdateColumn: (
    colName: string,
    patch: Partial<OnboardingSchemaColumn>,
  ) => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const columnNames = table.columns.map((c) => c.name);

  return (
    <div className="rounded-md border border-border bg-background">
      {/* Table header row */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        <Checkbox
          checked={table.selected}
          onCheckedChange={(v) => onUpdateTable({ selected: v === true })}
        />
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex flex-1 items-center justify-between gap-2 text-left"
        >
          <span className="font-mono text-sm text-foreground">{table.name}</span>
          <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            {table.columns.length} col(s)
            <ChevronDown
              size={12}
              className={cn(
                "transition-transform",
                expanded && "rotate-180",
              )}
            />
          </span>
        </button>
      </div>

      {/* Scope column picker (only for selected tables) */}
      {table.selected && (
        <div className="flex items-center gap-2 border-t border-border/60 px-3 py-2">
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Colonne de scope
          </span>
          <Select
            value={table.scope_column ?? "__none__"}
            onValueChange={(v) =>
              onUpdateTable({
                scope_column: v === "__none__" ? null : v,
              })
            }
          >
            <SelectTrigger className="h-7 w-40 text-xs" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">
                <span className="text-muted-foreground">Aucune (global)</span>
              </SelectItem>
              {columnNames.map((col) => (
                <SelectItem key={col} value={col}>
                  <span className="font-mono">{col}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-[10px] text-muted-foreground">
            RLS : l&apos;agent ne verra que les lignes où cette colonne = son scope.
          </span>
        </div>
      )}

      {/* Columns (expandable) */}
      {expanded && table.selected && (
        <div className="border-t border-border/60 px-3 py-2">
          <div className="grid gap-1.5 sm:grid-cols-2">
            {table.columns.map((col) => (
              <label
                key={col.name}
                className="flex items-center gap-2 text-xs"
              >
                <Checkbox
                  checked={col.selected}
                  onCheckedChange={(v) =>
                    onUpdateColumn(col.name, { selected: v === true })
                  }
                />
                <span className="font-mono text-foreground">{col.name}</span>
                <span className="text-muted-foreground">·</span>
                <span className="text-muted-foreground">{col.type}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Define roles
// ---------------------------------------------------------------------------

function Step3Roles({ tenantId }: { tenantId: string }) {
  const setOnboardingData = useCopilotStore((s) => s.setOnboardingData);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const setOnboardingLoading = useCopilotStore((s) => s.setOnboardingLoading);
  const setOnboardingError = useCopilotStore((s) => s.setOnboardingError);
  const loading = useCopilotStore((s) => s.onboardingLoading);
  const error = useCopilotStore((s) => s.onboardingError);
  const data = useCopilotStore((s) => s.onboardingData);

  // All table names from the schema draft (only selected ones, since
  // deselected tables were dropped from the saved schema).
  const allTables = React.useMemo(
    () => data.schemaDraft.filter((t) => t.selected).map((t) => t.name),
    [data.schemaDraft],
  );

  // All scope columns across selected tables — used to populate the role
  // scope-column dropdown. Deduped.
  const allScopeColumns = React.useMemo(() => {
    const set = new Set<string>();
    data.schemaDraft
      .filter((t) => t.selected && t.scope_column)
      .forEach((t) => set.add(t.scope_column as string));
    return Array.from(set);
  }, [data.schemaDraft]);

  // Default roles: admin (no scope, all tables) + user (scope = first picked
  // scope column, all tables). Computed once when the step mounts.
  const buildDefaultRoles = React.useCallback((): OnboardingRole[] => {
    const defaultScope =
      allScopeColumns[0] ?? null;
    return [
      {
        name: "admin",
        scope_column: null,
        allowed_tables: allTables,
      },
      {
        name: "user",
        scope_column: defaultScope,
        allowed_tables: allTables,
      },
    ];
  }, [allTables, allScopeColumns]);

  const [roles, setRoles] = React.useState<OnboardingRole[]>(
    data.rolesConfig.length > 0 ? data.rolesConfig : buildDefaultRoles(),
  );

  const updateRole = (idx: number, patch: Partial<OnboardingRole>) => {
    setRoles((prev) =>
      prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    );
  };

  const addRole = () => {
    setRoles((prev) => [
      ...prev,
      {
        name: `role-${prev.length + 1}`,
        scope_column: allScopeColumns[0] ?? null,
        allowed_tables: [],
      },
    ]);
  };

  const removeRole = (idx: number) => {
    setRoles((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleContinue = async () => {
    if (roles.length === 0) {
      setOnboardingError("Définissez au moins un rôle.");
      return;
    }
    // Validate role names are non-empty + unique.
    const names = roles.map((r) => r.name.trim());
    if (names.some((n) => !n)) {
      setOnboardingError("Tous les rôles doivent avoir un nom.");
      return;
    }
    if (new Set(names).size !== names.length) {
      setOnboardingError("Les noms de rôles doivent être uniques.");
      return;
    }
    setOnboardingLoading(true);
    setOnboardingError(null);
    try {
      const cleaned = roles.map((r) => ({
        name: r.name.trim(),
        scope_column: r.scope_column,
        allowed_tables: r.allowed_tables,
      }));
      setOnboardingData({ rolesConfig: cleaned });
      await saveRoles(tenantId, cleaned);
      setOnboardingStep(4);
      toast.success("Rôles enregistrés", {
        description: `${cleaned.length} rôle(s) défini(s).`,
      });
    } catch (err) {
      const message =
        err instanceof OnboardingApiError
          ? err.unreachable
            ? "Backend Tevet-7 injoignable"
            : err.message
          : err instanceof Error
            ? err.message
            : "Erreur inconnue";
      setOnboardingError(message);
    } finally {
      setOnboardingLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-heading text-xl text-foreground">
          3 · Définir les rôles
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Chaque rôle a un scope (colonne RLS) et une liste de tables
          autorisées. Les users ne voient que leurs lignes ; les admins voient
          tout le tenant.
        </p>
      </div>

      <div className="space-y-3">
        {roles.map((role, idx) => (
          <RoleRow
            key={idx}
            role={role}
            allTables={allTables}
            allScopeColumns={allScopeColumns}
            onUpdate={(patch) => updateRole(idx, patch)}
            onRemove={() => removeRole(idx)}
            canRemove={roles.length > 1}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={addRole}
        disabled={loading}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md border border-dashed border-border bg-background px-3 py-1.5 text-xs text-muted-foreground transition-colors",
          "hover:border-accent/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        <Plus size={13} />
        Ajouter un rôle
      </button>

      {error && <ErrorBanner message={error} />}

      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleContinue}
          disabled={loading || roles.length === 0}
          className={cn(
            "inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 font-body text-sm font-medium text-foreground transition-colors",
            "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {loading ? "Enregistrement…" : "Continuer"}
          <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}

function RoleRow({
  role,
  allTables,
  allScopeColumns,
  onUpdate,
  onRemove,
  canRemove,
}: {
  role: OnboardingRole;
  allTables: string[];
  allScopeColumns: string[];
  onUpdate: (patch: Partial<OnboardingRole>) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const [expanded, setExpanded] = React.useState(false);

  return (
    <div className="rounded-md border border-border bg-background">
      <div className="flex items-center gap-2 px-3 py-2.5">
        <input
          type="text"
          value={role.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          placeholder="nom-du-role"
          className="flex-1 rounded-md border border-border bg-background px-2 py-1 font-mono text-sm text-foreground outline-none focus:border-accent/50"
        />
        <Select
          value={role.scope_column ?? "__none__"}
          onValueChange={(v) =>
            onUpdate({ scope_column: v === "__none__" ? null : v })
          }
        >
          <SelectTrigger className="h-8 w-40 text-xs" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">
              <span className="text-muted-foreground">Aucun (admin)</span>
            </SelectItem>
            {allScopeColumns.map((col) => (
              <SelectItem key={col} value={col}>
                <span className="font-mono">{col}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
          aria-expanded={expanded}
        >
          {role.allowed_tables.length}/{allTables.length}
          <ChevronDown
            size={12}
            className={cn("transition-transform", expanded && "rotate-180")}
          />
        </button>
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            aria-label="Supprimer le rôle"
          >
            <Trash size={13} />
          </button>
        )}
      </div>

      {expanded && (
        <div className="border-t border-border/60 px-3 py-2">
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
            Tables autorisées
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {allTables.map((t) => {
              const checked = role.allowed_tables.includes(t);
              return (
                <label
                  key={t}
                  className="flex items-center gap-2 text-xs"
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={(v) => {
                      if (v) {
                        onUpdate({
                          allowed_tables: [...role.allowed_tables, t],
                        });
                      } else {
                        onUpdate({
                          allowed_tables: role.allowed_tables.filter(
                            (x) => x !== t,
                          ),
                        });
                      }
                    }}
                  />
                  <span className="font-mono text-foreground">{t}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Ready
// ---------------------------------------------------------------------------

function Step4Ready({ tenantId: _tenantId }: { tenantId: string }) {
  const completeOnboarding = useCopilotStore((s) => s.completeOnboarding);
  const loading = useCopilotStore((s) => s.onboardingLoading);
  const error = useCopilotStore((s) => s.onboardingError);
  const data = useCopilotStore((s) => s.onboardingData);

  const selectedTablesCount = data.schemaDraft.filter((t) => t.selected).length;
  const connectorLabel =
    data.connectorType === "postgres"
      ? "PostgreSQL"
      : data.connectorType === "csv"
        ? `CSV (${data.csvFileName ?? "fichier"})`
        : "—";

  return (
    <div className="space-y-5 text-center">
      <div className="mx-auto flex size-12 items-center justify-center rounded-full border border-accent bg-accent/10 text-accent">
        <CheckCircle size={26} />
      </div>

      <div>
        <h2 className="font-heading text-xl text-foreground">
          4 · Votre workspace est configuré
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          L&apos;agent Tevet-7 peut maintenant interroger vos données dans le
          respect du scope par rôle. Vous pouvez modifier ces réglages plus
          tard via la console admin.
        </p>
      </div>

      {/* Summary grid */}
      <div className="grid grid-cols-3 gap-2 text-left">
        <SummaryCard
          label="Source"
          value={connectorLabel}
        />
        <SummaryCard
          label="Tables"
          value={String(selectedTablesCount)}
        />
        <SummaryCard
          label="Rôles"
          value={String(data.rolesConfig.length)}
        />
      </div>

      {/* Roles breakdown */}
      <div className="rounded-md border border-border bg-secondary/20 px-4 py-3 text-left">
        <p className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
          Rôles définis
        </p>
        <ul className="space-y-1">
          {data.rolesConfig.map((r) => (
            <li
              key={r.name}
              className="flex flex-wrap items-center justify-between gap-2 text-xs"
            >
              <span className="font-mono text-foreground">{r.name}</span>
              <span className="text-muted-foreground">
                {r.scope_column
                  ? `scope : ${r.scope_column}`
                  : "admin (full tenant)"}
                {" · "}
                {r.allowed_tables.length} table(s)
              </span>
            </li>
          ))}
        </ul>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="flex justify-center">
        <button
          type="button"
          onClick={() => void completeOnboarding()}
          disabled={loading}
          className={cn(
            "inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 font-body text-sm font-medium text-foreground transition-colors",
            "hover:bg-accent hover:text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {loading ? (
            <>
              <RefreshCw size={14} className="animate-spin" />
              Finalisation…
            </>
          ) : (
            <>
              <Check size={14} />
              Accéder à l&apos;agent
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-heading text-base text-foreground">
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared error banner
// ---------------------------------------------------------------------------

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-dashed border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground"
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
      <span className="text-foreground">{message}</span>
    </div>
  );
}
