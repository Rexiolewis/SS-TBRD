import csv
from pathlib import Path
from datetime import datetime

class TradeLogger:
    def __init__(self, log_dir="logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.signal_file = self.log_dir / "signals.csv"
        self.trade_file = self.log_dir / "trades.csv"

    def _prepare_csv(self, path, fields):
        if not path.exists():
            return False

        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            current_fields = next(reader, [])

        if current_fields == fields:
            return True

        backup = path.with_name(f"{path.stem}_legacy_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{path.suffix}")
        path.replace(backup)
        return False

    def log_signal(self, symbol, action, score, price, reasons, signal=None):
        fields = [
            "time", "symbol", "action", "score", "confidence", "trend",
            "price", "entry_price", "take_profit_price", "stop_price",
            "target_net_profit_usd", "estimated_net_profit_usd",
            "estimated_stop_loss_usd", "risk_reward_ratio", "notional_usd",
            "quantity", "setup", "buy_zone", "sell_zone", "reasons"
        ]
        exists = self._prepare_csv(self.signal_file, fields)
        with self.signal_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not exists:
                writer.writeheader()
            signal = signal or object()
            writer.writerow({
                "time": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "action": action,
                "score": score,
                "confidence": getattr(signal, "confidence", ""),
                "trend": getattr(signal, "trend", ""),
                "price": price,
                "entry_price": getattr(signal, "entry_price", price),
                "take_profit_price": getattr(signal, "take_profit_price", ""),
                "stop_price": getattr(signal, "stop_price", ""),
                "target_net_profit_usd": getattr(signal, "target_net_profit_usd", ""),
                "estimated_net_profit_usd": getattr(signal, "estimated_net_profit_usd", ""),
                "estimated_stop_loss_usd": getattr(signal, "estimated_stop_loss_usd", ""),
                "risk_reward_ratio": getattr(signal, "risk_reward_ratio", ""),
                "notional_usd": getattr(signal, "notional_usd", ""),
                "quantity": getattr(signal, "quantity", ""),
                "setup": getattr(signal, "setup", ""),
                "buy_zone": getattr(signal, "buy_zone", ""),
                "sell_zone": getattr(signal, "sell_zone", ""),
                "reasons": " | ".join(reasons)
            })

    def log_trade(self, trade):
        exists = self.trade_file.exists()
        fields = [
            "closed_at", "symbol", "side", "entry_price", "exit_price", "quantity",
            "notional_usd", "gross_pnl", "fees", "net_pnl", "reason", "opened_at"
        ]
        with self.trade_file.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({k: trade.get(k) for k in fields})
