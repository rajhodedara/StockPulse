"""
polymarket.py
=============
Fetches prediction-market probabilities from Polymarket's public API.
Owned by: Person 1
"""

import json
import logging
import requests
from functools import lru_cache
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
TIMEOUT    = 15

# ── Ticker → search keywords mapping ─────────────────────────────────────────
# Maps specific tickers to relevant Polymarket search terms
TICKER_KEYWORD_MAP = {
    # Tech
    "AAPL"  : ["Apple stock", "Apple"],
    "MSFT"  : ["Microsoft stock", "Microsoft"],
    "GOOGL" : ["Google stock", "Alphabet"],
    "GOOG"  : ["Google stock", "Alphabet"],
    "AMZN"  : ["Amazon stock", "Amazon"],
    "TSLA"  : ["Tesla stock", "Tesla"],
    "META"  : ["Meta stock", "Facebook Meta"],
    "NVDA"  : ["Nvidia stock", "Nvidia"],
    "AMD"   : ["AMD stock", "AMD"],
    "NFLX"  : ["Netflix stock", "Netflix"],
    "INTC"  : ["Intel stock", "Intel"],
    "CRM"   : ["Salesforce stock", "Salesforce"],
    "UBER"  : ["Uber stock", "Uber"],
    "COIN"  : ["Coinbase stock", "Coinbase crypto"],
    "PLTR"  : ["Palantir stock", "Palantir"],
    "SQ"    : ["Block Square stock", "Square"],
    "SHOP"  : ["Shopify stock", "Shopify"],
    "NET"   : ["Cloudflare stock", "Cloudflare"],
    "SNOW"  : ["Snowflake stock", "Snowflake"],

    # Finance
    "JPM"   : ["JPMorgan stock", "JPMorgan"],
    "BAC"   : ["Bank of America stock", "Bank of America"],
    "GS"    : ["Goldman Sachs stock", "Goldman Sachs"],
    "V"     : ["Visa stock", "Visa"],
    "MA"    : ["Mastercard stock", "Mastercard"],
    "BRK-B" : ["Berkshire Hathaway stock", "Berkshire Hathaway"],

    # ETFs / Indices
    "SPY"   : ["S&P 500", "SPY ETF", "stock market 2025"],
    "QQQ"   : ["NASDAQ", "QQQ ETF", "tech stocks"],

    # Entertainment
    "DIS"   : ["Disney stock", "Disney"],
    "BABA"  : ["Alibaba stock", "Alibaba China"],
    "TSM"   : ["TSMC stock", "semiconductor"],
}

# Fallback general finance keywords when ticker not in map
GENERAL_FINANCE_KEYWORDS = [
    "S&P 500",
    "stock market",
    "Federal Reserve rate",
    "NASDAQ",
    "recession 2025",
]

# Finance-related terms to VALIDATE markets are actually finance-related
FINANCE_TERMS = [
    "stock", "market", "s&p", "nasdaq", "dow", "price", "share",
    "ipo", "earnings", "revenue", "fed", "rate", "inflation",
    "recession", "economy", "gdp", "bitcoin", "crypto", "etf",
    "index", "bull", "bear", "trade", "investment", "financial",
    "apple", "microsoft", "tesla", "google", "amazon", "nvidia",
    "meta", "netflix", "coinbase", "palantir", "shopify",
    "jpmorgan", "goldman", "visa", "mastercard", "berkshire",
    "alibaba", "tsmc", "intel", "amd", "uber", "salesforce",
]


# ── Core fetch ────────────────────────────────────────────────────────────────
def _get(url: str, params: dict = None) -> dict | list:
    """Thin wrapper with full error handling."""
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        logger.debug(
            "GET %s params=%s → type=%s",
            url, params,
            f"list[{len(data)}]" if isinstance(data, list)
            else f"dict keys={list(data.keys())}"
        )
        return data
    except requests.exceptions.Timeout:
        logger.error("Polymarket API timeout: %s", url)
    except requests.exceptions.HTTPError as exc:
        logger.error("Polymarket HTTP %s: %s", exc.response.status_code, url)
    except requests.exceptions.RequestException as exc:
        logger.error("Polymarket request error: %s", exc)
    except json.JSONDecodeError as exc:
        logger.error("Polymarket JSON decode error: %s", exc)
    return {}


# ── Market search ─────────────────────────────────────────────────────────────
def search_markets(keyword: str, limit: int = 5) -> list[dict]:
    """
    Search Gamma API for FINANCE-ONLY active markets matching keyword.
    Filters out sports, politics, entertainment results.
    """
    data = _get(
        f"{GAMMA_BASE}/markets",
        params={
            "search"   : keyword,
            "active"   : "true",
            "closed"   : "false",
            "limit"    : limit * 3,  # fetch more so we have enough after filtering
            "order"    : "volume",
            "ascending": "false",
        },
    )

    # ── Parse all Gamma API response shapes ───────────────────────────────
    if isinstance(data, list):
        markets_raw = data
    elif isinstance(data, dict):
        markets_raw = (
            data.get("data")
            or data.get("markets")
            or []
        )
    else:
        markets_raw = []

    if not markets_raw:
        logger.warning("No markets returned for keyword='%s'", keyword)
        return []

    results = []
    for m in markets_raw:
        # ── FILTER: only keep finance-related markets ──────────────────
        if not _is_finance_market(m):
            logger.debug(
                "Skipping non-finance market: %s",
                m.get("question", "")[:60]
            )
            continue

        yes_prob = _extract_yes_prob(m)
        results.append({
            "id"        : m.get("id", ""),
            "question"  : m.get("question", ""),
            "end_date"  : (m.get("endDate", "") or "")[:10],
            "yes_prob"  : yes_prob,
            "no_prob"   : round(1 - yes_prob, 4) if yes_prob is not None else None,
            "volume_usd": _safe_float(
                m.get("volume") or m.get("volumeNum") or 0
            ),
            "url"       : _build_url(m),
        })

        # Stop once we have enough valid results
        if len(results) >= limit:
            break

    logger.info(
        "search_markets('%s') → %d finance markets (from %d raw)",
        keyword, len(results), len(markets_raw)
    )
    return results


def _is_finance_market(market: dict) -> bool:
    """
    Returns True only if market question/tags are finance-related.
    Rejects sports, politics, entertainment etc.
    """
    question = (market.get("question") or "").lower()
    tags      = [
        str(t.get("label") or t.get("name") or "").lower()
        for t in (market.get("tags") or [])
    ]
    category = str(market.get("category") or "").lower()

    # Explicit non-finance categories to reject immediately
    reject_terms = [
        "golf", "tennis", "nba", "nfl", "nhl", "mlb", "soccer", "football",
        "baseball", "basketball", "cricket", "rugby", "olympics", "ufc", "mma",
        "election", "president", "congress", "senate", "vote", "political",
        "oscar", "grammy", "award", "celebrity", "movie", "tv show",
        "weather", "climate", "earthquake", "hurricane",
        "valero", "open", "tournament", "championship", "league",
        "braves", "yankees", "lakers", "celtics",  # sports teams
    ]

    all_text = question + " " + " ".join(tags) + " " + category

    # Reject if any sports/non-finance term found
    for term in reject_terms:
        if term in all_text:
            return False

    # Accept if any finance term found
    for term in FINANCE_TERMS:
        if term in all_text:
            return True

    # Default reject if nothing finance-related found
    return False


# ── YES probability extractor ─────────────────────────────────────────────────
def _extract_yes_prob(market: dict) -> float | None:
    """
    Parse YES probability — handles all Gamma API response shapes.
    """
    # ── Strategy 1: outcomePrices JSON string ─────────────────────────────
    raw_prices = market.get("outcomePrices")
    if raw_prices:
        try:
            prices = (
                json.loads(raw_prices)
                if isinstance(raw_prices, str)
                else raw_prices
            )
            if isinstance(prices, list) and len(prices) >= 1:
                val = float(prices[0])
                if 0.0 <= val <= 1.0:
                    return round(val, 4)
                if 1.0 < val <= 100.0:
                    return round(val / 100, 4)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.debug("outcomePrices parse failed: %s", exc)

    # ── Strategy 2: tokens[] list ─────────────────────────────────────────
    tokens = market.get("tokens") or []
    for t in tokens:
        outcome_name = str(
            t.get("outcome") or t.get("name") or ""
        ).upper()
        if outcome_name == "YES":
            price = (
                t.get("price")
                or t.get("lastTradePrice")
                or t.get("bestAsk")
            )
            if price is not None:
                val = float(price)
                if 0.0 <= val <= 1.0:
                    return round(val, 4)

    # ── Strategy 3: parallel outcomes + outcomePrices arrays ──────────────
    outcomes       = market.get("outcomes") or []
    outcome_prices = market.get("outcomePrices") or []

    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = []
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except json.JSONDecodeError:
            outcome_prices = []

    if isinstance(outcomes, list) and isinstance(outcome_prices, list):
        for i, outcome in enumerate(outcomes):
            if str(outcome).upper() == "YES" and i < len(outcome_prices):
                try:
                    val = float(outcome_prices[i])
                    if 0.0 <= val <= 1.0:
                        return round(val, 4)
                    if 1.0 < val <= 100.0:
                        return round(val / 100, 4)
                except (ValueError, TypeError):
                    pass

    logger.debug(
        "_extract_yes_prob: no prob found for market id=%s q='%s'",
        market.get("id"), market.get("question", "")[:50]
    )
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _safe_float(value) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _build_url(market: dict) -> str:
    slug = market.get("slug") or market.get("id", "")
    return f"https://polymarket.com/event/{slug}"


# ── Per-ticker sentiment ──────────────────────────────────────────────────────
def get_ticker_keywords(ticker: str) -> tuple:
    """
    Returns finance-relevant search keywords for a given ticker.
    Falls back to general finance keywords if ticker not mapped.
    """
    ticker_upper = ticker.upper().strip()
    keywords = TICKER_KEYWORD_MAP.get(
        ticker_upper,
        GENERAL_FINANCE_KEYWORDS  # fallback for unknown tickers
    )
    return tuple(keywords)


# ── Aggregate sentiment ───────────────────────────────────────────────────────
# NOTE: lru_cache keyed on (ticker, keywords) so each ticker gets its own result
@lru_cache(maxsize=32)
def polymarket_market_sentiment(
    ticker  : str   = "SPY",
    keywords: tuple = None,
) -> dict:
    """
    Pull stock-related markets for a SPECIFIC ticker and compute
    an aggregate 'market optimism' score.

    Parameters
    ----------
    ticker   : Stock ticker symbol e.g. "AAPL", "TSLA"
    keywords : Override search keywords (optional)

    Returns
    -------
    {
        "score"     : 0.57,
        "label"     : "Slightly Bullish",
        "markets"   : [...],
        "ticker"    : "AAPL",
        "fetched_at": "2025-01-01T12:00:00",
        "source"    : "live" | "fallback"
    }
    """
    kws = keywords or get_ticker_keywords(ticker)
    logger.info(
        "Fetching Polymarket sentiment for ticker=%s keywords=%s",
        ticker, kws
    )

    all_markets: list[dict] = []
    for kw in kws:
        found = search_markets(kw, limit=3)
        all_markets.extend(found)

    # ── Deduplicate by id ─────────────────────────────────────────────────
    seen, unique = set(), []
    for m in all_markets:
        if m["id"] and m["id"] not in seen:
            seen.add(m["id"])
            unique.append(m)

    logger.info(
        "ticker=%s → %d unique finance markets after dedup",
        ticker, len(unique)
    )

    # ── Separate valid probability markets ────────────────────────────────
    valid = [m for m in unique if m["yes_prob"] is not None]

    if not valid:
        logger.warning(
            "ticker=%s: No valid YES probabilities → returning neutral 0.5",
            ticker
        )
        return {
            "score"     : 0.5,
            "label"     : "Neutral",
            "markets"   : unique,
            "ticker"    : ticker,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
            "source"    : "fallback",
        }

    # ── Weighted average by USD volume ────────────────────────────────────
    total_vol = sum(m["volume_usd"] for m in valid)

    if total_vol > 0:
        score = sum(
            m["yes_prob"] * m["volume_usd"] for m in valid
        ) / total_vol
    else:
        score = sum(m["yes_prob"] for m in valid) / len(valid)

    score = round(max(0.0, min(1.0, score)), 4)

    return {
        "score"     : score,
        "label"     : _score_label(score),
        "markets"   : unique,
        "ticker"    : ticker,
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
        "source"    : "live",
    }


def _score_label(score: float) -> str:
    if score >= 0.70: return "Strongly Bullish"
    if score >= 0.55: return "Slightly Bullish"
    if score >= 0.45: return "Neutral"
    if score >= 0.30: return "Slightly Bearish"
    return "Strongly Bearish"


# ── Quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level  = logging.INFO,
        format = "%(levelname)s | %(name)s | %(message)s",
    )

    test_tickers = ["AAPL", "TSLA", "SPY", "NVDA"]

    for tick in test_tickers:
        print(f"\n── {tick} ──")
        result = polymarket_market_sentiment(ticker=tick)
        print(f"  Score  : {result['score']:.2%}")
        print(f"  Label  : {result['label']}")
        print(f"  Source : {result['source']}")
        print(f"  Markets: {len(result['markets'])} unique finance markets")
        for m in result["markets"][:2]:
            print(f"    • {m['question'][:65]:<65} YES={m['yes_prob']}")