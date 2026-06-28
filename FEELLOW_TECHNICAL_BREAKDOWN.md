# Feelow / StockPulse Technical Breakdown

This document explains the full implemented project in beginner-friendly language, while staying faithful to the actual codebase.

## 1. System Overview

### What the project does
Feelow is a stock intelligence dashboard that combines:
- market price data from Yahoo Finance
- technical indicators computed from price history
- official news sentiment from Yahoo Finance RSS headlines
- crowd sentiment from Polymarket prediction markets
- public discussion sentiment from Reddit and StockTwits
- a fused AI-style trading signal: `BUY`, `SELL`, or `HOLD`

### High-level data flow
1. Frontend calls FastAPI endpoints.
2. Backend fetches raw data from Yahoo Finance, Polymarket, Reddit, and StockTwits.
3. Backend computes indicators and sentiment scores.
4. Backend returns structured JSON for KPI cards, tabs, and charts.
5. Frontend renders dashboard cards, charts, tables, and summary explanations.

### Main files
- Backend API: `backend/main.py`
- Price data: `backend/data/market_data.py`
- Technical indicators: `backend/data/technical.py`
- News ingestion: `backend/data/news_ingestor.py`
- Official/news sentiment: `backend/models/sentiment_engine.py`
- Social ingestion: `backend/data/social_ingestor.py`
- Public opinion scoring: `backend/models/public_opinion_engine.py`
- Final AI signal fusion: `backend/models/scoring_engine.py`
- Polymarket processing: `backend/data/polymarket.py`
- Dashboard UI: `frontend/app.py`

## 2. Endpoint-by-Endpoint Architecture

### `/api/price-history`
- File: `backend/main.py`
- Uses `fetch_ohlcv()` and optionally `add_all_indicators()`
- Returns OHLCV data plus RSI, MACD, Bollinger Bands, and SMAs for charts

### `/api/kpis`
- File: `backend/main.py`
- Returns:
  - latest price
  - previous close
  - daily percentage move
  - RSI and RSI signal
  - MACD, MACD signal, MACD histogram
  - Bollinger Band upper/lower values
  - SMA 7, SMA 21, SMA 50
  - Polymarket score and label

### `/api/sentiment`
- File: `backend/main.py`
- Returns:
  - `official_analysis` from Yahoo Finance headlines
  - `public_opinion` from Reddit + StockTwits

### `/api/public-opinion`
- File: `backend/main.py`
- Returns only social/public mood summary

### `/api/polymarket`
- File: `backend/main.py`
- Returns processed Polymarket score, label, and selected markets

### `/api/signal`
- File: `backend/main.py`
- Returns final fused trading signal using technicals + official news + Polymarket

## 3. Price and Core Market Metrics

## Feature Name: Latest Price
- Simple Explanation:
  - This is the most recent closing price the app fetched for the selected stock.
- Technical Explanation:
  - The backend fetches recent OHLCV data from Yahoo Finance and takes the latest `Close`.
- Formula Used:
  - `price = latest Close`
- File Responsible:
  - `backend/data/market_data.py`
  - shown in `frontend/app.py`
- How Our Project Uses It:
  - price card
  - Bollinger Band position calculation
  - trend scoring versus moving averages
- What to Say in Presentation:
  - “This is the latest available adjusted market close for the stock. It is the base input for several downstream calculations.”

## Feature Name: Previous Close
- Simple Explanation:
  - Yesterday’s closing price.
- Technical Explanation:
  - The backend fetches 10 days of daily candles and uses the second-last `Close`.
- Formula Used:
  - `prev_close = Close[-2]`
- File Responsible:
  - `backend/data/market_data.py`
- How Our Project Uses It:
  - daily change percentage
- What to Say in Presentation:
  - “We compare the latest close to the previous close to measure daily movement.”

## Feature Name: Daily Change %
- Simple Explanation:
  - Shows how much the stock moved today compared with the last trading day.
- Technical Explanation:
  - Computed from latest close and previous close.
- Formula Used:
  - `change_pct = ((price - prev_close) / prev_close) * 100`
- File Responsible:
  - `backend/data/market_data.py`
  - displayed in KPI card in `frontend/app.py`
- How Our Project Uses It:
  - price delta card with up/down arrow
- Bullish/Bearish Meaning:
  - positive = bullish day
  - negative = bearish day
- What to Say in Presentation:
  - “This is short-term market movement only. It does not decide the final AI signal by itself.”

## 4. Technical Indicators

## Feature Name: RSI
- Simple Explanation:
  - RSI tells us whether price has been rising too fast or falling too fast recently.
- Technical Explanation:
  - The code computes price change per candle, separates gains and losses, smooths both with exponential weighting, computes relative strength, then converts it into a 0 to 100 oscillator.
- Formula Used:
  - `delta = close.diff()`
  - `gain = max(delta, 0)`
  - `loss = max(-delta, 0)`
  - `avg_gain = EWM(gain, alpha=1/14)`
  - `avg_loss = EWM(loss, alpha=1/14)`
  - `RS = avg_gain / avg_loss`
  - `RSI = 100 - (100 / (1 + RS))`
- File Responsible:
  - calculation: `backend/data/technical.py`
  - KPI label: `backend/data/technical.py`
  - displayed in KPI + chart: `frontend/app.py`
- How Our Project Uses It:
  - stored as `RSI`
  - shown on its own chart row
  - converted into:
    - `Overbought` if `RSI >= 70`
    - `Oversold` if `RSI <= 30`
    - `Neutral` otherwise
  - mapped into technical score by:
    - `map_rsi_score = clamp(0.5 + ((50 - RSI)/50)*0.5)`
- How the Final Signal Is Derived:
  - RSI contributes one component to the technical composite score.
  - Lower RSI pushes score upward in this implementation because oversold conditions are treated as rebound potential.
- Why RSI > 70 is overbought:
  - It means recent gains have dominated losses strongly. Traders interpret this as price being stretched upward and vulnerable to cooling off.
- Why RSI < 30 is oversold:
  - It means recent losses have dominated gains strongly. Traders interpret this as price being stretched downward and potentially ready for rebound.
- Bullish/Bearish Meaning:
  - below 30 = bearish selling may be exhausted, often interpreted as bullish reversal potential
  - above 70 = bullish run may be overheated, often interpreted as bearish reversal risk
- Beginner-Friendly Explanation:
  - “RSI is like a speedometer for price movement. Too high means the stock may have run up too fast. Too low means it may have dropped too fast.”
- What to Say in Presentation:
  - “Our RSI is a 14-period smoothed momentum oscillator. We use classic 70/30 interpretation and also convert it into a normalized technical score.”

## Feature Name: MACD
- Simple Explanation:
  - MACD measures trend and momentum by comparing fast and slow moving averages.
- Technical Explanation:
  - The code computes:
    - fast EMA: 12
    - slow EMA: 26
    - MACD line = fast EMA - slow EMA
    - signal line = 9-period EMA of MACD line
    - histogram = MACD line - signal line
- Formula Used:
  - `EMA_fast = EWM(close, span=12)`
  - `EMA_slow = EWM(close, span=26)`
  - `MACD = EMA_fast - EMA_slow`
  - `Signal = EWM(MACD, span=9)`
  - `Histogram = MACD - Signal`
- File Responsible:
  - calculation: `backend/data/technical.py`
  - displayed in chart and KPIs: `frontend/app.py`
- EMA Explanation:
  - EMA stands for Exponential Moving Average.
  - It gives more weight to recent prices than older prices.
  - That makes it react faster than a simple moving average.
- How Our Project Uses It:
  - Chart shows MACD line, signal line, and histogram.
  - Technical score uses `MACD - MACD_Signal` spread:
    - `map_macd_score = clamp(0.5 + (spread / (abs(spread)+1))*0.5)`
  - KPI card uses a simpler rule:
    - if `macd > 0` show `Bullish`
    - else show `Bearish`
- How the Final Signal Is Derived:
  - MACD spread contributes to the technical composite score.
- Bullish vs Bearish Crossover:
  - bullish crossover: MACD line crosses above signal line
  - bearish crossover: MACD line crosses below signal line
  - In this codebase, the technical score uses the spread between those two lines, which is the correct crossover-aware measure.
  - But the top KPI label uses only whether MACD is above or below zero, not whether it crossed the signal line.
- Bullish/Bearish Meaning:
  - MACD above signal = bullish momentum
  - MACD below signal = bearish momentum
  - MACD above zero = faster trend stronger than slower trend
- Beginner-Friendly Explanation:
  - “MACD compares short-term trend versus long-term trend. If the short-term trend is stronger, momentum is improving.”
- What to Say in Presentation:
  - “Our chart shows the full MACD system. In the scoring engine we use MACD spread, while the KPI card uses a simpler positive-versus-negative MACD read.”

## Feature Name: Bollinger Bands
- Simple Explanation:
  - Bollinger Bands show whether price is near the top or bottom of its recent normal range.
- Technical Explanation:
  - The code computes a 20-period simple moving average and 20-period standard deviation.
  - Upper and lower bands are two standard deviations above and below the average.
- Formula Used:
  - `BB_Mid = SMA(close, 20)`
  - `std = rolling_std(close, 20)`
  - `BB_Upper = BB_Mid + 2 * std`
  - `BB_Lower = BB_Mid - 2 * std`
  - `BB_Width = (BB_Upper - BB_Lower) / BB_Mid`
- File Responsible:
  - calculation: `backend/data/technical.py`
  - chart and KPI position: `frontend/app.py`
- How Our Project Uses It:
  - chart overlays upper band, lower band, and middle band
  - KPI card computes `BB Position`
- Upper/Lower Bands Meaning:
  - upper band = recent statistically high region
  - lower band = recent statistically low region
- Volatility Meaning:
  - wider bands mean more volatility
  - narrower bands mean less volatility
  - `BB_Width` is calculated in backend but not shown directly in the UI
- Feature Name: BB Position %
- Simple Explanation:
  - Shows where the current price sits between lower and upper Bollinger Bands.
- Formula Used:
  - `BB Position % = ((price - BB_Lower) / (BB_Upper - BB_Lower)) * 100`
- File Responsible:
  - derived in `frontend/app.py`
  - band values come from `backend/data/technical.py`
- How Our Project Uses It:
  - if `> 75%` -> `Near Upper`
  - if `< 25%` -> `Near Lower`
  - else -> `Mid Band`
- How the Final Signal Is Derived:
  - BB Position does not directly feed the final AI score.
  - It is an interpretive dashboard metric only.
- Bullish/Bearish Meaning:
  - near upper band can mean strength or possible overextension
  - near lower band can mean weakness or possible rebound zone
- Beginner-Friendly Explanation:
  - “This tells us whether current price is near the ceiling, middle, or floor of its recent trading range.”
- What to Say in Presentation:
  - “We use Bollinger Bands for context and chart interpretation. The dashboard also converts band location into a simple percentage position.”

## Feature Name: SMA 7 / SMA 21 / SMA 50
- Simple Explanation:
  - These are average prices over short, medium, and longer recent windows.
- Technical Explanation:
  - Each SMA is a rolling mean of closing prices.
- Formula Used:
  - `SMA_n = rolling_mean(close, n)`
- File Responsible:
  - `backend/data/technical.py`
  - chart overlays in `frontend/app.py`
- How Our Project Uses It:
  - visual chart overlays
  - SMA 21 and SMA 50 are used in technical trend scoring
- Bullish/Bearish Meaning:
  - price above SMA = strength
  - price below SMA = weakness
  - SMA 21 above SMA 50 = bullish trend alignment
  - SMA 21 below SMA 50 = bearish trend alignment
- Beginner-Friendly Explanation:
  - “Moving averages smooth out noisy price action so trend becomes easier to see.”
- What to Say in Presentation:
  - “We use these averages both visually and quantitatively. The scoring model compares price against SMA 21 and SMA 50.”

## Feature Name: Trend Detection
- Simple Explanation:
  - Trend detection checks whether price is aligned above or below key moving averages.
- Technical Explanation:
  - The project does not have a standalone trend model. Trend is implemented inside `map_sma_score()`.
  - It awards one bullish point for each of these:
    - `price >= sma_21`
    - `price >= sma_50`
    - `sma_21 >= sma_50`
  - Score is bullish points divided by total checks.
- Formula Used:
  - `trend_score = bullish_checks / 3`
- File Responsible:
  - `backend/models/scoring_engine.py`
- How Our Project Uses It:
  - becomes the `Trend` component inside the technical composite score
- How the Final Signal Is Derived:
  - technical score is the average of RSI score, MACD score, and trend score
- Bullish/Bearish Meaning:
  - 3/3 bullish checks = strong bullish alignment
  - 0/3 bullish checks = strong bearish alignment
- Beginner-Friendly Explanation:
  - “If price is above important moving averages, trend is healthier. If it is below them, trend is weaker.”
- What to Say in Presentation:
  - “Our trend logic is rule-based and transparent. It is not black-box AI.”

## Feature Name: Price Momentum
- Simple Explanation:
  - Momentum means how strongly price has been moving.
- Technical Explanation:
  - There is no separate dedicated `Price Momentum` metric implemented as its own backend field.
  - In this project, momentum is represented indirectly through:
    - RSI
    - MACD
    - daily change %
- File Responsible:
  - RSI/MACD: `backend/data/technical.py`
  - daily move: `backend/data/market_data.py`
- How Our Project Uses It:
  - momentum is inferred rather than computed as a named standalone feature
- What to Say in Presentation:
  - “We do not expose a separate momentum score. Instead, we capture momentum through RSI, MACD, and recent price movement.”

## Feature Name: Market Movement Logic
- Simple Explanation:
  - This means how the app reads current price action.
- Technical Explanation:
  - The project uses:
    - daily change percentage
    - RSI zone
    - MACD structure
    - SMA trend alignment
    - Bollinger Band location
- File Responsible:
  - multiple backend and frontend files listed above
- How Our Project Uses It:
  - these signals influence cards, charts, and the technical component of the final AI signal
- What to Say in Presentation:
  - “The dashboard separates raw movement, indicator context, and final scoring so the user can see both the data and the interpretation.”

## 5. Official News Sentiment

## Feature Name: RSS Ingestion Flow
- Simple Explanation:
  - The app pulls recent finance headlines for the selected stock from Yahoo Finance.
- Technical Explanation:
  - `fetch_news()` resolves company/ticker, requests Yahoo RSS feed, collects entries, then filters headlines using ticker/company keywords.
- Formula Used:
  - no finance formula; this is a data pipeline
- File Responsible:
  - `backend/data/news_ingestor.py`
- How Our Project Uses It:
  - provides official news headlines for FinBERT analysis
- What to Say in Presentation:
  - “We start from Yahoo Finance RSS headlines, then filter them so the news is actually relevant to the selected company.”

## Feature Name: FinBERT Usage
- Simple Explanation:
  - FinBERT is a finance-trained language model used to classify headlines as positive, negative, or neutral.
- Technical Explanation:
  - `transformers.pipeline("sentiment-analysis", model="ProsusAI/finbert")`
  - Each headline is scored once and converted into a signed number.
- Formula Used:
  - if model label = positive -> `+score`
  - if label = negative -> `-score`
  - if label = neutral -> `0`
- File Responsible:
  - `backend/models/sentiment_engine.py`
- How Our Project Uses It:
  - every official Yahoo headline gets:
    - sentiment label
    - signed score
    - source, URL, and timestamp
- What to Say in Presentation:
  - “FinBERT gives us finance-aware headline sentiment instead of generic NLP sentiment.”

## Feature Name: News Sentiment Scoring
- Simple Explanation:
  - Each article gets a number between `-1` and `+1`.
- Technical Explanation:
  - The raw FinBERT score is converted to signed form and then adjusted by title heuristics.
  - Example rule:
    - if headline sounds positive but is about price hikes, score is flipped negative
  - phrase dictionaries can strengthen weak positive or negative signals
- Formula Used:
  - `positive -> +probability`
  - `negative -> -probability`
  - weak signal threshold = `0.2`
- File Responsible:
  - `backend/models/sentiment_engine.py`
- How Our Project Uses It:
  - article-level scores feed average score, signal, confidence, and reason
- Beginner-Friendly Explanation:
  - “Positive headlines push the score above zero. Negative headlines push it below zero.”
- What to Say in Presentation:
  - “We do not use the model blindly. We add rule-based corrections for finance wording that generic classification can misread.”

## Feature Name: Neutral Sentiment Filtering
- Simple Explanation:
  - Weak or unclear headlines are not allowed to dominate the final news score.
- Technical Explanation:
  - `get_average_score()` filters out any item with `abs(score) < 0.2`
- Formula Used:
  - keep only scores where `|score| >= 0.2`
  - average only the kept articles
- File Responsible:
  - `backend/models/sentiment_engine.py`
- Why Neutral Sentiment Is Filtered:
  - It reduces noise.
  - It prevents many low-information headlines from diluting strong positive or negative headlines.
- What to Say in Presentation:
  - “We intentionally ignore weak sentiment so the average is based on meaningful headlines only.”

## Feature Name: Official News Aggregate Score
- Simple Explanation:
  - This is the average sentiment of meaningful official headlines.
- Technical Explanation:
  - The score range is `[-1, +1]`.
- Formula Used:
  - `avg_score = sum(filtered_scores) / count(filtered_scores)`
- File Responsible:
  - `backend/models/sentiment_engine.py`
  - packaged in `backend/main.py`
- Signal Thresholds:
  - `> 0.4` -> `STRONG BUY`
  - `> 0.1` -> `BUY`
  - `>= -0.1` -> `NEUTRAL`
  - `>= -0.4` -> `SELL`
  - else -> `STRONG SELL`
- What to Say in Presentation:
  - “This score represents the average directional tone of meaningful official headlines.”

## Feature Name: Official News Confidence
- Simple Explanation:
  - Confidence shows how many headlines have strong sentiment.
- Technical Explanation:
  - It counts headlines with `abs(score) > 0.6` and divides by total headlines.
- Formula Used:
  - `confidence = strong_headlines / total_headlines`
- File Responsible:
  - `backend/models/sentiment_engine.py`
- Beginner-Friendly Explanation:
  - “If many articles are strongly positive or strongly negative, confidence goes up.”
- What to Say in Presentation:
  - “This confidence is not market certainty. It is sentiment strength consistency.”

## Feature Name: Official News Reason Generator
- Simple Explanation:
  - This is the one-line explanation under the official news card.
- Technical Explanation:
  - It compares positive versus negative weight among meaningful headlines.
- File Responsible:
  - `backend/models/sentiment_engine.py`
- Example Outputs:
  - `Majority positive news sentiment`
  - `Majority negative news sentiment`
  - `Mixed market sentiment with slight positive bias`
- What to Say in Presentation:
  - “This turns the raw score into a human explanation for non-technical users.”

## 6. Public Opinion

## Feature Name: Reddit Ingestion
- Simple Explanation:
  - The app searches Reddit discussions related to the stock.
- Technical Explanation:
  - It tries:
    - Reddit search HTML
    - Reddit embedded JSON
    - old.reddit fallback
  - It extracts titles linking to `/comments/`
  - It cleans text, removes spam-like posts, and deduplicates items
- File Responsible:
  - `backend/data/social_ingestor.py`
- What to Say in Presentation:
  - “The Reddit collector is scrape-based with multiple fallback paths for resilience.”

## Feature Name: StockTwits Ingestion
- Simple Explanation:
  - The app also collects retail trader posts from StockTwits.
- Technical Explanation:
  - It calls the StockTwits symbol stream API, keeps only posts that explicitly mention the ticker, cleans text, and saves likes as engagement.
- File Responsible:
  - `backend/data/social_ingestor.py`
- What to Say in Presentation:
  - “StockTwits gives us more retail trading chatter than official finance media.”

## Feature Name: Public Sentiment Scoring
- Simple Explanation:
  - The app scores Reddit and StockTwits posts using the same FinBERT sentiment pipeline.
- Technical Explanation:
  - `analyze_public_opinion()` converts posts into FinBERT-compatible items and reuses `analyze_sentiment()`.
  - It then averages meaningful scores the same way as official news.
- Formula Used:
  - `public_sentiment_score = average of scores where |score| >= 0.2`
- File Responsible:
  - ingestion: `backend/data/social_ingestor.py`
  - scoring: `backend/models/public_opinion_engine.py`
  - model reuse: `backend/models/sentiment_engine.py`
- Bullish/Bearish Thresholds:
  - `score > 0.25` -> `BULLISH`
  - `score < -0.25` -> `BEARISH`
  - otherwise -> `NEUTRAL`
- Beginner-Friendly Explanation:
  - “This tells us how retail/social discussion feels overall.”
- What to Say in Presentation:
  - “Public sentiment is measured separately because retail chatter is noisier than official finance news.”

## Feature Name: Public Opinion Confidence
- Simple Explanation:
  - Confidence measures how much discussion exists and how much those posts agree.
- Technical Explanation:
  - It blends:
    - volume factor
    - agreement factor
    - intensity factor
- Formula Used:
  - `volume_factor = tanh(volume / 12)`
  - if bullish: `agreement = positive_count / volume`
  - if bearish: `agreement = negative_count / volume`
  - if neutral:
    - `agreement = neutral_count / volume`
    - if no neutrals, use `1 - directional_balance`
  - `intensity = average(abs(score)) of meaningful posts`
  - `confidence = min(1, volume_factor*0.5 + agreement*0.35 + intensity*0.15)`
- File Responsible:
  - `backend/models/public_opinion_engine.py`
- What to Say in Presentation:
  - “Public confidence is more sophisticated than news confidence because social data is noisier and needs volume and agreement checks.”

## Feature Name: Why Public Opinion Is Separate
- Simple Explanation:
  - Because social sentiment is useful, but noisier and easier to manipulate.
- Technical Explanation:
  - `public_opinion` is shown in `/api/sentiment` and `/api/public-opinion`.
  - It is not used inside the final `/api/signal` fusion model.
- File Responsible:
  - `backend/main.py`
  - `backend/models/scoring_engine.py`
- What to Say in Presentation:
  - “We surface public mood for context, but we keep it outside the final trading decision to avoid retail-noise distortion.”

## 7. Polymarket

## Feature Name: What Polymarket Is
- Simple Explanation:
  - Polymarket is a prediction market where users trade probabilities on future outcomes.
- Technical Explanation:
  - YES price is interpreted as market-implied probability from 0 to 1.
- Beginner-Friendly Explanation:
  - “If a Polymarket contract says 70% YES, the market is pricing that outcome as roughly 70% likely.”

## Feature Name: Polymarket Data Processing
- Simple Explanation:
  - The app searches active relevant prediction markets and converts them into a stock sentiment score.
- Technical Explanation:
  - Pipeline:
    1. search `/search-v2`
    2. optionally filter relevance with Gemini
    3. remove expired, illiquid, or almost-resolved markets
    4. classify questions like `close above`, `close below`, `hit high`, `hit low`
    5. convert YES probability into bullish sentiment
    6. weight events by `log1p(volume)`
    7. cap any single event at 30% influence
- File Responsible:
  - `backend/data/polymarket.py`
- What to Say in Presentation:
  - “We do not use Polymarket raw. We clean it heavily and only convert interpretable active markets into sentiment.”

## Feature Name: How Percentages Are Interpreted
- Simple Explanation:
  - YES % is the crowd’s estimated chance of the market question happening.
- Technical Explanation:
  - `_extract_price()` tries:
    - `outcomePrices[0]`
    - bid/ask midpoint
    - last trade price
- Formula Used:
  - `YES probability = extracted market price`
  - `NO probability = 1 - YES probability`
- File Responsible:
  - `backend/data/polymarket.py`

## Feature Name: Bullish/Bearish Conversion Rules
- Simple Explanation:
  - A high YES probability is not always bullish. It depends on the question wording.
- Technical Explanation:
  - `_market_to_sentiment()` rules:
    - `above` -> sentiment = `yes_prob`
    - `below` -> sentiment = `1 - yes_prob`
    - `hit_high` -> sentiment = `yes_prob`
    - `hit_low` -> sentiment = `1 - yes_prob`
    - `reach` -> sentiment = `yes_prob`
    - `range` or `other` -> ignored
- File Responsible:
  - `backend/data/polymarket.py`
- Example:
  - “Will TSLA close below $150?” with 80% YES is bearish.
  - So bullish sentiment becomes `1 - 0.80 = 0.20`.
- What to Say in Presentation:
  - “We convert market language into directional stock sentiment before scoring.”

## Feature Name: Active Market Filter
- Simple Explanation:
  - The app throws away bad markets before using them.
- Technical Explanation:
  - rejected if:
    - liquidity `< 50`
    - end date already passed
    - price `< 2%` or `> 98%`
- File Responsible:
  - `backend/data/polymarket.py`
- What to Say in Presentation:
  - “This prevents dead, dust, or already-resolved markets from distorting the crowd signal.”

## Feature Name: ATM Selection
- Simple Explanation:
  - If there are several `close above $X` markets, the app prefers the one closest to 50%.
- Technical Explanation:
  - `_atm_market()` selects active `above` markets whose YES probability is between 35% and 65%.
  - Then it picks the one closest to 50%.
- Why It Is Useful:
  - Near-50% contracts are the most informative because they are not already obvious.
- File Responsible:
  - `backend/data/polymarket.py`
- What to Say in Presentation:
  - “At-the-money contracts carry the richest information because the market is still actively debating them.”

## Feature Name: Polymarket Final Score
- Simple Explanation:
  - This is the crowd’s overall bullishness score for the stock on a 0 to 1 scale.
- Technical Explanation:
  - event-level sentiment records are combined with compressed volume weighting
- Formula Used:
  - `weight_i = log1p(volume_i + 1)`
  - cap each `weight_i` at `30% of total raw weight`
  - `score = sum(sentiment_i * weight_i) / sum(weight_i)`
  - final score is clamped to `[0,1]`
- File Responsible:
  - `backend/data/polymarket.py`
- Label Thresholds:
  - `>= 0.70` -> `Strongly Bullish`
  - `>= 0.55` -> `Slightly Bullish`
  - `>= 0.45` -> `Neutral`
  - `>= 0.30` -> `Slightly Bearish`
  - else -> `Strongly Bearish`
- Beginner-Friendly Explanation:
  - “0.5 is neutral. Above 0.5 means crowd leans bullish. Below 0.5 means crowd leans bearish.”
- What to Say in Presentation:
  - “Polymarket gives us a probability-weighted crowd intelligence layer, not just text sentiment.”

## 8. AI Signal Generation

## Feature Name: Technical Composite Score
- Simple Explanation:
  - This is the project’s internal technical score on a 0 to 1 scale.
- Technical Explanation:
  - It averages three parts:
    - RSI score
    - MACD spread score
    - SMA trend score
- Formula Used:
  - `technical_score = average([rsi_component, macd_component, trend_component])`
- File Responsible:
  - `backend/models/scoring_engine.py`
- Signal Thresholds:
  - `>= 0.75` -> `STRONG BUY`
  - `>= 0.60` -> `BUY`
  - `<= 0.25` -> `STRONG SELL`
  - `<= 0.40` -> `SELL`
  - else -> `HOLD`
- What to Say in Presentation:
  - “This is a transparent rule-based technical model, not a black-box neural network.”

## Feature Name: News Score Normalization
- Simple Explanation:
  - Official news average is on `[-1,1]`, but the fusion model needs `[0,1]`.
- Technical Explanation:
  - The code normalizes it linearly.
- Formula Used:
  - `news_score = (raw_news_score + 1) / 2`
- File Responsible:
  - `backend/models/scoring_engine.py`
- Examples:
  - `-1 -> 0`
  - `0 -> 0.5`
  - `+1 -> 1`
- What to Say in Presentation:
  - “Normalization lets technical, news, and Polymarket scores share the same scoring scale.”

## Feature Name: Final BUY / SELL / HOLD Fusion Logic
- Simple Explanation:
  - The final signal combines technicals, official news, and Polymarket into one score.
- Technical Explanation:
  - Weights:
    - `news = 0.30`
    - `polymarket = 0.45`
    - `technicals = 0.25`
  - Missing components are skipped, and weights are re-normalized over available sources.
- Formula Used:
  - `final_score = sum(component_score * weight) / sum(active_weights)`
- File Responsible:
  - `backend/models/scoring_engine.py`
- How the Final Signal Is Derived:
  - `score_to_signal(final_score)` with same thresholds as technical composite:
    - `>= 0.75` -> `STRONG BUY`
    - `>= 0.60` -> `BUY`
    - `<= 0.25` -> `STRONG SELL`
    - `<= 0.40` -> `SELL`
    - else -> `HOLD`
- Why This Is Useful:
  - It prevents a single source from dominating unless its weight and score justify it.
- Beginner-Friendly Explanation:
  - “The final signal is a weighted average of chart behavior, official news tone, and prediction-market crowd positioning.”
- What to Say in Presentation:
  - “Our fusion layer is explicit and auditable: 45% crowd markets, 30% official news, 25% technicals.”

## Feature Name: Final Confidence
- Simple Explanation:
  - Confidence is higher when the final score is far from neutral and when more source types are available.
- Technical Explanation:
  - It uses:
    - directional distance from neutral `0.5`
    - support from available weighted sources
- Formula Used:
  - `distance = abs(final_score - 0.5) * 2`
  - `support = min(1, total_weight_of_available_sources)`
  - `confidence = min(1, distance*0.7 + support*0.3)`
- File Responsible:
  - `backend/models/scoring_engine.py`
- Beginner-Friendly Explanation:
  - “Confidence rises when the model sees a stronger directional edge and enough source coverage.”
- What to Say in Presentation:
  - “This confidence is based on signal strength plus source support, not on future return certainty.”

## 9. Dashboard Components

## KPI Card: Price
- Shows:
  - latest price and today’s percentage move
- Colors:
  - Streamlit default positive/negative delta styling
- User Interpretation:
  - quick snapshot of today’s move
- What to Say:
  - “This is the current market context, not the full investment thesis.”

## KPI Card: RSI 14
- Shows:
  - numeric RSI and textual zone
- Example:
  - `RSI 75 -> Overbought`
- Colors:
  - delta color is forced off; interpretation is in the text
- User Interpretation:
  - stretched upward, stretched downward, or balanced

## KPI Card: MACD
- Shows:
  - numeric MACD value and `Bullish` or `Bearish`
- Important Implementation Note:
  - this label is based on `macd > 0`, not actual crossover
- User Interpretation:
  - whether short-term EMA is stronger than long-term EMA overall

## KPI Card: Polymarket
- Shows:
  - overall crowd score and label
- Example:
  - `62% -> Slightly Bullish`
- User Interpretation:
  - market-implied crowd positioning

## KPI Card: BB Position
- Shows:
  - where price sits inside the Bollinger range
- Example:
  - `81% -> Near Upper`
- User Interpretation:
  - price is near top, middle, or bottom of recent statistical range

## KPI Card: AI Signal
- Shows:
  - final fused verdict and confidence
- Example:
  - `HOLD -> Confidence: 42%`
- User Interpretation:
  - combined model output from technicals + news + Polymarket

## Price Chart Tab
- Shows:
  - candlestick, area, or line chart
  - optional Bollinger Bands
  - optional SMA overlays
  - optional volume
  - MACD subplot
  - RSI subplot
- Colors:
  - green candles/bars = bullish move
  - red candles/bars = bearish move
  - purple RSI line
  - blue MACD line
  - orange signal line
- User Interpretation:
  - full technical context behind the signal

## Polymarket Tab
- Shows:
  - overall Polymarket score card
  - each active market with YES %, derived sentiment, volume, end date, and link
- Colors:
  - green if YES % or derived sentiment is bullish
  - red if bearish
  - amber if near neutral
- User Interpretation:
  - where crowd prediction markets are leaning and why

## News Analysis Tab
- Shows:
  - official Yahoo signal card
  - confidence bar
  - reason string
  - article sentiment distribution pie chart
  - per-headline feed
- Colors:
  - green = positive
  - red = negative
  - amber = neutral
- User Interpretation:
  - official media sentiment direction and consistency

## Public Opinion Tab
- Shows:
  - retail/public mood card
  - confidence bar
  - total posts analyzed
  - Reddit and StockTwits feed
- Colors:
  - green = bullish public mood
  - red = bearish public mood
  - amber = neutral or mixed
- User Interpretation:
  - how the internet conversation feels, separate from official news

## AI Signal Tab
- Shows:
  - final verdict card
  - confidence bar
  - summary paragraph
  - technical/news/Polymarket driver cards
  - evidence trail
  - component bar chart
- Colors:
  - green = bullish driver
  - red = bearish driver
  - amber = mixed/hold
- Important Implementation Note:
  - the mini component chart simplifies source states:
    - technical/news `BUY -> 0.8`, `SELL -> 0.2`, `HOLD -> 0.5`
    - Polymarket uses its actual numeric score
- User Interpretation:
  - why the final signal was produced

## 10. Important Presentation Caveats

- Public opinion is displayed, but not included in final `/api/signal` fusion.
- The MACD KPI card is simpler than the chart logic; it uses `macd > 0` instead of crossover.
- Bollinger Band width is calculated in backend but not shown as its own dashboard metric.
- There is no standalone dedicated “price momentum” score; momentum is inferred through RSI, MACD, and daily move.
- Final signal styling in the frontend is optimized for exact `BUY`, `SELL`, `HOLD`. The backend can also emit `STRONG BUY` and `STRONG SELL`.

## 11. Short Presentation Script

Use this sequence in the demo:

1. “First, the app pulls clean market data from Yahoo Finance and computes RSI, MACD, Bollinger Bands, and moving averages.”
2. “RSI tells us whether recent price action is overheated or oversold.”
3. “MACD compares fast and slow EMAs to measure momentum and trend direction.”
4. “Bollinger Bands show where price sits inside its recent volatility range.”
5. “For official sentiment, we ingest Yahoo Finance RSS headlines and run them through FinBERT, then average only meaningful sentiment.”
6. “For public opinion, we separately analyze Reddit and StockTwits, because retail chatter is noisier than official media.”
7. “For crowd intelligence, we process Polymarket contracts, convert YES probabilities into bullish or bearish stock sentiment, and weight them by market volume.”
8. “Finally, the model fuses technicals, official news, and Polymarket with weights of 25%, 30%, and 45% respectively.”
9. “The final confidence depends on how far the score is from neutral and how many source types are available.”

## 12. Fast Answer Bank for Interview Questions

### “Why is RSI below 30 considered oversold?”
- Because recent losses have dominated gains so strongly that price may be stretched down relative to its recent behavior.

### “Why use EMA in MACD?”
- EMA reacts faster to recent prices than SMA, so it is better for momentum changes.

### “Why normalize news sentiment to 0 to 1?”
- Because technical and Polymarket scores are also used in a unified weighted fusion model.

### “Why separate public opinion from official news?”
- Because social data is noisier, easier to manipulate, and better treated as context rather than core decision input.

### “Why use Polymarket?”
- It provides real-money crowd probabilities, which can capture market expectations differently from news text and technical charts.

### “Why use weighted fusion instead of one model?”
- Because the system is easier to explain, audit, and debug when each signal source remains transparent.
