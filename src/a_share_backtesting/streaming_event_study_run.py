from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from .data_contract import validate_event_config, validate_technical_only_config
from .statistics import summarize_by_signal_date, summarize_events
from .streaming_event_study import count_tdx_mainboard_files, collect_control_events, collect_signal_events, iter_tdx_mainboard_bars, sample_control_distribution
from .signals import build_signal_variants


STAGE_ORDER = {
    "signal_audit": 0,
    "signal_events": 1,
    "control_events": 2,
    "sampling_and_writing": 3,
}


CLOSE_ENTRY_COLUMNS = [
    "event_id",
    "code",
    "name",
    "horizon",
    "signal_date",
    "buy_close",
    "exit_date",
    "exit_close",
    "net_return",
    "max_intraday_drawdown",
    "max_close_drawdown",
    "status",
]
FIELD_LIMITATIONS = [
    "historical_market_cap_unavailable",
    "historical_st_status_unavailable",
    "suspension_status_unavailable",
]


class ProgressReporter:
    def __init__(self, path: Path, total_files: int, interval_seconds: float, stream: object | None = None) -> None:
        self.path = path
        self.total_files = total_files
        self.interval_seconds = max(0.0, interval_seconds)
        self.stream = sys.stdout if stream is None else stream
        self.started_at = time.monotonic()
        self.last_emit_at: float | None = None
        self.stage_started_at: dict[str, float] = {}
        self.stage_durations_seconds: dict[str, float] = {}
        self.path.write_text("", encoding="utf-8")

    def update(
        self,
        stage: str,
        processed_files: int = 0,
        processed_code_windows: int = 0,
        event_count: int | None = None,
        candidate_event_count: int | None = None,
        force: bool = False,
        done: bool = False,
    ) -> None:
        now = time.monotonic()
        self.stage_started_at.setdefault(stage, now)
        if not force and self.last_emit_at is not None and now - self.last_emit_at < self.interval_seconds:
            return
        self.last_emit_at = now
        elapsed_seconds = now - self.started_at
        if done:
            self.stage_durations_seconds[stage] = round(now - self.stage_started_at[stage], 3)
        stage_percent = 100.0 if done else (100.0 if self.total_files == 0 else min(100.0, processed_files / self.total_files * 100.0))
        stage_index = STAGE_ORDER[stage]
        overall_percent = 100.0 if done and stage_index == len(STAGE_ORDER) - 1 else min(100.0, (stage_index + stage_percent / 100.0) / len(STAGE_ORDER) * 100.0)
        eta_seconds = None
        if 0.0 < overall_percent < 100.0:
            eta_seconds = elapsed_seconds * (100.0 / overall_percent - 1.0)
        record: dict[str, object] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "stage": stage,
            "stage_percent": round(stage_percent, 2),
            "overall_percent": round(overall_percent, 2),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "eta_seconds": round(eta_seconds, 3) if eta_seconds is not None else None,
            "processed_files": processed_files,
            "total_files": self.total_files,
            "processed_code_windows": processed_code_windows,
        }
        if event_count is not None:
            record["event_count"] = event_count
        if candidate_event_count is not None:
            record["candidate_event_count"] = candidate_event_count
        line = json.dumps(record, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(f"progress {line}", file=self.stream, flush=True)

    def metadata(self) -> dict[str, object]:
        return {
            "total_elapsed_seconds": round(time.monotonic() - self.started_at, 3),
            "stage_durations_seconds": dict(self.stage_durations_seconds),
        }



def _load_stock_pool(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        if "code" in frame.columns:
            codes = frame["code"].dropna().astype(str).tolist()
        else:
            codes = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    else:
        codes = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    return {str(code).strip().zfill(6) for code in codes if str(code).strip()}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No filled events."
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _write_signal_audit(source: Path, config: dict[str, object], output_path: Path, progress_reporter: ProgressReporter | None = None, code_filter: set[str] | None = None) -> tuple[int, int]:
    start, end = pd.Timestamp(config["analysis_start"]), pd.Timestamp(config["analysis_end"])
    columns = ["date", "code", "name", "eligible"] + [f"{variant}_first_trigger" for variant in config["variants"]]
    wrote_header = False
    row_count = 0
    latest_yielded_count = 0
    def progress_callback(scanned_count: int, yielded_count: int) -> None:
        nonlocal latest_yielded_count
        latest_yielded_count = yielded_count
        if progress_reporter is not None:
            progress_reporter.update("signal_audit", scanned_count, yielded_count, event_count=row_count)

    for bars in iter_tdx_mainboard_bars(source, start, end, progress_callback=progress_callback, code_filter=code_filter):
        signals = build_signal_variants(bars, config)
        audit = signals.loc[signals["date"].between(start, end), [column for column in columns if column in signals.columns]].copy()
        if audit.empty:
            continue
        audit.to_csv(output_path, mode="w" if not wrote_header else "a", header=not wrote_header, index=False, encoding="utf-8-sig")
        wrote_header = True
        row_count += len(audit)
    if not wrote_header:
        pd.DataFrame(columns=columns).to_csv(output_path, index=False, encoding="utf-8-sig")
    return row_count, latest_yielded_count



def _measure_close_entry_returns(signals: pd.DataFrame, horizons: list[int], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if signals.empty or "b1_first_trigger" not in signals.columns:
        return pd.DataFrame(columns=CLOSE_ENTRY_COLUMNS)
    rows: list[dict[str, object]] = []
    data = signals.sort_values(["code", "date"]).copy()
    data["date"] = pd.to_datetime(data["date"])
    for code, bars in data.groupby("code", sort=False):
        bars = bars.reset_index(drop=True)
        trigger = bars["b1_first_trigger"].fillna(False).astype(bool) & bars["date"].between(start, end)
        for signal_index in bars.index[trigger]:
            signal = bars.loc[signal_index]
            signal_date = pd.Timestamp(signal["date"])
            buy_close = float(signal["close"])
            for horizon in horizons:
                horizon = int(horizon)
                exit_index = int(signal_index) + horizon
                base = {
                    "event_id": f"{code}:b1_close:{horizon}:{signal_date:%Y%m%d}",
                    "code": str(code),
                    "name": signal.get("name", code),
                    "horizon": horizon,
                    "signal_date": signal_date,
                    "buy_close": buy_close,
                }
                if exit_index >= len(bars):
                    rows.append({**base, "exit_date": pd.NaT, "exit_close": float("nan"), "net_return": float("nan"), "max_intraday_drawdown": float("nan"), "max_close_drawdown": float("nan"), "status": "insufficient_history"})
                    continue
                exit_row = bars.loc[exit_index]
                holding_window = bars.iloc[int(signal_index) + 1 : exit_index + 1]
                exit_close = float(exit_row["close"])
                min_low = float(holding_window["low"].min())
                min_close = float(holding_window["close"].min())
                rows.append(
                    {
                        **base,
                        "exit_date": pd.Timestamp(exit_row["date"]),
                        "exit_close": exit_close,
                        "net_return": exit_close / buy_close - 1.0,
                        "max_intraday_drawdown": min(min_low / buy_close - 1.0, 0.0),
                        "max_close_drawdown": min(min_close / buy_close - 1.0, 0.0),
                        "status": "filled",
                    }
                )
    return pd.DataFrame(rows, columns=CLOSE_ENTRY_COLUMNS)


def _summarize_close_entry_events(events: pd.DataFrame) -> pd.DataFrame:
    columns = ["horizon", "event_count", "mean_net_return", "median_net_return", "win_rate", "mean_intraday_drawdown", "median_intraday_drawdown", "worst_intraday_drawdown", "mean_close_drawdown", "worst_close_drawdown"]
    if events.empty:
        return pd.DataFrame(columns=columns)
    filled = events.loc[events["status"].eq("filled")]
    if filled.empty:
        return pd.DataFrame(columns=columns)
    summary = filled.groupby("horizon", as_index=False).agg(
        event_count=("event_id", "size"),
        mean_net_return=("net_return", "mean"),
        median_net_return=("net_return", "median"),
        win_rate=("net_return", lambda values: float((values > 0).mean())),
        mean_intraday_drawdown=("max_intraday_drawdown", "mean"),
        median_intraday_drawdown=("max_intraday_drawdown", "median"),
        worst_intraday_drawdown=("max_intraday_drawdown", "min"),
        mean_close_drawdown=("max_close_drawdown", "mean"),
        worst_close_drawdown=("max_close_drawdown", "min"),
    )
    return summary[columns]


def _run_close_entry_b1_backtest(source: Path, config: dict[str, object], output: Path, code_filter: set[str] | None = None, stock_pool_path: Path | None = None) -> int:
    start, end = pd.Timestamp(config["analysis_start"]), pd.Timestamp(config["analysis_end"])
    horizons = [int(horizon) for horizon in config["horizons"]]
    frames: list[pd.DataFrame] = []
    processed_code_count = 0
    for bars in iter_tdx_mainboard_bars(source, start, end, code_filter=code_filter):
        processed_code_count += 1
        signals = build_signal_variants(bars, config)
        measured = _measure_close_entry_returns(signals, horizons, start, end)
        if not measured.empty:
            frames.append(measured)
    events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CLOSE_ENTRY_COLUMNS)
    summary = _summarize_close_entry_events(events)
    selected = events.loc[:, ["signal_date", "code", "name", "buy_close"]].drop_duplicates().sort_values(["signal_date", "code"]) if not events.empty else pd.DataFrame(columns=["signal_date", "code", "name", "buy_close"])
    _write_csv(events, output / "close_entry_events.csv")
    _write_csv(summary, output / "close_entry_summary.csv")
    _write_csv(selected, output / "close_entry_selected_signals.csv")
    metadata = {
        "mode": "close-entry-b1",
        "analysis_start": str(config["analysis_start"]),
        "analysis_end": str(config["analysis_end"]),
        "horizons": horizons,
        "processed_code_count": processed_code_count,
        "event_count": int(len(events)),
        "selected_signal_count": int(len(selected)),
        "entry_price": "signal_day_close",
        "exit_price": "future_close",
        "drawdown_price": "holding_period_intraday_low",
        "field_limitations": FIELD_LIMITATIONS,
        "stock_pool_path": str(stock_pool_path) if stock_pool_path is not None else None,
        "stock_pool_count": len(code_filter) if code_filter is not None else None,
    }
    (output / "close_entry_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# Close-Entry B1 Backtest",
        "",
        f"- Analysis window: {config['analysis_start']} to {config['analysis_end']}",
        "- Entry: signal-day close.",
        "- Exit: future close by holding horizon.",
        "- Drawdown: lowest intraday low during the holding window, capped at 0 when price never falls below entry.",
        "- Scope: technical-only; historical market-cap, ST and suspension filters are not validated.",
        "- Field limitations: " + ", ".join(FIELD_LIMITATIONS),
        "",
        "## Summary",
        "",
        _markdown_table(summary),
    ]
    (output / "close_entry_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0
def _control_summary(events: pd.DataFrame, distribution: pd.DataFrame, config: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    filled = events.loc[events["status"].eq("filled")]
    portfolios = summarize_by_signal_date(filled)
    for variant in config["variants"]:
        for horizon in config["horizons"]:
            observed_values = portfolios.loc[
                (portfolios["variant"] == variant) & (portfolios["horizon"] == horizon),
                "portfolio_net_return",
            ]
            control_values = distribution.loc[
                (distribution["variant"] == variant) & (distribution["horizon"] == horizon),
                "control_mean_return",
            ].dropna()
            observed_mean = float(observed_values.mean()) if not observed_values.empty else float("nan")
            rows.append(
                {
                    "variant": str(variant),
                    "horizon": int(horizon),
                    "observed_mean": observed_mean,
                    "control_mean": float(control_values.mean()) if not control_values.empty else float("nan"),
                    "control_percentile": float((control_values <= observed_mean).mean()) if not control_values.empty and pd.notna(observed_mean) else float("nan"),
                    "empirical_p_value": float((control_values >= observed_mean).mean()) if not control_values.empty and pd.notna(observed_mean) else float("nan"),
                }
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run streaming TDX B1 event study.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--progress-interval-seconds", type=float, default=60.0)
    parser.add_argument("--mode", choices=["event-study", "close-entry-b1"], default="event-study")
    parser.add_argument("--analysis-start")
    parser.add_argument("--analysis-end")
    parser.add_argument("--horizons", nargs="+", type=int)
    parser.add_argument("--stock-pool")
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    if args.analysis_start is not None:
        config["analysis_start"] = args.analysis_start
    if args.analysis_end is not None:
        config["analysis_end"] = args.analysis_end
    if args.horizons is not None:
        config["horizons"] = args.horizons
    validate_event_config(config)
    validate_technical_only_config(config)
    stock_pool_path = Path(args.stock_pool) if args.stock_pool is not None else None
    code_filter = _load_stock_pool(stock_pool_path) if stock_pool_path is not None else None
    if code_filter is not None:
        config["stock_pool_codes"] = sorted(code_filter)
    source = Path(args.source)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.mode == "close-entry-b1":
        return _run_close_entry_b1_backtest(source, config, output, code_filter=code_filter, stock_pool_path=stock_pool_path)
    total_files = count_tdx_mainboard_files(source, code_filter=code_filter)
    progress_reporter = ProgressReporter(output / "progress.jsonl", total_files, float(args.progress_interval_seconds))
    progress_reporter.update("signal_audit", force=True)
    signal_audit_rows, signal_audit_code_windows = _write_signal_audit(source, config, output / "signal_audit.csv", progress_reporter, code_filter=code_filter)
    progress_reporter.update("signal_audit", total_files, signal_audit_code_windows, force=True, done=True, event_count=signal_audit_rows)
    progress_reporter.update("signal_events", force=True)
    signal_progress = {"scanned": 0, "yielded": 0}
    def signal_progress_callback(scanned_count: int, yielded_count: int) -> None:
        signal_progress["scanned"] = scanned_count
        signal_progress["yielded"] = yielded_count
        progress_reporter.update("signal_events", scanned_count, yielded_count)

    events, metadata = collect_signal_events(
        source,
        config,
        progress_callback=signal_progress_callback,
        code_filter=code_filter,
    )
    progress_reporter.update("signal_events", total_files, signal_progress["yielded"], event_count=len(events), force=True, done=True)
    signal_dates = {(variant, horizon): set(group["signal_date"]) for (variant, horizon), group in events.loc[events["status"].eq("filled")].groupby(["variant", "horizon"])}
    progress_reporter.update("control_events", force=True)
    control_progress = {"scanned": 0, "yielded": 0}
    def control_progress_callback(scanned_count: int, yielded_count: int) -> None:
        control_progress["scanned"] = scanned_count
        control_progress["yielded"] = yielded_count
        progress_reporter.update("control_events", scanned_count, yielded_count, event_count=len(events))

    controls = collect_control_events(
        source,
        config,
        signal_dates,
        progress_callback=control_progress_callback,
        code_filter=code_filter,
    )
    progress_reporter.update("control_events", total_files, control_progress["yielded"], candidate_event_count=len(controls), force=True, done=True)
    progress_reporter.update("sampling_and_writing", event_count=len(events), candidate_event_count=len(controls), force=True)
    distribution = sample_control_distribution(events, controls, int(config["control_iterations"]), int(config["random_seed"]))
    summaries = summarize_events(events)
    _write_csv(events, output / "events.csv")
    _write_csv(controls, output / "control_candidates.csv")
    _write_csv(summaries, output / "summary.csv")
    _write_csv(summarize_by_signal_date(events), output / "date_portfolios.csv")
    _write_csv(distribution, output / "control_distribution.csv")
    (output / "control_summary.json").write_text(json.dumps(_control_summary(events, distribution, config), ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# Streaming B1 Event Study",
        "",
        f"- Analysis window: {config['analysis_start']} to {config['analysis_end']}",
        "- Scope: technical-only; historical market-cap, ST and suspension filters are not validated.",
        "- Field limitations: " + ", ".join(FIELD_LIMITATIONS),
        f"- Processed code windows: {metadata['processed_code_count']}",
        f"- Signal audit rows: {signal_audit_rows}",
        f"- Candidate control events: {len(controls)}",
        "",
        "## Summary",
        "",
        _markdown_table(summaries),
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    progress_reporter.update("sampling_and_writing", event_count=len(events), candidate_event_count=len(controls), force=True, done=True)
    metadata = {
        **metadata,
        **progress_reporter.metadata(),
        "signal_audit_row_count": signal_audit_rows,
        "signal_audit_code_window_count": signal_audit_code_windows,
        "candidate_control_event_count": int(len(controls)),
        "total_target_file_count": total_files,
        "data_scope_label": config.get("data_scope_label", metadata.get("data_scope_label")),
        "price_adjustment": config.get("price_adjustment", "unadjusted"),
        "field_limitations": FIELD_LIMITATIONS,
        "stock_pool_path": str(stock_pool_path) if stock_pool_path is not None else None,
        "stock_pool_count": len(code_filter) if code_filter is not None else None,
    }
    (output / "streaming_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
