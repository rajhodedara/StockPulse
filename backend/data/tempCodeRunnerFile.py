"""
polymarket.py
=============
AI-Powered Polymarket Engine using Gamma API (Discovery) + Gemini (Filtering).
"""

import json
import logging
import requests
import os
from datetime import datetime
from functools import lru_cache
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# ── Gemini Setup ──────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # Using Flash because it's insanely fast and perfect for quick JSON routing
    llm = genai.GenerativeModel('gemini-2.5-flash') 
else:
    logger.warning("GEMINI_API_KEY not found in .env! LLM filtering will fail.")
    llm = None

# ── Config ────────────────────────────────────────────────────────────────────
GAMMA_BASE = "https://gamma-api.polymarket.com"
TIMEOUT    = 15

# We still use a small map just to get the best initial search queries
TICKER_KEYWORD_MAP = {
    "AAPL": "Apple", "TSLA": "Tesla", "NVDA": "Nvidia", 
    "MSFT": "Microsoft", "AMZN": "Amazon", "SPY": "S&P 500"
}


# ── 1. Discovery (The Wide Net) ───────────────────────────────────────────────
def _fetch_raw_markets(keyword: str, limit: int = 15) -> list:
    """Hits Polymarket's search API to grab potential markets."""
    try:
        resp = requests.get(
            f"{GAMMA_BASE}/markets",
            params={
                "search": keyword,
                "active": "true",
                "closed": "false",
                "limit": limit
            },
            timeout=TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        logger.error(f"Failed to fetch raw markets for {keyword}: {e}")
        return []


# ── 2. AI Filtering (The Brain) ───────────────────────────────────────────────
def _filter_with_gemini(ticker: str, raw_markets: list) -> list:
    """Uses Gemini to surgically extract only highly relevant finance markets."""
    if not llm or not raw_markets:
        return []

    # Strip the data down so we don't overwhelm the LLM context window
    compact_markets = [
        {"id": m.get("id"), "question": m.get("question")} 
        for m in raw_markets if m.get("id") and m.get("question")
    ]

    prompt = f"""
    You are an expert financial data analyst.
    I am looking for prediction markets that directly impact the stock price, 
    corporate performance, or financial outlook of the ticker: {ticker}.
    
    Review the following list of markets. 
    Identify the IDs of markets that are strictly related to {ticker}'s business, stock price, or major macroeconomic factors affecting it.
    IGNORE sports, pop culture, politics (unless it directly names the company's executives/regulation), and unrelated tech.
    
    Return ONLY a valid JSON array of strings containing the relevant IDs. Nothing else.
    Example output: ["12345", "67890"]
    
    Markets to analyze:
    {json.dumps(compact_markets, indent=2)}
    """

    try:
        response = llm.generate_content(prompt)
        # Clean the response to ensure it's parseable JSON
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        valid_ids = json.loads(clean_text)
        
        # Return the full market objects that match the Gemini-approved IDs
        return [m for m in raw_markets if str(m.get("id")) in valid_ids]
    
    except Exception as e:
        logger.error(f"Gemini filtering failed: {e}")
        return [] # Fail safe


# ── 3. Formatting (The Engine) ────────────────────────────────────────────────
def _extract_yes_prob(market: dict) -> float:
    """Safely extracts the YES probability from the market tokens."""
    tokens = market.get("tokens", [])
    for t in tokens:
        if str(t.get("outcome", "")).upper() == "YES":
            try:
                return float(t.get("price", 0))
            except (ValueError, TypeError):
                return 0.0
    return 0.0

def search_markets(keyword: str, limit: int = 5) -> list[dict]:
    """Compatibility function for the frontend table."""
    raw = _fetch_raw_markets(keyword, limit=limit)
    valid_markets = []
    
    for m in raw:
        yes_prob = _extract_yes_prob(m)
        if yes_prob > 0:
            valid_markets.append({
                "id": m.get("id", ""),
                "question": m.get("question", ""),
                "end_date": (m.get("endDate", "") or "")[:10],
                "yes_prob": yes_prob,
                "volume_usd": float(m.get("volume", 0) or 0),
            })
    return valid_markets[:limit]


# ── 4. Main Export (The Dashboard Hook) ───────────────────────────────────────
@lru_cache(maxsize=32)
def polymarket_market_sentiment(ticker: str = "SPY") -> dict:
    """The main endpoint called by main.py /api/kpis"""
    
    keyword = TICKER_KEYWORD_MAP.get(ticker.upper(), ticker.upper())
    logger.info(f"Triggering AI Polymarket Pipeline for {ticker} (Keyword: {keyword})")

    # 1. Broad Search
    raw_markets = _fetch_raw_markets(keyword, limit=20)
    
    # 2. Gemini Filtering
    approved_markets = _filter_with_gemini(ticker, raw_markets)

    # 3. Process the AI-approved markets
    formatted_markets = []
    for m in approved_markets:
        yes_prob = _extract_yes_prob(m)
        if yes_prob > 0:
            formatted_markets.append({
                "id": m.get("id", ""),
                "question": m.get("question", ""),
                "end_date": (m.get("endDate", "") or "")[:10],
                "yes_prob": round(yes_prob, 4),
                "volume_usd": float(m.get("volume", 0) or 0),
            })

    # 4. Calculate Aggregate Score
    if not formatted_markets:
        return {
            "score": 0.5,
            "label": "Neutral",
            "markets": [],
            "ticker": ticker,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
            "source": "AI Filtered (None Valid)"
        }

    total_vol = sum(m["volume_usd"] for m in formatted_markets)
    if total_vol > 0:
        score = sum(m["yes_prob"] * m["volume_usd"] for m in formatted_markets) / total_vol
    else:
        score = sum(m["yes_prob"] for m in formatted_markets) / len(formatted_markets)

    score = round(max(0.0, min(1.0, score)), 4)

    # 5. Determine Label
    if score >= 0.70: label = "Strongly Bullish"
    elif score >= 0.55: label = "Slightly Bullish"
    elif score >= 0.45: label = "Neutral"
    elif score >= 0.30: label = "Slightly Bearish"
    else: label = "Strongly Bearish"

    return {
        "score": score,
        "label": label,
        "markets": formatted_markets,
        "ticker": ticker,
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds"),
        "source": "Gemini AI Live"
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(polymarket_market_sentiment("TSLA"))