# B1 staged-exit backtest design

## Purpose

Add a new close-entry B1 backtest mode that measures staged take-profit and stop-loss exits instead of valuing every event only at the T+N close.

The current `close-entry-b1` mode is useful as a fixed-horizon benchmark, but it over-simplifies the intended trading process. The new mode keeps the same B1 signal selection and signal-day close entry, then simulates conservative intraday high/low triggers during the holding window.

The first version covers B1 only. It does not change `legacy`, `bbi`, or the existing `close-entry-b1` outputs.

## Mode

Add a new streaming CLI mode:

```powershell
--mode staged-exit-b1
```

It should share the existing arguments used by `close-entry-b1`:

- `--source`
- `--config`
- `--output`
- `--analysis-start`
- `--analysis-end`
- `--horizons`
- `--stock-pool`

For the first implementation, exit parameters are fixed in code and recorded in metadata:

- Entry: B1 signal-day close.
- Observation window: T+1 through T+N for each requested horizon.
- Take-profit levels:
  - +5% sells one third of the original position.
  - +10% sells one third of the original position.
  - +15% sells all remaining position.
- Stop-loss level:
  - -5% sells all remaining position.
- Same-day conflict rule:
  - If the day's low triggers stop-loss and the day's high triggers take-profit, process stop-loss first and end the event.
- Fill prices:
  - Trigger fills use the threshold price, not the day's high or low.
  - Expiry fills use the T+N close.

## Event Flow

For each B1 first-trigger event:

1. Set `entry_price` to the signal day's close.
2. Set `remaining_fraction` to `1.0`.
3. Iterate through the post-entry holding window, from T+1 to T+N.
4. On each day, check stop-loss first:
   - If `low <= entry_price * 0.95`, sell all remaining fraction at `entry_price * 0.95`, record a stop-loss fill, and stop processing the event.
5. If stop-loss did not trigger, check take-profit levels in ascending order:
   - If `high >= entry_price * 1.05` and the +5% level has not filled, sell one third.
   - If `high >= entry_price * 1.10` and the +10% level has not filled, sell one third.
   - If `high >= entry_price * 1.15` and the +15% level has not filled, sell all remaining fraction.
6. If multiple take-profit levels are crossed on the same day, fill them all in ascending level order after the stop-loss check.
7. If the event still has remaining position after T+N, sell the remaining fraction at the T+N close.

T+N is therefore a maximum observation window, not a forced holding period.

## Return Calculation

Each event return is the weighted sum of realized fills:

```text
event_return = sum(sold_fraction * (fill_price / entry_price - 1))
```

The sold fractions should sum to `1.0` for filled events. The mode can ignore lot sizing in the first version, matching the existing close-entry B1 percentage-return style.

An event is a win when `event_return > 0`.

## Drawdown Calculation

The mode should report two drawdown fields:

- `max_intraday_drawdown`: the worst intraday low during the active holding period relative to entry price. This preserves comparability with the current close-entry report.
- `position_weighted_drawdown`: a conservative approximation of position-level drawdown after partial exits. For each day while position remains, compute the remaining position's low-price loss relative to entry and multiply by the remaining fraction before any same-day exit. Use the minimum value observed during the event.

When a stop-loss triggers, both drawdown fields should include the stop-loss day. If the event exits fully before T+N, later days are not considered.

## Outputs

Write staged-exit artifacts separately from the existing close-entry artifacts:

- `staged_exit_events.csv`
- `staged_exit_fills.csv`
- `staged_exit_summary.csv`
- `staged_exit_metadata.json`
- `staged_exit_report.md`

`staged_exit_events.csv` should contain one row per selected B1 signal and horizon:

- `event_id`
- `code`
- `name`
- `horizon`
- `signal_date`
- `entry_price`
- `final_exit_date`
- `status`
- `exit_reason`
- `net_return`
- `win`
- `max_intraday_drawdown`
- `position_weighted_drawdown`
- `take_profit_fill_count`
- `stop_loss_triggered`
- `remaining_fraction_at_expiry`

`staged_exit_fills.csv` should contain one row per realized sell fill:

- `event_id`
- `code`
- `horizon`
- `signal_date`
- `fill_date`
- `fill_type`
- `trigger_return`
- `fill_price`
- `sold_fraction`
- `remaining_fraction_after_fill`
- `fill_return`

`staged_exit_summary.csv` should aggregate by horizon:

- `horizon`
- `event_count`
- `mean_net_return`
- `median_net_return`
- `win_rate`
- `mean_intraday_drawdown`
- `worst_intraday_drawdown`
- `mean_position_weighted_drawdown`
- `worst_position_weighted_drawdown`
- `mean_take_profit_fill_count`
- `stop_loss_rate`
- `expiry_exit_rate`

Metadata must record the fixed rule, same-day conflict policy, source path, stock-pool path/count, analysis dates, horizons, processed code count, event count, and technical-only field limitations.

## Comparison Workflow

The intended comparison is:

1. Run existing `close-entry-b1` for the same source, date range, horizons, and stock pool.
2. Run new `staged-exit-b1` with the same inputs.
3. Compare:
   - average return,
   - median return,
   - win rate,
   - average and worst intraday drawdown,
   - position-weighted drawdown,
   - stop-loss rate,
   - expiry exit rate.

This keeps the fixed T+N close result as the baseline and makes it clear whether staged exits improve return, win rate, or drawdown.

## Testing

Add focused unit tests for:

- A +5% high sells one third at the +5% threshold price.
- A day that crosses +5% and +10% fills both take-profit levels in order.
- A same-day stop-loss and take-profit conflict exits by stop-loss only.
- A T+N event with remaining position exits the remainder at T+N close.
- Event return is the weighted sum of fills.
- Summary metrics include win rate, stop-loss rate, and expiry exit rate.
- The streaming CLI writes all staged-exit output files and stock-pool metadata.

Then run the existing full test suite with the bundled Python runtime.
