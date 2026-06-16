"""
RiskGuardAgent — claude-sonnet-4-6
Portfolio risk management and position sizing.
Receives the proposed trade + portfolio state and enforces guardrails,
then uses Sonnet to produce nuanced position sizing recommendations.

Separate model from MarketIntel to ensure independence of analysis.
"""
from __future__ import annotations

import json
from typing import Optional
import anthropic

from trading_engine.guardrails import (
    check_trade, GuardrailConfig, TradeProposal,
    PortfolioState, GuardrailDecision,
)

MODEL = "claude-sonnet-4-6"

_client = anthropic.Anthropic()

_SYSTEM = """You are RiskGuardAgent, an autonomous trading risk manager for a BNB Chain trading agent.
You enforce strict portfolio risk rules to protect capital and maximize competition PnL.

You receive: a proposed trade, portfolio state, security verdict, and market conditions.
You output a final position sizing decision in JSON.

Output format (ONLY JSON):
{
  "approved": true | false,
  "final_amount_usd": 0.0,
  "position_pct": 0.0,
  "rejection_reason": null | "string",
  "risk_notes": ["list of active risk factors"],
  "suggested_stop_loss_pct": 5.0,
  "suggested_take_profit_pct": 10.0
}

Hard rules (ALWAYS enforce regardless of other factors):
1. Max portfolio drawdown 25% -> reject ALL buys
2. Daily loss > 8% -> reject ALL buys for the day
3. Honeypot score > 30 -> reject
4. Per-trade max 5% of portfolio
5. Never bet more than $500 on a single trade in competition
6. Absolute minimum trade: $5

Portfolio management philosophy:
- Favor high-confidence, high-volume, audited contracts
- Scale down in volatile conditions (Fear < 20 or Greed > 80)
- Scale up on strong momentum confirmed by volume
- Kelly criterion approximation: bet_pct = (edge * confidence) / risk"""


def evaluate_trade(
    proposal: TradeProposal,
    portfolio: PortfolioState,
    security_verdict: dict,
    market_conditions: dict,
    config: Optional[GuardrailConfig] = None,
) -> dict:
    """
    Two-pass evaluation:
    1. Deterministic guardrails check (fast, hard blocks)
    2. Sonnet qualitative risk assessment (nuanced sizing)
    """
    # Pass 1: deterministic guardrails
    hard_check: GuardrailDecision = check_trade(proposal, portfolio, config)

    if not hard_check.approved:
        return {
            "approved": False,
            "final_amount_usd": 0.0,
            "position_pct": 0.0,
            "rejection_reason": hard_check.rejection_reason,
            "risk_notes": hard_check.warnings,
            "suggested_stop_loss_pct": 5.0,
            "suggested_take_profit_pct": 10.0,
            "pass": "guardrails_hard_block",
        }

    # Pass 2: LLM qualitative sizing
    context = {
        "proposal": {
            "symbol":          proposal.symbol,
            "direction":       proposal.direction,
            "requested_usd":   proposal.amount_usd,
            "guardrail_adj":   hard_check.adjusted_amount_usd,
            "confidence":      proposal.confidence,
            "reasoning":       proposal.reasoning,
        },
        "portfolio": {
            "total_value_usd":   portfolio.total_value_usd,
            "drawdown_pct":      portfolio.drawdown_pct,
            "daily_pnl_pct":    portfolio.daily_pnl_pct,
            "open_positions":    portfolio.open_positions,
            "trade_count_today": portfolio.trade_count_today,
        },
        "security": {
            "verdict":        security_verdict.get("verdict"),
            "honeypot_score": security_verdict.get("honeypot_score"),
            "top_risks":      security_verdict.get("top_risks", []),
        },
        "market": market_conditions,
        "guardrail_warnings": hard_check.warnings,
    }

    response = _client.messages.create(
        model=MODEL,
        max_tokens=512,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"Evaluate this trade:\n{json.dumps(context, indent=2)}\n\nOutput your decision as JSON.",
        }],
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text = block.text
            break

    try:
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        llm_decision = json.loads(raw_text[start:end])
    except (json.JSONDecodeError, ValueError):
        # Fall back to guardrails decision
        llm_decision = {
            "approved": hard_check.approved,
            "final_amount_usd": hard_check.adjusted_amount_usd,
            "position_pct": hard_check.position_pct,
            "rejection_reason": None,
            "risk_notes": hard_check.warnings,
            "suggested_stop_loss_pct": 5.0,
            "suggested_take_profit_pct": 10.0,
        }

    # Guardrails are always the ceiling — LLM can only reduce, not increase beyond hard cap
    llm_amount = float(llm_decision.get("final_amount_usd", hard_check.adjusted_amount_usd))
    final_amount = min(llm_amount, hard_check.adjusted_amount_usd)
    final_amount = max(0.0, final_amount)

    llm_decision["final_amount_usd"] = round(final_amount, 2)
    llm_decision["position_pct"] = round(
        (final_amount / portfolio.total_value_usd * 100) if portfolio.total_value_usd > 0 else 0, 2
    )
    llm_decision["pass"] = "llm_evaluated"
    return llm_decision
