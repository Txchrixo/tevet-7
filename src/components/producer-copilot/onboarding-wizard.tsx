"use client";

import * as React from "react";
import { motion } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle,
  Database,
  FileText,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
  X,
  Zap,
} from "@/components/ui/feather-icons";
import { useCopilotStore } from "@/lib/store";
import {
  connectCsv,
  connectPostgres,
  detectSchema as detectSchemaApi,
  saveRoles as saveRolesApi,
  saveSchema as saveSchemaApi,
  OnboardingApiError,
} from "@/lib/onboarding-api";
import type {
  ConnectorType,
  RoleConfig,
  SchemaTable,
} from "@/lib/types";
import { BrandMark } from "./brand-mark";

// ---------------------------------------------------------------------------
// Onboarding wizard — Phase 6b
// ---------------------------------------------------------------------------
//
// A full-screen 4-step wizard that walks the user through connecting a data
// source, detecting the schema, defining roles, and finally landing in the
// agent chat. Renders in place of the chat when the active tenant is not
// yet onboarded (or when the user re-opens it from the header menu).
//
// The wizard reads its working state from the zustand store
// (`onboardingStep`, `onboardingData`, `onboardingError`) so navigation
// between steps preserves the user's input. The page-level gate renders
// `<OnboardingWizard />` whenever `onboardingStep > 0`.

interface WizardProps {
  /** The tenant id the wizard is operating on. */
  tenantId: string;
}

export function OnboardingWizard({ tenantId }: WizardProps) {
  const step = useCopilotStore((s) => s.onboardingStep);
  const exitOnboarding = useCopilotStore((s) => s.exitOnboarding);
  const activeTenant = useCopilotStore((s) => s.activeTenant);

  // Background BrandMark size — computed after mount to avoid hydration
  // mismatch (server can't read window.innerWidth).
  const [bgMarkSize, setBgMarkSize] = React.useState(480);
  React.useEffect(() => {
    const update = () => setBgMarkSize(Math.min(640, window.innerWidth * 0.8));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-background">
      {/* Subtle background brand mark */}
      <div
        className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.04]"
        aria-hidden
      >
        <BrandMark size={bgMarkSize} />
      </div>

      {/* Top bar — brand + tenant badge + exit */}
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border bg-background/95 px-3 backdrop-blur sm:px-4">
        <div className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-md border border-border bg-background text-accent">
            <BrandMark size={18} />
          </span>
          <span className="font-heading text-base">Tevet-7</span>
          <Separator orientation="vertical" className="hidden h-4 sm:block" />
          <span className="hidden text-[11px] uppercase tracking-wide text-muted-foreground sm:inline">
            Configuration du workspace
          </span>
        </div>
        <div className="flex items-center gap-2">
          {activeTenant && (
            <span
              className="hidden max-w-[180px] truncate rounded-md border border-border bg-secondary/50 px-2 py-0.5 text-[11px] uppercase tracking-wide text-muted-foreground sm:inline"
              title={activeTenant.name}
            >
              {activeTenant.name}
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-[12px] text-muted-foreground"
            onClick={exitOnboarding}
          >
            <X size={14} />
            Fermer
          </Button>
        </div>
      </header>

      {/* Main wizard body */}
      <main className="relative z-10 flex flex-1 flex-col items-center justify-start px-4 py-8 sm:py-12">
        <div className="w-full max-w-2xl">
          <ProgressIndicator step={step} />

          <motion.div
            key={step}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="mt-6"
          >
            {step === 1 && <StepConnect tenantId={tenantId} />}
            {step === 2 && <StepSchema tenantId={tenantId} />}
            {step === 3 && <StepRoles tenantId={tenantId} />}
            {step === 4 && <StepReady tenantId={tenantId} />}
          </motion.div>
        </div>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress indicator — 4 dots + step labels
// ---------------------------------------------------------------------------

const STEP_LABELS = [
  "Connexion",
  "Schéma",
  "Rôles",
  "Prêt",
] as const;

function ProgressIndicator({ step }: { step: number }) {
  return (
    <div className="flex items-center justify-center gap-2 sm:gap-3">
      {STEP_LABELS.map((label, i) => {
        const n = i + 1;
        const isActive = n === step;
        const isDone = n < step;
        return (
          <React.Fragment key={label}>
            <div className="flex items-center gap-2">
              <div
                className={
                  "flex size-7 items-center justify-center rounded-full border text-[11px] font-heading transition-colors " +
                  (isActive
                    ? "border-accent bg-accent text-accent-foreground"
                    : isDone
                      ? "border-accent/40 bg-accent/10 text-accent"
                      : "border-border bg-background text-muted-foreground")
                }
                aria-current={isActive ? "step" : undefined}
                aria-label={`Étape ${n} : ${label}`}
              >
                {isDone ? <Check size={13} /> : n}
              </div>
              <span
                className={
                  "hidden text-[11px] uppercase tracking-wide sm:inline " +
                  (isActive ? "text-foreground" : "text-muted-foreground")
                }
              >
                {label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div
                className={
                  "h-px w-6 sm:w-12 " +
                  (isDone ? "bg-accent/40" : "bg-border")
                }
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step header — used by every step for the H2 + subtitle
// ---------------------------------------------------------------------------

function StepHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="text-center">
      <p className="text-[10px] uppercase tracking-[0.18em] text-accent">
        {eyebrow}
      </p>
      <h2 className="mt-1.5 font-heading text-xl sm:text-2xl">{title}</h2>
      <p className="mx-auto mt-1.5 max-w-md text-sm text-muted-foreground">
        {subtitle}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error block — surfaced inline below the wizard body
// ---------------------------------------------------------------------------

function ErrorBlock({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="mt-4 flex items-start gap-2 rounded-md border border-border bg-secondary/60 px-3 py-2 text-xs text-foreground"
    >
      <AlertCircle size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
      <span className="font-body leading-snug">{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Spinner — used by the wizard's action buttons
// ---------------------------------------------------------------------------

function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={
        "size-3 animate-spin rounded-full border-2 border-primary-foreground/40 border-t-primary-foreground " +
        (className ?? "")
      }
      aria-hidden
    />
  );
}

// ---------------------------------------------------------------------------
// Step 1 — Connect data
// ---------------------------------------------------------------------------

function StepConnect({ tenantId }: { tenantId: string }) {
  const updateOnboardingData = useCopilotStore((s) => s.updateOnboardingData);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const clearOnboardingError = useCopilotStore((s) => s.clearOnboardingError);
  const onboardingError = useCopilotStore((s) => s.onboardingError);
  const onboardingLoading = useCopilotStore((s) => s.onboardingLoading);

  const data = useCopilotStore((s) => s.onboardingData);
  const setWizardLoading = useSetOnboardingLoading();
  const setWizardError = useSetOnboardingError();

  const [url, setUrl] = React.useState(data.connectionUrl);
  const [fileName, setFileName] = React.useState(data.csvFile?.name ?? "");

  const connector = data.connectorType;
  const connectionTest = data.connectionTest;

  const onPick = (next: ConnectorType) => {
    clearOnboardingError();
    updateOnboardingData({
      connectorType: next,
      connectionTest: null,
    });
  };

  const onFilePicked = (file: File | null) => {
    clearOnboardingError();
    updateOnboardingData({ csvFile: file, connectionTest: null });
    setFileName(file?.name ?? "");
  };

  const testPostgres = async () => {
    setWizardLoading(true);
    setWizardError(null);
    try {
      const result = await connectPostgres(tenantId, url.trim());
      if (result.ok) {
        updateOnboardingData({
          connectionUrl: url.trim(),
          connectionTest: { ok: true, tables_count: result.tables_count },
        });
      } else {
        setWizardError(result.error ?? "Connexion échouée");
      }
    } catch (err) {
      const msg =
        err instanceof OnboardingApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Connexion échouée";
      setWizardError(msg);
    } finally {
      setWizardLoading(false);
    }
  };

  const testCsv = async () => {
    if (!data.csvFile) {
      setWizardError("Choisissez d'abord un fichier .csv");
      return;
    }
    setWizardLoading(true);
    setWizardError(null);
    try {
      const result = await connectCsv(tenantId, data.csvFile);
      if (result.ok) {
        updateOnboardingData({
          connectionTest: { ok: true, tables_count: result.tables_count },
        });
      } else {
        setWizardError(result.error ?? "Connexion échouée");
      }
    } catch (err) {
      const msg =
        err instanceof OnboardingApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Connexion échouée";
      setWizardError(msg);
    } finally {
      setWizardLoading(false);
    }
  };

  const canContinue = !!connectionTest?.ok;

  return (
    <div>
      <StepHeader
        eyebrow="Étape 1 / 4"
        title="Connectez votre donnée"
        subtitle="Choisissez une source de données. Vous pourrez la reconfigurer plus tard depuis le menu utilisateur."
      />

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        <ConnectorCard
          icon={<Database size={20} />}
          title="PostgreSQL"
          description="Connecter une base existante via son URL"
          selected={connector === "postgres"}
          onClick={() => onPick("postgres")}
        />
        <ConnectorCard
          icon={<FileText size={20} />}
          title="CSV"
          description="Charger un fichier CSV (une table)"
          selected={connector === "csv"}
          onClick={() => onPick("csv")}
        />
      </div>

      {connector === "postgres" && (
        <div className="mt-5 space-y-3 rounded-md border border-border bg-background p-4">
          <div className="space-y-1.5">
            <Label
              htmlFor="pg-url"
              className="text-[11px] uppercase tracking-wide text-muted-foreground"
            >
              URL de connexion
            </Label>
            <Input
              id="pg-url"
              type="text"
              autoComplete="off"
              spellCheck={false}
              placeholder="postgresql://user:pass@host:5432/dbname"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                updateOnboardingData({ connectionTest: null });
              }}
              className="h-9 font-mono text-[12px]"
            />
            <p className="text-[11px] text-muted-foreground">
              Le moteur tente une introspection en lecture seule — aucun
              dommage possible sur votre base.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-8 gap-1.5 text-[12px]"
              disabled={onboardingLoading || !url.trim()}
              onClick={testPostgres}
            >
              {onboardingLoading ? (
                <Spinner />
              ) : (
                <RefreshCw size={13} />
              )}
              Tester la connexion
            </Button>
            {connectionTest?.ok && (
              <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-accent">
                <CheckCircle size={13} />
                OK · {connectionTest.tables_count} table
                {connectionTest.tables_count > 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
      )}

      {connector === "csv" && (
        <div className="mt-5 space-y-3 rounded-md border border-border bg-background p-4">
          <Label className="text-[11px] uppercase tracking-wide text-muted-foreground">
            Fichier CSV
          </Label>
          <label
            htmlFor="csv-file"
            className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-secondary/30 px-4 py-6 text-center transition-colors hover:border-accent/50 hover:bg-accent/5"
          >
            <Upload size={22} className="text-accent" />
            <span className="text-[12px] font-body text-foreground">
              {fileName || "Cliquez pour choisir un fichier .csv"}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              La première ligne est l'en-tête
            </span>
            <input
              id="csv-file"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                onFilePicked(f);
              }}
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-8 gap-1.5 text-[12px]"
              disabled={onboardingLoading || !data.csvFile}
              onClick={testCsv}
            >
              {onboardingLoading ? <Spinner /> : <RefreshCw size={13} />}
              Tester
            </Button>
            {connectionTest?.ok && (
              <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-accent">
                <CheckCircle size={13} />
                OK · {connectionTest.tables_count} table
                {connectionTest.tables_count > 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
      )}

      {!connector && (
        <p className="mt-5 text-center text-[11px] uppercase tracking-wide text-muted-foreground">
          Sélectionnez une source ci-dessus pour commencer
        </p>
      )}

      <ErrorBlock message={onboardingError} />

      <WizardFooter>
        <span />
        <Button
          type="button"
          className="h-9 gap-2 text-sm"
          disabled={!canContinue}
          onClick={() => setOnboardingStep(2)}
        >
          Continuer
          <ArrowRight size={15} />
        </Button>
      </WizardFooter>
    </div>
  );
}

interface ConnectorCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  selected: boolean;
  onClick: () => void;
}

function ConnectorCard({
  icon,
  title,
  description,
  selected,
  onClick,
}: ConnectorCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={
        "flex items-start gap-3 rounded-md border p-4 text-left transition-colors " +
        (selected
          ? "border-accent bg-accent/10"
          : "border-border bg-background hover:border-accent/40 hover:bg-secondary/30")
      }
    >
      <span
        className={
          "flex size-9 shrink-0 items-center justify-center rounded-md border " +
          (selected
            ? "border-accent/40 bg-accent/20 text-accent"
            : "border-border bg-secondary/50 text-muted-foreground")
        }
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="font-heading text-sm text-foreground">{title}</span>
          {selected && <Check size={13} className="text-accent" />}
        </div>
        <p className="mt-0.5 text-[12px] text-muted-foreground">{description}</p>
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Detect schema
// ---------------------------------------------------------------------------

function StepSchema({ tenantId }: { tenantId: string }) {
  const data = useCopilotStore((s) => s.onboardingData);
  const updateOnboardingData = useCopilotStore((s) => s.updateOnboardingData);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const onboardingError = useCopilotStore((s) => s.onboardingError);
  const onboardingLoading = useCopilotStore((s) => s.onboardingLoading);

  const setWizardLoading = useSetOnboardingLoading();
  const setWizardError = useSetOnboardingError();
  const clearOnboardingError = useCopilotStore((s) => s.clearOnboardingError);

  const draft = data.schemaDraft;

  const detect = async () => {
    setWizardLoading(true);
    setWizardError(null);
    try {
      const result = await detectSchemaApi(tenantId);
      updateOnboardingData({ schemaDraft: result });
    } catch (err) {
      const msg =
        err instanceof OnboardingApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Détection échouée";
      setWizardError(msg);
    } finally {
      setWizardLoading(false);
    }
  };

  const toggleTable = (tableName: string, selected: boolean) => {
    if (!draft) return;
    updateOnboardingData({
      schemaDraft: {
        tables: draft.tables.map((t) =>
          t.name === tableName ? { ...t, selected } : t,
        ),
      },
    });
  };

  const toggleColumn = (
    tableName: string,
    columnName: string,
    selected: boolean,
  ) => {
    if (!draft) return;
    updateOnboardingData({
      schemaDraft: {
        tables: draft.tables.map((t) =>
          t.name === tableName
            ? {
                ...t,
                columns: t.columns.map((c) =>
                  c.name === columnName ? { ...c, selected } : c,
                ),
              }
            : t,
        ),
      },
    });
  };

  const setScopeColumn = (tableName: string, scope: string | null) => {
    if (!draft) return;
    updateOnboardingData({
      schemaDraft: {
        tables: draft.tables.map((t) =>
          t.name === tableName
            ? { ...t, scope_column: scope }
            : t,
        ),
      },
    });
  };

  const save = async () => {
    if (!draft) return;
    setWizardLoading(true);
    setWizardError(null);
    try {
      await saveSchemaApi(tenantId, draft.tables);
      setOnboardingStep(3);
    } catch (err) {
      const msg =
        err instanceof OnboardingApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Sauvegarde échouée";
      setWizardError(msg);
    } finally {
      setWizardLoading(false);
    }
  };

  const selectedCount = draft?.tables.filter((t) => t.selected).length ?? 0;

  return (
    <div>
      <StepHeader
        eyebrow="Étape 2 / 4"
        title="Détectez votre schéma"
        subtitle="L'agent ne verra que les tables et colonnes que vous activez. Choisissez la colonne de scope pour le row-level security."
      />

      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        <Button
          type="button"
          variant="outline"
          className="h-8 gap-1.5 text-[12px]"
          disabled={onboardingLoading}
          onClick={detect}
        >
          {onboardingLoading ? (
            <Spinner />
          ) : (
            <RefreshCw size={13} />
          )}
          {draft ? "Re-détecter" : "Détecter le schéma"}
        </Button>
        {draft && (
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {draft.tables.length} table
            {draft.tables.length > 1 ? "s" : ""} · {selectedCount} activée
            {selectedCount > 1 ? "s" : ""}
          </span>
        )}
      </div>

      {draft && draft.tables.length === 0 && (
        <p className="mt-6 text-center text-sm text-muted-foreground">
          Aucune table détectée. Vérifiez votre connexion puis re-détectez.
        </p>
      )}

      {draft && draft.tables.length > 0 && (
        <div className="mt-5 space-y-3">
          {draft.tables.map((table) => (
            <SchemaTableRow
              key={table.name}
              table={table}
              onToggleTable={(selected) => toggleTable(table.name, selected)}
              onToggleColumn={(col, selected) =>
                toggleColumn(table.name, col, selected)
              }
              onScopeColumn={(scope) => setScopeColumn(table.name, scope)}
            />
          ))}
        </div>
      )}

      <ErrorBlock message={onboardingError} />

      <WizardFooter>
        <Button
          type="button"
          variant="ghost"
          className="h-9 gap-1.5 text-sm text-muted-foreground"
          onClick={() => {
            clearOnboardingError();
            setOnboardingStep(1);
          }}
        >
          <ArrowRight size={15} className="rotate-180" />
          Retour
        </Button>
        <Button
          type="button"
          className="h-9 gap-2 text-sm"
          disabled={!draft || selectedCount === 0 || onboardingLoading}
          onClick={save}
        >
          {onboardingLoading ? <Spinner /> : null}
          Continuer
          <ArrowRight size={15} />
        </Button>
      </WizardFooter>
    </div>
  );
}

interface SchemaTableRowProps {
  table: SchemaTable;
  onToggleTable: (selected: boolean) => void;
  onToggleColumn: (columnName: string, selected: boolean) => void;
  onScopeColumn: (scope: string | null) => void;
}

function SchemaTableRow({
  table,
  onToggleTable,
  onToggleColumn,
  onScopeColumn,
}: SchemaTableRowProps) {
  const [expanded, setExpanded] = React.useState(true);
  const selectedColumns = table.columns.filter((c) => c.selected).length;

  return (
    <div
      className={
        "rounded-md border transition-colors " +
        (table.selected
          ? "border-border bg-background"
          : "border-border bg-secondary/30 opacity-70")
      }
    >
      <div className="flex items-center gap-2 p-3">
        <button
          type="button"
          aria-pressed={table.selected}
          aria-label={`${table.selected ? "Désélectionner" : "Sélectionner"} la table ${table.name}`}
          onClick={() => onToggleTable(!table.selected)}
          className={
            "flex size-5 shrink-0 items-center justify-center rounded border transition-colors " +
            (table.selected
              ? "border-accent bg-accent text-accent-foreground"
              : "border-border bg-background text-transparent hover:border-accent/60")
          }
        >
          <Check size={13} />
        </button>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span className="truncate font-heading text-sm text-foreground">
            {table.name}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {table.columns.length} col · {selectedColumns} actives
          </span>
        </button>
        <div className="flex items-center gap-1.5">
          <Label
            htmlFor={`scope-${table.name}`}
            className="hidden text-[10px] uppercase tracking-wide text-muted-foreground sm:inline"
          >
            Scope
          </Label>
          <Select
            value={table.scope_column ?? "__none__"}
            onValueChange={(v) =>
              onScopeColumn(v === "__none__" ? null : v)
            }
          >
            <SelectTrigger
              id={`scope-${table.name}`}
              className="h-7 w-[140px] gap-1.5 border-border text-[12px]"
              size="sm"
            >
              <SelectValue placeholder="Aucune" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">Aucune</SelectItem>
              {table.columns.map((c) => (
                <SelectItem key={c.name} value={c.name}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {expanded && table.selected && (
        <div className="border-t border-border px-3 py-2.5">
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {table.columns.map((col) => (
              <li key={col.name}>
                <button
                  type="button"
                  aria-pressed={col.selected}
                  onClick={() => onToggleColumn(col.name, !col.selected)}
                  className={
                    "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[12px] transition-colors hover:bg-secondary/40 " +
                    (col.selected ? "text-foreground" : "text-muted-foreground")
                  }
                >
                  <span
                    className={
                      "flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border " +
                      (col.selected
                        ? "border-accent bg-accent text-accent-foreground"
                        : "border-border bg-background text-transparent")
                    }
                  >
                    <Check size={11} />
                  </span>
                  <span className="font-mono">{col.name}</span>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                    {col.type}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {table.scope_column && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              RLS sur{" "}
              <code className="rounded bg-secondary px-1 py-0.5 font-mono text-[0.85em] text-accent">
                {table.scope_column}
              </code>{" "}
              — l'agent ne verra que les lignes du scope courant.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Define roles
// ---------------------------------------------------------------------------

function StepRoles({ tenantId }: { tenantId: string }) {
  const data = useCopilotStore((s) => s.onboardingData);
  const updateOnboardingData = useCopilotStore((s) => s.updateOnboardingData);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const onboardingError = useCopilotStore((s) => s.onboardingError);
  const onboardingLoading = useCopilotStore((s) => s.onboardingLoading);

  const setWizardLoading = useSetOnboardingLoading();
  const setWizardError = useSetOnboardingError();
  const clearOnboardingError = useCopilotStore((s) => s.clearOnboardingError);

  // Seed default roles the first time the user reaches step 3.
  React.useEffect(() => {
    if (data.rolesConfig.length === 0) {
      const selectedTables =
        data.schemaDraft?.tables.filter((t) => t.selected) ?? [];
      const firstScope = selectedTables.find((t) => t.scope_column)?.scope_column ?? null;
      const allTables = selectedTables.map((t) => t.name);
      const defaults: RoleConfig[] = [
        {
          name: "admin",
          scope_column: null,
          allowed_tables: allTables,
        },
        {
          name: "user",
          scope_column: firstScope,
          allowed_tables: allTables,
        },
      ];
      updateOnboardingData({ rolesConfig: defaults });
    }
    // Only seed once when entering step 3 — `data.rolesConfig.length === 0`
    // is the gate. We intentionally don't depend on `data.schemaDraft` so
    // navigating back to step 2 + re-detecting doesn't wipe the user's
    // role edits.
  }, []);

  const selectedTables = (data.schemaDraft?.tables ?? []).filter(
    (t) => t.selected,
  );
  const allColumnOptions = React.useMemo(() => {
    // Collect every column name across all selected tables — the scope
    // dropdown offers the union (e.g. "producer_id", "team_id").
    const set = new Set<string>();
    for (const t of selectedTables) {
      for (const c of t.columns) set.add(c.name);
    }
    return Array.from(set).sort();
  }, [selectedTables]);

  const updateRole = (idx: number, patch: Partial<RoleConfig>) => {
    const next = data.rolesConfig.map((r, i) =>
      i === idx ? { ...r, ...patch } : r,
    );
    updateOnboardingData({ rolesConfig: next });
  };

  const removeRole = (idx: number) => {
    updateOnboardingData({
      rolesConfig: data.rolesConfig.filter((_, i) => i !== idx),
    });
  };

  const addRole = () => {
    updateOnboardingData({
      rolesConfig: [
        ...data.rolesConfig,
        {
          name: `role-${data.rolesConfig.length + 1}`,
          scope_column: null,
          allowed_tables: selectedTables.map((t) => t.name),
        },
      ],
    });
  };

  const toggleRoleTable = (idx: number, tableName: string) => {
    const role = data.rolesConfig[idx];
    if (!role) return;
    const has = role.allowed_tables.includes(tableName);
    updateRole(idx, {
      allowed_tables: has
        ? role.allowed_tables.filter((t) => t !== tableName)
        : [...role.allowed_tables, tableName],
    });
  };

  const save = async () => {
    setWizardLoading(true);
    setWizardError(null);
    try {
      await saveRolesApi(tenantId, data.rolesConfig);
      setOnboardingStep(4);
    } catch (err) {
      const msg =
        err instanceof OnboardingApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Sauvegarde échouée";
      setWizardError(msg);
    } finally {
      setWizardLoading(false);
    }
  };

  return (
    <div>
      <StepHeader
        eyebrow="Étape 3 / 4"
        title="Définissez les rôles"
        subtitle="Chaque rôle a un scope (colonne de row-level security) et des tables autorisées. L'admin n'a pas de scope."
      />

      <div className="mt-6 space-y-3">
        {data.rolesConfig.map((role, idx) => (
          <RoleRow
            key={idx}
            role={role}
            columnOptions={allColumnOptions}
            tables={selectedTables.map((t) => t.name)}
            onChange={(patch) => updateRole(idx, patch)}
            onRemove={
              data.rolesConfig.length > 1 ? () => removeRole(idx) : undefined
            }
            onToggleTable={(t) => toggleRoleTable(idx, t)}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={addRole}
        className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-border bg-background py-2.5 text-[12px] uppercase tracking-wide text-muted-foreground transition-colors hover:border-accent/50 hover:text-accent"
      >
        <Plus size={13} />
        Ajouter un rôle
      </button>

      <ErrorBlock message={onboardingError} />

      <WizardFooter>
        <Button
          type="button"
          variant="ghost"
          className="h-9 gap-1.5 text-sm text-muted-foreground"
          onClick={() => {
            clearOnboardingError();
            setOnboardingStep(2);
          }}
        >
          <ArrowRight size={15} className="rotate-180" />
          Retour
        </Button>
        <Button
          type="button"
          className="h-9 gap-2 text-sm"
          disabled={data.rolesConfig.length === 0 || onboardingLoading}
          onClick={save}
        >
          {onboardingLoading ? <Spinner /> : null}
          Continuer
          <ArrowRight size={15} />
        </Button>
      </WizardFooter>
    </div>
  );
}

interface RoleRowProps {
  role: RoleConfig;
  columnOptions: string[];
  tables: string[];
  onChange: (patch: Partial<RoleConfig>) => void;
  onRemove?: () => void;
  onToggleTable: (tableName: string) => void;
}

function RoleRow({
  role,
  columnOptions,
  tables,
  onChange,
  onRemove,
  onToggleTable,
}: RoleRowProps) {
  return (
    <div className="rounded-md border border-border bg-background p-3">
      <div className="flex items-center gap-2">
        <Input
          type="text"
          value={role.name}
          onChange={(e) => onChange({ name: e.target.value })}
          className="h-8 flex-1 font-heading text-sm"
          placeholder="nom du rôle"
          aria-label="Nom du rôle"
        />
        <Select
          value={role.scope_column ?? "__none__"}
          onValueChange={(v) =>
            onChange({ scope_column: v === "__none__" ? null : v })
          }
        >
          <SelectTrigger className="h-8 w-[160px] gap-1.5 text-[12px]" size="sm">
            <SelectValue placeholder="Scope" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">Aucun (admin)</SelectItem>
            {columnOptions.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {onRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8 shrink-0 text-muted-foreground hover:text-foreground"
            onClick={onRemove}
            aria-label="Supprimer ce rôle"
          >
            <Trash2 size={14} />
          </Button>
        )}
      </div>
      <div className="mt-2.5">
        <p className="mb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
          Tables autorisées
        </p>
        <div className="flex flex-wrap gap-1.5">
          {tables.length === 0 && (
            <span className="text-[11px] text-muted-foreground">
              Aucune table sélectionnée à l'étape 2.
            </span>
          )}
          {tables.map((t) => {
            const has = role.allowed_tables.includes(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={has}
                onClick={() => onToggleTable(t)}
                className={
                  "rounded border px-1.5 py-0.5 font-mono text-[11px] transition-colors " +
                  (has
                    ? "border-accent/40 bg-accent/10 text-accent"
                    : "border-border bg-background text-muted-foreground hover:border-accent/40 hover:text-foreground")
                }
              >
                {has ? <Check size={9} className="mr-1 inline" /> : null}
                {t}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4 — Ready
// ---------------------------------------------------------------------------

function StepReady({ tenantId: _tenantId }: { tenantId: string }) {
  const data = useCopilotStore((s) => s.onboardingData);
  const finishOnboarding = useCopilotStore((s) => s.finishOnboarding);
  const setOnboardingStep = useCopilotStore((s) => s.setOnboardingStep);
  const onboardingLoading = useCopilotStore((s) => s.onboardingLoading);
  const onboardingError = useCopilotStore((s) => s.onboardingError);

  const selectedTables = (data.schemaDraft?.tables ?? []).filter(
    (t) => t.selected,
  );

  return (
    <div>
      <StepHeader
        eyebrow="Étape 4 / 4"
        title="Votre workspace est configuré"
        subtitle="Vérifiez la configuration puis accédez à l'agent. Vous pourrez tout reconfigurer depuis le menu utilisateur."
      />

      <div className="mt-6 overflow-hidden rounded-md border border-border bg-background">
        <SummaryRow
          label="Source de données"
          value={
            data.connectorType === "postgres"
              ? "PostgreSQL"
              : data.connectorType === "csv"
                ? "CSV"
                : "—"
          }
          icon={<Database size={14} />}
        />
        <SummaryRow
          label="Tables exposées"
          value={`${selectedTables.length} table${selectedTables.length > 1 ? "s" : ""}`}
          icon={<FileText size={14} />}
        />
        <SummaryRow
          label="Rôles définis"
          value={`${data.rolesConfig.length} rôle${data.rolesConfig.length > 1 ? "s" : ""}`}
          icon={<ShieldRowIcon />}
        />
        {data.rolesConfig.length > 0 && (
          <div className="border-t border-border bg-secondary/30 px-4 py-3">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Rôles
            </p>
            <ul className="mt-1.5 space-y-1">
              {data.rolesConfig.map((r, i) => (
                <li
                  key={`${r.name}-${i}`}
                  className="flex items-center gap-2 text-[12px]"
                >
                  <span className="font-heading text-foreground">{r.name}</span>
                  <span className="text-muted-foreground">
                    {r.scope_column
                      ? `scope : ${r.scope_column}`
                      : "admin (full tenant)"}
                  </span>
                  <span className="ml-auto text-[11px] text-muted-foreground">
                    {r.allowed_tables.length} table
                    {r.allowed_tables.length > 1 ? "s" : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <ErrorBlock message={onboardingError} />

      <WizardFooter>
        <Button
          type="button"
          variant="ghost"
          className="h-9 gap-1.5 text-sm text-muted-foreground"
          disabled={onboardingLoading}
          onClick={() => setOnboardingStep(3)}
        >
          <ArrowRight size={15} className="rotate-180" />
          Retour
        </Button>
        <Button
          type="button"
          className="h-9 gap-2 text-sm"
          disabled={onboardingLoading}
          onClick={() => void finishOnboarding()}
        >
          {onboardingLoading ? (
            <Spinner />
          ) : (
            <Zap size={15} />
          )}
          Accéder à l'agent
          <ArrowRight size={15} />
        </Button>
      </WizardFooter>
    </div>
  );
}

function ShieldRowIcon() {
  // Reuse the Feather Shield icon at small size — kept inline so we don't
  // have to import another icon name.
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={14}
      height={14}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}

function SummaryRow({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-secondary/50 text-muted-foreground">
        {icon}
      </span>
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="ml-auto font-heading text-sm text-foreground">
        {value}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard footer (back / continue row)
// ---------------------------------------------------------------------------

function WizardFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-7 flex items-center justify-between gap-2">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tiny helpers — write the wizard's loading / error flags directly via the
// store's setState API so individual step components don't need extra
// actions wired up.
// ---------------------------------------------------------------------------

function useSetOnboardingLoading(): (loading: boolean) => void {
  return React.useCallback((loading: boolean) => {
    useCopilotStore.setState({ onboardingLoading: loading });
  }, []);
}

function useSetOnboardingError(): (err: string | null) => void {
  return React.useCallback((err: string | null) => {
    useCopilotStore.setState({ onboardingError: err });
  }, []);
}
