from collections import deque
from decimal import Decimal
from statistics import mean

from hummingbot.core.data_type.common import OrderType
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class BuyLowSellHighV3(ScriptStrategyBase):
    """
    Enhanced version of buy_low_sell_high with minimal changes:
    - Uses mid price instead of ask price for MA calculation
    - True cross detection instead of regime detection
    - Simple cooldown to reduce churn
    - Basic TP/SL for risk management
    """
    markets = {"binance_paper_trade": {"BTC-USDT"}}
    #: pingpong is a variable to allow alternating between buy & sell signals
    pingpong = 0
    de_fast_ma = deque([], maxlen=5)
    de_slow_ma = deque([], maxlen=20)
    
    # Minimal additions for safety
    last_trade_time = 0
    cooldown_seconds = 60
    entry_price = None
    take_profit_pct = Decimal("0.005")  # 0.5%
    stop_loss_pct = Decimal("0.005")    # 0.5%
    prev_fast_ma = None
    prev_slow_ma = None

    def get_mid_price(self):
        """Get mid price instead of ask price to avoid bias"""
        connector = self.connectors["binance_paper_trade"]
        try:
            ask = connector.get_price("BTC-USDT", True)
            bid = connector.get_price("BTC-USDT", False)
            if ask and bid:
                return (ask + bid) / 2
        except:
            pass
        # Fallback to ask if mid not available
        return connector.get_price("BTC-USDT", True)

    def on_tick(self):
        p = self.get_mid_price()
        if not p:
            return

        # Original MA calculation logic
        self.de_fast_ma.append(p)
        self.de_slow_ma.append(p)
        
        if len(self.de_fast_ma) < 5 or len(self.de_slow_ma) < 20:
            return
            
        fast_ma = mean(self.de_fast_ma)
        slow_ma = mean(self.de_slow_ma)
        
        current_time = self.current_timestamp
        in_cooldown = (current_time - self.last_trade_time) < self.cooldown_seconds

        # Risk management for open position
        if self.pingpong == 1 and self.entry_price:
            pnl_pct = (p - self.entry_price) / self.entry_price
            if pnl_pct >= self.take_profit_pct or pnl_pct <= -self.stop_loss_pct:
                # Exit on TP/SL
                self.sell(
                    connector_name="binance_paper_trade",
                    trading_pair="BTC-USDT",
                    amount=Decimal(0.01),
                    order_type=OrderType.MARKET,
                )
                self.logger().info(f"Exit on TP/SL: PnL {pnl_pct:.4f}")
                self.pingpong = 0
                self.entry_price = None
                self.last_trade_time = current_time
                return

        # Enhanced cross detection (check for actual cross vs regime)
        golden_cross = False
        death_cross = False
        
        if self.prev_fast_ma and self.prev_slow_ma:
            # True cross: fast was below, now above (golden)
            if self.prev_fast_ma <= self.prev_slow_ma and fast_ma > slow_ma:
                golden_cross = True
            # True cross: fast was above, now below (death)  
            elif self.prev_fast_ma >= self.prev_slow_ma and fast_ma < slow_ma:
                death_cross = True

        # Original logic structure with enhancements
        if golden_cross and self.pingpong == 0 and not in_cooldown:
            self.buy(
                connector_name="binance_paper_trade",
                trading_pair="BTC-USDT",
                amount=Decimal(0.01),
                order_type=OrderType.MARKET,
            )
            self.logger().info(f"0.01 BTC bought at {p:.2f}")
            self.pingpong = 1
            self.entry_price = p
            self.last_trade_time = current_time

        elif death_cross and self.pingpong == 1 and not in_cooldown:
            self.sell(
                connector_name="binance_paper_trade",
                trading_pair="BTC-USDT",
                amount=Decimal(0.01),
                order_type=OrderType.MARKET,
            )
            pnl = (p - self.entry_price) if self.entry_price else Decimal(0)
            self.logger().info(f"0.01 BTC sold at {p:.2f}, PnL: {pnl:.4f}")
            self.pingpong = 0
            self.entry_price = None
            self.last_trade_time = current_time

        else:
            self.logger().info(f"Fast: {fast_ma:.2f}, Slow: {slow_ma:.2f}, Wait for signal")

        # Store for next iteration
        self.prev_fast_ma = fast_ma
        self.prev_slow_ma = slow_ma
