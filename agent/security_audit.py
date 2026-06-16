"""
SecurityAuditAgent — claude-haiku-4-5-20251001
Fast binary security verdict for BEP-20 contracts.
Runs the static engine FIRST (deterministic rules), then calls Haiku to
interpret findings and produce a natural-language risk summary.

Using Haiku here because:
- Speed is critical (called before every trade)
- The heavy lifting is done by our static engine
- LLM adds qualitative reasoning, not raw detection
"""
from __future__ import annotations

import json
from typing import Optional
import anthropic

from audit_engine import scan_address, scan_source, SecurityVerdict

MODEL = "claude-haiku-4-5-20251001"

_client = anthropic.Anthropic()

_SYSTEM = """You are SecurityAuditAgent, a BEP-20 token security specialist.
You receive the output of a static audit engine scan of a Solidity contract.
Your job: produce a concise security assessment in JSON.

Output format (ONLY JSON, no prose):
{
  "tradeable": true | false,
  "verdict": "SAFE" | "CAUTION" | "HONEYPOT" | "RUG",
  "confidence": 0.0-1.0,
  "top_risks": ["list of 1-3 main concerns, empty if safe"],
  "one_line_summary": "< 15 words"
}

Decision rules:
- CRITICAL findings (reentrancy, uncapped mint, fee manipulation, hidden owner, trading toggle) -> HONEYPOT or RUG + tradeable=false
- HIGH findings only -> CAUTION, tradeable=true with reduced confidence
- LOW/MEDIUM only -> SAFE with high confidence
- Unverified source -> HONEYPOT, tradeable=false
- Score 0 or CRITICAL risk_level -> always tradeable=false"""


def audit_contract(
    contract_address: str,
    source_code: Optional[str] = None,
) -> dict:
    """
    Main entry: audit a contract by address or source code.
    Returns a security dict with the LLM's verdict layered on top of static analysis.
    """
    # Step 1: Run deterministic static engine
    if source_code:
        verdict: SecurityVerdict = scan_source(source_code, label=contract_address)
    else:
        verdict: SecurityVerdict = scan_address(contract_address)

    # If definitely unverified/critical — short-circuit, no LLM needed
    if not verdict.tradeable and verdict.honeypot_score >= 80:
        return {
            "contract_address": contract_address,
            "tradeable": False,
            "verdict": "HONEYPOT" if verdict.honeypot_score > 60 else "RUG",
            "confidence": 0.95,
            "honeypot_score": verdict.honeypot_score,
            "risk_level": verdict.risk_level,
            "top_risks": verdict.critical_findings[:3],
            "one_line_summary": f"Blocked: {verdict.critical_findings[0][:60] if verdict.critical_findings else 'critical risk'}",
            "static_verdict": verdict.to_dict(),
        }

    # Step 2: Call Haiku for qualitative interpretation
    findings_summary = {
        "risk_level":       verdict.risk_level,
        "honeypot_score":   verdict.honeypot_score,
        "tradeable":        verdict.tradeable,
        "findings_count":   verdict.findings_summary,
        "critical_findings": verdict.critical_findings[:5],
        "high_findings":    verdict.high_findings[:5],
        "recommendation":   verdict.recommendation,
    }

    user_msg = f"""Contract: {contract_address}
Static audit engine results:
{json.dumps(findings_summary, indent=2)}

Provide your security verdict as JSON."""

    response = _client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_text = response.content[0].text if response.content else "{}"

    try:
        start = raw_text.find("{")
        end   = raw_text.rfind("}") + 1
        llm_verdict = json.loads(raw_text[start:end])
    except (json.JSONDecodeError, ValueError):
        llm_verdict = {}

    return {
        "contract_address": contract_address,
        "tradeable":        llm_verdict.get("tradeable", verdict.tradeable),
        "verdict":          llm_verdict.get("verdict", verdict.risk_level),
        "confidence":       llm_verdict.get("confidence", 0.5),
        "honeypot_score":   verdict.honeypot_score,
        "risk_level":       verdict.risk_level,
        "top_risks":        llm_verdict.get("top_risks", verdict.high_findings[:3]),
        "one_line_summary": llm_verdict.get("one_line_summary", verdict.recommendation[:80]),
        "static_verdict":   verdict.to_dict(),
    }
