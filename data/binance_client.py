"""
Binance Spot REST API client.

Spot trading means no leverage, no short-selling, no reduce_only.
You BUY to enter a long position and SELL to exit it.
All private endpoints (orders, balances) require API key + secret
generated at testnet.binance.vision (testnet) or binance.com (live).
"""

import hmac
import hashlib
import time
from urllib.parse import urlencode

import pandas as pd
import requests


class BinanceSpotClient:
    BASE_PROD = "https://api.binance.com"
    BASE_TEST = "https://testnet.binance.vision"

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = self.BASE_TEST if testnet else self.BASE_PROD

    # ── Auth helpers ──────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self.api_key}

    def _sign(self, params: dict) -> dict:
        query = urlencode(params)
        sig = hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def public_get(self, path: str, params: dict | None = None) -> dict | list:
        resp = requests.get(self.base_url + path, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def private_request(self, method: str, path: str, params: dict | None = None):
        if not self.api_key or not self.api_secret:
            raise ValueError("Binance API key and secret are required for private endpoints.")
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        signed = self._sign(params)
        resp = requests.request(
            method=method,
            url=self.base_url + path,
            params=signed,
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Market data (public) ──────────────────────────────────────────────────

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 150) -> pd.DataFrame:
        raw = self.public_get("/api/v3/klines", {
            "symbol": symbol, "interval": interval, "limit": limit
        })
        columns = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ]
        df = pd.DataFrame(raw, columns=columns)
        for col in ["open", "high", "low", "close", "volume",
                    "quote_volume", "taker_buy_base", "taker_buy_quote"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["open_time"]  = pd.to_datetime(df["open_time"],  unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        return df

    def get_ticker_24h(self, symbol: str) -> dict:
        return self.public_get("/api/v3/ticker/24hr", {"symbol": symbol})

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self.public_get("/api/v3/depth", {"symbol": symbol, "limit": limit})

    # ── Account (private) ─────────────────────────────────────────────────────

    def get_account(self) -> dict:
        return self.private_request("GET", "/api/v3/account")

    def get_balance(self, asset: str = "USDT") -> float:
        """Return free (available) balance for the given asset."""
        account = self.get_account()
        for bal in account.get("balances", []):
            if bal["asset"] == asset:
                return float(bal["free"])
        return 0.0

    def get_asset_balance(self, asset: str = "USDT") -> dict:
        """Return free, locked, and total balance for the given asset."""
        account = self.get_account()
        asset = asset.upper()
        for bal in account.get("balances", []):
            if bal["asset"] == asset:
                free = float(bal["free"])
                locked = float(bal["locked"])
                return {
                    "asset": asset,
                    "free": free,
                    "locked": locked,
                    "total": free + locked,
                }
        return {"asset": asset, "free": 0.0, "locked": 0.0, "total": 0.0}

    # ── Orders (private) ─────────────────────────────────────────────────────

    def place_market_buy(self, symbol: str, quantity: float) -> dict:
        """Open a long position — spend USDT to buy crypto."""
        return self.private_request("POST", "/api/v3/order", {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": quantity,
        })

    def place_market_sell(self, symbol: str, quantity: float) -> dict:
        """Close a long position — sell crypto back to USDT."""
        return self.private_request("POST", "/api/v3/order", {
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "quantity": quantity,
        })

    def get_open_orders(self, symbol: str) -> list:
        return self.private_request("GET", "/api/v3/openOrders", {"symbol": symbol})


# Back-compat alias so older imports still work during migration
BinanceFuturesClient = BinanceSpotClient
