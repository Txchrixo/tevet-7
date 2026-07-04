"""ForecastTool — ML-based stock-shortage prediction (Phase 5).

Predicts, for each product of a given producer, the probability that the
product will rupture at least once in the next ``horizon_days`` days. The
prediction is made by a ``RandomForestClassifier`` trained by
``ml.train_stock_model`` on the ``stock_history`` daily snapshots seeded
by ``app.db_seed.init_db``.

SECURITY NOTES
==============

The forecast tool enforces the **same row-level scoping** as
``SqlReadTool`` / ``RagSearchTool``:

1. The producer's ``producer_id`` is the ONLY scope value used to query
   ``stock_history`` / ``stocks`` / ``products``. It comes from the
   verified request identity (``ChatRequest.producer_id``), never from
   the user's message.
2. The ML model never sees another producer's data: features are built
   from rows WHERE ``producer_id = :producer_id``, so even a model bug
   cannot leak across producers.
3. If the model .pkl is missing or fails to load, the tool returns a
   graceful fallback message and the orchestrator falls back to the SQL
   heuristic (see ``app.agents.orchestrator._run_stock_forecast``).

DESIGN
======

The class mirrors ``RagSearchTool`` (constructor signature, ``tracer``
field, async ``predict`` entry point) so the orchestrator can construct
all three tools uniformly in ``app.api.chat``.

Tracing: every ``predict()`` call opens a Langfuse span
``forecast_predict`` with the producer_id, horizon_days, n_products, and
n_at_risk as metadata — so the Langfuse dashboard shows forecast calls
alongside SQL and RAG calls.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
from sqlalchemy import select, text

from app.db_seed import get_engine, stock_history, stocks, products, producers
from app.tracing.base import Span, TraceContext, Tracer

logger = logging.getLogger("tevet7.forecast_tool")

# ─────────────────────────────────────────────────────────────────────────────
# Path to the trained model bundle (ml/models/stock_shortage_model.pkl).
# Resolved relative to the service root so the path is stable regardless of
# the process CWD (uvicorn may run from anywhere).
# ─────────────────────────────────────────────────────────────────────────────
_SERVICE_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = _SERVICE_ROOT / "ml" / "models" / "stock_shortage_model.pkl"

# Reference "today" for the demo — matches ``app.db_seed._REFERENCE_NOW``.
# In a real deployment this would be ``datetime.now()``; in the Phase 5
# demo we fix it so the forecast sees the same day the seed ended on.
_REFERENCE_NOW = datetime(2024, 7, 15, 0, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ForecastPrediction:
    """One product-level stockout prediction."""

    product_id: int
    product_name: str
    category: str
    probability: float            # 0..1 — P(stockout in next horizon_days)
    stock_available: float        # current stocks.available
    sales_7d: float               # sum of daily_sales over last 7 days
    sales_3d: float
    sales_1d: float
    avg_sales_30d: float
    top_factor: str               # human-readable FR explanation
    is_perishable: bool
    days_since_last_stockout: int


@dataclass
class ForecastResult:
    """Structured result returned by ``ForecastTool.predict()``."""

    predictions: list[ForecastPrediction] = field(default_factory=list)
    producer_id: int = 0
    producer_name: str = ""
    horizon_days: int = 3
    latency_ms: int = 0
    model_loaded: bool = False
    n_products_evaluated: int = 0
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Top-factor heuristic — translates the model's probability into a
# human-readable FR explanation of the dominant risk driver. The mapping
# is intentionally simple (no SHAP) so it stays interpretable for the demo.
# ─────────────────────────────────────────────────────────────────────────────


def _explain_top_factor(
    *,
    sales_7d: float,
    avg_sales_30d: float,
    stock_available: float,
    is_weekend: bool,
    is_perishable: bool,
    days_since_last_stockout: int,
    month: int,
    peak_month: int | None,
) -> str:
    """Return a French label for the dominant risk factor.

    Priority (highest first):
      1. Rupture récente (days_since_last_stockout < 7)
      2. Stock faible (stock_available < 0.3 × avg_sales_30d)
      3. Ventess élevées (sales_7d > 1.5 × avg_sales_30d)
      4. Weekend (is_weekend)
      5. Produit périssable (is_perishable)
      6. Saisonnalité (month == peak_month)
      7. Tendance moyenne (fallback)
    """
    if days_since_last_stockout < 7:
        return "récurrence"
    if avg_sales_30d > 0 and stock_available < 0.3 * avg_sales_30d:
        return "stock faible"
    if avg_sales_30d > 0 and sales_7d > 1.5 * avg_sales_30d:
        return "ventes élevées"
    if is_weekend:
        return "weekend"
    if is_perishable:
        return "périssable"
    if peak_month is not None and month == peak_month:
        return "saisonnalité"
    return "tendance"


# ─────────────────────────────────────────────────────────────────────────────
# The tool
# ─────────────────────────────────────────────────────────────────────────────


class ForecastTool:
    """ML-based stock-shortage forecast tool.

    Construction (per request, mirrors ``RagSearchTool``)::

        forecast_tool = ForecastTool(
            connector=connector,            # SqliteConnector (only used for engine access)
            tenant_id="dp",
            producer_id=42,                  # None for admin
            role="producer",
            tracer=get_tracer(),
        )
        result = await forecast_tool.predict(producer_id=42, horizon_days=3)
    """

    def __init__(
        self,
        connector: Any,  # SqliteConnector (only used for engine access)
        tenant_id: str,
        producer_id: int | None,
        role: str,
        tracer: Tracer | None = None,
    ) -> None:
        self.connector = connector
        self.tenant_id = tenant_id
        self.producer_id = producer_id
        self.role = role
        self.tracer = tracer
        # Lazy-loaded model bundle ({model, feature_columns, label_encoder,
        # metadata}). ``None`` means "not yet loaded" or "failed to load".
        self._bundle: dict[str, Any] | None = None
        self._load_attempted = False

    # ───────────────────────────────────────────────────────────────────────
    # Model loading
    # ───────────────────────────────────────────────────────────────────────
    def _load_model(self) -> dict[str, Any] | None:
        """Lazy-load the .pkl bundle. Returns None on any failure."""
        if self._load_attempted:
            return self._bundle
        self._load_attempted = True
        if not MODEL_PATH.exists():
            logger.warning(
                "ForecastTool: model file %s does not exist — predict() will "
                "return a fallback message. Run `python3 ml/train_stock_model.py`.",
                MODEL_PATH,
            )
            return None
        try:
            bundle = joblib.load(MODEL_PATH)
            if not isinstance(bundle, dict) or "model" not in bundle:
                logger.warning("ForecastTool: model bundle at %s is malformed", MODEL_PATH)
                return None
            self._bundle = bundle
            logger.info(
                "ForecastTool: model loaded from %s (n_rows=%d, prevalence=%.1f%%)",
                MODEL_PATH,
                bundle.get("metadata", {}).get("n_rows", 0),
                bundle.get("metadata", {}).get("prevalence", 0.0) * 100,
            )
            return self._bundle
        except Exception as exc:  # noqa: BLE001 — never crash the chat flow
            logger.exception("ForecastTool: failed to load model from %s: %s", MODEL_PATH, exc)
            return None

    # ───────────────────────────────────────────────────────────────────────
    # Feature building for inference
    # ───────────────────────────────────────────────────────────────────────
    async def _build_inference_features(
        self, producer_id: int, horizon_days: int
    ) -> list[dict[str, Any]]:
        """Build one feature dict per product of the producer, for "today".

        Each dict has the same keys as ``ml.train_stock_model.FEATURE_COLUMNS``
        plus a few extra fields (product_id, name, category, sales_3d,
        avg_sales_30d, peak_month) used by the explanation heuristic and
        the ForecastResult.
        """
        engine = get_engine()
        today = _REFERENCE_NOW
        yesterday = today - timedelta(days=1)
        # Window edges for the rolling sales aggregates.
        win_7d_start = today - timedelta(days=7)   # inclusive of yesterday - 6
        win_3d_start = today - timedelta(days=3)
        win_30d_start = today - timedelta(days=30)
        # The stock_history rows go up to 2024-07-14 (yesterday). We query
        # daily_sales in the windows [win_Xd_start, yesterday].

        async with engine.connect() as conn:
            # 1. Load the producer's products (we forecast only for them).
            prod_rows = await conn.execute(
                select(
                    products.c.id,
                    products.c.name,
                    products.c.category,
                    products.c.producer_id,
                    products.c.is_perishable,
                    products.c.seasonality_peak_month,
                    stocks.c.available,
                )
                .select_from(products.join(stocks, stocks.c.product_id == products.c.id))
                .where(products.c.producer_id == producer_id)
                .order_by(products.c.id)
            )
            products_list = prod_rows.fetchall()
            if not products_list:
                return []

            product_ids = [r.id for r in products_list]

            # 2. Query rolling sales aggregates from stock_history. We use
            # a single SQL query with conditional SUMs to avoid N+1 round
            # trips. The :start_7d / :start_3d / :start_30d / :yesterday
            # params are bound (real values), so there's no injection risk.
            sales_sql = text(
                """
                SELECT
                    product_id,
                    COALESCE(SUM(CASE WHEN date BETWEEN :start_7d AND :yesterday
                                      THEN daily_sales ELSE 0 END), 0) AS sales_7d,
                    COALESCE(SUM(CASE WHEN date BETWEEN :start_3d AND :yesterday
                                      THEN daily_sales ELSE 0 END), 0) AS sales_3d,
                    COALESCE(SUM(CASE WHEN date = :yesterday
                                      THEN daily_sales ELSE 0 END), 0) AS sales_1d,
                    COALESCE(AVG(CASE WHEN date BETWEEN :start_30d AND :yesterday
                                      THEN daily_sales ELSE NULL END), 0) AS avg_sales_30d
                FROM stock_history
                WHERE product_id IN :product_ids
                GROUP BY product_id
                """
            )
            # SQLAlchemy text() doesn't support tuple-expansion for IN
            # directly; we expand it ourselves with unique parameter names.
            # product_ids comes from the verified producer_id scope, so
            # there's no injection risk (they're ints from the DB).
            pid_params: dict[str, Any] = {}
            pid_list_str = ",".join(f":pid_{i}" for i in range(len(product_ids)))
            for i, pid in enumerate(product_ids):
                pid_params[f"pid_{i}"] = int(pid)
            sales_sql_text = sales_sql.text.replace(":product_ids", f"({pid_list_str})")
            sales_rows = await conn.execute(
                text(sales_sql_text),
                {
                    **pid_params,
                    "start_7d": win_7d_start,
                    "start_3d": win_3d_start,
                    "start_30d": win_30d_start,
                    "yesterday": yesterday,
                },
            )
            sales_by_pid: dict[int, dict[str, float]] = {}
            for row in sales_rows.fetchall():
                sales_by_pid[int(row.product_id)] = {
                    "sales_7d": float(row.sales_7d or 0),
                    "sales_3d": float(row.sales_3d or 0),
                    "sales_1d": float(row.sales_1d or 0),
                    "avg_sales_30d": float(row.avg_sales_30d or 0),
                }

            # 3. Query days_since_last_stockout per product (days from the
            # most recent stockout_flag=1 up to yesterday). 365 if none.
            last_stockout_sql = text(
                f"""
                SELECT product_id, MAX(date) AS last_stockout_date
                FROM stock_history
                WHERE product_id IN ({pid_list_str})
                  AND stockout_flag = 1
                  AND date <= :yesterday
                GROUP BY product_id
                """
            )
            last_stockout_rows = await conn.execute(
                text(last_stockout_sql.text),
                {**pid_params, "yesterday": yesterday},
            )
            last_stockout_by_pid: dict[int, datetime] = {}
            for row in last_stockout_rows.fetchall():
                # SQLite returns the date as a string; parse it back to a
                # datetime so the timedelta arithmetic below works.
                raw = row.last_stockout_date
                if isinstance(raw, str):
                    try:
                        raw = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    except ValueError:
                        try:
                            raw = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
                        except ValueError:
                            raw = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
                if raw is None:
                    continue
                # Drop tzinfo if present (the seed writes naive UTC datetimes).
                if hasattr(raw, "replace") and raw.tzinfo is not None:
                    raw = raw.replace(tzinfo=None)
                last_stockout_by_pid[int(row.product_id)] = raw

        # 4. Assemble the feature dicts.
        bundle = self._bundle or {}
        label_encoder = bundle.get("label_encoder")
        feature_rows: list[dict[str, Any]] = []
        for p in products_list:
            sales = sales_by_pid.get(p.id, {
                "sales_7d": 0.0, "sales_3d": 0.0, "sales_1d": 0.0, "avg_sales_30d": 0.0,
            })
            last_stockout = last_stockout_by_pid.get(p.id)
            if last_stockout is not None:
                days_since = max(0, (yesterday - last_stockout).days)
            else:
                days_since = 365
            # Encode the category with the training-time label encoder.
            category = p.category or "unknown"
            try:
                if label_encoder is not None:
                    category_encoded = int(label_encoder.transform([str(category)])[0])
                else:
                    category_encoded = 0
            except Exception:  # noqa: BLE001 — unknown category → 0
                category_encoded = 0
            feature_rows.append({
                "product_id": int(p.id),
                "product_name": p.name,
                "category": category,
                "producer_id": int(p.producer_id),
                "stock_available": float(p.available or 0),
                "sales_7d": sales["sales_7d"],
                "sales_3d": sales["sales_3d"],
                "sales_1d": sales["sales_1d"],
                "avg_sales_30d": sales["avg_sales_30d"],
                "day_of_week": int(today.weekday()),
                "is_weekend": int(today.weekday() in (4, 5)),
                "month": int(today.month),
                "is_perishable": int(bool(p.is_perishable)),
                "category_encoded": category_encoded,
                "days_since_last_stockout": int(days_since),
                "seasonality_peak_month": p.seasonality_peak_month,
            })
        return feature_rows

    # ───────────────────────────────────────────────────────────────────────
    # predict()
    # ───────────────────────────────────────────────────────────────────────
    async def predict(
        self,
        producer_id: int,
        horizon_days: int = 3,
        ctx: TraceContext | None = None,
        top_k: int = 5,
    ) -> ForecastResult:
        """Run the model and return the top-k products at risk for the producer.

        Tracing: if a ``Tracer`` and ``ctx`` are provided, wraps the
        feature build + model inference in a span ``forecast_predict`` so
        Langfuse shows it alongside SQL / RAG spans.
        """
        started = time.monotonic()
        # Open a tracing span around the whole prediction.
        span: Span | None = None
        if self.tracer is not None and ctx is not None:
            span = self.tracer.start_span(
                ctx, "forecast_predict",
                producer_id=producer_id,
                horizon_days=horizon_days,
            )

        bundle = self._load_model()
        if bundle is None:
            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(
                    ctx, span, status="warning",
                    reason="model_not_loaded",
                    latency_ms=latency_ms,
                )
            return ForecastResult(
                predictions=[],
                producer_id=producer_id,
                horizon_days=horizon_days,
                latency_ms=latency_ms,
                model_loaded=False,
                n_products_evaluated=0,
                error="Modèle ML non entraîné. Lancez `python3 ml/train_stock_model.py`.",
            )

        try:
            feature_rows = await self._build_inference_features(producer_id, horizon_days)
        except Exception as exc:  # noqa: BLE001 — never crash the chat
            logger.exception("ForecastTool: feature build failed for producer=%s", producer_id)
            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(ctx, span, status="error", error=str(exc), latency_ms=latency_ms)
            return ForecastResult(
                predictions=[],
                producer_id=producer_id,
                horizon_days=horizon_days,
                latency_ms=latency_ms,
                model_loaded=True,
                n_products_evaluated=0,
                error=f"Erreur lors de la construction des features: {exc}",
            )

        if not feature_rows:
            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(
                    ctx, span, status="warning",
                    reason="no_products", latency_ms=latency_ms,
                )
            return ForecastResult(
                predictions=[],
                producer_id=producer_id,
                horizon_days=horizon_days,
                latency_ms=latency_ms,
                model_loaded=True,
                n_products_evaluated=0,
            )

        # Build the X matrix in the exact column order the model expects.
        feature_columns = bundle.get("feature_columns", [])
        if not feature_columns:
            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(ctx, span, status="error", error="missing feature_columns", latency_ms=latency_ms)
            return ForecastResult(
                predictions=[],
                producer_id=producer_id,
                horizon_days=horizon_days,
                latency_ms=latency_ms,
                model_loaded=True,
                n_products_evaluated=len(feature_rows),
                error="Modèle invalide (feature_columns manquantes).",
            )

        import pandas as pd  # local import — pandas is heavy and only needed here
        X = pd.DataFrame(feature_rows)[feature_columns]
        model = bundle["model"]
        try:
            probabilities = model.predict_proba(X)[:, 1]
        except Exception as exc:  # noqa: BLE001
            logger.exception("ForecastTool: model.predict_proba failed")
            latency_ms = int((time.monotonic() - started) * 1000)
            if span is not None and self.tracer is not None:
                self.tracer.end_span(ctx, span, status="error", error=str(exc), latency_ms=latency_ms)
            return ForecastResult(
                predictions=[],
                producer_id=producer_id,
                horizon_days=horizon_days,
                latency_ms=latency_ms,
                model_loaded=True,
                n_products_evaluated=len(feature_rows),
                error=f"Erreur lors de l'inférence ML: {exc}",
            )

        # Build the prediction list, sort by probability descending, take top_k.
        predictions: list[ForecastPrediction] = []
        for row, proba in zip(feature_rows, probabilities):
            top_factor = _explain_top_factor(
                sales_7d=row["sales_7d"],
                avg_sales_30d=row["avg_sales_30d"],
                stock_available=row["stock_available"],
                is_weekend=bool(row["is_weekend"]),
                is_perishable=bool(row["is_perishable"]),
                days_since_last_stockout=row["days_since_last_stockout"],
                month=row["month"],
                peak_month=row.get("seasonality_peak_month"),
            )
            predictions.append(ForecastPrediction(
                product_id=row["product_id"],
                product_name=row["product_name"],
                category=row["category"],
                probability=float(proba),
                stock_available=row["stock_available"],
                sales_7d=row["sales_7d"],
                sales_3d=row["sales_3d"],
                sales_1d=row["sales_1d"],
                avg_sales_30d=row["avg_sales_30d"],
                top_factor=top_factor,
                is_perishable=bool(row["is_perishable"]),
                days_since_last_stockout=row["days_since_last_stockout"],
            ))
        predictions.sort(key=lambda p: p.probability, reverse=True)
        top_predictions = predictions[:top_k]

        # Look up the producer's display name (for the answer header).
        producer_name = ""
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                r = await conn.execute(
                    select(producers.c.display_name).where(producers.c.id == producer_id)
                )
                row = r.fetchone()
                if row is not None:
                    producer_name = row.display_name
        except Exception:  # noqa: BLE001
            pass

        latency_ms = int((time.monotonic() - started) * 1000)
        n_at_risk = sum(1 for p in predictions if p.probability >= 0.5)
        if span is not None and self.tracer is not None:
            self.tracer.end_span(
                ctx, span, status="ok",
                n_products=len(feature_rows),
                n_at_risk=n_at_risk,
                top_probability=(top_predictions[0].probability if top_predictions else 0.0),
                latency_ms=latency_ms,
            )
        return ForecastResult(
            predictions=top_predictions,
            producer_id=producer_id,
            producer_name=producer_name,
            horizon_days=horizon_days,
            latency_ms=latency_ms,
            model_loaded=True,
            n_products_evaluated=len(feature_rows),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: render a ForecastResult as the markdown answer shown to the
# user. Used by ``app.agents.orchestrator._run_stock_forecast``.
# ─────────────────────────────────────────────────────────────────────────────


def render_forecast_answer(result: ForecastResult, model_meta: dict[str, Any] | None = None) -> str:
    """Build the French markdown answer for a forecast result.

    The format mirrors the Phase 5 spec::

        **Prévisions de rupture de stock** — 3 prochains jours (Ferme du Vallon)

        3 produits à risque selon le modèle ML :

        1. **Tomates cœur de bœuf** — 82% de risque
           Stock actuel : 18 unités · Ventes 7j : 142 · Facteur principal : ventes élevées
        2. **Salade laitue** — 67% de risque
           Stock actuel : 8 unités · Ventes 7j : 76 · Facteur principal : stock faible
        3. **Courgettes** — 45% de risque
           Stock actuel : 12 unités · Ventes 7j : 98 · Facteur principal : weekend

        Le modèle RandomForest (100 arbres) a été entraîné sur 90 jours d'historique.
    """
    if not result.model_loaded:
        return (
            "Modèle ML non entraîné. Lancez `python3 ml/train_stock_model.py` pour "
            "activer les prévisions de rupture de stock."
        )
    if result.error:
        return f"Le modèle ML n'a pas pu produire de prévision : {result.error}"
    if not result.predictions:
        return (
            f"Aucun produit à risque de rupture sur les {result.horizon_days} prochains jours. "
            "Vos stocks sont confortables."
        )
    producer_label = result.producer_name or f"producteur #{result.producer_id}"
    n_risk = len(result.predictions)
    lines: list[str] = [
        f"**Prévisions de rupture de stock** — {result.horizon_days} prochains jours ({producer_label})",
        "",
        f"{n_risk} produit{'s' if n_risk > 1 else ''} à risque selon le modèle ML :",
        "",
    ]
    factor_label_map = {
        "récurrence": "récurrence de rupture",
        "stock faible": "stock faible",
        "ventes élevées": "ventes élevées",
        "weekend": "effet weekend",
        "périssable": "produit périssable",
        "saisonnalité": "pic saisonnier",
        "tendance": "tendance générale",
    }
    for i, p in enumerate(result.predictions, start=1):
        pct = int(round(p.probability * 100))
        factor_label = factor_label_map.get(p.top_factor, p.top_factor)
        stock_int = int(round(p.stock_available))
        sales_7d_int = int(round(p.sales_7d))
        lines.append(f"{i}. **{p.product_name}** — {pct} % de risque")
        lines.append(
            f"   Stock actuel : {stock_int} unités · Ventes 7j : {sales_7d_int} "
            f"· Facteur principal : {factor_label}"
        )
    # Footer: model provenance.
    n_train_rows = (model_meta or {}).get("n_rows", 0)
    n_trees = (model_meta or {}).get("model_params", {}).get("n_estimators", 100)
    lines.append("")
    lines.append(
        f"Le modèle RandomForest ({n_trees} arbres) a été entraîné sur "
        f"{n_train_rows} lignes d'historique (90 jours × 7 producteurs)."
    )
    return "\n".join(lines)


def render_forecast_chart(result: ForecastResult) -> dict[str, Any] | None:
    """Build a bar chart spec for the top-k predictions (or None if empty).

    The chart shows the probability of rupture per product so the inspector
    UI can render a visual alongside the markdown answer.
    """
    if not result.predictions:
        return None
    return {
        "type": "bar",
        "title": f"Risque de rupture — {result.horizon_days} prochains jours",
        "xKey": "product_name",
        "series": [
            {
                "key": "probability",
                "label": "Probabilité de rupture (%)",
                "color": "#C0504D",
            },
        ],
        "data": [
            {
                "product_name": p.product_name,
                "probability": round(p.probability * 100, 1),
            }
            for p in result.predictions
        ],
        "unit": "%",
    }
