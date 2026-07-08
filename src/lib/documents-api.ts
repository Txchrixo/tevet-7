
const BACKEND_TIMEOUT = 15_000;

export interface DocumentInfo {
  id: number;
  title: string;
  source_type: string;
  created_at: string;
  chunks_count: number;
  producer_id: number | null;
}

async function fetchDocuments(tenantId?: string): Promise<DocumentInfo[]> {
  const headers: Record<string, string> = { Accept: "application/json" };

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT);
  try {
    const res = await fetch("/api/documents", { headers, signal: controller.signal });
    clearTimeout(timeout);
    if (!res.ok) return [];
    const data = await res.json();
    return data.documents ?? [];
  } catch {
    clearTimeout(timeout);
    return [];
  }
}

async function uploadDocument(
  title: string,
  sourceType: "pdf" | "text",
  file: File | null,
  content: string,
  producerId: number | null = null,
): Promise<{ document_id: number; chunks_count: number } | null> {
  const headers: Record<string, string> = {};

  const form = new FormData();
  form.append("title", title);
  form.append("source_type", sourceType);
  if (producerId != null) form.append("producer_id", String(producerId));
  if (sourceType === "pdf" && file) {
    form.append("file", file);
  } else {
    form.append("content", content);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const res = await fetch("/api/documents", {
      method: "POST",
      headers,
      body: form,
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    clearTimeout(timeout);
    return null;
  }
}

async function deleteDocument(id: number): Promise<boolean> {
  const headers: Record<string, string> = {};
  try {
    const res = await fetch(`/api/documents/${id}`, { method: "DELETE", headers });
    return res.ok;
  } catch {
    return false;
  }
}

export { fetchDocuments, uploadDocument, deleteDocument };
