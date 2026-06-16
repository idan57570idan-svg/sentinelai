"""
Portfolio tracker — maintains real-time state, PnL, and position records.
Reads balance from TWAK and tracks competition metrics.
"""
from __future__ import annotations

import json
import time
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

from .twak_client import get_balance, BalanceResult
from .guardrails import PortfolioState

_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio_state.json")


@dataclass
class Position:
    symbol: str
    token_address: str
    amount: float
    avg_buy_price_usd: float
    current_price_usd: float
    opened_at: float

    @property
    def value_usd(self) -> float:
        return self.amount * self.current_price_usd

    @property
    def unrealized_pnl_usd(self) -> float:
        return (self.current_price_usd - self.avg_buy_price_usd) * self.amount

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.avg_buy_price_usd <= 0:
            return 0.0
        return (self.current_price_usd - self.avg_buy_price_usd) / self.avg_buy_price_usd * 100


@dataclass
class TradeRecord:
    symbol: str
    direction: str          # BUY | SELL
    amount_usd: float
    price_usd: float
    tx_hash: Optional[str]
    fee_usd: float
    timestamp: float
    pnl_usd: float = 0.0   # realized PnL for SELL trades


class Portfolio:
    def __init__(self, start_value_usd: float = 100.0):
        self.start_value_usd   = start_value_usd
        self.peak_value_usd    = start_value_usd
        self.day_start_value   = start_value_usd
        self.day_reset_ts      = time.time()
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[TradeRecord] = []
        self.realized_pnl_usd  = 0.0
        self.daily_pnl_usd     = 0.0
        self.last_trade_time: Dict[str, float] = {}
        self.trade_count_today = 0
        self._load_state()

    def refresh_from_twak(self, price_map: Dict[str, float]) -> float:
        """Pull live balances from TWAK and update positions."""
        balances: List[BalanceResult] = get_balance()
        total = 0.0
        for b in balances:
            sym = b.symbol.upper()
            price = price_map.get(sym, b.value_usd / b.balance if b.balance > 0 else 0)
            total += b.value_usd
            if sym in self.positions:
                self.positions[sym].amount = b.balance
                self.positions[sym].current_price_usd = price
            elif b.balance > 0 and b.value_usd > 0.5:
                self.positions[sym] = Position(
                    symbol=sym, token_address=b.token_address,
                    amount=b.balance, avg_buy_price_usd=price,
                    current_price_usd=price, opened_at=time.time(),
                )

        if total > self.peak_value_usd:
            self.peak_value_usd = total

        # Daily reset check
        now = time.time()
        if now - self.day_reset_ts >= 86400:
            self.day_start_value  = total
            self.daily_pnl_usd    = 0.0
            self.trade_count_today = 0
            self.day_reset_ts     = now

        return total

    def record_trade(self, record: TradeRecord):
        self.trade_history.append(record)
        self.last_trade_time[record.symbol] = record.timestamp
        self.trade_count_today += 1
        if record.direction == "SELL":
            self.realized_pnl_usd += record.pnl_usd
            self.daily_pnl_usd += record.pnl_usd
        self._save_state()

    def get_state(self, current_value: float) -> PortfolioState:
        return PortfolioState(
            total_value_usd      = current_value,
            peak_value_usd       = self.peak_value_usd,
            start_value_usd      = self.start_value_usd,
            open_positions       = len([p for p in self.positions.values() if p.amount > 0]),
            daily_realized_pnl_usd = self.daily_pnl_usd,
            day_start_value_usd  = self.day_start_value,
            last_trade_time      = dict(self.last_trade_time),
            trade_count_today    = self.trade_count_today,
        )

    def summary(self, current_value: float) -> dict:
        state = self.get_state(current_value)
        return {
            "total_value_usd":    round(current_value, 2),
            "start_value_usd":    round(self.start_value_usd, 2),
            "total_return_pct":   round(state.total_return_pct, 2),
            "drawdown_pct":       round(state.drawdown_pct, 2),
            "daily_pnl_pct":      round(state.daily_pnl_pct, 2),
            "realized_pnl_usd":   round(self.realized_pnl_usd, 2),
            "open_positions":     state.open_positions,
            "trade_count_today":  self.trade_count_today,
            "total_trades":       len(self.trade_history),
        }

    def _save_state(self):
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        state = {
            "start_value_usd":   self.start_value_usd,
            "peak_value_usd":    self.peak_value_usd,
            "day_start_value":   self.day_start_value,
            "day_reset_ts":      self.day_reset_ts,
            "realized_pnl_usd":  self.realized_pnl_usd,
            "daily_pnl_usd":     self.daily_pnl_usd,
            "last_trade_time":   self.last_trade_time,
            "trade_count_today": self.trade_count_today,
            "trade_history":     [asdict(t) for t in self.trade_history[-200:]],
        }
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        if not os.path.exists(_STATE_FILE):
            return
        try:
            with open(_STATE_FILE) as f:
                s = json.load(f)
            self.start_value_usd    = s.get("start_value_usd", self.start_value_usd)
            self.peak_value_usd     = s.get("peak_value_usd", self.peak_value_usd)
            self.day_start_value    = s.get("day_start_value", self.day_start_value)
            self.day_reset_ts       = s.get("day_reset_ts", self.day_reset_ts)
            self.realized_pnl_usd   = s.get("realized_pnl_usd", 0.0)
            self.daily_pnl_usd      = s.get("daily_pnl_usd", 0.0)
            self.last_trade_time    = s.get("last_trade_time", {})
            self.trade_count_today  = s.get("trade_count_today", 0)
            for t in s.get("trade_history", []):
                self.trade_history.append(TradeRecord(**t))
        except Exception as e:
            print(f"[Portfolio] State load failed: {e}")
