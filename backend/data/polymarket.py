# polymarket.py - FINAL v3
import json
import logging
import math
import os
import re
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
_gemini_client = None

if GEMINI_API_KEY:
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini ready")
    except Exception as e:
        logger.error("Gemini init failed: %s", e)

# ── Config ─────────────────────────────────────────────────────────────────────
GAMMA_BASE     = "https://gamma-api.polymarket.com"
TIMEOUT        = 15
CACHE_TTL      = 300
GEMINI_MIN_GAP = 2.0       # production: users load one ticker at a time

# ── Sentiment filter constants ─────────────────────────────────────────────────
MIN_LIQUIDITY   = 50.0     # USD — dust/resolved market floor
MIN_YES_PROB    = 0.02     # below → almost certainly resolved
MAX_YES_PROB    = 0.98     # above → almost certainly resolved
ATM_BAND        = 0.35     # only markets where 35% ≤ YES ≤ 65% count as ATM
MAX_STRIKE_MULT = 1.40     # ignore "above $X" if strike > 1.4× estimated spot
MIN_STRIKE_MULT = 0.70     # ignore "above $X" if strike < 0.7× estimated spot

# ── Caches ─────────────────────────────────────────────────────────────────────
_ticker_cache:   dict[str, tuple[float, dict]] = {}
_last_gemini_ts: float = 0.0

# ── Ticker search config ───────────────────────────────────────────────────────
TICKER_QUERIES: dict[str, list[str]] = {
    "AAPL" : ["AAPL", "Apple stock"],
    "TSLA" : ["TSLA", "Tesla"],
    "NVDA" : ["NVDA", "Nvidia"],
    "MSFT" : ["MSFT", "Microsoft"],
    "AMZN" : ["AMZN", "Amazon"],
    "GOOG" : ["GOOGL", "Google"],
    "GOOGL": ["GOOGL", "Google"],
    "META" : ["META", "Meta"],
    "UBER" : ["UBER", "Uber"],
    "NFLX" : ["NFLX", "Netflix"],
    "AMD"  : ["AMD"],
    "COIN" : ["COIN", "Coinbase"],
    "SPY"  : ["S&P 500", "recession", "tariff"],
    "QQQ"  : ["NASDAQ", "S&P 500"],
    "BTC"  : ["Bitcoin", "BTC"],
    "ETH"  : ["Ethereum", "ETH"],
    "JPM"  : ["JPMorgan", "JPM"],
}

MACRO_QUERIES = [
    "S&P 500", "recession", "tariff",
    "Federal Reserve", "interest rate", "inflation",
]

# ── Regex patterns ─────────────────────────────────────────────────────────────
STRIKE_ABOVE_RE = re.compile(
    r"close[s]?\s+above\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
STRIKE_BELOW_RE = re.compile(
    r"(?:close[s]?\s+below|dip\s+to)\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
STRIKE_RANGE_RE = re.compile(
    r"close[s]?\s+at\s+\$?([\d,]+(?:\.\d+)?)\s*[-–]\s*\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
HIT_HIGH_RE = re.compile(
    r"hit\s+\$?([\d,]+(?:\.\d+)?)\s*[\(\[]?\s*HIGH\s*[\)\]]?",
    re.IGNORECASE,
)
HIT_LOW_RE = re.compile(
    r"hit\s+\$?([\d,]+(?:\.\d+)?)\s*[\(\[]?\s*LOW\s*[\)\]]?",
    re.IGNORECASE,
)
REACH_RE = re.compile(
    r"reach\s+\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# ════════════════════════════════════════════════════════════════════════════
# LAYER 1 ── Search via /search-v2
# ════════════════════════════════════════════════════════════════════════════

def _search_events(query: str, limit: int = 20) -> list[dict]:
    try:
        resp = requests.get(
            f"{GAMMA_BASE}/search-v2",
            params={
                "q"             : query,
                "page"          : 1,
                "limit_per_type": limit,
                "type"          : "events",
                "events_status" : "active",
                "optimized"     : "false",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data   = resp.json()
        events = data.get("events", [])
        logger.info("search-v2 '%s': %d events", query, len(events))
        return events
    except Exception as e:
        logger.error("search-v2 error for '%s': %s", query, e)
        return []


def _search_multi(queries: list[str], limit: int = 10) -> list[dict]:
    seen:   set        = set()
    merged: list[dict] = []
    for q in queries:
        for event in _search_events(q, limit=limit):
            eid = str(event.get("id", ""))
            if eid and eid not in seen:
                seen.add(eid)
                merged.append(event)
    logger.info("Multi-search %s: %d unique events", queries, len(merged))
    return merged

# ════════════════════════════════════════════════════════════════════════════
# LAYER 2 ── Price extraction
# ════════════════════════════════════════════════════════════════════════════

def _extract_price(market: dict) -> float | None:
    """Extract YES probability from market dict."""
    # Method 1: outcomePrices[0]
    raw = market.get("outcomePrices")
    if raw:
        try:
            prices = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(prices, list) and len(prices) >= 1:
                p = float(prices[0])
                if 0.0 <= p <= 1.0:
                    return round(p, 4)
        except Exception:
            pass

    # Method 2: bid/ask midpoint
    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    if bid is not None and ask is not None:
        try:
            b, a = float(bid), float(ask)
            if 0.0 < b <= 1.0 and 0.0 < a <= 1.0 and b <= a:
                return round((b + a) / 2, 4)
        except (ValueError, TypeError):
            pass

    # Method 3: last trade
    ltp = market.get("lastTradePrice")
    if ltp is not None:
        try:
            p = float(ltp)
            if 0.0 <= p <= 1.0:
                return round(p, 4)
        except (ValueError, TypeError):
            pass

    return None

# ════════════════════════════════════════════════════════════════════════════
# LAYER 3 ── Market classification
# ════════════════════════════════════════════════════════════════════════════

def _parse_float(s: str) -> float:
    return float(s.replace(",", ""))


def _classify_market(question: str) -> dict:
    """Parse market question → type + strike info."""
    info = {"type": "other", "strike": None,
            "strike_hi": None, "strike_lo": None}

    m = STRIKE_ABOVE_RE.search(question)
    if m:
        info["type"]   = "above"
        info["strike"] = _parse_float(m.group(1))
        return info

    m = STRIKE_BELOW_RE.search(question)
    if m:
        info["type"]   = "below"
        info["strike"] = _parse_float(m.group(1))
        return info

    m = STRIKE_RANGE_RE.search(question)
    if m:
        lo = _parse_float(m.group(1))
        hi = _parse_float(m.group(2))
        info["type"]      = "range"
        info["strike"]    = (lo + hi) / 2
        info["strike_lo"] = lo
        info["strike_hi"] = hi
        return info

    m = HIT_HIGH_RE.search(question)
    if m:
        info["type"]   = "hit_high"
        info["strike"] = _parse_float(m.group(1))
        return info

    m = HIT_LOW_RE.search(question)
    if m:
        info["type"]   = "hit_low"
        info["strike"] = _parse_float(m.group(1))
        return info

    m = REACH_RE.search(question)
    if m:
        info["type"]   = "reach"
        info["strike"] = _parse_float(m.group(1))
        return info

    return info


def _market_to_sentiment(yes_prob: float, classification: dict) -> float | None:
    """
    Convert YES probability + market type → [0, 1] bullish sentiment.

    above    : P itself           (high P = bullish)
    below    : 1 - P             (market thinks it goes below = bearish)
    hit_high : P                 (reaching upside target = bullish)
    hit_low  : 1 - P             (reaching downside target = bearish flip)
    reach    : P                 (generic upside target)
    range    : None              (too ambiguous)
    other    : None              (can't interpret)
    """
    mtype = classification["type"]

    if mtype == "above":    return round(yes_prob, 4)
    if mtype == "below":    return round(1.0 - yes_prob, 4)
    if mtype == "hit_high": return round(yes_prob, 4)
    if mtype == "hit_low":  return round(1.0 - yes_prob, 4)
    if mtype == "reach":    return round(yes_prob, 4)

    return None  # range / other → skip

# ════════════════════════════════════════════════════════════════════════════
# LAYER 4 ── Active-market filter
# ════════════════════════════════════════════════════════════════════════════

def _is_market_active(market: dict) -> bool:
    """
    Returns False if the market is expired, resolved, or a dust market.

    Checks (in order):
    1. Liquidity below MIN_LIQUIDITY → dust / delisted
    2. End date in the past          → expired
    3. Price at extreme (< 2% or > 98%) → resolved but not yet delisted
    """
    liq = float(market.get("liquidityClob") or market.get("liquidity") or 0)
    if liq < MIN_LIQUIDITY:
        return False

    end_raw = market.get("endDateIso") or market.get("endDate", "")
    if end_raw:
        try:
            end_dt = datetime.fromisoformat(end_raw[:19]).replace(tzinfo=timezone.utc)
            if end_dt < datetime.now(timezone.utc):
                logger.debug("Expired: %s", market.get("question", "")[:50])
                return False
        except Exception:
            pass

    price = _extract_price(market)
    if price is not None and (price < MIN_YES_PROB or price > MAX_YES_PROB):
        logger.debug("Resolved price %.4f: %s",
                     price, market.get("question", "")[:50])
        return False

    return True

# ════════════════════════════════════════════════════════════════════════════
# LAYER 5 ── ATM detection + per-event sentiment
# ════════════════════════════════════════════════════════════════════════════

def _atm_market(
    markets:    list[dict],
    spot_price: float | None = None,
) -> tuple[dict, float, float] | None:
    """
    From active 'above $X' markets, find the at-the-money one (YES ≈ 50%).

    Filters applied before selection:
    - Must pass _is_market_active()
    - YES probability must be within ATM_BAND (35% – 65%)
    - If spot_price known: strike must be within MIN/MAX_STRIKE_MULT of spot
    """
    candidates = []
    for m in markets:
        if not _is_market_active(m):
            continue

        price = _extract_price(m)
        if price is None:
            continue

        # ATM band: only genuinely uncertain markets
        if not (ATM_BAND <= price <= 1.0 - ATM_BAND):
            logger.debug("Outside ATM band (%.2f): %s",
                         price, m.get("question", "")[:50])
            continue

        info = _classify_market(m.get("question", ""))
        if info["type"] != "above" or info["strike"] is None:
            continue

        # Strike-distance filter when we have a spot estimate
        if spot_price is not None:
            ratio = info["strike"] / spot_price
            if ratio > MAX_STRIKE_MULT or ratio < MIN_STRIKE_MULT:
                logger.debug("Strike $%.0f too far from spot $%.0f (%.2f×): %s",
                             info["strike"], spot_price, ratio,
                             m.get("question", "")[:40])
                continue

        candidates.append((m, price, info["strike"]))

    if not candidates:
        return None

    # ATM = closest to 50% YES
    return min(candidates, key=lambda x: abs(x[1] - 0.50))


def _sentiment_from_event(event: dict) -> tuple[float, float, str] | None:
    """
    Extract a [0, 1] bullish sentiment score from one event.

    Strategy (in order):
    1. ≥ 2 active 'above $X' markets → ATM selection
    2. Best single interpretable active market
    3. None

    Returns (sentiment, volume_usd, method_description) or None.
    """
    markets = event.get("markets", [])
    if not markets:
        return None

    volume = float(event.get("volume") or 0)

    # Pre-filter: active markets only
    active = [m for m in markets if _is_market_active(m)]
    if not active:
        return None

    # ── Strategy 1: ATM from multiple 'above' markets ──────────────────
    above = [
        m for m in active
        if _classify_market(m.get("question", ""))["type"] == "above"
    ]

    if len(above) >= 2:
        # Estimate spot from the market closest to 50%
        spot_hint: float | None = None
        best_gap = 1.0
        for m in above:
            p    = _extract_price(m)
            info = _classify_market(m.get("question", ""))
            if p is not None and info["strike"] and abs(p - 0.50) < best_gap:
                best_gap  = abs(p - 0.50)
                spot_hint = info["strike"]

        atm = _atm_market(above, spot_price=spot_hint)
        if atm:
            market, yes_prob, strike = atm
            return (
                round(yes_prob, 4),
                volume,
                f"ATM(above ${strike:,.0f}, P={yes_prob:.2f})",
            )

    # ── Strategy 2: Best single interpretable market ───────────────────
    best_sentiment: float | None = None
    best_liq                     = -1.0
    best_desc                    = ""

    for m in active:
        price = _extract_price(m)
        if price is None:
            continue
        if price < MIN_YES_PROB or price > MAX_YES_PROB:
            continue

        info = _classify_market(m.get("question", ""))
        sent = _market_to_sentiment(price, info)
        if sent is None:
            continue

        liq = float(m.get("liquidityClob") or m.get("liquidity") or 0)
        if liq > best_liq:
            best_liq       = liq
            best_sentiment = sent
            best_desc      = f"{info['type']}(P={price:.2f}→sent={sent:.2f})"

    if best_sentiment is not None:
        return (best_sentiment, volume, best_desc)

    return None

# ════════════════════════════════════════════════════════════════════════════
# LAYER 6 ── Format for API response
# ════════════════════════════════════════════════════════════════════════════

def _best_market_from_event(event: dict) -> tuple[dict, float] | None:
    """
    Pick the most liquid market for display.
    Prefers active markets; falls back to all markets for display only.
    """
    markets = event.get("markets", [])
    active  = [m for m in markets if _is_market_active(m)]
    pool    = active if active else markets

    best_m   = None
    best_p   = None
    best_liq = -1.0

    for m in pool:
        price = _extract_price(m)
        if price is None:
            continue
        liq = float(m.get("liquidityClob") or m.get("liquidity") or 0)
        if liq > best_liq:
            best_liq = liq
            best_m   = m
            best_p   = price

    return (best_m, best_p) if best_m else None


def _format_event(
    event:     dict,
    market:    dict,
    price:     float,
    sentiment: float | None = None,
) -> dict:
    return {
        "id"        : str(market.get("conditionId") or market.get("id", "")),
        "question"  : market.get("question", event.get("title", "")),
        "end_date"  : (market.get("endDateIso") or market.get("endDate", ""))[:10],
        "yes_prob"  : round(price, 4),
        "no_prob"   : round(1 - price, 4),
        "sentiment" : round(sentiment, 4) if sentiment is not None else None,
        "volume_usd": float(event.get("volume") or 0),
        "url"       : f"https://polymarket.com/event/{event.get('slug', '')}",
    }

# ════════════════════════════════════════════════════════════════════════════
# LAYER 7 ── Score calculation
# ════════════════════════════════════════════════════════════════════════════

def _compute_score(sentiment_records: list[dict]) -> float:
    """
    log1p(volume)-weighted average sentiment, capped per-event at 30%.

    log1p compression: a $10 M event is only 3.3× a $1 k event
    (vs 100× with raw volume, 10× with sqrt).
    30% cap: no single event can contribute more than 30% of total weight.
    """
    if not sentiment_records:
        return 0.5

    valid = [r for r in sentiment_records if r.get("sentiment") is not None]
    if not valid:
        return 0.5

    raw_w = [math.log1p(r["volume_usd"] + 1.0) for r in valid]
    total = sum(raw_w)

    if total > 0:
        cap   = 0.30 * total
        raw_w = [min(w, cap) for w in raw_w]
        total = sum(raw_w)

    if total > 0:
        score = sum(r["sentiment"] * w for r, w in zip(valid, raw_w)) / total
    else:
        score = sum(r["sentiment"] for r in valid) / len(valid)

    return round(max(0.0, min(1.0, score)), 4)


def _score_label(score: float) -> str:
    if score >= 0.70:   return "Strongly Bullish"
    elif score >= 0.55: return "Slightly Bullish"
    elif score >= 0.45: return "Neutral"
    elif score >= 0.30: return "Slightly Bearish"
    else:               return "Strongly Bearish"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 8 ── Gemini filter
# ════════════════════════════════════════════════════════════════════════════

def _parse_json_array(text: str) -> list:
    for candidate in [
        text.strip(),
        re.sub(r"```(?:json)?|```", "", text).strip(),
    ]:
        try:
            r = json.loads(candidate)
            if isinstance(r, list):
                return [str(x) for x in r]
        except json.JSONDecodeError:
            pass

    match = re.search(r"\[[\s\S]*?\]", text)
    if match:
        try:
            r = json.loads(match.group())
            if isinstance(r, list):
                return [str(x) for x in r]
        except json.JSONDecodeError:
            pass

    return []


def _gemini_filter(ticker: str, events: list[dict]) -> list[dict]:
    """Filter events to ticker-relevant ones. Falls back on any error."""
    global _last_gemini_ts

    if not _gemini_client or not events:
        return events

    gap = time.time() - _last_gemini_ts
    if gap < GEMINI_MIN_GAP:
        logger.info("Gemini throttle: %.1fs remaining", GEMINI_MIN_GAP - gap)
        time.sleep(GEMINI_MIN_GAP - gap)

    compact = [
        {"id": str(e.get("id", "")), "title": e.get("title", "")}
        for e in events
    ]

    prompt = f"""Financial analyst task. Ticker: {ticker}
From these Polymarket events, return IDs of events directly relevant
to {ticker} stock price or sentiment. Include direct price bets,
earnings, revenue, macro events affecting {ticker}'s sector.

Return ONLY a JSON array of id strings. No markdown. If none: []

{json.dumps(compact, indent=2)}"""

    try:
        _last_gemini_ts = time.time()
        resp = _gemini_client.models.generate_content(
            model    = "gemini-2.5-flash",
            contents = prompt,
            config   = {"temperature": 0.0, "max_output_tokens": 512},
        )
        _last_gemini_ts = time.time()

        ids = _parse_json_array(resp.text)
        if not ids:
            return events

        id_set   = set(ids)
        filtered = [e for e in events if str(e.get("id", "")) in id_set]
        logger.info("Gemini: %d → %d events for %s",
                    len(events), len(filtered), ticker)
        return filtered if filtered else events

    except Exception as e:
        if "429" in str(e):
            logger.warning("Gemini 429 — skipping filter for %s", ticker)
        else:
            logger.warning("Gemini error: %s", e)
        return events

# ════════════════════════════════════════════════════════════════════════════
# PUBLIC: search_markets
# ════════════════════════════════════════════════════════════════════════════

def search_markets(keyword: str, limit: int = 5) -> list[dict]:
    """Frontend search — returns raw market list for dashboard table."""
    events  = _search_events(keyword, limit=limit * 2)
    results = []

    for event in events:
        result = _best_market_from_event(event)
        if result:
            market, price = result
            results.append(_format_event(event, market, price))
        if len(results) >= limit:
            break

    return results

# ════════════════════════════════════════════════════════════════════════════
# PUBLIC: polymarket_market_sentiment
# ════════════════════════════════════════════════════════════════════════════

def polymarket_market_sentiment(ticker: str = "SPY") -> dict:
    """
    Main entry point for /api/kpis and /api/signal.

    Pipeline:
    1.  Cache check (5-min TTL)
    2.  Search ticker events via /search-v2
    3.  Optional Gemini filter (relevance)
    4.  Per-event: filter inactive markets → ATM or best market
    5.  Convert to [0, 1] sentiment (skipping expired/dust/extreme markets)
    6.  log1p(volume)-weighted score with 30% per-event cap
    7.  Macro fallback if no ticker events found
    """
    ticker = ticker.upper()
    now    = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ── 1. Cache ──────────────────────────────────────────────────────────
    if ticker in _ticker_cache:
        ts, cached = _ticker_cache[ticker]
        if time.time() - ts < CACHE_TTL:
            logger.info("Cache hit: %s", ticker)
            return cached

    queries = TICKER_QUERIES.get(ticker, [ticker])
    source  = "search-v2 + Gemini" if _gemini_client else "search-v2"
    logger.info("Pipeline | ticker=%s queries=%s", ticker, queries)

    # ── 2. Search ─────────────────────────────────────────────────────────
    events = _search_multi(queries, limit=10)

    # ── 3. Gemini filter ──────────────────────────────────────────────────
    if events and _gemini_client and len(events) > 3:
        events = _gemini_filter(ticker, events)

    # ── 4 + 5. Sentiment per event ────────────────────────────────────────
    formatted: list[dict] = []

    for event in events:
        sent_result = _sentiment_from_event(event)
        display     = _best_market_from_event(event)
        if display is None:
            continue

        market, price = display
        sentiment     = sent_result[0] if sent_result else None
        method        = sent_result[2] if sent_result else "no-sentiment"

        rec = _format_event(event, market, price, sentiment=sentiment)
        rec["_method"] = method
        formatted.append(rec)

        logger.debug(
            "Event: %-45s | raw=%.2f | sent=%s | %s",
            event.get("title", "")[:45],
            price,
            f"{sentiment:.2f}" if sentiment is not None else "None",
            method,
        )

    logger.info("Events with prices: %d", len(formatted))

    # ── 6. Macro fallback ─────────────────────────────────────────────────
    if not formatted:
        logger.info("No ticker events → macro fallback for %s", ticker)
        for event in _search_multi(MACRO_QUERIES, limit=5):
            sent_result = _sentiment_from_event(event)
            display     = _best_market_from_event(event)
            if display is None:
                continue
            market, price = display
            sentiment     = sent_result[0] if sent_result else None
            rec = _format_event(event, market, price, sentiment=sentiment)
            formatted.append(rec)
        source += " (Macro Fallback)"

    # ── 7. Score ──────────────────────────────────────────────────────────
    if not formatted:
        result = {
            "score"     : 0.5,
            "label"     : "Neutral",
            "markets"   : [],
            "ticker"    : ticker,
            "fetched_at": now,
            "source"    : "No Markets Found",
        }
        _ticker_cache[ticker] = (time.time(), result)
        return result

    score = _compute_score(formatted)
    label = _score_label(score)

    clean_markets = [
        {k: v for k, v in m.items() if not k.startswith("_")}
        for m in formatted[:10]
    ]

    result = {
        "score"     : score,
        "label"     : label,
        "markets"   : clean_markets,
        "ticker"    : ticker,
        "fetched_at": now,
        "source"    : source,
    }

    _ticker_cache[ticker] = (time.time(), result)
    logger.info("Done | %s score=%.3f label=%s markets=%d",
                ticker, score, label, len(formatted))
    return result

# ════════════════════════════════════════════════════════════════════════════
# SELF TEST
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level  = logging.INFO,
        format = "%(asctime)s | %(levelname)s | %(message)s",
    )

    # ── Step 1: Classification unit tests ─────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 1: Classification + sentiment mapping")
    print("=" * 60)

    test_cases = [
        ("Will NVDA close above $160 on April 6?",   0.78,  "above",    0.78),
        ("Will NVDA close above $200 on April 6?",   0.12,  "above",    0.12),
        ("Will NVDA close above $120 on April 6?",   0.96,  "above",    0.96),
        ("Will TSLA close at $250-$260 on April 6?", 0.08,  "range",    None),
        ("Will Bitcoin reach $150,000 in April?",    0.01,  "reach",    0.01),
        ("Will S&P 500 hit $7,700 (HIGH) in June?",  0.03,  "hit_high", 0.03),
        ("Will S&P 500 hit $4,500 (LOW) in June?",   0.30,  "hit_low",  0.70),
        ("US recession by end of 2026?",             0.285, "other",    None),
    ]

    all_pass = True
    for q, p, exp_type, exp_sent in test_cases:
        info = _classify_market(q)
        sent = _market_to_sentiment(p, info)
        ok   = (info["type"] == exp_type) and (sent == exp_sent)
        all_pass = all_pass and ok
        print(f"  {'✓' if ok else '✗'} [{p:.0%}] {q[:55]}")
        print(f"      type={info['type']:8s} sentiment={sent} expected={exp_sent}")

    print(f"\n  {'ALL PASS ✓' if all_pass else 'FAILURES ✗'}")

    # ── Step 2: Active-market filter ──────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: Active-market filter")
    print("=" * 60)

    fake_dust = {
        "question"     : "Will NVDA close above $200 on Jan 1?",
        "liquidityClob": "10",
        "endDateIso"   : "2026-06-01T00:00:00Z",
        "outcomePrices": "[0.50, 0.50]",
    }
    fake_expired = {
        "question"     : "Will NVDA close above $200 on Jan 1?",
        "liquidityClob": "5000",
        "endDateIso"   : "2026-01-01T00:00:00Z",
        "outcomePrices": "[0.50, 0.50]",
    }
    fake_resolved = {
        "question"     : "Will NVDA close above $50 on Jan 1?",
        "liquidityClob": "5000",
        "endDateIso"   : "2026-06-01T00:00:00Z",
        "outcomePrices": "[0.995, 0.005]",
    }
    fake_active = {
        "question"     : "Will NVDA close above $150 on Jun 1?",
        "liquidityClob": "5000",
        "endDateIso"   : "2026-06-01T00:00:00Z",
        "outcomePrices": "[0.52, 0.48]",
    }

    tests = [
        (fake_dust,     False, "dust liquidity"),
        (fake_expired,  False, "past end date"),
        (fake_resolved, False, "resolved price 99.5%"),
        (fake_active,   True,  "active liquid market"),
    ]
    for market, expected, label in tests:
        result = _is_market_active(market)
        ok     = result == expected
        print(f"  {'✓' if ok else '✗'} {label}: active={result} (expected {expected})")

    # ── Step 3: Full pipeline ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: Full pipeline")
    print("=" * 60)

    for t in ["TSLA", "GOOGL", "NVDA", "SPY", "BTC"]:
        print(f"\n  ── {t} ──")
        r = polymarket_market_sentiment(t)
        print(f"  Score  : {r['score']} ({r['label']})")
        print(f"  Markets: {len(r['markets'])} | Source: {r['source']}")
        for m in r["markets"][:3]:
            s = m.get("sentiment")
            tag = f"sent={s:.2f}" if s is not None else "no-sent"
            print(f"    [raw={m['yes_prob']:.0%} {tag}] {m['question'][:55]}")