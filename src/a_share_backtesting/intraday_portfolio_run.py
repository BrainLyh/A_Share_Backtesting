from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from .intraday_execution import ExecutionConfig, validate_execution_config
from .intraday_portfolio import cached_scan_candidate_provider, run_intraday_portfolio, summarize_portfolio
from .market_regime import MarketRegimeSchedule, build_market_regime_schedule
from .tdx_lc5 import audit_lc5_records, find_lc5_path, read_tdx_lc5_file


REQUIRED_OUTPUTS = (
    "data_audit.csv",
    "signal_scans.csv",
    "candidates.csv",
    "orders.csv",
    "fills.csv",
    "positions.csv",
    "trades.csv",
    "rejections.csv",
    "nav_5m.csv",
    "nav_daily.csv",
    "portfolio_summary.csv",
    "trade_summary.csv",
    "comparison.csv",
    "run_manifest.json",
    "report.md",
)
EMPTY_CSV_COLUMNS = {
    "signal_scans.csv": [
        "date", "code", "scan_time", "b1_signal", "eligible", "signal_strength", "j", "prior_j",
        "bbi", "dif", "volume", "volume_ma", "atr14", "qfq_scale",
    ],
    "candidates.csv": [
        "date", "code", "scan_time", "b1_signal", "eligible", "signal_strength", "j", "prior_j",
        "bbi", "dif", "volume", "volume_ma", "atr14", "qfq_scale", "first_trigger_time",
    ],
    "orders.csv": ["timestamp", "code", "side", "reason", "status"],
    "fills.csv": [
        "position_id", "code", "timestamp", "side", "reason", "shares", "raw_price", "adjusted_price",
        "gross_notional", "commission", "stamp_duty", "slippage_cost", "cash_delta",
    ],
    "positions.csv": [
        "timestamp", "position_id", "code", "remaining_shares", "market_value", "position_return",
        "position_return_low",
    ],
    "trades.csv": [
        "position_id", "code", "entry_timestamp", "exit_timestamp", "status", "exit_reason", "entry_cost",
        "net_proceeds", "net_pnl", "net_return", "holding_days", "maximum_adverse_excursion",
    ],
    "rejections.csv": ["timestamp", "code", "side", "reason"],
    "nav_5m.csv": ["timestamp", "date", "cash", "gross_exposure", "positions", "nav", "nav_low"],
    "nav_daily.csv": ["timestamp", "date", "cash", "gross_exposure", "positions", "nav", "nav_low"],
}
LIMITATIONS = [
    "retrospective_stock_pool_snapshot",
    "historical_st_status_unavailable",
    "historical_market_cap_unavailable",
    "five_minute_intrabar_order_unknown_stop_first",
    "order_book_queue_unavailable",
]
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the five-minute rolling B1 portfolio backtest.")
    parser.add_argument("--minute-root", required=True)
    parser.add_argument("--qfq-source", required=True)
    parser.add_argument("--stock-pool", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--scan-source")
    parser.add_argument("--market-regime")
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
    data = data.loc[data["code"].isin(codes) & data["date"].le(end)].copy()
    if data.empty:
        raise ValueError("qfq source has no rows for the selected pool and window")
    numeric_columns = [
        "open", "high", "low", "close", "qfq_open", "qfq_high", "qfq_low", "qfq_close", "volume",
        *[column for column in ("upper_limit", "lower_limit") if column in data.columns],
    ]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="raise")
    if "qfq_scale" not in data.columns:
        data["qfq_scale"] = data["qfq_close"] / data["close"]
    data["qfq_scale"] = pd.to_numeric(data["qfq_scale"], errors="raise")
    if "preclose" not in data.columns:
        data["preclose"] = data.groupby("code", sort=False)["close"].shift(1)
    data["preclose"] = pd.to_numeric(data["preclose"], errors="coerce")
    windows = []
    for _, group in data.sort_values(["code", "date"]).groupby("code", sort=False):
        warmup = group.loc[group["date"] < start].tail(180)
        analysis = group.loc[group["date"].between(start, end)]
        windows.append(pd.concat([warmup, analysis], ignore_index=True))
    data = pd.concat(windows, ignore_index=True) if windows else data.iloc[0:0].copy()
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
        try:
            frame = read_tdx_lc5_file(path)
        except (OSError, ValueError):
            audit_rows.append({"code": code, "date": pd.NaT, "reason": "lc5_parse_error"})
            continue
        frame = frame.loc[pd.to_datetime(frame["date"]).between(start, end)].copy()
        if frame.empty:
            audit_rows.append({"code": code, "date": pd.NaT, "reason": "no_lc5_rows_in_window"})
            continue
        bad_dates: set[pd.Timestamp] = set()
        for issue in audit_lc5_records(frame):
            issue_date = pd.Timestamp(issue["date"])
            bad_dates.add(issue_date)
            audit_rows.append({"code": code, "date": issue_date, "reason": issue["reason"]})
        if code not in daily:
            audit_rows.append({"code": code, "date": pd.NaT, "reason": "missing_qfq_code"})
            continue
        join_columns = [
            "date", "qfq_scale", "preclose", "raw_close",
            *[column for column in ("upper_limit", "lower_limit") if column in daily[code].columns],
        ]
        join = daily[code][join_columns].copy()
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
    execution = ExecutionConfig(
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
    validate_execution_config(execution)
    return execution


def _git_state() -> tuple[str | None, bool | None]:
    repository = Path(__file__).resolve().parents[2]
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=no"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return revision, bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        return None, None


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _report(
    portfolio: pd.DataFrame,
    trade: pd.DataFrame,
    audit_count: int,
    market_regime: bool = False,
) -> str:
    row, trade_row = portfolio.iloc[0], trade.iloc[0]
    limitations = [f"- {item}" for item in LIMITATIONS]
    if market_regime:
        limitations.extend(
            [
                "- Market-regime dates were manually supplied.",
                "- Market-regime thresholds are post-hoc.",
                "- `same_day_1455` assumes the full signal is observable by 14:55.",
            ]
        )
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
            *limitations,
            "",
        ]
    )


def _build_cli_market_regime(
    path: Path | None,
    minutes: dict[str, pd.DataFrame],
    source_bytes: bytes | None = None,
) -> MarketRegimeSchedule | None:
    if path is None:
        return None
    payload = json.loads((source_bytes if source_bytes is not None else path.read_bytes()).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("market regime config must be a JSON object")
    config: dict[str, object] = payload
    trading_dates = sorted(
        {
            pd.Timestamp(date).normalize()
            for frame in minutes.values()
            for date in frame["date"].unique()
        }
    )
    raw_extensions = config.get("calendar_extension_dates")
    has_extension_source = "calendar_extension_source" in config
    if raw_extensions is None:
        if has_extension_source:
            raise ValueError("calendar_extension_source requires calendar_extension_dates")
    else:
        if config.get("execution_mode") != "next_session_0935":
            raise ValueError("calendar extensions require next_session_0935 execution")
        if not isinstance(raw_extensions, list) or not raw_extensions:
            raise ValueError("calendar_extension_dates must be a non-empty list")
        extension_source = config.get("calendar_extension_source")
        if not isinstance(extension_source, str) or not extension_source.strip():
            raise ValueError("calendar_extension_source must be a non-empty string")
        extensions: list[pd.Timestamp] = []
        for value in raw_extensions:
            if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
                raise ValueError("calendar_extension_dates entries must be ISO dates (YYYY-MM-DD)")
            try:
                extensions.append(pd.Timestamp(value).normalize())
            except (TypeError, ValueError) as error:
                raise ValueError("calendar_extension_dates entries must be ISO dates (YYYY-MM-DD)") from error
        if len(set(extensions)) != len(extensions):
            raise ValueError("calendar_extension_dates must not contain duplicates")
        if not trading_dates or any(date <= trading_dates[-1] for date in extensions):
            raise ValueError("calendar extension dates must follow in-window minute trading dates")
        trading_dates.extend(extensions)
    return build_market_regime_schedule(config, trading_dates)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    minute_root = Path(args.minute_root)
    qfq_source = Path(args.qfq_source)
    pool_path = Path(args.stock_pool)
    config_path = Path(args.config)
    scan_source = Path(args.scan_source) if args.scan_source else None
    market_regime_path = Path(args.market_regime) if args.market_regime else None
    output = Path(args.output)
    market_regime_source = None
    market_regime_source_bytes = None
    market_regime_source_sha256 = None
    if market_regime_path is not None:
        market_regime_artifact = output / "market_regime.csv"
        resolved_source = market_regime_path.resolve()
        resolved_artifact = market_regime_artifact.resolve()
        aliases_artifact = resolved_source == resolved_artifact
        if not aliases_artifact and market_regime_artifact.exists():
            aliases_artifact = market_regime_path.samefile(market_regime_artifact)
        if aliases_artifact:
            raise ValueError("market regime source must not alias output market_regime.csv")
        market_regime_source = str(resolved_source)
        market_regime_source_bytes = market_regime_path.read_bytes()
        market_regime_source_sha256 = hashlib.sha256(market_regime_source_bytes).hexdigest()
    start, end = pd.Timestamp(args.analysis_start).normalize(), pd.Timestamp(args.analysis_end).normalize()
    if start > end:
        raise ValueError("analysis start must not be after end")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    codes = _load_pool(pool_path)
    config["stock_pool_codes"] = codes
    daily = _load_qfq(qfq_source, set(codes), start, end)
    minutes, data_audit, minute_paths = _load_minutes(minute_root, codes, daily, start, end)
    market_regime = _build_cli_market_regime(market_regime_path, minutes, market_regime_source_bytes)
    execution = _execution_config(config)
    cached_scans = None
    candidate_provider = None
    if scan_source is not None:
        cached_scans = pd.read_csv(scan_source, dtype={"code": str})
        cached_scans["date"] = pd.to_datetime(cached_scans["date"]).dt.normalize()
        cached_scans = cached_scans.loc[cached_scans["date"].between(start, end)].copy()
        candidate_provider = cached_scan_candidate_provider(cached_scans, daily, config)
    result = run_intraday_portfolio(
        daily,
        minutes,
        config,
        execution,
        start,
        end,
        candidate_provider=candidate_provider,
        market_regime=market_regime,
    )
    if cached_scans is not None:
        result.scans = cached_scans
    result.data_audit = data_audit
    portfolio_summary, trade_summary = summarize_portfolio(result, execution.initial_cash)
    comparison = portfolio_summary.assign(mode="intraday_portfolio", start=start, end=end)
    output.mkdir(parents=True, exist_ok=True)
    if market_regime is None:
        (output / "market_regime.csv").unlink(missing_ok=True)
    frames = {
        "data_audit.csv": result.data_audit,
        "signal_scans.csv": result.scans,
        "candidates.csv": result.candidates,
        "orders.csv": result.orders,
        "fills.csv": result.fills,
        "positions.csv": result.positions,
        "trades.csv": result.trades,
        "rejections.csv": result.rejections,
        "nav_5m.csv": result.nav_5m,
        "nav_daily.csv": result.nav_daily,
        "portfolio_summary.csv": portfolio_summary,
        "trade_summary.csv": trade_summary,
        "comparison.csv": comparison,
    }
    if market_regime is not None:
        frames["market_regime.csv"] = result.market_regime
    for filename, frame in frames.items():
        if frame.empty and len(frame.columns) == 0 and filename in EMPTY_CSV_COLUMNS:
            frame = pd.DataFrame(columns=EMPTY_CSV_COLUMNS[filename])
        _write_csv(frame, output / filename)
    git_revision, git_dirty = _git_state()
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
        "scan_source": str(scan_source.resolve()) if scan_source is not None else None,
        "scan_source_sha256": _sha256_file(scan_source) if scan_source is not None else None,
        "minute_source_sha256": _sha256_paths(minute_paths),
        "last_minute_date": max((frame["date"].max() for frame in minutes.values()), default=pd.NaT).strftime("%Y-%m-%d")
        if minutes
        else None,
        "git_revision": git_revision,
        "git_dirty": git_dirty,
        "python_version": sys.version,
        "execution_config": execution.__dict__,
        "limitations": LIMITATIONS,
    }
    if market_regime_path is not None:
        manifest.update(
            {
                "market_regime_source": market_regime_source,
                "market_regime_source_sha256": market_regime_source_sha256,
                "outputs": [*REQUIRED_OUTPUTS, "market_regime.csv"],
            }
        )
    (output / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output / "report.md").write_text(
        _report(portfolio_summary, trade_summary, len(data_audit), market_regime=market_regime is not None),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
