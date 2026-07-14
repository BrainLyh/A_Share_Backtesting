# TDX Technical-Only Event Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import local Tongdaxin `.day` files into a validated technical-only daily-bar CSV and execute the frozen B1 event study with auditable scope limitations.

**Architecture:** A dedicated binary-reader module parses one 32-byte `.day` record format and exposes normalized OHLCV rows. A separate import CLI discovers source files, selects only target mainboard codes, writes the existing daily-bar contract plus provenance metadata, and then the existing event-study CLI consumes the CSV and incorporates that metadata into its report.

**Tech Stack:** Python 3.11+, standard-library `struct`/`json`/`pathlib`, pandas, numpy, unittest, UTF-8-SIG CSV and UTF-8 JSON/Markdown.

## Global Constraints

- Source files are read only from a user-provided local root; no remote market-data fetches occur.
- A valid `.day` file has a byte length divisible by 32 and records unpacked as `<IIIIIfII`; prices are stored as integer cent values and divided by 100.
- Only `sh600/sh601/sh603/sh605` and `sz000/sz001/sz002` file names enter the study universe.
- Imported technical-only rows set `name=code`, `market_cap=0`, `is_st=false`, `is_suspended=false`; the last two booleans are not inferred from volume.
- The technical-only configuration must set `min_market_cap=0`, `data_scope_label=technical_only_no_historical_market_cap_or_st`, and `price_adjustment=unadjusted`.
- Do not claim that this run evaluates the original historical market-cap or ST filters.
- All implementation uses test-first development; outputs under `data/` and `outputs/` remain ignored by Git.

---

## Planned File Structure

```text
config/event_study_technical_only.json                 # frozen technical-only run config
src/a_share_backtesting/tdx_day.py                     # one-file binary parser and code filter
src/a_share_backtesting/tdx_import.py                  # import CLI, metadata and atomic output flow
src/a_share_backtesting/data_contract.py               # technical-only config validation
src/a_share_backtesting/event_study_run.py             # optional metadata input and report disclosure
tests/test_tdx_day.py                                  # parser/filter tests
tests/test_tdx_import.py                               # import and CLI artifact tests
tests/test_data_contract.py                             # technical-only config guard test
tests/test_event_study.py                               # report-metadata smoke test
README.md                                              # documented import/run commands and limitations
DEVELOPMENT_STATUS.md                                  # cross-machine handoff after the real run
```

### Task 1: Parse and validate a single Tongdaxin day file

**Files:**
- Create: `src/a_share_backtesting/tdx_day.py`
- Create: `tests/test_tdx_day.py`

**Interfaces:**

```python
def is_target_mainboard_path(path: Path) -> bool: ...
def read_tdx_day_file(path: Path) -> pd.DataFrame: ...
```

`read_tdx_day_file` produces `date`, `code`, `open`, `high`, `low`, `close`, and `volume`; it raises `ValueError` containing the path when the file length, filename, date, or price fields are invalid.

- [ ] **Step 1: Write failing parser/filter tests**

```python
class TestTdxDayReader(unittest.TestCase):
    def test_reads_one_32_byte_record_and_scales_prices(self):
        path = self.write_day("sh600000.day", [(20260105, 1001, 1020, 990, 1015, 123.0, 4567, 0)])
        actual = read_tdx_day_file(path)
        self.assertEqual(actual.loc[0, "code"], "600000")
        self.assertEqual(actual.loc[0, "date"], pd.Timestamp("2026-01-05"))
        self.assertAlmostEqual(actual.loc[0, "close"], 10.15)
        self.assertEqual(actual.loc[0, "volume"], 4567)

    def test_rejects_file_whose_length_is_not_a_multiple_of_32(self):
        path = self.temp_dir / "sh600000.day"
        path.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "multiple of 32"):
            read_tdx_day_file(path)

    def test_filters_only_requested_mainboard_file_prefixes(self):
        self.assertTrue(is_target_mainboard_path(Path("sh/lday/sh603000.day")))
        self.assertTrue(is_target_mainboard_path(Path("sz/lday/sz002001.day")))
        self.assertFalse(is_target_mainboard_path(Path("sh/lday/sh688001.day")))
        self.assertFalse(is_target_mainboard_path(Path("bj/lday/bj920001.day")))
```

- [ ] **Step 2: Run the new test module and verify the expected RED failure**

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest tests.test_tdx_day -v
```

Expected: import failure because `a_share_backtesting.tdx_day` does not yet exist.

- [ ] **Step 3: Implement the smallest parser that satisfies the tests**

```python
_RECORD = struct.Struct("<IIIIIfII")
_TARGET_PREFIXES = {"sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002"}

def is_target_mainboard_path(path: Path) -> bool:
    return path.suffix.lower() == ".day" and path.stem[:5].lower() in _TARGET_PREFIXES

def read_tdx_day_file(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    if not raw or len(raw) % _RECORD.size:
        raise ValueError(f"{path}: byte length must be a non-zero multiple of 32")
    code = path.stem[2:]
    rows = []
    for offset in range(0, len(raw), _RECORD.size):
        date, open_, high, low, close, _amount, volume, _reserved = _RECORD.unpack_from(raw, offset)
        timestamp = pd.to_datetime(str(date), format="%Y%m%d", errors="coerce")
        if pd.isna(timestamp) or min(open_, high, low, close) <= 0:
            raise ValueError(f"{path}: invalid record at byte offset {offset}")
        rows.append({"date": timestamp, "code": code, "open": open_ / 100, "high": high / 100,
                     "low": low / 100, "close": close / 100, "volume": volume})
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run the parser module and the existing data-contract tests**

```powershell
& $py -m unittest tests.test_tdx_day tests.test_data_contract -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the parser deliverable**

```powershell
git add src/a_share_backtesting/tdx_day.py tests/test_tdx_day.py
git commit -m "feat: parse local Tongdaxin day files"
```

### Task 2: Import the mainboard universe and emit provenance metadata

**Files:**
- Create: `src/a_share_backtesting/tdx_import.py`
- Create: `tests/test_tdx_import.py`

**Interfaces:**

```python
def import_tdx_daily_bars(source_root: Path) -> tuple[pd.DataFrame, dict[str, object]]: ...
def main(argv: list[str] | None = None) -> int: ...
```

`import_tdx_daily_bars` recursively discovers `.day` files, parses every target file, validates uniqueness through `normalize_daily_bars`, and returns the full technical-only frame and a JSON-serializable quality dictionary. `main` accepts `--source`, `--output`, and `--metadata`, and writes neither output until import succeeds.

- [ ] **Step 1: Write failing import tests**

```python
def test_imports_mainboard_rows_and_records_excluded_files(self):
    self.write_day("sh/lday/sh600000.day", [(20260105, 1000, 1010, 990, 1005, 0.0, 1, 0)])
    self.write_day("sh/lday/sh688001.day", [(20260105, 1000, 1010, 990, 1005, 0.0, 1, 0)])
    bars, metadata = import_tdx_daily_bars(self.source)
    self.assertEqual(bars["code"].tolist(), ["600000"])
    self.assertEqual(bars.loc[0, "market_cap"], 0)
    self.assertFalse(bars.loc[0, "is_st"])
    self.assertEqual(metadata["excluded_non_target_files"], 1)
    self.assertEqual(metadata["data_scope_label"], "technical_only_no_historical_market_cap_or_st")

def test_cli_writes_csv_and_metadata_after_successful_import(self):
    self.write_day("sz/lday/sz000001.day", [(20260105, 1000, 1010, 990, 1005, 0.0, 1, 0)])
    self.assertEqual(main(["--source", str(self.source), "--output", str(self.csv), "--metadata", str(self.metadata)]), 0)
    self.assertTrue(self.csv.exists())
    self.assertEqual(json.loads(self.metadata.read_text(encoding="utf-8"))["imported_code_count"], 1)
```

- [ ] **Step 2: Run the module and verify the expected RED failure**

```powershell
& $py -m unittest tests.test_tdx_import -v
```

Expected: import failure because `a_share_backtesting.tdx_import` does not yet exist.

- [ ] **Step 3: Implement import, metadata, and CLI output**

```python
def import_tdx_daily_bars(source_root: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    files = sorted(source_root.rglob("*.day"))
    target_files = [path for path in files if is_target_mainboard_path(path)]
    frames = [read_tdx_day_file(path) for path in target_files]
    if not frames:
        raise ValueError(f"{source_root}: no target mainboard .day files found")
    bars = pd.concat(frames, ignore_index=True)
    bars = bars.assign(name=bars["code"], market_cap=0, is_st=False, is_suspended=False)
    normalized = normalize_daily_bars(bars, require_core_pool=False)
    metadata = {
        "data_scope_label": "technical_only_no_historical_market_cap_or_st",
        "price_adjustment": "unadjusted",
        "source_root": str(source_root),
        "source_file_count": len(files),
        "excluded_non_target_files": len(files) - len(target_files),
        "imported_code_count": int(normalized["code"].nunique()),
        "imported_row_count": len(normalized),
        "date_start": normalized["date"].min().date().isoformat(),
        "date_end": normalized["date"].max().date().isoformat(),
        "field_limitations": ["historical_market_cap_unavailable", "historical_st_status_unavailable", "suspension_status_unavailable"],
    }
    return normalized, metadata
```

`main` must convert `--source`, `--output`, and `--metadata` to `Path`, call the function before creating parent directories, write CSV using `encoding="utf-8-sig"`, write metadata JSON using `ensure_ascii=False`, and return `0`.

- [ ] **Step 4: Run focused tests and the full suite**

```powershell
& $py -m unittest tests.test_tdx_import -v
& $py -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the importer deliverable**

```powershell
git add src/a_share_backtesting/tdx_import.py tests/test_tdx_import.py
git commit -m "feat: import technical-only TDX daily bars"
```

### Task 3: Freeze and disclose the technical-only research scope

**Files:**
- Create: `config/event_study_technical_only.json`
- Modify: `src/a_share_backtesting/data_contract.py`
- Modify: `src/a_share_backtesting/event_study_run.py`
- Modify: `tests/test_data_contract.py`
- Modify: `tests/test_event_study.py`
- Modify: `README.md`

**Interfaces:**

```python
def validate_technical_only_config(config: dict[str, object]) -> None: ...
```

The event-study command gains an optional `--metadata <path>` argument. When metadata is supplied, the report displays its data scope, source date coverage, price adjustment, and all field limitations.

- [ ] **Step 1: Write failing configuration and report tests**

```python
def test_technical_only_scope_rejects_a_positive_market_cap_filter(self):
    config = baseline_config() | {
        "data_scope_label": "technical_only_no_historical_market_cap_or_st",
        "price_adjustment": "unadjusted",
        "min_market_cap": 1,
    }
    with self.assertRaisesRegex(ValueError, "min_market_cap"):
        validate_technical_only_config(config)

def test_cli_report_includes_metadata_limitations(self):
    metadata = {"data_scope_label": "technical_only_no_historical_market_cap_or_st", "date_start": "2020-01-01",
                "date_end": "2026-07-13", "price_adjustment": "unadjusted",
                "field_limitations": ["historical_market_cap_unavailable"]}
    self.metadata_json.write_text(json.dumps(metadata), encoding="utf-8")
    self.assertEqual(main(["--data", str(self.bars_csv), "--config", str(self.config_json), "--metadata", str(self.metadata_json), "--output", str(self.output_dir)]), 0)
    self.assertIn("historical_market_cap_unavailable", (self.output_dir / "report.md").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run focused tests and verify the expected RED failure**

```powershell
& $py -m unittest tests.test_data_contract.TestDataContract.test_technical_only_scope_rejects_a_positive_market_cap_filter tests.test_event_study.EventStudyCliTests.test_cli_report_includes_metadata_limitations -v
```

Expected: import failure for `validate_technical_only_config` and parser failure for the unknown `--metadata` argument.

- [ ] **Step 3: Implement config guard, metadata option, and report disclosure**

```python
TECHNICAL_ONLY_SCOPE = "technical_only_no_historical_market_cap_or_st"

def validate_technical_only_config(config: dict[str, object]) -> None:
    if config.get("data_scope_label") != TECHNICAL_ONLY_SCOPE:
        return
    if config.get("min_market_cap") != 0:
        raise ValueError("technical-only data requires min_market_cap to be 0")
    if config.get("price_adjustment") != "unadjusted":
        raise ValueError("technical-only data requires price_adjustment to be unadjusted")
```

Call both config validators before loading bars. Add `parser.add_argument("--metadata", help="Optional import metadata JSON")`; if supplied, load JSON with UTF-8, append its scope, dates, price adjustment, and `field_limitations` to `report.md`, and append the sentence `本报告为技术条件版，不验证历史市值与ST筛选。` when the scope label matches the constant.

Create `config/event_study_technical_only.json` by copying every frozen field from `event_study_default.json`, setting `min_market_cap` to `0`, and adding exactly the two technical-only fields shown in the interface test.

- [ ] **Step 4: Document the exact two-command workflow**

```powershell
& $py -m a_share_backtesting.tdx_import `
  --source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw `
  --output data\daily_bars_technical.csv `
  --metadata data\daily_bars_technical.metadata.json
& $py -m a_share_backtesting.event_study_run `
  --data data\daily_bars_technical.csv `
  --config config\event_study_technical_only.json `
  --metadata data\daily_bars_technical.metadata.json `
  --output outputs\event_study_technical_2026h1
```

In `README.md`, state the required 120-trading-day preheat, unadjusted-price convention, excluded code prefixes, and that results are not the full original formula without point-in-time market cap/ST data.

- [ ] **Step 5: Verify and commit the scope disclosure**

```powershell
& $py -m unittest discover -s tests -v
git add config/event_study_technical_only.json src/a_share_backtesting/data_contract.py src/a_share_backtesting/event_study_run.py tests/test_data_contract.py tests/test_event_study.py README.md
git commit -m "feat: disclose technical-only event study scope"
```

Expected: all tests pass.

### Task 4: Run, audit, and record the frozen technical-only study

**Files:**
- Create ignored outputs: `data/daily_bars_technical.csv`, `data/daily_bars_technical.metadata.json`, `outputs/event_study_technical_2026h1/*`
- Modify: `DEVELOPMENT_STATUS.md`

**Consumes:** the Task 2 importer and Task 3 configuration/report support.

**Produces:** a reproducible result directory plus a cross-machine handoff record containing the exact input root, command, source/coverage counts, test result, commit IDs, and known limitations.

- [ ] **Step 1: Run the complete automated suite before touching real data**

```powershell
& $py -m unittest discover -s tests -v
```

Expected: all tests pass with no test failure.

- [ ] **Step 2: Import the supplied data and preserve the quality report**

```powershell
& $py -m a_share_backtesting.tdx_import --source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --output data\daily_bars_technical.csv --metadata data\daily_bars_technical.metadata.json
```

Expected: exit code `0`; both files exist; metadata labels the data `technical_only_no_historical_market_cap_or_st`.

- [ ] **Step 3: Execute the frozen study**

```powershell
& $py -m a_share_backtesting.event_study_run --data data\daily_bars_technical.csv --config config\event_study_technical_only.json --metadata data\daily_bars_technical.metadata.json --output outputs\event_study_technical_2026h1
```

Expected: exit code `0`; output contains `signal_audit.csv`, `events.csv`, `date_portfolios.csv`, `summary.csv`, `control_distribution.csv`, `control_summary.json`, and `report.md`.

- [ ] **Step 4: Audit timing and artefact completeness with a read-only check**

```powershell
& $py -c "import pandas as pd; from pathlib import Path; p=Path('outputs/event_study_technical_2026h1'); e=pd.read_csv(p/'events.csv'); s=pd.read_csv(p/'summary.csv'); assert {'legacy','bbi','b1'} == set(s['variant']); assert {2,5,10,20} == set(s['horizon']); f=e[e.status.eq('filled')]; assert (pd.to_datetime(f.signal_date) < pd.to_datetime(f.entry_date)).all(); assert (pd.to_datetime(f.entry_date) < pd.to_datetime(f.exit_date)).all(); assert e.loc[e.status.ne('filled'), ['gross_return','net_return']].isna().all().all(); print({'events':len(e),'filled':len(f),'summary_rows':len(s)})"
```

Expected: no assertion failure. Preserve the printed counts verbatim in `DEVELOPMENT_STATUS.md`.

- [ ] **Step 5: Update the handoff status and commit only source-controlled files**

Add the frozen-run date, source root, coverage from metadata, exact commands, audit output, technical-only limitation, all verification results, latest commit IDs, and next action to `DEVELOPMENT_STATUS.md`. Do not stage the input CSV or output directory.

```powershell
git add DEVELOPMENT_STATUS.md
git commit -m "docs: record technical-only event study run"
git push origin codex/b1-event-study
```

## Self-Review

- Spec coverage: Task 1 implements the 32-byte parser and code scope; Task 2 performs full-universe import and metadata; Task 3 freezes the technical-only configuration and surfaces limitations; Task 4 imports, runs, audits and preserves the handoff evidence.
- Type consistency: `read_tdx_day_file` supplies the rows consumed by `import_tdx_daily_bars`; that function supplies the CSV and JSON consumed by `event_study_run`; `validate_technical_only_config` is called by the runner before signal construction.
- Scope: No remote data retrieval, historical-field estimation, portfolio simulation, or post-result parameter tuning is included.
