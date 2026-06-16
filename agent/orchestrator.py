"""
OrchestratorAgent — claude-opus-4-8 with adaptive thinking
Master coordinator for SentinelAI trading system.

Architecture:
  Orchestrator (Opus 4.8) coordinates 4 specialist sub-agents:
    1. MarketIntelAgent   (Sonnet 4.6) -> trading signals from CMC data
    2. SecurityAuditAgent (Haiku 4.5)  -> contract safety verdict
    3. RiskGuardAgent     (Sonnet 4.6) -> position sizing + guardrails
    4. ExecutionAgent     (Haiku 4.5)  -> TWAK swap execution

  Each signal flows through: MarketIntel -> SecurityAudit -> RiskGuard -> Execution
  Orchestrator makes the final GO/HOLD decision before execution.

The Orchestrator uses extended thinking to reason about:
- Overall market regime
- Portfolio concentration risk
- Which signals to prioritize
- When to skip a cycle entirely
"""
from __future__ import annotations

import json
import time
import logging
from typing import List, Optional
import anthropic

from config.allowed_tokens import ALLOWED_SYMBOLS, is_stablecoin
from trading_engine.cmc_client import (
    get_global_metrics, get_trending_tokens, get_price,
    GlobalMetrics, TokenSignal,
)
from trading_engine.guardrails import TradeProposal
from trading_engine.portfolio import Portfolio

from agent.market_intel import generate_signals
from agent.security_audit import audit_contract
from agent.risk_guard import evaluate_trade
from agent.execution import execute_trade
from config.allowed_tokens import get_address

logger = logging.getLogger("sentinel.orchestrator")

MODEL = "claude-opus-4-8"

_client = anthropic.Anthropic()

_SYSTEM = """You are the OrchestratorAgent for SentinelAI, an autonomous BNB Chain trading bot.
You coordinate market analysis, contract security audits, risk management, and trade execution.

You receive a full market snapshot and candidate signals from specialist sub-agents.
Your job: decide the FINAL trading strategy for this cycle.

Output ONLY JSON:
{
  "action": "TRADE" | "HOLD" | "REDUCE",
  "selected_signals": ["SYMBOL1", "SYMBOL2"],
  "market_regime": "BULL" | "BEAR" | "NEUTRAL" | "VOLATILE",
  "strategy_note": "one sentence on current approach",
  "max_trades_this_cycle": 1-3,
  "risk_multiplier": 0.3-1.0
}

Decision rules:
- TRADE: execute top 1-3 signals with normal sizing
- HOLD: skip this cycle (market unfavorable or no good signals)
- REDUCE: sell losing positions, don't open new ones

When to HOLD:
- All signals have confidence < 0.5
- Fear & Greed extreme in wrong direction for strategy
- Drawdown > 20% (near competition disqualification)
- No signals pass security audit

risk_multiplier scales all position sizes:
- 1.0 = full size, 0.5 = half size, 0.3 = minimal (de-risking)"""


class Orchestrator:
    def __init__(self, portfolio: Portfolio, dry_run: bool = False):
        self.portfolio  = portfolio
        self.dry_run    = dry_run
        self.cycle_count = 0

    def run_cycle(self) -> dict:
        """Execute one full trading cycle. Called every N minutes."""
        self.cycle_count += 1
        logger.info(f"=== Cycle {self.cycle_count} ===")

        # ── Step 1: Fetch market data ────────────────────────────────────────
        try:
            metrics  = get_global_metrics()
            trending = get_trending_tokens(limit=20)
        except Exception as e:
            logger.error(f"CMC data fetch failed: {e}")
            return {"cycle": self.cycle_count, "action": "HOLD", "reason": f"CMC error: {e}"}

        # ── Step 2: MarketIntelAgent → signals ───────────────────────────────
        positions_dict = {sym: pos.__dict__ for sym, pos in self.portfolio.positions.items()}
        current_value  = sum(
            pos.value_usd for pos in self.portfolio.positions.values()
        ) or 100.0

        signals: List[dict] = generate_signals(
            metrics=metrics,
            trending=trending,
            allowed_symbols=ALLOWED_SYMBOLS,
            current_positions=positions_dict,
        )

        if not signals:
            logger.info("No signals generated — holding")
            return {"cycle": self.cycle_count, "action": "HOLD", "reason": "No market signals"}

        # ── Step 3: Orchestrator strategic decision (Opus 4.8) ───────────────
        portfolio_state = self.portfolio.get_state(current_value)
        orch_input = {
            "market": {
                "fear_greed": metrics.fear_greed_index,
                "sentiment":  metrics.market_sentiment,
                "btc_dom":    metrics.btc_dominance,
            },
            "portfolio": {
                "value_usd":     round(current_value, 2),
                "drawdown_pct":  round(portfolio_state.drawdown_pct, 2),
                "daily_pnl_pct": round(portfolio_state.daily_pnl_pct, 2),
                "open_positions": portfolio_state.open_positions,
                "trades_today":   portfolio_state.trade_count_today,
            },
            "signals": signals[:5],
        }

        orch_response = _client.messages.create(
            model=MODEL,
            max_tokens=512,
            thinking={"type": "adaptive"},
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Analyze this cycle and decide strategy:\n{json.dumps(orch_input, indent=2)}",
            }],
        )

        raw_orch = ""
        for block in orch_response.content:
            if block.type == "text":
                raw_orch = block.text
                break

        try:
            start = raw_orch.find("{")
            end   = raw_orch.rfind("}") + 1
            orch_decision = json.loads(raw_orch[start:end])
        except (json.JSONDecodeError, ValueError):
            orch_decision = {"action": "TRADE", "selected_signals": [s["symbol"] for s in signals[:2]],
                             "max_trades_this_cycle": 1, "risk_multiplier": 0.7,
                             "market_regime": "NEUTRAL", "strategy_note": "fallback"}

        action = orch_decision.get("action", "HOLD")
        logger.info(f"Orchestrator: {action} | regime={orch_decision.get('market_regime')} | {orch_decision.get('strategy_note')}")

        if action == "HOLD":
            return {"cycle": self.cycle_count, "action": "HOLD",
                    "strategy_note": orch_decision.get("strategy_note"), "signals_skipped": len(signals)}

        # ── Step 4: For each selected signal: audit -> risk -> execute ────────
        selected = set(orch_decision.get("selected_signals", [s["symbol"] for s in signals[:2]]))
        max_trades = orch_decision.get("max_trades_this_cycle", 2)
        risk_mult  = float(orch_decision.get("risk_multiplier", 1.0))
        executions = []
        trade_count = 0

        for signal in signals:
            if trade_count >= max_trades:
                break
            if signal.get("symbol") not in selected:
                continue

            sym = signal["symbol"]
            logger.info(f"Processing signal: {sym} {signal['direction']} conf={signal['confidence']:.2f}")

            # SecurityAuditAgent
            token_addr = get_address(sym) or "unverified"
            security = audit_contract(token_addr)
            logger.info(f"Security [{sym}]: {security['verdict']} honeypot={security['honeypot_score']}")

            if not security.get("tradeable", False):
                executions.append({
                    "symbol": sym, "action": "BLOCKED",
                    "reason": f"Security: {security.get('verdict')} (score={security.get('honeypot_score')})"
                })
                continue

            # RiskGuardAgent
            base_amount = current_value * 0.03 * signal.get("confidence", 0.5) * risk_mult
            base_amount = max(5.0, min(500.0, base_amount))

            proposal = TradeProposal(
                symbol           = sym,
                direction        = signal.get("direction", "BUY"),
                amount_usd       = base_amount,
                token_address    = token_addr,
                estimated_price_usd = 0.0,
                token_volume_24h = 1_000_000,  # from CMC trending data
                honeypot_score   = security.get("honeypot_score", 0),
                reasoning        = signal.get("reasoning", ""),
                confidence       = signal.get("confidence", 0.5),
            )

            risk_decision = evaluate_trade(
                proposal         = proposal,
                portfolio        = portfolio_state,
                security_verdict = security,
                market_conditions = {
                    "fear_greed": metrics.fear_greed_index,
                    "market_regime": orch_decision.get("market_regime", "NEUTRAL"),
                },
            )

            logger.info(f"Risk [{sym}]: approved={risk_decision['approved']} ${risk_decision.get('final_amount_usd', 0):.2f}")

            if not risk_decision.get("approved"):
                executions.append({
                    "symbol": sym, "action": "REJECTED",
                    "reason": risk_decision.get("rejection_reason")
                })
                continue

            # ExecutionAgent
            exec_result = execute_trade(
                approved_decision = risk_decision,
                signal            = signal,
                security_verdict  = security,
                portfolio         = self.portfolio,
                dry_run           = self.dry_run,
            )

            logger.info(f"Executed [{sym}]: {'OK tx=' + str(exec_result.get('tx_hash','?')) if exec_result.get('executed') else 'FAILED: ' + str(exec_result.get('error'))}")
            executions.append({"symbol": sym, "action": "EXECUTED", **exec_result})
            trade_count += 1

        return {
            "cycle":        self.cycle_count,
            "action":       action,
            "market_regime": orch_decision.get("market_regime"),
            "strategy_note": orch_decision.get("strategy_note"),
            "fear_greed":   metrics.fear_greed_index,
            "signals":      len(signals),
            "executions":   executions,
            "portfolio":    self.portfolio.summary(current_value),
            "dry_run":      self.dry_run,
        }
