"""
BNB Chain Audit Engine — runs all rules (vulnerability + honeypot) on a parsed contract.
Returns a SecurityVerdict with a deployable/tradeable flag.
"""
from dataclasses import dataclass, field
from typing import List, Dict
from .parser import ParsedFile, parse
from .rules.base import Finding, Severity
from .rules.vulnerability_rules import ALL_VULNERABILITY_RULES
from .rules.bnb_honeypot_rules import ALL_BNB_HONEYPOT_RULES


@dataclass
class AuditResult:
    source_file: str
    parsed: ParsedFile
    security_findings: List[Finding] = field(default_factory=list)
    honeypot_findings: List[Finding] = field(default_factory=list)

    def all_findings(self) -> List[Finding]:
        return self.security_findings + self.honeypot_findings

    def risk_level(self) -> str:
        all_f = self.all_findings()
        if any(f.severity == Severity.CRITICAL for f in all_f):
            return "CRITICAL"
        if any(f.severity == Severity.HIGH for f in all_f):
            return "HIGH"
        if any(f.severity == Severity.MEDIUM for f in all_f):
            return "MEDIUM"
        if all_f:
            return "LOW"
        return "SAFE"

    def is_tradeable(self) -> bool:
        """True if the contract passes our security gate for trading."""
        return self.risk_level() not in ("CRITICAL",)

    def honeypot_score(self) -> int:
        """0 = clean, 100 = definite honeypot. Used for quick filtering."""
        score = 0
        for f in self.honeypot_findings:
            if f.severity == Severity.CRITICAL:
                score += 35
            elif f.severity == Severity.HIGH:
                score += 20
            elif f.severity == Severity.MEDIUM:
                score += 10
            else:
                score += 3
        return min(100, score)

    def severity_counts(self) -> Dict[str, int]:
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for f in self.all_findings():
            counts[f.severity.name] += 1
        return counts

    def summary_line(self) -> str:
        c = self.severity_counts()
        hs = self.honeypot_score()
        tradeable = "TRADEABLE" if self.is_tradeable() else "BLOCKED"
        return (
            f"[{tradeable}] risk={self.risk_level()} "
            f"honeypot_score={hs}/100 "
            f"findings: CRIT={c['CRITICAL']} HIGH={c['HIGH']} MED={c['MEDIUM']}"
        )


@dataclass
class SecurityVerdict:
    """Compact trading decision object returned by the scanner."""
    contract_address: str
    contract_name: str
    tradeable: bool
    risk_level: str
    honeypot_score: int
    findings_summary: Dict[str, int]
    critical_findings: List[str]
    high_findings: List[str]
    recommendation: str
    raw_result: AuditResult = field(repr=False)

    def to_dict(self) -> dict:
        return {
            "contract_address": self.contract_address,
            "contract_name": self.contract_name,
            "tradeable": self.tradeable,
            "risk_level": self.risk_level,
            "honeypot_score": self.honeypot_score,
            "findings_summary": self.findings_summary,
            "critical_findings": self.critical_findings,
            "high_findings": self.high_findings,
            "recommendation": self.recommendation,
        }


class AuditEngine:
    def __init__(self, run_security: bool = True, run_honeypot: bool = True):
        self.run_security  = run_security
        self.run_honeypot  = run_honeypot

    def analyze(self, source: str, label: str = "<input>") -> AuditResult:
        parsed = parse(source)
        result = AuditResult(source_file=label, parsed=parsed)

        if self.run_security:
            for rule in ALL_VULNERABILITY_RULES:
                try:
                    result.security_findings.extend(rule.check(parsed))
                except Exception:
                    pass

        if self.run_honeypot:
            for rule in ALL_BNB_HONEYPOT_RULES:
                try:
                    result.honeypot_findings.extend(rule.check(parsed))
                except Exception:
                    pass

        sev_order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
        result.security_findings.sort(key=lambda f: sev_order.index(f.severity))
        result.honeypot_findings.sort(key=lambda f: sev_order.index(f.severity))
        return result

    def to_verdict(self, result: AuditResult, contract_address: str = "unknown") -> SecurityVerdict:
        all_f = result.all_findings()
        crits  = [f"{f.rule_id}: {f.title}" for f in all_f if f.severity == Severity.CRITICAL]
        highs  = [f"{f.rule_id}: {f.title}" for f in all_f if f.severity == Severity.HIGH]
        risk   = result.risk_level()

        if risk == "CRITICAL":
            rec = "DO NOT TRADE — critical honeypot/security findings detected"
        elif risk == "HIGH":
            rec = "HIGH RISK — trade only with micro position size (<0.5% portfolio)"
        elif risk == "MEDIUM":
            rec = "MEDIUM risk — apply standard position limits"
        elif risk == "LOW":
            rec = "LOW risk — normal position sizing applies"
        else:
            rec = "SAFE — no significant findings, full position size allowed"

        contract_name = result.parsed.contracts[0].name if result.parsed.contracts else "Unknown"
        return SecurityVerdict(
            contract_address  = contract_address,
            contract_name     = contract_name,
            tradeable         = result.is_tradeable(),
            risk_level        = risk,
            honeypot_score    = result.honeypot_score(),
            findings_summary  = result.severity_counts(),
            critical_findings = crits,
            high_findings     = highs,
            recommendation    = rec,
            raw_result        = result,
        )
