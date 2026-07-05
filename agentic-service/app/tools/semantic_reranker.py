"""Semantic reranker for RAG — improves FTS5 recall with semantic matching.

Two-stage retrieval:
  1. FTS5 (BM25) — high recall, fetches candidate chunks.
  2. Semantic reranker — reranks by synonym-expanded Jaccard similarity.

Uses French business-domain synonyms (payé↔règlement, commission↔frais, etc.).
Free (no API), fast (<1ms), deterministic. Production upgrade: replace with
a real embedding model (cosine similarity).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger("tevet7.semantic_reranker")

_SYNONYMS: dict[str, set[str]] = {
    "payé": {"paiement", "règlement", "regler", "verser", "virement"},
    "paye": {"paiement", "règlement", "regler", "verser", "virement"},
    "paiement": {"payé", "paye", "règlement", "verser", "virement"},
    "règlement": {"paiement", "payé", "règle", "regler"},
    "reglement": {"paiement", "payé", "règle", "regler"},
    "commission": {"frais", "pourcentage", "taux", "prélèvement"},
    "vente": {"vendre", "vendu", "commande", "transaction"},
    "commande": {"vente", "vendre", "commander", "transaction"},
    "stock": {"inventaire", "réserve", "quantité", "disponible"},
    "rupture": {"manque", "épuise", "indisponible"},
    "retrait": {"click", "collect", "ramassage"},
    "producteur": {"fournisseur", "vendeur", "agriculteur", "exploitant"},
    "client": {"acheteur", "consommateur", "membre"},
    "catalogue": {"produit", "article", "offre", "liste"},
    "onboarding": {"inscription", "validation", "accueil", "admission"},
    "cgv": {"condition", "contrat", "règle", "term"},
    "faq": {"question", "réponse", "aide", "frequent"},
    "remboursement": {"rembourser", "retour", "annulation", "refund"},
    "litige": {"conflit", "désaccord", "plainte", "probleme"},
    "annuler": {"annulation", "supprimer", "retirer", "cancel"},
}


def _normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _tokenize(text: str) -> set[str]:
    text = _normalize(text)
    tokens = re.findall(r"[a-z0-9]{3,}", text)
    expanded: set[str] = set(tokens)
    for t in tokens:
        if t in _SYNONYMS:
            expanded.update(_SYNONYMS[t])
    return expanded


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


@dataclass
class ScoredChunk:
    chunk: dict
    score: float
    bm25_score: float


def semantic_score(question: str, chunk_content: str) -> float:
    """Synonym-expanded Jaccard similarity (0.0 - 1.0)."""
    q_tokens = _tokenize(question)
    c_tokens = _tokenize(chunk_content)
    return _jaccard(q_tokens, c_tokens)


def rerank(question: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """Rerank FTS5 results by semantic similarity. Returns top_k chunks."""
    if not chunks:
        return []
    bm25_scores = [abs(c.get("score", 0)) for c in chunks]
    max_bm25 = max(bm25_scores) if bm25_scores else 1.0
    if max_bm25 == 0:
        max_bm25 = 1.0

    scored: list[ScoredChunk] = []
    for chunk in chunks:
        content = chunk.get("content", "")
        sem = semantic_score(question, content)
        bm25_norm = abs(chunk.get("score", 0)) / max_bm25
        hybrid = 0.4 * bm25_norm + 0.6 * sem
        scored.append(ScoredChunk(chunk=chunk, score=hybrid, bm25_score=chunk.get("score", 0)))

    scored.sort(key=lambda s: s.score, reverse=True)

    result = []
    for s in scored[:top_k]:
        chunk = dict(s.chunk)
        chunk["semantic_score"] = round(s.score, 4)
        result.append(chunk)
    return result
