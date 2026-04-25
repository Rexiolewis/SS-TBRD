import unittest

import pandas as pd

from strategy.backtester import run_short_backtest
from strategy.signal_engine import ShortSignalEngine


def candles(rows=140):
    records = []
    base_time = pd.Timestamp("2026-01-01")
    for i in range(rows):
        close = 1000 - i
        if i in (80, 111):
            close -= 15
        open_price = close + 1
        records.append(
            {
                "open_time": base_time + pd.Timedelta(minutes=i),
                "open": open_price,
                "high": open_price + 2,
                "low": close - 2,
                "close": close,
                "volume": 500 if i in (80, 111) else 100,
                "close_time": base_time + pd.Timedelta(minutes=i + 1),
                "quote_volume": close * 100,
                "trades": 100,
                "taker_buy_base": 50,
                "taker_buy_quote": close * 50,
            }
        )
    return pd.DataFrame(records)


class BacktesterTests(unittest.TestCase):
    def test_backtest_returns_summary(self):
        engine = ShortSignalEngine(min_score=7, target_profit_usd=1.0)
        summary = run_short_backtest(
            df_1m=candles(),
            df_5m=candles(),
            signal_engine=engine,
            symbol="BTCUSDT",
            starting_equity=100.0,
            max_hold_candles=20,
        )

        self.assertGreaterEqual(summary.total_trades, 0)
        self.assertGreaterEqual(summary.ending_equity, 0)
        self.assertGreaterEqual(summary.max_drawdown, 0)


if __name__ == "__main__":
    unittest.main()
