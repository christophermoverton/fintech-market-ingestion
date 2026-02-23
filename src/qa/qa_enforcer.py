# src/qa/qa_enforcer.py
"""
QA Enforcer (Strict Mode)

This module converts QA outputs from observational reporting into enforceable
pipeline guardrails.

It is designed to work with your existing QA Summary Export artifacts:

artifacts/qa/<run_dir>/
  - qa_summary_by_symbol.csv
  - qa_summary_global.csv

Where <run_dir> looks like:
  - qa_bars_1m_1Min_<start>_<end>_<exchange>
  - qa_bars_daily_1D_<start>_<end>_<exchange>

CSV Schemas (as provided)
-------------------------
qa_summary_by_symbol.csv header:
  run_id,dataset_name,bar_interval,symbol,start_ts,end_ts,rows_observed,expected_bars,
  coverage_pct,duplicate_rows,duplicate_keys,gap_count,gap_segments,max_gap_len,
  ohlc_violation_count,first_ts,last_ts,notes

qa_summary_global.csv header:
  run_id,dataset_name,bar_interval,start_ts,end_ts,total_rows,unique_rows,duplicate_rows,
  symbols_expected,symbols_present,symbols_missing,total_gap_count,total_ohlc_violation_count,
  pct_symbols_below_coverage_threshold,coverage_threshold,overall_status

Strict Mode Contract
--------------------
If strict mode is enabled and any configured threshold is exceeded:
  - Print a CI-friendly failure summary
  - Optionally log the same summary
  - Exit non-zero via SystemExit(1)

Design Principle
----------------
- qa_metrics.py   : compute metrics
- qa_export.py    : export summaries (CSV)
- qa_enforcer.py  : enforce thresholds (this module)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd


# -----------------------------
# Data structures / contracts
# -----------------------------

@dataclass(frozen=True)
class Thresholds:
    """Configurable strict-mode thresholds."""
    max_duplicate_keys: int = 0
    max_ohlc_violations: int = 0

    # Optional / future expansions
    min_coverage_pct: Optional[float] = None  # e.g., 0.995
    max_gap_count: Optional[int] = None
    allow_missing_symbols: bool = True


@dataclass(frozen=True)
class SymbolOffense:
    """Per-symbol breakdown for CI-friendly summaries."""
    symbol: str
    duplicate_keys: int = 0
    ohlc_violations: int = 0
    gap_count: int = 0
    coverage_pct: Optional[float] = None


@dataclass(frozen=True)
class QAMetrics:
    """
    Minimal interface for enforcement, aligned to your exported schema.
    """
    dataset: str
    timeframe: str  # e.g. "1Min" or "1D"
    start: str
    end: str

    total_duplicate_keys: int
    total_ohlc_violations: int

    # Optional totals (future expansions)
    total_gap_count: Optional[int] = None
    min_coverage_pct_observed: Optional[float] = None
    missing_symbols: Optional[List[str]] = None

    # Per-symbol breakdown (keyed by symbol)
    by_symbol: Optional[Dict[str, SymbolOffense]] = None


@dataclass(frozen=True)
class EnforcerResult:
    """Structured result to support CLI printing and unit tests."""
    passed: bool
    reasons: List[str]
    exit_code: int
    top_offenders: List[SymbolOffense]


# -----------------------------
# Public API
# -----------------------------

def enforce(
    metrics: QAMetrics,
    strict: bool,
    thresholds: Thresholds,
    *,
    top_n: int = 10,
    logger=None,
) -> EnforcerResult:
    """
    Enforce QA thresholds.

    Returns an EnforcerResult (suitable for tests). If strict=True and failing,
    the returned exit_code will be 1, but this function will not exit by itself.
    Use enforce_or_exit() to enforce process termination in CLI contexts.
    """
    reasons: List[str] = []

    # --- Required checks (P1) ---
    if metrics.total_duplicate_keys > thresholds.max_duplicate_keys:
        reasons.append(
            f"Duplicate keys: {metrics.total_duplicate_keys} "
            f"(threshold: {thresholds.max_duplicate_keys})"
        )

    if metrics.total_ohlc_violations > thresholds.max_ohlc_violations:
        reasons.append(
            f"OHLC violations: {metrics.total_ohlc_violations} "
            f"(threshold: {thresholds.max_ohlc_violations})"
        )

    # --- Optional expansions ---
    if thresholds.max_gap_count is not None and metrics.total_gap_count is not None:
        if metrics.total_gap_count > thresholds.max_gap_count:
            reasons.append(
                f"Gap count: {metrics.total_gap_count} "
                f"(threshold: {thresholds.max_gap_count})"
            )

    if thresholds.min_coverage_pct is not None and metrics.min_coverage_pct_observed is not None:
        if metrics.min_coverage_pct_observed < thresholds.min_coverage_pct:
            reasons.append(
                f"Min coverage pct observed: {metrics.min_coverage_pct_observed:.6f} "
                f"(min required: {thresholds.min_coverage_pct:.6f})"
            )

    if not thresholds.allow_missing_symbols and metrics.missing_symbols:
        reasons.append(f"Missing expected symbols: {len(metrics.missing_symbols)}")

    passed = len(reasons) == 0

    top_offenders = _rank_top_offenders(metrics.by_symbol, top_n=top_n)

    exit_code = 0
    if strict and not passed:
        exit_code = 1

    result = EnforcerResult(
        passed=passed,
        reasons=reasons,
        exit_code=exit_code,
        top_offenders=top_offenders,
    )

    _emit_summary(metrics, result, strict=strict, thresholds=thresholds, logger=logger)
    return result


def enforce_or_exit(
    metrics: QAMetrics,
    strict: bool,
    thresholds: Thresholds,
    *,
    top_n: int = 10,
    logger=None,
) -> EnforcerResult:
    """
    CLI-friendly wrapper: raises SystemExit(exit_code) when strict is enabled and failing.
    """
    result = enforce(metrics, strict, thresholds, top_n=top_n, logger=logger)
    if result.exit_code != 0:
        raise SystemExit(result.exit_code)
    return result


def enforce_from_artifacts_dir(
    artifacts_run_dir: Union[str, Path],
    *,
    dataset: str,
    timeframe: str,
    start: str,
    end: str,
    strict: bool,
    thresholds: Thresholds,
    top_n: int = 10,
    logger=None,
) -> EnforcerResult:
    """
    Load QA metrics from artifacts/qa/<run_dir> exports and enforce thresholds.

    artifacts_run_dir should be a directory containing:
      - qa_summary_global.csv
      - qa_summary_by_symbol.csv
    """
    artifacts_run_dir = Path(artifacts_run_dir)
    global_csv = artifacts_run_dir / "qa_summary_global.csv"
    by_symbol_csv = artifacts_run_dir / "qa_summary_by_symbol.csv"

    metrics = load_metrics_from_exports(
        global_csv=global_csv,
        by_symbol_csv=by_symbol_csv,
        dataset=dataset,
        timeframe=timeframe,
        start=start,
        end=end,
    )

    return enforce_or_exit(
        metrics,
        strict=strict,
        thresholds=thresholds,
        top_n=top_n,
        logger=logger,
    )


def load_metrics_from_exports(
    *,
    global_csv: Union[str, Path],
    by_symbol_csv: Union[str, Path],
    dataset: str,
    timeframe: str,
    start: str,
    end: str,
) -> QAMetrics:
    """
    Build QAMetrics from your existing CSV exports.
    """
    global_csv = Path(global_csv)
    by_symbol_csv = Path(by_symbol_csv)

    if not global_csv.exists():
        raise FileNotFoundError(f"Missing QA global export: {global_csv}")
    if not by_symbol_csv.exists():
        raise FileNotFoundError(f"Missing QA by-symbol export: {by_symbol_csv}")

    gdf = pd.read_csv(global_csv)
    if len(gdf) != 1:
        raise ValueError(f"Expected 1 row in {global_csv.name}, found {len(gdf)}")

    grow = gdf.iloc[0].to_dict()

    bsdf = pd.read_csv(by_symbol_csv)

    # Per-symbol offenders
    by_symbol_map: Dict[str, SymbolOffense] = {}
    for _, r in bsdf.iterrows():
        sym = str(r["symbol"])
        by_symbol_map[sym] = SymbolOffense(
            symbol=sym,
            duplicate_keys=int(r.get("duplicate_keys", 0) or 0),
            ohlc_violations=int(r.get("ohlc_violation_count", 0) or 0),
            gap_count=int(r.get("gap_count", 0) or 0),
            coverage_pct=float(r["coverage_pct"])
            if "coverage_pct" in bsdf.columns and pd.notna(r["coverage_pct"])
            else None,
        )

    # Totals used for enforcement
    # Duplicate keys: sum per-symbol duplicate_keys
    total_duplicate_keys = (
        int(bsdf["duplicate_keys"].fillna(0).sum())
        if "duplicate_keys" in bsdf.columns
        else 0
    )

    # OHLC violations: authoritative global total
    total_ohlc_violations = int(grow.get("total_ohlc_violation_count", 0) or 0)

    # Optional: gaps
    total_gap_count = int(grow.get("total_gap_count", 0) or 0)

    # Optional: missing symbols parsing
    missing_symbols = _parse_missing_symbols(grow.get("symbols_missing", ""))

    # Optional: min coverage observed derived from by_symbol coverage_pct
    min_coverage_observed = None
    if "coverage_pct" in bsdf.columns:
        cov = bsdf["coverage_pct"].dropna()
        if len(cov) > 0:
            min_coverage_observed = float(cov.min())

    return QAMetrics(
        dataset=dataset,
        timeframe=timeframe,
        start=start,
        end=end,
        total_duplicate_keys=total_duplicate_keys,
        total_ohlc_violations=total_ohlc_violations,
        total_gap_count=total_gap_count,
        min_coverage_pct_observed=min_coverage_observed,
        missing_symbols=missing_symbols,
        by_symbol=by_symbol_map,
    )

def build_metrics_from_dataframes(
    *,
    by_symbol_df: pd.DataFrame,
    global_df: pd.DataFrame,
) -> QAMetrics:
    """
    Build QAMetrics from the exact QA export DataFrames produced by qa_export.py
    (no CSV read required).
    """
    if global_df is None or len(global_df) != 1:
        raise ValueError("global_df must have exactly 1 row")

    g = global_df.iloc[0].to_dict()

    # Per-symbol breakdown
    by_symbol_map: Dict[str, SymbolOffense] = {}
    if by_symbol_df is not None and len(by_symbol_df):
        for _, r in by_symbol_df.iterrows():
            sym = str(r["symbol"])
            by_symbol_map[sym] = SymbolOffense(
                symbol=sym,
                duplicate_keys=int(r.get("duplicate_keys", 0) or 0),
                ohlc_violations=int(r.get("ohlc_violation_count", 0) or 0),
                gap_count=int(r.get("gap_count", 0) or 0),
                coverage_pct=float(r["coverage_pct"]) if "coverage_pct" in by_symbol_df.columns and pd.notna(r["coverage_pct"]) else None,
            )

    total_duplicate_keys = int(by_symbol_df["duplicate_keys"].fillna(0).sum()) if "duplicate_keys" in by_symbol_df.columns else 0
    total_ohlc_violations = int(g.get("total_ohlc_violation_count", 0) or 0)
    total_gap_count = int(g.get("total_gap_count", 0) or 0)

    # Derive min coverage observed for optional strict checks
    min_cov = None
    if "coverage_pct" in by_symbol_df.columns:
        cov = by_symbol_df["coverage_pct"].dropna()
        if len(cov) > 0:
            min_cov = float(cov.min())

    missing_symbols = None
    if "symbols_missing" in g:
        missing_symbols = _parse_missing_symbols(g.get("symbols_missing", ""))

    return QAMetrics(
        dataset=str(g.get("dataset_name", "")),
        timeframe=str(g.get("bar_interval", "")),
        start=str(g.get("start_ts", "")),
        end=str(g.get("end_ts", "")),
        total_duplicate_keys=total_duplicate_keys,
        total_ohlc_violations=total_ohlc_violations,
        total_gap_count=total_gap_count,
        min_coverage_pct_observed=min_cov,
        missing_symbols=missing_symbols,
        by_symbol=by_symbol_map if by_symbol_map else None,
    )
# -----------------------------
# Helpers
# -----------------------------

def _parse_missing_symbols(value) -> Optional[List[str]]:
    """
    Parse symbols_missing from global CSV.

    Exporters vary: could be empty, NaN, "AAPL|MSFT", "AAPL,MSFT", "['AAPL','MSFT']".
    We parse conservatively.
    """
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if not isinstance(value, str):
        value = str(value)

    s = value.strip()
    if not s:
        return None

    s = s.strip().strip("[]")
    s = s.replace("|", ",")
    parts = [p.strip().strip("'").strip('"') for p in s.split(",")]
    parts = [p for p in parts if p]
    return parts if parts else None


def _rank_top_offenders(
    by_symbol: Optional[Dict[str, SymbolOffense]],
    *,
    top_n: int,
) -> List[SymbolOffense]:
    if not by_symbol:
        return []

    offenders = list(by_symbol.values())
    offenders.sort(
        key=lambda o: (o.duplicate_keys, o.ohlc_violations, o.gap_count),
        reverse=True,
    )
    offenders = [
        o for o in offenders
        if (o.duplicate_keys > 0) or (o.ohlc_violations > 0) or (o.gap_count > 0)
    ]
    return offenders[:top_n]


def _emit_summary(
    metrics: QAMetrics,
    result: EnforcerResult,
    *,
    strict: bool,
    thresholds: Thresholds,
    logger=None,
) -> None:
    """
    Emit a CI-friendly summary to console and optionally to logger.
    Keep output stable for CI parsing.
    """
    header = "QA STRICT MODE" if strict else "QA MODE"
    status = "PASS" if result.passed else ("FAIL" if strict else "WARN")

    lines: List[str] = []
    lines.append("=" * 30)
    lines.append(f"{header}: {status}")
    lines.append("=" * 30)
    lines.append(f"Dataset: {metrics.dataset}")
    lines.append(f"Timeframe: {metrics.timeframe}")
    lines.append(f"Range: {metrics.start} → {metrics.end}")
    lines.append("")

    # Always show key totals
    lines.append(
        f"Duplicate keys: {metrics.total_duplicate_keys} "
        f"(threshold: {thresholds.max_duplicate_keys})"
    )
    lines.append(
        f"OHLC violations: {metrics.total_ohlc_violations} "
        f"(threshold: {thresholds.max_ohlc_violations})"
    )

    if thresholds.max_gap_count is not None and metrics.total_gap_count is not None:
        lines.append(
            f"Gap count: {metrics.total_gap_count} "
            f"(threshold: {thresholds.max_gap_count})"
        )

    if thresholds.min_coverage_pct is not None and metrics.min_coverage_pct_observed is not None:
        lines.append(
            f"Min coverage pct observed: {metrics.min_coverage_pct_observed:.6f} "
            f"(min required: {thresholds.min_coverage_pct:.6f})"
        )

    if metrics.missing_symbols:
        lines.append(f"Missing symbols: {len(metrics.missing_symbols)}")

    if not result.passed:
        lines.append("")
        lines.append("Reasons:")
        for r in result.reasons:
            lines.append(f"- {r}")

    if result.top_offenders:
        lines.append("")
        lines.append("Top offending symbols:")
        for o in result.top_offenders:
            parts: List[str] = []
            if o.duplicate_keys:
                parts.append(f"{o.duplicate_keys} duplicate keys")
            if o.ohlc_violations:
                parts.append(f"{o.ohlc_violations} OHLC violations")
            if o.gap_count:
                parts.append(f"{o.gap_count} gaps")
            if o.coverage_pct is not None and thresholds.min_coverage_pct is not None:
                parts.append(f"coverage={o.coverage_pct:.6f}")
            lines.append(f"- {o.symbol} – " + ", ".join(parts))

    if strict and not result.passed:
        lines.append("")
        lines.append("Pipeline halted.")
        lines.append(f"Exit Code: {result.exit_code}")

    message = "\n".join(lines)
    print(message)

    if logger is not None:
        if strict and not result.passed:
            logger.error(message)
        else:
            logger.info(message)