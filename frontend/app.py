"""
app.py  –  Enhanced Streamlit Dashboard
Inspired by dark-theme AI Sentiment × Price Intelligence UI
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── Page config (MUST be first) ───────────────────────────────────────────────
st.set_page_config(
    page_title = "StockPulse · AI Dashboard",
    page_icon  = "📈",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# ── Dark theme CSS ────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Global dark background ── */
html, body, [data-testid="stAppViewContainer"],
[data-testid="stMain"], .main {
    background-color: #0d1117 !important;
    color: #e6edf3 !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #161b22 !important;
    border-right: 1px solid #30363d;
}

/* ── Metric cards ── */
[data-testid="metric-container"] {
    background    : #161b22;
    border        : 1px solid #30363d;
    border-radius : 12px;
    padding       : 20px 24px;
    transition    : border-color 0.2s;
}
[data-testid="metric-container"]:hover {
    border-color: #58a6ff;
}
[data-testid="stMetricLabel"] {
    color       : #8b949e !important;
    font-size   : 0.78rem !important;
    font-weight : 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    color       : #e6edf3 !important;
    font-size   : 2rem !important;
    font-weight : 700 !important;
}
[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }

/* ── Selectbox / text input ── */
[data-testid="stSelectbox"] > div,
[data-testid="stTextInput"] > div > div {
    background-color: #21262d !important;
    border          : 1px solid #30363d !important;
    border-radius   : 8px !important;
    color           : #e6edf3 !important;
}

/* ── Buttons ── */
.stButton > button {
    background    : #1f6feb;
    color         : #fff;
    border        : none;
    border-radius : 6px;
    font-weight   : 600;
    padding       : 6px 18px;
}
.stButton > button:hover { background: #388bfd; }

/* ── Tabs ── */
[data-testid="stTabs"] button {
    color           : #8b949e;
    border-bottom   : 2px solid transparent;
    font-weight     : 600;
    border-radius   : 0;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color        : #58a6ff;
    border-bottom: 2px solid #58a6ff;
}

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    background-color: #161b22 !important;
    border-radius   : 8px;
}

/* ── Divider ── */
hr { border-color: #30363d !important; }

/* ── Section header ── */
.section-header {
    font-size   : 1.1rem;
    font-weight : 700;
    color       : #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 12px;
}

/* ── Signal badge ── */
.badge {
    display       : inline-block;
    padding       : 3px 12px;
    border-radius : 20px;
    font-size     : 0.78rem;
    font-weight   : 700;
}
.badge-buy    { background:#1a4731; color:#3fb950; border:1px solid #3fb950; }
.badge-sell   { background:#4a1a1a; color:#f85149; border:1px solid #f85149; }
.badge-hold   { background:#2d2a1a; color:#e3b341; border:1px solid #e3b341; }
.badge-neutral{ background:#21262d; color:#8b949e; border:1px solid #30363d; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000"

# Popular tickers with company names for autocomplete
POPULAR_TICKERS = {
    "AAPL"  : "Apple Inc.",
    "GOOG"  : "Alphabet (Google)",
    "GOOGL" : "Alphabet Class A",
    "MSFT"  : "Microsoft",
    "AMZN"  : "Amazon",
    "TSLA"  : "Tesla",
    "META"  : "Meta Platforms",
    "NVDA"  : "NVIDIA",
    "AMD"   : "AMD",
    "NFLX"  : "Netflix",
    "SPY"   : "S&P 500 ETF",
    "QQQ"   : "NASDAQ-100 ETF",
    "BRK-B" : "Berkshire Hathaway",
    "JPM"   : "JPMorgan Chase",
    "BAC"   : "Bank of America",
    "GS"    : "Goldman Sachs",
    "V"     : "Visa",
    "MA"    : "Mastercard",
    "DIS"   : "Walt Disney",
    "BABA"  : "Alibaba",
    "TSM"   : "TSMC",
    "INTC"  : "Intel",
    "CRM"   : "Salesforce",
    "UBER"  : "Uber",
    "COIN"  : "Coinbase",
    "PLTR"  : "Palantir",
    "SQ"    : "Block (Square)",
    "SHOP"  : "Shopify",
    "NET"   : "Cloudflare",
    "SNOW"  : "Snowflake",
}

PERIOD_OPTIONS = {
    "1 Month"  : 30,
    "3 Months" : 90,
    "6 Months" : 180,
    "1 Year"   : 365,
}

CHART_TYPES  = ["Candle", "Area", "Line"]
INTERVAL_MAP = {"1d": "Daily", "1h": "Hourly"}


# ── API helpers ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_sentiment(ticker: str) -> dict:
    """Fetches FinBERT sentiment analysis for the given ticker."""
    try:
        # Increased timeout because FinBERT takes a few seconds to run
        r = requests.get(
            f"{API_BASE}/api/sentiment",
            params={"ticker": ticker},
            timeout=30, 
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}
@st.cache_data(ttl=60)
def get_kpis(ticker: str) -> dict:
    try:
        r = requests.get(
            f"{API_BASE}/api/kpis",
            params={"ticker": ticker}, timeout=12,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=60)
def get_price_history(ticker: str, period_days: int, interval: str) -> list[dict]:
    try:
        r = requests.get(
            f"{API_BASE}/api/price-history",
            params={
                "ticker"      : ticker,
                "period_days" : period_days,
                "interval"    : interval,
                "indicators"  : True,
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("records", [])
    except Exception as e:
        st.error(f"❌ Price history error: {e}")
        return []


@st.cache_data(ttl=300)
def get_polymarket(ticker: str = "SPY") -> dict:
    """
    Now ticker-aware — each stock gets its own Polymarket data.
    """
    try:
        r = requests.get(
            f"{API_BASE}/api/polymarket",
            params={"ticker": ticker},  # ← FIXED: pass ticker
            timeout=12,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Polymarket fetch error: %s", e)
        return {}


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📈 StockPulse")
    st.markdown("---")

    # ── Ticker search with autocomplete ──────────────────────────────────────
    st.markdown("#### 🔍 Search Stock")

    search_input = st.text_input(
        "Type ticker or company name",
        value="",
        placeholder="e.g. AAPL, Tesla, NVDA…",
        label_visibility="collapsed",
    ).strip().upper()

    # Filter matching tickers
    if search_input:
        matches = {
            k: v for k, v in POPULAR_TICKERS.items()
            if search_input in k.upper() or search_input in v.upper()
        }
    else:
        matches = POPULAR_TICKERS

    # Format options as "AAPL – Apple Inc."
    options_list = [f"{k} – {v}" for k, v in matches.items()]

    if not options_list:
        st.warning("No match found. Type a valid ticker below.")
        options_list = [f"{search_input} – Custom"]

    selected_option = st.selectbox(
        "Select ticker",
        options_list,
        label_visibility="collapsed",
    )

    # Extract just the ticker symbol
    ticker = selected_option.split(" – ")[0].strip()
    company = selected_option.split(" – ")[1].strip() if " – " in selected_option else ""

    st.markdown("---")

    # ── Chart settings ────────────────────────────────────────────────────────
    st.markdown("#### ⚙️ Chart Settings")

    period_label = st.selectbox("Time Period", list(PERIOD_OPTIONS.keys()), index=2)
    period_days  = PERIOD_OPTIONS[period_label]

    interval = st.selectbox("Bar Interval", list(INTERVAL_MAP.keys()),
                            format_func=lambda x: INTERVAL_MAP[x])

    chart_type = st.radio("Chart Type", CHART_TYPES, horizontal=True)

    st.markdown("---")

    # ── Indicator toggles ─────────────────────────────────────────────────────
    st.markdown("#### 📊 Overlays")
    show_bb    = st.checkbox("Bollinger Bands", value=True)
    show_sma7  = st.checkbox("SMA 7",           value=True)
    show_sma21 = st.checkbox("SMA 21",          value=True)
    show_sma50 = st.checkbox("SMA 50",          value=True)
    show_vol   = st.checkbox("Volume",          value=True)

    st.markdown("---")
    st.caption("Data: Yahoo Finance + Polymarket")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# ── Page header ───────────────────────────────────────────────────────────────
col_title, col_tag = st.columns([3, 1])
with col_title:
    st.markdown(f"## 📈 {ticker} — {company}")
    st.caption(f"AI Sentiment × Price Intelligence · {period_label} · {INTERVAL_MAP[interval]}")


# ════════════════════════════════════════════════════════════════════════════
# KPI CARDS
# ════════════════════════════════════════════════════════════════════════════
kpis = get_kpis(ticker)

k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    price      = kpis.get("price", 0)
    change_pct = kpis.get("change_pct", 0)
    direction  = "▲" if change_pct >= 0 else "▼"
    st.metric(
        label = f"Price ({ticker})",
        value = f"${price:,.2f}" if price else "—",
        delta = f"{direction} {abs(change_pct):.2f}% today",
    )

with k2:
    rsi_val = kpis.get("rsi")
    rsi_sig = kpis.get("rsi_signal", "—")
    st.metric(
        label = "RSI (14)",
        value = f"{rsi_val:.1f}" if rsi_val else "—",
        delta = rsi_sig,
        delta_color="off",
    )

with k3:
    macd_val = kpis.get("macd")
    macd_sig = kpis.get("macd_signal")
    macd_label = "↑ Bullish" if macd_val and macd_val > 0 else "↓ Bearish"
    st.metric(
        label = "MACD",
        value = f"{macd_val:.4f}" if macd_val is not None else "—",
        delta = macd_label,
        delta_color="normal" if macd_val and macd_val > 0 else "inverse",
    )

# ── FIXED: KPI Card k4 — Polymarket Score ────────────────────────────────────
# ── FIXED KPI Card k4 ─────────────────────────────────────────────────────────
with k4:
    poly_score = kpis.get("polymarket_score")
    poly_label = kpis.get("polymarket_label", "—")

    # Score of exactly 0 = backend returned no data, not truly 0%
    score_valid = poly_score is not None and poly_score != 0

    st.metric(
        label       = "Polymarket Score",
        value       = f"{poly_score:.0%}" if score_valid else "—",
        delta       = poly_label if score_valid else "No data",
        delta_color = "off",
    )

with k5:
    # Blended signal: combine RSI + MACD direction + Polymarket
    signal_score = 0
    signal_parts = 0
    if rsi_val:
        signal_score += (rsi_val - 50) / 50   # -1 to +1
        signal_parts += 1
    if macd_val is not None and kpis.get("bb_upper"):
        signal_score += 1 if macd_val > 0 else -1
        signal_parts += 1
    if poly_score is not None:
        signal_score += (poly_score - 0.5) * 2
        signal_parts += 1
    blended = signal_score / signal_parts if signal_parts else 0

    if blended > 0.3:
        sig_label, sig_color = "BUY",  "normal"
    elif blended < -0.3:
        sig_label, sig_color = "SELL", "inverse"
    else:
        sig_label, sig_color = "HOLD", "off"

    st.metric(
        label = "Signal",
        value = sig_label,
        delta = f"Score: {blended:+.2f}",
        delta_color=sig_color,
    )

st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
# MAIN CHART  (Candlestick / Area / Line + Indicators + Volume + RSI + MACD)
# ════════════════════════════════════════════════════════════════════════════
st.markdown(f"### {ticker} — Price Chart")

records = get_price_history(ticker, period_days, interval)

if records:
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])

    # ── Decide row layout ─────────────────────────────────────────────────
    # Row 1 = Price, Row 2 = Volume (optional), Row 3 = MACD, Row 4 = RSI
    rows        = [0.52, 0.16, 0.18, 0.14] if show_vol else [0.58, 0.22, 0.20]
    n_rows      = len(rows)
    vol_row     = 2 if show_vol else None
    macd_row    = 3 if show_vol else 2
    rsi_row     = 4 if show_vol else 3

    subplot_titles = [f"{ticker} Price"]
    if show_vol:   subplot_titles.append("Volume")
    subplot_titles += ["MACD", "RSI (14)"]

    fig = make_subplots(
        rows             = n_rows,
        cols             = 1,
        shared_xaxes     = True,
        row_heights      = rows,
        vertical_spacing = 0.03,
        subplot_titles   = subplot_titles,
    )

    # ── Row 1 – Price ─────────────────────────────────────────────────────
    if chart_type == "Candle":
        fig.add_trace(go.Candlestick(
            x           = df["date"],
            open        = df["open"],
            high        = df["high"],
            low         = df["low"],
            close       = df["close"],
            name        = "OHLC",
            increasing  = dict(line=dict(color="#3fb950"), fillcolor="#1a4731"),
            decreasing  = dict(line=dict(color="#f85149"), fillcolor="#4a1a1a"),
        ), row=1, col=1)

    elif chart_type == "Area":
        fig.add_trace(go.Scatter(
            x    = df["date"],
            y    = df["close"],
            name = "Price",
            mode = "lines",
            line = dict(color="#58a6ff", width=2),
            fill = "tozeroy",
            fillcolor = "rgba(88,166,255,0.08)",
        ), row=1, col=1)

    else:  # Line
        fig.add_trace(go.Scatter(
            x    = df["date"],
            y    = df["close"],
            name = "Price",
            mode = "lines",
            line = dict(color="#58a6ff", width=2),
        ), row=1, col=1)

    # ── Overlays: Bollinger Bands ─────────────────────────────────────────
    if show_bb and "bb_upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["bb_upper"],
            name="BB Upper",
            line=dict(color="rgba(139,148,158,0.5)", dash="dot", width=1),
            showlegend=True,
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x         = df["date"],
            y         = df["bb_lower"],
            name      = "BB Lower",
            line      = dict(color="rgba(139,148,158,0.5)", dash="dot", width=1),
            fill      = "tonexty",
            fillcolor = "rgba(139,148,158,0.07)",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df["date"], y=df["bb_mid"],
            name="BB Mid",
            line=dict(color="rgba(139,148,158,0.4)", width=1),
        ), row=1, col=1)

    # ── Overlays: SMAs ────────────────────────────────────────────────────
    sma_config = [
        ("sma_7",  show_sma7,  "#e3b341", "SMA 7"),
        ("sma_21", show_sma21, "#f0883e", "SMA 21"),
        ("sma_50", show_sma50, "#a371f7", "SMA 50"),
    ]
    for col_name, show, color, label in sma_config:
        if show and col_name in df.columns:
            fig.add_trace(go.Scatter(
                x    = df["date"],
                y    = df[col_name],
                name = label,
                line = dict(color=color, width=1.5, dash="dot"),
            ), row=1, col=1)

    # ── Row 2 – Volume ────────────────────────────────────────────────────
    if show_vol and "volume" in df.columns:
        colors_vol = [
            "#3fb950" if c >= o else "#f85149"
            for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(go.Bar(
            x             = df["date"],
            y             = df["volume"],
            name          = "Volume",
            marker_color  = colors_vol,
            showlegend    = False,
        ), row=vol_row, col=1)

    # ── MACD ──────────────────────────────────────────────────────────────
    if "macd" in df.columns:
        hist_colors = [
            "#3fb950" if v >= 0 else "#f85149"
            for v in df.get("macd_hist", pd.Series(dtype=float)).fillna(0)
        ]
        fig.add_trace(go.Bar(
            x            = df["date"],
            y            = df.get("macd_hist", pd.Series(dtype=float)),
            name         = "Histogram",
            marker_color = hist_colors,
            showlegend   = False,
        ), row=macd_row, col=1)

        fig.add_trace(go.Scatter(
            x=df["date"], y=df["macd"],
            name="MACD", line=dict(color="#58a6ff", width=1.5),
        ), row=macd_row, col=1)

        fig.add_trace(go.Scatter(
            x=df["date"], y=df.get("macd_signal", pd.Series(dtype=float)),
            name="Signal", line=dict(color="#f0883e", width=1.5),
        ), row=macd_row, col=1)

    # ── RSI ───────────────────────────────────────────────────────────────
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(
            x    = df["date"],
            y    = df["rsi"],
            name = "RSI",
            line = dict(color="#a371f7", width=1.5),
        ), row=rsi_row, col=1)

        # Zones
        fig.add_hrect(
            y0=70, y1=100,
            fillcolor="rgba(248,81,73,0.08)",
            line_width=0,
            row=rsi_row, col=1,
        )
        fig.add_hrect(
            y0=0, y1=30,
            fillcolor="rgba(63,185,80,0.08)",
            line_width=0,
            row=rsi_row, col=1,
        )
        fig.add_hline(
            y=70, line_color="rgba(248,81,73,0.5)",
            line_dash="dot", row=rsi_row, col=1,
        )
        fig.add_hline(
            y=30, line_color="rgba(63,185,80,0.5)",
            line_dash="dot", row=rsi_row, col=1,
        )

    # ── Layout ────────────────────────────────────────────────────────────
    fig.update_layout(
        height    = 820,
        paper_bgcolor = "#0d1117",
        plot_bgcolor  = "#0d1117",
        font      = dict(color="#8b949e", size=12),
        xaxis_rangeslider_visible = False,
        legend    = dict(
            orientation = "h",
            yanchor     = "bottom",
            y           = 1.01,
            xanchor     = "left",
            x           = 0,
            bgcolor     = "rgba(0,0,0,0)",
            font        = dict(color="#8b949e"),
        ),
        margin    = dict(l=0, r=0, t=60, b=0),
        hovermode = "x unified",
    )

    # Style all axes dark
    axis_style = dict(
        gridcolor   = "#21262d",
        zerolinecolor = "#30363d",
        tickfont    = dict(color="#8b949e"),
    )
    for i in range(1, n_rows + 1):
        fig.update_xaxes(axis_style, row=i, col=1)
        fig.update_yaxes(axis_style, row=i, col=1)

    # Subplot title styling
    for ann in fig.layout.annotations:
        ann.font = dict(color="#8b949e", size=11)
        ann.x    = 0

    st.plotly_chart(fig, use_container_width=True)

    # ── Last row data preview ─────────────────────────────────────────────
    with st.expander("🔍 Raw Data (last 10 rows)"):
        show_cols = ["date","open","high","low","close","volume","rsi","macd","bb_upper","bb_lower"]
        show_cols = [c for c in show_cols if c in df.columns]
        st.dataframe(
            df[show_cols].tail(10).set_index("date"),
            use_container_width=True,
        )

else:
    st.warning("⚠️ No price data. Check backend is running at localhost:8000")


# ── FIXED Polymarket Section ──────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🎲 Polymarket — Prediction Market Odds")

# Pass current ticker so data is stock-specific
poly_data = get_polymarket(ticker=ticker)

if not poly_data:
    st.warning("⚠️ Backend `/api/polymarket` returned empty.")
elif not poly_data.get("markets"):
    st.info(
        f"ℹ️ No Polymarket prediction markets found for **{ticker}** yet. "
        f"Showing general market sentiment instead."
    )

if poly_data:
    score  = poly_data.get("score", 0.5)
    label  = poly_data.get("label", "Neutral")
    source = poly_data.get("source", "")
    mkts   = poly_data.get("markets", [])

    col_score, col_markets = st.columns([1, 3])

    with col_score:
        color = (
            "#3fb950" if score >= 0.55
            else "#f85149" if score <= 0.45
            else "#e3b341"
        )
        source_text = "🟢 Live Data" if source == "live" else "🟡 Fallback"

        st.markdown(f"""
        <div style='background:#161b22;border:1px solid #30363d;
                    border-radius:12px;padding:24px;text-align:center;'>
            <div style='font-size:0.75rem;color:#8b949e;
                        text-transform:uppercase;letter-spacing:0.08em;'>
                {ticker} Market Sentiment
            </div>
            <div style='font-size:2.8rem;font-weight:700;
                        color:{color};margin:8px 0;'>
                {score:.0%}
            </div>
            <div style='font-size:0.95rem;color:{color};font-weight:600;'>
                {label}
            </div>
            <div style='font-size:0.72rem;color:#8b949e;margin-top:10px;'>
                {source_text}
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_markets:
        if mkts:
            mdf = pd.DataFrame(mkts)

            mdf["yes_prob"] = mdf["yes_prob"].apply(
                lambda x: f"{x:.0%}" if (x is not None and x != 0) else "—"
            )
            mdf["volume_usd"] = mdf["volume_usd"].apply(
                lambda x: f"${x:,.0f}" if x else "$0"
            )

            available_cols = {
                "question"  : "Market Question",
                "yes_prob"  : "YES %",
                "volume_usd": "Volume (USD)",
                "end_date"  : "Ends",
            }
            cols_to_show = [
                c for c in available_cols if c in mdf.columns
            ]

            st.dataframe(
                mdf[cols_to_show].rename(columns=available_cols),
                use_container_width=True,
                hide_index=True,
            )

            fetched = poly_data.get("fetched_at", "")
            if fetched:
                st.caption(f"⏱ Last fetched: {fetched} UTC")
        else:
            st.info(
                f"No specific prediction markets found for {ticker}. "
                "This is normal — Polymarket has limited individual stock markets."
            )
# ════════════════════════════════════════════════════════════════════════════
# PERSON 2 PLACEHOLDER
# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# NEWS & AI SENTIMENT (FinBERT)
# ════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown("### 📰 AI News Sentiment (FinBERT)")

with st.spinner(f"Analyzing latest news for {ticker} using FinBERT..."):
    sentiment_data = get_sentiment(ticker)

if "error" in sentiment_data:
    st.error(f"⚠️ Failed to load sentiment data: {sentiment_data['error']}")
elif not sentiment_data.get("articles"):
    st.info(f"ℹ️ No recent news articles found to analyze for {ticker}.")
else:
    summary = sentiment_data["summary"]
    articles = sentiment_data["articles"]

    col_sent_score, col_sent_news = st.columns([1, 2.5])

    # ── Left Column: Sentiment Score ──────────────────────────────────────────
    with col_sent_score:
        signal = summary.get("signal", "NEUTRAL")
        score = summary.get("score", 0.0)
        conf = summary.get("confidence", 0.0)
        reason = summary.get("reason", "")

        # Color mapping based on signal
        if "BUY" in signal:
            sig_color = "#3fb950"
        elif "SELL" in signal:
            sig_color = "#f85149"
        else:
            sig_color = "#e3b341"

        st.markdown(f"""
        <div style='background:#161b22;border:1px solid #30363d;
                    border-radius:12px;padding:24px;text-align:center;'>
            <div style='font-size:0.75rem;color:#8b949e;
                        text-transform:uppercase;letter-spacing:0.08em;'>
                AI Market Signal
            </div>
            <div style='font-size:2.4rem;font-weight:700;
                        color:{sig_color};margin:8px 0;'>
                {signal}
            </div>
            <div style='font-size:0.95rem;color:#e6edf3;font-weight:600;margin-bottom:8px;'>
                Score: {score:+.2f}
            </div>
            <div style='font-size:0.8rem;color:#8b949e;margin-bottom:4px;'>
                Confidence: {conf:.0%}
            </div>
            <div style='font-size:0.75rem;color:#58a6ff;font-style:italic;'>
                "{reason}"
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Right Column: News Feed ───────────────────────────────────────────────
    with col_sent_news:
        st.markdown("<div class='section-header'>Latest Analyzed Headlines</div>", unsafe_allow_html=True)
        
        # Build a visual feed instead of a standard dataframe
        feed_html = "<div style='display:flex; flex-direction:column; gap:12px;'>"
        
        for art in articles:
            title = art.get("title", "")
            sent = art.get("sentiment", "neutral").upper()
            art_score = art.get("score", 0.0)
            
            # Match sentiment to your CSS badges
            if sent == "POSITIVE":
                badge_class = "badge-buy"
            elif sent == "NEGATIVE":
                badge_class = "badge-sell"
            else:
                badge_class = "badge-neutral"
                
            feed_html += f"""
            <div style='background:#21262d; border:1px solid #30363d; border-radius:8px; padding:12px 16px;'>
                <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
                    <span class='badge {badge_class}'>{sent} ({art_score:+.2f})</span>
                </div>
                <div style='font-size:0.95rem; color:#e6edf3; font-weight:500;'>
                    {title}
                </div>
            </div>
            """
            
        feed_html += "</div>"
        st.markdown(feed_html, unsafe_allow_html=True)