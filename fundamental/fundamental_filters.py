import requests

class FundamentalFilters:
    def __init__(self):
        self.session = requests.Session()

    def fear_greed(self):
        try:
            url = "https://api.alternative.me/fng/"
            data = self.session.get(url, timeout=10).json()
            item = data["data"][0]
            return {
                "value": int(item["value"]),
                "classification": item["value_classification"]
            }
        except Exception as exc:
            return {"value": None, "classification": "unknown", "error": str(exc)}

    def coingecko_market(self, coin_id="bitcoin"):
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                "vs_currency": "usd",
                "ids": coin_id,
                "price_change_percentage": "1h,24h"
            }
            data = self.session.get(url, params=params, timeout=10).json()
            if not data:
                return {"ok": False, "reason": "No CoinGecko data"}
            item = data[0]
            return {
                "ok": True,
                "price_change_24h": item.get("price_change_percentage_24h"),
                "total_volume": item.get("total_volume"),
                "market_cap": item.get("market_cap")
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def should_block_short(self, symbol: str, use_fear_greed=True, use_coingecko=True):
        reasons = []

        if use_fear_greed:
            fg = self.fear_greed()
            value = fg.get("value")
            # Block shorts in very fearful markets because price may be oversold and bounce sharply.
            if value is not None and value < 20:
                reasons.append(f"Extreme fear detected ({value}), avoid late short.")
            # Very greedy markets are not a blocker for shorts, but still risky.

        if use_coingecko:
            coin_id = "bitcoin" if symbol.upper().startswith("BTC") else "ethereum" if symbol.upper().startswith("ETH") else None
            if coin_id:
                market = self.coingecko_market(coin_id)
                change = market.get("price_change_24h")
                if change is not None and change > 4:
                    reasons.append(f"Strong 24h positive move ({change:.2f}%), avoid shorting momentum pump.")

        return {
            "block": len(reasons) > 0,
            "reasons": reasons
        }
