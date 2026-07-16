# 开发进度报告

> 2026-07-16 qfq 数据适配器落地记录（优先阅读本节）

## 本次完成

- 新增 `src/a_share_backtesting/qfq.py`，可读取带 `preclose` 的 rustdx CSV 行情，并生成前复权 `qfq_open/qfq_high/qfq_low/qfq_close`。
- 新增 `src/a_share_backtesting/qfq_run.py`，提供最小 CLI：读取 rustdx 输出，写出完整 qfq 行情 CSV 和除权跳变审计 CSV。
- 保留原始 OHLC，并新增审计列：`raw_prev_close`、`preclose_to_raw_prev_close_ratio`、`adjustment_jump`、`qfq_scale`、`raw_gap_return`、`adjusted_day_return`。
- 已用真实 688200 样本验证：2026-06-11 原始 close 相比 2026-06-10 raw close 的跳变约 `-32.6146%`；使用 `D:\apps\tdx\T0002\hq_cache\gbbq` 后，rustdx 输出 `preclose=315.047287`，qfq 适配器识别出比例 `0.6739556`，调整后当日收益约 `-0.0150%`。
- 这说明 688200 的 2026-06-11 异常不应再被当成真实暴跌输入 ATR、止损、回撤、BBI/KDJ 等指标。

## 当前边界

- 当前实现是 qfq 适配层和审计工具，尚未把 qfq OHLC 正式接入主回测数据读取路径。
- 当前不提交 `outputs/rustdx_verify/` 和 `outputs/tools/rustdx.exe`，这些仍作为本地验证产物保留。
- 下一步应把 `price_adjustment=qfq` 接入 B1 close-entry、staged-exit、trend-runner，然后重跑 2026-06-01 至 2026-07-15 股票池结果。

## 验证

- 已运行全量单元测试：`PYTHONPATH=src python -m unittest discover -s tests -v`，54/54 通过。

> 2026-07-16 收尾记录：trend-runner 下一版参数与前复权验证（优先阅读本节）

## 本次完成

- 将 trend-runner 下一版策略参数调整为 `+10%/+20%` 分批止盈：触发 +10% 卖出 1/3，触发 +20% 再卖出 1/3，剩余 1/3 作为趋势底仓。
- trend-runner 默认不再使用 BBI 连续两日跌破作为底仓退出条件；新增 `--bbi-exit-timing disabled`，并保留 `same_close` / `next_open` 作为显式可选实验口径。
- 保留 ATR 初始止损：信号日 ATR14，默认 `min(max(1.5*ATR14/entry, 6%), 10%)`，当前仍是按盘中最低价触发的固定初始止损，不是移动止损。
- 保留 15% 底仓高点回撤作为下一版主退出规则：`--residual-drawdown-return -0.15`。
- 分析 688200 止损样本：当前未复权 TDX `.day` 数据中，2026-06-11 的 low=304.73、close=315.00，均显著低于 B1 买入价 441.00 对应的 ATR 止损价 396.90；这解释了为何回测会在 6 月 11 日触发止损。
- 统计“止损后修复”现象：旧版 `+6%/+12% + ATR + dd15` 的 20 日窗口中，ATR 止损样本 23 个，其中 14 个若单纯持有到 20 日为正收益，19 个单纯持有收益高于策略止损收益；新版 `+10%/+20% + ATR + dd15 + BBI disabled` 的 20 日窗口中，ATR 止损样本 24 个，其中 15 个单纯持有到 20 日为正收益，21 个单纯持有收益高于策略止损收益。
- 由止损日期集中度判断：止损事件高度集中于 2026-06-08、2026-06-11/12 等日期，倾向认为未复权价格跳变正在污染 ATR 止损、回撤和 BBI 判断，后续不应继续在未复权数据上细调止损。
- 验证 `rustdx` 前复权链路：已下载 Windows release `rustdx.exe` 并验证其可读取本项目 TDX `.day`；使用 `-g gbbq` 可输出 `preclose` 与 `factor`。官方配套样本 `sz000001.day + assets/gbbq` 能识别除权类日期并生成复权因子。
- 已将 rustdx 验证产物同步到真实项目 worktree 的 `outputs/rustdx_verify/`；该目录仍按 `outputs/` 忽略规则不进入 Git。

## 新版参数初测结果

- 输出目录：`outputs/trend_runner_b1_20260601_20260715_ai_semiconductor_pool_hsjday_long_atr_dd15_tp10_20_bbi_disabled`。
- 口径：AI/半导体股票池，2026-06-01 至 2026-07-15，horizon=5/10/15/20，买入价为 B1 当日收盘价，止盈为 +10%/+20%，止损为 ATR，底仓回撤为 -15%，BBI 退出禁用。
- 新版平均收益：

| 持仓天数 | 事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中回撤 | 止损率 | 到期退出率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 74 | 2.9405% | 4.5178% | 59.46% | -6.8900% | 33.78% | 66.22% |
| 10 | 70 | 5.9005% | 9.1226% | 58.57% | -7.3806% | 38.57% | 55.71% |
| 15 | 66 | 5.5554% | 9.9515% | 54.55% | -7.7991% | 45.45% | 31.82% |
| 20 | 46 | 3.4011% | -3.3806% | 45.65% | -9.2256% | 52.17% | 13.04% |

- 与旧版 `+6%/+12% + ATR + dd15` 相比，新版平均收益提高：5 日 2.2936% -> 2.9405%，10 日 4.6371% -> 5.9005%，15 日 4.3515% -> 5.5554%，20 日 2.5590% -> 3.4011%。
- 代价：新版止盈档后移后，胜率下降、止损率上升；例如 688200 旧版先在 +6% 卖出 1/3 后最终 -4.6667%，新版未触发 +10% 止盈，直接 ATR 止损为 -10%。

## rustdx 前复权验证结论

- `rustdx day` 不传 `-g/--gbbq` 时只解析未复权 OHLCV；传入 `-g gbbq` 后输出会增加 `preclose` 与 `factor`。
- 当前项目数据目录 `C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw` 只有 `sh/sz/bj` 市场日线目录，没有发现最新 `gbbq` 或 `T0002/hq_cache` 类通达信客户端缓存。
- 使用 rustdx 仓库示例 `assets/gbbq` 跑 688200 时，2026-06-11 仍未被识别为除权日：`preclose` 等于上一日原始 close，前复权结果仍等于未复权结果。因此 688200 尚未被修正，原因是缺少最新 gbbq/复权因子，不是 rustdx 命令链路不可用。
- 结论：下一轮必须先补齐真实最新 gbbq 或其他可靠前复权因子，再重跑 688200、688766、688037 等异常跳变样本；在此之前，不建议继续根据未复权数据优化 ATR 止损阈值。

## 开源工具借鉴记录

- `zjp-CN/rustdx`（https://github.com/zjp-CN/rustdx）：当前优先级最高。可读取 TDX `.day`，并在提供 `gbbq` 时输出 `preclose/factor`，适合作为本项目 qfq 数据层的第一候选。短期任务是补齐真实最新 gbbq 后验证 688200；中期任务是把 rustdx 输出接入 `price_adjustment=qfq`。
- `1nchaos/adata`（https://github.com/1nchaos/adata）：适合作为备用数据源和数据审计源。可用于补充股票列表、名称、行业/概念、行情交叉校验，尤其用于核对 TDX 未复权跳变和 qfq 结果是否合理；暂不建议直接替换本地 TDX 主数据源。
- `shy3130/tickflow-stock-panel`（https://github.com/shy3130/tickflow-stock-panel）：最值得借鉴回测工程架构。重点参考其 enriched 特征表、策略文件结构、组合回测、T+1/手续费/滑点/持仓约束、流式进度和复盘面板思路。后续本项目可从事件回测升级为“每日 14:30 选股 + 组合持仓 + 资金曲线”的组合回测。
- `khscience/OSkhQuant`（https://github.com/khscience/OSkhQuant）：更偏桌面 GUI、MiniQMT/xtquant、策略执行和实盘框架。短期不迁移其 GUI 架构，但可借鉴交易明细、风险指标、持仓限制、止损模块和 MyTT/通达信指标兼容思路。
- 当前借鉴顺序：先用 rustdx/qfq 修正数据口径；再用 tickflow 的 enriched 表与策略配置方式重构回测输入；再用 adata 做交叉校验与行业/概念补充；最后视实盘或 GUI 需求参考 OSkhQuant。

## 验证

- 已运行全量单元测试：`PYTHONPATH=src python -m unittest discover -s tests -v`，52/52 通过。
- 已验证 rustdx Windows release 可运行，并可解析本项目 TDX `.day` 单只股票输出 CSV。
- 已验证 rustdx 官方样本 `sz000001.day + assets/gbbq` 可生成 `preclose/factor`，并识别除权类日期。

## 未完成任务

1. 获取真实最新的通达信 `gbbq` 除权除息文件或等价前复权因子来源；当前本机和项目数据目录没有找到可直接用于生产回测的最新 gbbq。
2. 在拿到真实 gbbq 后，用 rustdx 重跑 688200，并验证 2026-06-11 的价格跳变是否被前复权消除。
3. 将前复权数据正式接入本项目数据层：新增 `price_adjustment=qfq` 口径，避免继续把未复权价格用于 ATR、BBI、KDJ、回撤和止损。
4. 建立数据质量审计表：重点检查 `preclose` 与上一日 raw close 的差异、factor 跳变、异常低开/除权日期、停牌缺口。
5. 使用前复权数据重跑 B1 close-entry、staged-exit、trend-runner，并重新评估 `+10%/+20% + ATR + dd15` 是否优于旧版参数。
6. 将 rustdx 验证流程整理为可重复脚本；当前只完成了手工验证，尚未形成项目内 CLI 或自动测试。
7. 决定是否提交精简后的 rustdx 验证摘要 CSV；当前完整验证产物仍在 ignored `outputs/rustdx_verify/`，未纳入版本库。

## 下一步建议

1. 先从通达信客户端复制最新 `gbbq`，或改用可提供 qfq factor 的可靠外部数据源。
2. 补一个最小 qfq adapter，只针对少量股票输出 qfq OHLC 与 factor 审计表。
3. 用 688200 作为回归样本，确认 qfq 后不再因未复权跳变误触发 ATR 止损。
4. qfq 口径确认后，再重跑 2026-06/2026-06-01 至 2026-07-15 股票池回测。
> 2026-07-16 trend-runner 参数矩阵初测（优先阅读本节）

## 本次完成

- 新增 `--mode trend-runner-b1`，用于测试“+6%/+12% 分批止盈、保留 1/3 趋势底仓”的 V2 方案。
- 支持两种 BBI 底仓退出口径：`--bbi-exit-timing same_close`（第二日跌破 BBI 当日收盘退出）与 `next_open`（确认后次日开盘退出）。
- 支持三类初始止损：固定 `-6%`、固定 `-8%`、`atr` 自适应止损；ATR 口径为信号日 ATR14，默认 `min(max(1.5*ATR14/entry, 6%), 10%)`。
- 支持底仓从最高收盘价回撤退出：本轮测试 `-8%` 与 `-10%` 两档。
- 已补充回归测试：趋势底仓连续两日跌破 BBI 的 same-close 与 next-open 退出、ATR 自适应止损避免固定百分比洗出、CLI 输出文件。

## 回测范围与产物

- 1-5 日矩阵：`same_close/next_open × sl6/sl8/atr × dd8/dd10`，分别跑 2026-06 与 2026-06-01 至 2026-07-15 两个窗口。
- 长持仓小矩阵：`same_close/next_open × sl6/atr × dd10`，跑 2026-06-01 至 2026-07-15，horizon 为 5/10/15/20。
- 汇总产物：`outputs/trend_runner_matrix_summary.csv` 与 `outputs/trend_runner_long_horizon_summary.csv`。

## 关键结果

- 1-5 日扩展窗口中，跨 horizon 平均收益最好的是 `sl6 + dd10`，平均收益约 1.1045%，平均盘中回撤约 -5.1107%；ATR+dd10 的 5 日收益更高（2.0547%），但跨 1-5 日平均收益低于 sl6+dd10。
- same-close 与 next-open 在本轮 1-5 日结果几乎相同，原因是短 horizon 内连续两日跌破 BBI 的样本很少，退出主要由止损、底仓高点回撤和到期退出触发。
- 长持仓对比显示，固定持有 close-entry 在 10/15/20 日明显吃到趋势收益：10 日平均 14.8821%、15 日 18.0742%、20 日 16.4198%。
- 当前 trend-runner 参数仍过于保守：ATR+dd10 的 10/15/20 日平均收益分别约 3.2759%、3.1421%、0.9595%，显著低于 close-entry 长持仓；sl6+dd10 更弱。
- BBI 连续两日跌破在长持仓中也只触发 1 个样本，说明当前 V2 的主要退出实际是止损与 10%高点回撤，不是 BBI 趋势破坏。

## 当前判断

- V2 框架方向仍有价值，但当前参数没有解决“趋势收益吃不到”的问题；`+6%/+12%` 分批止盈后，剩余 1/3 又被 `10%` 高点回撤过早卖出，右侧趋势收益被压掉。
- 下一轮应测试更宽的底仓退出：取消底仓高点回撤或放宽到 15%/20%，让 BBI 破位成为主退出条件；止损可优先保留 ATR 自适应或 `-8%`，不建议继续用 `-6%` 作为主版本。
- 若采用 14:30 实盘执行，same-close 仍值得保留；但研究报告默认应以 next-open 作为无未来函数保守口径。

## 验证

- 已运行完整单元测试：`python -m unittest discover -s tests -v`，51/51 通过。

> 2026-07-16 合并 staged-exit 分批止盈分支（优先阅读本节）

## 本次完成

- 已将远程实验分支 `origin/codex/staged-exit-b1` 快进合并到主开发线 `codex/b1-event-study`；该分支基于 `1ed8fa9`，新增提交为 `47a9948`、`5b97551`、`07a5623`。
- 新增 `--mode staged-exit-b1` 分批退出回测模式：B1 当日收盘买入；触发 5%、10%、15% 浮盈时分别卖出三分之一、三分之一、剩余仓位；触发 -5% 止损时退出剩余仓位；同日止损/止盈冲突按先止损处理；到期未退出部分按 horizon 日收盘价退出。
- 新增设计文档 `docs/superpowers/specs/2026-07-15-staged-exit-b1-design.md` 和计划文档 `docs/superpowers/plans/2026-07-15-staged-exit-b1.md`。
- 已把 staged-exit 与 close-entry 的对比输出提交到 `outputs/` 下，便于跨机器复核；这与上一轮“本地 outputs 未提交”的状态不同。

## 分批止盈结果摘要

### 2026-06-01 至 2026-06-30，AI/半导体股票池

| 持仓天数 | 事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中最大回撤 | 最差盘中最大回撤 | 平均分仓回撤 | 最差分仓回撤 | 平均止盈次数 | 止损率 | 到期退出率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 70 | 0.9377% | 0.9405% | 60.00% | -3.1665% | -9.3778% | -3.1665% | -9.3778% | 0.43 | 22.86% | 74.29% |
| 2 | 70 | 0.8627% | 0.0902% | 51.43% | -4.0218% | -9.3778% | -3.9863% | -9.3778% | 0.83 | 41.43% | 48.57% |
| 3 | 69 | 1.4954% | -1.6667% | 47.83% | -4.4847% | -11.7387% | -4.2480% | -9.3778% | 1.10 | 50.72% | 30.43% |
| 4 | 68 | 1.6073% | -1.6667% | 48.53% | -4.6372% | -11.7387% | -4.2677% | -9.3778% | 1.26 | 52.94% | 17.65% |
| 5 | 67 | 1.8610% | -1.6667% | 49.25% | -4.6637% | -11.7387% | -4.2507% | -9.3778% | 1.33 | 53.73% | 13.43% |

### 2026-06-01 至 2026-07-15，AI/半导体股票池

| 持仓天数 | 事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中最大回撤 | 最差盘中最大回撤 | 平均分仓回撤 | 最差分仓回撤 | 平均止盈次数 | 止损率 | 到期退出率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 119 | -0.0107% | 0.0923% | 51.26% | -4.1994% | -14.8004% | -4.1994% | -14.8004% | 0.45 | 36.13% | 60.50% |
| 2 | 117 | -0.2486% | -5.0000% | 39.32% | -5.3731% | -19.0984% | -5.1690% | -14.8004% | 0.74 | 55.56% | 34.19% |
| 3 | 117 | 0.0292% | -5.0000% | 35.90% | -5.7690% | -19.0984% | -5.3996% | -14.8004% | 0.90 | 63.25% | 21.37% |
| 4 | 116 | 0.0748% | -5.0000% | 35.34% | -5.8990% | -19.0984% | -5.4245% | -14.8004% | 1.00 | 65.52% | 12.93% |
| 5 | 84 | 1.4568% | -1.6667% | 46.43% | -4.8814% | -11.7712% | -4.4317% | -9.8413% | 1.26 | 57.14% | 11.90% |

## 解读边界

- staged-exit 的收益未必高于 close-entry，尤其 2026 年 6 月 close-entry 5 日平均收益为 4.4233%，staged-exit 5 日平均收益为 1.8610%；但 staged-exit 明显降低了 5 日平均盘中最大回撤（-6.9011% 降至 -4.6637%）和最差盘中回撤（-30.9002% 降至 -11.7387%）。
- 这更符合实盘风控逻辑：它牺牲一部分右侧利润，换取更可控的尾部回撤，因此后续比较应同时看收益、止损率、到期退出率和回撤，而不是只看平均收益。
- 当前仍是技术条件版：历史市值、真实 ST、真实停牌状态仍未验证，价格仍基于通达信日线。

## 验证

- 合并后已运行完整单元测试：`python -m unittest discover -s tests -v`，47/47 通过。
- 本节对应的合并和进度记录推送后，远程 `origin/codex/b1-event-study` 应包含 staged-exit 模式与结果产物。

> 2026-07-15 AI/半导体股票池回测（优先阅读本节）

## 本次完成

- 已解析用户整理的股票池文件 `C:\Users\playd\Desktop\AI-Semiconductor-Stock-Universe-20260715.md`，提取并去重得到 171 个 6 位 A 股代码，保存为 `config/ai_semiconductor_stock_pool_20260715.csv`。
- 流式 CLI 新增 `--stock-pool` 参数；传入股票池后，TDX 文件遍历按股票池代码精确过滤，不再只限原先沪深主板前缀。
- 信号层新增股票池 universe：默认仍按原主板范围过滤；传入 `stock_pool_codes` 时，`688/300/301/835438` 等非主板代码可作为候选参与 B1 计算。
- 修复通达信目录中同一 6 位代码可能同时存在 `sh/lday` 与 `sz/lday` 的错前缀重复文件问题；股票池模式现在按代码段校验交易所前缀，避免双计数。
- 已补充回归测试：股票池包含非主板代码、股票池 CLI 输出、股票池 universe eligibility、错市场前缀重复路径过滤。

## 2026 年 6 月股票池 close-entry B1 回测

- 命令模式：`--mode close-entry-b1 --analysis-start 2026-06-01 --analysis-end 2026-06-30 --horizons 1 2 3 4 5 --stock-pool config/ai_semiconductor_stock_pool_20260715.csv`。
- 输出目录：`outputs/b1_close_entry_202606_ai_semiconductor_pool`。
- 元数据：`stock_pool_count=171`，`processed_code_count=171`，`selected_signal_count=70`，`event_count=350`；买入价仍为 B1 当日收盘价，退出价为未来第 N 个交易日收盘价，回撤使用持仓期盘中最低价。
- 汇总结果：持仓 1/2/3/4/5 日平均收益分别为 1.1321%、1.4203%、2.8320%、4.5795%、4.4233%；胜率分别为 61.43%、52.86%、57.97%、54.41%、64.18%。
- 平均盘中最大回撤：持仓 1/2/3/4/5 日分别为 -3.1665%、-4.6136%、-5.8692%、-6.2379%、-6.9011%；最差盘中最大回撤分别为 -9.3778%、-15.7412%、-15.7412%、-17.6794%、-30.9002%。

### 最新收益与回撤明细

| 持仓天数 | 成交事件数 | 平均收益 | 中位收益 | 胜率 | 平均盘中最大回撤 | 最差盘中最大回撤 | 平均收盘回撤 | 最差收盘回撤 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 70 | 1.1321% | 0.9405% | 61.43% | -3.1665% | -9.3778% | -1.4626% | -7.4842% |
| 2 | 70 | 1.4203% | 1.4916% | 52.86% | -4.6136% | -15.7412% | -2.8084% | -13.7221% |
| 3 | 69 | 2.8320% | 4.6084% | 57.97% | -5.8692% | -15.7412% | -3.9314% | -15.6511% |
| 4 | 68 | 4.5795% | 2.7145% | 54.41% | -6.2379% | -17.6794% | -4.1297% | -15.6511% |
| 5 | 67 | 4.4233% | 2.7692% | 64.18% | -6.9011% | -30.9002% | -4.9375% | -28.5714% |

## 同步与披露状态

- 代码、测试和股票池配置对应功能提交为 `12b372b feat: support stock-pool b1 backtests`，并已推送到 `origin/codex/b1-event-study`；本次收益/回撤明细属于后续文档补充提交。
- `outputs/b1_close_entry_202606_ai_semiconductor_pool` 是本地复测产物目录，未作为 Git 跟踪文件提交；人工复核时优先查看本地 `close_entry_summary.csv` 和 `close_entry_selected_signals.csv`。
- 本轮暂未发现其他未同步到进度文档的信息：工作目录、股票池来源、CLI 参数、去重/市场前缀修复、测试结果、回测元数据、收益/回撤和下一步复核事项均已记录在本节。

## 验证

- 已运行完整单元测试：`python -m unittest discover -s tests -v`，42/42 通过。
- 已重新运行股票池回测并确认 `processed_code_count` 与 `stock_pool_count` 均为 171，未再出现重复市场前缀导致的额外处理代码窗口。

## 下一步

1. 人工抽查 `outputs/b1_close_entry_202606_ai_semiconductor_pool/close_entry_selected_signals.csv` 中的 70 个 B1 信号，优先检查 6 月 3 日、6 月 4 日、6 月 15 日信号密集日期。
2. 基于股票池结果新增行业/主题池对比：AI 半导体池 vs 全市场 6 月结果，确认收益改善来自行业趋势过滤，而不是样本期偶然。
3. 下一轮策略改进建议增加“行业/主题池参数”作为显式输入，而不是把行业判断混入 KDJ/BBI 技术信号本身。


> 2026-07-15 B1 规则与收盘买入回测（优先阅读本节）

## B1 信号口径修正

- 人工核验 2026-06-30 样本后，已将 B1 的 KDJ 条件修正为：T-1 日 J < 15 且 T 日 J > T-1 日 J，避免把已经远离低位后的阶段高点误判为 B1。
- B1 不再要求 BBI 本身已较前一日上升；B1 只要求价格站上 BBI，`bbi` 对照变体仍保留 BBI 上升过滤。
- 已补充针对 immediate prior low-J 与 BBI 斜率差异的回归测试。

## B1 收盘买入月度回测 CLI

- 已为流式 CLI 增加 `--mode close-entry-b1`，支持用 `--analysis-start`、`--analysis-end` 和 `--horizons` 覆盖配置文件，在指定日期段内筛选 B1，按信号日收盘价买入、未来第 N 个交易日收盘价退出。
- 输出文件包括 `close_entry_events.csv`、`close_entry_summary.csv`、`close_entry_selected_signals.csv`、`close_entry_metadata.json`、`close_entry_report.md`。
- 已运行 2026-06-01 至 2026-06-30 月度回测，输出目录为 `outputs/b1_close_entry_202606`；处理有效代码窗口 3,165 个，B1 信号 237 个，事件记录 1,185 条。
- 月度结果：1日平均收益 0.4441%、2日 0.3052%、3日 0.4412%、4日 0.4209%、5日 -0.2486%；对应平均盘中最大回撤分别为 -3.2252%、-4.5651%、-5.6858%、-6.3968%、-7.4936%。
> 2026-07-15 全量运行审计（优先阅读本节）

## 全量 CLI 结果

- 全量流式 CLI 已在真实开发 worktree `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study` 跑完，输出目录为 `outputs/event_study_technical_2026h1`。
- 产物齐全：`signal_audit.csv`、`events.csv`、`date_portfolios.csv`、`summary.csv`、`control_distribution.csv`、`control_summary.json`、`report.md`、`streaming_metadata.json`、`progress.jsonl`、`control_candidates.csv`。
- `progress.jsonl` 最后一条为 `overall_percent=100.0`；`streaming_metadata.json` 记录总耗时 `6899.734` 秒（约 1 小时 55 分）。
- 数据处理计数：目标文件 3,439 个，有效窗口代码 3,339 个，信号审计行 4,842,212，事件 730,844，已成交事件 728,754，候选对照事件 7,411,192。
- `summary.csv` 有 12 行，覆盖 `legacy`、`bbi`、`b1` 与 2、5、10、20 日全部组合；`control_distribution.csv` 有 12,000 行，每个组合 1,000 次随机对照，且没有 NaN。
- 事件状态审计正常：`insufficient_history` 与 `unfilled_entry` 的收益为空，未虚构收益。

## 结果初读

- 技术条件版结果显示：`b1` 四个持有期平均净收益均为负，且相对同日随机对照偏弱；当前不能把 B1 作为有效增强信号。
- `bbi` 的 10、20 日平均净收益略正，但优势不稳定；`legacy` 的 20 日相对随机对照较强，值得后续按年份和市场阶段拆分复核。
- 本轮结论仍限于“技术条件版”：未验证历史市值、ST 与真实停牌状态过滤，价格为未复权通达信日线。

## 本轮代码/报告披露修正

- 已补充流式 CLI 报告与 `streaming_metadata.json` 的字段限制披露：`historical_market_cap_unavailable`、`historical_st_status_unavailable`、`suspension_status_unavailable`。
- 已补充回归测试，要求流式 CLI 的 metadata 和 report 同时披露 `suspension_status_unavailable`。
- 已验证：`python -m unittest discover -s tests -v`，33/33 通过。

## 下一步

1. 提交并推送本轮披露修正与进度记录。
2. 做正式结果解读文档，优先按年份、市场阶段、信号触发条件拆分解释 `legacy`、`bbi`、`b1` 的差异。
3. 如需进一步提高结论可信度，补充可获取的逐日 ST、停牌、市值或历史指数成分数据后，再跑非技术条件版复核。

> 2026-07-14 续开发记录（优先阅读本节）

## 今日完成

- 已核验通达信原始数据：目标沪深主板 3,439 个 `.day` 文件，约 13,976,804 条记录、447,257,728 字节；数据截至 2026-07-13。
- 已确认仅有日线，缺少逐日市值与 ST 状态；研究口径冻结为“技术条件版”：`min_market_cap=0`、未复权价格、不宣称验证市值/ST 过滤。
- 已新增并推送 TDX 二进制解析、主板筛选、技术条件版配置保护、报告限制披露和导入器：`4f3d6cf`、`902630f`、`da1c216`。
- 原全量 CSV 导入因一次性拼接全市场数据未成功产出可用 CSV，已转为流式方案；流式设计与计划已推送：`c6b2a0c`、`c370ffa`。
- 流式任务1完成并推送：逐股读取、预热、信号和事件测量，不保留全市场日线：`2645b15`、`940ac13`。
- 流式任务2核心完成并推送：第二遍逐股生成同日非信号候选事件、固定随机种子抽样：`32fb50e`。
- 已验证：在提交 `32fb50e` 时，完整单元测试为 30/30 通过。
- 本轮续作已补充测试：空窗口股票帧跳过、流式 CLI 产物写出、BOM JSON 配置读取、进度日志与阶段耗时元数据；完整单元测试为 33/33 通过。
- 流式 CLI 初稿已补齐七类研究产物：`signal_audit.csv`、`events.csv`、`date_portfolios.csv`、`summary.csv`、`control_distribution.csv`、`control_summary.json`、`report.md`，并额外写出 `streaming_metadata.json` 和 `control_candidates.csv`。
- 已用 6 个真实通达信 `.day` 样本文件试跑：原始 1000 次控制迭代配置 15.667 秒完成，输出 12 个 `variant + horizon` 组合各 1000 行控制分布；样本元数据为 3 个有效窗口代码、4,713 行信号审计、737 个候选对照事件。
- 已诊断此前“长时间无输出”的主要可复现原因之一：随机对照抽样在迭代内反复筛选 DataFrame；现已改为预先按 `variant + horizon + signal_date` 建候选池索引。
- 已新增流式 CLI 进度汇报：参数 `--progress-interval-seconds` 默认 60 秒，控制台输出 `progress {...}`，同时写入 `progress.jsonl`；`streaming_metadata.json` 记录 `total_elapsed_seconds` 与 `stage_durations_seconds`。`df4decc` 已同步到真实开发 worktree `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`。

## 当前未提交状态与阻塞点

- 当前代码变更已提交为 `df4decc`，并同步到真实开发 worktree；本次仅补充目录说明与进度记录后提交、推送。
- `data/daily_bars_technical.metadata.json` 是本地研究数据；保持忽略，不提交。
- 本轮发现并停止了一个残留全量流式 CLI 进程和一个样本长跑进程；当前不应再依赖此前 `outputs/event_study_technical_2026h1` 的任何半成品。
- 真实全量 3,439 个目标主板文件尚未重新跑完；不能将真实回测视为已完成，也不能提交或推送为最终结果。

## 下一步执行顺序

1. 在真实开发 worktree `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study` 运行 `git status --short`，确认工作区 clean。
2. 再次确认没有残留 `streaming_event_study_run` 进程。
3. 在真实开发 worktree 运行全量真实数据 CLI：`--source C:\Users\playd\Desktop\A_Share_Backtesting\data\tdx_raw --config config\event_study_technical_only.json --output outputs\event_study_technical_2026h1 --progress-interval-seconds 60`。
4. 记录退出码、耗时、产物存在性、事件数、12 个组合的控制分布行数、`streaming_metadata.json` 和进程/内存证据。
5. 全量产物完整且审计通过后，再更新本文件、提交源码和文档、推送 `codex/b1-event-study`。

最后更新：2026-07-15（Asia/Shanghai）

## 当前目标

实现 B 层 A 股 B1 信号事件研究：对 `legacy`、`bbi`、`b1` 三组日线收盘信号，分别计算下一交易日开盘入场后持有 2、5、10、20 个完整交易日的结果，并与同日随机对照组比较。

## 工作状态

- 开发分支：`codex/b1-event-study`
- 当前工作树：`C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`；不要在 `C:\Users\playd\Desktop\A_Share_Backtesting` 根目录或 `C:\Users\playd\Documents\A_share_backtesting` 继续本分支开发。
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

1. 进入 `C:\Users\playd\Desktop\A_Share_Backtesting\.worktrees\codex-b1-event-study`，确认当前分支为 `codex/b1-event-study` 并同步该分支的最新提交。
2. 先阅读本文件和实施计划；不要从 `main` 直接继续开发。
3. 设置运行环境后执行：

```powershell
$py = 'C:\Users\playd\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH = "$PWD\src"
& $py -m unittest discover -s tests -v
```

4. 从“下一步”的第一条继续；完成一个任务后，更新本文件的已完成项、验证结果、提交号和下一步。
