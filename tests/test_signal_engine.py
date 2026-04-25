import unittest

import pandas as pd

from strategy.signal_engine import ShortSignalEngine


def bearish_candles(rows=80):
    records = []
    price = 1000.0
    for i in range(rows):
        close = price - (i * 2.0)
        if i == rows - 1:
            close -= 8.0
        open_price = close + 1.5
        high = open_price + 2.0
        low = close - 1.0
        volume = 500.0 if i == rows - 1 else 100.0
        records.append(
            {
                "open_time": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "close_time": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i + 1),
                "quote_volume": volume * close,
                "trades": 100,
                "taker_buy_base": volume / 2,
                "taker_buy_quote": volume * close / 2,
            }
        )
    return pd.DataFrame(records)


class SignalEngineTests(unittest.TestCase):
    def test_bearish_setup_returns_short_with_trade_plan(self):
        engine = ShortSignalEngine(min_score=8, target_profit_usd=1.0, fee_rate=0.0005)
        order_book = {
            "bids": [["840", "1"] for _ in range(10)],
            "asks": [["841", "2"] for _ in range(10)],
        }

        result = engine.evaluate(
            df_1m=bearish_candles(),
            df_5m=bearish_candles(),
            order_book=order_book,
            position_size_usd=100.0,
        )

        self.assertEqual(result.action, "SHORT")
        self.assertGreaterEqual(result.score, 8)
        self.assertLess(result.take_profit_price, result.entry_price)
        self.assertGreater(result.stop_price, result.entry_price)
        self.assertAlmostEqual(result.estimated_net_profit_usd, 1.0, places=6)
        self.assertGreater(result.confidence, 0)

    def test_waits_when_there_is_not_enough_data(self):
        engine = ShortSignalEngine()
        result = engine.evaluate(bearish_candles(rows=20), bearish_candles(rows=20))

        self.assertEqual(result.action, "WAIT")
        self.assertIn("Not enough candle data", result.reasons)


if __name__ == "__main__":
    unittest.main()
