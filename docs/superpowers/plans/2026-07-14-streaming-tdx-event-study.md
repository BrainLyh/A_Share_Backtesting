# Streaming TDX Event Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the frozen technical-only event study over local full-market TDX files with memory bounded by one stock file.

**Architecture:** The runner makes two sequential passes over `.day` files. Pass one emits only signal events and their dates; pass two measures eligible non-signal control events on those dates. It then reuses the existing event summaries and fixed-seed random sampling on the compact event tables.

**Tech Stack:** Python 3.11, pandas, standard library, unittest.

## Global Constraints

- Read one code at a time; never concatenate all daily bars.
- Retain all frozen signal, execution, cost, random-seed, and technical-only limitations.
- Store only events, candidate control events, and metadata under ignored `outputs/`.

### Task 1: Add one-code source iterator and streaming event collection

**Files:** Create `src/a_share_backtesting/streaming_event_study.py`; create `tests/test_streaming_event_study.py`.

**Interfaces:**

```python
def iter_tdx_mainboard_bars(source_root: Path, start: pd.Timestamp, end: pd.Timestamp) -> Iterator[pd.DataFrame]: ...
def collect_signal_events(source_root: Path, config: dict[str, object]) -> tuple[pd.DataFrame, dict[str, object]]: ...
```

- [ ] **Step 1: Write a failing one-code memory-bound test**

```python
def test_iterator_yields_one_normalized_code_frame_at_a_time(self):
    frames = list(iter_tdx_mainboard_bars(self.source, pd.Timestamp("2025-01-01"), pd.Timestamp("2026-01-31")))
    self.assertEqual([frame["code"].iat[0] for frame in frames], ["600000", "000001"])
    self.assertTrue(all(frame["code"].nunique() == 1 for frame in frames))
```

- [ ] **Step 2: Verify RED**

```powershell
& $py -m unittest tests.test_streaming_event_study -v
```

Expected: `ModuleNotFoundError` for `streaming_event_study`.

- [ ] **Step 3: Implement iterator and first pass**

```python
def iter_tdx_mainboard_bars(source_root, start, end):
    for path in sorted(source_root.rglob("*.day")):
        if not is_target_mainboard_path(path):
            continue
        bars = normalize_daily_bars(read_tdx_day_file(path).assign(name=lambda x: x.code, market_cap=0, is_st=False, is_suspended=False), False)
        yield bars.loc[bars["date"].between(start - pd.offsets.BDay(180), end)].copy()

def collect_signal_events(source_root, config):
    frames = []
    for bars in iter_tdx_mainboard_bars(source_root, pd.Timestamp(config["analysis_start"]), pd.Timestamp(config["analysis_end"])):
        signals = build_signal_variants(bars, config)
        frames.extend(measure_events(signals, variant, horizon, config) for variant in config["variants"] for horizon in config["horizons"])
    return pd.concat(frames, ignore_index=True), {"data_scope_label": TECHNICAL_ONLY_SCOPE}
```

- [ ] **Step 4: Verify and commit**

```powershell
& $py -m unittest tests.test_streaming_event_study -v
git add src/a_share_backtesting/streaming_event_study.py tests/test_streaming_event_study.py
git commit -m "feat: collect TDX events in streaming batches"
```

### Task 2: Collect same-date controls and expose the streaming CLI

**Files:** Modify `src/a_share_backtesting/streaming_event_study.py`; create `src/a_share_backtesting/streaming_event_study_run.py`; modify `tests/test_streaming_event_study.py`, `README.md`.

**Interfaces:**

```python
def collect_control_events(source_root: Path, config: dict[str, object], signal_dates: dict[tuple[str, int], set[pd.Timestamp]]) -> pd.DataFrame: ...
def main(argv: list[str] | None = None) -> int: ...
```

- [ ] **Step 1: Write a failing equivalence test**

```python
def test_streaming_control_excludes_signal_codes_and_is_seeded(self):
    events, _ = collect_signal_events(self.source, self.config)
    controls = collect_control_events(self.source, self.config, signal_dates_from(events))
    self.assertFalse(set(events.query("status == 'filled'").event_id) & set(controls.query("status == 'filled'").event_id))
```

- [ ] **Step 2: Verify RED, then implement the second pass**

For each one-code signal frame, measure candidate events only on dates in `signal_dates[(variant, horizon)]` where that code lacks the variant first trigger. Keep `code`, dates, variant, horizon, returns and risk fields. Reuse `np.random.default_rng(config["random_seed"])` to sample one candidate per observed signal event on each date; report omitted dates when the candidate pool is insufficient.

- [ ] **Step 3: Implement CLI and artifacts**

```powershell
& $py -m a_share_backtesting.streaming_event_study_run --source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --config config\event_study_technical_only.json --output outputs\event_study_technical_2026h1
```

Write the existing seven artifacts plus `streaming_metadata.json`; include input counts, date coverage, excluded files, technical-only limitations and omitted-control counts in `report.md`.

- [ ] **Step 4: Verify, audit, commit and push**

```powershell
& $py -m unittest discover -s tests -v
& $py -m a_share_backtesting.streaming_event_study_run --source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --config config\event_study_technical_only.json --output outputs\event_study_technical_2026h1
git add src tests README.md DEVELOPMENT_STATUS.md
git commit -m "feat: run streaming TDX event study"
git push origin codex/b1-event-study
```

## Self-Review

Task 1 bounds daily-bar memory and produces frozen events. Task 2 collects matching controls without full-universe bars, preserves deterministic sampling, writes auditable artifacts, and records the real run.
