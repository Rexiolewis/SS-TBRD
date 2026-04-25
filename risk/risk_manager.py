from dataclasses import dataclass
from datetime import date

@dataclass
class RiskDecision:
    allow: bool
    reason: str
    quantity: float
    notional_usd: float

class RiskManager:
    def __init__(
        self,
        max_loss_usd=5,
        target_profit_usd=1.2,
        leverage=2,
        daily_max_loss_usd=15,
        max_consecutive_losses=3,
    ):
        self.max_loss_usd = max_loss_usd
        self.target_profit_usd = target_profit_usd
        self.leverage = leverage
        self.daily_max_loss_usd = daily_max_loss_usd
        self.max_consecutive_losses = max_consecutive_losses

        self.today = date.today()
        self.daily_pnl = 0.0
        self.consecutive_losses = 0

    def reset_day_if_needed(self):
        if date.today() != self.today:
            self.today = date.today()
            self.daily_pnl = 0.0
            self.consecutive_losses = 0

    def record_trade(self, pnl):
        self.reset_day_if_needed()
        self.daily_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def can_trade(self, entry_price, stop_price, account_equity_usd=100):
        self.reset_day_if_needed()

        if self.daily_pnl <= -abs(self.daily_max_loss_usd):
            return RiskDecision(False, "Daily max loss reached", 0, 0)

        if self.consecutive_losses >= self.max_consecutive_losses:
            return RiskDecision(False, "Max consecutive losses reached", 0, 0)

        stop_distance = abs(stop_price - entry_price)
        if stop_distance <= 0:
            return RiskDecision(False, "Invalid stop distance", 0, 0)

        stop_pct = stop_distance / entry_price
        if stop_pct <= 0:
            return RiskDecision(False, "Invalid stop percent", 0, 0)

        # Notional position so that stop-loss is approximately max_loss_usd.
        notional = self.max_loss_usd / stop_pct

        # Keep beginner paper mode conservative.
        max_notional_allowed = account_equity_usd * self.leverage
        notional = min(notional, max_notional_allowed)

        quantity = notional / entry_price

        if notional < 5:
            return RiskDecision(False, "Position too small for practical execution", 0, 0)

        return RiskDecision(True, "Risk accepted", quantity, notional)
