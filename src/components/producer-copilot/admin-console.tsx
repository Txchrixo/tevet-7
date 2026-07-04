"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart2,
  Check,
  Clock,
  Eye,
  Globe,
  Layers,
  MessageSquare,
  RefreshCw,
  Server,
  Shield,
  ShieldOff,
  Sliders,
  Trash,
  Users,
} from "@/components/ui/feather-icons";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import type {
  Conversation,
  PlatformStats,
  PlatformTenant,
  TenantConfig,
  TenantStats,
  TenantUser,
} from "@/lib/types";

import { BrandMark } from "./brand-mark";

// ---------------------------------------------------------------------------
// Formatting helpers — French locale, Caudex for numbers in stat cards.
// ---------------------------------------------------------------------------

function frNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("fr-FR").replace(/\s/g, "\u00A0");
}

function frMoney(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const v = n.toFixed(2).replace(".", ",");
  return `${v}\u00A0$`;
}

function frPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // refusal_rate is 0..1 per the spec, but tolerate 0..100 just in case.
  const pct = n > 1 ? n : n * 100;
  return `${pct.toFixed(1).replace(".", ",")}\u00A0%`;
}

function frDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncate(s: string, max = 80): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

// ---------------------------------------------------------------------------
// Shared subcomponents
// ---------------------------------------------------------------------------

interface AdminConsoleProps {
  mode: "tenant" | "platform";
}

export function AdminConsole({ mode }: AdminConsoleProps) {
  if (mode === "tenant") return <TenantAdminView />;
  return <PlatformOwnerView />;
}

// ---------------------------------------------------------------------------
// Tenant admin view
// ---------------------------------------------------------------------------

function TenantAdminView() {
  const identity = useCopilotStore((s) => s.identity);
  const adminData = useCopilotStore((s) => s.adminData);
  const adminLoading = useCopilotStore((s) => s.adminLoading);
  const setAdminView = useCopilotStore((s) => s.setAdminView);
  const loadTenantAdmin = useCopilotStore((s) => s.loadTenantAdmin);

  // Refresh on mount — the store action is idempotent.
  React.useEffect(() => {
    void loadTenantAdmin();
  }, []);

  const tenantLabel =
    adminData.config && typeof adminData.config === "object"
      ? "Drive Producteur"
      : `tenant ${adminData.tenantId}`;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AdminHeader
        title="Console Admin"
        subtitle={tenantLabel}
        icon={<Shield size={18} />}
        onBack={() => setAdminView("none")}
      />

      <main className="mx-auto w-full max-w-7xl flex-1 px-3 py-5 sm:px-4">
        {adminData.error && <ErrorBanner message={adminData.error} />}

        {adminLoading && adminData.users.length === 0 ? (
          <LoadingState />
        ) : (
          <div className="space-y-5">
            {/* Stats row */}
            <TenantStatsGrid stats={adminData.stats} />

            {/* Two-column: users + config */}
            <div className="grid gap-5 lg:grid-cols-2">
              <UsersPanel users={adminData.users} />
              <ConfigPanel config={adminData.config} tenantId={adminData.tenantId} />
            </div>

            {/* Conversations — full width */}
            <ConversationsPanel conversations={adminData.conversations} />
          </div>
        )}

        <p className="mt-6 text-[11px] uppercase tracking-wide text-muted-foreground">
          Identité · {identity.name} · {identity.role}
        </p>
      </main>
    </div>
  );
}

function TenantStatsGrid({ stats }: { stats: TenantStats | null }) {
  const cards: Array<{
    label: string;
    value: string;
    icon: React.ReactNode;
    accent?: boolean;
  }> = [
    {
      label: "Conversations totales",
      value: stats ? frNum(stats.total_conversations) : "—",
      icon: <MessageSquare size={14} />,
    },
    {
      label: "Tokens consommés",
      value: stats ? frNum(stats.total_tokens) : "—",
      icon: <Activity size={14} />,
    },
    {
      label: "Coût USD",
      value: stats ? frMoney(stats.total_cost_usd) : "—",
      icon: <BarChart2 size={14} />,
      accent: true,
    },
    {
      label: "Latence moyenne",
      value: stats ? `${frNum(stats.avg_latency_ms)}\u00A0ms` : "—",
      icon: <Clock size={14} />,
    },
  ];
  return (
    <section>
      <SectionLabel icon={<Activity size={12} />}>Statistiques</SectionLabel>
      <div className="mt-2 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {cards.map((c) => (
          <StatCard key={c.label} {...c} />
        ))}
      </div>
      <div className="mt-2.5">
        <SmallStat
          label="Taux de refus"
          value={stats ? frPct(stats.refusal_rate) : "—"}
        />
      </div>
    </section>
  );
}

function UsersPanel({ users }: { users: TenantUser[] }) {
  return (
    <section className="rounded-md border border-border bg-background">
      <PanelHeader icon={<Users size={14} />} title="Membres" count={users.length} />
      <Separator />
      {users.length === 0 ? (
        <EmptyPanel message="Aucun membre." />
      ) : (
        <div className="max-h-96 overflow-y-auto admin-scroll">
          <ul className="divide-y divide-border">
            {users.map((u) => (
              <li key={u.user_id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-foreground">
                        {u.name || "—"}
                      </span>
                      <RoleBadge role={u.role} />
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                      {u.email}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                      {u.producer_id !== null && u.producer_id !== undefined && (
                        <span>
                          producer_id ·{" "}
                          <span className="font-heading text-foreground tabular-nums">
                            {u.producer_id}
                          </span>
                        </span>
                      )}
                      <span>
                        membre depuis ·{" "}
                        <span className="font-heading text-foreground">
                          {frDate(u.joined_at)}
                        </span>
                      </span>
                    </div>
                  </div>
                  <span className="font-heading text-[11px] text-muted-foreground tabular-nums">
                    #{u.user_id}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ConfigPanel({
  config,
  tenantId,
}: {
  config: TenantConfig | null;
  tenantId: string;
}) {
  const tableCount = React.useMemo(() => {
    if (!config) return null;
    const sc = config.schema_config as
      | { tables?: unknown }
      | Record<string, unknown>
      | null;
    if (!sc) return null;
    if (Array.isArray((sc as { tables?: unknown[] }).tables)) {
      return (sc as { tables: unknown[] }).tables.length;
    }
    if (
      sc &&
      typeof sc === "object" &&
      "tables" in sc &&
      typeof (sc as { tables: Record<string, unknown> }).tables === "object"
    ) {
      return Object.keys((sc as { tables: Record<string, unknown> }).tables).length;
    }
    return null;
  }, [config]);

  const roleCount = React.useMemo(() => {
    if (!config) return null;
    const rc = config.roles_config as Record<string, unknown> | null;
    if (!rc || typeof rc !== "object") return null;
    return Object.keys(rc).length;
  }, [config]);

  return (
    <section className="rounded-md border border-border bg-background">
      <PanelHeader
        icon={<Sliders size={14} />}
        title="Configuration"
        subtitle={tenantId}
      />
      <Separator />
      {!config ? (
        <EmptyPanel message="Configuration indisponible." />
      ) : (
        <div className="space-y-3 p-4">
          <ConfigRow label="Connector" value={config.connector_type} mono />
          <ConfigRow
            label="Tables"
            value={tableCount !== null ? frNum(tableCount) : "—"}
          />
          <ConfigRow
            label="Rôles"
            value={roleCount !== null ? frNum(roleCount) : "—"}
          />
          <ConfigRow
            label="Onboarded"
            value={config.onboarded ? "Oui" : "Non"}
            badge={config.onboarded ? "ok" : "muted"}
          />
          <ConfigRow label="Créé le" value={frDate(config.created_at)} />
        </div>
      )}
    </section>
  );
}

function ConversationsPanel({ conversations }: { conversations: Conversation[] }) {
  return (
    <section className="rounded-md border border-border bg-background">
      <PanelHeader
        icon={<Eye size={14} />}
        title="Conversations récentes"
        count={conversations.length}
      />
      <Separator />
      {conversations.length === 0 ? (
        <EmptyPanel message="Aucune conversation enregistrée." />
      ) : (
        <div className="max-h-96 overflow-y-auto admin-scroll">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-background">
              <tr className="border-b border-border text-left">
                <Th>Message</Th>
                <Th>Intent</Th>
                <Th className="text-right">Latence</Th>
                <Th className="text-right">Tokens</Th>
                <Th className="text-right">Coût</Th>
                <Th>Statut</Th>
                <Th className="text-right">Créé le</Th>
              </tr>
            </thead>
            <tbody>
              {conversations.map((c) => (
                <tr key={c.id} className="border-b border-border last:border-0">
                  <Td className="max-w-[280px] truncate text-foreground">
                    {truncate(c.user_message, 80)}
                  </Td>
                  <Td>
                    <span className="rounded-md border border-border bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                      {c.intent || "—"}
                    </span>
                  </Td>
                  <Td className="text-right font-heading tabular-nums text-foreground">
                    {frNum(c.latency_ms)}
                    <span className="text-muted-foreground"> ms</span>
                  </Td>
                  <Td className="text-right font-heading tabular-nums text-foreground">
                    {frNum(c.tokens_in + c.tokens_out)}
                  </Td>
                  <Td className="text-right font-heading tabular-nums text-foreground">
                    {frMoney(c.cost_usd)}
                  </Td>
                  <Td>
                    {c.refused ? (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                        <ShieldOff size={11} />
                        Refusé
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-accent">
                        <Check size={11} />
                        OK
                      </span>
                    )}
                  </Td>
                  <Td className="text-right text-[11px] text-muted-foreground">
                    {frDate(c.created_at)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Platform owner view
// ---------------------------------------------------------------------------

function PlatformOwnerView() {
  const adminData = useCopilotStore((s) => s.adminData);
  const adminLoading = useCopilotStore((s) => s.adminLoading);
  const setAdminView = useCopilotStore((s) => s.setAdminView);
  const loadPlatformAdmin = useCopilotStore((s) => s.loadPlatformAdmin);
  const resetDemo = useCopilotStore((s) => s.resetDemo);

  React.useEffect(() => {
    void loadPlatformAdmin();
  }, []);

  const openTenant = (tenantId: string) => {
    void useCopilotStore.getState().loadTenantAdmin(tenantId).then(() => {
      setAdminView("tenant");
    });
  };

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AdminHeader
        title="Console Platform"
        subtitle="Tevet-7"
        icon={<Globe size={18} />}
        onBack={() => setAdminView("none")}
        right={
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 border-border text-muted-foreground hover:border-accent/50 hover:text-foreground"
                disabled={adminLoading}
              >
                <Trash size={14} />
                Reset démo
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent className="bg-background">
              <AlertDialogHeader>
                <AlertDialogTitle className="font-heading">
                  Réinitialiser la démo ?
                </AlertDialogTitle>
                <AlertDialogDescription>
                  Cette action régénère les commandes et documents du tenant
                  démo <code className="font-mono text-accent">dp</code>. Les
                  conversations existantes sont conservées mais les données
                  métier reviennent à leur état initial. Cette action est
                  irréversible.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="border-border">
                  Annuler
                </AlertDialogCancel>
                <AlertDialogAction
                  className="bg-primary text-foreground hover:bg-primary/90"
                  onClick={() => void resetDemo()}
                >
                  Réinitialiser
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        }
      />

      <main className="mx-auto w-full max-w-7xl flex-1 px-3 py-5 sm:px-4">
        {adminData.error && <ErrorBanner message={adminData.error} />}

        {adminLoading && adminData.tenants.length === 0 ? (
          <LoadingState />
        ) : (
          <div className="space-y-5">
            <PlatformStatsGrid stats={adminData.platformStats} />
            <TenantsPanel tenants={adminData.tenants} onOpen={openTenant} />
          </div>
        )}
      </main>
    </div>
  );
}

function PlatformStatsGrid({ stats }: { stats: PlatformStats | null }) {
  const cards: Array<{
    label: string;
    value: string;
    icon: React.ReactNode;
    accent?: boolean;
  }> = [
    {
      label: "Tenants totaux",
      value: stats ? frNum(stats.total_tenants) : "—",
      icon: <Layers size={14} />,
    },
    {
      label: "Users totaux",
      value: stats ? frNum(stats.total_users) : "—",
      icon: <Users size={14} />,
    },
    {
      label: "Conversations totales",
      value: stats ? frNum(stats.total_conversations) : "—",
      icon: <MessageSquare size={14} />,
    },
    {
      label: "Coût total USD",
      value: stats ? frMoney(stats.total_cost_usd) : "—",
      icon: <BarChart2 size={14} />,
      accent: true,
    },
    {
      label: "Tokens totaux",
      value: stats ? frNum(stats.total_tokens) : "—",
      icon: <Activity size={14} />,
    },
  ];
  return (
    <section>
      <SectionLabel icon={<Globe size={12} />}>Statistiques globales</SectionLabel>
      <div className="mt-2 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
        {cards.map((c) => (
          <StatCard key={c.label} {...c} />
        ))}
      </div>
      <div className="mt-2.5">
        <SmallStat
          label="Latence moyenne (ms)"
          value={stats ? frNum(stats.avg_latency_ms) : "—"}
        />
      </div>
    </section>
  );
}

function TenantsPanel({
  tenants,
  onOpen,
}: {
  tenants: PlatformTenant[];
  onOpen: (tenantId: string) => void;
}) {
  return (
    <section className="rounded-md border border-border bg-background">
      <PanelHeader
        icon={<Server size={14} />}
        title="Tenants"
        count={tenants.length}
      />
      <Separator />
      {tenants.length === 0 ? (
        <EmptyPanel message="Aucun tenant." />
      ) : (
        <div className="max-h-[28rem] overflow-y-auto admin-scroll">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-background">
              <tr className="border-b border-border text-left">
                <Th>Tenant</Th>
                <Th>Slug</Th>
                <Th>Type</Th>
                <Th>Onboarded</Th>
                <Th className="text-right">Membres</Th>
                <Th className="text-right">Conv.</Th>
                <Th className="text-right">Coût USD</Th>
                <Th className="text-right">Créé le</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr
                  key={t.id}
                  className="border-b border-border last:border-0 hover:bg-secondary/40"
                >
                  <Td>
                    <button
                      type="button"
                      onClick={() => onOpen(t.id)}
                      className="text-left text-sm font-medium text-foreground transition-colors hover:text-accent"
                    >
                      {t.name}
                    </button>
                  </Td>
                  <Td>
                    <code className="font-mono text-[11px] text-muted-foreground">
                      {t.slug}
                    </code>
                  </Td>
                  <Td>
                    {t.is_demo ? (
                      <span className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-accent">
                        Démo
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                        Prod
                      </span>
                    )}
                  </Td>
                  <Td>
                    {t.onboarded ? (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-accent">
                        <Check size={11} /> Oui
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                        <AlertTriangle size={11} /> Non
                      </span>
                    )}
                  </Td>
                  <Td className="text-right font-heading tabular-nums text-foreground">
                    {frNum(t.member_count)}
                  </Td>
                  <Td className="text-right font-heading tabular-nums text-foreground">
                    {frNum(t.conversation_count)}
                  </Td>
                  <Td className="text-right font-heading tabular-nums text-foreground">
                    {frMoney(t.total_cost_usd)}
                  </Td>
                  <Td className="text-right text-[11px] text-muted-foreground">
                    {frDate(t.created_at)}
                  </Td>
                  <Td className="text-right">
                    <button
                      type="button"
                      onClick={() => onOpen(t.id)}
                      className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground transition-colors hover:border-accent/50 hover:text-foreground"
                    >
                      Console
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Shared presentational primitives
// ---------------------------------------------------------------------------

function AdminHeader({
  title,
  subtitle,
  icon,
  onBack,
  right,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  onBack: () => void;
  right?: React.ReactNode;
}) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border bg-background px-3 sm:px-4">
      <Button
        variant="ghost"
        size="sm"
        className="gap-1.5 text-muted-foreground hover:text-foreground"
        onClick={onBack}
      >
        <ArrowLeft size={14} />
        <span className="hidden sm:inline">Retour à l&apos;agent</span>
        <span className="sm:hidden">Agent</span>
      </Button>
      <Separator orientation="vertical" className="hidden h-5 md:block" />
      <div className="hidden items-center justify-center rounded-md border border-border bg-background text-accent md:flex size-7">
        <BrandMark size={16} />
      </div>
      <div className="flex min-w-0 flex-col">
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">{icon}</span>
          <h1 className="truncate font-heading text-sm font-medium text-foreground">
            {title}
          </h1>
          <span className="text-muted-foreground/50">·</span>
          <span className="truncate text-[12px] text-muted-foreground">
            {subtitle}
          </span>
        </div>
      </div>
      {right && <div className="ml-auto flex items-center gap-1.5">{right}</div>}
    </header>
  );
}

function SectionLabel({
  icon,
  children,
}: {
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
      {icon && <span className="text-muted-foreground">{icon}</span>}
      {children}
    </div>
  );
}

function PanelHeader({
  icon,
  title,
  count,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  count?: number;
  subtitle?: string;
}) {
  return (
    <div className="flex items-center gap-2 px-4 py-3">
      <span className="text-muted-foreground">{icon}</span>
      <h2 className="font-heading text-sm font-medium text-foreground">{title}</h2>
      {typeof count === "number" && (
        <span className="font-heading text-[11px] text-muted-foreground tabular-nums">
          {frNum(count)}
        </span>
      )}
      {subtitle && (
        <code className="ml-auto font-mono text-[10px] text-muted-foreground">
          {subtitle}
        </code>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-md border bg-background p-3.5",
        accent ? "border-accent/40" : "border-border",
      )}
    >
      <div className="flex items-center justify-between text-muted-foreground">
        <span className="text-[10px] uppercase tracking-wide">{label}</span>
        <span className={accent ? "text-accent" : "text-muted-foreground"}>
          {icon}
        </span>
      </div>
      <div
        className={cn(
          "mt-2 font-heading text-xl tabular-nums",
          accent ? "text-accent" : "text-foreground",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function SmallStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className="font-heading text-sm tabular-nums text-foreground">
        {value}
      </span>
    </div>
  );
}

function ConfigRow({
  label,
  value,
  mono,
  badge,
}: {
  label: string;
  value: string;
  mono?: boolean;
  badge?: "ok" | "muted";
}) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {badge ? (
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] uppercase tracking-wide",
            badge === "ok"
              ? "border-accent/30 bg-accent/5 text-accent"
              : "border-border text-muted-foreground",
          )}
        >
          {badge === "ok" && <Check size={11} />}
          {value}
        </span>
      ) : (
        <span
          className={cn(
            "text-right text-foreground",
            mono && "font-mono text-[12px]",
            !mono && "font-heading tabular-nums",
          )}
        >
          {value}
        </span>
      )}
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const isAdmin = role === "admin" || role === "owner";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0 text-[10px] uppercase tracking-wide",
        isAdmin
          ? "border-accent/30 bg-accent/5 text-accent"
          : "border-border text-muted-foreground",
      )}
    >
      {role}
    </span>
  );
}

function Th({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      className={cn(
        "px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground",
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <td className={cn("px-3 py-2.5 align-middle text-sm", className)}>{children}</td>
  );
}

function EmptyPanel({ message }: { message: string }) {
  return (
    <div className="px-4 py-8 text-center text-[12px] text-muted-foreground">
      {message}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="flex size-10 items-center justify-center rounded-md border border-border bg-background text-accent">
        <RefreshCw size={18} className="animate-spin" />
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">Chargement…</p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          Interrogation du backend admin Tevet-7.
        </p>
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-4 flex items-start gap-2 rounded-md border border-dashed border-border bg-background px-3 py-2.5 text-sm text-muted-foreground">
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <div>
        <p className="font-medium text-foreground">Admin indisponible</p>
        <p className="mt-0.5 text-[12px] text-muted-foreground">{message}</p>
        <p className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground/70">
          Le backend admin FastAPI doit tourner sur localhost:8001.
        </p>
      </div>
    </div>
  );
}
