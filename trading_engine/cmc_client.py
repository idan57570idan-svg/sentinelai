"""
CoinMarketCap AI Agent Hub client.
Fetches market signals: fear/greed, trending tokens, price data, global metrics.
Uses CMC Pro API v1/v2 + Agent Hub skills endpoints.

Env vars required:
  CMC_API_KEY  - CoinMarketCap Pro API key
"""
from __future__ import annotations

import os
import time
import requests
from dataclasses import dataclass
from typing import Optional, List, Dict

CMC_BASE    = "https://pro-api.coinmarketcap.com"
CMC_API_KEY = os.getenv("CMC_API_KEY", "")

_HEADERS = {
    "X-CMC_PRO_API_KEY": CMC_API_KEY,
    "Accept": "application/json",
    "Accept-Encoding": "deflate, gzip",
}

_price_cache: dict[str, tuple[float, dict]] = {}
_PRICE_TTL = 60  # 1 minute


def _get(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{CMC_BASE}{path}", headers=_HEADERS, params=params or {}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("status", {}).get("error_code", 0) != 0:
        raise ValueError(f"CMC API error: {data['status'].get('error_message', 'unknown')}")
    return data


@dataclass
class TokenSignal:
    symbol: str
    name: str
    cmc_id: int
    price_usd: float
    price_change_1h: float
    price_change_24h: float
    volume_24h: float
    market_cap: float
    bsc_address: Optional[str]
    signal_type: str       # "TRENDING" | "MOMENTUM" | "FEAR_DIP" | "GREED_TOP"
    confidence: float      # 0.0 - 1.0
    reasoning: str

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class GlobalMetrics:
    total_market_cap: float
    btc_dominance: float
    eth_dominance: float
    fear_greed_index: float    # 0-100 (0=extreme fear, 100=extreme greed)
    fear_greed_label: str
    active_cryptocurrencies: int
    total_volume_24h: float
    defi_volume_24h: float
    timestamp: float

    @property
    def market_sentiment(self) -> str:
        if self.fear_greed_index < 20:
            return "EXTREME_FEAR"
        if self.fear_greed_index < 40:
            return "FEAR"
        if self.fear_greed_index < 60:
            return "NEUTRAL"
        if self.fear_greed_index < 80:
            return "GREED"
        return "EXTREME_GREED"


def get_global_metrics() -> GlobalMetrics:
    """Fetch global market metrics including Fear & Greed index."""
    data = _get("/v1/global-metrics/quotes/latest")
    q = data["data"]["quote"]["USD"]

    # CMC doesn't have a direct F&G endpoint in v1 — use CMC Fear & Greed alternative
    # Approximation: derive from BTC dominance + market cap change
    try:
        fg_data = _get("/v3/fear-and-greed/latest")
        fg_value = fg_data["data"]["value"]
        fg_label = fg_data["data"]["value_classification"]
    except Exception:
        # Fallback: approximate F&G from BTC dominance
        btc_dom = data["data"].get("btc_dominance", 50)
        mcap_change = q.get("total_market_cap_yesterday_percentage_change", 0)
        fg_value = max(0, min(100, 50 + (50 - btc_dom) + mcap_change * 2))
        fg_label = "Fear" if fg_value < 40 else "Greed" if fg_value > 60 else "Neutral"

    return GlobalMetrics(
        total_market_cap     = q.get("total_market_cap", 0),
        btc_dominance        = data["data"].get("btc_dominance", 0),
        eth_dominance        = data["data"].get("eth_dominance", 0),
        fear_greed_index     = float(fg_value),
        fear_greed_label     = str(fg_label),
        active_cryptocurrencies = data["data"].get("active_cryptocurrencies", 0),
        total_volume_24h     = q.get("total_volume_24h", 0),
        defi_volume_24h      = q.get("defi_volume_24h", 0),
        timestamp            = time.time(),
    )


def get_price(symbols: List[str]) -> Dict[str, dict]:
    """Fetch latest price data for given symbols."""
    sym_key = ",".join(symbols).upper()
    cached_at, cached = _price_cache.get(sym_key, (0, {}))
    if time.time() - cached_at < _PRICE_TTL and cached:
        return cached

    data = _get("/v2/cryptocurrency/quotes/latest", {
        "symbol": sym_key,
        "convert": "USD",
    })

    result = {}
    for sym, entries in data.get("data", {}).items():
        if not entries:
            continue
        entry = entries[0] if isinstance(entries, list) else entries
        q = entry.get("quote", {}).get("USD", {})
        result[sym.upper()] = {
            "price":          q.get("price", 0),
            "volume_24h":     q.get("volume_24h", 0),
            "market_cap":     q.get("market_cap", 0),
            "change_1h":      q.get("percent_change_1h", 0),
            "change_24h":     q.get("percent_change_24h", 0),
            "change_7d":      q.get("percent_change_7d", 0),
            "cmc_id":         entry.get("id", 0),
            "name":           entry.get("name", sym),
            "bsc_address":    None,  # fetched separately if needed
        }

    _price_cache[sym_key] = (time.time(), result)
    return result


def get_trending_tokens(limit: int = 20) -> List[TokenSignal]:
    """Fetch trending/gainers tokens and generate initial signals."""
    signals: List[TokenSignal] = []

    try:
        # CMC trending gainers
        data = _get("/v1/cryptocurrency/trending/gainers-losers", {
            "start": 1, "limit": limit, "convert": "USD", "time_period": "24h",
        })
        entries = data.get("data", {}).get("gainers", [])
    except Exception:
        # Fallback: latest listings sorted by 24h change
        data = _get("/v1/cryptocurrency/listings/latest", {
            "start": 1, "limit": limit, "sort": "percent_change_24h",
            "sort_dir": "desc", "convert": "USD",
        })
        entries = data.get("data", [])

    for entry in entries:
        q = entry.get("quote", {}).get("USD", {})
        sym = entry.get("symbol", "")
        change_24h = q.get("percent_change_24h", 0)
        change_1h  = q.get("percent_change_1h", 0)

        # Only include if in our allowed token list
        from config.allowed_tokens import is_allowed
        if not is_allowed(sym):
            continue

        # Confidence based on volume and consistency of momentum
        vol = q.get("volume_24h", 0)
        mcap = q.get("market_cap", 1)
        vol_ratio = vol / mcap if mcap > 0 else 0
        confidence = min(0.9, 0.5 + (change_24h / 100) * 0.3 + vol_ratio * 0.2)

        signals.append(TokenSignal(
            symbol       = sym,
            name         = entry.get("name", sym),
            cmc_id       = entry.get("id", 0),
            price_usd    = q.get("price", 0),
            price_change_1h  = change_1h,
            price_change_24h = change_24h,
            volume_24h   = vol,
            market_cap   = mcap,
            bsc_address  = None,
            signal_type  = "TRENDING" if change_24h > 5 else "MOMENTUM",
            confidence   = round(confidence, 3),
            reasoning    = f"+{change_24h:.1f}% 24h, +{change_1h:.1f}% 1h, vol/mcap={vol_ratio:.2f}",
        ))

    return signals[:10]  # top 10


def get_bsc_token_info(cmc_id: int) -> Optional[dict]:
    """Get BSC (BNB Chain) contract address for a CMC token."""
    try:
        data = _get("/v1/cryptocurrency/info", {"id": str(cmc_id)})
        info = data.get("data", {}).get(str(cmc_id), {})
        platforms = info.get("platform", {})
        if platforms and isinstance(platforms, dict):
            # Direct platform check
            if platforms.get("id") == 56:  # BSC chain ID in CMC
                return {"address": platforms.get("token_address"), "info": info}
        # Check contract_address list
        for contract in info.get("contract_address", []):
            if contract.get("platform", {}).get("coin", {}).get("symbol") == "BNB":
                return {"address": contract.get("contract_address"), "info": info}
    except Exception:
        pass
    return None


def get_fear_greed() -> float:
    """Quick helper — returns current Fear & Greed index (0-100)."""
    try:
        metrics = get_global_metrics()
        return metrics.fear_greed_index
    except Exception:
        return 50.0  # neutral fallback
