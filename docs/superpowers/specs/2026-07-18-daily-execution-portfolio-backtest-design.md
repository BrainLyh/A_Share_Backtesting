# Intraday B1 execution and portfolio backtest design

## Purpose

Upgrade the B1 research runner into an auditable five-minute portfolio backtest that matches the intended trading workflow: scan during D day, enter near the close on D day, enforce A-share T+1 selling, hold no more than three stocks, and measure account return and drawdown after realistic execution constraints.

The existing `close-entry-b1`, `staged-exit-b1`, and `trend-runner-b1` modes remain unchanged as historical research baselines. The new mode is separate and becomes the preferred source for investability claims.

## Confirmed strategy

- Scan at 14:40, 14:45, and 14:50 using only completed data through each timestamp.
- Scheme A confirmation: a code enters the intraday candidate set at its first true B1 scan and must still satisfy B1 at 14:50.
- Enter during 14:50-14:55 using the 14:55 five-minute close plus 5 basis points of adverse buy slippage.
- A position bought on D cannot be sold until D+1.
- Hold at most three codes. The confirmed canonical mode targets one third of account NAV at entry. A separately labeled risk-control sensitivity targets one quarter and leaves at least 25% cash when three positions are full.
- Rank excess candidates by first trigger time ascending, 14:50 signal strength descending, then code ascending.
- Preserve the latest trend-runner exits: +10% sells one third, +20% sells one third, ATR stop sells all remaining, and the final one third exits on a 15% completed-close drawdown or D+5 expiry.
- Use five-minute bars for exits. Within one bar, process stop loss before take profit before residual drawdown before expiry.
- Apply a 10% five-minute volume participation cap to every fill.
- Use CNY 1,000,000 initial cash and no leverage.

The CLI rejects `max_positions` outside 1-3 and `participation_rate` above 10%. These are hard strategy constraints, not permissive tuning parameters.

## Data scope

### Inputs

The canonical runner requires:

- Tongdaxin `.lc5` files from `vipdoc/{sh,sz,bj}/fzline`.
- Daily raw and qfq bars with a per-code, per-date qfq scale.
- An explicit stock-pool CSV.
- Existing B1 and transaction-cost configuration.

The downloaded AI/semiconductor data contains 170 usable pool codes from 2026-04-09 through 2026-07-17. Code `835438` is absent from both the current daily/qfq snapshot and five-minute files, so it is excluded with an audit reason rather than silently dropped.

The `.lc5` amount field is not used. Record-level checks found amount/volume values outside bar ranges in a small subset of records. Strategy volume and liquidity constraints use the `.lc5` volume field only.

### Qfq alignment

Signals, ATR, thresholds, returns, and mark-to-market valuation use qfq prices. Raw five-minute OHLC is multiplied by the matching day's qfq scale. Raw prices, raw volume, raw preclose, and physical share quantities are retained for lot sizing, legal price limits, participation caps, and transaction costs.

Before a run, validate that:

- every `.lc5` file length is divisible by 32 bytes,
- timestamps are unique and strictly increasing,
- complete trading days contain the exact expected 48 timestamps, including 15:00,
- scan and entry bars exist,
- OHLC relationships are valid,
- the 15:00 raw minute close agrees with the raw daily close within tick tolerance,
- qfq scales are finite and positive.

Malformed files and days are rejected and written to the data audit without aborting other codes. No bar is synthesized.

### Research windows

Produce two canonical runs:

1. Same-window comparison through 2026-07-15, matching the prior published report end date.
2. Latest-data run through 2026-07-17.

Open positions at the data boundary are marked to market and remain excluded from closed-trade win rate. Closed-trade metrics are the observable-lifecycle cohort; the report always shows the open count beside them.

## Intraday B1 signal

### Provisional daily bar

At each scan, construct a provisional D-day daily bar:

- open: first five-minute open of D,
- high and low: extrema through the scan bar,
- close: scan bar close,
- volume: cumulative five-minute volume through the scan bar.

Append this provisional bar to completed qfq daily history and calculate BBI, KDJ, DIF, ATR, and the rolling five-day volume mean. This reproduces the information available on a live daily chart and avoids using D-day close or full-day volume before it exists.

### First-trigger state

A code can become a candidate only when the prior completed trading day's B1 state is available and false. Missing prior-day state is rejected as `missing_prior_day_state`, not treated as false. A code already held cannot create another entry. After exit, the code cannot re-enter on the same day. A later entry still requires the immediately prior completed daily B1 state to be false.

Candidates that lose B1 by 14:50, exceed capacity, lack cash, or cannot trade are rejected for D and do not remain queued for the next day.

### Capacity ranking

At 14:50, surviving candidates are sorted by:

1. first true scan time ascending,
2. existing `signal_strength` at 14:50 descending,
3. code ascending.

The ranking is a deterministic capacity rule, not independently validated alpha. Reports disclose this limitation.

## Entry execution

At 14:55, process exits for existing positions before new entries. Positions fully closed by then release cash and a slot. Positions scheduled to close at 15:00 still occupy a slot.

For each ranked candidate while fewer than three codes are held:

1. Target notional is one third of the pre-entry account NAV snapshot.
2. Base price is the 14:55 raw close; adverse buy slippage is 5 basis points and cannot exceed the legal upper limit.
3. Maximum shares are 10% of the 14:55 bar volume, rounded down to a 100-share lot.
4. Desired shares are also rounded down to a 100-share lot and reduced until cash covers notional plus commission.
5. Zero-volume, suspended, or one-price upper-limit bars reject the entry.
6. A partial entry occupies one slot and is never topped up later.

All candidates use the same pre-entry NAV snapshot so candidate ordering does not change target weights. Cash is consumed in deterministic rank order.

## Exit execution

### Frozen thresholds

ATR14 is calculated from the 14:50 provisional qfq daily bar and frozen at entry. The stop distance is:

```text
clamp(1.5 * ATR14 / adjusted_entry_price, 6%, 10%)
```

Take-profit and stop thresholds use adjusted economic entry cost including buy slippage:

- +10%: sell one third of original units,
- +20%: sell another one third of original units,
- stop: sell every remaining unit,
- residual: after two thirds have been sold, sell the remainder at 15% below the highest prior completed five-minute close,
- expiry: sell remaining units at the D+5 15:00 close.

The residual peak is tracked from entry but updated only after the current bar has been processed. The current bar close cannot create a peak used against the same bar low.

### Chronology and conflicts

No exit is evaluated on entry day. From D+1 onward, each bar is processed in this order:

1. persistent stop order,
2. newly triggered ATR stop,
3. pending and newly triggered +10% take profit,
4. pending and newly triggered +20% take profit,
5. residual drawdown,
6. D+5 expiry.

If a bar spans both stop and take-profit thresholds, the stop wins and cancels pending take-profit orders. If multiple take-profit levels trigger, lower thresholds receive volume first. A gap beyond a threshold uses the bar open; an intrabar cross uses the threshold price. Sell slippage is 5 basis points in the adverse direction and cannot pass the legal lower limit.

Each fill is capped at 10% of that bar's raw volume. Unfilled sell quantity persists to the next bar and executes at the next executable open, subject to the same participation cap. A one-price lower-limit bar cannot fill a sell. A take-profit sell at an upper limit may fill, subject to participation.

D+5 means the fifth trading day after D. An expiry order is submitted at the D+5 15:00 close. Quantity delayed by limit locks or participation remains open until the first executable bars and is labeled `overtime_exit`.

### Share allocation

Entry shares are 100-share lots. The first and second target slices are each the largest 100-share lot not exceeding one third of original shares. All rounding remainder belongs to the residual slice. Final liquidation sells the exact remaining position so no economic units remain.

## Corporate-action accounting

Store share quantities in entry-date raw-share units. At each timestamp, the ratio between the current qfq scale and entry qfq scale converts marked value, executable notional, modeled slippage, and the volume cap back to that entry basis. This preserves total-return continuity without pretending that the backtester separately posted cash dividends or changed the physical share ledger.

The qfq input audit identifies adjustment jumps before the portfolio run. The ledger reconciles cash, adjusted market value, executable notional, and the total-return contribution, but does not currently add a per-position corporate-action flag.

## Portfolio ledger

Maintain a single chronological account with:

- cash,
- open positions and sellable dates,
- pending exit orders,
- realized and unrealized P&L,
- cumulative commission, stamp duty, and modeled slippage,
- five-minute and end-of-day NAV,
- exposure and drawdown.

Sell proceeds completed before 14:55 are available for same-day entries. Later proceeds cannot retroactively fund an earlier entry. Cash interest is zero. Negative cash, duplicate open positions, and leverage are forbidden.

## Transaction costs

Use the existing defaults for each actual partial fill:

- commission: 0.03% on buys and sells,
- minimum commission: CNY 5 per fill,
- sell stamp duty: 0.05%,
- adverse slippage: 5 basis points on buys and sells.

The report separates commission, stamp duty, and slippage drag. Brokerage commission is treated as the configured all-in brokerage rate; no additional exchange levy is invented.

## Tradeability

Price-limit checks operate in raw space. When explicit limit columns are unavailable, a one-price bar is compared with the known 5%, 10%, 20%, and 30% ratios around raw preclose within tick tolerance. This recognizes likely locks but does not reconstruct the complete historical board or ST regime.

- Zero-volume or absent bars cannot fill.
- A one-price upper-limit 14:55 bar blocks entry.
- A one-price lower-limit bar blocks exit.
- Merely touching a limit does not block a fill.

Every uncertain decision is labeled `historical_st_status_unavailable`. The report must not imply complete historical ST or suspension coverage.

## Metrics

Primary account metrics:

- total net return,
- five-minute close NAV maximum drawdown,
- conservative five-minute low NAV maximum drawdown,
- end-of-day NAV maximum drawdown,
- average and maximum exposure,
- turnover and capital utilization,
- maximum simultaneous positions,
- commission, tax, and slippage drag.

Closed-trade metrics:

- net win rate,
- mean and median net return,
- payoff ratio and profit factor,
- expectancy,
- average holding period,
- maximum consecutive losses,
- stop, take-profit, residual, expiry, and overtime exit rates,
- maximum adverse excursion.

Open positions are included in NAV return but excluded from closed-trade win rate. Annualized statistics are secondary and omitted when the observation window is shorter than 90 calendar days.

Capital utilization is the time average of five-minute gross exposure divided by initial cash. Average exposure instead divides each five-minute gross exposure by contemporaneous NAV.

## Comparisons

Separate signal and portfolio effects with three layers:

1. Published daily B1 trend-runner baseline.
2. Rolling intraday B1 events with unlimited capital and no three-position constraint.
3. Canonical portfolio with CNY 1,000,000, three positions, costs, limits, and participation.

Use the same signal cutoff when comparing mature cohorts. Event-level mean return is never presented as account return. The fixed 2026-07-15 stock pool is a retrospective universe and its results are not called alpha.

## Outputs

Each run writes:

- `data_audit.csv`
- `signal_scans.csv`
- `candidates.csv`
- `orders.csv`
- `fills.csv`
- `positions.csv`
- `trades.csv`
- `rejections.csv`
- `nav_5m.csv`
- `nav_daily.csv`
- `portfolio_summary.csv`
- `trade_summary.csv`
- `comparison.csv`
- `run_manifest.json`
- `report.md`

Machine-readable rejection and status reasons include missing data, no B1 persistence, prior-day B1 true, duplicate position, capacity, cash, volume cap below one lot, suspension, upper-limit lock, lower-limit lock, insufficient lifecycle data, and overtime exit.

## Invariants

Every run enforces:

- cash is not below a one-cent tolerance,
- at most three codes are open,
- one code has at most one position,
- no sell occurs on entry day,
- entry shares are non-negative 100-share lots,
- sold units never exceed remaining units,
- fill quantity never exceeds 10% of bar volume,
- all final slices reconcile to original units,
- NAV equals cash plus marked position value,
- timestamps are chronological,
- every rejected order has a reason.

The CLI fails before final summaries on negative cash or non-finite NAV, while unit tests cover the remaining chronology and fill invariants. Run manifests record the repository-relative Git revision and dirty flag. Together with rejection files and input hashes, they provide the audit trail for completed runs.

## Testing

Use test-driven development for:

- `.lc5` decoding, date/time decoding, and malformed files,
- provisional daily bars and no future volume leakage,
- 14:40/14:45/14:50 Scheme A persistence,
- prior-day false state and re-arm behavior,
- deterministic candidate ranking,
- 14:55 close entry with slippage, lots, cash, and participation,
- maximum three positions and no pyramiding,
- T+1 enforcement,
- open-gap stop and profit fills,
- stop-first five-minute conflicts,
- persistent partial orders and volume caps,
- residual peak using prior completed closes,
- one-price upper/lower-limit behavior,
- D+5 and overtime exits,
- qfq/raw reconciliation across an adjustment jump,
- per-fill minimum commissions and sell-only stamp duty,
- five-minute, conservative-low, and daily drawdowns,
- open-position and mature-cohort statistics,
- CLI output and manifest completeness.

Run focused tests after each component, then the full existing suite and a deterministic end-to-end fixture before using real data.

## Research limitations

- The 2026-07-15 stock pool is used retrospectively for June and therefore has point-in-time membership bias.
- Historical ST, suspension reason, market capitalization, and order-book queue data are incomplete.
- Five-minute bars cannot determine tick order within one bar; conservative stop-first ordering remains an assumption.
- The 10% participation rule is a capacity model, not proof of actual queue priority.
- Strategy changes after the AI/semiconductor result must be selected on a training segment and evaluated unchanged on held-out dates and other sector pools.

These limitations must appear in every report.
