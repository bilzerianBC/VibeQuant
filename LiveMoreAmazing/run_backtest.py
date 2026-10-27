# -*- coding: utf-8 -*-
"""AmazingData 日线采集与离线并行回测（主入口），参见 README.md。

流程：
    1. 确定股票池（--codes / 缓存的股票池清单 / 在线拉取）
    2. 下载并归一化日线到 Parquet 缓存（--skip-download 时跳过）
    3. 逐只校验缓存完整，再用 spawn 进程池并行回测
    4. 写 summary_*.csv（开启交易）或 signals_*.csv（仅行情阶段），失败时以非零退出
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd

# amazing_data 只在 AmazingDataManager.connect() 里才导入在线 SDK，
# 因此这里顶层导入是安全的：离线回测、worker 进程都不会加载 SDK。
from livemore.amazing_data import CACHE_DIR, RESULT_DIR, AmazingDataManager, validate_range
from livemore.backtest import INDEX_CODE, USE_INDEX_FILTER, run_single
from livemore.charts import build_html, trade_chart
from livemore.report import atomic_write

os.makedirs(RESULT_DIR, exist_ok=True)

PROGRESS_EVERY = 50


def _worker(args):
    """在独立进程里回测一只标的：只读缓存，开启交易时额外生成成交图。"""
    code, start, end, use_index, trading_enabled = args
    dm = AmazingDataManager(offline=True)
    df = dm.get_daily(code, start, end)
    index_df = dm.get_daily(INDEX_CODE, start, end) if use_index else None
    result = run_single(code, df, index_df, trading_enabled=trading_enabled)
    if trading_enabled and "_fills" in result:
        # Content-addressed chart keeps older reports paired with their original fills.
        html = build_html([trade_chart(code, df, result.pop("_fills"))]).encode()
        filename = f"chart_{code}_{hashlib.sha256(html).hexdigest()[:16]}.html"
        atomic_write(Path(RESULT_DIR) / filename, html)
        result["chart_file"] = filename
    return result


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="19900101",
                    help="历史请求起点，默认 19900101；实际起点以服务端返回为准")
    ap.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--codes", nargs="+", help="显式股票列表，例如 000001.SZ 600519.SH")
    ap.add_argument("--sector", default="EXTRA_STOCK_A_SH_SZ")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--resume", action="store_true", help="续跑：复用已完整的缓存，只下载缺失的标的")
    ap.add_argument("--enable-trading", action="store_true", help="开启模拟交易（默认仅计算行情信号）")
    ap.add_argument("--no-index", action="store_true", help="关闭大盘过滤")
    return ap, ap.parse_args()


def resolve_pool(ap, args, dm):
    """股票池：显式 --codes > 离线时读缓存清单 > 在线拉取并写清单。"""
    manifest = Path(CACHE_DIR) / f"universe_{args.sector}_{args.start}_{args.end}.json"
    if args.codes:
        pool = sorted(set(args.codes))
    elif args.skip_download:
        if not manifest.exists():
            ap.error("缺少股票池缓存，请先采集或通过 --codes 指定已缓存代码")
        pool = json.loads(manifest.read_text())
    else:
        pool = dm.get_a_share_list(args.sector)
        manifest.write_text(json.dumps(pool))
    if args.limit:
        pool = pool[: args.limit]
    return pool


def download(dm, pool, args, use_index):
    print("下载历史行情…")
    t0 = time.time()
    download_list = pool + ([INDEX_CODE] if use_index else [])
    report = dm.batch_download(download_list, args.start, args.end,
                               index_codes=[INDEX_CODE] if use_index else [],
                               resume=args.resume)
    coverage = Path(RESULT_DIR) / f"coverage_{args.start}_{args.end}.json"
    coverage.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"实际覆盖报告：{coverage}（不保证覆盖请求起点，上市日期也会影响起点）")
    print(f"下载完成，用时 {time.time()-t0:.1f}s")


def run_all(task_args, workers, total):
    rows: list[dict] = []
    if workers <= 1:
        for ta in task_args:
            rows.append(_worker(ta))
            if len(rows) % PROGRESS_EVERY == 0:
                print(f"  {len(rows)}/{total} done")
        return rows
    # 必须用 spawn：fork 会让子进程继承主进程在线 SDK 的线程状态，
    # spawn 让每个 worker 全新解释器，仅从缓存读取。
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futures = {ex.submit(_worker, ta): ta[0] for ta in task_args}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                rows.append(fut.result())
            except Exception as e:  # noqa: BLE001
                rows.append({"code": futures[fut], "error": str(e)})
            if i % PROGRESS_EVERY == 0:
                print(f"  {i}/{total} done")
    return rows


def print_summary(valid):
    print("\n=== 全样本统计 ===")
    print(f"有效样本数      : {len(valid)}")
    print(f"中位累计收益    : {valid['total_return'].median():.2%}")
    print(f"中位年化        : {valid['annual_return'].median():.2%}")
    print(f"中位最大回撤    : {valid['max_drawdown'].median():.2%}")
    print(f"中位胜率        : {valid['winrate'].median():.2%}")
    print(f"中位 buy&hold   : {valid['buy_and_hold'].median():.2%}")
    print(f"中位超额 vs B&H : {valid['excess_vs_bh'].median():.2%}")
    print(f"跑赢 B&H 比例   : {(valid['excess_vs_bh'] > 0).mean():.2%}")


def main():
    ap, args = parse_args()
    use_index = USE_INDEX_FILTER  # --no-index 当前无额外作用，见 livemore/backtest.py
    if args.workers < 1 or args.limit < 0:
        ap.error("workers 必须大于零，limit 不能为负")
    validate_range(args.start, args.end)
    dm = AmazingDataManager(offline=args.skip_download)
    if not args.sector.replace("_", "").isalnum():
        ap.error("sector 只能包含字母、数字及下划线")

    pool = resolve_pool(ap, args, dm)
    print(f"标的池：{len(pool)} 只，区间 {args.start}~{args.end}，大盘过滤={use_index}")

    if not args.skip_download:
        download(dm, pool, args, use_index)

    # Validate every cache before starting workers. A missing index is an error,
    # never silently turn off the market filter.
    for code in pool + ([INDEX_CODE] if use_index else []):
        if dm.get_daily(code, args.start, args.end).empty:
            raise ValueError(f"{code} 缓存为空")
    print("开始回测…" if args.enable_trading else "交易已关闭，开始计算行情信号…")
    task_args = [(c, args.start, args.end, use_index, args.enable_trading) for c in pool]
    rows = run_all(task_args, args.workers, len(pool))

    res = pd.DataFrame(rows)
    failures = sum("error" in row for row in rows)
    prefix = "summary" if args.enable_trading else "signals"
    out = os.path.join(RESULT_DIR, f"{prefix}_{args.start}_{args.end}.csv")
    res.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n结果写入 {out}")

    if not args.enable_trading:
        if failures:
            raise RuntimeError(f"{failures} 个标的信号计算失败，请检查 error/trace 列")
        if not any("phase" in row for row in rows):
            raise RuntimeError("没有有效信号结果；至少需要 2 根日线")
        print("交易已关闭：结果仅包含行情阶段，不计算交易绩效。")
        return

    valid = res.dropna(subset=["total_return"]) if "total_return" in res else pd.DataFrame()
    if not valid.empty:
        print_summary(valid)

    if failures:
        raise RuntimeError(f"{failures} 个标的回测失败，请检查结果中的 error/trace 列")
    if valid.empty:
        raise RuntimeError("没有有效回测结果；至少需要 2 根日线")


if __name__ == "__main__":
    sys.exit(main())
