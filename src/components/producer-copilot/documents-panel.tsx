"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/lib/store";
import { fetchDocuments, uploadDocument, deleteDocument, type DocumentInfo } from "@/lib/documents-api";
import { FileText, Trash, Upload, X } from "@/components/ui/feather-icons";
import { toast } from "sonner";

export function DocumentsPanel() {
  const identity = useCopilotStore((s) => s.identity);
  const [docs, setDocs] = React.useState<DocumentInfo[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showUpload, setShowUpload] = React.useState(false);
  const [title, setTitle] = React.useState("");
  const [textContent, setTextContent] = React.useState("");
  const [uploading, setUploading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    const result = await fetchDocuments();
    setDocs(result);
    setLoading(false);
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const handleUpload = async () => {
    if (!title.trim() || !textContent.trim()) return;
    setUploading(true);
    const result = await uploadDocument(title.trim(), "text", null, textContent.trim(), identity.producerId);
    setUploading(false);
    if (result) {
      toast.success(`Document indexé (${result.chunks_count} chunks)`);
      setTitle("");
      setTextContent("");
      setShowUpload(false);
      void load();
    } else {
      toast.error("Échec de l'upload du document");
    }
  };

  const handleDelete = async (id: number) => {
    const ok = await deleteDocument(id);
    if (ok) {
      toast.success("Document supprimé");
      void load();
    } else {
      toast.error("Échec de la suppression");
    }
  };

  return (
    <section>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-body font-medium uppercase tracking-wide text-muted-foreground">
          <FileText size={12} className="text-muted-foreground" />
          Documents
        </div>
        <button
          type="button"
          onClick={() => setShowUpload(!showUpload)}
          className="flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:border-accent/50 hover:text-foreground"
        >
          <Upload size={10} />
          Uploader
        </button>
      </div>

      {showUpload && (
        <div className="mt-2 space-y-2 rounded-md border border-border bg-background p-2.5">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Titre du document"
            className="w-full rounded border border-border bg-transparent px-2 py-1 text-xs text-foreground outline-none placeholder:text-muted-foreground"
          />
          <textarea
            value={textContent}
            onChange={(e) => setTextContent(e.target.value)}
            placeholder="Collez le texte du document ici..."
            rows={4}
            className="w-full rounded border border-border bg-transparent px-2 py-1 text-xs text-foreground outline-none placeholder:text-muted-foreground resize-none"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleUpload}
              disabled={uploading || !title.trim() || !textContent.trim()}
              className="flex-1 rounded bg-primary px-2 py-1 text-[11px] text-foreground transition-colors hover:bg-accent disabled:opacity-50"
            >
              {uploading ? "Indexation…" : "Indexer"}
            </button>
            <button
              type="button"
              onClick={() => setShowUpload(false)}
              className="rounded border border-border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              Annuler
            </button>
          </div>
        </div>
      )}

      <div className="mt-2 space-y-1.5">
        {loading ? (
          <p className="text-[10px] text-muted-foreground">Chargement…</p>
        ) : docs.length === 0 ? (
          <p className="text-[10px] text-muted-foreground">Aucun document. Uploadez un texte.</p>
        ) : (
          docs.map((doc) => (
            <div
              key={doc.id}
              className="group flex items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5"
            >
              <FileText size={12} className="shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium text-foreground">{doc.title}</div>
                <div className="text-[10px] text-muted-foreground">{doc.chunks_count} chunks</div>
              </div>
              <button
                type="button"
                onClick={() => handleDelete(doc.id)}
                className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
              >
                <Trash size={12} />
              </button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
