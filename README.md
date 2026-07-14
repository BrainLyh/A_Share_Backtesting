# A 股 B1 信号事件研究

本项目当前只验证技术信号的历史统计有效性，不做连续持仓或自动交易。

第一阶段比较三组日线收盘信号：

- `legacy`：原通达信缩量回撤公式；
- `bbi`：原公式加 BBI 多头向上过滤；
- `b1`：J 值低位后右侧转强确认。

每个信号均按下一交易日开盘入场，分别测量 2、5、10、20 个完整交易日后的收益、最大不利波动、收盘最大回撤，并与同日随机对照组比较。

## 运行事件研究

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m a_share_backtesting.event_study_run `
  --data data\daily_bars.csv `
  --config config\event_study_default.json `
  --output outputs\event_study_2026h1
```

输入应在首个分析日前保留至少 120 个交易日的预热数据，并覆盖最后一个信号日之后最长持有期及退出日。当前基线不要求历史主线池；只有提供逐日、无未来信息的 `in_core_pool` 后，才可声称验证了完整六步法。

开发计划见 [B1 Signal Event Study Implementation Plan](docs/superpowers/plans/2026-07-13-b1-event-study.md)。尚未接入真实历史数据，也尚未生成策略表现结论。
