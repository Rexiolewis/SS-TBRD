# Crypto Short Trading Bot Starter App

This is a **safe starter application** for a Binance USD-M Futures short trading bot.

Default mode: **PAPER TRADING ONLY**  
Live order execution is disabled unless you intentionally change the configuration.

## What it does

- Uses Binance public market data
- Calculates EMA, RSI, MACD, ATR, VWAP, support breakdown, and volume confirmation
- Builds a fee-aware short plan with entry, take-profit, stop, net target, estimated loss, and risk/reward
- Adds simple fundamental/sentiment blockers:
  - Fear & Greed Index
  - CoinGecko market data
  - Optional news keyword blocker
- Generates SHORT signals using a scoring engine
- Simulates short entries and exits in paper mode
- Applies:
  - USD 5 max loss per trade
  - Net profit target setting, defaulting to USD 1 per completed short
  - daily loss limit
  - consecutive loss limit
- Logs every signal and trade

## What it does NOT guarantee

It cannot guarantee USD 1 profit every run. No bot can do that. This app is built to reduce bad trades, manage risk, and test strategies safely before live usage.

## Setup

```bash
cd crypto_short_bot_app
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`.

For first run, keep:

```env
TRADING_MODE=paper
ENABLE_LIVE_TRADING=false
```

## Run bot

```bash
python app.py
```

## Dashboard

```bash
streamlit run dashboard.py
```

The dashboard includes a live Binance futures chart, EMA/VWAP overlays, entry/take-profit/stop lines, the current short decision, fundamental blockers, a manual prediction calculator, and CSV signal/trade history.

The dashboard sidebar also has bot controls:

- `Start` launches the paper bot loop in the background.
- `Stop` asks the bot to exit cleanly.
- `Force Stop` terminates the tracked bot process if it does not stop cleanly.
- `Bot log` shows the latest background bot output from `logs/bot_stdout.log`.

Use `Dummy backtest` in the dashboard before live trading. It replays the loaded candles, simulates short entries/exits, and reports trades, win rate, net PnL, max drawdown, and ending equity.

Use `Manual dummy trade` to practice your own Buy Long or Sell Short decisions without real money. It tracks one manual paper position at a time, calculates live unrealized PnL after fees, and writes closed manual trades to `logs/manual_trades.csv`.

## Deploy free on Streamlit Community Cloud

1. Push this project to a GitHub repository.
2. Do not commit `.env`, `venv/`, `logs/`, or `__pycache__/`. They are excluded by `.gitignore`.
3. Go to Streamlit Community Cloud and create a new app from your GitHub repository.
4. Set the app entry file to:

```text
dashboard.py
```

5. Add app secrets in Streamlit Cloud. Use root-level values so this app can read them through environment variables:

```toml
TRADING_MODE = "paper"
ENABLE_LIVE_TRADING = "false"
BINANCE_API_KEY = ""
BINANCE_API_SECRET = ""
BINANCE_TESTNET = "true"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
CONFIRM_INTERVAL = "5m"
MAX_LOSS_USD = "5"
TARGET_PROFIT_USD = "1.0"
FEE_RATE = "0.001"
DAILY_MAX_LOSS_USD = "15"
MAX_CONSECUTIVE_LOSSES = "3"
MIN_SCORE_TO_BUY = "13"
LOOP_SECONDS = "20"
CANDLE_LIMIT = "150"
USE_FEAR_GREED_FILTER = "true"
USE_COINGECKO_FILTER = "true"
BLOCK_EXTREME_VOLATILITY = "true"
```

For free Streamlit hosting, treat the dashboard as the deployed app. The background bot control can be useful for testing, but Streamlit Community Cloud apps can restart or sleep, so do not rely on it for unattended real-money trading.

## Binance testnet

Use Binance Futures testnet API keys first. Do not use live keys until paper results are stable.

## Main files

- `app.py` - bot runner
- `bot_control.py` - dashboard start/stop control and PID tracking
- `config.py` - environment settings
- `data/binance_client.py` - public and private Binance API helper
- `strategy/indicators.py` - technical indicators
- `strategy/signal_engine.py` - short signal scoring and trade-plan output
- `strategy/backtester.py` - dummy historical replay for paper validation
- `strategy/prediction_calculator.py` - fee-aware short target calculator
- `risk/risk_manager.py` - USD 5 stop-loss and position sizing
- `execution/paper_broker.py` - paper trading simulation
- `execution/manual_paper_broker.py` - dashboard manual dummy Buy/Sell trading
- `execution/live_broker_stub.py` - disabled live trading template
- `fundamental/fundamental_filters.py` - free API filters
- `storage/trade_logger.py` - CSV logs
- `dashboard.py` - simple Streamlit dashboard

## Suggested first settings

```env
SYMBOL=BTCUSDT
INTERVAL=1m
CONFIRM_INTERVAL=5m
MAX_LOSS_USD=5
TARGET_PROFIT_USD=1.0
FEE_RATE=0.0005
LEVERAGE=2
DAILY_MAX_LOSS_USD=15
MAX_CONSECUTIVE_LOSSES=3
MIN_SCORE_TO_SHORT=8
```

## Safety checklist before live trading

1. Paper trade for at least 2 to 4 weeks.
2. Check fees and slippage.
3. Confirm emergency exit works.
4. Confirm stop-loss is placed immediately after entry.
5. Start with very small capital.
6. Never expose API keys.
7. Disable withdrawal permission on Binance API key.
