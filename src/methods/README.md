# QuantPick 常见量化方法代码库

本目录 `src/methods/` 收录了一组**常见量化策略方法的纯函数实现**，作为研究参考与策略模板。
所有函数**不连接任何数据源、不调用券商接口、不落盘**，仅依赖 `numpy` / `pandas`。

> 这是「方法库」而非「策略引擎」：每个方法输入价格/收益序列，输出信号或权重。
> 把它们接入你的回测/实盘框架即可，QuantPick 不在此处自动运行它们。

## 目录结构

| 文件 | 类别 | 方法 |
|---|---|---|
| `base.py` | 工具 | 收益、SMA/EMA、滚动标准差、z-score、权重归一、信号转持仓 |
| `trend.py` | 趋势跟踪 | 双均线交叉、三均线、MACD、N 日突破 |
| `momentum.py` | 动量 | 时间序列动量、横截面动量 |
| `mean_reversion.py` | 均值回归 | z-score 回归、布林带、RSI 超买超卖 |
| `volatility.py` | 波动率 | ATR、波动率目标权重 |
| `stat_arb.py` | 统计套利 | 配对交易（协整 z-score）、网格价位 |
| `position.py` | 仓位管理 | 凯利公式、固定分数、风险平价 |
| `multi_factor.py` | 多因子 | 横截面 z-score、因子加权合成 |
| `turtle.py` | 趋势跟踪 | 海龟法则完整版（突破入场+金字塔加仓+2*ATR止损+反向突破退出） |
| `multi_timeframe.py` | 趋势跟踪 | 多周期均线共振 |
| `ml_timing.py` | 机器学习 | 机器学习择时（logreg/随机森林，walk-forward；惰性依赖 scikit-learn） |
| `rotation.py` | 动量（多标的） | ETF 动量轮动：平滑动量打分、排名选强、绝对动量过滤；含多标的回测 |
| `backtest_signal.py` | 回测 | 单标的信号回测（T+1/成本/指标）与方法注册表 |

## 信号约定

- **signal / position**：`-1`（空/做空）、`0`（空仓）、`+1`（多/做多）
- **weight**：`>= 0`，组合层面合计为 1

## 快速示例

```python
import pandas as pd
from src.methods import trend, mean_reversion, position

close = pd.Series([...])  # 收盘价序列

# 趋势：双均线
sig = trend.dual_ma_signal(close, fast=5, slow=20)

# 反转：布林带（只做多）
pos = mean_reversion.bollinger_signal(close, window=20, k=2.0, long_only=True)

# 仓位：风险平价（需协方差矩阵 cov）
# w = position.risk_parity_weights(cov)

# 多标的轮动：ETF 动量轮动（改写自聚宽社区策略）
from src.methods.rotation import gen_multi_prices, rotation_backtest
px = gen_multi_prices(n=750, n_assets=8, seed=7)   # 合成行情，不连数据源
res = rotation_backtest(px, top_k=3, cost=0.0005)
print(res["metrics"])
```

### 命令行跑回测（合成数据，不连券商）

```bash
python -m scripts.execute rotate --assets 8 --top-k 2   # 有趋势场景
python -m scripts.execute rotate --trend-amp 0          # 无趋势场景（演示轮动失效）
python -m scripts.execute method --name turtle --n 250  # 单标的信号回测
```

## 风险提示

- 单方法均有适用边界（趋势法怕震荡、回归法怕趋势），实盘需组合与风控。
- 配对交易、均值回归依赖平稳/协整前提，使用前务必做 ADF / 协整检验。
- 本目录代码仅供学习与回测参考，不构成投资建议。
