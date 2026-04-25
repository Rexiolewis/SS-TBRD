from dataclasses import dataclass


@dataclass
class LongTradePlan:
    entry_price: float
    stop_price: float
    take_profit_price: float
    quantity: float
    notional_usd: float
    target_net_profit_usd: float
    estimated_gross_profit_usd: float
    estimated_target_fees_usd: float
    estimated_net_profit_usd: float
    estimated_stop_loss_usd: float
    risk_reward_ratio: float


def calculate_long_trade_plan(
    entry_price: float,
    stop_price: float,
    notional_usd: float,
    target_net_profit_usd: float = 1.0,
    fee_rate: float = 0.001,   # Spot taker fee (0.1% per side)
) -> LongTradePlan:
    """
    Fee-aware take-profit price for a spot LONG (buy) position.

    Net P&L formula
    ───────────────
    net = (tp - entry) * qty  -  fee_rate * qty * (entry + tp)
        = qty * [tp * (1 - fee_rate)  -  entry * (1 + fee_rate)]

    Solving for tp given target net:
        tp = (target / qty  +  entry * (1 + fee_rate)) / (1 - fee_rate)

    Note: spot fee is typically 0.1% (0.001) per trade leg, vs 0.05% for futures.
    """
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if stop_price >= entry_price:
        raise ValueError("stop_price must be below entry_price for a long")
    if notional_usd <= 0:
        raise ValueError("notional_usd must be positive")
    if target_net_profit_usd <= 0:
        raise ValueError("target_net_profit_usd must be positive")

    quantity = notional_usd / entry_price

    take_profit_price = (
        target_net_profit_usd / quantity + entry_price * (1 + fee_rate)
    ) / (1 - fee_rate)

    if take_profit_price <= entry_price:
        raise ValueError("target profit requires an impossible take-profit price")

    estimated_gross = (take_profit_price - entry_price) * quantity
    estimated_fees  = (entry_price + take_profit_price) * quantity * fee_rate
    estimated_net   = estimated_gross - estimated_fees

    stop_gross_loss = (entry_price - stop_price) * quantity
    stop_fees       = (entry_price + stop_price) * quantity * fee_rate
    estimated_stop_loss = stop_gross_loss + stop_fees

    rr = estimated_net / estimated_stop_loss if estimated_stop_loss > 0 else 0.0

    return LongTradePlan(
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        quantity=quantity,
        notional_usd=notional_usd,
        target_net_profit_usd=target_net_profit_usd,
        estimated_gross_profit_usd=estimated_gross,
        estimated_target_fees_usd=estimated_fees,
        estimated_net_profit_usd=estimated_net,
        estimated_stop_loss_usd=estimated_stop_loss,
        risk_reward_ratio=rr,
    )


@dataclass
class ShortTradePlan:
    entry_price: float
    stop_price: float
    take_profit_price: float
    quantity: float
    notional_usd: float
    target_net_profit_usd: float
    estimated_gross_profit_usd: float
    estimated_target_fees_usd: float
    estimated_net_profit_usd: float
    estimated_stop_loss_usd: float
    risk_reward_ratio: float


def calculate_short_trade_plan(
    entry_price: float,
    stop_price: float,
    notional_usd: float,
    target_net_profit_usd: float = 1.0,
    fee_rate: float = 0.0005,
) -> ShortTradePlan:
    if entry_price <= 0:
        raise ValueError("entry_price must be greater than zero")
    if stop_price <= entry_price:
        raise ValueError("stop_price must be above entry_price for a short")
    if notional_usd <= 0:
        raise ValueError("notional_usd must be greater than zero")
    if target_net_profit_usd <= 0:
        raise ValueError("target_net_profit_usd must be greater than zero")
    if fee_rate < 0:
        raise ValueError("fee_rate cannot be negative")

    quantity = notional_usd / entry_price

    # net = (entry - exit) * qty - fee_rate * qty * (entry + exit)
    take_profit_price = (
        entry_price * (1 - fee_rate) - (target_net_profit_usd / quantity)
    ) / (1 + fee_rate)

    if take_profit_price <= 0:
        raise ValueError("target profit requires an impossible take-profit price")

    estimated_gross_profit = (entry_price - take_profit_price) * quantity
    estimated_target_fees = (entry_price + take_profit_price) * quantity * fee_rate
    estimated_net_profit = estimated_gross_profit - estimated_target_fees

    stop_gross_loss = (stop_price - entry_price) * quantity
    stop_fees = (entry_price + stop_price) * quantity * fee_rate
    estimated_stop_loss = stop_gross_loss + stop_fees
    risk_reward = estimated_net_profit / estimated_stop_loss if estimated_stop_loss > 0 else 0

    return ShortTradePlan(
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        quantity=quantity,
        notional_usd=notional_usd,
        target_net_profit_usd=target_net_profit_usd,
        estimated_gross_profit_usd=estimated_gross_profit,
        estimated_target_fees_usd=estimated_target_fees,
        estimated_net_profit_usd=estimated_net_profit,
        estimated_stop_loss_usd=estimated_stop_loss,
        risk_reward_ratio=risk_reward,
    )
