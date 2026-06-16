"""
BNB Chain contract scanner — fetches Solidity source from BSCScan API,
runs the full audit engine, and returns a SecurityVerdict.

Security gate: contracts scoring CRITICAL are blocked from trading.
"""
from __future__ import annotations

import os
import re
import time
import hashlib
import requests
from typing import Optional

from .engine import AuditEngine, SecurityVerdict, AuditResult

_BSCSCAN_API = "https://api.bscscan.com/api"
_BSCSCAN_KEY = os.getenv("BSCSCAN_API_KEY", "")

_engine = AuditEngine(run_security=True, run_honeypot=True)

# In-memory verdict cache — keyed by contract address
_verdict_cache: dict[str, tuple[float, SecurityVerdict]] = {}
_CACHE_TTL = 3600  # 1 hour


def _fetch_source_bscscan(address: str) -> Optional[str]:
    """Fetch verified Solidity source from BSCScan. Returns None if not verified."""
    params = {
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
        "apikey": _BSCSCAN_KEY,
    }
    try:
        r = requests.get(_BSCSCAN_API, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "1" or not data.get("result"):
            return None
        result = data["result"][0]
        source = result.get("SourceCode", "")
        if not source or source == "":
            return None
        # BSCScan wraps multi-file sources in JSON — extract first file
        if source.startswith("{") and "sources" in source:
            import json
            try:
                wrapped = json.loads(source[1:-1] if source.startswith("{{") else source)
                sources = wrapped.get("sources", {})
                if sources:
                    first_key = next(iter(sources))
                    return sources[first_key].get("content", source)
            except Exception:
                pass
        return source
    except Exception as e:
        print(f"[scanner] BSCScan fetch error for {address}: {e}")
        return None


def _is_bep20(source: str) -> bool:
    """Quick check: does this look like a BEP-20 token contract?"""
    return bool(re.search(r"function\s+transfer\s*\(|IERC20|ERC20|BEP20|totalSupply\s*\(", source))


def scan_address(address: str, force_refresh: bool = False) -> SecurityVerdict:
    """
    Main entry point: scan a BEP-20 contract by BSC address.
    Returns a cached verdict if available (TTL=1h).
    """
    address = address.lower()

    # Cache check
    if not force_refresh and address in _verdict_cache:
        cached_at, verdict = _verdict_cache[address]
        if time.time() - cached_at < _CACHE_TTL:
            return verdict

    source = _fetch_source_bscscan(address)

    if source is None:
        # Contract not verified — treat as HIGH risk (can't audit what we can't see)
        verdict = SecurityVerdict(
            contract_address  = address,
            contract_name     = "UNVERIFIED",
            tradeable         = False,
            risk_level        = "HIGH",
            honeypot_score    = 80,
            findings_summary  = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 0, "LOW": 0, "INFO": 0},
            critical_findings = [],
            high_findings     = ["Source not verified on BSCScan — cannot audit"],
            recommendation    = "DO NOT TRADE — unverified contract source",
            raw_result        = None,
        )
        _verdict_cache[address] = (time.time(), verdict)
        return verdict

    result = _engine.analyze(source, label=address)
    verdict = _engine.to_verdict(result, contract_address=address)
    _verdict_cache[address] = (time.time(), verdict)
    return verdict


def scan_source(source: str, label: str = "<inline>") -> SecurityVerdict:
    """Scan raw Solidity source code directly (for testing / local files)."""
    result = _engine.analyze(source, label=label)
    return _engine.to_verdict(result, contract_address=label)


def batch_scan(addresses: list[str], delay: float = 0.25) -> dict[str, SecurityVerdict]:
    """Scan multiple addresses — respects BSCScan rate limit (5 req/s free tier)."""
    results = {}
    for addr in addresses:
        results[addr] = scan_address(addr)
        if delay > 0:
            time.sleep(delay)
    return results
