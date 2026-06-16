"""
ExecutionAgent — claude-haiku-4-5-20251001
Translates an approved, risk-sized trade into TWAK commands and executes.
Uses Haiku for speed — at execution time, the hard decisions are already made.

Responsibilities:
- Validate the final decision one more time (sanity check)
- Calculate optimal slippage based on token liquidity
- Call TWAK to execute the swap
- Record the trade in portfolio state
- Return execution receipt
"""
from __future__ import annotations

import json
import time
from typing import Optional
import anthropic

from trading_engine.twak_client import execute_swap, SwapResult
from trading_engine.portfolio import Portfolio, TradeRecord

MODEL = "claude-haiku-4-5-20251001"

_client = anthropic.Anthropic()

_SYSTEM = """You are ExecutionAgent, the final execution layer of a BNB Chain trading bot.
You receive a fully approved, risk-checked trade. Your job: compute execution parameters.

Output ONLY this JSON (no prose):
{
  "execute": true | false,
  "from_token": "USDT",
  "to_token": "CAKE",
  "amount_usd": 50.0,
  "slippage_pct": 0.5,
  "execution_notes": "one-line note"
}

Slippage guidelines:
- Large cap (ETH, LINK, CAKE volume>$10M): 0.3-0.5%
- Mid cap (volume $1M-$10M): 0.5-1.0%
- Small cap (volume <$1M): 1.0-1.5%
- Do NOT exceed 1.5% slippage

For SELL: from_token = position symbol, to_token = USDT
For BUY:  from_token = USDT, to_token = target symbol

Set execute=false ONLY if amount_usd < $1 or obviously invalid input."""


def execute_trade(
    approved_decision: dict,
    signal: dict,
    security_verdict: dict,
    portfolio: Portfolio,
    dry_run: bool = False,
) -> dict:
    """
    Execute an approved trade via TWAK.

    approved_decision: from risk_guard.evaluate_trade()
    signal: from market_intel.generate_signals()
    dry_run: simulate only, don't send transaction
    """
    if not approved_decision.get("approved", False):
        return {"executed": False, "reason": "Trade not approved by RiskGuard"}

    amount = float(approved_decision.get("final_amount_usd", 0))
    if amount < 1.0:
        return {"executed": False, "reason": f"Amount too small: ${amount:.2f}"}

    direction = signal.get("direction", "BUY").upper()
    symbol    = signal.get("symbol", "").upper()

    # Build execution params via Haiku (fast)
    context = {
        "direction":     direction,
        "symbol":        symbol,
        "amount_usd":    amount,
        "volume_24h":    security_verdict.get("static_verdict", {}).get("findings_summary", {}),
        "risk_level":    security_verdict.get("risk_level", "MEDIUM"),
    }

    response = _client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Execute this trade:\n{json.dumps(context)}\n\nOutput JSON only.",
        }],
    )

    raw_text = response.content[0].text if response.content else "{}"
    try:
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        exec_params = json.loads(raw_text[start:end])
    except (json.JSONDecodeError, ValueError):
        exec_params = {
            "execute":     True,
            "from_token":  "USDT" if direction == "BUY" else symbol,
            "to_token":    symbol if direction == "BUY" else "USDT",
            "amount_usd":  amount,
            "slippage_pct": 0.8,
            "execution_notes": "fallback params",
        }

    if not exec_params.get("execute", True):
        return {"executed": False, "reason": exec_params.get("execution_notes", "agent declined")}

    slippage = float(exec_params.get("slippage_pct", 0.8))
    slippage = min(1.5, max(0.1, slippage))  # hard cap

    # Execute via TWAK
    result: SwapResult = execute_swap(
        from_symbol = exec_params.get("from_token", "USDT"),
        to_symbol   = exec_params.get("to_token", symbol),
        amount_usd  = amount,
        slippage_pct = slippage,
        dry_run     = dry_run,
    )

    # Record trade
    trade_record = TradeRecord(
        symbol    = symbol,
        direction = direction,
        amount_usd = amount,
        price_usd  = 0.0,  # filled from result
        tx_hash   = result.tx_hash,
        fee_usd   = result.fee_usd,
        timestamp = time.time(),
        pnl_usd   = 0.0,
    )
    portfolio.record_trade(trade_record)

    return {
        "executed":      result.success,
        "tx_hash":       result.tx_hash,
        "symbol":        symbol,
        "direction":     direction,
        "amount_usd":    amount,
        "amount_out":    result.amount_out,
        "fee_usd":       result.fee_usd,
        "slippage_pct":  slippage,
        "dry_run":       dry_run,
        "error":         result.error,
        "execution_notes": exec_params.get("execution_notes", ""),
    }
