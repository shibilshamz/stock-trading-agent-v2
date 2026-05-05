"""
Fetches headlines from Google News RSS and returns a simple sentiment score
without any paid API key.
"""

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from config import NEWS_CACHE_MINUTES, NEWS_MAX_ARTICLES, NEWS_RSS_TEMPLATE

logger = logging.getLogger(__name__)

# In-memory cache: symbol → (epoch, articles_list, sentiment_score)
_cache: dict[str, tuple[float, list[dict], float]] = {}

# Positive / negative keyword lists (lightweight, no ML dependency)
_POSITIVE = {
    "surge", "rally", "jump", "soar", "gain", "profit", "beat", "upgrade",
    "bullish", "record", "high", "strong", "positive", "growth", "expand",
    "win", "outperform", "buy", "acquisition", "merger", "dividend",
}
_NEGATIVE = {
    "fall", "drop", "decline", "crash", "loss", "miss", "downgrade",
    "bearish", "low", "weak", "negative", "shrink", "sell", "investigation",
    "fraud", "penalty", "fine", "lawsuit", "recall", "layoff", "cut",
}


def _keyword_sentiment(text: str) -> float:
    """Return a score in [-1, 1] based on positive/negative keyword hits."""
    words = set(text.lower().split())
    pos = len(words & _POSITIVE)
    neg = len(words & _NEGATIVE)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 4)


def _fetch_rss(query: str) -> list[dict]:
    """Download and parse a Google News RSS feed. Returns list of article dicts."""
    url = NEWS_RSS_TEMPLATE.format(query=quote_plus(query))
    articles = []

    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
    except Exception as exc:
        logger.warning("RSS fetch failed for '%s': %s", query, exc)
        return []

    for item in root.iter("item"):
        title       = item.findtext("title", "")
        description = item.findtext("description", "")
        pub_date    = item.findtext("pubDate", "")
        link        = item.findtext("link", "")

        text = f"{title} {description}"
        articles.append({
            "title":     title,
            "link":      link,
            "published": pub_date,
            "sentiment": _keyword_sentiment(text),
        })

        if len(articles) >= NEWS_MAX_ARTICLES:
            break

    return articles


def get_sentiment(symbol: str) -> dict:
    """
    Return sentiment data for a symbol.

    Result keys:
      articles  – list of fetched headlines
      score     – mean sentiment in [-1, 1]
      label     – "positive" | "negative" | "neutral"
      cached    – bool
    """
    now = time.monotonic()
    ttl = NEWS_CACHE_MINUTES * 60

    if symbol in _cache:
        ts, articles, score = _cache[symbol]
        if now - ts < ttl:
            return _build_result(articles, score, cached=True)

    articles = _fetch_rss(symbol)

    if articles:
        score = round(sum(a["sentiment"] for a in articles) / len(articles), 4)
    else:
        score = 0.0

    _cache[symbol] = (now, articles, score)
    logger.debug(
        "News sentiment for %s: %.3f (%d articles)", symbol, score, len(articles)
    )
    return _build_result(articles, score, cached=False)


def _build_result(articles: list[dict], score: float, cached: bool) -> dict:
    if score > 0.1:
        label = "positive"
    elif score < -0.1:
        label = "negative"
    else:
        label = "neutral"

    return {
        "articles": articles,
        "score":    score,
        "label":    label,
        "cached":   cached,
    }


def batch_sentiment(symbols: list[str]) -> dict[str, dict]:
    """Fetch sentiment for multiple symbols sequentially (respects RSS rate limits)."""
    results = {}
    for sym in symbols:
        results[sym] = get_sentiment(sym)
        time.sleep(0.5)   # polite delay between requests
    return results
