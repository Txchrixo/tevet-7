#!/usr/bin/env python3
"""Train the RandomForest stock-shortage classifier — Phase 5.

Standalone script (also called programmatically by
``ml.train_on_startup.ensure_model_trained``). Loads the daily
``stock_history`` snapshots seeded by ``app/db_seed.init_db`` and trains a
binary classifier that predicts, for each (product, today) row, the
probability that the product will rupture at least once in the next 3 days.

Pipeline
--------
1. Load ``stock_history`` + ``products`` from the SQLite database at
   ``dev.db`` into pandas DataFrames.
2. Build the feature matrix per ``(product_id, date)`` row:
   - ``sales_7d``  — sum of ``daily_sales`` for the same product over the
     last 7 days ending yesterday.
   - ``sales_3d``  — same, last 3 days.
   - ``sales_1d``  — yesterday's ``daily_sales``.
   - ``stock_available`` — the row's start-of-day ``available`` stock.
   - ``day_of_week``  — 0..6 (Mon..Sun).
   - ``is_weekend``   — 1 if Fri(4) or Sat(5).
   - ``month``        — 1..12.
   - ``is_perishable`` — from ``products.is_perishable``.
   - ``category_encoded`` — label-encoded ``products.category``.
   - ``producer_id``  — from ``products.producer_id`` (denormalised).
   - ``days_since_last_stockout`` — rolling count of days since the last
     ``stockout_flag=True`` for the same product (large value when no
     rupture has been observed yet).
   - ``avg_sales_30d`` — rolling mean of ``daily_sales`` over the last
     30 days ending yesterday.
3. Compute the target ``stockout_next_3d = 1`` if any of ``date+1``,
   ``date+2``, ``date+3`` has ``stockout_flag=True`` for the same product,
   else 0. Drop the last 3 days per product (no observable target).
4. Train/test split: 80/20, ``stratify=target``.
5. Train ``RandomForestClassifier(n_estimators=100, max_depth=8,
   class_weight='balanced', random_state=42)``.
6. Evaluate: accuracy, precision, recall, F1, ROC-AUC, confusion matrix.
7. Persist the bundle to ``ml/models/stock_shortage_model.pkl`` (joblib)
   and the metrics to ``ml/models/training_report.json``.
8. Print a clear summary to stdout (top-10 feature importances, headline
   metrics, dataset size, class balance).

Reproducibility
---------------
``random_state=42`` is set on both the RandomForest and the train/test
split. The seed itself uses a fixed PRNG (``random.Random(20240601)``) so
the stock_history data is identical across runs.

Usage
-----
::

    cd agentic-service
    python3 ml/train_stock_model.py

The script is idempotent: re-running overwrites the .pkl + report. If the
SQLite database is missing or empty, the script exits with code 1.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger("tevet7.ml.train")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

# Resolve relative to this file so the script works from any CWD.
_SERVICE_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _SERVICE_ROOT / "dev.db"
MODELS_DIR = _SERVICE_ROOT / "ml" / "models"
MODEL_PATH = MODELS_DIR / "stock_shortage_model.pkl"
REPORT_PATH = MODELS_DIR / "training_report.json"

# The 12 feature columns the model is trained on. The forecast tool must
# produce these exact columns in this exact order at inference time.
FEATURE_COLUMNS: list[str] = [
    "sales_7d",
    "sales_3d",
    "sales_1d",
    "stock_available",
    "day_of_week",
    "is_weekend",
    "month",
    "is_perishable",
    "category_encoded",
    "producer_id",
    "days_since_last_stockout",
    "avg_sales_30d",
]

TARGET_COLUMN = "stockout_next_3d"
RANDOM_STATE = 42


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────


def load_dataframe(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Load ``stock_history`` joined with ``products`` into a DataFrame.

    Returns one row per ``(product_id, date)`` with the product's
    ``category`` / ``is_perishable`` / ``producer_id`` denormalised so the
    feature builder doesn't need a second round-trip.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"SQLite database not found at {db_path}. "
            "Run `python3 -c 'import asyncio; from app.db_seed import init_db; asyncio.run(init_db())'` first."
        )
    conn = sqlite3.connect(str(db_path))
    try:
        df = pd.read_sql_query(
            """
            SELECT
                sh.id,
                sh.producer_id,
                sh.product_id,
                sh.date           AS snapshot_date,
                sh.stock_level,
                sh.reserved,
                sh.available,
                sh.daily_sales,
                sh.restocked_qty,
                sh.stockout_flag,
                sh.day_of_week,
                sh.is_weekend,
                sh.month,
                p.category        AS category,
                p.is_perishable   AS is_perishable,
                p.base_popularity AS base_popularity,
                p.seasonality_peak_month AS seasonality_peak_month
            FROM stock_history sh
            JOIN products p ON p.id = sh.product_id
            ORDER BY sh.product_id, sh.date
            """,
            conn,
            parse_dates=["snapshot_date"],
        )
    finally:
        conn.close()

    if df.empty:
        raise ValueError(
            f"stock_history table is empty at {db_path}. "
            "Run `python3 -c 'import asyncio; from app.db_seed import init_db; asyncio.run(init_db())'` first."
        )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering
# ─────────────────────────────────────────────────────────────────────────────


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, LabelEncoder]:
    """Build the feature matrix ``X`` and target vector ``y`` from the
    loaded stock_history DataFrame.

    Returns ``(X, y, label_encoder)``. The label encoder is fit on the
    ``category`` column so the forecast tool can encode new categories at
    inference time (it's saved alongside the model in the .pkl bundle).
    """
    # Ensure dtypes are right (booleans → ints for the model).
    df = df.copy()
    df["is_perishable"] = df["is_perishable"].astype(int)
    df["is_weekend"] = df["is_weekend"].astype(int)
    df["stockout_flag"] = df["stockout_flag"].astype(int)
    df["daily_sales"] = df["daily_sales"].astype(float)
    # Rename to match FEATURE_COLUMNS (the SQL query uses ``available`` but
    # the model expects ``stock_available`` — clearer name for inference).
    df = df.rename(columns={"available": "stock_available"})
    df["stock_available"] = df["stock_available"].astype(float)

    # Sort by product + date so rolling windows are well-defined.
    df = df.sort_values(["product_id", "snapshot_date"]).reset_index(drop=True)

    # ── Rolling sales features ──
    # We want sales_7d = sum of daily_sales over the 7 days ENDING YESTERDAY
    # (so the row's own daily_sales isn't included — that would be a
    # target leak, since daily_sales today determines whether stock_level
    # goes negative today). Using ``shift(1)`` then rolling on the shifted
    # series gives us "yesterday and the 6 days before" = 7-day trailing
    # window ending yesterday.
    grouped = df.groupby("product_id", group_keys=False)
    shifted_sales = grouped["daily_sales"].shift(1)
    df["sales_1d"] = shifted_sales.fillna(0.0)
    df["sales_3d"] = (
        grouped["daily_sales"]
        .shift(1)
        .rolling(3, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .fillna(0.0)
    )
    df["sales_7d"] = (
        grouped["daily_sales"]
        .shift(1)
        .rolling(7, min_periods=1)
        .sum()
        .reset_index(level=0, drop=True)
        .fillna(0.0)
    )
    df["avg_sales_30d"] = (
        grouped["daily_sales"]
        .shift(1)
        .rolling(30, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
        .fillna(0.0)
    )

    # ── days_since_last_stockout ──
    # For each product, count days since the most recent stockout_flag=1
    # (as of the previous day, to avoid leaking today's target).
    df["prev_stockout"] = grouped["stockout_flag"].shift(1).fillna(0).astype(int)
    # Cumulative count of stockouts seen so far (up to yesterday).
    df["cum_stockouts"] = (
        df.groupby("product_id")["prev_stockout"].cumsum()
    )
    # For each product, find the index of the last stockout (up to yesterday).
    # We compute "days since last stockout" as the row number difference.
    df["row_in_product"] = df.groupby("product_id").cumcount()
    # last_stockout_row = the row_in_product of the most recent prev_stockout=1
    # (or -1 if none). We compute it via a running max on (row_in_product
    # where prev_stockout=1, else -1).
    df["last_stockout_row"] = df["row_in_product"].where(df["prev_stockout"] == 1, -1)
    df["last_stockout_row"] = df.groupby("product_id")["last_stockout_row"].cummax()
    df["days_since_last_stockout"] = df["row_in_product"] - df["last_stockout_row"]
    # When no stockout has been seen yet, last_stockout_row=-1, so days_since
    # becomes row_in_product + 1 — that's fine (a large-ish number that
    # monotonically increases). Cap at 365 so the model doesn't see absurd
    # values for very old products.
    df["days_since_last_stockout"] = (
        df["days_since_last_stockout"].clip(upper=365).fillna(365).astype(int)
    )

    # ── category_encoded ──
    label_encoder = LabelEncoder()
    label_encoder.fit(df["category"].astype(str))
    df["category_encoded"] = label_encoder.transform(df["category"].astype(str))

    # ── target: stockout in the next 3 days ──
    # For each (product, date), check if stockout_flag=1 in any of date+1,
    # date+2, date+3. We compute this by shifting stockout_flag backwards
    # by 1, 2, 3 within each product and ORing the results.
    next1 = grouped["stockout_flag"].shift(-1)
    next2 = grouped["stockout_flag"].shift(-2)
    next3 = grouped["stockout_flag"].shift(-3)
    df["stockout_next_3d"] = (
        (next1.fillna(0).astype(int) == 1)
        | (next2.fillna(0).astype(int) == 1)
        | (next3.fillna(0).astype(int) == 1)
    ).astype(int)

    # Drop rows where the target is NaN (the last 3 days per product — no
    # observable future).
    df = df.dropna(subset=["stockout_next_3d"]).reset_index(drop=True)
    # Also drop rows where sales_7d is NaN (first day per product — no
    # history). The .fillna(0.0) above already handles this, but be safe.
    df = df.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)

    X = df[FEATURE_COLUMNS].copy()
    y = df[TARGET_COLUMN].astype(int).copy()
    return X, y, label_encoder


# ─────────────────────────────────────────────────────────────────────────────
# Training
# ─────────────────────────────────────────────────────────────────────────────


def train_model(
    X: pd.DataFrame,
    y: pd.Series,
    label_encoder: LabelEncoder,
) -> tuple[dict, RandomForestClassifier, dict]:
    """Train the RandomForest, evaluate it, and return
    ``(metrics, model, metadata)``.

    ``metadata`` is the bundle dict saved to the .pkl (model + feature
    columns + label encoder + training metadata).
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    logger.info(
        "Train/test split: train=%d (positive=%d, %.1f%%), test=%d (positive=%d, %.1f%%)",
        len(X_train),
        int(y_train.sum()),
        100.0 * y_train.mean(),
        len(X_test),
        int(y_test.sum()),
        100.0 * y_test.mean(),
    )

    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=8,
        class_weight="balanced",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    y_proba = clf.predict_proba(X_test)[:, 1]

    # Metrics.
    accuracy = float(accuracy_score(y_test, y_pred))
    precision = float(precision_score(y_test, y_pred, zero_division=0))
    recall = float(recall_score(y_test, y_pred, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))
    try:
        roc_auc = float(roc_auc_score(y_test, y_proba))
    except ValueError:
        # ROC-AUC is undefined when y_test has only one class.
        roc_auc = float("nan")
    cm = confusion_matrix(y_test, y_pred).tolist()
    clf_report = classification_report(
        y_test, y_pred, zero_division=0, output_dict=True
    )

    # Feature importances (top 10).
    importances = list(zip(FEATURE_COLUMNS, clf.feature_importances_))
    importances.sort(key=lambda x: x[1], reverse=True)
    top_features = [
        {"feature": name, "importance": float(imp)}
        for name, imp in importances[:10]
    ]
    all_features = [
        {"feature": name, "importance": float(imp)}
        for name, imp in importances
    ]

    metrics = {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "roc_auc": roc_auc,
        "confusion_matrix": cm,
        "classification_report": clf_report,
        "top_features": top_features,
        "all_features": all_features,
    }

    metadata = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(X)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "prevalence": float(y.mean()),
        "feature_columns": FEATURE_COLUMNS,
        "model_params": {
            "n_estimators": 100,
            "max_depth": 8,
            "class_weight": "balanced",
            "random_state": RANDOM_STATE,
        },
        "categories": list(label_encoder.classes_),
    }

    return metrics, clf, metadata


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


def save_model(
    clf: RandomForestClassifier,
    label_encoder: LabelEncoder,
    metadata: dict,
    model_path: Path = MODEL_PATH,
) -> None:
    """Save the model bundle to ``model_path`` (joblib)."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": clf,
        "feature_columns": FEATURE_COLUMNS,
        "label_encoder": label_encoder,
        "metadata": metadata,
    }
    joblib.dump(bundle, model_path)
    logger.info("Model saved to %s (%.1f KB)", model_path, model_path.stat().st_size / 1024)


def save_report(metrics: dict, metadata: dict, report_path: Path = REPORT_PATH) -> None:
    """Save the metrics + metadata to ``report_path`` (JSON)."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"metadata": metadata, "metrics": metrics}
    report_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info("Training report saved to %s", report_path)


# ─────────────────────────────────────────────────────────────────────────────
# Summary printer
# ─────────────────────────────────────────────────────────────────────────────


def print_summary(metrics: dict, metadata: dict) -> None:
    """Print a clear, scannable summary to stdout."""
    print()
    print("=" * 72)
    print("Tevet-7 — Stock Shortage Model Training Summary (Phase 5)")
    print("=" * 72)
    print(f"  Dataset:        {metadata['n_rows']} rows "
          f"({metadata['n_train']} train + {metadata['n_test']} test)")
    print(f"  Class balance:  {metadata['prevalence']*100:.1f}% positive "
          f"(stockout in next 3 days)")
    print(f"  Model:          RandomForestClassifier "
          f"(n_estimators={metadata['model_params']['n_estimators']}, "
          f"max_depth={metadata['model_params']['max_depth']}, "
          f"class_weight='{metadata['model_params']['class_weight']}')")
    print()
    print("  Metrics (test set):")
    print(f"    Accuracy:  {metrics['accuracy']:.4f}")
    print(f"    Precision: {metrics['precision']:.4f}")
    print(f"    Recall:    {metrics['recall']:.4f}")
    print(f"    F1:        {metrics['f1']:.4f}")
    print(f"    ROC-AUC:   {metrics['roc_auc']:.4f}")
    print()
    print("  Confusion matrix [[TN, FP], [FN, TP]]:")
    cm = metrics["confusion_matrix"]
    print(f"    TN={cm[0][0]:>5}  FP={cm[0][1]:>5}")
    print(f"    FN={cm[1][0]:>5}  TP={cm[1][1]:>5}")
    print()
    print("  Top 10 feature importances:")
    for i, f in enumerate(metrics["top_features"], start=1):
        print(f"    {i:>2}. {f['feature']:<28} {f['importance']:.4f}")
    print()
    print("=" * 72)
    # The headline F1 — operators scan for this line.
    print(f"  HEADLINE F1 = {metrics['f1']:.4f} "
          f"({'PASS' if metrics['f1'] > 0.40 else 'FAIL — needs > 0.40'})")
    print("=" * 72)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Load data, train, evaluate, save, print summary. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        df = load_dataframe()
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Cannot load training data: %s", exc)
        return 1
    logger.info(
        "Loaded %d stock_history rows (%d products, %d producers)",
        len(df),
        df["product_id"].nunique(),
        df["producer_id"].nunique(),
    )

    X, y, label_encoder = build_features(df)
    logger.info(
        "Built feature matrix: %d rows × %d cols, %d positive examples (%.1f%%)",
        len(X), len(FEATURE_COLUMNS), int(y.sum()), 100.0 * y.mean(),
    )

    metrics, clf, metadata = train_model(X, y, label_encoder)
    save_model(clf, label_encoder, metadata)
    save_report(metrics, metadata)
    print_summary(metrics, metadata)
    return 0


if __name__ == "__main__":
    sys.exit(main())
