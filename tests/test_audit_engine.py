"""
Tests for BNB Chain audit engine — honeypot detection rules.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from audit_engine.engine import AuditEngine
from audit_engine.rules.base import Severity


HONEYPOT_CONTRACT = """
pragma solidity ^0.8.0;

contract HoneypotToken {
    string public name = "HoneyToken";
    bool public tradingEnabled = false;
    mapping(address => bool) public blacklisted;
    uint256 public sellTax = 5;
    address private previousOwner;

    function enableTrading() external onlyOwner {
        tradingEnabled = true;
    }

    function disableTrading() external onlyOwner {
        tradingEnabled = false;
    }

    function setSellTax(uint256 newTax) external onlyOwner {
        sellTax = newTax;
    }

    function blacklistAddress(address addr) external onlyOwner {
        blacklisted[addr] = true;
    }

    function mint(address to, uint256 amount) external public {
        // no cap!
        _balances[to] += amount;
    }
}
"""

SAFE_CONTRACT = """
pragma solidity ^0.8.0;

contract SafeToken {
    string public name = "SafeToken";
    uint256 public constant MAX_SUPPLY = 1_000_000 * 1e18;
    uint256 private constant MAX_FEE = 5;

    function transfer(address to, uint256 amount) external returns (bool) {
        emit Transfer(msg.sender, to, amount);
        return true;
    }
}
"""


def test_honeypot_detection():
    engine = AuditEngine(run_security=True, run_honeypot=True)
    result = engine.analyze(HONEYPOT_CONTRACT, label="honeypot_test.sol")

    crits = [f for f in result.honeypot_findings if f.severity == Severity.CRITICAL]
    highs = [f for f in result.honeypot_findings if f.severity == Severity.HIGH]

    print(f"Critical findings: {len(crits)}")
    for f in crits:
        print(f"  [{f.rule_id}] {f.title}")

    print(f"High findings: {len(highs)}")
    for f in highs:
        print(f"  [{f.rule_id}] {f.title}")

    assert len(crits) >= 2, f"Expected >=2 critical findings, got {len(crits)}"
    assert not result.is_tradeable(), "Honeypot should NOT be tradeable"
    assert result.honeypot_score() > 50, f"Expected honeypot score > 50, got {result.honeypot_score()}"
    print(f"Honeypot score: {result.honeypot_score()}/100 - PASS")


def test_safe_contract():
    engine = AuditEngine(run_security=True, run_honeypot=True)
    result = engine.analyze(SAFE_CONTRACT, label="safe_test.sol")

    crits = [f for f in result.honeypot_findings if f.severity == Severity.CRITICAL]
    print(f"Critical findings on safe contract: {len(crits)}")
    for f in crits:
        print(f"  [{f.rule_id}] {f.title}")

    assert len(crits) == 0, f"Safe contract should have 0 critical findings, got {len(crits)}"
    print(f"Honeypot score: {result.honeypot_score()}/100 - PASS")


def test_verdict_summary():
    engine = AuditEngine()
    result = engine.analyze(HONEYPOT_CONTRACT, "honeypot.sol")
    verdict = engine.to_verdict(result, "0xHONEYPOT")
    print(f"\nVerdict: {verdict.verdict if hasattr(verdict, 'verdict') else 'n/a'}")
    print(f"Tradeable: {verdict.tradeable}")
    print(f"Recommendation: {verdict.recommendation}")
    assert not verdict.tradeable


if __name__ == "__main__":
    print("=== test_honeypot_detection ===")
    test_honeypot_detection()
    print("\n=== test_safe_contract ===")
    test_safe_contract()
    print("\n=== test_verdict_summary ===")
    test_verdict_summary()
    print("\nAll tests PASSED")
