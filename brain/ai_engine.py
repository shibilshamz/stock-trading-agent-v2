"""
AI decision engine powered by Groq (llama-3.1-8b-instant).
Combines technical signals + news sentiment into a final trade decision.
"""

import json
import logging
import time
from typing import Optional

import httpx

from config import (
    AI_MAX_TOKENS,
    AI_TEMPERATURE,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL,
    SIGNAL_THRESHOLD,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_GAP = 2.0   # minimum seconds between successive Groq API calls
_RETRY_WAIT_429 = 5.0   # seconds to wait after a 429 before the single retry

_SYSTEM_PROMPT = """You are an expert NSE intraday trading analyst.
You receive structured JSON data about a stock and return a JSON trading decision.
Be concise, factual, and risk-aware. Never recommend a position size above the stated limit.

Your response MUST be valid JSON with exactly these keys:
{
  "action":     "BUY" | "SELL" | "HOLD",
  "confidence": <float 0-1>,
  "reason":     "<one sentence>",
  "risk_note":  "<one sentence about the main risk>"
}
"""

_USER_TEMPLATE = """Analyse this NSE stock and decide:

Symbol: {symbol}
Current price: ₹{price:.2f}
ATR (14-period, 15m): ₹{atr:.2f}

Technical signals:
  ORB signal:       {orb}
  VWAP signal:      {vwap}
  Momentum signal:  {momentum}
  Composite score:  {score:.3f}  (threshold: {threshold})

News sentiment:
  Score: {news_score:.3f}  ({news_label})
  Headlines: {headlines}

Current portfolio state:
  Open positions:   {open_positions}
  Available cash:   ₹{cash:.2f}
  Daily P&L:        ₹{daily_pnl:.2f}

Rules:
- Only BUY if composite_score >= {threshold} and news is not negative
- Only SELL if composite_score <= -{threshold}
- Prefer HOLD when signals are mixed or news is strongly negative
- Max confidence 0.9; always state the main risk

Respond with JSON only.
"""


class AIEngine:
    def __init__(self):
        if not GROQ_API_KEY:
            logger.warning("GROQ_API_KEY not set — AI engine will use rule-based fallback")
        self.client = httpx.Client(
            base_url=GROQ_BASE_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        self._last_call_time: float = 0.0  # monotonic timestamp of the last API call

    def decide(
        self,
        symbol: str,
        technical: dict,
        sentiment: dict,
        portfolio_state: dict,
    ) -> dict:
        """
        Call Groq and return a decision dict.
        Falls back to rule-based decision if the API is unavailable.
        """
        headlines = "; ".join(
            a["title"] for a in sentiment.get("articles", [])[:3]
        ) or "No headlines available"

        prompt = _USER_TEMPLATE.format(
            symbol=symbol,
            price=technical.get("last_close", 0),
            atr=technical.get("atr") or 0,
            orb=technical.get("orb_signal", 0),
            vwap=technical.get("vwap_signal", 0),
            momentum=technical.get("momentum_signal", 0),
            score=technical.get("composite_score", 0),
            threshold=SIGNAL_THRESHOLD,
            news_score=sentiment.get("score", 0),
            news_label=sentiment.get("label", "neutral"),
            headlines=headlines,
            open_positions=portfolio_state.get("open_positions", 0),
            cash=portfolio_state.get("cash", 0),
            daily_pnl=portfolio_state.get("daily_pnl", 0),
        )

        if not GROQ_API_KEY:
            return self._rule_based_fallback(technical, sentiment)

        try:
            resp = self._call_groq({
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens":  AI_MAX_TOKENS,
                "temperature": AI_TEMPERATURE,
                "response_format": {"type": "json_object"},
            })
            content = resp.json()["choices"][0]["message"]["content"]
            decision = json.loads(content)

            # Validate required keys
            for key in ("action", "confidence", "reason", "risk_note"):
                if key not in decision:
                    raise ValueError(f"Missing key: {key}")

            decision["action"]    = decision["action"].upper()
            decision["ai_source"] = "groq"
            logger.info(
                "AI decision for %s: %s (conf=%.2f) | %s",
                symbol, decision["action"], decision["confidence"], decision["reason"],
            )
            return decision

        except Exception as exc:
            logger.error("Groq API error for %s: %s — using fallback", symbol, exc)
            return self._rule_based_fallback(technical, sentiment)

    def _call_groq(self, payload: dict) -> httpx.Response:
        """
        POST to Groq with two protections:
          1. Rate limiter  — enforces _RATE_LIMIT_GAP seconds between calls so
             scanning 20 stocks back-to-back doesn't burst the API.
          2. 429 retry     — waits _RETRY_WAIT_429 seconds and retries once before
             letting the exception propagate to the rule-based fallback.
        """
        gap = time.monotonic() - self._last_call_time
        if gap < _RATE_LIMIT_GAP:
            time.sleep(_RATE_LIMIT_GAP - gap)

        self._last_call_time = time.monotonic()
        resp = self.client.post("/chat/completions", json=payload)

        if resp.status_code == 429:
            logger.warning(
                "Groq 429 rate limit hit — waiting %.0fs and retrying once",
                _RETRY_WAIT_429,
            )
            time.sleep(_RETRY_WAIT_429)
            self._last_call_time = time.monotonic()
            resp = self.client.post("/chat/completions", json=payload)

        resp.raise_for_status()
        return resp

    @staticmethod
    def _rule_based_fallback(technical: dict, sentiment: dict) -> dict:
        """Simple deterministic fallback when Groq is unavailable."""
        score = technical.get("composite_score", 0)
        news  = sentiment.get("score", 0)

        if score >= SIGNAL_THRESHOLD and news >= -0.1:
            action = "BUY"
            conf   = min(0.7, 0.5 + score)
        elif score <= -SIGNAL_THRESHOLD:
            action = "SELL"
            conf   = min(0.7, 0.5 + abs(score))
        else:
            action = "HOLD"
            conf   = 0.5

        return {
            "action":     action,
            "confidence": round(conf, 2),
            "reason":     "Rule-based fallback (Groq unavailable).",
            "risk_note":  "AI unavailable; signals may be incomplete.",
            "ai_source":  "fallback",
        }

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
