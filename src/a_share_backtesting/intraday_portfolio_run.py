from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .intraday_execution import ExecutionConfig
from .intraday_portfolio import run_intraday_portfolio, summarize_portfolio
from .tdx_lc5 import audit_lc5_frame, find_lc5_path, read_tdx_lc5_file


REQUIRED_OUTPUTS = (
    "data_audit.csv",
    "signal_scans.csv",
    "candidates.csv",
    "orders.csv",
    "fills.csv",
    "positions.csv",
    "trades.csv",
    "nav_5m.csv",
    "nav_daily.csv",
    "portfolio_summary.csv",
    "trade_summary.csv",
    "comparison.csv",
    "run_manifest.json",
    "report.md",
)
LIMITATIONS = [
    "retrospective_20260715_stock_pool",
    "historical_st_status_unavailable",
    "historical_market_cap_unavailable",
    "five_minute_intrabar_order_unknown_stop_first",
    "order_book_queue_unavailable",
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the five-minute rolling B1 portfolio backtest.")
    parser.add_argument("--minute-root", required=True)
    parser.add_argument("--qfq-source", required=True)
    parser.add_argument("--stock-pool", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--analysis-start", required=True)
    parser.add_argument("--analysis-end", required=True)
    return parser


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_paths(source: Path) -> list[Path]:
    return [source] if source.is_file() else sorted(source.rglob("*.csv"))


def _sha256_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.resolve()).encode("utf-8"))
        digest.update(bytes.fromhex(_sha256_file(path)))
    return digest.hexdigest()


def _load_pool(path: Path) -> list[str]:
    frame = pd.read_csv(path, dtype={"code": str})
    if "code" not in frame.columns:
        raise ValueError(f"{path}: stock pool requires code column")
    return sorted(frame["code"].astype(str).str.strip().str.zfill(6).drop_duplicates().tolist())


def _load_qfq(source: Path, codes: set[str], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, pd.DataFrame]:
    paths = _source_paths(source)
    if not paths:
        raise ValueError(f"{source}: no qfq CSV files found")
    data = pd.concat([pd.read_csv(path, dtype={"code": str}) for path in paths], ignore_index=True)
    required = {"date", "code", "open", "high", "low", "close", "qfq_open", "qfq_high", "qfq_low", "qfq_close"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"{source}: missing qfq columns {', '.join(sorted(missing))}")
    if "volume" not in data.columns:
        if "vol" not in data.columns:
            raise ValueError(f"{source}: missing volume or vol")
        data["volume"] = data["vol"]
    data["date"] = pd.to_datetime(data["date"], errors="raise")
    data["code"] = data["code"].astype(str).str.strip().str.zfill(6)
    data = data.loc[data["code"].isin(codes) & data["date"].between(start - pd.offsets.BDay(180), end)].copy()
    if data.empty:
        raise ValueError("qfq source has no rows for the selected pool and window")
    for column in ("open", "high", "low", "close", "qfq_open", "qfq_high", "qfq_low", "qfq_close", "volume"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    if "qfq_scale" not in data.columns:
        data["qfq_scale"] = data["qfq_close"] / data["close"]
    data["qfq_scale"] = pd.to_numeric(data["qfq_scale"], errors="raise")
    if "preclose" not in data.columns:
        data["preclose"] = data.groupby("code", sort=False)["close"].shift(1)
    data["preclose"] = pd.to_numeric(data["preclose"], errors="coerce")
    for column in ("open", "high", "low", "close"):
        data[f"raw_{column}"] = data[column]
        data[column] = data[f"qfq_{column}"]
    data = data.assign(
        name=lambda frame: frame["code"],
        market_cap=0,
        is_st=False,
        is_suspended=False,
        in_core_pool=False,
    )
    return {code: group.sort_values("date").reset_index(drop=True) for code, group in data.groupby("code", sort=True)}


def _load_minutes(
    root: Path,
    codes: list[str],
    daily: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[Path]]:
    result: dict[str, pd.DataFrame] = {}
    audit_rows: list[dict[str, object]] = []
    selected_paths: list[Path] = []
    for code in codes:
        path = find_lc5_path(root, code)
        if path is None:
            audit_rows.append({"code": code, "date": pd.NaT, "reason": "missing_lc5_file"})
            continue
        selected_paths.append(path)
        frame = read_tdx_lc5_file(path)
        frame = frame.loc[pd.to_datetime(frame["date"]).between(start, end)].copy()
        if frame.empty:
            audit_rows.append({"code": code, "date": pd.NaT, "reason": "no_lc5_rows_in_window"})
            continue
        bad_dates: set[pd.Timestamp] = set()
        for issue in audit_lc5_frame(frame):
            _, date_text, reason = issue.split(" ", 2)
            bad_dates.add(pd.Timestamp(date_text))
            audit_rows.append({"code": code, "date": pd.Timestamp(date_text), "reason": reason})
        if code not in daily:
            audit_rows.append({"code": code, "date": pd.NaT, "reason": "missing_qfq_code"})
            continue
        join = daily[code][["date", "qfq_scale", "preclose", "raw_close"]].copy()
        frame = frame.merge(join, on="date", how="left", validate="many_to_one")
        for date in frame.loc[frame["qfq_scale"].isna(), "date"].drop_duplicates():
            bad_dates.add(pd.Timestamp(date))
            audit_rows.append({"code": code, "date": pd.Timestamp(date), "reason": "missing_qfq_day"})
        closes = frame.loc[frame["time"].eq("15:00")]
        for date in closes.loc[(closes["close"] - closes["raw_close"]).abs() > 0.011, "date"]:
            bad_dates.add(pd.Timestamp(date))
            audit_rows.append({"code": code, "date": pd.Timestamp(date), "reason": "minute_daily_close_mismatch"})
        if bad_dates:
            frame = frame.loc[~frame["date"].isin(bad_dates)].copy()
        if not frame.empty:
            result[code] = frame.sort_values("timestamp").reset_index(drop=True)
    audit = pd.DataFrame(audit_rows, columns=["code", "date", "reason"])
    return result, audit, selected_paths


def _execution_config(config: dict[str, Any]) -> ExecutionConfig:
    defaults = ExecutionConfig()
    values = {
        field: config.get(field, getattr(defaults, field))
        for field in defaults.__dataclass_fields__
    }
    return ExecutionConfig(
        initial_cash=float(values["initial_cash"]),
        max_positions=int(values["max_positions"]),
        target_fraction=float(values["target_fraction"]),
        lot_size=int(values["lot_size"]),
        participation_rate=float(values["participation_rate"]),
        buy_slippage_bps=float(values["buy_slippage_bps"]),
        sell_slippage_bps=float(values["sell_slippage_bps"]),
        commission_rate=float(values["commission_rate"]),
        minimum_commission=float(values["minimum_commission"]),
        sell_stamp_duty_rate=float(values["sell_stamp_duty_rate"]),
        atr_multiple=float(values["atr_multiple"]),
        atr_min_stop=float(values["atr_min_stop"]),
        atr_max_stop=float(values["atr_max_stop"]),
        take_profit_1=float(values["take_profit_1"]),
        take_profit_2=float(values["take_profit_2"]),
        residual_drawdown=float(values["residual_drawdown"]),
        horizon_days=int(values["horizon_days"]),
    )


def _git_revision() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _report(portfolio: pd.DataFrame, trade: pd.DataFrame, audit_count: int) -> str:
    row, trade_row = portfolio.iloc[0], trade.iloc[0]
    return "\n".join(
        [
            "# Intraday B1 Portfolio Backtest",
            "",
            f"- Total net return: {float(row.get('total_net_return', float('nan'))):.4%}",
            f"- Five-minute maximum drawdown: {float(row.get('max_drawdown_5m', float('nan'))):.4%}",
            f"- Conservative low maximum drawdown: {float(row.get('max_drawdown_low', float('nan'))):.4%}",
            f"- Closed trades: {int(trade_row.get('closed_trade_count', 0))}",
            f"- Net win rate: {float(trade_row.get('win_rate', float('nan'))):.4%}",
            f"- Data audit issues: {audit_count}",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in LIMITATIONS],
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    minute_root = Path(args.minute_root)
    qfq_source = Path(args.qfq_source)
    pool_path = Path(args.stock_pool)
    config_path = Path(args.config)
    output = Path(args.output)
    start, end = pd.Timestamp(args.analysis_start).normalize(), pd.Timestamp(args.analysis_end).normalize()
    if start > end:
        raise ValueError("analysis start must not be after end")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    codes = _load_pool(pool_path)
    config["stock_pool_codes"] = codes
    daily = _load_qfq(qfq_source, set(codes), start, end)
    minutes, data_audit, minute_paths = _load_minutes(minute_root, codes, daily, start, end)
    execution = _execution_config(config)
    result = run_intraday_portfolio(daily, minutes, config, execution, start, end)
    result.data_audit = data_audit
    portfolio_summary, trade_summary = summarize_portfolio(result, execution.initial_cash)
    comparison = portfolio_summary.assign(mode="intraday_portfolio", start=start, end=end)
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "data_audit.csv": result.data_audit,
        "signal_scans.csv": result.scans,
        "candidates.csv": result.candidates,
        "orders.csv": result.orders,
        "fills.csv": result.fills,
        "positions.csv": result.positions,
        "trades.csv": result.trades,
        "nav_5m.csv": result.nav_5m,
        "nav_daily.csv": result.nav_daily,
        "portfolio_summary.csv": portfolio_summary,
        "trade_summary.csv": trade_summary,
        "comparison.csv": comparison,
    }
    for filename, frame in frames.items():
        _write_csv(frame, output / filename)
    manifest = {
        "mode": "intraday-b1-portfolio",
        "analysis_start": f"{start:%Y-%m-%d}",
        "analysis_end": f"{end:%Y-%m-%d}",
        "stock_pool_count": len(codes),
        "processed_code_count": len(minutes),
        "minute_file_count": len(minute_paths),
        "qfq_source": str(qfq_source.resolve()),
        "qfq_source_sha256": _sha256_paths(_source_paths(qfq_source)),
        "stock_pool_sha256": _sha256_file(pool_path),
        "config_sha256": _sha256_file(config_path),
        "minute_source_sha256": _sha256_paths(minute_paths),
        "last_minute_date": max((frame["date"].max() for frame in minutes.values()), default=pd.NaT).strftime("%Y-%m-%d")
        if minutes
        else None,
        "git_revision": _git_revision(),
        "python_version": sys.version,
        "execution_config": execution.__dict__,
        "limitations": LIMITATIONS,
    }
    (output / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output / "report.md").write_text(_report(portfolio_summary, trade_summary, len(data_audit)), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
