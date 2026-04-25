"""
Real-time Binance Futures WebSocket stream.

Subscribes to kline and bookTicker streams for configured intervals.
Seed the buffer with initial REST history, then start() to go live.
The main loop reads get_dataframe() instead of calling REST each tick.
"""

import json
import threading
import time

import numpy as np
import pandas as pd
import websocket
from collections import deque


class BinanceWSStream:
    # Binance Spot WebSocket endpoints (not Futures)
    WS_PROD = "wss://stream.binance.com:9443/stream"
    WS_TEST = "wss://testnet.binance.vision/stream"

    def __init__(self, symbol: str, intervals: list, testnet: bool = True, max_candles: int = 250):
        self.symbol = symbol.lower()
        self.intervals = intervals
        self.testnet = testnet

        self._lock = threading.Lock()
        self._candles: dict[str, deque] = {iv: deque(maxlen=max_candles) for iv in intervals}
        self._latest_price: float | None = None
        self._order_book: dict = {"bids": [], "asks": []}

        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = threading.Event()

    # ── URL ──────────────────────────────────────────────────────────────────

    def _ws_url(self) -> str:
        base = self.WS_TEST if self.testnet else self.WS_PROD
        parts = [f"{self.symbol}@kline_{iv}" for iv in self.intervals]
        parts.append(f"{self.symbol}@bookTicker")
        return f"{base}?streams=" + "/".join(parts)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_open(self, ws):
        self._connected.set()
        print("[WS] Connected to Binance stream")

    def _on_message(self, ws, raw: str):
        try:
            msg = json.loads(raw)
            stream = msg.get("stream", "")
            data = msg.get("data", {})
            if "@kline_" in stream:
                self._handle_kline(data)
            elif "@bookTicker" in stream:
                self._handle_book_ticker(data)
        except Exception as exc:
            print(f"[WS] Message parse error: {exc}")

    def _handle_kline(self, data: dict):
        k = data["k"]
        interval = k["i"]
        candle = {
            "open_time": pd.to_datetime(k["t"], unit="ms"),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
            "close_time": pd.to_datetime(k["T"], unit="ms"),
            "quote_volume": float(k["q"]),
            "trades": int(k["n"]),
            "taker_buy_base": float(k["V"]),
            "taker_buy_quote": float(k["Q"]),
            "_closed": bool(k["x"]),
        }
        with self._lock:
            self._latest_price = candle["close"]
            if interval not in self._candles:
                return
            buf = self._candles[interval]
            if buf and not buf[-1].get("_closed", True):
                buf[-1] = candle       # update in-place while candle is open
            else:
                buf.append(candle)

    def _handle_book_ticker(self, data: dict):
        with self._lock:
            self._order_book = {
                "bids": [[data["b"], data["B"]]],
                "asks": [[data["a"], data["A"]]],
            }

    def _on_error(self, ws, error):
        print(f"[WS] Error: {error}")

    def _on_close(self, ws, code, msg):
        self._connected.clear()
        print(f"[WS] Connection closed (code={code})")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _run_loop(self):
        """Background thread: connect and auto-reconnect on drops."""
        while self._running:
            url = self._ws_url()
            self._ws = websocket.WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self._ws.run_forever(ping_interval=20, ping_timeout=10)
            self._connected.clear()
            if self._running:
                print("[WS] Reconnecting in 3 s…")
                time.sleep(3)

    def seed(self, df_by_interval: dict):
        """Pre-fill candle buffers from REST history. Call before start()."""
        with self._lock:
            for iv, df in df_by_interval.items():
                if iv not in self._candles:
                    continue
                for _, row in df.iterrows():
                    c = row.to_dict()
                    c["_closed"] = True
                    self._candles[iv].append(c)
        print(f"[WS] Seeded buffers: { {iv: len(self._candles[iv]) for iv in self.intervals} }")

    def start(self, timeout: float = 12.0):
        """Launch background WebSocket thread and wait for connection."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="binance-ws")
        self._thread.start()
        connected = self._connected.wait(timeout=timeout)
        if not connected:
            print("[WS] Warning: connection timeout — will retry in background")

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()

    # ── Data access ──────────────────────────────────────────────────────────

    def get_dataframe(self, interval: str) -> pd.DataFrame:
        """Return closed candles as a DataFrame (live open candle excluded)."""
        with self._lock:
            rows = [c for c in self._candles[interval] if c.get("_closed", True)]
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).drop(columns=["_closed"], errors="ignore")
        return df.reset_index(drop=True)

    def latest_price(self) -> float | None:
        with self._lock:
            return self._latest_price

    def order_book(self) -> dict:
        with self._lock:
            return dict(self._order_book)

    @property
    def is_ready(self) -> bool:
        """True once all intervals have at least 55 closed candles."""
        with self._lock:
            return all(
                sum(1 for c in self._candles[iv] if c.get("_closed", True)) >= 55
                for iv in self.intervals
            )

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()
