"""
15 BNB Chain / BSC-specific honeypot and rug-pull detection rules.
These are our core trading moat — every token is scanned before any trade.

Rule IDs: B-01 through B-15
"""
import re
from typing import List
from .base import Finding, Severity, RuleBase
from ..parser import ParsedFile


def _grep(pattern: str, text: str, flags: int = re.IGNORECASE) -> List[int]:
    results = []
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line, flags):
            results.append(i)
    return results


# ── B-01: Fee Manipulation ──────────────────────────────────────────────────

class FeeManipulationRule(RuleBase):
    id = "B-01"
    title = "Owner-Controlled Fee Manipulation (Rug Vector)"
    severity = Severity.CRITICAL
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        fee_setters = re.compile(
            r"function\s+(set(?:Buy|Sell|Tax|Fee|Percent|Rate|Limit|Max)"
            r"|updateFee|changeFee|updateTax|setTaxes)\s*\(",
            re.IGNORECASE,
        )
        for contract in parsed.contracts:
            for fn in contract.functions:
                if fee_setters.search(fn.raw):
                    has_cap = re.search(r"require\s*\(.*<=\s*(\d+)", fn.body_text())
                    cap_val = int(has_cap.group(1)) if has_cap else None
                    if cap_val is None or cap_val > 25:
                        findings.append(Finding(
                            rule_id=self.id,
                            title=self.title,
                            severity=self.severity,
                            lines=[fn.line],
                            description=(
                                f"`{fn.name}` allows the owner to change trading fees"
                                + (f" up to {cap_val}%" if cap_val else " with no cap")
                                + ". Owner can set fees to 99% to trap buyers."
                            ),
                            recommendation="Cap fees at 5% max via require(). Lock fees after launch.",
                            code_snippet=fn.raw,
                            bnb_specific=True,
                            category="security",
                        ))
        return findings


# ── B-02: Blacklist / Whitelist Trap ────────────────────────────────────────

class BlacklistRule(RuleBase):
    id = "B-02"
    title = "Address Blacklist — Can Block Sellers"
    severity = Severity.HIGH
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        bl_pats = [
            r"blacklist|blacklisted|_isBlacklisted|blocklist|isBot|bots\[",
            r"_blacklist\[|blacklistAddress|addBlacklist",
        ]
        for contract in parsed.contracts:
            full_src = "\n".join(contract.functions[0].body_text() if contract.functions else "")
            source = parsed.source
            for pat in bl_pats:
                lines = _grep(pat, source)
                if lines:
                    findings.append(Finding(
                        rule_id=self.id,
                        title=self.title,
                        severity=self.severity,
                        lines=lines[:3],
                        description=(
                            "Contract maintains a blacklist that can prevent specific addresses "
                            "from selling. Owner can blacklist buyers and trap their funds."
                        ),
                        recommendation="Remove blacklist mechanism or implement decentralized governance.",
                        code_snippet=parsed.lines[lines[0] - 1].strip() if lines else "",
                        bnb_specific=True,
                        category="security",
                    ))
                    break
        return findings


# ── B-03: Trading Enable Toggle ─────────────────────────────────────────────

class TradingToggleRule(RuleBase):
    id = "B-03"
    title = "Owner Can Disable Trading (Sell Trap)"
    severity = Severity.CRITICAL
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        toggle_pats = [
            r"tradingEnabled|tradingOpen|tradingActive|_tradingEnabled",
            r"enableTrading|openTrading|setTradingEnabled",
            r"swapEnabled|canTrade|tradeAllowed",
        ]
        source = parsed.source
        for pat in toggle_pats:
            lines = _grep(pat, source)
            if not lines:
                continue
            # Check if there's a function to toggle it off
            toggle_fn = re.search(
                r"function\s+\w*(?:disable|close|pause|stop)(?:Trading|Swap|Trade)\w*\s*\(",
                source, re.IGNORECASE,
            )
            set_false = re.search(r"tradingEnabled\s*=\s*false|_tradingEnabled\s*=\s*false", source)
            if toggle_fn or set_false:
                findings.append(Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=self.severity,
                    lines=lines[:2],
                    description=(
                        "Owner can disable trading, preventing all sells. "
                        "Classic honeypot pattern: buyers can purchase but never sell."
                    ),
                    recommendation="Remove disable functionality. Once trading is enabled, it must stay enabled.",
                    code_snippet=parsed.lines[lines[0] - 1].strip() if lines else "",
                    bnb_specific=True,
                    category="security",
                ))
            break
        return findings


# ── B-04: Uncapped Mint Function ────────────────────────────────────────────

class UncappedMintRule(RuleBase):
    id = "B-04"
    title = "Uncapped Mint Function — Infinite Inflation Risk"
    severity = Severity.CRITICAL
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        for contract in parsed.contracts:
            for fn in contract.functions:
                if not re.search(r"^mint|^_mint", fn.name, re.IGNORECASE):
                    continue
                if fn.visibility not in ("public", "external"):
                    continue
                body = fn.body_text()
                has_cap = re.search(r"maxSupply|totalSupply.*<=|MAX_SUPPLY|cap\b", body, re.IGNORECASE)
                has_access = bool(fn.modifiers) or re.search(r"onlyOwner|onlyMinter|require.*msg\.sender", body)
                if not has_cap:
                    findings.append(Finding(
                        rule_id=self.id,
                        title=self.title,
                        severity=self.severity if has_access else Severity.CRITICAL,
                        lines=[fn.line],
                        description=(
                            f"`{fn.name}` can mint unlimited tokens"
                            + (" (only owner, but owner-controlled inflation)" if has_access else " with no access control — anyone can call it")
                            + ". Owner can dump freshly minted tokens."
                        ),
                        recommendation="Add hard supply cap: require(totalSupply() + amount <= MAX_SUPPLY).",
                        code_snippet=fn.raw,
                        bnb_specific=True,
                        category="security",
                    ))
        return findings


# ── B-05: Proxy Admin Backdoor ──────────────────────────────────────────────

class ProxyBackdoorRule(RuleBase):
    id = "B-05"
    title = "Upgradeable Proxy Without Timelock — Admin Backdoor"
    severity = Severity.HIGH
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        proxy_pats = [
            r"TransparentUpgradeableProxy|UUPSUpgradeable|UpgradeableBeacon",
            r"_upgradeTo|upgradeToAndCall|_setImplementation",
            r"ProxyAdmin|ERC1967Upgrade",
        ]
        timelock_pats = [r"TimelockController|timelock|Timelock|_minDelay"]
        source = parsed.source

        has_proxy = any(re.search(p, source) for p in proxy_pats)
        has_timelock = any(re.search(p, source) for p in timelock_pats)

        if has_proxy and not has_timelock:
            upgrade_lines = _grep(r"upgradeTo|_setImplementation|upgradeToAndCall", source)
            if upgrade_lines:
                findings.append(Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=self.severity,
                    lines=upgrade_lines[:2],
                    description=(
                        "Contract uses an upgradeable proxy without a timelock. "
                        "Admin can silently replace the implementation to steal funds instantly."
                    ),
                    recommendation="Add TimelockController with min 48h delay. Use transparent proxy with community multisig.",
                    code_snippet=parsed.lines[upgrade_lines[0] - 1].strip() if upgrade_lines else "",
                    bnb_specific=True,
                    category="security",
                ))
        return findings


# ── B-06: Max Transaction / Wallet Limit ────────────────────────────────────

class MaxTxLimitRule(RuleBase):
    id = "B-06"
    title = "Owner-Adjustable Max Transaction / Wallet Limit"
    severity = Severity.MEDIUM
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        maxtx_pats = [r"maxTxAmount|_maxTxAmount|maxWallet|maxWalletAmount|maxTransactionAmount"]
        setter_pats = [r"function\s+set(?:Max|_max)(?:Tx|Transaction|Wallet)\w*\s*\("]
        source = parsed.source

        has_maxtx = any(re.search(p, source, re.IGNORECASE) for p in maxtx_pats)
        setter_m = None
        for pat in setter_pats:
            setter_m = re.search(pat, source, re.IGNORECASE)
            if setter_m:
                break

        if has_maxtx and setter_m:
            line_n = source[: setter_m.start()].count("\n") + 1
            body_snippet = parsed.lines[line_n - 1].strip() if line_n <= len(parsed.lines) else ""
            # Check if setter has no minimum requirement check
            fn_end = source.find("}", setter_m.end())
            fn_body = source[setter_m.end(): fn_end]
            has_min = re.search(r"require\s*\(.*>=\s*\d", fn_body)
            if not has_min:
                findings.append(Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=self.severity,
                    lines=[line_n],
                    description=(
                        "Owner can reduce maxTxAmount or maxWallet to 0, "
                        "effectively freezing all transfers for everyone but the owner."
                    ),
                    recommendation="Enforce minimum: require(newMax >= totalSupply / 1000).",
                    code_snippet=body_snippet,
                    bnb_specific=True,
                    category="security",
                ))
        return findings


# ── B-07: Burn From Arbitrary Address ───────────────────────────────────────

class BurnFromArbitraryRule(RuleBase):
    id = "B-07"
    title = "Owner Can Burn Tokens From Any Address"
    severity = Severity.CRITICAL
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        for contract in parsed.contracts:
            for fn in contract.functions:
                if not re.search(r"burn|destroy", fn.name, re.IGNORECASE):
                    continue
                params = fn.params
                has_from_addr = re.search(r"address\s+\w*(from|account|holder|addr|target)", params, re.IGNORECASE)
                if not has_from_addr:
                    continue
                body = fn.body_text()
                has_approval_check = re.search(r"allowance|_approve|_spendAllowance|msg\.sender.*==.*from", body)
                if not has_approval_check:
                    findings.append(Finding(
                        rule_id=self.id,
                        title=self.title,
                        severity=self.severity,
                        lines=[fn.line],
                        description=(
                            f"`{fn.name}` burns tokens from an arbitrary address without checking approval. "
                            "Owner can destroy any holder's tokens without consent."
                        ),
                        recommendation="Require ERC-20 allowance: _spendAllowance(account, msg.sender, amount).",
                        code_snippet=fn.raw,
                        bnb_specific=True,
                        category="security",
                    ))
        return findings


# ── B-08: Hidden Transfer Fee in _transfer ──────────────────────────────────

class HiddenTransferFeeRule(RuleBase):
    id = "B-08"
    title = "Hidden Tax in _transfer — Sell Tax May Differ From Buy Tax"
    severity = Severity.HIGH
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        for contract in parsed.contracts:
            for fn in contract.functions:
                if fn.name not in ("_transfer", "transfer", "_tokenTransfer"):
                    continue
                body = fn.body_text()
                has_fee_branch = re.search(
                    r"if\s*\(.*(?:sell|buy|isSell|isBuy|from\s*==\s*\w+pair|to\s*==\s*\w+pair)",
                    body, re.IGNORECASE,
                )
                has_different_tax = re.search(r"sell[Tt]ax|sell[Ff]ee|[Ss]ell[Rr]ate", body)
                if has_fee_branch and has_different_tax:
                    # Check if the sell fee can be changed
                    sell_setter = re.search(
                        r"function.*set.*sell|setSellTax|setSellFee|updateSellFee",
                        parsed.source, re.IGNORECASE,
                    )
                    if sell_setter:
                        line = parsed.source[: sell_setter.start()].count("\n") + 1
                        findings.append(Finding(
                            rule_id=self.id,
                            title=self.title,
                            severity=self.severity,
                            lines=[fn.line, line],
                            description=(
                                "_transfer applies different buy/sell fees AND the sell fee can be changed by owner. "
                                "Owner can raise sell tax to 99% after buyers are in."
                            ),
                            recommendation="Lock sell tax at deploy. Max sell tax 5%, same as buy tax.",
                            code_snippet=fn.raw[:200],
                            bnb_specific=True,
                            category="security",
                        ))
        return findings


# ── B-09: Anti-Dump / Cool-Down Trap ────────────────────────────────────────

class AntiDumpRule(RuleBase):
    id = "B-09"
    title = "Anti-Dump / Cooldown Mechanism Can Lock Sellers"
    severity = Severity.MEDIUM
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        cooldown_pats = [
            r"cooldown|_cooldownTime|lastTrade|lastSell|_lastTransfer|antiDump",
            r"require\s*\(.*block\.timestamp.*>.*last",
        ]
        source = parsed.source
        for pat in cooldown_pats:
            lines_found = _grep(pat, source)
            if lines_found:
                setter = re.search(r"function\s+\w*(?:setCooldown|setAntiDump|updateCooldown)\w*\s*\(", source, re.IGNORECASE)
                if setter:
                    setter_line = source[: setter.start()].count("\n") + 1
                    findings.append(Finding(
                        rule_id=self.id,
                        title=self.title,
                        severity=self.severity,
                        lines=lines_found[:2],
                        description=(
                            "Contract has an owner-adjustable cooldown or anti-dump mechanism. "
                            "Owner can set cooldown to 1 year, preventing all sells."
                        ),
                        recommendation="Hard-cap cooldown at 24h max. Remove owner control over cooldown duration.",
                        code_snippet=parsed.lines[lines_found[0] - 1].strip(),
                        bnb_specific=True,
                        category="security",
                    ))
                    break
        return findings


# ── B-10: External Call in Transfer Hook ────────────────────────────────────

class TransferHookCallRule(RuleBase):
    id = "B-10"
    title = "External Call Inside _transfer — Reentrancy / MEV Risk"
    severity = Severity.HIGH
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        external_call_pats = [r"\.\s*call\s*[({]", r"\.swap\s*\(", r"IUniswap\w*\."]
        for contract in parsed.contracts:
            for fn in contract.functions:
                if fn.name not in ("_transfer", "_tokenTransfer", "transfer"):
                    continue
                body = fn.body_text()
                for pat in external_call_pats:
                    m = re.search(pat, body)
                    if m:
                        findings.append(Finding(
                            rule_id=self.id,
                            title=self.title,
                            severity=self.severity,
                            lines=[fn.line],
                            description=(
                                f"_transfer makes external calls ({m.group().strip()}). "
                                "This enables reentrancy attacks and MEV sandwich attacks on every transfer."
                            ),
                            recommendation="Remove external calls from _transfer. Use a separate swapAndLiquify trigger with CEI pattern.",
                            code_snippet=fn.raw[:200],
                            bnb_specific=True,
                            category="security",
                        ))
                        break
        return findings


# ── B-11: Hidden Owner (Renounce Bypass) ────────────────────────────────────

class HiddenOwnerRule(RuleBase):
    id = "B-11"
    title = "Hidden Owner Mechanism — Renounce Can Be Bypassed"
    severity = Severity.CRITICAL
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        hidden_pats = [
            r"previousOwner|_previousOwner|hiddenOwner|secretOwner|_owner2",
            r"function\s+\w*(?:recover|reclaim|restore)Ownership\s*\(",
            r"_owner\s*=\s*previousOwner",
        ]
        source = parsed.source
        for pat in hidden_pats:
            lines_found = _grep(pat, source)
            if lines_found:
                findings.append(Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=self.severity,
                    lines=lines_found[:3],
                    description=(
                        "Contract has a hidden owner variable or ownership recovery function. "
                        "Owner can renounce ownership (appearing safe) then recover it later."
                    ),
                    recommendation="Remove all hidden owner mechanisms. Use standard OZ Ownable with no recovery.",
                    code_snippet=parsed.lines[lines_found[0] - 1].strip(),
                    bnb_specific=True,
                    category="security",
                ))
        return findings


# ── B-12: Token Balance Manipulation ────────────────────────────────────────

class BalanceManipulationRule(RuleBase):
    id = "B-12"
    title = "Direct Balance Manipulation — Owner Can Zero Out Holders"
    severity = Severity.CRITICAL
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        for contract in parsed.contracts:
            for fn in contract.functions:
                body = fn.body_text()
                balance_set = re.search(r"_balances\s*\[.*\]\s*=|balanceOf\[.*\]\s*=", body)
                if balance_set and fn.name not in ("constructor", "_transfer", "transfer", "_mint", "_burn"):
                    is_public = fn.visibility in ("public", "external")
                    if is_public:
                        findings.append(Finding(
                            rule_id=self.id,
                            title=self.title,
                            severity=self.severity,
                            lines=[fn.line],
                            description=(
                                f"`{fn.name}` directly modifies _balances mapping. "
                                "Owner can set any holder's balance to 0."
                            ),
                            recommendation="Never expose direct balance modification. Use _mint/_burn internally only.",
                            code_snippet=fn.raw,
                            bnb_specific=True,
                            category="security",
                        ))
        return findings


# ── B-13: Ownership Not Renounced Check (Warning) ───────────────────────────

class OwnershipNotRenouncedRule(RuleBase):
    id = "B-13"
    title = "Mutable Ownership With High-Risk Functions"
    severity = Severity.MEDIUM
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        for contract in parsed.contracts:
            has_owner = any(re.search(r"\bOwnable\b|\bowner\(\)", inh) for inh in contract.inheritance)
            if not has_owner:
                has_owner = any(re.search(r"\bowner\b", sv.name, re.IGNORECASE) for sv in contract.state_vars)
            if not has_owner:
                continue

            danger_fns = [
                fn for fn in contract.functions
                if fn.visibility in ("public", "external")
                and (bool(fn.modifiers) or re.search(r"onlyOwner", fn.raw))
                and re.search(r"mint|burn|fee|tax|blacklist|whitelist|pause|disable|withdraw", fn.name, re.IGNORECASE)
            ]
            if len(danger_fns) >= 3:
                findings.append(Finding(
                    rule_id=self.id,
                    title=self.title,
                    severity=self.severity,
                    lines=[contract.line],
                    description=(
                        f"Contract has {len(danger_fns)} owner-gated high-risk functions "
                        f"({', '.join(f.name for f in danger_fns[:4])}...). "
                        "Ownership must be renounced post-launch for this token to be safe."
                    ),
                    recommendation="Renounce ownership after liquidity lock. Use timelock for remaining admin functions.",
                    code_snippet=f"contract {contract.name} (owner has {len(danger_fns)} privileged functions)",
                    bnb_specific=True,
                    category="security",
                ))
        return findings


# ── B-14: Swap/Liquidity Lock Bypass ────────────────────────────────────────

class SwapLockBypassRule(RuleBase):
    id = "B-14"
    title = "Liquidity/Swap Lock Bypass — Owner Can Drain LP"
    severity = Severity.HIGH
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        drain_pats = [
            r"function\s+\w*(?:rescueToken|recoverToken|withdrawToken|drainLP|removeLiquidity)\w*\s*\(",
            r"function\s+\w*(?:claimStuck|rescueETH|withdrawETH|clearStuckBalance)\w*\s*\(",
        ]
        source = parsed.source
        for pat in drain_pats:
            m = re.search(pat, source, re.IGNORECASE)
            if m:
                line = source[: m.start()].count("\n") + 1
                fn_end = source.find("}", m.end())
                fn_body = source[m.end(): fn_end]
                calls_transfer = re.search(r"\.(transfer|call)\s*\(|IERC20.*transfer", fn_body)
                if calls_transfer:
                    findings.append(Finding(
                        rule_id=self.id,
                        title=self.title,
                        severity=self.severity,
                        lines=[line],
                        description=(
                            "Owner can call a drain/rescue function that transfers LP tokens or ETH "
                            "out of the contract. Classic soft-rug pattern."
                        ),
                        recommendation="Remove rescue functions or lock them behind community multisig + timelock.",
                        code_snippet=parsed.lines[line - 1].strip() if line <= len(parsed.lines) else "",
                        bnb_specific=True,
                        category="security",
                    ))
        return findings


# ── B-15: Missing Transfer Event ────────────────────────────────────────────

class MissingTransferEventRule(RuleBase):
    id = "B-15"
    title = "Missing ERC-20 Transfer Event in Custom _transfer"
    severity = Severity.LOW
    bnb_specific = True

    def check(self, parsed: ParsedFile) -> List[Finding]:
        findings = []
        for contract in parsed.contracts:
            for fn in contract.functions:
                if fn.name not in ("_transfer", "_tokenTransfer"):
                    continue
                body = fn.body_text()
                if not re.search(r"emit\s+Transfer\s*\(", body):
                    findings.append(Finding(
                        rule_id=self.id,
                        title=self.title,
                        severity=self.severity,
                        lines=[fn.line],
                        description=(
                            f"`{fn.name}` does not emit Transfer event. "
                            "DEX aggregators, block explorers, and tax tools rely on Transfer events "
                            "to track balances — omitting it can make tokens invisible to DeFi tools."
                        ),
                        recommendation="Add: emit Transfer(from, to, amount); at end of _transfer.",
                        code_snippet=fn.raw[:150],
                        bnb_specific=True,
                        category="security",
                    ))
        return findings


ALL_BNB_HONEYPOT_RULES: List[RuleBase] = [
    FeeManipulationRule(),
    BlacklistRule(),
    TradingToggleRule(),
    UncappedMintRule(),
    ProxyBackdoorRule(),
    MaxTxLimitRule(),
    BurnFromArbitraryRule(),
    HiddenTransferFeeRule(),
    AntiDumpRule(),
    TransferHookCallRule(),
    HiddenOwnerRule(),
    BalanceManipulationRule(),
    OwnershipNotRenouncedRule(),
    SwapLockBypassRule(),
    MissingTransferEventRule(),
]
