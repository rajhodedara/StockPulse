# Feelow Implementation Snippets

Below is the code-faithful breakdown from the Feelow codebase.

---

Feature: Yahoo Finance price fetching  
Library Used: `yfinance`, `pandas`  
Code Snippet:
```python
raw = ticker_obj.history(
    start       = start_date.strftime("%Y-%m-%d"),
    interval    = interval,
    auto_adjust = True,
)
```
```python
price      = float(df["Close"].iloc[-1])
prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else price
change_pct = round((price - prev_close) / prev_close * 100, 2)
```
File: [backend/data/market_data.py](D:\Python-Project\StockPulse-main\backend\data\market_data.py)  
Internal Logic:
- Creates `yf.Ticker(ticker.upper())`
- Fetches OHLCV history from Yahoo Finance
- Cleans columns to `Open, High, Low, Close, Volume`
- Uses latest `Close` as current price
- Uses previous `Close` to compute daily % move  
Actual Formula:
- `price = latest close`
- `prev_close = previous close`
- `change_pct = ((price - prev_close) / prev_close) * 100`  
Presentation Explanation:
- “We use Yahoo Finance through `yfinance` to fetch historical OHLCV candles, then derive current price and daily percentage movement from the most recent closing values.”

---

Feature: RSI calculation  
Library Used: `pandas`, `numpy`  
Code Snippet:
```python
delta    = close.diff()
gain     = delta.clip(lower=0)
loss     = (-delta).clip(lower=0)
avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
rs       = avg_gain / avg_loss.replace(0, np.nan)
rsi_val  = 100 - (100 / (1 + rs))
```
File: [backend/data/technical.py](D:\Python-Project\StockPulse-main\backend\data\technical.py)  
Internal Logic:
- No `pandas_ta` or `ta-lib` is used
- RSI is implemented manually with pandas
- Splits candle-to-candle change into gains and losses
- Smooths both with exponential weighting
- Converts relative strength into RSI on a 0 to 100 scale  
Actual Formula:
- `delta = close_t - close_(t-1)`
- `gain = max(delta, 0)`
- `loss = max(-delta, 0)`
- `RS = avg_gain / avg_loss`
- `RSI = 100 - 100 / (1 + RS)`  
Presentation Explanation:
- “RSI measures whether recent upward moves are stronger than recent downward moves. In our code, we calculate it directly using pandas instead of using a technical-analysis library.”

---

Feature: MACD calculation  
Library Used: `pandas`  
Code Snippet:
```python
ema_fast    = close.ewm(span=fast,   adjust=False).mean()
ema_slow    = close.ewm(span=slow,   adjust=False).mean()
macd_line   = ema_fast - ema_slow
signal_line = macd_line.ewm(span=signal, adjust=False).mean()
histogram   = macd_line - signal_line
```
File: [backend/data/technical.py](D:\Python-Project\StockPulse-main\backend\data\technical.py)  
Internal Logic:
- Computes 12-period EMA and 26-period EMA
- MACD line is the difference between them
- Signal line is 9-period EMA of MACD
- Histogram is MACD minus signal  
Actual Formula:
- `EMA_fast = EMA(close, 12)`
- `EMA_slow = EMA(close, 26)`
- `MACD = EMA_fast - EMA_slow`
- `Signal = EMA(MACD, 9)`
- `Histogram = MACD - Signal`  
Presentation Explanation:
- “MACD compares short-term EMA and long-term EMA. If the short-term EMA pulls away upward, momentum is bullish; if it drops below, momentum is bearish.”

---

Feature: Bollinger Bands calculation  
Library Used: `pandas`  
Code Snippet:
```python
sma   = close.rolling(period).mean()
std   = close.rolling(period).std()
upper = sma + num_std * std
lower = sma - num_std * std
width = (upper - lower) / sma
```
File: [backend/data/technical.py](D:\Python-Project\StockPulse-main\backend\data\technical.py)  
Internal Logic:
- Takes 20-period rolling mean
- Takes 20-period rolling standard deviation
- Builds upper/lower bands using `2 * std`
- Also computes normalized band width  
Actual Formula:
- `BB_Mid = SMA(close, 20)`
- `BB_Upper = BB_Mid + 2 * std`
- `BB_Lower = BB_Mid - 2 * std`
- `BB_Width = (BB_Upper - BB_Lower) / BB_Mid`  
Presentation Explanation:
- “Bollinger Bands show where price sits relative to its recent average and volatility range. Wider bands mean higher volatility.”

---

Feature: SMA moving averages  
Library Used: `pandas`  
Code Snippet:
```python
def sma(close: pd.Series, period: int) -> pd.Series:
    s = close.rolling(period).mean()
    s.name = f"SMA_{period}"
    return s
```
```python
df["SMA_7"]  = sma(close, 7)
df["SMA_21"] = sma(close, 21)
df["SMA_50"] = sma(close, 50)
```
File: [backend/data/technical.py](D:\Python-Project\StockPulse-main\backend\data\technical.py)  
Internal Logic:
- Uses rolling mean on close prices
- Creates short, medium, and longer moving averages  
Actual Formula:
- `SMA_n = sum(last n closes) / n`  
Presentation Explanation:
- “SMA smooths price noise. We use 7, 21, and 50 periods to visualize short-, medium-, and longer-term trend.”

---

Feature: Trend scoring logic  
Library Used: Pure Python  
Code Snippet:
```python
if price_value >= sma_21:
    bullish += 1
else:
    bearish += 1

if price_value >= sma_50:
    bullish += 1
else:
    bearish += 1

if sma_21 >= sma_50:
    bullish += 1
else:
    bearish += 1

return round(bullish / total, 4)
```
File: [backend/models/scoring_engine.py](D:\Python-Project\StockPulse-main\backend\models\scoring_engine.py)  
Internal Logic:
- Gives 1 bullish point for:
  - price above SMA 21
  - price above SMA 50
  - SMA 21 above SMA 50
- Final trend score is bullish checks divided by total checks  
Actual Formula:
- `trend_score = bullish_checks / 3`  
Presentation Explanation:
- “Trend is rule-based. If price is above key moving averages and the shorter average is above the longer one, the trend score becomes more bullish.”

---

Feature: Polymarket scoring  
Library Used: `requests`, `math`, optional `google.genai`  
Code Snippet:
```python
if mtype == "above":    return round(yes_prob, 4)
if mtype == "below":    return round(1.0 - yes_prob, 4)
if mtype == "hit_high": return round(yes_prob, 4)
if mtype == "hit_low":  return round(1.0 - yes_prob, 4)
if mtype == "reach":    return round(yes_prob, 4)
```
```python
raw_w = [math.log1p(r["volume_usd"] + 1.0) for r in valid]
cap   = 0.30 * total
raw_w = [min(w, cap) for w in raw_w]
score = sum(r["sentiment"] * w for r, w in zip(valid, raw_w)) / total
```
File: [backend/data/polymarket.py](D:\Python-Project\StockPulse-main\backend\data\polymarket.py)  
Internal Logic:
- Searches active Polymarket events
- Extracts YES probability
- Converts market wording into bullish sentiment
- Weights each event by `log1p(volume)`
- Caps any single event’s influence at 30%  
Actual Formula:
- sentiment conversion:
  - `above -> yes_prob`
  - `below -> 1 - yes_prob`
  - `hit_low -> 1 - yes_prob`
- weighted score:
  - `w_i = log(1 + volume_i + 1)`
  - `score = sum(sentiment_i * w_i) / sum(w_i)`  
Presentation Explanation:
- “We turn Polymarket contract probabilities into stock-direction sentiment, then combine them using liquidity-aware volume weighting so large but not dominant markets matter more.”

---

Feature: FinBERT sentiment analysis  
Library Used: `transformers`  
Code Snippet:
```python
classifier = pipeline("sentiment-analysis", model="ProsusAI/finbert")
```
```python
result = classifier(text)[0]

if label == 'positive':
    final_score = score
elif label == 'negative':
    final_score = -score
else:
    final_score = 0
```
File: [backend/models/sentiment_engine.py](D:\Python-Project\StockPulse-main\backend\models\sentiment_engine.py)  
Internal Logic:
- Loads FinBERT once as a Hugging Face pipeline
- Runs each headline/post through it
- Converts positive labels to `+score`, negative to `-score`, neutral to `0`
- Then applies custom finance heuristics  
Actual Formula:
- `positive -> +p`
- `negative -> -p`
- `neutral -> 0`  
Presentation Explanation:
- “We use FinBERT because it is trained for finance language. Then we convert its classification output into a signed sentiment score.”

---

Feature: News confidence calculation  
Library Used: Pure Python  
Code Snippet:
```python
strong = sum(1 for r in results if abs(r["score"]) > 0.6)
return round(strong / len(results), 2)
```
File: [backend/models/sentiment_engine.py](D:\Python-Project\StockPulse-main\backend\models\sentiment_engine.py)  
Internal Logic:
- Counts how many articles have strong sentiment magnitude
- Divides by total article count  
Actual Formula:
- `news_confidence = strong_article_count / total_articles`
- where strong means `|score| > 0.6`  
Presentation Explanation:
- “If many articles are strongly positive or strongly negative, our confidence in the news signal goes up.”

---

Feature: Public opinion sentiment calculation  
Library Used: `requests`, `bs4`, `transformers`, `math`  
Code Snippet:
```python
reddit_items = fetch_reddit_posts(symbol, company_name, limit=limit_per_source)
stocktwits_items = fetch_stocktwits_posts(symbol, limit=limit_per_source)
return reddit_items + stocktwits_items
```
```python
score = round(get_average_score(analyzed_posts), 4)
signal = _public_signal(score)
```
```python
ranked_discussions = sorted(
    analyzed_posts,
    key=lambda post: (
        abs(post.get("score", 0.0)),
        post.get("engagement") or 0,
    ),
    reverse=True,
)
```
File:  
- ingestion: [backend/data/social_ingestor.py](D:\Python-Project\StockPulse-main\backend\data\social_ingestor.py)  
- scoring: [backend/models/public_opinion_engine.py](D:\Python-Project\StockPulse-main\backend\models\public_opinion_engine.py)  
Internal Logic:
- Scrapes Reddit search results
- Calls StockTwits symbol API
- Cleans text, removes spam-like content, deduplicates
- Reuses FinBERT scoring pipeline
- Averages meaningful scores
- Ranks top discussions by score strength and engagement  
Actual Formula:
- `public_sentiment_score = average(scores where |score| >= 0.2)`
- signal thresholds:
  - `> 0.25 -> BULLISH`
  - `< -0.25 -> BEARISH`
  - else `NEUTRAL`  
Presentation Explanation:
- “We treat Reddit and StockTwits as retail/public mood inputs, score them with FinBERT, then aggregate them into a separate social sentiment signal.”

---

Feature: Final AI signal fusion  
Library Used: Pure Python  
Code Snippet:
```python
weights = {
    "news": 0.30,
    "polymarket": 0.45,
    "technicals": 0.25,
}
```
```python
final_score = sum(available[name] * weights[name] for name in available) / total_weight
result["final_signal"] = score_to_signal(final_score) or "HOLD"
```
```python
if score >= 0.75:
    return "STRONG BUY"
if score >= 0.60:
    return "BUY"
if score <= 0.25:
    return "STRONG SELL"
if score <= 0.40:
    return "SELL"
return "HOLD"
```
File: [backend/models/scoring_engine.py](D:\Python-Project\StockPulse-main\backend\models\scoring_engine.py)  
Internal Logic:
- Builds three comparable 0–1 scores:
  - technical
  - news
  - Polymarket
- Applies fixed weights
- Re-normalizes if some components are missing
- Converts final numeric score into signal label  
Actual Formula:
- `final_score = weighted_average(component_scores)`
- weights:
  - technical = `0.25`
  - news = `0.30`
  - Polymarket = `0.45`  
Presentation Explanation:
- “The final AI signal is not a black box. It is a transparent weighted fusion of chart signals, official news sentiment, and prediction-market sentiment.”

---

Feature: Final confidence calculation  
Library Used: Pure Python  
Code Snippet:
```python
distance = abs(final_score - 0.5) * 2.0
support = min(1.0, total_weight)
result["confidence"] = round(min(1.0, distance * 0.7 + support * 0.3), 3)
```
File: [backend/models/scoring_engine.py](D:\Python-Project\StockPulse-main\backend\models\scoring_engine.py)  
Internal Logic:
- Measures how far final score is from neutral `0.5`
- Adds a support term based on how many source weights were available
- Blends both into a capped confidence score  
Actual Formula:
- `distance = |final_score - 0.5| * 2`
- `support = total active source weight`
- `confidence = min(1, 0.7*distance + 0.3*support)`  
Presentation Explanation:
- “Confidence rises when the final score is clearly away from neutral and when enough signal sources are available to support the decision.”

---

If needed next, I can also create:
- a viva Q&A markdown
- a 5-minute presentation script markdown
- a one-page cheat sheet with only formulas and answers
