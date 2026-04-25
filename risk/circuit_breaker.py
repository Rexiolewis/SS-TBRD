"""
Circuit breaker — halts new trade entries on extreme market conditions.

Three independent triggers
──────────────────────────
1. Flash crash   : price dropped ≥ drop_pct% in the last drop_window candles.
2. ATR spike     : current ATR > atr_mult × its 50-candle rolling average.
3. Cascade       : cascade_candles consecutive large bearish candles (body > 0.5 × ATR).

Once triggered, the breaker blocks new entries for cooldown_sec seconds,
then auto-resets. It can also be cleared manually via force_resume().

Why this matters for a short bot
─────────────────────────────────
Flash crashes and cascades often V-reverse violently. Slippage, thin liquidity,
and forced liquidations make entries during extreme volatility very dangerous
even though the technical setup might "look" perfect. Better to wait.
"""

import time
import pandas as pd


class CircuitBreaker:
    def __init__(
        self,
        drop_pct: float = 3.0,          # % drop in window that triggers halt
        drop_window: int = 5,            # candles to measure the drop over
        atr_mult: float = 4.0,           # ATR spike multiplier vs 50-candle mean
        cascade_candles: int = 5,        # consecutive large red candles threshold
        cooldown_sec: int = 300,         # seconds to stay halted after trigger
    ):
        self._drop_pct = drop_pct
        self._drop_window = drop_window
        self._atr_mult = atr_mult
        self._cascade_candles = cascade_candles
        self._cooldown_sec = cooldown_sec

        self._halt_until: float = 0.0
        self._halt_reason: str = ""

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_halted(self) -> bool:
        return time.time() < self._halt_until

    def resume_in(self) -> int:
        """Seconds remaining in current cooldown (0 if clear)."""
        return max(0, int(self._halt_until - time.time()))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _trigger(self, reason: str):
        self._halt_reason = reason
        self._halt_until = time.time() + self._cooldown_sec

    @staticmethod
    def _rolling_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    # ── Public API ────────────────────────────────────────────────────────────

    def check(self, df: pd.DataFrame) -> dict:
        """
        Inspect the latest candles and fire a halt if any trigger condition is met.

        Parameters
        ----------
        df : raw OHLCV DataFrame (columns: open, high, low, close, volume)

        Returns
        -------
        {"halted": bool, "reason": str, "resume_in": int}
        """
        if self.is_halted:
            return {"halted": True, "reason": self._halt_reason, "resume_in": self.resume_in()}

        min_rows = max(self._drop_window + 1, 64)
        if len(df) < min_rows:
            return {"halted": False, "reason": "", "resume_in": 0}

        close = df["close"]
        atr_series = self._rolling_atr(df).dropna()
        current_atr = float(atr_series.iloc[-1]) if len(atr_series) else 0.0
        baseline_atr = float(atr_series.tail(50).mean()) if len(atr_series) >= 50 else current_atr

        # ── Trigger 1: Flash crash ─────────────────────────────────────────────
        window_start = float(close.iloc[-(self._drop_window + 1)])
        window_end = float(close.iloc[-1])
        if window_start > 0:
            drop_pct = (window_start - window_end) / window_start * 100
            if drop_pct >= self._drop_pct:
                reason = (
                    f"Flash crash: -{drop_pct:.2f}% in {self._drop_window} candles "
                    f"({window_start:.2f} → {window_end:.2f})"
                )
                self._trigger(reason)
                return {"halted": True, "reason": reason, "resume_in": self._cooldown_sec}

        # ── Trigger 2: ATR explosion ───────────────────────────────────────────
        if baseline_atr > 0 and current_atr > baseline_atr * self._atr_mult:
            ratio = current_atr / baseline_atr
            reason = (
                f"Volatility spike: ATR {current_atr:.2f} = {ratio:.1f}× baseline "
                f"({baseline_atr:.2f})"
            )
            self._trigger(reason)
            return {"halted": True, "reason": reason, "resume_in": self._cooldown_sec}

        # ── Trigger 3: Cascade of large bearish candles ────────────────────────
        tail = df.tail(self._cascade_candles)
        if len(tail) >= self._cascade_candles:
            all_red = (tail["close"] < tail["open"]).all()
            if all_red and current_atr > 0:
                bodies = tail["open"] - tail["close"]
                if (bodies > current_atr * 0.5).all():
                    reason = (
                        f"Cascade: {self._cascade_candles} consecutive large "
                        f"bearish candles"
                    )
                    self._trigger(reason)
                    return {"halted": True, "reason": reason, "resume_in": self._cooldown_sec}

        return {"halted": False, "reason": "", "resume_in": 0}

    def status(self) -> dict:
        """Current breaker state for dashboards and logging."""
        if self.is_halted:
            return {
                "halted": True,
                "reason": self._halt_reason,
                "resume_in": self.resume_in(),
            }
        return {"halted": False, "reason": "Clear", "resume_in": 0}

    def force_resume(self):
        """Manually clear the halt (e.g., via dashboard button)."""
        self._halt_until = 0.0
        self._halt_reason = ""
