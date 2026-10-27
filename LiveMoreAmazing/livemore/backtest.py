# -*- coding: utf-8 -*-
"""单标的回测引擎：纯 Backtrader，不接触行情 SDK，可直接用合成数据调用。"""

from __future__ import annotations

import traceback
from typing import Any

import backtrader as bt
import pandas as pd

from .livermore_strategy import LivermoreStrategy, PandasDailyFeed
from .trading_statistics import PositionStatistics

INDEX_CODE = "000300.SH"  # 沪深300，作大盘最小阻力线过滤

# 大盘过滤当前关闭：不下载、不校验、不喂给策略指数数据。
# run_backtest.py 的 --no-index 参数仍被接受，但因此不改变任何行为。
USE_INDEX_FILTER = False

INITIAL_CASH = 100_000.0
SLIPPAGE_PERC = 0.0005       # 万五滑点
TRADING_DAYS_PER_YEAR = 252.0


class AShareCommission(bt.CommInfoBase):
    """A 股成本：双边万二佣金 + 卖出千一印花税。"""

    params = dict(
        commission=0.0002,
        stamp_duty=0.001,
        stocklike=True,
        commtype=bt.CommInfoBase.COMM_PERC,
        percabs=True,
    )

    def _getcommission(self, size, price, pseudoexec):
        notional = abs(size) * price
        comm = notional * self.p.commission
        if size < 0:  # 卖出加印花税
            comm += notional * self.p.stamp_duty
        return comm


def _build_cerebro(code, df, index_df, initial_cash, trading_enabled):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.addcommissioninfo(AShareCommission())
    cerebro.broker.set_slippage_perc(perc=SLIPPAGE_PERC)

    cerebro.adddata(PandasDailyFeed(dataname=df), name=code)
    if USE_INDEX_FILTER:
        cerebro.adddata(PandasDailyFeed(dataname=index_df), name="INDEX")

    cerebro.addstrategy(LivermoreStrategy, trading_enabled=trading_enabled)
    if trading_enabled:
        cerebro.addanalyzer(PositionStatistics, _name="positions")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="dd")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        riskfreerate=0.03, annualize=True)
    return cerebro


def _date_range(df):
    return df.index[0].strftime("%Y-%m-%d"), df.index[-1].strftime("%Y-%m-%d")


def run_single(
    code: str,
    df: pd.DataFrame,
    index_df: pd.DataFrame | None = None,
    initial_cash: float = INITIAL_CASH,
    trading_enabled: bool = False,
) -> dict[str, Any]:
    """回测一只标的。

    返回三种形态之一：
      * ``{"skipped": ...}``  —— 数据不足 2 根日线；
      * ``{"error": ..., "trace": ...}`` —— Backtrader 运行异常；
      * 正常结果 —— 交易关闭时只有行情阶段 ``phase``；交易开启时为完整绩效指标，
        另带 ``_fills``（成交明细，供画图，写 CSV 前由调用方取走）。
    """
    if df is None or df.empty or len(df) < 2:
        return {"code": code, "skipped": "insufficient_data", "bars": 0 if df is None else len(df)}

    cerebro = _build_cerebro(code, df, index_df, initial_cash, trading_enabled)
    try:
        strat = cerebro.run(maxcpus=1)[0]
    except Exception as e:  # noqa: BLE001
        return {"code": code, "error": str(e), "trace": traceback.format_exc()}

    start, end = _date_range(df)
    if not trading_enabled:
        return {
            "code": code, "trading_enabled": False, "bars": len(df),
            "start": start, "end": end,
            "phase": strat.key.col.value if strat.key.col else "未定",
        }

    positions = strat.analyzers.positions
    # md §六原则三：储备金已撤出市场，总资产 = broker 权益 + 储备金
    reserve = positions.reserve
    end_value = cerebro.broker.getvalue() + reserve
    total_return = end_value / initial_cash - 1.0

    bars = len(df)
    years = bars / TRADING_DAYS_PER_YEAR
    annual = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 and total_return > -1 else 0.0

    dd = strat.analyzers.dd.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()

    won = trades.get("won", {}).get("total", 0)
    lost = trades.get("lost", {}).get("total", 0)
    total_trades = won + lost

    bh_ret = (df["close"].iloc[-1] / df["close"].iloc[0]) - 1.0  # 买入持有基准

    return {
        "code": code,
        "_fills": positions.fills,
        "bars": bars,
        "start": start,
        "end": end,
        "end_value": round(end_value, 2),
        "end_position": strat.position.size,
        "avg_cost": positions.avg_cost,
        "entry_count": positions.entry_count,
        "min_position": positions.min_position,
        "orders": positions.order_count,
        "reserve": round(reserve, 2),
        "total_return": total_return,
        "annual_return": annual,
        "max_drawdown": dd.get("max", {}).get("drawdown", 0.0) / 100.0,
        "sharpe": sharpe.get("sharperatio") or 0.0,
        "trades": total_trades,
        "winrate": (won / total_trades) if total_trades else 0.0,
        "buy_and_hold": bh_ret,
        "excess_vs_bh": total_return - bh_ret,
    }
