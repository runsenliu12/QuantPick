# 聚宽 2025 年精选策略集（joinquant）

本目录收录从聚宽社区（joinquant.com）2025 年精选帖中筛选出的 **52 篇可运行策略代码**，
按「框架/择时/行业轮动/ETF 轮动/小市值价投/打板/多策略/机器学习」分类整理，文件名已改为英文以便检索。

> 来源说明：每篇 `.py` 文件头部均保留原始「克隆自聚宽文章」链接、标题与作者，版权归原作者所有，
> 此处仅作**学习与研究存档**，不构成任何投资建议。代码基于聚宽 `jqdata` / `jqfactor` API，
> 需在聚宽研究环境运行，本地无聚宽 SDK 时无法直接执行。

## 分类索引

| 编号 | 文件 | 主题 |
|------|------|------|
| 01 | 01_allweather_rotation.py | 全天候轮动（简易框架） |
| 02 | 02_quant_from_scratch.py | 从零搭建：择时/选股/仓位/因子 |
| 03 | 03_ml_pipeline.py | 完整机器学习 pipeline |
| 04 | 04_conformal_regression.py | 5 折保形回归 |
| 05 | 05_ml_rolling_value.py | 机器学习滚动训练价投 |
| 06 | 06_deep_learning_pipeline.py | 深度学习神经网络 pipeline |
| 07 | 07_market_timing.py | 大盘择时（逻辑简单） |
| 08 | 08_fundamental_rsi_timing.py | 基本面 + RSI 择时 |
| 09 | 09_svr_index_timing.py | SVR 上证综指择时 |
| 10 | 10_industry_rotation_trend_crowd.py | 趋势/拥挤/景气行业轮动 |
| 11 | 11_industry_breadth_rotation.py | 行业宽度轮动 |
| 12 | 12_etf_momentum_epo.py | 多品种 ETF 动量轮动 + EPO |
| 13 | 13_etf_min_corr_volfilter.py | 波动率过滤最小相关 ETF |
| 14 | 14_etf_epo_lowcorr.py | EPO 优化低相关 ETF 组合 |
| 15 | 15_etf_core_asset_rotation.py | 核心资产轮动（线性加权） |
| 16 | 16_etf_multi_asset.py | 多标的 ETF 策略 |
| 17 | 17_etf_min_corr_trend.py | 趋势筛选最小相关 ETF |
| 18 | 18_etf_index_momentum.py | 指数 ETF 动量轮动 |
| 19 | 19_etf_stable.py | 稳健型 ETF |
| 20 | 20_etf_t0_momentum.py | ETF T0 动量（年化18%） |
| 21 | 21_etf_bilstm.py | BiLSTM for ETF |
| 22 | 22_etf_min_corr_fast.py | 最小相关 ETF 加速 10x |
| 23 | 23_smallcap_new_factor.py | 小市值全新因子（10年52倍） |
| 24 | 24_dividend_smallcap.py | 股息率小市值（10年206倍） |
| 25 | 25_high_dividend.py | 高股息 |
| 26 | 26_smallcap_optimized.py | 小市值再优化（无未来函数） |
| 27 | 27_smallcap_guojiu.py | 国九小市值（年化100.5） |
| 28 | 28_smallcap_bugfix.py | 小市值排除 3 bug |
| 29 | 29_smallcap_stop_loss.py | 小市值止损（年化104） |
| 30 | 30_smallcap_5y15x.py | 小市值 5年15倍 |
| 31 | 31_smallcap_guojiu_debug.py | 国九条众神 Debug 版 |
| 32 | 32_value_low_drawdown.py | 大容量低回撤价值投资 |
| 33 | 33_largecap_value_dividend.py | 大市值价投高股息 |
| 34 | 34_midcap_roic.py | ROIC 中等市值 |
| 35 | 35_value_dividend_growth.py | 高股息低估值高增长价投 |
| 36 | 36_guojiu_dividend_factor.py | 国九条红利因子（修正审计意见） |
| 37 | 37_first_limit_low_open.py | 首板低开策略 |
| 38 | 38_consecutive_limit_leader.py | 连板龙头策略 |
| 39 | 39_chase_first_limit.py | 追首板涨停（年化304） |
| 40 | 40_first_limit_weak_to_strong.py | 首板弱转强竞价 |
| 41 | 41_chase_limit_doubled.py | 追板策略（今年翻倍） |
| 42 | 42_first_second_limit_lhb.py | 首版+二版龙虎榜 |
| 43 | 43_multi_strategy_subaccount.py | 子账户多策略分仓 |
| 44 | 44_multi_strategy_combo.py | 多策略整合（十年百倍） |
| 45 | 45_stock_etf_combo.py | 股票 + ETF 组合 |
| 46 | 46_fund_plus.py | 固收+ |
| 47 | 47_ml_linear_smallcap.py | 机器学习线性回归小市值 |
| 48 | 48_dqn_rl_agent.py | DQN 强化学习交易智能体 |
| 49 | 49_four_troublemakers.py | 四大搅屎棍策略 |
| 50 | 50_hot_sector_constituents.py | 热点行业/概念成分股 |
| 51 | 51_kmeans_fund_cluster.py | K-means 基金分类 |
| 52 | 52_smallcap_dynamic_rebalance.py | 小盘股动态调仓 |
| 53 | 53_etf_candidate_pool.py | ETF 策略候选池构建 |

## 与原 QuantPick 方法的对应关系

- `src/methods/` 里的纯函数（双均线/布林/RSI/海龟/多周期共振/ML 择时）是通用信号模板；
- 本目录是**聚宽平台完整策略实现**（含 `initialize`/`handle_data`、交易成本控制、下单逻辑），
  可作为把 `src/methods` 信号落地为实盘/回测策略的参考范例。
- ETF 轮动类（12–22）与 QuantPick 的「ETF 动量轮动 + 风险平价」方向直接对应。
