"""
market_data.py
==============
Fetches OHLCV price history via yfinance.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_PERIOD_DAYS = 180
VALID_INTERVALS     = {"1d", "1h", "30m", "15m", "5m"}

def fetch_ohlcv(
    ticker: str,
    period_days: int = DEFAULT_PERIOD_DAYS,
    interval: str = "1d",
) -> pd.DataFrame:
    if interval not in VALID_INTERVALS:
        raise ValueError(f"interval must be one of {VALID_INTERVALS}")

    # FIX 1: Cap at 59 and 729 to provide a safe timezone buffer for Yahoo's strict limits
    if interval in ["30m", "15m", "5m"] and period_days > 59:
        logger.warning(f"Yahoo Finance limits '{interval}' data to 60 days. Capping period_days to 59.")
        period_days = 59
    elif interval == "1h" and period_days > 729:
        logger.warning(f"Yahoo Finance limits '1h' data to 730 days. Capping period_days to 729.")
        period_days = 729

    start_date = datetime.utcnow() - timedelta(days=period_days)

    logger.info("Fetching %s | %s days | interval=%s", ticker, period_days, interval)

    ticker_obj = yf.Ticker(ticker.upper())
    
    # FIX 2: Removed the 'end' parameter. yfinance will automatically fetch up to the current minute.
    raw = ticker_obj.history(
        start       = start_date.strftime("%Y-%m-%d"),
        interval    = interval,
        auto_adjust = True,
    )

    if raw.empty:
        raise ValueError(
            f"No data returned for ticker '{ticker}'. "
            "Check symbol, date limits, or if Yahoo Finance is blocking your IP."
        )

    df = _clean(raw, ticker)
    logger.info("Fetched %d rows for %s", len(df), ticker)
    return df


def _clean(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalise columns, drop NaNs, make index tz-naive."""

    # Flatten MultiIndex if present (yfinance does this in newer versions)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Standardize column names (Capitalize the first letter just in case)
    df.columns = df.columns.str.capitalize()

    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df   = df[keep].copy()

    # Strip timezone safely
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = "Date"

    df.dropna(subset=["Close"], inplace=True)
    df.sort_index(inplace=True)
    return df


def latest_price(ticker: str) -> dict:
    # Use 10 days to ensure we get at least 2 trading days (avoids weekend/holiday gaps)
    df = fetch_ohlcv(ticker, period_days=10, interval="1d")

    price      = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else price
    change_pct = round((price - prev_close) / prev_close * 100, 2)

    return {
        "ticker"     : ticker.upper(),
        "price"      : round(price, 2),
        "prev_close" : round(prev_close, 2),
        "change_pct" : change_pct,
        "as_of"      : str(df.index[-1].date()),
    }




def to_records(df: pd.DataFrame) -> list[dict]:
    df = df.reset_index()
    df["Date"] = df["Date"].astype(str)
    df.columns = [c.lower() for c in df.columns]
    
    # THE FIX: Clean out any NaNs created by technical indicators
    df = df.replace(np.nan, None)
    
    return df.to_dict(orient="records")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ticker = "GOOG"
    print(latest_price(ticker))
    
    # Test intraday fetching
    df_intraday = fetch_ohlcv(ticker, period_days=30, interval="15m")
    print("\nIntraday Data Tail:")
    print(df_intraday.tail())