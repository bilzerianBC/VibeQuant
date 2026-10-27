# -*- coding: utf-8 -*-
"""
利弗莫尔《股票大作手操盘术》策略 —— Backtrader 完整实现。

本文件严格对照 doc/Livemore策略.md 实现，md 中的策略原文以 `md §x` 注释直接嵌在
对应代码处，确保"代码 == 原文"可逐条核对。

整体结构：
    1) LivermoreMarketKey  —— 附录"六列行情记录体系"的状态机（关键点 / 转向的唯一来源）
    2) LivermoreStrategy    —— 用状态机的关键点信号做：入场 / 金字塔加仓 / 10%止损 /
                               反转关键点离场 / 储备金 / 最小阻力线与大盘过滤
    3) PandasDailyFeed       —— 吃 qmt_data 的 DataFrame

══════════════════════════════════════════════════════════════════════════════
 md §九 利弗莫尔的操盘体系：行情记录方法（附录一、二）
   "利弗莫尔的核心工具是一本手记。他坚持记录关键价位和波动幅度，价格模式自然浮现。"
══════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from enum import Enum

import backtrader as bt


# ══════════════════════════════════════════════════════════════════════════════
# 1) 六列行情记录状态机
# ══════════════════════════════════════════════════════════════════════════════
class Col(Enum):
    """
    md §9.1 六列记录表：每只目标股开一张表，按下列六列记录价格。

        | 列名               | 含义                          |
        | 二次反弹 SEC_RALLY  | 自然反弹基础上的进一步反弹      |
        | 自然反弹 NAT_RALLY  | 下跌趋势中出现的反弹            |
        | 上涨趋势 UP_TREND   | 主升趋势（md §9.2 用黑色钢笔）  |
        | 下跌趋势 DOWN_TREND | 主跌趋势（md §9.2 用红色钢笔）  |
        | 自然回调 NAT_REACT  | 上涨趋势中的回调                |
        | 二次回调 SEC_REACT  | 自然回调后的二次回调            |
    """
    SEC_RALLY = "二次反弹"
    NAT_RALLY = "自然反弹"
    UP_TREND = "上涨趋势"
    DOWN_TREND = "下跌趋势"
    NAT_REACT = "自然回调"
    SEC_REACT = "二次回调"


class LivermoreMarketKey:
    """
    利弗莫尔行情记录体系（Livermore Market Key）状态机。

    md §9.3 适用范围 / 阈值：
        · 只跟踪 30 美元以上的股票（高价股波动更具规律性）。
        · 记录"幅度大于 6 美元（约 6 个点）"的波动；幅度过小则忽略，避免被噪声干扰。
        · 还有一个"3 美元"的次级阈值（md §9.4 的 10 系列规则）。

    原书的 6 美元 / 3 美元是针对约 30 美元美股的【绝对点数】（6/30 ≈ 20%）。
    A 股价格从 2 元到 2000 元跨度极大，绝对点数无意义，这里把它【参数化为百分比】：
        swing_pct      ← 对应原书 6 点（趋势 / 反弹 / 回调 成立的最小摆动）
        secondary_pct  ← 对应原书 3 点（10 系列规则里"接近前高/前低"的判定带）
    默认取较大的摆动幅度，这正契合 md §一 "大钱靠'坐'出来" —— 只捕捉大波动、长期持有。

    md §9.5 用记录表识别关键点 / 转向：
        · 某列连续记录后突然大幅反向（约 6 点）且未能恢复 → 趋势可能反转。
        · 接近前期高/低点时能否"突破并延续"，就是关键点的考验。
        · 突破后假回踩未破突破位 → 趋势确认；跌穿原突破位 → 假突破，反手离场。
    """

    def __init__(
        self,
        swing_pct: float = 0.06,      # 转向阈值 = 当前列极值价的 6%（原书"6 美元"）
        secondary_pct: float = 0.03,  # 次级阈值 = 极值价的 3%（原书"3 美元"）
        reversal_pct: float | None = None,
    ):
        self.swing_pct = swing_pct
        self.secondary_pct = secondary_pct
        # 深度反转阈值：自上涨趋势关键点回撤超过此比例即判反转（md §9.5 第一条
        # "突然大幅反向且未能恢复 → 趋势可能反转"）。默认 = 2 倍摆动幅度。
        self.reversal_pct = reversal_pct if reversal_pct is not None else 2 * swing_pct

        # 当前所在列（趋势状态）
        self.col: Col | None = None
        # 方向未定阶段的锚价（md §一：等最小阻力线方向被市场昭示后再下注）
        self.anchor: float | None = None
        # 当前列记录的最新极值价（上涨/反弹列=最高，下跌/回调列=最低）
        self.col_price: float | None = None

        # ── 关键价位（md §9.2：切换列时"画线"标出的就是关键点）──────────────
        # 上一个【上涨趋势关键点】：上涨趋势列转入自然回调时，画红线标出的高点。
        self.up_pivot: float | None = None
        # 上一个【下跌趋势关键点】：下跌趋势列转入自然反弹时，画线标出的低点。
        self.down_pivot: float | None = None
        # 自然反弹列的高点 / 自然回调列的低点（10 系列规则用来判转折）
        self.nat_rally_high: float | None = None
        self.nat_react_low: float | None = None
        # 【上一轮】自然回调低点 / 自然反弹高点（md §9.5：跌破上一个回调低点 = 反转）
        self.prev_nat_react_low: float | None = None
        self.prev_nat_rally_high: float | None = None

        # ── 对外信号（每个 bar 由 update() 刷新）─────────────────────────────
        # 延续关键点被向上突破（恢复 / 确立上涨趋势）→ 入场 & 加仓信号
        self.signal_breakout_up = False
        # 反转关键点被向下击穿（转入下跌趋势）→ 清仓信号（md §9.5 / 原则12）
        self.signal_reversal_down = False
        # 10 系列：自然反弹接近前高却走不动（差距 < secondary）→ 上涨趋势可能结束
        self.signal_uptrend_failing = False

    # ── 工具 ────────────────────────────────────────────────────────────────
    def _swing(self, ref: float) -> float:
        return ref * self.swing_pct

    def _secondary(self, ref: float) -> float:
        return ref * self.secondary_pct

    @property
    def in_uptrend(self) -> bool:
        return self.col in (Col.UP_TREND, Col.NAT_REACT, Col.SEC_REACT)

    @property
    def in_downtrend(self) -> bool:
        return self.col in (Col.DOWN_TREND, Col.NAT_RALLY, Col.SEC_RALLY)

    # ── 每日推进 ──────────────────────────────────────────────────────────────
    def update(self, price: float) -> None:
        """
        输入当日记录价格（用收盘价，对应利弗莫尔每天在表上记一格），推进状态机。

        md §9.4 列与列之间的切换规则（节选 4-A / 4-B / 5-6 / 10 系列）在下方逐条落地。
        """
        # 清空上一 bar 的瞬时信号
        self.signal_breakout_up = False
        self.signal_reversal_down = False
        self.signal_uptrend_failing = False

        # ──────────────────────────────────────────────────────────────────
        # 方向未定阶段（md §一："要等阻力线的方向被市场明确昭示后再下注"）
        #   先以第一笔价格为锚，直到价格向上 / 向下摆动一个 swing 才确立趋势。
        #   向上确立 = 延续/确立上涨趋势的关键点突破 → 触发首次入场信号。
        # ──────────────────────────────────────────────────────────────────
        if self.col is None:
            if self.anchor is None:
                self.anchor = price
                return
            ratio = price / self.anchor - 1.0           # 相对锚价的涨跌幅
            eps = 1e-9
            if ratio >= self.swing_pct - eps:
                self._enter_uptrend(price)
                self.signal_breakout_up = True          # ← 首次入场信号
            elif ratio <= -self.swing_pct + eps:
                self.col = Col.DOWN_TREND
                self.col_price = price
                self.down_pivot = price
            # else：仍在锚 ±swing 内震荡，锚保持不变，继续等待方向昭示
            return

        swing = self._swing(self.col_price)

        # ──────────────────────────────────────────────────────────────────
        # 状态：UP_TREND（上涨趋势，规则 1 黑笔；规则 6a 回撤换栏）
        # ──────────────────────────────────────────────────────────────────
        if self.col == Col.UP_TREND:
            if price >= self.col_price:
                # 续创新高 → 继续记录，刷新上涨趋势关键点候选
                self.col_price = price
                self.up_pivot = price
            elif price <= self.col_price - swing:
                # 规则 4a / 6a：自高点回撤约 6 点 → 转"自然回撤"栏，
                # 在上涨趋势栏最后价下画红线（= 锁定 up_pivot 关键点）。
                self.up_pivot = self.col_price
                self.col = Col.NAT_REACT
                self.col_price = price
                self.nat_react_low = price

        # ──────────────────────────────────────────────────────────────────
        # 状态：NAT_REACT（自然回撤）—— 规则 6a/6d/6e/6g
        # ──────────────────────────────────────────────────────────────────
        elif self.col == Col.NAT_REACT:
            if price <= self.col_price:
                # 回撤加深；规则 5b/6e：跌破关键点 → 确立下跌趋势（反转）
                self.col_price = price
                self.nat_react_low = price
                self._check_downtrend_reversal(price)
            elif price >= self.col_price + swing:
                # 自回撤低点反弹约 6 点
                if self.nat_rally_high is not None and price <= self.nat_rally_high:
                    # 规则 6g：反弹够 6 点、但没超过上一自然回升高点 → 次级回升栏
                    self.col = Col.SEC_RALLY
                    self.col_price = price
                else:
                    # 规则 6d：常规 → 自然回升栏
                    self.col = Col.NAT_RALLY
                    self.col_price = price
                    self.nat_rally_high = price
                    self._check_uptrend_resume(price)

        # ──────────────────────────────────────────────────────────────────
        # 状态：SEC_RALLY（次级回升，横盘震荡的弱反弹）—— 规则 6g
        # ──────────────────────────────────────────────────────────────────
        elif self.col == Col.SEC_RALLY:
            if price >= self.col_price:
                self.col_price = price
                # 规则 6g 结尾：超过上一自然回升高点 → 回自然回升栏，再判是否确立上涨
                if self.nat_rally_high is not None and price > self.nat_rally_high:
                    self.col = Col.NAT_RALLY
                    self.nat_rally_high = price
                    self._check_uptrend_resume(price)
            elif price <= self.col_price - swing:
                # 次级回升又跌 6 点 → 回自然回撤栏
                self.col = Col.NAT_REACT
                self.col_price = price
                self.nat_react_low = price
                self._check_downtrend_reversal(price)

        # ──────────────────────────────────────────────────────────────────
        # 状态：NAT_RALLY（自然回升）—— 规则 6c/6f/6h + 规则 10e(危险信号)
        # ──────────────────────────────────────────────────────────────────
        elif self.col == Col.NAT_RALLY:
            if price >= self.col_price:
                self.col_price = price
                self.nat_rally_high = price
                # 规则 5a/6f/10a：突破关键点 → 确立上涨（signal_breakout_up）
                if not self._check_uptrend_resume(price):
                    # 规则 10e：反弹逼近前高（差 < 3 点 secondary）却没突破 → 危险信号
                    if (
                        self.up_pivot is not None
                        and 0 <= self.up_pivot - price <= self._secondary(self.up_pivot)
                    ):
                        self.signal_uptrend_failing = True
            elif price <= self.col_price - swing:
                # 自回升高点回落约 6 点
                if self.nat_react_low is not None and price >= self.nat_react_low:
                    # 规则 6h：回落够 6 点、但没跌破上一自然回撤低点 → 次级回撤栏
                    self.col = Col.SEC_REACT
                    self.col_price = price
                else:
                    # 规则 6b：常规 → 自然回撤栏
                    self.col = Col.NAT_REACT
                    self.col_price = price
                    self.nat_react_low = price
                    self._check_downtrend_reversal(price)

        # ──────────────────────────────────────────────────────────────────
        # 状态：SEC_REACT（次级回撤，横盘震荡的弱回落）—— 规则 6h
        # ──────────────────────────────────────────────────────────────────
        elif self.col == Col.SEC_REACT:
            if price <= self.col_price:
                self.col_price = price
                # 规则 6h 结尾：跌破上一自然回撤低点 → 回自然回撤栏，再判是否反转
                if self.nat_react_low is not None and price < self.nat_react_low:
                    self.col = Col.NAT_REACT
                    self.nat_react_low = price
                    self._check_downtrend_reversal(price)
            elif price >= self.col_price + swing:
                # 次级回撤又涨 6 点 → 回自然回升栏
                self.col = Col.NAT_RALLY
                self.col_price = price
                self.nat_rally_high = price
                self._check_uptrend_resume(price)

        # ──────────────────────────────────────────────────────────────────
        # 状态：DOWN_TREND（下跌趋势，规则 2 红笔；规则 6c 反弹换栏）
        # ──────────────────────────────────────────────────────────────────
        elif self.col == Col.DOWN_TREND:
            if price <= self.col_price:
                # 续创新低 → 刷新下跌趋势关键点候选
                self.col_price = price
                self.down_pivot = price
            elif price >= self.col_price + swing:
                # 规则 4c / 6c：自低点反弹约 6 点 → 转"自然回升"栏，画线锁定 down_pivot
                self.down_pivot = self.col_price
                self.col = Col.NAT_RALLY
                self.col_price = price
                self.nat_rally_high = price
                self._check_uptrend_resume(price)

    # ── 趋势确立 / 反转的复用判据 ─────────────────────────────────────────────
    def _check_uptrend_resume(self, price: float) -> bool:
        """规则 5a/6f/10a：在自然回升/次级栏里判断是否确立上涨趋势。成立则发买入信号。
           三判据：① 突破上涨趋势关键点 up_pivot；② 突破上一轮自然回升高点；
                  ③ 自下跌趋势关键点深度反弹 reversal_pct（解决 up_pivot 尚为 None）。"""
        broke_up_pivot = self.up_pivot is not None and price > self.up_pivot
        broke_prev_rally = (
            self.prev_nat_rally_high is not None and price > self.prev_nat_rally_high
        )
        deep_rally = (
            self.down_pivot is not None
            and price >= self.down_pivot * (1 + self.reversal_pct)
        )
        if broke_up_pivot or broke_prev_rally or deep_rally:
            self._enter_uptrend(price)
            self.signal_breakout_up = True
            return True
        return False

    def _check_downtrend_reversal(self, price: float) -> bool:
        """规则 5b/6e/10b：在自然回撤/次级栏里判断是否确立下跌趋势（反转）。
           三判据：① 跌破上一轮自然回撤低点；② 跌破下跌趋势关键点；
                  ③ 自上涨趋势关键点深度回撤 reversal_pct。"""
        broke_prev_react = (
            self.prev_nat_react_low is not None and price < self.prev_nat_react_low
        )
        broke_down_pivot = (
            self.down_pivot is not None and price < self.down_pivot
        )
        deep_reversal = (
            self.up_pivot is not None
            and price <= self.up_pivot * (1 - self.reversal_pct)
        )
        if broke_prev_react or broke_down_pivot or deep_reversal:
            self._enter_downtrend(price)
            return True
        return False

    # ── 状态切换 + 信号 ───────────────────────────────────────────────────────
    def _enter_uptrend(self, price: float) -> None:
        # 恢复上涨趋势前，把刚结束的这轮自然回调低点存为"上一轮回调低点"，
        # 供下一次回调判断是否跌破（md §9.5 反转判据①）。
        if self.nat_react_low is not None:
            self.prev_nat_react_low = self.nat_react_low
        self.col = Col.UP_TREND
        self.col_price = price
        self.up_pivot = price

    def _enter_downtrend(self, price: float) -> None:
        # md §9.5：跌穿关键点 = 反转关键点被向下击穿 → 趋势反转。
        if self.nat_rally_high is not None:
            self.prev_nat_rally_high = self.nat_rally_high
        self.col = Col.DOWN_TREND
        self.col_price = price
        self.down_pivot = price
        self.signal_reversal_down = True  # ← 清仓信号


# ══════════════════════════════════════════════════════════════════════════════
# 2) 策略主体
# ══════════════════════════════════════════════════════════════════════════════
class LivermoreStrategy(bt.Strategy):
    """行情状态和买卖信号；执行与持仓统计由外部 trade_hook 接收。"""

    params = dict(trade_hook=None, trading_enabled=False,
                  swing_pct=0.06, secondary_pct=0.03, printlog=False)

    # ── 日志 ──────────────────────────────────────────────────────────────────
    def log(self, txt):
        if self.p.printlog:
            dt = self.datas[0].datetime.date(0).isoformat()
            print(f"{dt} {txt}")

    # ── 初始化 ────────────────────────────────────────────────────────────────
    def __init__(self):
        self.dataclose = self.data.close
        self.key = LivermoreMarketKey(self.p.swing_pct, self.p.secondary_pct)
        self._last_stock_bar = 0
        self.trade_hook = self.p.trade_hook

    # ── 主循环 ────────────────────────────────────────────────────────────────
    def _new_stock_bar(self):
        if not len(self.data) or len(self.data) == self._last_stock_bar:
            return False
        self._last_stock_bar = len(self.data)
        return True

    def prenext(self):
        self.next()

    def next(self):
        if not self._new_stock_bar():
            return
        price = self.dataclose[0]
        if price <= 0:
            return
        previous = self.key.col
        self.key.update(price)
        if not self.p.trading_enabled or self.trade_hook is None:
            return
        self.trade_hook(
            buy=previous != Col.UP_TREND and self.key.col == Col.UP_TREND,
            sell=previous == Col.UP_TREND and self.key.col != Col.UP_TREND,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3) 数据 feed
# ══════════════════════════════════════════════════════════════════════════════
class PandasDailyFeed(bt.feeds.PandasData):
    """直接吃 qmt_data.QmtDataManager.get_daily() 的 DataFrame（index=datetime）。"""

    params = dict(
        datetime=None,
        open="open",
        high="high",
        low="low",
        close="close",
        volume="volume",
        openinterest=-1,
    )
