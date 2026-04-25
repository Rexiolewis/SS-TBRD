import time
import os
from bot_control import mark_bot_started, mark_bot_stopped, should_keep_running
from config import settings
from data.binance_client import BinanceSpotClient
from data.ws_stream import BinanceWSStream
from strategy.signal_engine import SpotLongEngine
from risk.risk_manager import RiskManager
from risk.circuit_breaker import CircuitBreaker
from execution.paper_broker import PaperBroker
from fundamental.fundamental_filters import FundamentalFilters
from storage.trade_logger import TradeLogger

_WS_LOOP_SECONDS = 2
_DIVIDER = "─" * 60


def controlled_sleep(seconds: float) -> bool:
    for _ in range(max(int(seconds), 1)):
        if not should_keep_running():
            return False
        time.sleep(1)
    return True


def _fetch_rest(client: BinanceSpotClient):
    df_1m      = client.get_klines(settings.symbol, settings.interval, settings.candle_limit)
    df_5m      = client.get_klines(settings.symbol, settings.confirm_interval, settings.candle_limit)
    order_book = client.get_order_book(settings.symbol, limit=20)
    latest_price = float(df_1m.iloc[-1]["close"])
    return df_1m, df_5m, order_book, latest_price


def main():
    print(_DIVIDER)
    print("  Crypto Spot Long Bot  —  starting up")
    print(f"  Mode     : {settings.trading_mode}")
    print(f"  Symbol   : {settings.symbol}")
    print(f"  Target   : ${settings.target_profit_usd:.2f} net profit per trade (after fees)")
    print(f"  Max loss : ${settings.max_loss_usd:.2f} per trade")
    print(f"  Fee rate : {settings.fee_rate*100:.2f}% per leg (spot)")
    print(_DIVIDER)

    client = BinanceSpotClient(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        testnet=settings.binance_testnet,
    )

    signal_engine = SpotLongEngine(
        min_score=settings.min_score_to_buy,
        target_profit_usd=settings.target_profit_usd,
        max_loss_usd=settings.max_loss_usd,
        fee_rate=settings.fee_rate,
    )

    risk = RiskManager(
        max_loss_usd=settings.max_loss_usd,
        target_profit_usd=settings.target_profit_usd,
        leverage=1,   # spot: no leverage
        daily_max_loss_usd=settings.daily_max_loss_usd,
        max_consecutive_losses=settings.max_consecutive_losses,
    )

    broker          = PaperBroker(fee_rate=settings.fee_rate)
    fundamentals    = FundamentalFilters()
    logger          = TradeLogger()
    circuit_breaker = CircuitBreaker(
        drop_pct=settings.cb_drop_pct,
        drop_window=settings.cb_window,
        atr_mult=settings.cb_atr_mult,
        cascade_candles=settings.cb_cascade,
        cooldown_sec=settings.cb_cooldown,
    )
    mark_bot_started(os.getpid())

    # ── Bootstrap WebSocket with REST seed data ───────────────────────────────
    print("Fetching initial candle history via REST…")
    try:
        df_1m_seed = client.get_klines(settings.symbol, settings.interval, settings.candle_limit)
        df_5m_seed = client.get_klines(settings.symbol, settings.confirm_interval, settings.candle_limit)
        print(f"  Seeded {len(df_1m_seed)} × {settings.interval}  |  {len(df_5m_seed)} × {settings.confirm_interval}")
    except Exception as exc:
        print(f"REST seed failed: {exc} — will retry in loop")
        df_1m_seed = df_5m_seed = None

    stream = BinanceWSStream(
        symbol=settings.symbol,
        intervals=[settings.interval, settings.confirm_interval],
        testnet=settings.binance_testnet,
    )
    if df_1m_seed is not None:
        stream.seed({settings.interval: df_1m_seed, settings.confirm_interval: df_5m_seed})
    stream.start(timeout=12)

    use_ws       = stream.is_ready
    loop_seconds = _WS_LOOP_SECONDS if use_ws else settings.loop_seconds
    print(f"Data source : {'WebSocket (real-time)' if use_ws else 'REST polling'}")
    print(f"Loop cadence: {loop_seconds}s")
    print(_DIVIDER)

    # ── Main loop ─────────────────────────────────────────────────────────────
    try:
        while should_keep_running():
            try:
                if use_ws and stream.is_ready:
                    df_1m        = stream.get_dataframe(settings.interval)
                    df_5m        = stream.get_dataframe(settings.confirm_interval)
                    order_book   = stream.order_book()
                    latest_price = stream.latest_price()
                    if latest_price is None and len(df_1m):
                        latest_price = float(df_1m.iloc[-1]["close"])
                else:
                    df_1m, df_5m, order_book, latest_price = _fetch_rest(client)
                    if not use_ws and stream.is_ready:
                        use_ws       = True
                        loop_seconds = _WS_LOOP_SECONDS
                        print("[INFO] WebSocket recovered — switching to real-time mode")

                if latest_price is None:
                    if not controlled_sleep(loop_seconds):
                        break
                    continue

                # ── Manage open paper position ────────────────────────────────
                if broker.has_open_position():
                    exit_status = broker.check_exit(latest_price)
                    if exit_status and exit_status.get("ok"):
                        pnl = exit_status["net_pnl"]
                        risk.record_trade(pnl)
                        logger.log_trade(exit_status)
                        print(
                            f"CLOSED  pnl=${pnl:+.2f}  "
                            f"entry={exit_status.get('entry_price', '?')}  "
                            f"exit={exit_status.get('exit_price', '?')}  "
                            f"reason={exit_status.get('reason', '?')}"
                        )
                    else:
                        pos = exit_status or {}
                        print(
                            f"Holding LONG  price={latest_price:.2f}  "
                            f"TP={pos.get('take_profit_price', '?')}  "
                            f"SL={pos.get('stop_price', '?')}  "
                            f"pnl=${pos.get('net_pnl', 0):+.2f}"
                        )
                    if not controlled_sleep(loop_seconds):
                        break
                    continue

                # ── Circuit breaker ───────────────────────────────────────────
                cb = circuit_breaker.check(df_1m)
                if cb["halted"]:
                    print(
                        f"CIRCUIT BREAKER  {cb['reason']}  "
                        f"— resume in {cb['resume_in']}s"
                    )
                    logger.log_signal(
                        settings.symbol, "CB_HALT", 0, latest_price,
                        [cb["reason"], f"resume_in={cb['resume_in']}s"],
                    )
                    if not controlled_sleep(min(loop_seconds, 30)):
                        break
                    continue

                # ── Fundamental blocker ───────────────────────────────────────
                block = fundamentals.should_block_short(
                    settings.symbol,
                    use_fear_greed=settings.use_fear_greed_filter,
                    use_coingecko=settings.use_coingecko_filter,
                )
                if block["block"]:
                    print("BLOCKED:", block["reasons"])
                    logger.log_signal(settings.symbol, "BLOCKED", 0, latest_price, block["reasons"])
                    if not controlled_sleep(loop_seconds):
                        break
                    continue

                # ── Signal evaluation (preliminary at $100 notional) ──────────
                preliminary = signal_engine.evaluate(
                    df_1m=df_1m,
                    df_5m=df_5m,
                    order_book=order_book,
                    position_size_usd=100,
                )

                bd = preliminary.score_breakdown or {}
                print(
                    f"Signal: {preliminary.action:5s}  "
                    f"Score: {preliminary.score}/{preliminary.max_score}  "
                    f"({preliminary.confidence}%)  "
                    f"Price: {preliminary.entry_price:.2f}  "
                    f"[T:{bd.get('trend',0)} M:{bd.get('momentum',0)} "
                    f"S:{bd.get('structure',0)} V:{bd.get('volume',0)} "
                    f"P:{bd.get('pattern_mkst',0)}]"
                )

                logger.log_signal(
                    settings.symbol,
                    preliminary.action,
                    preliminary.score,
                    preliminary.entry_price,
                    preliminary.reasons,
                    signal=preliminary,
                )

                if preliminary.action != "BUY":
                    if not controlled_sleep(loop_seconds):
                        break
                    continue

                # ── Risk check ────────────────────────────────────────────────
                decision = risk.can_trade(
                    entry_price=preliminary.entry_price,
                    stop_price=preliminary.stop_price,
                    account_equity_usd=100,
                )
                if not decision.allow:
                    print("Risk rejected:", decision.reason)
                    if not controlled_sleep(loop_seconds):
                        break
                    continue

                # ── Final signal sized to actual notional ─────────────────────
                signal = signal_engine.evaluate(
                    df_1m=df_1m,
                    df_5m=df_5m,
                    order_book=order_book,
                    position_size_usd=decision.notional_usd,
                )
                logger.log_signal(
                    settings.symbol,
                    signal.action,
                    signal.score,
                    signal.entry_price,
                    [*signal.reasons, "Risk-sized final plan"],
                    signal=signal,
                )

                print(
                    f"OPEN LONG   entry={signal.entry_price:.4f}  "
                    f"TP={signal.take_profit_price:.4f}  "
                    f"SL={signal.stop_price:.4f}  "
                    f"target_net=${signal.target_net_profit_usd:.2f}  "
                    f"R/R={signal.risk_reward_ratio:.2f}"
                )

                result = broker.open_long(
                    symbol=settings.symbol,
                    entry_price=signal.entry_price,
                    quantity=decision.quantity,
                    notional_usd=decision.notional_usd,
                    stop_price=signal.stop_price,
                    take_profit_price=signal.take_profit_price,
                )
                print("Position opened:", result)

                if not controlled_sleep(loop_seconds):
                    break

            except KeyboardInterrupt:
                print("Stopped by user.")
                break
            except Exception as exc:
                print("ERROR:", repr(exc))
                if not controlled_sleep(settings.loop_seconds):
                    break
    finally:
        stream.stop()
        mark_bot_stopped()
        print("Bot stopped.")


if __name__ == "__main__":
    main()
