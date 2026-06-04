# 🤖 Stock Trading Agent v2

> An autonomous AI agent that scans NSE markets every 15 minutes, validates signals with a Groq LLaMA model, and manages paper trades with full risk controls — running 24/7 on a VPS with real-time Telegram alerts.

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![AI Engine](https://img.shields.io/badge/AI-Groq%20LLaMA%203.1-FF6B35)](https://groq.com)
[![Deployed](https://img.shields.io/badge/Deployed-Hostinger%20VPS%2024%2F7-22C55E)](https://hostinger.com)
[![Dashboard](https://img.shields.io/badge/Dashboard-Live%20GitHub%20Pages-7C3AED)](https://shibilshamz.github.io/stock-trading-agent-v2)
[![Market](https://img.shields.io/badge/Market-NSE%20Nifty%2050-F59E0B)](https://nseindia.com)
[![Mode](https://img.shields.io/badge/Mode-Paper%20Trading-64748B)](https://github.com/shibilshamz/stock-trading-agent-v2)

---

## What This Agent Does

Every weekday during NSE market hours **(09:15 – 15:30 IST)**, this agent autonomously:

1. **Scans** the top 20 Nifty 50 stocks ranked by morning gap, volume, and ATR
2. **Scores** each stock across three weighted technical signal layers
3. **Validates** the composite score with a Groq LLaMA AI that cross-checks technicals against live news sentiment
4. **Sizes** positions dynamically using ATR — never risking more than 1% of balance per trade
5. **Manages** open positions in real time — checking stop-loss and take-profit on every cycle
6. **Alerts** every signal, entry, exit, and end-of-day summary to Telegram instantly
7. **Self-closes** all positions at 15:35 IST and sends a full daily P&L report

**Live dashboard →** [shibilshamz.github.io/stock-trading-agent-v2](https://shibilshamz.github.io/stock-trading-agent-v2)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    main.py  — Orchestrator                        │
│   Startup → Morning universe scan → 15-min cycle → EOD close     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
           ┌─────────────────▼──────────────────┐
           │           DATA LAYER                │
           │  data/universe.py   ─→ Top 20 NSE   │
           │  data/market_data.py ─→ OHLCV cache │
           └─────────────────┬──────────────────┘
                             │
           ┌─────────────────▼──────────────────┐
           │        SIGNAL ENGINE                │
           │  indicators/technical.py            │
           │  ORB (40%) + VWAP (30%)             │
           │  + EMA/RSI Momentum (30%)           │
           │  → Composite score [0.0 – 1.0]      │
           └─────────────────┬──────────────────┘
                             │
           ┌─────────────────▼──────────────────┐
           │         AI BRAIN                    │
           │  brain/ai_engine.py                 │
           │  sentiment/news.py (Google RSS)     │
           │  Groq LLaMA validates signal        │
           │  → BUY / SELL / HOLD + reason       │
           └─────────────────┬──────────────────┘
                             │
           ┌─────────────────▼──────────────────┐
           │      RISK & EXECUTION               │
           │  risk/sizing.py  → ATR position     │
           │  portfolio/paper_trader.py → P&L    │
           └─────────────────┬──────────────────┘
                             │
           ┌─────────────────▼──────────────────┐
           │         ALERTS                      │
           │  alerts/telegram_bot.py             │
           │  Signal / Open / Close / EOD        │
           └────────────────────────────────────┘
```

---

## Signal Logic

| Layer | Indicator | Weight | Trigger |
|-------|-----------|--------|---------|
| **ORB** | Opening Range Breakout | **40%** | Price breaks above/below first 30-min high/low |
| **VWAP** | Volume-Weighted Avg Price | **30%** | Price position relative to intraday anchored VWAP |
| **Momentum** | EMA 9/21 crossover + RSI 14 | **30%** | EMA cross confirmed by RSI direction |
| **AI Validation** | Groq LLaMA 3.1-8b-instant | Veto layer | Compares composite score against live news sentiment — can block a trade |

**Entry threshold:** composite score ≥ 0.55. Below this, the agent holds regardless of individual signals.

---

## Risk Management

| Rule | Value | Purpose |
|------|-------|---------|
| Stop Loss | 1.5 × ATR | Dynamic, volatility-adjusted — wider on volatile days |
| Take Profit | 2:1 Risk-Reward | Fixed RR target per trade |
| Max Risk / Trade | 1% of balance | Hard cap on position size |
| Max Daily Loss | 3% drawdown | Circuit breaker — halts all new trades for the day |
| Max Cash / Trade | 10% of portfolio | Concentration limit |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Market Data | yfinance — 15-min OHLCV, `.NS` suffix for NSE tickers |
| Technical Indicators | pandas-ta — EMA, RSI, ATR, VWAP, Bollinger Bands, ADX, OBV |
| AI Decision Engine | Groq API — `llama-3.1-8b-instant` (free tier: 14,400 req/day) |
| News Sentiment | Google News RSS → keyword-based sentiment scoring |
| Alerts | Telegram Bot API — typed message helpers per event |
| Deployment | Hostinger VPS, Ubuntu 22.04 — systemd service, 24/7 |
| CI Fallback | GitHub Actions — cron-scheduled scan cycle |
| Dashboard | GitHub Pages — live P&L and signal log |
| Broker Adapters | IBKR + Upstox APIs — configured, `DRY_RUN=true` |

---

## Project Structure

```
stock-trading-agent-v2/
├── main.py                   # Orchestrator: scheduler + scan loop + EOD
├── config.py                 # All settings — tune the agent here
├── requirements.txt
├── .env.example              # Environment variable template
├── Procfile                  # Deployment process declaration
├── runtime.txt               # Python 3.12 pin
│
├── data/
│   ├── universe.py           # Morning scan → ranks top 20 Nifty 50 stocks
│   └── market_data.py        # yfinance OHLCV fetcher with caching
│
├── indicators/
│   └── technical.py          # VWAP, EMA, RSI, ATR + composite scorer
│
├── sentiment/
│   └── news.py               # Google News RSS → per-symbol sentiment
│
├── brain/
│   └── ai_engine.py          # Groq LLM decision engine + rule-based fallback
│
├── risk/
│   └── sizing.py             # ATR position sizing + daily risk guards
│
├── portfolio/
│   └── paper_trader.py       # Paper book: open/close positions, P&L, JSON state
│
├── alerts/
│   └── telegram_bot.py       # Typed Telegram alert helpers (signal/open/close/EOD)
│
├── dashboard/                # GitHub Pages live dashboard source
├── logs/                     # Runtime logs + paper_state.json (git-ignored)
└── .github/workflows/        # GitHub Actions CI scan cycle (fallback)
```

---

## Quickstart

```bash
# 1. Clone
git clone https://github.com/shibilshamz/stock-trading-agent-v2.git
cd stock-trading-agent-v2

# 2. Virtual environment
python -m venv venv
source venv/bin/activate       # macOS / Linux
# venv\Scripts\activate        # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure secrets
cp .env.example .env
# Edit .env — add GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 5. Smoke test (validates all modules, no live calls)
python test_run.py

# 6. Run
python main.py
```

### Environment Variables

| Variable | Required | Where to Get |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ | [console.groq.com/keys](https://console.groq.com/keys) — free |
| `TELEGRAM_BOT_TOKEN` | ✅ | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | ✅ | Send `/start` to your bot, call `getUpdates` API |
| `LOG_LEVEL` | ⬜ | `INFO` (default) or `DEBUG` |
| `DRY_RUN` | ⬜ | `true` = paper mode (default), `false` = live broker |

---

## Key Config Knobs (`config.py`)

| Setting | Default | What It Does |
|---------|---------|-------------|
| `PAPER_BALANCE` | ₹50,000 | Starting capital for paper trades |
| `UNIVERSE_TOP_N` | 20 | Number of stocks scanned each morning |
| `SIGNAL_THRESHOLD` | 0.55 | Minimum composite score to trigger entry |
| `POSITION_SIZE_PCT` | 10% | Max cash deployed per trade |
| `MAX_RISK_PER_TRADE_PCT` | 1% | Hard risk cap per trade |
| `MAX_DAILY_LOSS_PCT` | 3% | Daily circuit breaker |
| `STOP_LOSS_ATR_MULT` | 1.5× | Stop distance as ATR multiple |
| `TAKE_PROFIT_RR` | 2.0 | Risk-reward ratio for take-profit target |

---

## VPS Deployment (24/7)

The agent runs as a `systemd` service on Hostinger VPS (Ubuntu 22.04, Mumbai region):

```bash
# /etc/systemd/system/trading-agent.service
[Unit]
Description=Stock Trading Agent v2
After=network.target

[Service]
User=root
WorkingDirectory=/path/to/stock-trading-agent-v2
EnvironmentFile=/path/to/.env
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-agent
sudo systemctl start trading-agent
sudo journalctl -u trading-agent -f   # Live logs
```

GitHub Actions provides a cron-based fallback scan cycle during market hours if the VPS is unreachable.

---

## What the Agent Does Each Day

| Time (IST) | Action |
|------------|--------|
| 09:15 | Market opens — universe scan begins |
| 09:20 | Top 20 stocks ranked by gap/volume/ATR |
| 09:20 – 15:30 | Signal scan every 15 minutes |
| Each scan | Fetch candles → score signals → AI validation → execute or skip |
| Real-time | Telegram alert on every signal, trade open, and trade close |
| 15:35 | Force-close all open positions |
| 15:36 | Send full end-of-day P&L summary to Telegram |

---

## Known Quirks & Fixes Applied

- `TATAMOTORS` trades as `TATAMOTORS-BE` on Yahoo Finance — corrected in `config.py`
- Groq free tier handles 14,400 requests/day — sufficient for 15-min scans across 20 symbols with headroom
- EOD summary sends once only — deduplication guard in place
- SL/TP checks use candle Close price, not High/Low — prevents whipsaw false triggers
- Out-of-universe position tracking: open positions dropped from the daily universe still get price updates for SL/TP checks via `latest_price()`

---

## Notes

- **Paper mode only.** `DRY_RUN=true` by default. No real money is ever placed.
- To go live: swap `portfolio/paper_trader.py` for a broker API adapter. IBKR and Upstox integration files are included but gated behind `DRY_RUN`.
- This project was built through AI-assisted development (vibe coding) — demonstrating that well-structured, production-grade AI systems can be built by domain experts using modern AI tools.

---

## Author

**Shibil Shamsudheen**  
AI Builder · Workflow Automation · Dubai, UAE

[LinkedIn](https://linkedin.com/in/shibil-shamsudheen) · [GitHub](https://github.com/shibilshamz) · shamz.shibil@gmail.com

> *Built end-to-end using AI-assisted development — proof that domain expertise + the right tools produces real systems.*
