"use client";

/**
 * TeamManagement — admin panel to invite + manage tenant members.
 *
 * Phase C2: allows tenant admins to:
 *  - List current members (email, role, producer_id, active status)
 *  - Invite a new member by email (must already have an account)
 *  - Remove a member
 *  - Change a member's role
 *
 * Uses POST /api/tenants/{id}/members (existing backend endpoint).
 */

import { useState, useEffect, useCallback } from "react";
import { UserPlus, Trash2, Shield, User, Mail, Loader2 } from "lucide-react";
import { toast } from "sonner";

interface Member {
  user_id: number;
  email: string;
  name: string;
  role: string;
  producer_id: number | null;
  is_active: boolean;
}

interface TeamManagementProps {
  tenantId: string;
}

export function TeamManagement({ tenantId }: TeamManagementProps) {
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("producer");
  const [inviteProducerId, setInviteProducerId] = useState("");
  const [inviting, setInviting] = useState(false);

  const fetchMembers = useCallback(async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem("tevet7.jwt");
      const res = await fetch(`/api/tenants/${tenantId}`, {
        headers: { authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setMembers(data.members || []);
      }
    } catch {
      // Non-fatal
    } finally {
      setLoading(false);
    }
  }, [tenantId]);

  useEffect(() => {
    void fetchMembers();
  }, [fetchMembers]);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) {
      toast.error("Email requis");
      return;
    }
    setInviting(true);
    try {
      const token = localStorage.getItem("tevet7.jwt");
      const res = await fetch(`/api/tenants/${tenantId}/members`, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
        body: JSON.stringify({
          email: inviteEmail.trim(),
          role: inviteRole,
          producer_id: inviteProducerId ? parseInt(inviteProducerId) : null,
        }),
      });
      if (res.ok) {
        toast.success(`${inviteEmail} ajouté au workspace`);
        setInviteEmail("");
        setInviteProducerId("");
        void fetchMembers();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || "Erreur lors de l'invitation");
      }
    } catch {
      toast.error("Erreur réseau");
    } finally {
      setInviting(false);
    }
  };

  const handleRemove = async (userId: number, email: string) => {
    if (!confirm(`Retirer ${email} du workspace ?`)) return;
    try {
      const token = localStorage.getItem("tevet7.jwt");
      const res = await fetch(`/api/tenants/${tenantId}/members/${userId}`, {
        method: "DELETE",
        headers: { authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        toast.success(`${email} retiré du workspace`);
        void fetchMembers();
      } else {
        toast.error("Erreur lors du retrait");
      }
    } catch {
      toast.error("Erreur réseau");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Invite form ── */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 flex items-center gap-2 font-heading text-lg text-foreground">
          <UserPlus className="h-5 w-5 text-accent" />
          Inviter un membre
        </h3>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="mb-1 block text-xs text-muted-foreground">Email</label>
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="marie@exemple.com"
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">Rôle</label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              className="rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
            >
              <option value="producer">Producteur</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          {inviteRole === "producer" && (
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Producer ID</label>
              <input
                type="number"
                value={inviteProducerId}
                onChange={(e) => setInviteProducerId(e.target.value)}
                placeholder="42"
                className="w-24 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
              />
            </div>
          )}
          <button
            onClick={handleInvite}
            disabled={inviting}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          >
            {inviting ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            Inviter
          </button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          L'utilisateur doit déjà avoir un compte Tevet-7. Il devra activer le
          workspace depuis son sélecteur de tenant.
        </p>
      </div>

      {/* ── Members list ── */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 flex items-center gap-2 font-heading text-lg text-foreground">
          <Users className="h-5 w-5 text-accent" />
          Membres ({members.length})
        </h3>
        <div className="space-y-2">
          {members.map((m) => (
            <div
              key={m.user_id}
              className="flex items-center justify-between rounded-md border border-border/50 bg-background/50 p-3"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary/30">
                  {m.role === "admin" ? (
                    <Shield className="h-4 w-4 text-accent" />
                  ) : (
                    <User className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {m.name || m.email}
                    {m.is_active && (
                      <span className="ml-2 rounded-full bg-accent/20 px-2 py-0.5 text-[10px] text-accent-foreground">
                        Actif
                      </span>
                    )}
                  </p>
                  <p className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Mail className="h-3 w-3" />
                    {m.email}
                    {m.producer_id && ` · producer_id: ${m.producer_id}`}
                  </p>
                </div>
              </div>
              <button
                onClick={() => handleRemove(m.user_id, m.email)}
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                title="Retirer du workspace"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Also export Users icon for the parent
import { Users } from "lucide-react";
