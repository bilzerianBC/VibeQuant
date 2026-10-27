"""LiveMore 核心库：AmazingData 数据适配、利弗莫尔策略、回测引擎与报告渲染。

模块分层（上层只依赖下层）：

    amazing_data        SDK 适配 + 本地缓存契约（唯一接触 AmazingData SDK 的模块）
    livermore_strategy  六列行情记录状态机 + Backtrader 策略（与原版 LiveMore 保持一致）
    trading_statistics  模拟成交与持仓统计（Backtrader Analyzer）
    backtest            单标的回测引擎 run_single
    charts / report     K 线阶段图、回测报告 HTML（report 也是发布命令：python -m livemore.report）

主入口是项目根的 run_backtest.py。
"""
