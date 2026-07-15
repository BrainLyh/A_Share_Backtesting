# Close-Entry B1 Backtest

- Analysis window: 2026-06-01 to 2026-07-15
- Entry: signal-day close.
- Exit: future close by holding horizon.
- Drawdown: lowest intraday low during the holding window, capped at 0 when price never falls below entry.
- Scope: technical-only; historical market-cap, ST and suspension filters are not validated.
- Field limitations: historical_market_cap_unavailable, historical_st_status_unavailable, suspension_status_unavailable

## Summary

| horizon | event_count | mean_net_return | median_net_return | win_rate | mean_intraday_drawdown | median_intraday_drawdown | worst_intraday_drawdown | mean_close_drawdown | worst_close_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 119 | -0.0070947440564186216 | -0.005831182487333941 | 0.4957983193277311 | -0.041994145391777024 | -0.030601659751037347 | -0.1480043149946062 | -0.028787679975368786 | -0.1467098166127293 |
| 2 | 117 | -0.02011521677967088 | -0.02382146439317956 | 0.4017094017094017 | -0.06820089575812589 | -0.056087551299589644 | -0.23077932473394835 | -0.052920997077970225 | -0.20873410579080665 |
| 3 | 117 | -0.007754358096562232 | -0.02238544945785237 | 0.4358974358974359 | -0.08754807526624404 | -0.073968705547653 | -0.2323539832298871 | -0.06350581225645155 | -0.20873410579080665 |
| 4 | 116 | -0.014317877112698331 | -0.02573876634415595 | 0.41379310344827586 | -0.09568633323207558 | -0.09081357334173634 | -0.2491909385113269 | -0.07603198767800559 | -0.24304207119741106 |
| 5 | 84 | 0.028521196616925933 | 0.01451382118609612 | 0.5952380952380952 | -0.07622007681129991 | -0.060168042474010475 | -0.3090022675736961 | -0.05624025577414625 | -0.2857142857142857 |
