import unittest

from strategy.prediction_calculator import calculate_short_trade_plan


class PredictionCalculatorTests(unittest.TestCase):
    def test_short_take_profit_targets_net_profit_after_fees(self):
        plan = calculate_short_trade_plan(
            entry_price=100.0,
            stop_price=102.0,
            notional_usd=100.0,
            target_net_profit_usd=1.0,
            fee_rate=0.0005,
        )

        self.assertLess(plan.take_profit_price, plan.entry_price)
        self.assertAlmostEqual(plan.estimated_net_profit_usd, 1.0, places=6)
        self.assertGreater(plan.estimated_gross_profit_usd, plan.estimated_net_profit_usd)
        self.assertGreater(plan.estimated_stop_loss_usd, 0)

    def test_rejects_invalid_short_stop(self):
        with self.assertRaises(ValueError):
            calculate_short_trade_plan(
                entry_price=100.0,
                stop_price=99.0,
                notional_usd=100.0,
                target_net_profit_usd=1.0,
            )


if __name__ == "__main__":
    unittest.main()
