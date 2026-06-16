"""
Autonomous trading guardrails.
Hard limits that CANNOT be overridden by any agent — enforced before every trade.

Competition rules (from hackathon contract):
- Max drawdown 30% -> disqualification
- Min 1 trade/day over 7-day window
- Portfolio must be >$1 to count

Our internal guardrails (more conservative):
- Max drawdown gate: 25% (5% buffer before disqualification)
- Per-trade max: 5% of portfolio value
- Daily loss limit: 8%
- Max open positions: 10
- Min liquidity for trade: $100,000 24h volume
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class GuardrailConfig:
    max_drawdown_pct: float = 25.0       # % below peak -> stop all trading
    per_trade_max_pct: float = 5.0       # % of portfolio per single trade
    per_trade_min_usd: float = 5.0       # minimum trade size in USD
    per_trade_max_usd: float = 500.0     # maximum trade size in USD
    daily_loss_limit_pct: float = 8.0   # % daily loss -> pause trading for 24h
    max_open_positions: int = 10
    min_token_volume_24h: float = 50_000.0  # USD — avoid illiquid tokens
    max_slippage_pct: float = 1.5        # max acceptable slippage
    cool_down_seconds: int = 60          # min seconds between trades on same token
    honeypot_score_limit: int = 30       # block tokens scoring above this


@dataclass
class PortfolioState:
    total_value_usd: float
    peak_value_usd: float
    start_value_usd: float
    open_positions: int
    daily_realized_pnl_usd: float
    day_start_value_usd: float
    last_trade_time: dict = field(default_factory=dict)  # symbol -> timestamp
    trade_count_today: int = 0

    @property
    def drawdown_pct(self) -> float:
        if self.peak_value_usd <= 0:
            return 0.0
        return (self.peak_value_usd - self.total_value_usd) / self.peak_value_usd * 100

    @property
    def daily_pnl_pct(self) -> float:
        if self.day_start_value_usd <= 0:
            return 0.0
        return self.daily_realized_pnl_usd / self.day_start_value_usd * 100

    @property
    def total_return_pct(self) -> float:
        if self.start_value_usd <= 0:
            return 0.0
        return (self.total_value_usd - self.start_value_usd) / self.start_value_usd * 100


@dataclass
class TradeProposal:
    symbol: str
    direction: str           # "BUY" or "SELL"
    amount_usd: float
    token_address: str
    estimated_price_usd: float
    token_volume_24h: float
    honeypot_score: int
    reasoning: str
    confidence: float        # 0.0 - 1.0


@dataclass
class GuardrailDecision:
    approved: bool
    adjusted_amount_usd: float
    rejection_reason: Optional[str]
    warnings: List[str]
    position_pct: float      # % of portfolio this represents

    def __str__(self) -> str:
        status = "APPROVED" if self.approved else f"REJECTED: {self.rejection_reason}"
        return f"[{status}] ${self.adjusted_amount_usd:.2f} ({self.position_pct:.1f}%)"


class GuardrailEngine:
    def __init__(self, config: Optional[GuardrailConfig] = None):
        self.config = config or GuardrailConfig()

    def evaluate(self, proposal: TradeProposal, portfolio: PortfolioState) -> GuardrailDecision:
        warnings: List[str] = []

        # ── HARD BLOCKS (cannot trade at all) ────────────────────────────────

        # 1. Drawdown gate
        if portfolio.drawdown_pct >= self.config.max_drawdown_pct:
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Max drawdown breached: {portfolio.drawdown_pct:.1f}% >= {self.config.max_drawdown_pct}% limit",
                warnings=[],
                position_pct=0.0,
            )

        # 2. Daily loss limit
        if portfolio.daily_pnl_pct <= -self.config.daily_loss_limit_pct:
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Daily loss limit hit: {portfolio.daily_pnl_pct:.1f}% <= -{self.config.daily_loss_limit_pct}%",
                warnings=[],
                position_pct=0.0,
            )

        # 3. Portfolio too small to trade ($1 competition floor)
        if portfolio.total_value_usd <= 1.0:
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason="Portfolio value <= $1 — competition floor reached",
                warnings=[],
                position_pct=0.0,
            )

        # 4. Honeypot score too high
        if proposal.honeypot_score > self.config.honeypot_score_limit:
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Honeypot score {proposal.honeypot_score}/100 exceeds limit {self.config.honeypot_score_limit}",
                warnings=[],
                position_pct=0.0,
            )

        # 5. Too many open positions
        if portfolio.open_positions >= self.config.max_open_positions and proposal.direction == "BUY":
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Max open positions {self.config.max_open_positions} reached",
                warnings=[],
                position_pct=0.0,
            )

        # 6. Token liquidity check
        if proposal.token_volume_24h < self.config.min_token_volume_24h:
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Insufficient liquidity: ${proposal.token_volume_24h:,.0f} < ${self.config.min_token_volume_24h:,.0f}",
                warnings=[],
                position_pct=0.0,
            )

        # ── SOFT ADJUSTMENTS (reduce size, add warnings) ─────────────────────

        amount = proposal.amount_usd

        # 7. Per-trade max cap
        max_by_pct = portfolio.total_value_usd * (self.config.per_trade_max_pct / 100)
        if amount > max_by_pct:
            warnings.append(f"Trade reduced from ${amount:.2f} to ${max_by_pct:.2f} (per-trade {self.config.per_trade_max_pct}% cap)")
            amount = max_by_pct

        # 8. Absolute max cap
        if amount > self.config.per_trade_max_usd:
            warnings.append(f"Trade capped at absolute max ${self.config.per_trade_max_usd}")
            amount = self.config.per_trade_max_usd

        # 9. Minimum trade check
        if amount < self.config.per_trade_min_usd:
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Trade ${amount:.2f} below minimum ${self.config.per_trade_min_usd}",
                warnings=warnings,
                position_pct=0.0,
            )

        # 10. Cool-down per token
        last = portfolio.last_trade_time.get(proposal.symbol, 0)
        elapsed = time.time() - last
        if elapsed < self.config.cool_down_seconds:
            remaining = self.config.cool_down_seconds - elapsed
            return GuardrailDecision(
                approved=False,
                adjusted_amount_usd=0.0,
                rejection_reason=f"Cool-down active for {proposal.symbol}: {remaining:.0f}s remaining",
                warnings=warnings,
                position_pct=0.0,
            )

        # 11. Drawdown warning zone (15-25%)
        if portfolio.drawdown_pct > 15.0:
            half = amount * 0.5
            warnings.append(f"Drawdown warning ({portfolio.drawdown_pct:.1f}%) — position halved to ${half:.2f}")
            amount = half

        # 12. Low confidence -> reduce size
        if proposal.confidence < 0.5:
            reduced = amount * proposal.confidence * 1.5
            warnings.append(f"Low confidence ({proposal.confidence:.2f}) — position reduced to ${reduced:.2f}")
            amount = reduced

        position_pct = (amount / portfolio.total_value_usd * 100) if portfolio.total_value_usd > 0 else 0

        return GuardrailDecision(
            approved=True,
            adjusted_amount_usd=round(amount, 2),
            rejection_reason=None,
            warnings=warnings,
            position_pct=round(position_pct, 2),
        )


# Singleton with default config
_default_engine = GuardrailEngine()


def check_trade(proposal: TradeProposal, portfolio: PortfolioState,
                config: Optional[GuardrailConfig] = None) -> GuardrailDecision:
    engine = GuardrailEngine(config) if config else _default_engine
    return engine.evaluate(proposal, portfolio)
