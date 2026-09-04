# QuantPick · 智选

> A 股「股票 + ETF」双选量化研究系统：数据 → 因子 → 风控 → 服务，一条龙。

QuantPick 是一个聚焦 A 股、同时覆盖**股票与场内 ETF** 的量化筛选系统。它不承诺"稳赚"，而是把选股决策建立在**多因子打分 + 严格风控**之上，输出可解释的候选清单，并通过 Web 看板与推送送达。

```
                    ┌─────────────┐
   行情/财务/资金流  │  数据层      │  AKShare → SQLite 缓存
   (AKShare)        └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  因子层      │  动量 / 质量 / 估值 / 资金流（股）
                    │             │  规模 / 流动性 / 动量 / 跟踪误差（ETF）
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  风控层      │  单标仓位封顶 / 止损线 / 相关性去重
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  服务层      │  Web 看板 + 飞书/企微推送 + 定时扫描
                    └─────────────┘
```

## ✨ 功能

- **双选**：同一套流程同时产出股票 Top 清单与 ETF Top 清单
- **多因子打分**：因子 Z-Score 标准化后按权重加权，结果可解释
- **风控建议**：自动给出单标仓位上限、止损线，并按相关性去重分散组合
- **Web 看板**：`/api/candidates` 提供 JSON，页面自动刷新展示候选
- **定时推送**：交易日收盘后自动扫描，结果推送飞书/企微
- **回测验证**：内置动量因子 IC / ICIR / 净值演示，验证因子有效性
- **历史回测净值看板**：页面 "📉 历史回测净值" 展示策略 vs 沪深300 的净值曲线、Sharpe / 最大回撤 / 样本内·外分段，且**无需行情密钥即可用合成数据演示**（`--demo`）
- **量化方法库 `src/methods`**：一组纯函数量化方法模板（趋势/动量/均值回归/波动率/统计套利/仓位/多因子/海龟/多周期共振/机器学习择时/ETF 动量轮动），不连数据源、不接券商，可接回测框架
- **执行层 `scripts/execute.py`**：目标组合生成 → 聚宽/PTrade/QMT 策略代码生成 → 纸面回放 → 单方法/多标的回测（合成数据，不连券商）
- **聚宽策略存档 `joinquant/`**：从聚宽社区精选的 100 篇策略，整理为可运行代码 + 英文 slug，按「精选」与「补充笔记」两档归档
- **一键部署**：Docker / docker-compose 打包，服务器常驻

## 📁 目录结构

```
QuantPick/
├── config.json                 # 公共配置（因子权重、筛选门槛、端口）
├── config.local.example.json    # 私有配置样例（飞书 webhook、代理）
├── requirements.txt
├── Dockerfile / docker-compose.yml / .dockerignore
├── docker-deploy.sh            # 一键部署/管理
├── src/
│   ├── config.py               # 配置加载
│   ├── data.py                 # 数据层（AKShare + SQLite 缓存）
│   ├── factors.py              # 因子计算
│   ├── selection.py            # 打分与排名
│   ├── risk.py                 # 风控层
│   ├── notify.py               # 推送层
│   └── server.py               # Web 看板
├── scripts/
│   ├── daily_scan.py           # 每日扫描入口
│   ├── backtest.py             # 回测验证
│   └── execute.py              # 执行层 CLI：目标组合→平台策略→回放→回测
├── joinquant/                  # 聚宽社区精选策略存档
│   ├── README.md               # 52 篇精选策略分类索引
│   ├── notes/                  # 48 篇补充存档（笔记/变体/重复类）
│   └── *.py                    # 编号化英文 slug 策略代码
└── web/templates/              # 看板页面（index / backtest / factors / us_etf / methodology / methods）
```

### `src/methods/` 量化方法库

纯函数实现，**不连数据源、不接券商、不落盘**，仅依赖 `numpy` / `pandas`。每个方法输入价格/收益序列，输出信号或权重，可接入回测框架。

| 类别 | 模块 | 方法 |
|---|---|---|
| 趋势跟踪 | `trend` | 双均线、三均线、MACD、N 日突破 |
| 动量 | `momentum` | 时间序列动量、横截面动量 |
| 均值回归 | `mean_reversion` | z-score 回归、布林带、RSI |
| 波动率 | `volatility` | ATR、波动率目标 |
| 统计套利 | `stat_arb` | 配对交易、网格 |
| 仓位管理 | `position` | 凯利、固定分数、风险平价 |
| 多因子 | `multi_factor` | 横截面 z-score 合成 |
| 趋势（完整版） | `turtle` | 海龟法则（突破+加仓+ATR 止损+退出） |
| 趋势 | `multi_timeframe` | 多周期均线共振 |
| 机器学习 | `ml_timing` | 机器学习择时（logreg/RF，walk-forward） |
| 动量（多标的） | `rotation` | ETF 动量轮动：平滑动量打分→排名选强→绝对动量过滤 |
| 回测 | `backtest_signal` | 单标的信号回测 + 多标的轮动回测（T+1/成本/指标） |

> 这是「方法库」而非「策略引擎」：每个方法只产出信号/权重，把它们接入你的回测或实盘框架即可。

## 🚀 快速开始（本地 venv）

```bash
git clone https://github.com/<你>/QuantPick.git
cd QuantPick

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 可选：配置飞书推送
cp config.local.example.json config.local.json
# 编辑 config.local.json 填入 webhook 并设 enabled: true

# 启动 Web 看板
python -m src.server
# 浏览器打开 http://localhost:8080

# 或跑一次每日扫描（交易日 15:30 后）
python scripts/daily_scan.py

# 跑一次历史回测（需连通行情接口）；加 --demo 用合成数据离线演示，无需密钥
python scripts/backtest.py --demo --out backtest_result.json
```

> 回测结果可用 `--out backtest_result.json` 导出为 API 友好 JSON，供 Web 看板 `/api/backtest` 消费；看板在真实数据缺失时也会自动回退到合成演示，保证面板始终有内容。

## 🧪 方法库 & 回测（执行层 CLI）

`scripts/execute.py` 把方法库接到回测框架，**全程合成数据、不连券商、绝不下单**：

```bash
# 单标的信号回测（双均线 / 海龟 / RSI / 突破 …）
python -m scripts.execute method --name turtle --n 250 --seed 7
python -m scripts.execute method --name rsi --params "window=14,oversold=30" --list

# 多标的 ETF 动量轮动回测（改写自聚宽社区策略）
python -m scripts.execute rotate --assets 8 --top-k 2 --seed 7        # 有趋势场景
python -m scripts.execute rotate --trend-amp 0                        # 无趋势场景：演示轮动失效

# 平台策略代码生成（仅产出 .py，不连接/不下单）
python -m scripts.execute gen --platform joinquant
python -m scripts.execute paper --demo                              # 纸面回放演示
```

`rotate` 演示结论：合成数据含持续轮动趋势时，轮动 top3 大幅跑赢等权基准；**无趋势时轮动只剩换手成本、反跑输**——即动量策略的失效边界（详见 `src/methods/rotation.py` 与 `tests/test_rotation.py`）。

## 📚 聚宽策略存档（joinquant/）

从聚宽社区 **2025 年精选 100 篇**中整理，剔除纯笔记/山寨/乱改/重复变体后归档：

| 目录 | 内容 | 数量 |
|------|------|------|
| `joinquant/`（根） | 精选策略，按框架/择时/行业轮动/ETF轮动/小市值价投/打板/多策略/机器学习分类 | 52 篇 |
| `joinquant/notes/` | 补充存档：学习笔记、变体版本、重复实现（含「乱改/山寨」类，质量参差） | 48 篇 |

- 每篇 `.py` 头部保留原始「克隆自聚宽文章」链接、标题与作者，版权归原作者，仅作**学习与研究存档**
- 代码基于聚宽 `jqdata` / `jqfactor` API，需在聚宽研究环境运行；本地无聚宽 SDK 时不能直接执行
- **不构成投资建议**；`notes/` 目录文件未做质量筛选，使用时请自行甄别

## 🐳 Docker 部署（推荐服务器）

```bash
cd QuantPick
cp config.local.example.json config.local.json   # 按需填 webhook
chmod +x docker-deploy.sh

./docker-deploy.sh            # 构建并后台启动
./docker-deploy.sh status     # 查看状态
./docker-deploy.sh logs       # 看日志
./docker-deploy.sh stop       # 停止
```

访问 `http://服务器IP:8080`。若服务器有安全组，放通 8080 入站。

## ⏰ 定时任务

在服务器 crontab（交易日 15:30）跑扫描并推送：

```cron
30 15 * * 1-5 cd /path/QuantPick && /path/.venv/bin/python scripts/daily_scan.py >> data/scan.log 2>&1
```

云函数（腾讯云 SCF / 阿里云 FC）也可定时触发 `scripts/daily_scan.py`。

## ⚙️ 配置说明

`config.json` 关键项：

| 配置 | 含义 | 默认 |
|------|------|------|
| `selection.stock.min_market_cap` | 股票最小总市值门槛 | 50 亿 |
| `selection.stock.min_amount` | 最小日成交额门槛 | 5000 万 |
| `models.stock_weights` | 股票因子权重（动量/质量/估值/资金流） | 0.3/0.25/0.25/0.2 |
| `models.etf_weights` | ETF 因子权重 | 规模/流动性/折溢价/动量/跟踪误差 |
| `risk.max_position_pct` | 单标仓位上限 | 12% |
| `risk.stop_loss_pct` | 个股止损线 | 8% |
| `risk.max_correlation` | 组合相关性去重阈值 | 0.7 |
| `server.port` | Web 看板端口 | 8080 |

## 🛡️ 风控与纪律（必读）

系统输出的是**研究信号，不是必赚代码**。能否赚钱取决于：

1. **先求不亏大** — 单标 ≤12% 仓位，个股 -8% 止损，总回撤 -20% 减仓
2. **正期望策略** — 因子需回测 + 样本外验证，看 IC/ICIR，不是拍脑袋
3. **分散不相关** — 股 + ETF 搭配，相关性去重，降低波动
4. **仓位管理** — 等分或按分，绝不一把梭；满仓追涨是亏损第一来源
5. **少交易、吃复利** — 频繁交易 = 手续费 + 情绪损耗
6. **持续迭代** — 策略会失效，监控表现、定期再训练

先用仿真/小资金跑 3–6 个月验证，再考虑加钱。

## ⚠️ 免责声明

本项目仅供学习与研究，所有输出不构成任何投资建议。量化模型有回撤期与失效期，据此操作产生的盈亏由使用者自行承担。

## 🗺️ 路线图

- [x] 历史回测净值曲线看板 + 离线 `--demo` 演示模式（无需密钥即可跑通展示）
- [x] 美股 ETF 选基脚手架（`src/us_etf.py`，yfinance 惰性接入，默认关闭；需 `config.json` 启用 + 安装 `yfinance`）
- [x] 因子表现监控（IC / ICIR 滚动，`src/ic.py` + `/api/ic`，含合成演示兜底）
- [x] ML 打分模块（`src/ml.py`，纯 numpy 扩张窗口 walk-forward，无第三方依赖）
- [x] 推送（飞书 / 企业微信 webhook，密钥放 `config.local.json` 的 `_local.notifications`，默认关闭）
- [x] 量化方法库 `src/methods/`（11 类纯函数方法 + 单标的/多标的回测引擎）
- [x] 执行层 `scripts/execute.py`（目标组合→聚宽/PTrade/QMT 策略代码→纸面回放→单方法/多标的回测，合成数据不连券商）
- [x] ETF 动量轮动方法 `rotation.py`（改写自聚宽社区策略，含有效/失效场景演示）
- [x] 聚宽 2025 精选策略存档 `joinquant/`（52 精选 + 48 补充笔记，共 100 篇）
- [ ] ETF 折溢价（IOPV/净值）精确接入
- [ ] 实盘下单接口（需对接券商 API，谨慎）

### 美股 ETF 选基（默认关闭）

```python
# config.json
"us_etf": {
  "enabled": false,                 # 改为 true 启用（需 pip install yfinance）
  "symbols": ["SPY","QQQ","IWM","VTI","GLD","TLT","ARKK","VNQ","EEM","XLF"],
  "top_n": 5,
  "weights": {"momentum":0.35,"liquidity":0.20,"scale":0.15,"premium":0.10,"expense":0.20}
}
```

启用后 `scripts/daily_scan.py` 会额外产出 `kind="us_etf"` 候选池（独立风控，不影响 A 股组合），
并与 A 股候选同 schema 写入历史表。yfinance 未安装 / 网络失败时自动回退到合成演示数据，
保证链路与看板始终可跑通（demo 数据不进入真实决策）。

### 推送（飞书 / 企业微信）

密钥不入库，放 `config.local.json`：

```json
{ "notifications": { "enabled": true,
  "feishu_webhook_url": "https://open.feishu.cn/...",
  "wechat_webhook_url": "https://qyapi.weixin.qq.com/..." } }
```

`daily_scan.py` 与 `paper_trading.py --notify` 都会在结果产出后推送；空结果会发告警。

---

Made with ❤️ by QuantPick
