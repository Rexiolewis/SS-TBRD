from dataclasses import dataclass

import pandas as pd

from execution.paper_broker import PaperBroker
from risk.risk_manager import RiskManager


@dataclass
class BacktestSummary:
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl: float
    max_drawdown: float
    ending_equity: float
    trades: pd.DataFrame


def _empty_summary(starting_equity):
    return BacktestSummary(
        total_trades=0,
        wins=0,
        losses=0,
        win_rate=0.0,
        net_pnl=0.0,
        max_drawdown=0.0,
        ending_equity=starting_equity,
        trades=pd.DataFrame(),
    )


def _max_drawdown(equity_curve):
    peak = equity_curve[0] if equity_curve else 0.0
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return abs(worst)


def run_short_backtest(
    df_1m,
    df_5m,
    signal_engine,
    symbol,
    starting_equity=100.0,
    max_loss_usd=5.0,
    leverage=2,
    max_hold_candles=30,
    fee_rate=0.0005,
):
    if df_1m.empty or df_5m.empty:
        return _empty_summary(starting_equity)

    risk = RiskManager(
        max_loss_usd=max_loss_usd,
        leverage=leverage,
        daily_max_loss_usd=abs(max_loss_usd) * 1000,
        max_consecutive_losses=1000,
    )
    trades = []
    equity = float(starting_equity)
    equity_curve = [equity]

    i = 60
    while i < len(df_1m) - 2:
        current_time = df_1m.iloc[i]["open_time"]
        entry_slice = df_1m.iloc[: i + 1]
        confirm_slice = df_5m[df_5m["open_time"] <= current_time]
        if len(confirm_slice) < 60:
            i += 1
            continue

        preliminary = signal_engine.evaluate(entry_slice, confirm_slice, position_size_usd=100)
        if preliminary.action != "SHORT":
            i += 1
            continue

        decision = risk.can_trade(preliminary.entry_price, preliminary.stop_price, account_equity_usd=equity)
        if not decision.allow:
            i += 1
            continue

        signal = signal_engine.evaluate(entry_slice, confirm_slice, position_size_usd=decision.notional_usd)
        broker = PaperBroker(fee_rate=fee_rate)
        broker.open_short(
            symbol=symbol,
            entry_price=signal.entry_price,
            quantity=decision.quantity,
            notional_usd=decision.notional_usd,
            stop_price=signal.stop_price,
            take_profit_price=signal.take_profit_price,
        )

        exit_trade = None
        exit_index = min(i + max_hold_candles, len(df_1m) - 1)
        for j in range(i + 1, exit_index + 1):
            candle = df_1m.iloc[j]
            if float(candle["high"]) >= signal.stop_price:
                exit_trade = broker.close(signal.stop_price, "STOP_LOSS")
                exit_index = j
                break
            if float(candle["low"]) <= signal.take_profit_price:
                exit_trade = broker.close(signal.take_profit_price, "TAKE_PROFIT")
                exit_index = j
                break

        if exit_trade is None:
            exit_trade = broker.close(float(df_1m.iloc[exit_index]["close"]), "MAX_HOLD_EXIT")

        equity += float(exit_trade["net_pnl"])
        equity_curve.append(equity)
        exit_trade["entry_time"] = df_1m.iloc[i]["open_time"]
        exit_trade["exit_time"] = df_1m.iloc[exit_index]["open_time"]
        exit_trade["score"] = signal.score
        exit_trade["confidence"] = signal.confidence
        trades.append(exit_trade)
        risk.record_trade(float(exit_trade["net_pnl"]))
        i = exit_index + 1

    if not trades:
        return _empty_summary(starting_equity)

    trades_df = pd.DataFrame(trades)
    wins = int((trades_df["net_pnl"] > 0).sum())
    losses = int((trades_df["net_pnl"] <= 0).sum())
    total = len(trades_df)
    net_pnl = float(trades_df["net_pnl"].sum())

    return BacktestSummary(
        total_trades=total,
        wins=wins,
        losses=losses,
        win_rate=(wins / total) * 100 if total else 0.0,
        net_pnl=net_pnl,
        max_drawdown=_max_drawdown(equity_curve),
        ending_equity=equity,
        trades=trades_df,
    )
