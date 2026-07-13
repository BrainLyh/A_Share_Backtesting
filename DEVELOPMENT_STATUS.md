# 开发进度报告

最后更新：2026-07-13（Asia/Shanghai）

## 当前目标

实现 B 层 A 股 B1 信号事件研究：对 `legacy`、`bbi`、`b1` 三组日线收盘信号，分别计算下一交易日开盘入场后持有 2、5、10、20 个完整交易日的结果，并与同日随机对照组比较。

## 工作状态

- 开发分支：`codex/b1-event-study`
- 工作树：`C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`
- 基线提交：`06c3899`（`chore: establish B1 event study baseline`）
- 实施计划：[docs/superpowers/plans/2026-07-13-b1-event-study.md](docs/superpowers/plans/2026-07-13-b1-event-study.md)
- 已完成：清理此前连续组合回测路径；保留指标、信号基础和最小测试。
- 已验证：`python -m unittest discover -s tests -v`，2 项通过。
- 已完成：Task 1（数据契约与冻结实验配置），提交 `29f9e8d`。
- 验证：`python -m unittest discover -s tests -v`，7 项通过。
- 已完成：Task 2（`legacy`、`bbi`、`b1` 信号变体与首次触发标记），提交 `2f3332f`。
- 验证：`python -m unittest discover -s tests -v`，10 项通过。
- 下一任务：Task 3（事件入场、持有期、未成交状态、收益与回撤测量）。

## 已确定的研究口径

- 技术基线不要求 `in_core_pool`；有历史主线池后再作为可选过滤器比较增量价值。
- 信号在 `D` 收盘后生成；下一交易日开盘入场。
- 持有期 `H` 使用完整交易日：信号行 `i`，入场行 `i+1` 开盘，退出行 `i+1+H` 开盘。
- 同一股票在同一 `variant + horizon` 的前一事件退出前，不重复计入新事件。
- 停牌、涨跌停无法成交时记录未成交状态，不虚构收益。

## 下一步

1. 创建 `event_study.py`，将首次信号转换为不可重叠的持有期事件。
2. 测试下一开盘入场、2/5/10/20 日退出、涨停未买、停牌/跌停未卖及最大不利波动。
3. 通过全量测试后提交，并在本文件中写入提交号与 Task 4。

## 跨机器续作

1. 切换到 `codex/b1-event-study` 分支，并同步该分支的最新提交。
2. 先阅读本文件和实施计划；不要从 `main` 直接继续开发。
3. 设置运行环境后执行：

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest discover -s tests -v
```

4. 从“下一步”的第一条继续；完成一个任务后，更新本文件的已完成项、验证结果、提交号和下一步。
