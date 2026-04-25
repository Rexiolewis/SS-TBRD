import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ManualPosition:
    symbol: str
    side: str
    entry_price: float
    quantity: float
    notional_usd: float
    stop_price: float
    take_profit_price: float
    opened_at: str


class ManualPaperBroker:
    def __init__(self, log_dir="logs", fee_rate=0.0005):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.position_file = self.log_dir / "manual_position.json"
        self.trade_file = self.log_dir / "manual_trades.csv"
        self.fee_rate = fee_rate

    def load_position(self):
        if not self.position_file.exists():
            return None
        try:
            data = json.loads(self.position_file.read_text(encoding="utf-8"))
            return ManualPosition(**data)
        except Exception:
            return None

    def has_open_position(self):
        return self.load_position() is not None

    def open_position(self, symbol, side, entry_price, notional_usd, stop_price=0.0, take_profit_price=0.0):
        if self.has_open_position():
            return {"ok": False, "reason": "Manual dummy position already open"}

        side = side.upper()
        if side not in ("LONG", "SHORT"):
            return {"ok": False, "reason": "Side must be LONG or SHORT"}
        if entry_price <= 0 or notional_usd <= 0:
            return {"ok": False, "reason": "Entry price and notional must be positive"}

        position = ManualPosition(
            symbol=symbol,
            side=side,
            entry_price=float(entry_price),
            quantity=float(notional_usd) / float(entry_price),
            notional_usd=float(notional_usd),
            stop_price=float(stop_price or 0),
            take_profit_price=float(take_profit_price or 0),
            opened_at=datetime.utcnow().isoformat(),
        )
        self.position_file.write_text(json.dumps(asdict(position), indent=2), encoding="utf-8")
        return {"ok": True, "reason": f"Opened manual dummy {side}", "position": position}

    def mark_to_market(self, current_price):
        position = self.load_position()
        if not position:
            return None

        gross_pnl = self._gross_pnl(position, current_price)
        fees = self._fees(position, current_price)
        return {
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "current_price": current_price,
            "quantity": position.quantity,
            "notional_usd": position.notional_usd,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": gross_pnl - fees,
            "stop_price": position.stop_price,
            "take_profit_price": position.take_profit_price,
            "opened_at": position.opened_at,
        }

    def close_position(self, exit_price, reason="MANUAL_CLOSE"):
        position = self.load_position()
        if not position:
            return {"ok": False, "reason": "No manual dummy position open"}

        gross_pnl = self._gross_pnl(position, exit_price)
        fees = self._fees(position, exit_price)
        trade = {
            "ok": True,
            "closed_at": datetime.utcnow().isoformat(),
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": float(exit_price),
            "quantity": position.quantity,
            "notional_usd": position.notional_usd,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": gross_pnl - fees,
            "reason": reason,
            "opened_at": position.opened_at,
        }
        self._append_trade(trade)
        self.position_file.unlink(missing_ok=True)
        return trade

    def reset_position(self):
        self.position_file.unlink(missing_ok=True)
        return {"ok": True, "reason": "Manual dummy position reset"}

    def _gross_pnl(self, position, exit_price):
        if position.side == "LONG":
            return (float(exit_price) - position.entry_price) * position.quantity
        return (position.entry_price - float(exit_price)) * position.quantity

    def _fees(self, position, exit_price):
        return (position.entry_price + float(exit_price)) * position.quantity * self.fee_rate

    def _append_trade(self, trade):
        fields = [
            "closed_at", "symbol", "side", "entry_price", "exit_price", "quantity",
            "notional_usd", "gross_pnl", "fees", "net_pnl", "reason", "opened_at"
        ]
        exists = self.trade_file.exists()
        with self.trade_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({field: trade.get(field) for field in fields})
