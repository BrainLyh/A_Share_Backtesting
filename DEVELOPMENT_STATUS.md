# 开发进度报告

最后更新：2026-07-13（Asia/Shanghai）

## 当前目标

实现 B 层 A 股 B1 信号事件研究：对 `legacy`、`bbi`、`b1` 三组日线收盘信号，分别计算下一交易日开盘入场后持有 2、5、10、20 个完整交易日的结果，并与同日随机对照组比较。

## 工作状态

- 开发分支：`codex/b1-event-study`
- 当前工作树：随机器而变；以分支 `codex/b1-event-study` 和本文件的提交号为准。
- 基线提交：`06c3899`（`chore: establish B1 event study baseline`）
- 实施计划：[docs/superpowers/plans/2026-07-13-b1-event-study.md](docs/superpowers/plans/2026-07-13-b1-event-study.md)
- 已完成：清理此前连续组合回测路径；保留指标、信号基础和最小测试。
- 已验证：`python -m unittest discover -s tests -v`，2 项通过。
- 已完成：Task 1（数据契约与冻结实验配置），提交 `29f9e8d`。
- 验证：`python -m unittest discover -s tests -v`，7 项通过。
- 已完成：Task 2（`legacy`、`bbi`、`b1` 信号变体与首次触发标记），提交 `2f3332f`。
- 验证：`python -m unittest discover -s tests -v`，10 项通过。
- 已完成：Task 3（事件入场、持有期、未成交状态、收益与回撤测量），提交 `ab3fcb3`。
- 验证：`python -m unittest discover -s tests -v`，14 项通过。
- 已完成：Task 4（按信号日汇总与确定性随机对照组），提交 `50457f9`、`23d76c9`。
- 验证：`python -m unittest discover -s tests -v`，17 项通过。
- 已完成：Task 5（事件研究命令行入口、产物写入和研究报告），提交 `4a571ec`。
- 验证：`python -m unittest discover -s tests -v`，18 项通过。
- 下一任务：Task 6（使用真实历史数据运行冻结实验并审计研究产物）。

## 已确定的研究口径

- 技术基线不要求 `in_core_pool`；有历史主线池后再作为可选过滤器比较增量价值。
- 信号在 `D` 收盘后生成；下一交易日开盘入场。
- 持有期 `H` 使用完整交易日：信号行 `i`，入场行 `i+1` 开盘，退出行 `i+1+H` 开盘。
- 同一股票在同一 `variant + horizon` 的前一事件退出前，不重复计入新事件。
- 停牌、涨跌停无法成交时记录未成交状态，不虚构收益。

## 下一步

1. 准备带 120 个交易日预热期的本地历史日线数据和冻结配置。
2. 运行 CLI，检查输出文件、信号/入场/退出时序及未成交事件计数。
3. 记录数据来源、覆盖日期、基准和复权口径；不在结果出现后修改参数。

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
