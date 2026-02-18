from collections import deque
from decimal import Decimal, getcontext
from typing import Optional

from hummingbot.core.data_type.common import OrderType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class BuyLowSellHighV2(ScriptStrategyBase):
    """
    Directional MA cross script with:
    - Mid-price signals (avoid side bias)
    - True cross detection (zero-cross of fast-slow)
    - Cooldown and minimum MA gap threshold
    - Simple TP/SL for exits
    - Parameterized lengths, size, thresholds
    - Basic realized PnL logging
    """

    # Configurable parameters
    connector_name: str = "binance_paper_trade"
    trading_pair: str = "BTC-USDT"
    amount: Decimal = Decimal("0.01")

    fast_len: int = 9
    slow_len: int = 21

    cooldown_sec: int = 90  # minimum seconds between trades
    min_diff_ratio: Decimal = Decimal("0.0005")  # 0.05% of price
    take_profit_ratio: Decimal = Decimal("0.004")  # 0.4%
    stop_loss_ratio: Decimal = Decimal("0.004")  # 0.4%

    # State
    _de_fast = deque(maxlen=fast_len)
    _de_slow = deque(maxlen=slow_len)
    _prev_diff: Optional[Decimal] = None
    _in_position: bool = False
    _entry_price: Optional[Decimal] = None
    _last_trade_ts: float = 0.0
    _realized_pnl_quote: Decimal = Decimal("0")

    def _get_mid_price(self) -> Optional[Decimal]:
        conn = self.connectors.get(self.connector_name)
        if conn is None:
            return None
        # Prefer connector's mid if available; fall back to (bid+ask)/2
        try:
            mp = conn.get_mid_price(self.trading_pair)
            if mp is not None:
                return Decimal(str(mp))
        except Exception:
            pass
        try:
            ask = conn.get_price(self.trading_pair, True)
            bid = conn.get_price(self.trading_pair, False)
            if ask is not None and bid is not None:
                return (Decimal(str(ask)) + Decimal(str(bid))) / Decimal("2")
        except Exception:
            pass
        return None

    def _ma(self, values: deque) -> Optional[Decimal]:
        if not values or len(values) == 0:
            return None
        s = sum(values)
        return s / Decimal(len(values))

    def on_tick(self):
        getcontext().prec = 28
        mid = self._get_mid_price()
        if mid is None:
            return

        # Append new sample
        self._de_fast.append(Decimal(mid))
        self._de_slow.append(Decimal(mid))

        if len(self._de_fast) < self.fast_len or len(self._de_slow) < self.slow_len:
            return  # warm-up

        fast_ma = self._ma(self._de_fast)
        slow_ma = self._ma(self._de_slow)
        if fast_ma is None or slow_ma is None:
            return

        diff = fast_ma - slow_ma
        now = self.current_timestamp
        in_cooldown = (now - self._last_trade_ts) < self.cooldown_sec
        gap_ok = (abs(diff) / mid) >= self.min_diff_ratio

        # Exit logic if in position (manage risk first)
        if self._in_position and self._entry_price is not None:
            up_ratio = (mid / self._entry_price) - Decimal("1")
            down_ratio = (self._entry_price / mid) - Decimal("1")
            tp_hit = up_ratio >= self.take_profit_ratio
            sl_hit = down_ratio >= self.stop_loss_ratio
            cross_down = (self._prev_diff is not None and self._prev_diff > 0 and diff <= 0 and gap_ok)

            if (tp_hit or sl_hit or (cross_down and not in_cooldown)):
                # Close long
                self.sell(self.connector_name, self.trading_pair, self.amount, OrderType.MARKET)
                realized = (mid - self._entry_price) * self.amount
                self._realized_pnl_quote += realized
                self.logger().info(
                    f"Exit LONG | mid={mid:.4f} entry={self._entry_price:.4f} pnl={realized:.4f} cum_pnl={self._realized_pnl_quote:.4f}"
                )
                self._in_position = False
                self._entry_price = None
                self._last_trade_ts = now

        # Entry logic if flat
        if not self._in_position and not in_cooldown:
            cross_up = (self._prev_diff is not None and self._prev_diff <= 0 and diff > 0 and gap_ok)
            if cross_up:
                self.buy(self.connector_name, self.trading_pair, self.amount, OrderType.MARKET)
                self._entry_price = mid
                self._in_position = True
                self._last_trade_ts = now
                self.logger().info(
                    f"Enter LONG | mid={mid:.4f} fast={fast_ma:.4f} slow={slow_ma:.4f} diff={diff:.6f}"
                )

        # Update prev diff and log heartbeat occasionally
        self._prev_diff = diff
        if int(now) % 30 == 0:
            self.logger().info(
                f"HB | mid={mid:.4f} fast={fast_ma:.4f} slow={slow_ma:.4f} diff={diff:.6f} in_pos={self._in_position} pnl={self._realized_pnl_quote:.4f}"
            )
