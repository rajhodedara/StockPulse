from fastapi import FastAPI

from data.news_ingestor import fetch_news, resolve_stock
from models.sentiment_engine import (
    analyze_sentiment,
    get_average_score,
    get_signal,
    calculate_confidence,
    generate_reason
)

app = FastAPI()


@app.get("/")
def home():
    return {"message": "Feelow API is running 🚀"}


@app.get("/analyze")
def analyze_stock(ticker: str):
    stock = resolve_stock(ticker)

    # STEP 1: Fetch news
    news = fetch_news(stock["symbol"])

    if not news:
        return {"error": "No news found"}

    # STEP 2: Analyze sentiment
    analyzed = analyze_sentiment(news)

    # STEP 3: Aggregate score
    avg_score = get_average_score(analyzed)

    # STEP 4: Get signal + confidence
    signal = get_signal(avg_score)
    confidence = calculate_confidence(analyzed)
    reason = generate_reason(analyzed)

    return {
        "ticker": stock["symbol"],
        "company_name": stock["company_name"],
        "exchange": stock.get("exchange"),
        "resolved_from": stock.get("resolved_from", ticker),
        "sentiment_score": avg_score,
        "confidence": confidence,
        "signal": signal,
        "reason": reason,
        "details": analyzed
    }
