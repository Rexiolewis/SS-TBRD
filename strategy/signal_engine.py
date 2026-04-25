"""
Spot Long signal engine — 20-point dip-buying scoring system.

Strategy: "buy the dip in an uptrend"
• Wait for macro uptrend context (price above EMA50/200, bullish EMA stack).
• Enter when price dips to oversold levels (RSI < 45, Stoch oversold, near support / lower BB).
• Confirm reversal with bullish candles, rising OBV, and bid pressure.
• Target $1 net profit per trade after spot fees (0.1% per leg).

Score breakdown
───────────────
Trend context   (max 6)   EMA alignment, price vs EMAs, 5m confirmation
Momentum        (max 5)   RSI oversold zone, Stoch RSI recovering, MACD, Williams %R
Structure       (max 4)   Support bounce, lower-BB proximity, bullish engulfing
Volume          (max 3)   Volume spike (capitulation), OBV rising, VWAP proximity
Pattern/MkSt    (max 2)   Heikin-Ashi bullish, order-book bid pressure

Threshold: 13 / 20 (65%) to fire BUY.
"""

from dataclasses import dataclass, field
import pandas as pd
from .indicators import add_indicators, support_level
from .prediction_calculator import calculate_long_trade_plan


@dataclass
class SignalResult:
    action: str
    score: int
    max_score: int
    reasons: list
    entry_price: float
    stop_price: float
    take_profit_price: float
    confidence: float = 0.0
    trend: str = "UNKNOWN"
    setup: str = "No trade"
    buy_zone: str = ""
    sell_zone: str = ""
    target_net_profit_usd: float = 0.0
    estimated_net_profit_usd: float = 0.0
    estimated_stop_loss_usd: float = 0.0
    risk_reward_ratio: float = 0.0
    notional_usd: float = 0.0
    quantity: float = 0.0
    score_breakdown: dict = field(default_factory=dict)


class SpotLongEngine:
    """Buy-the-dip signal engine for Binance Spot trading."""

    MAX_SCORE  = 20
    MIN_RR     = 0.35      # minimum R/R before a BUY fires

    def __init__(
        self,
        min_score: int = 13,
        target_profit_usd: float = 1.0,
        max_loss_usd: float = 5.0,
        fee_rate: float = 0.001,   # Spot: 0.1% per leg
    ):
        self.min_score = min_score
        self.target_profit_usd = target_profit_usd
        self.max_loss_usd = max_loss_usd
        self.fee_rate = fee_rate

    # ── Evaluate ──────────────────────────────────────────────────────────────

    def evaluate(
        self,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        order_book: dict | None = None,
        position_size_usd: float = 100.0,
    ) -> SignalResult:

        df_1m = add_indicators(df_1m).dropna(subset=["ema_9", "ema_21", "rsi_14", "macd_hist"])
        df_5m = add_indicators(df_5m).dropna(subset=["ema_21", "ema_50"])

        if len(df_1m) < 55 or len(df_5m) < 30:
            return SignalResult("WAIT", 0, self.MAX_SCORE, ["Insufficient candle data"], 0, 0, 0)

        last    = df_1m.iloc[-1]
        prev    = df_1m.iloc[-2]
        confirm = df_5m.iloc[-1]
        close   = float(last["close"])

        score    = 0
        reasons: list[str] = []
        breakdown: dict[str, int] = {}

        # ── 1. TREND CONTEXT (max 6) ──────────────────────────────────────────
        # We want macro uptrend so we're buying WITH the trend, not against it.

        trend_pts = 0

        # EMA stack: 9 > 21 > 50 = healthy uptrend
        if last["ema_9"] > last["ema_21"] and last["ema_21"] > last["ema_50"]:
            trend_pts += 2
            reasons.append("EMA stack bullish: 9 > 21 > 50")
        elif last["ema_9"] > last["ema_21"]:
            trend_pts += 1
            reasons.append("EMA 9 above EMA 21")

        # Price above EMA50 (macro support intact)
        if close > float(last["ema_50"]):
            trend_pts += 2
            reasons.append("Price above EMA 50 (macro uptrend intact)")
        elif close > float(last["ema_21"]):
            trend_pts += 1
            reasons.append("Price above EMA 21")

        # 5m context: dip visible but EMA50 still support on 5m
        if float(confirm["close"]) < float(confirm["ema_9"]):
            trend_pts += 1
            reasons.append("5m short-term dip (below EMA 9)")
        if float(confirm["close"]) > float(confirm["ema_50"]):
            trend_pts += 1
            reasons.append("5m price above EMA 50 (macro bullish on 5m)")

        score += trend_pts
        breakdown["trend"] = trend_pts

        # ── 2. MOMENTUM — OVERSOLD RECOVERY (max 5) ──────────────────────────
        # We want RSI oversold but starting to turn up — the reversal entry.

        mom_pts = 0

        rsi_val = float(last["rsi_14"])
        if 25 <= rsi_val <= 45:
            mom_pts += 1
            reasons.append(f"RSI in oversold bounce zone: {rsi_val:.1f}")

        # Stoch RSI: K > D recovering from below 25 (fresh bullish cross)
        k_val = float(last["stoch_k"]) if pd.notna(last["stoch_k"]) else 100.0
        d_val = float(last["stoch_d"]) if pd.notna(last["stoch_d"]) else 100.0
        k_prev = float(prev["stoch_k"]) if pd.notna(prev["stoch_k"]) else 100.0
        if k_val > d_val and k_val < 50 and k_prev < d_val:
            mom_pts += 2
            reasons.append(f"Stoch RSI bullish crossover: K={k_val:.1f} crossed above D={d_val:.1f}")
        elif k_val > d_val and k_val < 40:
            mom_pts += 1
            reasons.append(f"Stoch RSI K above D in oversold territory")

        # MACD histogram improving (turning up from negative)
        hist_now  = float(last["macd_hist"])
        hist_prev = float(prev["macd_hist"])
        if hist_now > hist_prev:
            mom_pts += 1
            reasons.append("MACD histogram improving (momentum recovering)")

        # Williams %R deeply oversold (below -75)
        wr = float(last["williams_r"]) if pd.notna(last["williams_r"]) else 0.0
        if wr < -75:
            mom_pts += 1
            reasons.append(f"Williams %R deeply oversold: {wr:.1f}")

        score += mom_pts
        breakdown["momentum"] = mom_pts

        # ── 3. STRUCTURE (max 4) ──────────────────────────────────────────────

        struct_pts = 0

        # Support level: price bouncing near recent 20-candle low
        support = support_level(df_1m.iloc[:-1], lookback=20)
        if support > 0 and (close - support) / support <= 0.005:
            struct_pts += 2
            reasons.append(f"Price at support level: {support:.2f}")
        elif support > 0 and (close - support) / support <= 0.012:
            struct_pts += 1
            reasons.append(f"Price near support: {support:.2f}")

        # Price near lower Bollinger Band (within 0.5% above lower band)
        bb_lower = float(last["bb_lower"]) if pd.notna(last["bb_lower"]) else 0.0
        if bb_lower > 0 and (close - bb_lower) / bb_lower <= 0.005:
            struct_pts += 1
            reasons.append("Price at/near lower Bollinger Band")

        # Bullish engulfing candle
        if bool(last["bullish_engulfing"]):
            struct_pts += 1
            reasons.append("Bullish engulfing candle")

        score += struct_pts
        breakdown["structure"] = struct_pts

        # ── 4. VOLUME (max 3) ─────────────────────────────────────────────────

        vol_pts = 0

        # Volume spike: capitulation / panic selling = reversal fuel
        if pd.notna(last["volume_ma_20"]) and float(last["volume"]) > 1.5 * float(last["volume_ma_20"]):
            vol_pts += 1
            reasons.append("Volume spike (potential capitulation)")

        # OBV rising: buyers accumulating
        if pd.notna(last["obv_ema_10"]) and float(last["obv"]) > float(last["obv_ema_10"]):
            vol_pts += 1
            reasons.append("OBV above its EMA (buying pressure)")

        # Price near VWAP (within 0.5% below) — VWAP as support
        if pd.notna(last["vwap"]) and last["vwap"] > 0:
            vwap_diff = (float(last["vwap"]) - close) / float(last["vwap"])
            if 0 <= vwap_diff <= 0.005:
                vol_pts += 1
                reasons.append("Price bouncing at VWAP support")

        score += vol_pts
        breakdown["volume"] = vol_pts

        # ── 5. PATTERN / MICROSTRUCTURE (max 2) ──────────────────────────────

        pat_pts = 0

        # Heikin-Ashi: green HA candle = bullish momentum
        if pd.notna(last["ha_close"]) and float(last["ha_close"]) > float(last["ha_open"]):
            pat_pts += 1
            reasons.append("Heikin-Ashi candle bullish (green)")

        # Order book: bid notional > ask notional
        if order_book:
            try:
                bid_notional = sum(float(p) * float(q) for p, q in order_book.get("bids", [])[:10])
                ask_notional = sum(float(p) * float(q) for p, q in order_book.get("asks", [])[:10])
                if bid_notional > ask_notional * 1.10:
                    pat_pts += 1
                    reasons.append("Order book bid pressure dominant")
            except Exception:
                pass

        score += pat_pts
        breakdown["pattern_mkst"] = pat_pts

        # ── Stop / take-profit calculation ────────────────────────────────────
        # Stop: below recent 15-candle low minus 0.5 × ATR (tight, below noise)
        recent_low = float(df_1m["low"].tail(15).min())
        atr_val    = float(last["atr_14"]) if pd.notna(last["atr_14"]) else close * 0.002
        stop_price = min(recent_low, close - atr_val * 0.5)

        try:
            plan = calculate_long_trade_plan(
                entry_price=close,
                stop_price=stop_price,
                notional_usd=position_size_usd,
                target_net_profit_usd=self.target_profit_usd,
                fee_rate=self.fee_rate,
            )
        except ValueError as exc:
            return SignalResult(
                "WAIT", score, self.MAX_SCORE, [*reasons, str(exc)],
                close, stop_price, 0,
                score_breakdown=breakdown,
            )

        # Minimum R/R gate
        if plan.risk_reward_ratio < self.MIN_RR:
            reasons.append(
                f"R/R {plan.risk_reward_ratio:.2f} below minimum {self.MIN_RR} — skipped"
            )
            return SignalResult(
                "WAIT", score, self.MAX_SCORE, reasons,
                close, stop_price, plan.take_profit_price,
                confidence=round(score / self.MAX_SCORE * 100, 1),
                score_breakdown=breakdown,
            )

        action     = "BUY" if score >= self.min_score else "WAIT"
        confidence = round(score / self.MAX_SCORE * 100, 1)
        trend      = "BULLISH" if score >= self.min_score else "MIXED"
        setup      = "Dip-buy setup confirmed" if action == "BUY" else "Wait — insufficient confluence"

        if action == "BUY":
            buy_zone  = f"Spot buy entry ~{close:.4f}"
            sell_zone = (
                f"Sell for profit near {plan.take_profit_price:.4f} (+$1 net), "
                f"stop {stop_price:.4f}"
            )
        else:
            buy_zone  = "No entry"
            sell_zone = f"Watching — stop would be {stop_price:.4f}"
            reasons.append(f"Score {score}/{self.MAX_SCORE} below threshold {self.min_score}")

        return SignalResult(
            action=action,
            score=score,
            max_score=self.MAX_SCORE,
            reasons=reasons,
            entry_price=close,
            stop_price=stop_price,
            take_profit_price=plan.take_profit_price,
            confidence=confidence,
            trend=trend,
            setup=setup,
            buy_zone=buy_zone,
            sell_zone=sell_zone,
            target_net_profit_usd=self.target_profit_usd,
            estimated_net_profit_usd=plan.estimated_net_profit_usd,
            estimated_stop_loss_usd=plan.estimated_stop_loss_usd,
            risk_reward_ratio=plan.risk_reward_ratio,
            notional_usd=position_size_usd,
            quantity=plan.quantity,
            score_breakdown=breakdown,
        )


# Back-compat alias — old code that imports ShortSignalEngine still loads
ShortSignalEngine = SpotLongEngine
