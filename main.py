"""
SentinelAI — Autonomous BNB Chain Trading Agent
BNB Hack: AI Trading Agent Edition | Track 1: Autonomous Trading Agents

Multi-agent architecture:
  Orchestrator (Opus 4.8)  — strategic coordinator, adaptive thinking
  MarketIntelAgent (Sonnet 4.6) — CMC data analysis, signal generation
  SecurityAuditAgent (Haiku 4.5) — fast BEP-20 contract honeypot scan
  RiskGuardAgent (Sonnet 4.6)   — portfolio risk + position sizing
  ExecutionAgent (Haiku 4.5)    — TWAK swap execution

Usage:
  python main.py                     # run live trading loop
  python main.py --dry-run           # simulate without executing trades
  python main.py --register          # register agent in competition contract
  python main.py --audit 0xADDRESS  # audit a single BEP-20 contract
  python main.py --cycle             # run a single cycle and exit
  python main.py --status            # show portfolio status
"""
import argparse
import json
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sentinel.main")

CYCLE_INTERVAL_SECONDS = int(os.getenv("CYCLE_INTERVAL", "300"))  # 5 min default
START_PORTFOLIO_VALUE  = float(os.getenv("START_VALUE", "100.0"))


def cmd_register():
    """Register the agent wallet in the BNB Hack competition contract."""
    from trading_engine.twak_client import register_competition, get_wallet_address
    wallet = get_wallet_address()
    print(f"\nSentinelAI — Competition Registration")
    print(f"  Agent wallet: {wallet or '[not configured — set TWAK_WALLET env var]'}")
    print(f"  Contract:     0x212c61b9b72c95d95bf29cf032f5e5635629aed5 (BSC)")
    print(f"  Deadline:     June 22, 2026 (before trading window)")
    print()
    result = register_competition()
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        print("  Make sure TWAK is installed and wallet is configured.")
        sys.exit(1)
    print(f"  TX hash: {result.get('tx_hash', result)}")
    print("  Registration complete! Trading window opens June 22, 2026.")


def cmd_audit(address: str):
    """Audit a single BEP-20 contract address."""
    from agent.security_audit import audit_contract
    print(f"\nSentinelAI Security Audit")
    print(f"  Contract: {address}")
    print(f"  Fetching source from BSCScan...")
    verdict = audit_contract(address)
    print(json.dumps(verdict, indent=2))


def cmd_status():
    """Show current portfolio status."""
    from trading_engine.portfolio import Portfolio
    from trading_engine.twak_client import get_competition_status
    portfolio = Portfolio(start_value_usd=START_PORTFOLIO_VALUE)
    comp = get_competition_status()
    print("\nSentinelAI Portfolio Status")
    print(f"  Wallet:          {comp.wallet_address}")
    print(f"  Portfolio value: ${comp.portfolio_value_usd:.2f}")
    print(f"  Total return:    {comp.total_return_pct:+.2f}%")
    print(f"  Competition rank: {comp.rank or 'not ranked yet'}")
    print(f"  Trades today:    {comp.trade_count}")
    print(f"  Registered:      {comp.registered}")


def cmd_cycle(dry_run: bool = False):
    """Run a single trading cycle."""
    from trading_engine.portfolio import Portfolio
    from agent.orchestrator import Orchestrator

    portfolio    = Portfolio(start_value_usd=START_PORTFOLIO_VALUE)
    orchestrator = Orchestrator(portfolio=portfolio, dry_run=dry_run)
    result       = orchestrator.run_cycle()
    print(json.dumps(result, indent=2, default=str))


def cmd_run(dry_run: bool = False):
    """Main autonomous trading loop."""
    from trading_engine.portfolio import Portfolio
    from agent.orchestrator import Orchestrator

    logger.info("=" * 60)
    logger.info("SentinelAI — Autonomous BNB Chain Trading Agent")
    logger.info(f"  Mode:     {'DRY RUN' if dry_run else 'LIVE TRADING'}")
    logger.info(f"  Interval: {CYCLE_INTERVAL_SECONDS}s ({CYCLE_INTERVAL_SECONDS // 60}m)")
    logger.info(f"  Models:   Opus 4.8 + Sonnet 4.6 x2 + Haiku 4.5 x2")
    logger.info("=" * 60)

    portfolio    = Portfolio(start_value_usd=START_PORTFOLIO_VALUE)
    orchestrator = Orchestrator(portfolio=portfolio, dry_run=dry_run)

    cycle_num = 0
    while True:
        cycle_num += 1
        t_start = time.time()
        try:
            result = orchestrator.run_cycle()
            executions = result.get("executions", [])
            executed   = [e for e in executions if e.get("action") == "EXECUTED"]
            blocked    = [e for e in executions if e.get("action") == "BLOCKED"]
            rejected   = [e for e in executions if e.get("action") == "REJECTED"]

            logger.info(
                f"Cycle {cycle_num} | {result.get('action')} | "
                f"F&G={result.get('fear_greed', '?'):.0f} | "
                f"executed={len(executed)} blocked={len(blocked)} rejected={len(rejected)} | "
                f"portfolio=${result.get('portfolio', {}).get('total_value_usd', 0):.2f}"
            )

            if executed:
                for e in executed:
                    tx = e.get("tx_hash", "?")
                    logger.info(f"  TRADE: {e['symbol']} {e.get('direction','?')} ${e.get('amount_usd',0):.2f} | tx={tx}")

        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break
        except Exception as e:
            logger.error(f"Cycle {cycle_num} error: {e}", exc_info=True)

        elapsed = time.time() - t_start
        sleep_for = max(10, CYCLE_INTERVAL_SECONDS - elapsed)
        logger.info(f"Next cycle in {sleep_for:.0f}s")
        try:
            time.sleep(sleep_for)
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break


def main():
    parser = argparse.ArgumentParser(description="SentinelAI — BNB Chain Autonomous Trading Agent")
    parser.add_argument("--dry-run",  action="store_true", help="Simulate trades without executing")
    parser.add_argument("--register", action="store_true", help="Register in competition contract")
    parser.add_argument("--audit",    metavar="ADDRESS",   help="Audit a BEP-20 contract address")
    parser.add_argument("--cycle",    action="store_true", help="Run single cycle and exit")
    parser.add_argument("--status",   action="store_true", help="Show portfolio status")
    args = parser.parse_args()

    os.makedirs("data", exist_ok=True)

    if args.register:
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
