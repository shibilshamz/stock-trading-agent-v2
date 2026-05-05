# stock-trading-agent-v2

Autonomous NSE intraday day-trading agent running 24/7 on Railway.app.
Scans the Nifty 50 every 15 minutes, generates ORB + VWAP + Momentum signals,
validates decisions with a Groq LLM, and executes paper trades with full
position sizing and risk management. All trade alerts are pushed to Telegram.

---

## Strategy

| Layer | Detail |
|---|---|
| Universe | Top 20 Nifty 50 stocks ranked by gap, volume, and ATR each morning |
| Candles | 15-minute OHLCV via yfinance (`.NS` suffix) |
| Signal 1 — ORB | Breakout above / below first 30-min opening range (40% weight) |
| Signal 2 — VWAP | Price position relative to intraday anchored VWAP (30% weight) |
| Signal 3 — Momentum | EMA 9/21 crossover + RSI 14 confirmation (30% weight) |
| AI layer | Groq `llama-3.1-8b-instant` validates composite score vs news sentiment |
| Sizing | ATR-based stop (1.5×ATR), 2:1 RR target, max 1% balance at risk per trade |
| Mode | **Paper trading only** — no live brokerage connection |

---

## Project Structure

```
stock-trading-agent-v2/
├── main.py                  # Scheduler + orchestration loop
├── config.py                # All settings (edit this to tune the agent)
├── requirements.txt
├── runtime.txt              # Python 3.12 for Railway
├── Procfile                 # worker: python main.py
├── data/
│   ├── universe.py          # Morning scan → top 20 symbols
│   └── market_data.py       # yfinance candle fetcher + cache
├── indicators/
│   └── technical.py         # VWAP, EMA, RSI, ATR, composite score
├── sentiment/
│   └── news.py              # Google News RSS → keyword sentiment
├── brain/
│   └── ai_engine.py         # Groq API decision engine + rule fallback
├── risk/
│   └── sizing.py            # ATR-based position sizing + risk guards
├── portfolio/
│   └── paper_trader.py      # Paper book: positions, P&L, JSON persistence
├── alerts/
│   └── telegram_bot.py      # Typed Telegram alert helpers
└── logs/                    # Runtime logs + paper_state.json (git-ignored)
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values.
On Railway, add these under **Settings → Variables**.

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Get free key at [console.groq.com/keys](https://console.groq.com/keys) |
| `TELEGRAM_BOT_TOKEN` | Yes | From [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_CHAT_ID` | Yes | Your numeric chat ID (send `/start` to your bot, then call `getUpdates`) |
| `LOG_LEVEL` | No | `INFO` (default) or `DEBUG` |

---

## Local Setup

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd stock-trading-agent-v2

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure secrets
cp .env.example .env
# Edit .env and add your GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 5. Run the smoke test (no scheduler, verifies every module)
python test_run.py

# 6. Start the agent
python main.py
```

---

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select this repository
4. Go to **Settings → Variables** and add the three env vars above
5. Railway auto-detects `Procfile` and `runtime.txt` — click **Deploy**

The agent runs as a **worker** (no web port needed). It will:
- Start at 09:20 IST and scan the Nifty 50 universe
- Run a signal scan every 15 minutes during market hours (09:15–15:30 IST)
- Force-close all open positions at 15:35 IST and send an EOD summary
- Push every trade open, close, and daily summary to your Telegram

---

## Key Config Knobs (`config.py`)

| Setting | Default | Effect |
|---|---|---|
| `PAPER_BALANCE` | ₹50,000 | Starting capital |
| `UNIVERSE_TOP_N` | 20 | Stocks scanned each session |
| `SIGNAL_THRESHOLD` | 0.55 | Min composite score to trigger entry |
| `POSITION_SIZE_PCT` | 10% | Max cash deployed per trade |
| `MAX_RISK_PER_TRADE_PCT` | 1% | Max balance at risk per trade |
| `MAX_DAILY_LOSS_PCT` | 3% | Halt trading after this drawdown |
| `STOP_LOSS_ATR_MULT` | 1.5× | Stop distance as multiple of ATR |
| `TAKE_PROFIT_RR` | 2.0 | Risk-reward ratio for target |

---

## Notes

- **Paper mode only.** No real money is ever placed. To connect a live broker,
  replace `portfolio/paper_trader.py` with a broker API adapter.
- TATAMOTORS is listed as `TATAMOTORS-BE` on Yahoo Finance — already corrected
  in `config.py`.
- The Groq API has a generous free tier (14,400 requests/day) — more than enough
  for 15-minute scans across 20 symbols.
