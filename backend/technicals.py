"""
technicals.py
=============
RSI, MACD, Bollinger Bands
"""

import pandas as pd
import numpy as np
import logging


logger = logging.getLogger(__name__)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    rsi_val  = 100 - (100 / (1 + rs))
    rsi_val.name = f"RSI_{period}"
    return rsi_val


def macd(
    close: pd.Series,
    fast: int = 12, slow: int = 26, signal: int = 9,
) -> pd.DataFrame:
    ema_fast    = close.ewm(span=fast,   adjust=False).mean()
    ema_slow    = close.ewm(span=slow,   adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return pd.DataFrame({
        "MACD"        : macd_line,
        "MACD_Signal" : signal_line,
        "MACD_Hist"   : histogram,
    }, index=close.index)


def bollinger_bands(
    close: pd.Series,
    period: int = 20, num_std: float = 2.0,
) -> pd.DataFrame:
    sma   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    width = (upper - lower) / sma
    return pd.DataFrame({
        "BB_Mid"  : sma,
        "BB_Upper": upper,
        "BB_Lower": lower,
        "BB_Width": width,
    }, index=close.index)


def sma(close: pd.Series, period: int) -> pd.Series:
    s = close.rolling(period).mean()
    s.name = f"SMA_{period}"
    return s


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df    = df.copy()
    close = df["Close"]

    df["RSI"] = rsi(close)

    macd_df = macd(close)
    df = pd.concat([df, macd_df], axis=1)

    bb_df = bollinger_bands(close)
    df = pd.concat([df, bb_df], axis=1)

    # SMAs for chart overlay
    df["SMA_7"]  = sma(close, 7)
    df["SMA_21"] = sma(close, 21)
    df["SMA_50"] = sma(close, 50)

    logger.info("Indicators added: RSI, MACD, BB, SMA 7/21/50")
    return df


def latest_indicator_snapshot(df: pd.DataFrame) -> dict:
    enriched = add_all_indicators(df)
    last     = enriched.iloc[-1]

    def _f(col: str):
        val = last.get(col)
        if val is None:
            return None
        try:
            f = float(val)
            return round(f, 4) if not np.isnan(f) else None
        except (TypeError, ValueError):
            return None

    return {
        "rsi"         : _f("RSI"),
        "macd"        : _f("MACD"),
        "macd_signal" : _f("MACD_Signal"),
        "macd_hist"   : _f("MACD_Hist"),
        "bb_upper"    : _f("BB_Upper"),
        "bb_lower"    : _f("BB_Lower"),
        "bb_mid"      : _f("BB_Mid"),
        "bb_width"    : _f("BB_Width"),
        "sma_7"       : _f("SMA_7"),
        "sma_21"      : _f("SMA_21"),
        "sma_50"      : _f("SMA_50"),
    }


def rsi_signal(rsi_value) -> str:
    if rsi_value is None:
        return "Unknown"
    if rsi_value >= 70:
        return "Overbought 🔴"
    if rsi_value <= 30:
        return "Oversold 🟢"
    return "Neutral ⚪"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from market_data import fetch_ohlcv
    df = fetch_ohlcv("GOOG", period_days=90)
    enriched = add_all_indicators(df)
    print(enriched[["Close", "RSI", "MACD", "BB_Upper", "SMA_50"]].tail(5))