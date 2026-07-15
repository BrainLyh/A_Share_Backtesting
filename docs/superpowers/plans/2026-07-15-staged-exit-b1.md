# Staged-Exit B1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `staged-exit-b1` streaming CLI mode that simulates B1 signal-day close entry, staged intraday take-profit exits, conservative same-day stop-loss priority, and horizon expiry exits.

**Architecture:** Keep the staged-exit math in `streaming_event_study_run.py` next to the existing `close-entry-b1` mode because the current project keeps close-entry CLI helpers in that module. Add focused helper functions for measuring staged fills, summarizing events, and writing mode-specific artifacts. Reuse existing TDX iteration, B1 signal generation, stock-pool loading, CSV writing, markdown tables, and technical-only metadata conventions.

**Tech Stack:** Python 3.11, pandas, unittest, existing Codex bundled Python runtime.

---

### Tasks

- [ ] Write failing tests for staged-exit fills: first take-profit level, same-day stop-loss priority, multi-level same-day take-profit, expiry exits, summary metrics, and CLI artifacts.
- [ ] Implement `_measure_staged_exit_returns` with fixed B1 staged-exit rules: +5% sell one third, +10% sell one third, +15% sell remaining, -5% stop-loss all remaining, stop-loss first on same-day conflicts, expiry at T+N close.
- [ ] Implement `_summarize_staged_exit_events` with return, win-rate, drawdown, take-profit count, stop-loss rate, and expiry-exit rate metrics.
- [ ] Add `--mode staged-exit-b1` to the streaming CLI and write `staged_exit_events.csv`, `staged_exit_fills.csv`, `staged_exit_summary.csv`, `staged_exit_metadata.json`, and `staged_exit_report.md`.
- [ ] Run targeted tests after each red/green cycle, then run the full unittest suite with the bundled Python runtime.
- [ ] Commit the implementation on `codex/staged-exit-b1`.

### Verification Commands

```powershell
$env:PYTHONPATH = "$PWD\src"
& 'C:\Users\yuhang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```
