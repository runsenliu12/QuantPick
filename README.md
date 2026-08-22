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
│   └── backtest.py             # 回测验证
└── web/templates/index.html    # 看板页面
```

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
