import numpy as np
import pandas as pd


# ── Primitive helpers ────────────────────────────────────────────────────────

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder-smoothed RSI (matches TradingView default)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def stoch_rsi(
    close: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """
    Stochastic RSI.
    Returns (K, D) lines in 0..100.
    K < D and both below 50 indicates bearish momentum.
    """
    r = rsi(close, rsi_period)
    lo = r.rolling(stoch_period).min()
    hi = r.rolling(stoch_period).max()
    raw_k = 100 * (r - lo) / (hi - lo).replace(0, np.nan)
    k = raw_k.rolling(k_smooth).mean()
    d = k.rolling(d_smooth).mean()
    return k, d


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-smoothed ATR."""
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).cumsum() / df["volume"].cumsum()


def bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, mid, lower)."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + num_std * std, mid, mid - num_std * std


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Williams %R in range -100..0.
    -20 to 0   → overbought (approaching reversal down)
    -80 to -100 → oversold  (approaching reversal up)
    """
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    return -100 * (hh - df["close"]) / (hh - ll).replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — accumulates volume in direction of price move."""
    direction = np.sign(df["close"].diff())
    direction.iloc[0] = 0
    return (direction * df["volume"]).cumsum()


def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Heikin-Ashi candles.
    HA bearish signal: ha_close < ha_open (red HA candle).
    """
    close_vals = ((df["open"] + df["high"] + df["low"] + df["close"]) / 4).to_numpy()
    open_vals = df["open"].to_numpy()
    close_raw = df["close"].to_numpy()

    ha_open = np.empty(len(df))
    ha_open[0] = (open_vals[0] + close_raw[0]) / 2
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i - 1] + close_vals[i - 1]) / 2

    ha_high = np.maximum(np.maximum(df["high"].to_numpy(), ha_open), close_vals)
    ha_low = np.minimum(np.minimum(df["low"].to_numpy(), ha_open), close_vals)

    return pd.DataFrame(
        {"ha_open": ha_open, "ha_high": ha_high, "ha_low": ha_low, "ha_close": close_vals},
        index=df.index,
    )


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Previous bullish candle fully engulfed by current bearish candle."""
    p_open = df["open"].shift(1)
    p_close = df["close"].shift(1)
    prev_bull = p_close > p_open
    curr_bear = df["close"] < df["open"]
    engulfs = (df["open"] >= p_close) & (df["close"] <= p_open)
    return (prev_bull & curr_bear & engulfs).fillna(False)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Previous bearish candle fully engulfed by current bullish candle."""
    p_open = df["open"].shift(1)
    p_close = df["close"].shift(1)
    prev_bear = p_close < p_open
    curr_bull = df["close"] > df["open"]
    engulfs = (df["open"] <= p_close) & (df["close"] >= p_open)
    return (prev_bear & curr_bull & engulfs).fillna(False)


def support_level(df: pd.DataFrame, lookback: int = 20) -> float:
    return float(df["low"].tail(lookback).min())


# ── Composite ────────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Trend EMAs
    df["ema_9"] = ema(df["close"], 9)
    df["ema_21"] = ema(df["close"], 21)
    df["ema_50"] = ema(df["close"], 50)
    df["ema_200"] = ema(df["close"], 200)

    # Momentum
    df["rsi_14"] = rsi(df["close"], 14)
    df["stoch_k"], df["stoch_d"] = stoch_rsi(df["close"])
    df["macd_line"], df["macd_signal"], df["macd_hist"] = macd(df["close"])
    df["williams_r"] = williams_r(df)

    # Volatility / structure
    df["atr_14"] = atr(df, 14)
    df["vwap"] = vwap(df)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(df["close"])

    # Volume
    df["obv"] = obv(df)
    df["obv_ema_10"] = df["obv"].ewm(span=10, adjust=False).mean()
    df["volume_ma_20"] = df["volume"].rolling(20).mean()

    # Candlestick patterns
    ha = heikin_ashi(df)
    df["ha_open"] = ha["ha_open"]
    df["ha_close"] = ha["ha_close"]
    df["bearish_engulfing"] = bearish_engulfing(df)
    df["bullish_engulfing"] = bullish_engulfing(df)

    return df
