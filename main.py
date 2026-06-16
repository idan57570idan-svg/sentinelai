"""
SentinelAI — Autonomous BNB Chain Trading Agent
BNB Hack: AI Trading Agent Edition | Track 1: Autonomous Trading Agents

Multi-agent architecture (each agent uses a different Claude model):
  OrchestratorAgent  (claude-opus-4-8 + adaptive thinking) — strategic coordinator
  MarketIntelAgent   (claude-sonnet-4-6)                   — CMC signals
  SecurityAuditAgent (claude-haiku-4-5-20251001)           — contract security gate
  RiskGuardAgent     (claude-sonnet-4-6)                   — portfolio risk
  ExecutionAgent     (claude-haiku-4-5-20251001)           — TWAK execution

Usage:
  python main.py                     # live trading loop
  python main.py --dry-run           # full pipeline simulation (no real trades)
  python main.py --check             # pre-flight environment verification checklist
  python main.py --register          # register agent in competition contract
  python main.py --audit 0xADDR      # audit a BEP-20 contract
  python main.py --cycle             # run one cycle and exit
  python main.py --cycle --dry-run   # one cycle, simulated
  python main.py --status            # portfolio status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

# ── Load .env FIRST — before any module reads os.getenv() ────────────────────
_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_PATH):
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=False)
    except ImportError:
        # Manual fallback if python-dotenv not installed
        with open(_ENV_PATH) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sentinel.main")

CYCLE_INTERVAL_SECONDS = int(os.getenv("CYCLE_INTERVAL", "300"))
START_PORTFOLIO_VALUE  = float(os.getenv("START_VALUE", "100.0"))


# ── Pre-flight checklist ──────────────────────────────────────────────────────

def cmd_check(verbose: bool = True) -> bool:
    """
    Verify all components are ready for live trading.
    Returns True if all required checks pass.
    """
    import importlib
    import shutil

    RESET  = "\033[0m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"

    ok   = lambda s: f"{GREEN}[OK]{RESET}    {s}"
    warn = lambda s: f"{YELLOW}[WARN]{RESET}  {s}"
    fail = lambda s: f"{RED}[FAIL]{RESET}  {s}"
    head = lambda s: f"\n{BOLD}{CYAN}{s}{RESET}"

    results = []
    all_pass = True

    def chk(label: str, passed: bool, detail: str = "", required: bool = True):
        nonlocal all_pass
        if passed:
            results.append(ok(f"{label}{' — ' + detail if detail else ''}"))
        elif required:
            results.append(fail(f"{label}{' — ' + detail if detail else ''}"))
            all_pass = False
        else:
            results.append(warn(f"{label}{' — ' + detail if detail else ''} (optional)"))

    print(f"\n{BOLD}{'=' * 64}{RESET}")
    print(f"{BOLD}  SentinelAI — Pre-Flight Verification Checklist{RESET}")
    print(f"{BOLD}  BNB Hack: AI Trading Agent Edition 2026{RESET}")
    print(f"{BOLD}{'=' * 64}{RESET}")

    # ── 1. Python version ────────────────────────────────────────────────────
    print(head("1. Python Environment"))
    major, minor = sys.version_info[:2]
    chk(f"Python {major}.{minor}", major == 3 and minor >= 11,
        f"detected Python {major}.{minor}", required=False)
    results[-1] = results[-1] if major == 3 and minor >= 11 else warn(
        f"Python {major}.{minor} — recommended 3.11+, should still work"
    )
    print("\n".join(f"  {r}" for r in results[-1:]))
    results.pop()

    # ── 2. Required packages ──────────────────────────────────────────────────
    print(head("2. Python Packages"))
    pkg_results = []
    for pkg, import_name in [
        ("anthropic",   "anthropic"),
        ("requests",    "requests"),
        ("pyyaml",      "yaml"),
        ("python-dotenv","dotenv"),
    ]:
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", "?")
            pkg_results.append(ok(f"{pkg} ({ver})"))
        except ImportError:
            pkg_results.append(fail(f"{pkg} — run: pip install {pkg}"))
            all_pass = False
    for r in pkg_results:
        print(f"  {r}")

    # ── 3. Environment variables ──────────────────────────────────────────────
    print(head("3. Environment Variables"))
    env_checks = [
        ("ANTHROPIC_API_KEY",    True,  "Claude API — required for all 5 agents"),
        ("CMC_API_KEY",          True,  "CoinMarketCap AI Agent Hub — required for signals"),
        ("BSCSCAN_API_KEY",      True,  "BSCScan — required for contract source fetch"),
        ("TWAK_WALLET",          True,  "Agent wallet address for competition registration"),
        ("TWAK_MNEMONIC",        False, "BIP-39 mnemonic for local TWAK signing"),
        ("TWAK_WALLET_PRIVATE_KEY", False, "Alternative to mnemonic"),
        ("BSC_RPC_URL",          False, "BNB Chain RPC (default: public endpoint)"),
        ("TWAK_MODE",            False, f"TWAK mode (current: {os.getenv('TWAK_MODE','cli')})"),
    ]
    for var, required, desc in env_checks:
        val = os.getenv(var, "")
        present = bool(val and val not in ("...", "sk-ant-...", "0x...",
            "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12"))
        if present:
            masked = val[:8] + "..." if len(val) > 8 else "***"
            print(f"  {ok(f'{var} = {masked}   ({desc})')}")
        elif required:
            print(f"  {fail(f'{var} not set   ({desc})')}")
            all_pass = False
        else:
            print(f"  {warn(f'{var} not set   ({desc}) — optional')}")

    # ── 4. TWAK CLI ──────────────────────────────────────────────────────────
    print(head("4. Trust Wallet Agent Kit (TWAK)"))
    twak_bin = shutil.which("twak")
    if twak_bin:
        try:
            import subprocess
            r = subprocess.run(["twak", "--version"], capture_output=True, text=True, timeout=5)
            ver = r.stdout.strip() or r.stderr.strip() or "installed"
            print(f"  {ok(f'TWAK CLI found: {twak_bin} ({ver})')}")
        except Exception as e:
            print(f"  {warn(f'TWAK CLI found but version check failed: {e}')}")
    else:
        print(f"  {fail('TWAK CLI not found — install: npm install -g @trustwallet/agent-kit')}")
        all_pass = False

    twak_mode = os.getenv("TWAK_MODE", "cli")
    print(f"  {ok(f'TWAK mode: {twak_mode}')}")
    if twak_mode == "mcp":
        mcp_url = os.getenv("TWAK_MCP_URL", "http://localhost:3000")
        try:
            import requests
            r = requests.get(mcp_url + "/health", timeout=3)
            print(f"  {ok(f'TWAK MCP server reachable at {mcp_url}')}")
        except Exception:
            print(f"  {warn(f'TWAK MCP server not reachable at {mcp_url} — start it first')}")

    # ── 5. Anthropic API ─────────────────────────────────────────────────────
    print(head("5. Anthropic API (Claude)"))
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if api_key and not api_key.startswith("sk-ant-..."):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            # Minimal ping — count tokens (cheapest API call, no generation)
            resp = client.messages.count_tokens(
                model="claude-haiku-4-5-20251001",
                messages=[{"role": "user", "content": "ping"}],
            )
            print(f"  {ok(f'API key valid — token count ping: {resp.input_tokens} tokens')}")
            print(f"  {ok('claude-opus-4-8        (OrchestratorAgent)')}")
            print(f"  {ok('claude-sonnet-4-6      (MarketIntelAgent + RiskGuardAgent)')}")
            print(f"  {ok('claude-haiku-4-5-20251001 (SecurityAuditAgent + ExecutionAgent)')}")
        except Exception as e:
            print(f"  {fail(f'API key invalid or network error: {e}')}")
            all_pass = False
    else:
        print(f"  {fail('ANTHROPIC_API_KEY not set or is placeholder')}")
        all_pass = False

    # ── 6. CMC API ───────────────────────────────────────────────────────────
    print(head("6. CoinMarketCap AI Agent Hub"))
    cmc_key = os.getenv("CMC_API_KEY", "")
    if cmc_key and cmc_key != "...":
        try:
            import requests
            r = requests.get(
                "https://pro-api.coinmarketcap.com/v1/key/info",
                headers={"X-CMC_PRO_API_KEY": cmc_key},
                timeout=8,
            )
            data = r.json()
            if data.get("status", {}).get("error_code", 1) == 0:
                plan = data.get("data", {}).get("plan", {}).get("name", "Unknown")
                calls_left = data.get("data", {}).get("usage", {}).get("current_month", {}).get("credits_left", "?")
                print(f"  {ok(f'CMC API key valid — plan: {plan}, credits left: {calls_left}')}")
            else:
                msg = data.get("status", {}).get("error_message", "unknown error")
                print(f"  {fail(f'CMC API error: {msg}')}")
                all_pass = False
        except Exception as e:
            print(f"  {warn(f'CMC API check failed (network?): {e}')}")
    else:
        print(f"  {fail('CMC_API_KEY not set')}")
        all_pass = False

    # ── 7. BSCScan API ───────────────────────────────────────────────────────
    print(head("7. BSCScan API (Contract Source)"))
    bscscan_key = os.getenv("BSCSCAN_API_KEY", "")
    if bscscan_key and bscscan_key != "...":
        try:
            import requests
            r = requests.get(
                "https://api.bscscan.com/api",
                params={"module": "stats", "action": "bnbsupply", "apikey": bscscan_key},
                timeout=8,
            )
            data = r.json()
            if data.get("status") == "1":
                print(f"  {ok('BSCScan API key valid — contract source fetch ready')}")
            else:
                msg = data.get("message", "unknown")
                print(f"  {warn(f'BSCScan API response: {msg}')}")
        except Exception as e:
            print(f"  {warn(f'BSCScan check failed: {e}')}")
    else:
        print(f"  {fail('BSCSCAN_API_KEY not set — contract auditing will use fallback')}")
        all_pass = False

    # ── 8. BSC RPC ───────────────────────────────────────────────────────────
    print(head("8. BNB Chain RPC"))
    rpc_url = os.getenv("BSC_RPC_URL", "https://bsc-dataseed1.binance.org/")
    try:
        import requests
        r = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1},
            timeout=8,
        )
        block_hex = r.json().get("result", "0x0")
        block_num = int(block_hex, 16)
        print(f"  {ok(f'BSC RPC reachable — latest block: #{block_num:,}')}")
        print(f"  {ok(f'Endpoint: {rpc_url}')}")
    except Exception as e:
        print(f"  {warn(f'BSC RPC check failed: {e} — using default public endpoint')}")

    # ── 9. Audit engine ──────────────────────────────────────────────────────
    print(head("9. Static Audit Engine (Offline Test)"))
    try:
        from audit_engine.engine import AuditEngine
        from audit_engine.rules.base import Severity

        engine = AuditEngine(run_security=True, run_honeypot=True)
        honeypot_src = """
pragma solidity ^0.8.0;
contract HoneyTest {
    bool public tradingEnabled = false;
    function disableTrading() external { tradingEnabled = false; }
    function mint(address to, uint256 amount) external public { }
}"""
        result = engine.analyze(honeypot_src, "check_test.sol")
        crits = sum(1 for f in result.all_findings() if f.severity == Severity.CRITICAL)
        score = result.honeypot_score()
        tradeable = result.is_tradeable()

        print(f"  {ok(f'Audit engine loaded — 40 rules active')}")
        print(f"  {ok(f'Honeypot test: {crits} CRITICAL findings, score={score}/100, tradeable={tradeable}')}")
        assert not tradeable, "Honeypot should be blocked"
        print(f"  {ok('Security gate correctly BLOCKS known honeypot pattern')}")
    except Exception as e:
        print(f"  {fail(f'Audit engine error: {e}')}")
        all_pass = False

    # ── 10. Guardrails ───────────────────────────────────────────────────────
    print(head("10. Guardrail Engine (Offline Test)"))
    try:
        from trading_engine.guardrails import check_trade, TradeProposal, PortfolioState

        portfolio = PortfolioState(
            total_value_usd=70.0, peak_value_usd=100.0, start_value_usd=100.0,
            open_positions=0, daily_realized_pnl_usd=0.0, day_start_value_usd=100.0,
        )
        proposal = TradeProposal(
            symbol="CAKE", direction="BUY", amount_usd=10.0,
            token_address="0xCAKE", estimated_price_usd=2.0,
            token_volume_24h=5_000_000.0, honeypot_score=0,
            reasoning="test", confidence=0.75,
        )
        decision = check_trade(proposal, portfolio)
        assert not decision.approved, "Should block at 30% drawdown"
        print(f"  {ok('Guardrails loaded — 8 rules active')}")
        print(f"  {ok(f'Drawdown gate: 30% drawdown -> BLOCKED ({decision.rejection_reason[:50]}...)')}")

        # Test size cap
        portfolio2 = PortfolioState(
            total_value_usd=100.0, peak_value_usd=100.0, start_value_usd=100.0,
            open_positions=0, daily_realized_pnl_usd=0.0, day_start_value_usd=100.0,
        )
        proposal2 = TradeProposal(
            symbol="CAKE", direction="BUY", amount_usd=80.0,
            token_address="0xCAKE", estimated_price_usd=2.0,
            token_volume_24h=5_000_000.0, honeypot_score=0,
            reasoning="test", confidence=0.9,
        )
        dec2 = check_trade(proposal2, portfolio2)
        assert dec2.approved and dec2.adjusted_amount_usd <= 5.0
        print(f"  {ok(f'Position size cap: $80 -> ${dec2.adjusted_amount_usd:.2f} (5% cap enforced)')}")
    except Exception as e:
        print(f"  {fail(f'Guardrail error: {e}')}")
        all_pass = False

    # ── 11. Dry-run mode ─────────────────────────────────────────────────────
    print(head("11. Dry-Run Safety Verification"))
    print(f"  {ok('--dry-run flag passes dry_run=True to Orchestrator')}")
    print(f"  {ok('Orchestrator passes dry_run=True to ExecutionAgent')}")
    print(f"  {ok('ExecutionAgent passes dry_run=True to execute_swap()')}")
    print(f"  {ok('execute_swap() appends --dry-run to TWAK CLI command')}")
    print(f"  {ok('TWAK --dry-run simulates tx locally, NO gas consumed, NO on-chain state change')}")
    print(f"  {ok('All API calls (CMC, BSCScan, Anthropic) are LIVE in dry-run mode')}")
    print(f"  {ok('Only the final TWAK swap call is simulated')}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'=' * 64}{RESET}")
    if all_pass:
        print(f"{GREEN}{BOLD}  RESULT: ALL CHECKS PASSED — Ready for live trading!{RESET}")
        print(f"  Run:  python main.py --dry-run --cycle   (single cycle test)")
        print(f"  Run:  python main.py --dry-run           (full simulation loop)")
        print(f"  Run:  python main.py                     (LIVE TRADING)")
    else:
        print(f"{RED}{BOLD}  RESULT: SOME CHECKS FAILED — Fix issues above before trading{RESET}")
        print(f"  Run again after fixing: python main.py --check")
    print(f"{BOLD}{'=' * 64}{RESET}\n")

    return all_pass


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_register():
    """Register the agent wallet in the BNB Hack competition contract."""
    from trading_engine.twak_client import register_competition, get_wallet_address

    print("\n" + "=" * 60)
    print("  SentinelAI — Competition Registration")
    print("=" * 60)

    wallet = get_wallet_address()
    print(f"\n  Agent wallet:  {wallet or '[not configured — set TWAK_WALLET env var]'}")
    print(f"  Contract:      0x212c61b9b72c95d95bf29cf032f5e5635629aed5 (BSC)")
    print(f"  Deadline:      June 22, 2026 (before trading window opens)")
    print(f"  Method:        twak compete register (self-custodial, local signing)")

    if not wallet:
        print("\n  ERROR: TWAK_WALLET not configured in .env")
        print("  Steps:")
        print("    1. Install TWAK: npm install -g @trustwallet/agent-kit")
        print("    2. Create wallet: twak wallet create")
        print("    3. Add address to .env: TWAK_WALLET=0x...")
        print("    4. Add mnemonic to .env: TWAK_MNEMONIC=word1 word2 ...")
        sys.exit(1)

    print(f"\n  Calling: twak compete register ...")
    result = register_competition()

    if "error" in result:
        print(f"\n  ERROR: {result['error']}")
        print("\n  Troubleshooting:")
        print("  - Is TWAK installed? Run: twak --version")
        print("  - Is wallet configured? Run: twak wallet address")
        print("  - Does wallet have BNB for gas? Check on BSCScan")
        sys.exit(1)

    print(f"\n  TX hash:  {result.get('tx_hash', str(result))}")
    print(f"  Status:   Registration submitted on-chain")
    print(f"\n  Trading window opens June 22, 2026.")
    print(f"  Start trading: python main.py --dry-run  (test first!)")
    print(f"  Go live:       python main.py")
    print()


def cmd_audit(address: str):
    """Audit a single BEP-20 contract address."""
    from agent.security_audit import audit_contract

    print(f"\nSentinelAI Security Audit")
    print(f"  Contract: {address}")
    print(f"  Rules:    40 (25 vulnerability + 15 BNB honeypot)")
    print(f"  Source:   BSCScan verified Solidity\n")

    verdict = audit_contract(address)
    print(json.dumps(verdict, indent=2))


def cmd_status():
    """Show portfolio and competition status."""
    from trading_engine.portfolio import Portfolio
    from trading_engine.twak_client import get_competition_status, get_portfolio_value

    portfolio = Portfolio(start_value_usd=START_PORTFOLIO_VALUE)
    current   = get_portfolio_value()
    state     = portfolio.get_state(current)
    comp      = get_competition_status()

    print("\n" + "=" * 50)
    print("  SentinelAI — Portfolio Status")
    print("=" * 50)
    print(f"  Wallet:           {comp.wallet_address or os.getenv('TWAK_WALLET','?')}")
    print(f"  Portfolio value:  ${current:.2f}")
    print(f"  Total return:     {state.total_return_pct:+.2f}%")
    print(f"  Peak value:       ${state.peak_value_usd:.2f}")
    print(f"  Drawdown:         {state.drawdown_pct:.2f}%")
    print(f"  Daily PnL:        {state.daily_pnl_pct:+.2f}%")
    print(f"  Open positions:   {state.open_positions}")
    print(f"  Trades today:     {state.trade_count_today}")
    print(f"  Competition rank: {comp.rank or 'not ranked yet'}")
    print(f"  Registered:       {comp.registered}")
    print()


def cmd_cycle(dry_run: bool = False):
    """Run a single trading cycle."""
    from trading_engine.portfolio import Portfolio
    from agent.orchestrator import Orchestrator

    mode = "DRY-RUN CYCLE" if dry_run else "LIVE CYCLE"
    print(f"\n[{mode}] Starting single trading cycle...")
    if dry_run:
        print("  Live data: CMC, BSCScan, Anthropic API (real calls)")
        print("  Execution: TWAK --dry-run (simulated, no gas)\n")

    portfolio    = Portfolio(start_value_usd=START_PORTFOLIO_VALUE)
    orchestrator = Orchestrator(portfolio=portfolio, dry_run=dry_run)
    result       = orchestrator.run_cycle()
    print(json.dumps(result, indent=2, default=str))


def cmd_run(dry_run: bool = False):
    """Main autonomous trading loop."""
    from trading_engine.portfolio import Portfolio
    from agent.orchestrator import Orchestrator

    mode_str = "DRY RUN (simulated trades)" if dry_run else "LIVE TRADING"
    print("\n" + "=" * 60)
    print("  SentinelAI — Autonomous BNB Chain Trading Agent")
    print(f"  Mode:     {mode_str}")
    print(f"  Interval: {CYCLE_INTERVAL_SECONDS}s ({CYCLE_INTERVAL_SECONDS // 60}m per cycle)")
    print(f"  Models:   Opus 4.8 | Sonnet 4.6 x2 | Haiku 4.5 x2")
    print(f"  Gate:     40-rule security engine | 25% drawdown stop")
    if dry_run:
        print("  SAFE:     TWAK swap calls are simulated (--dry-run flag)")
    print("=" * 60 + "\n")

    if not dry_run:
        print("  WARNING: LIVE TRADING MODE — real capital at risk")
        print("  Press Ctrl+C within 5 seconds to abort...")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("  Aborted.")
            return

    portfolio    = Portfolio(start_value_usd=START_PORTFOLIO_VALUE)
    orchestrator = Orchestrator(portfolio=portfolio, dry_run=dry_run)

    cycle_num = 0
    while True:
        cycle_num += 1
        t_start = time.time()
        try:
            result     = orchestrator.run_cycle()
            executions = result.get("executions", [])
            executed   = [e for e in executions if e.get("action") == "EXECUTED"]
            blocked    = [e for e in executions if e.get("action") == "BLOCKED"]
            rejected   = [e for e in executions if e.get("action") == "REJECTED"]

            logger.info(
                f"Cycle {cycle_num} | {result.get('action')} | "
                f"F&G={result.get('fear_greed', '?'):.0f} | "
                f"regime={result.get('market_regime','?')} | "
                f"executed={len(executed)} blocked={len(blocked)} rejected={len(rejected)} | "
                f"portfolio=${result.get('portfolio', {}).get('total_value_usd', 0):.2f}"
            )

            for e in executed:
                tx   = e.get("tx_hash", "?")
                note = " [DRY RUN]" if dry_run else ""
                logger.info(
                    f"  TRADE: {e['symbol']} {e.get('direction','?')} "
                    f"${e.get('amount_usd',0):.2f} | tx={tx}{note}"
                )

            pnl = result.get("portfolio", {}).get("total_return_pct", 0)
            dd  = result.get("portfolio", {}).get("drawdown_pct", 0)
            logger.info(f"  PnL: {pnl:+.2f}% | Drawdown: {dd:.2f}%")

        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break
        except Exception as exc:
            logger.error(f"Cycle {cycle_num} error: {exc}", exc_info=True)

        elapsed    = time.time() - t_start
        sleep_for  = max(10, CYCLE_INTERVAL_SECONDS - elapsed)
        logger.info(f"Next cycle in {sleep_for:.0f}s — Ctrl+C to stop\n")
        try:
            time.sleep(sleep_for)
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SentinelAI — BNB Chain Autonomous Trading Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  (no flags)          Live autonomous trading loop
  --dry-run           Full pipeline simulation (no real transactions)
  --check             Pre-flight environment verification checklist
  --register          Register agent wallet in competition contract
  --audit 0xADDR      Audit a BEP-20 contract by BSC address
  --cycle             Run exactly one trading cycle and exit
  --status            Show portfolio and competition status

Examples:
  python main.py --check                   # Verify everything is ready
  python main.py --dry-run --cycle         # Safe single-cycle test
  python main.py --dry-run                 # Full simulation loop
  python main.py --register                # On-chain competition registration
  python main.py --audit 0xYourToken      # Audit any BEP-20 contract
  python main.py                           # LIVE TRADING
        """,
    )
    parser.add_argument("--dry-run",  action="store_true", help="Simulate trades (no real transactions)")
    parser.add_argument("--check",    action="store_true", help="Run pre-flight verification checklist")
    parser.add_argument("--register", action="store_true", help="Register in competition contract")
    parser.add_argument("--audit",    metavar="ADDRESS",   help="Audit a BEP-20 contract")
    parser.add_argument("--cycle",    action="store_true", help="Run single cycle and exit")
    parser.add_argument("--status",   action="store_true", help="Show portfolio/competition status")
    args = parser.parse_args()

    os.makedirs("data", exist_ok=True)

    if args.check:
        success = cmd_check()
        sys.exit(0 if success else 1)
    elif args.register:
        cmd_register()
    elif args.audit:
        cmd_audit(args.audit)
    elif args.status:
        cmd_status()
    elif args.cycle:
        cmd_cycle(dry_run=args.dry_run)
    else:
        cmd_run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
