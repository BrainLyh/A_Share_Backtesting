# Staged-Exit B1 Backtest

- Analysis window: 2026-06-01 to 2026-06-30
- Entry: signal-day close.
- Take profit: +5% sells one third, +10% sells one third, +15% sells all remaining.
- Stop loss: -5% sells all remaining.
- Same-day conflict policy: stop-loss before take-profit.
- Expiry: remaining position exits at the horizon-day close.
- Scope: technical-only; historical market-cap, ST and suspension filters are not validated.
- Field limitations: historical_market_cap_unavailable, historical_st_status_unavailable, suspension_status_unavailable

## Summary

| horizon | event_count | mean_net_return | median_net_return | win_rate | mean_intraday_drawdown | worst_intraday_drawdown | mean_position_weighted_drawdown | worst_position_weighted_drawdown | mean_take_profit_fill_count | stop_loss_rate | expiry_exit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 70 | 0.009377137399139692 | 0.00940517765925497 | 0.6 | -0.03166516127336665 | -0.09377817853922465 | -0.03166516127336665 | -0.09377817853922465 | 0.42857142857142855 | 0.22857142857142856 | 0.7428571428571429 |
| 2 | 70 | 0.008627197807999625 | 0.0009015993414758783 | 0.5142857142857142 | -0.04021796901668884 | -0.09377817853922465 | -0.039862715987628736 | -0.09377817853922465 | 0.8285714285714286 | 0.4142857142857143 | 0.4857142857142857 |
| 3 | 69 | 0.014953953632720488 | -0.016666666666666673 | 0.4782608695652174 | -0.04484723924354013 | -0.11738746690202995 | -0.042479920721157007 | -0.09377817853922465 | 1.1014492753623188 | 0.5072463768115942 | 0.30434782608695654 |
| 4 | 68 | 0.01607308310437655 | -0.016666666666666673 | 0.4852941176470588 | -0.04637156741350677 | -0.11738746690202995 | -0.04267728619594844 | -0.09377817853922465 | 1.2647058823529411 | 0.5294117647058824 | 0.17647058823529413 |
| 5 | 67 | 0.018609767925306234 | -0.016666666666666673 | 0.4925373134328358 | -0.046636684622655175 | -0.11738746690202995 | -0.042506991539353195 | -0.09377817853922465 | 1.328358208955224 | 0.5373134328358209 | 0.13432835820895522 |
