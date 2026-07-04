"""Startup helper — ensures the stock-shortage model is trained.

Called from ``app.main.lifespan`` after ``init_db()``. If
``ml/models/stock_shortage_model.pkl`` already exists, this is a no-op
(just logs the loaded model's metadata). If it's missing, the helper runs
``ml.train_stock_model.main`` programmatically to train + save it.

The training is synchronous (blocks app startup until done) but only runs
once per cold start when the .pkl is missing. On a typical dev box the
training takes < 5 seconds. If training fails, the helper logs a warning
and returns — the forecast tool will fall back to the SQL heuristic at
request time (see ``app.tools.forecast_tool.ForecastTool.predict``).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# When run as a script (``python3 ml/train_on_startup.py``), the parent
# directory (``agentic-service/``) is NOT on sys.path, so the sibling
# ``ml.train_stock_model`` import below would fail. Add it explicitly.
# When imported from ``app.main`` (the normal lifespan path), the parent
# is already on sys.path so this is a no-op.
_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

import joblib  # noqa: E402

from ml.train_stock_model import (  # noqa: E402
    MODEL_PATH,
    REPORT_PATH,
    build_features,
    load_dataframe,
    save_model,
    save_report,
    train_model,
)

logger = logging.getLogger("tevet7.ml.train_on_startup")


def model_exists() -> bool:
    """Return True iff the .pkl bundle exists at the expected path."""
    return MODEL_PATH.exists()


def load_metadata() -> dict | None:
    """Return the metadata dict from the .pkl bundle, or None if missing."""
    if not MODEL_PATH.exists():
        return None
    try:
        bundle = joblib.load(MODEL_PATH)
        return bundle.get("metadata") if isinstance(bundle, dict) else None
    except Exception as exc:  # noqa: BLE001 — corrupt .pkl → treat as missing
        logger.warning("Failed to load model metadata from %s: %s", MODEL_PATH, exc)
        return None


def ensure_model_trained(force_retrain: bool = False) -> bool:
    """Ensure the stock-shortage model .pkl exists. Returns True on success.

    If ``force_retrain`` is True, retrain even if the .pkl already exists
    (useful after a schema change). Otherwise the existing .pkl is reused.

    On failure (DB missing, training crash), logs a warning and returns
    False — the caller (``app.main``) continues startup so the rest of the
    service stays up. The forecast tool will then fall back to the SQL
    heuristic at request time.
    """
    if not force_retrain and model_exists():
        meta = load_metadata()
        if meta is not None:
            logger.info(
                "ML model: %s loaded (trained on %d rows, prevalence %.1f%%, "
                "F1=%.3f)",
                MODEL_PATH.name,
                meta.get("n_rows", 0),
                meta.get("prevalence", 0.0) * 100,
                _read_f1_from_report(),
            )
            return True
        # .pkl exists but is corrupt → fall through to retrain.
        logger.warning("ML model .pkl exists but is corrupt — retraining")

    try:
        df = load_dataframe()
        X, y, label_encoder = build_features(df)
        metrics, clf, metadata = train_model(X, y, label_encoder)
        save_model(clf, label_encoder, metadata)
        save_report(metrics, metadata)
        logger.info(
            "ML model trained: %s (n_rows=%d, F1=%.3f, ROC-AUC=%.3f)",
            MODEL_PATH.name,
            metadata["n_rows"],
            metrics["f1"],
            metrics["roc_auc"],
        )
        return True
    except FileNotFoundError as exc:
        logger.warning(
            "ML model NOT trained — %s. The forecast tool will fall back to "
            "the SQL heuristic. Run `python3 ml/train_stock_model.py` after "
            "starting the service once to train it.",
            exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — never crash app startup
        logger.warning(
            "ML model training failed: %s. The forecast tool will fall back "
            "to the SQL heuristic.",
            exc,
        )
        return False


def _read_f1_from_report() -> float:
    """Read the F1 score from the JSON report (best-effort, 0.0 if missing)."""
    try:
        import json

        if not REPORT_PATH.exists():
            return 0.0
        payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return float(payload.get("metrics", {}).get("f1", 0.0))
    except Exception:  # noqa: BLE001
        return 0.0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ok = ensure_model_trained(force_retrain=False)
    raise SystemExit(0 if ok else 1)
