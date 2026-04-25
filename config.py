import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "y")

@dataclass
class Settings:
    trading_mode: str = os.getenv("TRADING_MODE", "paper")
    enable_live_trading: bool = as_bool(os.getenv("ENABLE_LIVE_TRADING"), False)

    # Spot testnet keys from testnet.binance.vision (different from futures testnet)
    binance_api_key:    str  = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str  = os.getenv("BINANCE_API_SECRET", "")
    binance_testnet:    bool = as_bool(os.getenv("BINANCE_TESTNET"), True)
    # Use live public market data by default so the dashboard loads even without testnet symbols.
    market_data_testnet: bool = as_bool(os.getenv("MARKET_DATA_TESTNET"), False)

    symbol:           str = os.getenv("SYMBOL", "BTCUSDT").upper()
    interval:         str = os.getenv("INTERVAL", "1m")
    confirm_interval: str = os.getenv("CONFIRM_INTERVAL", "5m")
    leverage:         int = 1   # Spot has no leverage

    # Risk — no leverage so max_loss is simply capped by account size
    max_loss_usd:            float = float(os.getenv("MAX_LOSS_USD", "5"))
    target_profit_usd:       float = float(os.getenv("TARGET_PROFIT_USD", "1.0"))
    fee_rate:                float = float(os.getenv("FEE_RATE", "0.001"))   # Spot: 0.1%/leg
    daily_max_loss_usd:      float = float(os.getenv("DAILY_MAX_LOSS_USD", "15"))
    max_consecutive_losses:  int   = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "3"))
    min_score_to_buy:        int   = int(os.getenv("MIN_SCORE_TO_BUY", "13"))

    loop_seconds:  int = int(os.getenv("LOOP_SECONDS", "20"))
    candle_limit:  int = int(os.getenv("CANDLE_LIMIT", "150"))

    use_fear_greed_filter:    bool = as_bool(os.getenv("USE_FEAR_GREED_FILTER"), True)
    use_coingecko_filter:     bool = as_bool(os.getenv("USE_COINGECKO_FILTER"), True)
    block_extreme_volatility: bool = as_bool(os.getenv("BLOCK_EXTREME_VOLATILITY"), True)

    # Circuit breaker
    cb_drop_pct: float = float(os.getenv("CB_DROP_PCT", "3.0"))
    cb_window:   int   = int(os.getenv("CB_WINDOW_CANDLES", "5"))
    cb_atr_mult: float = float(os.getenv("CB_ATR_MULT", "4.0"))
    cb_cascade:  int   = int(os.getenv("CB_CASCADE_CANDLES", "5"))
    cb_cooldown: int   = int(os.getenv("CB_COOLDOWN_SECONDS", "300"))

    # Back-compat: if old MIN_SCORE_TO_SHORT is set, use it as fallback
    @property
    def min_score_to_short(self) -> int:
        return self.min_score_to_buy

settings = Settings()
