# QFQ data adapter design

## Purpose

Fix the price-adjustment layer before doing more B1 parameter tuning. Recent validation with `688200` showed that raw Tongdaxin `.day` prices can contain ex-rights jumps that look like trading drawdowns. On 2026-06-11, raw close moved from 467.46 to 315.00, while `rustdx + gbbq` reports adjusted `preclose=315.047287`; the real adjusted day return is approximately flat, not a -32% crash.

The first implementation should build a minimal, testable adapter that converts `rustdx day -g gbbq` CSV output into front-adjusted OHLC columns and explicit audit fields. Strategy reruns come after this adapter is verified.

## Scope

In scope:

- Add a pure Python qfq transformation for data frames that already contain raw OHLC and `preclose`.
- Preserve raw OHLC columns.
- Add `qfq_open`, `qfq_high`, `qfq_low`, `qfq_close`.
- Add audit columns that expose adjustment jumps.
- Add a small CLI that reads a rustdx CSV and writes adjusted CSV plus audit CSV.
- Validate with unit tests and the `688200` sample.

Out of scope for this step:

- Downloading or invoking `rustdx` from inside the project.
- Parsing binary `gbbq` directly.
- Replacing all backtest modes with qfq input.
- Retuning `close-entry`, `staged-exit`, or `trend-runner` parameters.

## Adjustment Rule

The adapter uses `preclose` as the authoritative adjusted previous close for each row.

For each code sorted by date:

1. Start with scale `1.0` for every row.
2. For row `i > 0`, compare `preclose[i]` with the previous raw close `close[i-1]`.
3. If the ratio `preclose[i] / close[i-1]` differs materially from `1.0`, multiply all earlier rows' scale by that ratio.
4. Compute qfq OHLC as raw OHLC multiplied by the final row scale.

This anchors the most recent raw price at scale `1.0` and adjusts historical prices backward.

## Audit Columns

The adjusted output should include:

- `raw_prev_close`
- `preclose_to_raw_prev_close_ratio`
- `adjustment_jump`
- `qfq_scale`
- `raw_gap_return`
- `adjusted_day_return`

For `688200` on 2026-06-11, expected behavior is:

- `raw_gap_return` is approximately `-32.61%`.
- `adjusted_day_return` is approximately `-0.015%`.
- Earlier prices before 2026-06-11 are scaled down.
- The adjusted 2026-06-11 low no longer triggers the old raw-data ATR stop sample.

## Files

- New module: `src/a_share_backtesting/qfq.py`
- New CLI: `src/a_share_backtesting/qfq_run.py`
- New tests: `tests/test_qfq.py`
- Plan document: `docs/superpowers/plans/2026-07-16-qfq-data-adapter.md`

## Verification

Run:

```powershell
$env:PYTHONPATH = "$PWD\src"
& 'C:\Users\yuhang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

Then run a manual 688200 audit from the rustdx CSV in `outputs/rustdx_verify/688200_with_gbbq.csv` and confirm that 2026-06-11 is treated as an adjustment day rather than a trading crash.
