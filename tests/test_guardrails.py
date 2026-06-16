"""
Tests for autonomous trading guardrails.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from trading_engine.guardrails import (
    check_trade, GuardrailConfig, TradeProposal, PortfolioState
)


def _make_portfolio(**kwargs) -> PortfolioState:
    defaults = dict(
        total_value_usd=100.0, peak_value_usd=100.0, start_value_usd=100.0,
        open_positions=0, daily_realized_pnl_usd=0.0, day_start_value_usd=100.0,
    )
    defaults.update(kwargs)
    return PortfolioState(**defaults)


def _make_proposal(**kwargs) -> TradeProposal:
    defaults = dict(
        symbol="CAKE", direction="BUY", amount_usd=10.0,
        token_address="0xCAKE", estimated_price_usd=2.0,
        token_volume_24h=5_000_000.0, honeypot_score=0,
        reasoning="test", confidence=0.75,
    )
    defaults.update(kwargs)
    return TradeProposal(**defaults)


def test_drawdown_block():
    portfolio = _make_portfolio(total_value_usd=70.0, peak_value_usd=100.0)
    proposal  = _make_proposal()
    decision  = check_trade(proposal, portfolio)
    assert not decision.approved, "Should block at 30% drawdown"
    assert "drawdown" in decision.rejection_reason.lower()
    print("test_drawdown_block PASSED")


def test_honeypot_block():
    portfolio = _make_portfolio()
    proposal  = _make_proposal(honeypot_score=75)
    decision  = check_trade(proposal, portfolio)
    assert not decision.approved
    assert "honeypot" in decision.rejection_reason.lower()
    print("test_honeypot_block PASSED")


def test_size_cap():
    portfolio = _make_portfolio(total_value_usd=200.0)
    proposal  = _make_proposal(amount_usd=50.0)  # 25% of portfolio -> should be capped to 5%
    decision  = check_trade(proposal, portfolio)
    assert decision.approved
    assert decision.adjusted_amount_usd <= 10.0, f"Expected <=10, got {decision.adjusted_amount_usd}"
    print(f"test_size_cap PASSED: ${decision.adjusted_amount_usd:.2f}")


def test_liquidity_block():
    portfolio = _make_portfolio()
    proposal  = _make_proposal(token_volume_24h=1000.0)  # very low liquidity
    config    = GuardrailConfig(min_token_volume_24h=50_000.0)
    decision  = check_trade(proposal, portfolio, config)
    assert not decision.approved
    assert "liquidity" in decision.rejection_reason.lower()
    print("test_liquidity_block PASSED")


def test_normal_trade_approved():
    portfolio = _make_portfolio()
    proposal  = _make_proposal(amount_usd=5.0, confidence=0.8)
    decision  = check_trade(proposal, portfolio)
    assert decision.approved, f"Expected approved, got: {decision.rejection_reason}"
    assert decision.adjusted_amount_usd > 0
    print(f"test_normal_trade_approved PASSED: ${decision.adjusted_amount_usd:.2f} ({decision.position_pct:.1f}%)")


def test_daily_loss_limit():
    portfolio = _make_portfolio(
        total_value_usd=100.0,
        daily_realized_pnl_usd=-10.0,  # -10% today
        day_start_value_usd=100.0,
    )
    proposal = _make_proposal()
    decision = check_trade(proposal, portfolio)
    assert not decision.approved
    print("test_daily_loss_limit PASSED")


if __name__ == "__main__":
    test_drawdown_block()
    test_honeypot_block()
    test_size_cap()
    test_liquidity_block()
    test_normal_trade_approved()
    test_daily_loss_limit()
    print("\nAll guardrail tests PASSED")
