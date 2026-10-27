#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取「美国 M2」和「黄金价格」全量历史数据，并各自聚合为月度数据。

数据源（各一个，官方权威）:
  - 美国 M2  : FRED 序列 M2SL（M2 Money Stock，季调，原生月度，1959 至今，单位: 十亿美元）
  - 黄金价格 : LBMA 伦敦金定盘价（日度，美元/盎司），优先 PM 定盘价、AM 兜底

依赖: python3 + pandas
    pip install pandas

用法:
  1. 免费申请 FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
  2. 设置环境变量:  export FRED_API_KEY=你的32位key
  3. 运行:          python fetch_m2_gold.py

环境变量:
  - FRED_API_KEY                 FRED 的 32 位 key（必需）

输出（写入 ./data/ 目录）:
  - m2_monthly.csv        M2 月度（原生月度，日期对齐到月末）
  - gold_daily.csv        黄金日度（LBMA 定盘价原始日度，供日度比值图使用）
  - gold_monthly.csv      黄金月度（gold_month_end 月末收盘 + gold_month_avg 月均价）
  - combined_monthly.csv  两者按月末日期合并后的总表
"""

import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime

import pandas as pd


FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

M2_SERIES = "M2SL"

# LBMA 伦敦金定盘价日度 JSON（先 PM 后 AM，v=[美元,英镑,欧元]）
LBMA_GOLD_URLS = [
    "https://prices.lbma.org.uk/json/gold_pm.json",
    "https://prices.lbma.org.uk/json/gold_am.json",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _download(url, tries=3, timeout=60):
    """带重试的下载，返回 bytes；全部失败抛最后一次异常。"""
    last_err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            if i < tries - 1:
                time.sleep(2 * (i + 1))   # 2s, 4s 退避
    raise last_err


# ---------------- FRED ----------------

def fred_observations(series_id, api_key):
    """从 FRED 拉取某个序列的全部观测值，返回 [(date_str, value_float), ...]"""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "limit": 100000,          # 一次性取全量
        "sort_order": "asc",
    }
    url = f"{FRED_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        payload = json.load(resp)

    rows = []
    for obs in payload.get("observations", []):
        v = obs.get("value", ".")
        if v == ".":
            continue               # FRED 用 '.' 表示缺失值
        rows.append((obs["date"], float(v)))
    return rows


def to_df(rows, value_name):
    """观测值列表 -> 单列 DataFrame（DatetimeIndex 升序、去重）"""
    if not rows:
        return pd.DataFrame(columns=[value_name])
    dates = [datetime.strptime(d, "%Y-%m-%d") for d, _ in rows]
    vals = [v for _, v in rows]
    df = pd.DataFrame({value_name: vals}, index=pd.to_datetime(dates))
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def aggregate_monthly(df, value_name, how="last"):
    """把任意频率数据聚合到月度。

    how='last' -> 月末收盘价；how='mean' -> 月均价。
    返回 index 为当月末日期的单列 DataFrame。
    """
    if df.empty:
        return df
    series = df[value_name]
    try:
        agg = series.resample("ME").agg(how)   # pandas>=2.2 的月末别名
    except ValueError:
        agg = series.resample("M").agg(how)    # 旧版 pandas
    agg.index = agg.index.normalize()
    return agg.to_frame(name=value_name)


def gold_monthly_from_daily(gold_daily):
    """日度金价 -> 月度 DataFrame（列: gold_month_end, gold_month_avg）"""
    gold_last = aggregate_monthly(gold_daily, "gold", how="last")
    gold_mean = aggregate_monthly(gold_daily, "gold", how="mean")
    out = gold_last.rename(columns={"gold": "gold_month_end"})
    out["gold_month_avg"] = gold_mean["gold"]
    return out


# ---------------- 黄金：LBMA ----------------

def _parse_lbma_json(payload):
    """把 LBMA 价格 JSON 归一化为 [(date_str, usd_price), ...]。

    真实结构: [{"d":"YYYY-MM-DD","v":[usd, gbp, eur],"is_cms_locked":false}, ...]
    v[0] 是美元价；PM 未定价的日子 v 可能全为 0，需过滤。
    """
    if not isinstance(payload, list):
        return []

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}")
    rows = []
    for it in payload:
        if not isinstance(it, dict):
            continue
        d = it.get("d") or it.get("date") or it.get("Date")
        v = it.get("v")
        if not d or v is None:
            continue
        d = str(d)[:10]
        if not date_re.match(d):
            continue
        # v 是 [usd, gbp, eur] 数组；兼容标量
        usd = v[0] if isinstance(v, (list, tuple)) else v
        if usd is None:
            continue
        try:
            usd = float(usd)
        except (TypeError, ValueError):
            continue
        if usd <= 0:              # 0 表示当日该场次未定价
            continue
        rows.append((d, usd))
    return rows


def gold_from_lbma():
    """从 LBMA 官网拉伦敦金定盘价日度数据，返回单列 DataFrame（'gold'）或 None。"""
    for url in LBMA_GOLD_URLS:
        session = "PM" if "pm" in url else "AM"
        print(f"拉取黄金（LBMA {session}）...")
        try:
            raw = _download(url)
            payload = json.loads(raw.decode("utf-8"))
            rows = _parse_lbma_json(payload)
        except Exception as e:
            print(f"  LBMA {session} 下载/解析失败: {e}")
            continue
        if not rows:
            print(f"  LBMA {session} 无数据")
            continue
        df = to_df(rows, "gold")
        if not df.empty:
            print(f"  黄金日度: {len(df)} 行 ({df.index.min().date()} ~ {df.index.max().date()})")
            return df
    return None


# ---------------- 主流程 ----------------

def main():
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        sys.exit(
            "缺少 FRED_API_KEY 环境变量。\n"
            "先到 https://fred.stlouisfed.org/docs/api/api_key.html 免费申请，\n"
            "再执行: export FRED_API_KEY=你的key"
        )

    os.makedirs("data", exist_ok=True)

    # ---------- 1. 美国 M2（FRED）----------
    print("拉取 M2 (M2SL) ...")
    m2_raw = to_df(fred_observations(M2_SERIES, api_key), "m2")
    if m2_raw.empty:
        print("警告: M2SL 无数据，请检查 API key 或序列号")
    m2_monthly = aggregate_monthly(m2_raw, "m2", how="last")
    m2_monthly.to_csv("data/m2_monthly.csv")
    print(f"  M2 月度: {len(m2_monthly)} 行 -> data/m2_monthly.csv")

    # ---------- 2. 黄金价格（LBMA）----------
    gold_monthly = None

    gold_daily = gold_from_lbma()
    if gold_daily is not None:
        # 原始日度金价单独落盘，供日度 M2/黄金 比值图（daily_ratio_chart.py）使用
        gold_daily.to_csv("data/gold_daily.csv")
        print(f"  黄金日度: {len(gold_daily)} 行 -> data/gold_daily.csv")
        gold_monthly = gold_monthly_from_daily(gold_daily)

    if gold_monthly is None:
        print("警告: LBMA 黄金数据获取失败。")
    else:
        gold_monthly.to_csv("data/gold_monthly.csv")
        print(f"  黄金月度: {len(gold_monthly)} 行 -> data/gold_monthly.csv")

    # ---------- 3. 合并 ----------
    parts = [m2_monthly]
    if gold_monthly is not None:
        parts.append(gold_monthly)
    combined = pd.concat(parts, axis=1).sort_index()
    combined.to_csv("data/combined_monthly.csv")
    print(f"  合并表: {len(combined)} 行 -> data/combined_monthly.csv")

    print("\n完成。数据覆盖范围:")
    print(f"  M2   : {m2_monthly.index.min().date()} ~ {m2_monthly.index.max().date()}")
    if gold_monthly is not None:
        print(f"  黄金 : {gold_monthly.index.min().date()} ~ {gold_monthly.index.max().date()}")


if __name__ == "__main__":
    main()
