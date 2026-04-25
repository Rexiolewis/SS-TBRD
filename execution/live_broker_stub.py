"""
Live broker stub for Binance Spot trading.

Disabled by default — set ENABLE_LIVE_TRADING=true in .env only after
thorough paper testing. Spot trades: BUY to enter, SELL to exit.
No leverage, no reduce_only, no shorts.
"""


class LiveBroker:
    def __init__(self, client, enable_live_trading: bool = False):
        self.client = client
        self.enable_live_trading = enable_live_trading

    def _guard(self):
        if not self.enable_live_trading:
            raise RuntimeError(
                "Live trading is disabled. "
                "Set ENABLE_LIVE_TRADING=true in .env only after paper testing."
            )

    def open_long(self, symbol: str, quantity: float) -> dict:
        """Place a market BUY order to open a spot long position."""
        self._guard()
        return self.client.place_market_buy(symbol=symbol, quantity=quantity)

    def close_long(self, symbol: str, quantity: float) -> dict:
        """Place a market SELL order to close the spot long position."""
        self._guard()
        return self.client.place_market_sell(symbol=symbol, quantity=quantity)
