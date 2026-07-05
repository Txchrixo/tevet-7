"""Tests for Phase A5 — Semantic reranker for RAG."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTIC = Path(__file__).resolve().parent.parent
if str(_AGENTIC) not in sys.path:
    sys.path.insert(0, str(_AGENTIC))

import pytest

from app.tools.semantic_reranker import (
    _jaccard,
    _normalize,
    _tokenize,
    rerank,
    semantic_score,
)


def test_normalize_strips_accents() -> None:
    assert _normalize("éàù") == "eau"


def test_tokenize_drops_short_tokens() -> None:
    tokens = _tokenize("le paiement de la vente")
    assert "le" not in tokens
    assert "paiement" in tokens


def test_tokenize_expands_synonyms() -> None:
    tokens = _tokenize("comment suis-je payé")
    assert "paiement" in tokens


def test_jaccard_identical() -> None:
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_disjoint() -> None:
    assert _jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial() -> None:
    assert _jaccard({"a", "b", "c"}, {"a", "b", "d"}) == 0.5


def test_semantic_score_identical() -> None:
    assert semantic_score("paiement des ventes", "paiement des ventes") == 1.0


def test_semantic_score_synonym_match() -> None:
    score = semantic_score("quand suis-je payé", "le règlement des ventes")
    assert score > 0.0


def test_rerank_empty() -> None:
    assert rerank("q", []) == []


def test_rerank_returns_top_k() -> None:
    chunks = [{"content": f"chunk {i}", "score": -1.0 * i} for i in range(10)]
    assert len(rerank("chunk 5", chunks, top_k=3)) == 3


def test_rerank_orders_by_relevance() -> None:
    question = "comment suis-je payé"
    chunks = [
        {"content": "le règlement des ventes se fait par virement", "score": -2.0},
        {"content": "les tomates sont rouges", "score": -1.0},
        {"content": "le paiement est effectué chaque mois", "score": -3.0},
    ]
    result = rerank(question, chunks, top_k=3)
    contents = [r["content"] for r in result]
    assert "les tomates sont rouges" == contents[-1]


def test_rerank_adds_semantic_score() -> None:
    chunks = [{"content": "test", "score": -1.0}]
    result = rerank("test", chunks, top_k=1)
    assert "semantic_score" in result[0]
