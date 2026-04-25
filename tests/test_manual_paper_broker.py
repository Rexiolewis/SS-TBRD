import tempfile
import unittest

from execution.manual_paper_broker import ManualPaperBroker


class ManualPaperBrokerTests(unittest.TestCase):
    def test_manual_long_trade_persists_and_closes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            broker = ManualPaperBroker(log_dir=temp_dir, fee_rate=0.0005)
            opened = broker.open_position("BTCUSDT", "LONG", 100.0, 50.0)

            self.assertTrue(opened["ok"])
            self.assertTrue(broker.has_open_position())

            status = broker.mark_to_market(101.0)
            self.assertGreater(status["gross_pnl"], 0)

            closed = broker.close_position(101.0)
            self.assertTrue(closed["ok"])
            self.assertFalse(broker.has_open_position())

    def test_manual_short_trade_profit_when_price_falls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            broker = ManualPaperBroker(log_dir=temp_dir, fee_rate=0.0005)
            broker.open_position("BTCUSDT", "SHORT", 100.0, 50.0)
            status = broker.mark_to_market(99.0)

            self.assertGreater(status["gross_pnl"], 0)


if __name__ == "__main__":
    unittest.main()
