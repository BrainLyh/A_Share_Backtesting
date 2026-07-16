# QFQ Data Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal qfq adapter that converts `rustdx day -g gbbq` CSV output into front-adjusted OHLC plus audit fields.

**Architecture:** Keep the adjustment math in a focused `qfq.py` module with no dependency on rustdx execution. Add a small `qfq_run.py` CLI that reads an existing rustdx CSV, writes adjusted bars, and writes an adjustment-jump audit file. Existing strategy modes continue to use their current inputs until this adapter is validated.

**Tech Stack:** Python 3.11, pandas, unittest.

---

### Task 1: QFQ adjustment core

**Files:**
- Create: `src/a_share_backtesting/qfq.py`
- Create: `tests/test_qfq.py`

- [ ] **Step 1: Write failing tests**

Test a two-day adjustment where previous raw close is 467.46 and current preclose is 315.047287. Expected: earlier row is scaled by `315.047287 / 467.46`; current row scale remains `1.0`; current adjusted day return is `315.00 / 315.047287 - 1`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:PYTHONPATH = "$PWD\src"
& 'C:\Users\yuhang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_qfq -v
```

Expected: import failure because `a_share_backtesting.qfq` does not exist.

- [ ] **Step 3: Implement minimal core**

Create `apply_qfq_adjustment(frame: pd.DataFrame, tolerance: float = 0.001) -> pd.DataFrame`.

Required columns: `date`, `code`, `open`, `high`, `low`, `close`, `preclose`.

Add columns:

- `raw_prev_close`
- `preclose_to_raw_prev_close_ratio`
- `adjustment_jump`
- `qfq_scale`
- `qfq_open`
- `qfq_high`
- `qfq_low`
- `qfq_close`
- `raw_gap_return`
- `adjusted_day_return`

- [ ] **Step 4: Verify GREEN**

Run the same targeted unittest command. Expected: pass.

### Task 2: CLI wrapper

**Files:**
- Create: `src/a_share_backtesting/qfq_run.py`
- Modify: `tests/test_qfq.py`

- [ ] **Step 1: Write failing CLI test**

Create a temporary rustdx-style CSV, call `qfq_run.main(["--input", ..., "--output", ..., "--audit", ...])`, and assert both output files exist. Assert audit contains the adjustment day.

- [ ] **Step 2: Verify RED**

Expected: import failure because `qfq_run` does not exist.

- [ ] **Step 3: Implement CLI**

Arguments:

- `--input`: rustdx CSV with `preclose`
- `--output`: adjusted CSV
- `--audit`: adjustment-jump audit CSV
- `--tolerance`: default `0.001`

Write full adjusted rows to `--output`; write only rows where `adjustment_jump` is true to `--audit`.

- [ ] **Step 4: Verify GREEN**

Run targeted qfq tests. Expected: pass.

### Task 3: Verification and commit

**Files:**
- Create: `src/a_share_backtesting/qfq.py`
- Create: `src/a_share_backtesting/qfq_run.py`
- Create: `tests/test_qfq.py`
- Add: qfq design and plan docs.

- [ ] **Step 1: Run full test suite**

Run:

```powershell
$env:PYTHONPATH = "$PWD\src"
& 'C:\Users\yuhang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run 688200 manual audit**

Run:

```powershell
$env:PYTHONPATH = "$PWD\src"
& 'C:\Users\yuhang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m a_share_backtesting.qfq_run --input outputs\rustdx_verify\688200_with_gbbq.csv --output outputs\rustdx_verify\688200_qfq.csv --audit outputs\rustdx_verify\688200_qfq_audit.csv
```

Expected: audit contains 2026-06-11 as an adjustment jump.

- [ ] **Step 3: Commit**

Commit source, tests, and docs. Do not commit ignored `outputs/` verification artifacts.
