"""Backtrader execution and position accounting, separate from market signals."""
import backtrader as bt


class PositionStatistics(bt.Analyzer):
    """Own pending orders and accounting; strategy emits only buy/sell intent."""

    params = dict(stake=100)  # Fixed simulation quantity.

    def __init__(self):
        self.fills = []
        self._fill_sizes = {}
        self.pending = None
        self.entry_count = 0
        self.avg_cost = 0.0
        self.reserve = 0.0
        self._counted = set()
        self.min_position = 0
        self.order_count = 0
        self.strategy.trade_hook = self.on_signal

    def on_signal(self, *, buy, sell):
        s = self.strategy
        if not s.p.trading_enabled:
            return
        if s.position.size < 0:
            raise RuntimeError('Long-only strategy has a negative position')
        if self.pending is not None:
            return
        if sell and s.position.size > 0:
            self.pending = s.close()
        elif buy and not s.position:
            self.pending = s.buy(size=self.p.stake)
        else:
            return
        self.order_count += self.pending is not None

    def notify_order(self, order):
        s = self.strategy
        # Notifications carry cumulative executions: emit only the new fill delta.
        previous_size, previous_notional = self._fill_sizes.get(order.ref, (0, 0.0))
        size = abs(order.executed.size)
        notional = size * order.executed.price
        if size > previous_size:
            self.fills.append(dict(
                date=bt.num2date(order.executed.dt).strftime('%Y-%m-%d'),
                side='BUY' if order.isbuy() else 'SELL',
                price=(notional-previous_notional)/(size-previous_size),
                size=size-previous_size, order_ref=order.ref,
            ))
            self._fill_sizes[order.ref] = (size, notional)
        self.min_position = min(self.min_position, s.position.size)
        if s.position.size < 0:
            raise RuntimeError('Long-only strategy has a negative position')
        if order.executed.size and order.isbuy():
            # A partially filled order counts as one entry, including when cancelled.
            if order.ref not in self._counted:
                self._counted.add(order.ref)
                self.entry_count += 1
            self.avg_cost = s.position.price
        if order.status in (order.Completed, order.Canceled, order.Expired,
                            order.Margin, order.Rejected):
            if self.pending is not None and self.pending.ref == order.ref:
                self.pending = None
        if order.status == order.Completed:
            s.log(f'{"BUY" if order.isbuy() else "SELL"} EXEC '
                  f'{order.executed.size}@{order.executed.price:.2f}')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.entry_count = 0
        self.avg_cost = 0.0

    def get_analysis(self):
        return dict(reserve=self.reserve, position=self.strategy.position.size,
                    avg_cost=self.avg_cost, entry_count=self.entry_count,
                    min_position=self.min_position, orders=self.order_count)
