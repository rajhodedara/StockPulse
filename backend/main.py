"""
main.py  –  FastAPI
"""

from __future__ import annotations
import logging
import traceback
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from data.news_ingestor import fetch_news
from models.sentiment_engine import (
    analyze_sentiment,
    get_average_score,
    get_signal,
    calculate_confidence,
    generate_reason,
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


# ════════════════════════════════════════════════════════════════════════════
# Root / Health
# ════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "app"      : "Market Prediction Dashboard",
        "status"   : "running",
        "docs"     : "http://localhost:8000/docs",
        "endpoints": [
            "/health",
            "/api/price-history",
            "/api/polymarket",
            "/api/kpis",
            "/api/sentiment",
            "/api/signal",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# ════════════════════════════════════════════════════════════════════════════
# Price history + indicators
# ════════════════════════════════════════════════════════════════════════════

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

    if indicators:
        try:
            df = add_all_indicators(df)
        except Exception:
            logger.error("Indicator error:\n%s", traceback.format_exc())
            # Return raw OHLCV if indicators fail — non-fatal

    records = to_records(df)
    return {
        "ticker"  : ticker.upper(),
        "interval": interval,
        "count"   : len(records),
        "records" : records,
    }


# ════════════════════════════════════════════════════════════════════════════
# Polymarket
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/polymarket")
def polymarket_endpoint(
    ticker  : str           = Query("SPY"),
    keyword : Optional[str] = Query(None),
):
    """
    GET /api/polymarket?ticker=TSLA
    GET /api/polymarket?keyword=bitcoin
    """
    if keyword:
        markets = search_markets(keyword, limit=10)
        return {
            "keyword": keyword,
            "markets": markets,
        }

    result = polymarket_market_sentiment(ticker)
    return result


# ════════════════════════════════════════════════════════════════════════════
# KPIs  (price + technicals + polymarket sentiment)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/kpis")
def kpis(ticker: str = Query("AAPL")):
    """
    GET /api/kpis?ticker=NVDA
    """
    # ── Price ──────────────────────────────────────────────────────────────
    try:
        price_info = latest_price(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("KPI price error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # ── Technicals ─────────────────────────────────────────────────────────
    snap: dict = {}
    try:
        df   = fetch_ohlcv(ticker, period_days=90)
        # THE FIX: Removed the redundant df = add_all_indicators(df) here
        snap = latest_indicator_snapshot(df)
    except Exception as exc:
        logger.warning("Technicals failed for %s: %s", ticker, exc)

    # ── Polymarket ─────────────────────────────────────────────────────────
    poly_score : float | None = None
    poly_label : str          = "Unavailable"
    poly_markets: list        = []

    try:
        poly        = polymarket_market_sentiment(ticker)
        poly_score  = poly["score"]
        poly_label  = poly["label"]
        poly_markets = poly.get("markets", [])
        logger.info("Polymarket %s → %.3f (%s)", ticker, poly_score, poly_label)
    except Exception as exc:
        logger.warning("Polymarket failed for %s: %s", ticker, exc)

    return {
        # ── Identity ────────────────────────────────────────────────────
        "ticker"           : price_info["ticker"],
        "as_of"            : price_info["as_of"],

        # ── Price ────────────────────────────────────────────────────────
        "price"            : price_info["price"],
        "prev_close"       : price_info["prev_close"],
        "change_pct"       : price_info["change_pct"],

        # ── Technicals ───────────────────────────────────────────────────
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

        # ── Polymarket ───────────────────────────────────────────────────
        "polymarket_score"   : poly_score,
        "polymarket_label"   : poly_label,
        "polymarket_markets" : poly_markets[:5],   
    }


# ════════════════════════════════════════════════════════════════════════════
# News sentiment  (FinBERT)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/sentiment")
def sentiment_endpoint(ticker: str = Query("AAPL")):
    """
    GET /api/sentiment?ticker=TSLA
    """
    try:
        news_list = fetch_news(ticker, limit=10)

        if not news_list:
            return {
                "ticker" : ticker.upper(),
                "error"  : "No recent news found.",
            }

        analyzed_news = analyze_sentiment(news_list)
        avg_score     = get_average_score(analyzed_news)
        signal        = get_signal(avg_score)
        confidence    = calculate_confidence(analyzed_news)
        reason        = generate_reason(analyzed_news)

        return {
            "ticker"  : ticker.upper(),
            "summary" : {
                "signal"    : signal,
                "score"     : avg_score,
                "confidence": confidence,
                "reason"    : reason,
            },
            "articles": analyzed_news,
        }

    except Exception as exc:
        logger.error("Sentiment failed for %s: %s", ticker, exc)
        raise HTTPException(
            status_code = 500,
            detail      = "Failed to process sentiment analysis.",
        )


# ════════════════════════════════════════════════════════════════════════════
# Combined signal  (all sources → one verdict)
# ════════════════════════════════════════════════════════════════════════════

@app.get("/api/signal")
def signal_endpoint(ticker: str = Query("AAPL")):
    """
    GET /api/signal?ticker=NVDA
    """
    result: dict = {
        "ticker"          : ticker.upper(),
        "technical_signal": None,
        "news_signal"     : None,
        "polymarket_score": None,
        "polymarket_label": None,
        "final_signal"    : "HOLD",
        "confidence"      : 0.0,
        "reasons"         : [],
    }

    reasons: list[str] = []

    # ── Technicals ─────────────────────────────────────────────────────────
    try:
        df   = fetch_ohlcv(ticker, period_days=90)
        # THE FIX: Removed the redundant df = add_all_indicators(df) here
        snap = latest_indicator_snapshot(df)
        rsi  = snap.get("rsi")

        tech_signal = rsi_signal(rsi)
        result["technical_signal"] = tech_signal

        if rsi is not None:
            reasons.append(f"RSI={rsi:.1f} → {tech_signal}")
    except Exception as exc:
        logger.warning("Signal technicals failed for %s: %s", ticker, exc)

    # ── News sentiment ─────────────────────────────────────────────────────
    try:
        news_list     = fetch_news(ticker, limit=10)
        analyzed_news = analyze_sentiment(news_list) if news_list else []
        avg_score     = get_average_score(analyzed_news)
        news_sig      = get_signal(avg_score)

        result["news_signal"] = news_sig
        if analyzed_news:
            reasons.append(f"News sentiment={avg_score:.2f} → {news_sig}")
    except Exception as exc:
        logger.warning("Signal news failed for %s: %s", ticker, exc)

    # ── Polymarket ─────────────────────────────────────────────────────────
    try:
        poly = polymarket_market_sentiment(ticker)  
        result["polymarket_score"] = poly["score"]
        result["polymarket_label"] = poly["label"]
        reasons.append(
            f"Polymarket={poly['score']:.2f} → {poly['label']}"
        )
    except Exception as exc:
        logger.warning("Signal polymarket failed for %s: %s", ticker, exc)

    # ── Combine into final verdict ─────────────────────────────────────────
    signals = []

    tech = result.get("technical_signal", "")
    if tech in ("BUY", "STRONG BUY"):
        signals.append(1)
    elif tech in ("SELL", "STRONG SELL"):
        signals.append(-1)
    else:
        signals.append(0)

    news = result.get("news_signal", "")
    if news in ("BUY", "STRONG BUY"):
        signals.append(1)
    elif news in ("SELL", "STRONG SELL"):
        signals.append(-1)
    else:
        signals.append(0)

    poly_score = result.get("polymarket_score")
    if poly_score is not None:
        if poly_score >= 0.60:
            signals.append(1)
        elif poly_score <= 0.40:
            signals.append(-1)
        else:
            signals.append(0)

    if signals:
        avg = sum(signals) / len(signals)
        if avg >= 0.5:
            result["final_signal"] = "BUY"
        elif avg <= -0.5:
            result["final_signal"] = "SELL"
        else:
            result["final_signal"] = "HOLD"

        result["confidence"] = round(abs(avg), 3)

    result["reasons"] = reasons
    return result


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)