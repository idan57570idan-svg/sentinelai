"""
MarketIntelAgent — claude-sonnet-4-6
Analyzes CMC data and generates structured trading signals.
Returns a ranked list of trade opportunities with confidence scores.
"""
from __future__ import annotations

import json
from typing import List
import anthropic

from trading_engine.cmc_client import GlobalMetrics, TokenSignal

MODEL = "claude-sonnet-4-6"

_client = anthropic.Anthropic()

_SYSTEM = """You are MarketIntelAgent, a crypto market analyst specialized in BNB Chain trading.
You receive live CoinMarketCap data: global metrics, fear/greed index, and trending tokens on BSC.
Your job: analyze the data and output a JSON array of trade signals.

ALLOWED tokens only: you must ONLY recommend tokens from the provided allowed_symbols list.
STABLECOINS: never recommend buying stablecoins (USDT, USDC, DAI, BUSD etc.) — use them as base only.

Each signal must have:
{
  "symbol": "TOKEN",
  "direction": "BUY" | "SELL",
  "confidence": 0.0-1.0,
  "strategy": "MOMENTUM" | "FEAR_DIP" | "MEAN_REVERSION" | "BREAKOUT" | "SENTIMENT",
  "reasoning": "one sentence",
  "hold_hours": 2-48,
  "risk_level": "LOW" | "MEDIUM" | "HIGH"
}

RULES:
- Fear < 30: prefer safe large-caps (ETH, LINK, CAKE), smaller positions
- Fear < 20 (extreme fear): DIP BUY opportunities on blue-chips with confidence 0.7+
- Greed > 70: be cautious, reduce sizes, look for SELL signals on recent runners
- Greed > 85: near peak — mostly SELL or hold cash
- Only BUY tokens with 24h volume > $1M
- Never output more than 5 signals
- Rank by confidence DESC
- Output ONLY valid JSON array, no prose"""


def generate_signals(
    metrics: GlobalMetrics,
    trending: List[TokenSignal],
    allowed_symbols: set,
    current_positions: dict,
) -> List[dict]:
    """
    Call claude-sonnet-4-6 to analyze market data and return trade signals.
    Returns list of signal dicts, sorted by confidence DESC.
    """
    # Build context payload
    trending_data = []
    for t in trending:
        if t.symbol in allowed_symbols:
            trending_data.append({
                "symbol": t.symbol,
                "price_change_1h":  round(t.price_change_1h, 2),
                "price_change_24h": round(t.price_change_24h, 2),
                "volume_24h_usd":   round(t.volume_24h, 0),
                "confidence_raw":   t.confidence,
            })

    user_msg = f"""LIVE MARKET DATA — {__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

GLOBAL METRICS:
- Fear & Greed Index: {metrics.fear_greed_index:.0f}/100 ({metrics.fear_greed_label}) — {metrics.market_sentiment}
- Total Market Cap: ${metrics.total_market_cap / 1e9:.1f}B
- 24h Volume: ${metrics.total_volume_24h / 1e9:.1f}B
- BTC Dominance: {metrics.btc_dominance:.1f}%

TRENDING TOKENS (BNB Chain eligible):
{json.dumps(trending_data, indent=2)}

CURRENT OPEN POSITIONS: {list(current_positions.keys()) if current_positions else 'None'}
ALLOWED SYMBOLS (sample): {', '.join(list(allowed_symbols)[:30])}...

Generate 3-5 trade signals as JSON array."""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text = block.text
            break

    # Extract JSON array
    try:
        start = raw_text.find("[")
        end   = raw_text.rfind("]") + 1
        if start >= 0 and end > start:
            signals = json.loads(raw_text[start:end])
            # Filter to allowed symbols only, sort by confidence
            valid = [
                s for s in signals
                if s.get("symbol", "").upper() in allowed_symbols
            ]
            valid.sort(key=lambda x: x.get("confidence", 0), reverse=True)
            return valid[:5]
    except (json.JSONDecodeError, ValueError):
        pass
    return []
