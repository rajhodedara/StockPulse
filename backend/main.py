"""
main.py  –  FastAPI  (Person 1 endpoints)
"""

from __future__ import annotations
import logging
import traceback
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# FIX: Remove 'backend.' prefix since main.py is inside the backend folder
from data.news_ingestor import fetch_news
from models.sentiment_engine import (
    analyze_sentiment, 
    get_average_score, 
    get_signal, 
    calculate_confidence, 
    generate_reason
)
from data.market_data import fetch_ohlcv, latest_price, to_records
from data.technical import add_all_indicators, latest_indicator_snapshot, rsi_signal
from data.polymarket import search_markets, polymarket_market_sentiment

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title   = "Market Prediction API",
    version = "0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_methods = ["GET"],
    allow_headers = ["*"],
)


@app.get("/")
def root():
    return {
        "app"      : "Market Prediction Dashboard",
        "status"   : "running",
        "docs"     : "http://localhost:8000/docs",
        "endpoints": ["/health", "/api/price-history", "/api/polymarket", "/api/kpis"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/price-history")
def price_history(
    ticker      : str  = Query("AAPL"),
    period_days : int  = Query(180, ge=5, le=730),
    interval    : str  = Query("1d"),
    indicators  : bool = Query(True),
):
    try:
        df = fetch_ohlcv(ticker, period_days=period_days, interval=interval)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("price-history error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Data fetch error: {exc}")

    try:
        if indicators:
            df = add_all_indicators(df)
    except Exception as exc:
        logger.error("Indicator error:\n%s", traceback.format_exc())
        # Return raw OHLCV if indicators fail
        pass

    records = to_records(df)
    return {
        "ticker"  : ticker.upper(),
        "interval": interval,
        "count"   : len(records),
        "records" : records,
    }


@app.get("/api/polymarket")
def polymarket_endpoint(
    keyword: Optional[str] = Query(None),
):
    if keyword:
        markets = search_markets(keyword, limit=10)
        return {"keyword": keyword, "markets": markets}
    return polymarket_market_sentiment()


@app.get("/api/kpis")
def kpis(ticker: str = Query("AAPL")):
    # Price
    try:
        price_info = latest_price(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("KPI price error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Technicals
    snap = {}
    try:
        df   = fetch_ohlcv(ticker, period_days=90)
        snap = latest_indicator_snapshot(df)
    except Exception as exc:
        logger.warning("Technicals failed for %s: %s", ticker, exc)

    # Polymarket
    poly_score, poly_label = None, "Unavailable"
    try:
        poly       = polymarket_market_sentiment()
        poly_score = poly["score"]
        poly_label = poly["label"]
    except Exception as exc:
        logger.warning("Polymarket failed: %s", exc)

    return {
        "ticker"           : price_info["ticker"],
        "price"            : price_info["price"],
        "prev_close"       : price_info["prev_close"],
        "change_pct"       : price_info["change_pct"],
        "as_of"            : price_info["as_of"],
        "rsi"              : snap.get("rsi"),
        "rsi_signal"       : rsi_signal(snap.get("rsi")),
        "macd"             : snap.get("macd"),
        "macd_signal"      : snap.get("macd_signal"),
        "macd_hist"        : snap.get("macd_hist"),
        "bb_upper"         : snap.get("bb_upper"),
        "bb_lower"         : snap.get("bb_lower"),
        "sma_7"            : snap.get("sma_7"),
        "sma_21"           : snap.get("sma_21"),
        "sma_50"           : snap.get("sma_50"),
        "polymarket_score" : poly_score,
        "polymarket_label" : poly_label,
    }

@app.get("/api/sentiment")
def sentiment_endpoint(ticker: str = Query("AAPL")):
    try:
        # 1. Fetch the raw news headlines
        news_list = fetch_news(ticker, limit=10)
        
        if not news_list:
            return {"ticker": ticker.upper(), "error": "No recent news found."}

        # 2. Run the news through FinBERT
        analyzed_news = analyze_sentiment(news_list)

        # 3. Calculate the aggregate metrics
        avg_score = get_average_score(analyzed_news)
        signal = get_signal(avg_score)
        confidence = calculate_confidence(analyzed_news)
        reason = generate_reason(analyzed_news)

        # 4. Send the clean package to the frontend
        return {
            "ticker": ticker.upper(),
            "summary": {
                "signal": signal,           # e.g., "STRONG BUY"
                "score": avg_score,         # e.g., 0.45
                "confidence": confidence,   # e.g., 0.8
                "reason": reason            # e.g., "Majority positive news sentiment"
            },
            "articles": analyzed_news       # The individual headlines and their scores
        }
        
    except Exception as exc:
        logger.error(f"Sentiment analysis failed for {ticker}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to process sentiment analysis.")
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)