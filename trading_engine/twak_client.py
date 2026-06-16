"""
Trust Wallet Agent Kit (TWAK) client wrapper.
Supports both CLI mode (subprocess) and MCP mode (HTTP to TWAK MCP server).

CLI commands used:
  twak wallet balance [--token <address>]
  twak trade swap --from <token> --to <token> --amount <usd> --slippage <pct>
  twak compete register
  twak compete status

Env vars:
  TWAK_MODE      = "cli" | "mcp" (default: cli)
  TWAK_MCP_URL   = http://localhost:3000 (if MCP mode)
  TWAK_WALLET    = 0x... (agent wallet address for registration)
"""
from __future__ import annotations

import os
import json
import time
import subprocess
from dataclasses import dataclass
from typing import Optional

TWAK_MODE    = os.getenv("TWAK_MODE", "cli")
TWAK_MCP_URL = os.getenv("TWAK_MCP_URL", "http://localhost:3000")
TWAK_WALLET  = os.getenv("TWAK_WALLET", "")


@dataclass
class SwapResult:
    success: bool
    tx_hash: Optional[str]
    amount_in: float
    amount_out: float
    fee_usd: float
    gas_used: Optional[int]
    error: Optional[str]

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class BalanceResult:
    token_address: str
    symbol: str
    balance: float
    value_usd: float


@dataclass
class CompetitionStatus:
    registered: bool
    wallet_address: str
    portfolio_value_usd: float
    rank: Optional[int]
    total_return_pct: float
    trade_count: int


def _run_cli(args: list[str], timeout: int = 30) -> dict:
    """Run a TWAK CLI command and parse JSON output."""
    cmd = ["twak"] + args + ["--output", "json"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8",
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip() or f"Exit code {result.returncode}"}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": f"TWAK CLI timeout after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse failed: {e}", "raw": result.stdout[:200]}
    except FileNotFoundError:
        return {"error": "TWAK CLI not found — install with: npm install -g @trustwallet/agent-kit"}
    except Exception as e:
        return {"error": str(e)}


def _call_mcp(action: str, params: dict) -> dict:
    """Call TWAK via MCP server."""
    import requests
    try:
        r = requests.post(
            f"{TWAK_MCP_URL}/mcp",
            json={"action": action, "params": params},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _call(action: str, cli_args: list[str], mcp_params: dict) -> dict:
    """Dispatch to CLI or MCP based on TWAK_MODE."""
    if TWAK_MODE == "mcp":
        return _call_mcp(action, mcp_params)
    return _run_cli(cli_args)


def get_balance(token_address: Optional[str] = None) -> list[BalanceResult]:
    """Get wallet balance for all tokens or a specific token."""
    cli_args = ["wallet", "balance"]
    mcp_params = {}
    if token_address:
        cli_args += ["--token", token_address]
        mcp_params["token"] = token_address

    raw = _call("wallet_balance", cli_args, mcp_params)
    if "error" in raw:
        print(f"[TWAK] balance error: {raw['error']}")
        return []

    results = []
    items = raw if isinstance(raw, list) else raw.get("balances", [raw])
    for item in items:
        results.append(BalanceResult(
            token_address = item.get("address", ""),
            symbol        = item.get("symbol", "?"),
            balance       = float(item.get("balance", 0)),
            value_usd     = float(item.get("value_usd", 0)),
        ))
    return results


def get_portfolio_value() -> float:
    """Return total portfolio value in USD."""
    balances = get_balance()
    return sum(b.value_usd for b in balances)


def execute_swap(
    from_symbol: str,
    to_symbol: str,
    amount_usd: float,
    slippage_pct: float = 1.0,
    dry_run: bool = False,
) -> SwapResult:
    """
    Execute a token swap via TWAK.
    dry_run=True (or DRY_RUN=true env var) returns a simulated SwapResult
    without calling the TWAK CLI or MCP — no gas, no on-chain state change.
    """
    _dry = dry_run or os.getenv("DRY_RUN", "false").strip().lower() == "true"

    if _dry:
        # Simulate: apply slippage, estimate 0.1% fee, return fake tx hash
        simulated_out = amount_usd * (1 - slippage_pct / 100) * 0.999
        sim_hash = f"0xDRYRUN{'0'*56}{int(time.time()) % 10000:04d}"
        print(
            f"[TWAK DRY-RUN] SIMULATED swap {from_symbol} -> {to_symbol} "
            f"${amount_usd:.2f} | out≈${simulated_out:.2f} | "
            f"slippage={slippage_pct}% | tx={sim_hash}"
        )
        return SwapResult(
            success    = True,
            tx_hash    = sim_hash,
            amount_in  = amount_usd,
            amount_out = simulated_out,
            fee_usd    = amount_usd * 0.001,
            gas_used   = 150000,
            error      = None,
        )

    cli_args = [
        "trade", "swap",
        "--from", from_symbol,
        "--to", to_symbol,
        "--amount", str(amount_usd),
        "--slippage", str(slippage_pct),
    ]
    mcp_params = {
        "from_token": from_symbol,
        "to_token": to_symbol,
        "amount_usd": amount_usd,
        "slippage": slippage_pct,
    }

    raw = _call("trade_swap", cli_args, mcp_params)

    if "error" in raw:
        return SwapResult(
            success=False, tx_hash=None,
            amount_in=amount_usd, amount_out=0.0,
            fee_usd=0.0, gas_used=None,
            error=raw["error"],
        )

    return SwapResult(
        success    = raw.get("success", True),
        tx_hash    = raw.get("tx_hash") or raw.get("txHash"),
        amount_in  = float(raw.get("amount_in", amount_usd)),
        amount_out = float(raw.get("amount_out", 0)),
        fee_usd    = float(raw.get("fee_usd", 0)),
        gas_used   = raw.get("gas_used"),
        error      = raw.get("error"),
    )


def register_competition() -> dict:
    """
    Register the agent wallet in the BNB Hack competition contract.
    Calls: twak compete register OR MCP action: competition_register

    Competition contract: 0x212c61b9b72c95d95bf29cf032f5e5635629aed5 (BSC)
    Deadline: June 22, 2026 (before trading window opens)
    """
    print("[TWAK] Registering in BNB Hack competition...")
    raw = _call("competition_register", ["compete", "register"], {"action": "register"})
    if "error" in raw:
        print(f"[TWAK] Registration failed: {raw['error']}")
    else:
        print(f"[TWAK] Registration successful: {raw}")
    return raw


def get_competition_status() -> CompetitionStatus:
    """Get current competition rank and portfolio status."""
    raw = _call("competition_status", ["compete", "status"], {"action": "status"})
    return CompetitionStatus(
        registered          = raw.get("registered", False),
        wallet_address      = raw.get("wallet", TWAK_WALLET),
        portfolio_value_usd = float(raw.get("portfolio_value_usd", 0)),
        rank                = raw.get("rank"),
        total_return_pct    = float(raw.get("total_return_pct", 0)),
        trade_count         = int(raw.get("trade_count", 0)),
    )


def get_wallet_address() -> str:
    """Get the agent wallet address."""
    if TWAK_WALLET:
        return TWAK_WALLET
    raw = _run_cli(["wallet", "address"])
    return raw.get("address", "")
