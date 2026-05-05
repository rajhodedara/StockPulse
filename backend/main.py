"""
main.py - FastAPI
"""

from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from data.market_data import fetch_ohlcv, latest_price, to_records
from data.news_ingestor import fetch_news
from data.polymarket import polymarket_market_sentiment, search_markets
from data.social_ingestor import fetch_social_posts
from data.technical import add_all_indicators, latest_indicator_snapshot, rsi_signal
from models.scoring_engine import build_signal_payload
from models.sentiment_engine import (
    analyze_sentiment,
    calculate_confidence,
    generate_reason,
    get_average_score,
    get_signal,
)
from models.social_sentiment_engine import analyze_social_sentiment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Market Prediction API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _balanced_articles(
    analyzed_news: list[dict],
    analyzed_social: list[dict],
    total_limit: int = 12,
    max_per_source: int = 4,
) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)

    for article in analyzed_news + analyzed_social:
        source = (article.get("source") or "news").lower()
        if len(grouped[source]) < max_per_source:
            grouped[source].append(article)

    preferred_order = ["stocktwits", "reddit", "news"]
    balanced: list[dict] = []
    index = 0

    while len(balanced) < total_limit:
        added = False
        for source in preferred_order:
            source_items = grouped.get(source, [])
            if index < len(source_items):
                balanced.append(source_items[index])
                added = True
                if len(balanced) >= total_limit:
                    break
        if not added:
            break
        index += 1

    return balanced


@app.get("/")
def root():
    return {
        "app": "Market Prediction Dashboard",
        "status": "running",
        "docs": "http://localhost:8000/docs",
        "endpoints": [
            "/health",
            "/api/price-history",
            "/api/polymarket",
            "/api/kpis",
            "/api/sentiment",
            "/api/social-sentiment",
            "/api/signal",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/price-history")
def price_history(
    ticker: str = Query("AAPL"),
    period_days: int = Query(180, ge=5, le=730),
    interval: str = Query("1d"),
    indicators: bool = Query(True),
):
    try:
        df = fetch_ohlcv(ticker, period_days=period_days, interval=interval)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("price-history error:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Data fetch error: {exc}")

    if indicators:
        try:
            df = add_all_indicators(df)
        except Exception:
            logger.error("Indicator error:\n%s", traceback.format_exc())

    records = to_records(df)
    return {
        "ticker": ticker.upper(),
        "interval": interval,
        "count": len(records),
        "records": records,
    }


@app.get("/api/polymarket")
def polymarket_endpoint(
    ticker: str = Query("SPY"),
    keyword: Optional[str] = Query(None),
):
    if keyword:
        return {
            "keyword": keyword,
            "markets": search_markets(keyword, limit=10),
        }

    return polymarket_market_sentiment(ticker)


@app.get("/api/kpis")
def kpis(ticker: str = Query("AAPL")):
    try:
        price_info = latest_price(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("KPI price error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    snap: dict = {}
    try:
        df = fetch_ohlcv(ticker, period_days=90)
        snap = latest_indicator_snapshot(df)
    except Exception as exc:
        logger.warning("Technicals failed for %s: %s", ticker, exc)

    poly_score: float | None = None
    poly_label = "Unavailable"
    poly_markets: list = []

    try:
        poly = polymarket_market_sentiment(ticker)
        poly_score = poly["score"]
        poly_label = poly["label"]
        poly_markets = poly.get("markets", [])
        logger.info("Polymarket %s -> %.3f (%s)", ticker, poly_score, poly_label)
    except Exception as exc:
        logger.warning("Polymarket failed for %s: %s", ticker, exc)

    return {
        "ticker": price_info["ticker"],
        "as_of": price_info["as_of"],
        "price": price_info["price"],
        "prev_close": price_info["prev_close"],
        "change_pct": price_info["change_pct"],
        "rsi": snap.get("rsi"),
        "rsi_signal": rsi_signal(snap.get("rsi")),
        "macd": snap.get("macd"),
        "macd_signal": snap.get("macd_signal"),
        "macd_hist": snap.get("macd_hist"),
        "bb_upper": snap.get("bb_upper"),
        "bb_lower": snap.get("bb_lower"),
        "sma_7": snap.get("sma_7"),
        "sma_21": snap.get("sma_21"),
        "sma_50": snap.get("sma_50"),
        "polymarket_score": poly_score,
        "polymarket_label": poly_label,
        "polymarket_markets": poly_markets[:5],
    }


@app.get("/api/sentiment")
def sentiment_endpoint(ticker: str = Query("AAPL")):
    try:
        news_list = fetch_news(ticker, limit=10)
        analyzed_news = analyze_sentiment(news_list)
        analyzed_social: list[dict] = []

        try:
            social_posts = fetch_social_posts(ticker, limit_per_source=5)
            social_summary = analyze_social_sentiment(social_posts)
            analyzed_social = social_summary.get("posts", [])
        except Exception as exc:
            logger.warning("Social sentiment merge failed for %s: %s", ticker, exc)

        articles = _balanced_articles(analyzed_news, analyzed_social)
        if not articles:
            return {
                "ticker": ticker.upper(),
                "error": "No recent news found.",
            }

        avg_score = get_average_score(articles)
        signal = get_signal(avg_score)
        confidence = calculate_confidence(articles)
        reason = generate_reason(articles)
        sources = [
            {
                "title": article.get("title") or article.get("text") or "News article",
                "source": article.get("source", "news"),
                "url": article.get("url", ""),
            }
            for article in articles[:5]
            if article.get("url")
        ]

        return {
            "ticker": ticker.upper(),
            "summary": {
                "signal": signal,
                "score": avg_score,
                "confidence": confidence,
                "reason": reason,
            },
            "articles": articles,
            "sources": sources,
        }
    except Exception as exc:
        logger.error("Sentiment failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to process sentiment analysis.",
        )


@app.get("/api/social-sentiment")
def social_sentiment_endpoint(ticker: str = Query("AAPL")):
    try:
        posts = fetch_social_posts(ticker, limit_per_source=20)
        summary = analyze_social_sentiment(posts)
        return {
            "ticker": ticker.upper(),
            "summary": {
                "signal": get_signal(summary["score"]),
                "score": summary["score"],
                "confidence": summary["confidence"],
                "volume": summary["volume"],
            },
            "posts": summary["posts"],
        }
    except Exception as exc:
        logger.error("Social sentiment failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to process social sentiment analysis.",
        )


@app.get("/api/signal")
def signal_endpoint(ticker: str = Query("AAPL")):
    return build_signal_payload(ticker)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
