from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .data_contract import normalize_daily_bars, validate_event_config
from .event_study import measure_events
from .signals import build_signal_variants
from .statistics import random_control_test, summarize_by_signal_date, summarize_events


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the A-share B1 signal event study.")
    parser.add_argument("--data", required=True, help="Local daily-bars CSV")
    parser.add_argument("--config", required=True, help="Frozen experiment JSON")
    parser.add_argument("--output", required=True, help="Output directory")
    return parser


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "无已成交事件。"
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    validate_event_config(config)
    bars = normalize_daily_bars(pd.read_csv(args.data, dtype={"code": str}), bool(config.get("require_core_pool", False)))
    signals = build_signal_variants(bars, config)
    start, end = pd.Timestamp(config["analysis_start"]), pd.Timestamp(config["analysis_end"])
    audit = signals.loc[signals["date"].between(start, end)].copy()
    event_frames = [measure_events(signals, variant, horizon, config) for variant in config["variants"] for horizon in config["horizons"]]
    events = pd.concat(event_frames, ignore_index=True)
    events = events.loc[events["signal_date"].between(start, end)].copy()
    date_portfolios, summaries, distributions, control_summaries = [], [], [], []
    for variant in config["variants"]:
        for horizon in config["horizons"]:
            subset = events.loc[(events["variant"] == variant) & (events["horizon"] == horizon)]
            date_portfolios.append(summarize_by_signal_date(subset))
            summaries.append(summarize_events(subset))
            distribution, control_summary = random_control_test(signals, subset, variant, horizon, config)
            distribution["variant"], distribution["horizon"] = variant, horizon
            distributions.append(distribution)
            control_summaries.append({"variant": variant, "horizon": horizon, **control_summary})
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(audit, output / "signal_audit.csv")
    _write_csv(events, output / "events.csv")
    _write_csv(pd.concat(date_portfolios, ignore_index=True), output / "date_portfolios.csv")
    _write_csv(pd.concat(summaries, ignore_index=True), output / "summary.csv")
    _write_csv(pd.concat(distributions, ignore_index=True), output / "control_distribution.csv")
    (output / "control_summary.json").write_text(json.dumps(control_summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# B1 信号事件研究报告", "", f"- 分析区间：{start.date()} 至 {end.date()}", "- 交易约定：信号日收盘后确认，下一交易日开盘入场；持有期结束后下一开盘退出。", "- 提醒：结果是日线研究模拟，未还原盘中成交顺序和涨跌停排队。", "", "## 汇总结果", "", _markdown_table(pd.concat(summaries, ignore_index=True))]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
