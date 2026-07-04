"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import type { DocumentInfo } from "@/lib/types";
import {
  BookOpen,
  FileText,
  Trash2,
  Upload,
} from "@/components/ui/feather-icons";

/**
 * Sidebar section listing the RAG corpus (CGV, FAQ, procédure, etc.) for the
 * active identity. Producers see only their own documents (scoped by
 * `producer_id`); the admin sees everything.
 *
 * The panel is rendered inside the sidebar's ScrollArea, so it stays compact
 * — it shows:
 *   - a "DOCUMENTS" caption (uppercase tracking-wide muted — ledger style),
 *   - the list with title + chunk count + hover-only delete button,
 *   - an "Uploader" button that opens a small Dialog (title + PDF | texte
 *     source + file picker / textarea + "Indexer" submit).
 */
export function DocumentsPanel() {
  const documents = useCopilotStore((s) => s.documents);
  const loading = useCopilotStore((s) => s.documentsLoading);
  const mutating = useCopilotStore((s) => s.documentMutating);
  const removeDocument = useCopilotStore((s) => s.removeDocument);

  const [dialogOpen, setDialogOpen] = React.useState(false);

  return (
    <section>
      <div className="flex items-center justify-between">
        <SectionLabel icon={<BookOpen size={12} />}>Documents</SectionLabel>
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-1.5 py-0.5 text-[10px] font-body uppercase tracking-wide text-muted-foreground transition-colors hover:border-accent/50 hover:text-accent"
          aria-label="Uploader un document"
        >
          <Upload size={11} />
          Uploader
        </button>
      </div>

      <div className="mt-2 space-y-1">
        {loading ? (
          <DocumentsSkeleton />
        ) : documents.length === 0 ? (
          <EmptyState />
        ) : (
          documents.map((d) => (
            <DocumentRow
              key={d.id}
              document={d}
              disabled={mutating}
              onDelete={() => removeDocument(d.id)}
            />
          ))
        )}
      </div>

      <UploadDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </section>
  );
}

function DocumentRow({
  document: doc,
  disabled,
  onDelete,
}: {
  document: DocumentInfo;
  disabled: boolean;
  onDelete: () => void;
}) {
  return (
    <div
      className={cn(
        "group flex items-start gap-2 rounded-md border border-border bg-background px-2 py-1.5 text-left transition-colors hover:border-accent/40",
      )}
    >
      <FileText
        size={13}
        className="mt-0.5 shrink-0 text-muted-foreground group-hover:text-accent"
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium text-foreground">
          {doc.title}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
          <span className="font-heading tabular-nums">{doc.chunksCount}</span>
          chunk{doc.chunksCount > 1 ? "s" : ""}
          <span className="text-muted-foreground/40">·</span>
          <span className="inline-flex items-center rounded-sm border border-border bg-secondary px-1 py-0 text-[9px] uppercase tracking-wide text-muted-foreground">
            {doc.sourceType}
          </span>
        </div>
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={onDelete}
        aria-label={`Supprimer le document ${doc.title}`}
        className={cn(
          "shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-secondary hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 disabled:opacity-30",
        )}
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}

function DocumentsSkeleton() {
  return (
    <div className="space-y-1.5">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="flex items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5"
        >
          <Skeleton className="size-3.5 shrink-0 rounded-sm" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-2.5 w-3/4" />
            <Skeleton className="h-2 w-1/3" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-dashed border-border bg-background/50 px-2.5 py-3 text-center">
      <p className="text-[11px] text-muted-foreground">
        Aucun document.
        <br />
        Uploadez un PDF ou un texte.
      </p>
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
    <div className="flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
      <span className="text-muted-foreground">{icon}</span>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload dialog
// ---------------------------------------------------------------------------

type SourceMode = "pdf" | "text";

function UploadDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const addDocument = useCopilotStore((s) => s.addDocument);
  const mutating = useCopilotStore((s) => s.documentMutating);

  const [title, setTitle] = React.useState("");
  const [mode, setMode] = React.useState<SourceMode>("pdf");
  const [file, setFile] = React.useState<File | null>(null);
  const [content, setContent] = React.useState("");
  const [touched, setTouched] = React.useState(false);

  // Reset form whenever the dialog closes — avoids stale state on reopen.
  React.useEffect(() => {
    if (!open) {
      const id = window.setTimeout(() => {
        setTitle("");
        setMode("pdf");
        setFile(null);
        setContent("");
        setTouched(false);
      }, 150);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  const titleValid = title.trim().length > 0;
  const pdfValid = mode === "pdf" && file != null;
  const textValid =
    mode === "text" && content.trim().length >= 10;
  const formValid = titleValid && (pdfValid || textValid);

  async function handleSubmit() {
    setTouched(true);
    if (!formValid || mutating) return;
    try {
      if (mode === "pdf" && file) {
        await addDocument({ kind: "file", title: title.trim(), file });
      } else if (mode === "text") {
        await addDocument({
          kind: "text",
          title: title.trim(),
          content: content.trim(),
        });
      }
      // Close on success — the toast confirms the indexation.
      onOpenChange(false);
    } catch {
      // The store already surfaces a toast; just leave the dialog open so
      // the user can retry without re-typing everything.
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-foreground">
            Indexer un document
          </DialogTitle>
          <DialogDescription>
            Le contenu sera découpé en chunks et vectorisé pour la recherche
            documentaire (RAG).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="doc-title" className="text-xs uppercase tracking-wide text-muted-foreground">
              Titre
            </Label>
            <Input
              id="doc-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="ex. FAQ Producteurs"
              autoFocus
            />
            {touched && !titleValid && (
              <p className="text-[11px] text-muted-foreground">
                Le titre est requis.
              </p>
            )}
          </div>

          {/* Source mode toggle */}
          <div className="space-y-1.5">
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">
              Source
            </Label>
            <div className="flex w-full items-center rounded-md border border-border p-0.5">
              <ModeButton
                active={mode === "pdf"}
                onClick={() => setMode("pdf")}
                label="Fichier PDF"
              />
              <ModeButton
                active={mode === "text"}
                onClick={() => setMode("text")}
                label="Texte"
              />
            </div>
          </div>

          {/* Source input (file picker OR textarea) */}
          {mode === "pdf" ? (
            <div className="space-y-1.5">
              <Label
                htmlFor="doc-file"
                className="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Fichier
              </Label>
              <label
                htmlFor="doc-file"
                className="flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-border bg-background px-3 py-5 text-center transition-colors hover:border-accent/50"
              >
                <Upload size={16} className="text-muted-foreground" />
                <span className="text-xs text-muted-foreground">
                  {file ? file.name : "Cliquez pour sélectionner un .pdf"}
                </span>
                <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60">
                  {file
                    ? `${(file.size / 1024).toFixed(1)} Ko`
                    : "PDF uniquement"}
                </span>
              </label>
              <input
                id="doc-file"
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  setFile(f ?? null);
                }}
              />
              {touched && !pdfValid && (
                <p className="text-[11px] text-muted-foreground">
                  Sélectionnez un fichier PDF.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label
                htmlFor="doc-content"
                className="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Contenu
              </Label>
              <Textarea
                id="doc-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Collez ici le texte du document (CGV, procédure, FAQ…)."
                className="min-h-32 font-body text-sm"
              />
              {touched && !textValid && (
                <p className="text-[11px] text-muted-foreground">
                  Le contenu doit faire au moins 10 caractères.
                </p>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={mutating}
          >
            Annuler
          </Button>
          <Button
            size="sm"
            onClick={handleSubmit}
            disabled={!formValid || mutating}
            className="gap-1.5"
          >
            <Upload size={13} />
            {mutating ? "Indexation…" : "Indexer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ModeButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex-1 rounded-[calc(var(--radius)-3px)] px-2 py-1 text-xs font-body uppercase tracking-wide transition-colors",
        active
          ? "bg-secondary text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}
