"""
Paper broker for spot LONG trades.

Simulates buying and selling without real capital.
P&L = (exit - entry) * qty  minus  round-trip fees.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PaperPosition:
    symbol: str
    side: str                # always "LONG" for spot
    entry_price: float
    quantity: float
    notional_usd: float
    stop_price: float
    take_profit_price: float
    opened_at: str


class PaperBroker:
    def __init__(self, fee_rate: float = 0.001):   # 0.1% spot default
        self.position: PaperPosition | None = None
        self.fee_rate = fee_rate

    def has_open_position(self) -> bool:
        return self.position is not None

    def open_long(
        self,
        symbol: str,
        entry_price: float,
        quantity: float,
        notional_usd: float,
        stop_price: float,
        take_profit_price: float,
    ) -> dict:
        if self.position:
            return {"ok": False, "reason": "Position already open"}

        self.position = PaperPosition(
            symbol=symbol,
            side="LONG",
            entry_price=entry_price,
            quantity=quantity,
            notional_usd=notional_usd,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            opened_at=datetime.utcnow().isoformat(),
        )
        return {"ok": True, "position": self.position}

    def check_exit(self, current_price: float) -> dict | None:
        if not self.position:
            return None

        p = self.position
        gross_pnl = (current_price - p.entry_price) * p.quantity
        fees      = (p.entry_price + current_price) * p.quantity * self.fee_rate
        net_pnl   = gross_pnl - fees

        # Stop hit: price fell below stop
        if current_price <= p.stop_price:
            return self.close(current_price, "STOP_LOSS")

        # Take profit hit: price rose above target
        if current_price >= p.take_profit_price:
            return self.close(current_price, "TAKE_PROFIT")

        return {
            "ok": False,
            "status": "OPEN",
            "entry_price":        p.entry_price,
            "stop_price":         p.stop_price,
            "take_profit_price":  p.take_profit_price,
            "current_price":      current_price,
            "gross_pnl":          gross_pnl,
            "net_pnl":            net_pnl,
        }

    def close(self, exit_price: float, reason: str) -> dict:
        if not self.position:
            return {"ok": False, "reason": "No open position"}

        p         = self.position
        gross_pnl = (exit_price - p.entry_price) * p.quantity
        fees      = (p.entry_price + exit_price) * p.quantity * self.fee_rate
        net_pnl   = gross_pnl - fees

        result = {
            "ok":           True,
            "symbol":       p.symbol,
            "side":         p.side,
            "entry_price":  p.entry_price,
            "exit_price":   exit_price,
            "quantity":     p.quantity,
            "notional_usd": p.notional_usd,
            "gross_pnl":    gross_pnl,
            "fees":         fees,
            "net_pnl":      net_pnl,
            "reason":       reason,
            "opened_at":    p.opened_at,
            "closed_at":    datetime.utcnow().isoformat(),
        }
        self.position = None
        return result
