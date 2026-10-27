#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「M2 ÷ 黄金」的**日度交互式**网页图表。

数据:
  - M2   : data/m2_monthly.csv（FRED M2SL，原生月度）
           官方没有日度 M2，这里把月度值按时间**线性插值**到每一天；
           当月尚未公布的部分沿用最近一个月末值（ffill）。
  - 黄金 : data/gold_daily.csv（LBMA 伦敦金定盘价，原生日度）

输出: 一个**自包含**的 HTML（数据内嵌，无任何外部依赖，离线可开）。
      默认窗口为「最近一年」，可用鼠标拖动平移、滚轮缩放、悬停查看当日数值。

用法:
    python daily_ratio_chart.py [-o 输出HTML路径]
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

DAY_MS = 86400000
EPOCH = pd.Timestamp("1970-01-01")

DATA_DIR = "data"
M2_CSV = os.path.join(DATA_DIR, "m2_monthly.csv")
GOLD_DAILY_CSV = os.path.join(DATA_DIR, "gold_daily.csv")


def _find(path, name):
    """优先用 data/ 下的，其次脚本同目录。"""
    if os.path.exists(path):
        return path
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    return here if os.path.exists(here) else path


def _default_out(m2_path):
    """默认输出路径。

    容器里设了 VIBEQUANT_SITE_DIR（站点根，如 /srv/web）时，写到
    <站点根>/m2divgold/ratio_m2_gold_daily.html，供前端门户 index 链接；
    没设（比如本机跑）就写到 data/ 旁边。
    """
    site = os.environ.get("VIBEQUANT_SITE_DIR")
    if site:
        return os.path.join(site, "m2divgold", "ratio_m2_gold_daily.html")
    return os.path.join(os.path.dirname(os.path.abspath(m2_path)),
                        "ratio_m2_gold_daily.html")


def load_m2_monthly(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    s = pd.to_numeric(df["m2"], errors="coerce").dropna()
    return s.sort_index()


def load_gold_daily(path):
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    col = "gold" if "gold" in df.columns else df.columns[0]
    s = pd.to_numeric(df[col], errors="coerce").dropna()
    return s.sort_index()


def interpolate_daily(monthly, daily_index):
    """把月度序列按时间线性插值到日度；首尾不足处用最近值补齐。"""
    union = monthly.index.union(daily_index)
    s = monthly.reindex(union).interpolate(method="time").ffill().bfill()
    return s.reindex(daily_index)


def build_daily_ratio(m2_monthly, gold_daily):
    """日度 M2（插值）/ 日度金价 -> 逐日比值。返回 DataFrame(m2, gold, ratio)。"""
    daily_index = pd.date_range(gold_daily.index.min(), gold_daily.index.max(), freq="D")
    m2_daily = interpolate_daily(m2_monthly, daily_index)
    gold = gold_daily.reindex(daily_index)
    df = pd.DataFrame({"m2": m2_daily, "gold": gold})
    df = df.dropna()
    df["ratio"] = df["m2"] / df["gold"]
    return df


def build_payload(df):
    days = ((df.index - EPOCH).days).astype(int).tolist()
    return {
        "d": days,
        "r": [round(float(x), 4) for x in df["ratio"]],
        "m": [round(float(x), 1) for x in df["m2"]],
        "g": [round(float(x), 2) for x in df["gold"]],
    }


def _updated_ts():
    """出图时间（即数据拉取+出图这一步跑完的时刻）。

    容器里默认是 UTC，这里按 Asia/Shanghai（UTC+8，无夏令时）换算，
    用固定偏移即可，不必依赖容器时区或 tzdata。可用 VIBEQUANT_UTC_OFFSET 覆盖。
    """
    off = int(os.environ.get("VIBEQUANT_UTC_OFFSET", "8"))
    tz = timezone(timedelta(hours=off))
    return datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def render_html(payload, start_date, end_date, latest, year_ago, low, high):
    data_json = json.dumps(payload, separators=(",", ":"))

    stats = (
        f"更新 {_updated_ts()} ｜ "
        f"样本 {start_date} ~ {end_date} ｜ 数据点 {len(payload['d'])} ｜ "
        f"最新 {latest:.2f} ｜ 一年前 {year_ago:.2f} ｜ "
        f"一年涨跌 {(latest / year_ago - 1) * 100:+.1f}% ｜ "
        f"窗口区间 {low:.2f} ~ {high:.2f}（十亿盎司）"
    )

    html = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>M2 ÷ 黄金（日度）</title>
<style>
  :root { color-scheme: light; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         margin: 0; padding: 28px 32px 40px; color: #1c1c1e; background: #fff; }
  h1 { font-size: 21px; margin: 0 0 6px; font-weight: 600; }
  .stats { color: #555; font-size: 13px; margin-bottom: 16px; }
  .controls { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
  .controls button { font: inherit; font-size: 13px; padding: 5px 12px; border: 1px solid #d8d8dc;
         background: #fff; color: #333; border-radius: 7px; cursor: pointer; }
  .controls button:hover { background: #f5f5f7; }
  .controls button.active { background: #1f77b4; border-color: #1f77b4; color: #fff; }
  .hint { color: #9a9aa0; font-size: 12px; margin-left: 6px; }
  .srcbar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
            font-size: 11.5px; color: #777; margin: 2px 0 10px; }
  .chip { display: inline-flex; align-items: center; }
  .chip i { display: inline-block; width: 11px; height: 11px; border-radius: 2px;
            margin-right: 5px; }
  .src code { background: #f4f4f7; padding: 1px 5px; border-radius: 3px; }
  .chartbox { position: relative; width: 100%; }
  svg { display: block; width: 100%; height: auto; touch-action: none;
        cursor: crosshair; user-select: none; }
  svg.dragging { cursor: grabbing; }
  .tip { position: absolute; pointer-events: none; background: rgba(28,28,30,.92); color: #fff;
         font-size: 12px; line-height: 1.55; padding: 7px 10px; border-radius: 7px;
         white-space: nowrap; opacity: 0; transition: opacity .08s; z-index: 5; }
  .note { color: #8a8a90; font-size: 12px; margin-top: 16px; line-height: 1.7; }
  .note b { color: #666; font-weight: 600; }
</style>
</head>
<body>
<h1>M2 ÷ 黄金（日度 · 动态一年窗口）</h1>
<div class="stats">__STATS__</div>
<div class="controls">
  <button data-range="1y" class="active">1 年</button>
  <button data-range="2y">2 年</button>
  <button data-range="5y">5 年</button>
  <button data-range="10y">10 年</button>
  <button data-range="all">全部</button>
  <span class="hint">拖动平移 · 滚轮缩放 · 悬停查看当日数值 · 双击切换 一年/全部</span>
</div>
<div class="srcbar">
  <span class="chip"><i style="background:#1f77b4"></i>比值曲线</span>
  <span class="chip"><i style="background:#cfe0f5"></i>布雷顿森林体系区间</span>
  <span class="src">
    黄金：<b>LBMA 伦敦金定盘价</b>（日度，1968-04 起）
    M2：<b>FRED <code>M2SL</code></b>（月度 → 线性插值到日度）
  </span>
</div>
<div class="chartbox">
  <svg id="chart" viewBox="0 0 1000 440" preserveAspectRatio="xMidYMid meet"></svg>
  <div class="tip" id="tip"></div>
</div>
<div class="note">
  <b>M2</b>：FRED M2SL（月度）按时间线性插值到日度，当月未公布部分沿用最近月末值。<br>
  <b>黄金</b>：LBMA 伦敦金定盘价（原生日度，美元/盎司，周末与假日无报价）。<br>
  比值 = M2 ÷ 金价，单位为「十亿盎司」，即全部 M2 能买多少盎司黄金。
</div>
<script>
const DATA = __PAYLOAD__;
const DAY = 86400000;
const VBW = 1000, VBH = 440;
const M = { l: 62, r: 18, t: 16, b: 38 };

const N = DATA.d.length;
const FIRST = DATA.d[0], LAST = DATA.d[N - 1];

// 时代区间（底纹）：数据本身从 1968-04 起，官价段之前已经在图外
const ERAS = [
  { from: FIRST, to: Math.floor(Date.UTC(1971, 7, 15) / DAY),
    label: '布雷顿森林体系（名义存续至 1971-08，金价已是市场价）', color: '#cfe0f5' },
];

const svg = document.getElementById('chart');
const tip = document.getElementById('tip');
const box = svg.parentNode;

let x0 = LAST - 365, x1 = LAST, y0 = 0, y1 = 1;
let hoverI = -1, dragging = false, dragMoved = false, dragStart = null;

function fmtDay(d) {
  const dt = new Date(d * DAY);
  const y = dt.getUTCFullYear();
  const mo = String(dt.getUTCMonth() + 1).padStart(2, '0');
  const da = String(dt.getUTCDate()).padStart(2, '0');
  return y + '-' + mo + '-' + da;
}
function fmtShort(d) {
  const dt = new Date(d * DAY);
  return String(dt.getUTCMonth() + 1).padStart(2, '0') + '-' + String(dt.getUTCDate()).padStart(2, '0');
}
function yearOf(d) { return new Date(d * DAY).getUTCFullYear(); }

// 二分：第一个 DATA.d[i] >= t 的下标
function lowerBound(t) {
  let lo = 0, hi = N - 1, ans = N;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (DATA.d[mid] >= t) { ans = mid; hi = mid - 1; } else { lo = mid + 1; }
  }
  return ans;
}

const sx = d => M.l + (d - x0) / (x1 - x0) * (VBW - M.l - M.r);
const sy = v => VBH - M.b - (v - y0) / (y1 - y0 || 1) * (VBH - M.t - M.b);
const ix = px => x0 + (px - M.l) / (VBW - M.l - M.r) * (x1 - x0);

function niceTicks(min, max, n) {
  const span = (max - min) || 1;
  const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = mag * (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10);
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(v);
  return out;
}

function xTicks() {
  const span = x1 - x0, out = [];
  if (span > 1500) {                       // 年（按需跳年）
    const y0y = yearOf(x0), y1y = yearOf(x1);
    const step = Math.max(1, Math.ceil((y1y - y0y + 1) / 12));
    for (let y = Math.ceil(y0y / step) * step; y <= y1y; y += step) {
      const t = Date.UTC(y, 0, 1) / DAY;
      if (t >= x0 && t <= x1) out.push({ t, label: String(y) });
    }
  } else if (span > 500) {                 // 季度
    let y = yearOf(x0), q = Math.floor(new Date(x0 * DAY).getUTCMonth() / 3);
    for (;;) {
      const t = Date.UTC(y, q * 3, 1) / DAY;
      if (t > x1) break;
      if (t >= x0) out.push({ t, label: y + ' Q' + (q + 1) });
      if (++q > 3) { q = 0; y++; }
    }
  } else if (span > 60) {                  // 月
    let y = yearOf(x0), m = new Date(x0 * DAY).getUTCMonth();
    for (;;) {
      const t = Date.UTC(y, m, 1) / DAY;
      if (t > x1) break;
      if (t >= x0) out.push({ t, label: (m === 0 || out.length === 0) ? String(y) : (m + 1) + '月' });
      if (++m > 11) { m = 0; y++; }
    }
  } else {                                 // 周/日
    const step = span > 45 ? 7 : span > 14 ? 3 : 1;
    for (let t = Math.ceil(x0); t <= x1; t += step) out.push({ t, label: fmtShort(t) });
  }
  return out;
}

function el(tag, attrs, text) {
  const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text != null) e.textContent = text;
  return e;
}

function limits() {
  let i0 = Math.max(0, lowerBound(x0) - 1);
  let i1 = Math.min(N - 1, Math.max(lowerBound(x1), i0 + 1));
  let lo = Infinity, hi = -Infinity;
  for (let i = i0; i <= i1; i++) { const v = DATA.r[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
  const pad = (hi - lo) * 0.08 || 0.1;
  return { i0, i1, lo: lo - pad, hi: hi + pad };
}

function draw() {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const L = limits();
  y0 = L.lo; y1 = L.hi;

  // 时代底纹（画在网格与曲线之下）
  for (const era of ERAS) {
    const s = Math.max(era.from, x0), e = Math.min(era.to, x1);
    if (e <= s) continue;
    const px0 = sx(s), px1 = sx(e);
    svg.appendChild(el('rect', { x: px0, y: M.t, width: px1 - px0, height: VBH - M.t - M.b,
      fill: era.color, opacity: 0.45 }));
    if (px1 - px0 > 150) {
      svg.appendChild(el('text', { x: (px0 + px1) / 2, y: M.t + 14, 'text-anchor': 'middle',
        fill: '#7a9cc0', 'font-size': 10 }, era.label));
    }
  }

  // 网格 + y 轴
  const yt = niceTicks(y0, y1, 5);
  const dec = (yt[1] - yt[0]) < 1 ? 2 : 1;
  for (const v of yt) {
    const py = sy(v);
    svg.appendChild(el('line', { x1: M.l, y1: py, x2: VBW - M.r, y2: py,
      stroke: '#ececf0', 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: M.l - 8, y: py + 4, 'text-anchor': 'end',
      fill: '#8a8a90', 'font-size': 11 }, v.toFixed(dec)));
  }

  // 网格 + x 轴
  for (const tk of xTicks()) {
    const px = sx(tk.t);
    svg.appendChild(el('line', { x1: px, y1: M.t, x2: px, y2: VBH - M.b,
      stroke: '#f4f4f7', 'stroke-width': 1 }));
    svg.appendChild(el('text', { x: px, y: VBH - M.b + 17, 'text-anchor': 'middle',
      fill: '#8a8a90', 'font-size': 11 }, tk.label));
  }

  // 折线（可视点过多时抽稀，保证 hover 重绘流畅；首尾点始终保留）
  const cnt = L.i1 - L.i0 + 1;
  const step = Math.max(1, Math.floor(cnt / 2000));
  let dpath = '';
  for (let i = L.i0; i <= L.i1; i += step) {
    dpath += (i === L.i0 ? 'M' : 'L') + sx(DATA.d[i]).toFixed(1) + ' ' + sy(DATA.r[i]).toFixed(1) + ' ';
  }
  if ((cnt - 1) % step !== 0) {
    dpath += 'L' + sx(DATA.d[L.i1]).toFixed(1) + ' ' + sy(DATA.r[L.i1]).toFixed(1);
  }
  svg.appendChild(el('path', { d: dpath, fill: 'none', stroke: '#1f77b4',
    'stroke-width': 1.6, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  // 轴框
  svg.appendChild(el('rect', { x: M.l, y: M.t, width: VBW - M.l - M.r, height: VBH - M.t - M.b,
    fill: 'none', stroke: '#e2e2e8', 'stroke-width': 1 }));

  drawHover();
}

function drawHover() {
  const old = svg.querySelector('.hoverline');
  if (old) old.remove();
  if (hoverI < 0 || hoverI >= N) { tip.style.opacity = 0; return; }
  const dd = DATA.d[hoverI];
  if (dd < x0 || dd > x1) { tip.style.opacity = 0; return; }
  const px = sx(dd), py = sy(DATA.r[hoverI]);
  const g = el('g', { class: 'hoverline' });
  g.appendChild(el('line', { x1: px, y1: M.t, x2: px, y2: VBH - M.b,
    stroke: '#b9b9c0', 'stroke-width': 1, 'stroke-dasharray': '3 3' }));
  g.appendChild(el('circle', { cx: px, cy: py, r: 3.6, fill: '#1f77b4',
    stroke: '#fff', 'stroke-width': 1.5 }));
  svg.appendChild(g);

  tip.innerHTML = fmtDay(dd) + '<br>比值 <b>' + DATA.r[hoverI].toFixed(2) + '</b>'
    + '<br>M2 ' + DATA.m[hoverI].toFixed(1) + ' 十亿美元'
    + '<br>黄金 ' + DATA.g[hoverI].toFixed(2) + ' 美元/盎司';
  tip.style.opacity = 1;
  const rect = box.getBoundingClientRect();
  const sc = rect.width / VBW;
  let left = px * sc + 14;
  if (left > rect.width - 170) left = px * sc - 160;
  tip.style.left = left + 'px';
  tip.style.top = Math.max(4, py * sc - 10) + 'px';
}

function setRange(days) {
  x1 = LAST;
  x0 = (days === 'all') ? FIRST : Math.max(FIRST, LAST - days);
  draw();
}

function zoomAt(px, factor) {
  const cx = ix(px);
  let nx0 = cx - (cx - x0) * factor;
  let nx1 = cx + (x1 - cx) * factor;
  if (nx1 - nx0 < 7) return;                        // 最小 7 天
  if (nx0 < FIRST) { nx1 += FIRST - nx0; nx0 = FIRST; }
  if (nx1 > LAST) { nx0 -= nx1 - LAST; nx1 = LAST; }
  x0 = Math.max(FIRST, nx0); x1 = Math.min(LAST, nx1);
  draw();
}

// ---- 事件 ----
function localX(evt) {
  const rect = svg.getBoundingClientRect();
  return (evt.clientX - rect.left) / rect.width * VBW;
}

svg.addEventListener('mousemove', e => {
  const px = localX(e);
  if (dragging && dragStart) {
    const span = dragStart.x1 - dragStart.x0;
    const shift = (dragStart.px - px) / (VBW - M.l - M.r) * span;
    let nx0 = dragStart.x0 + shift, nx1 = dragStart.x1 + shift;
    if (nx0 < FIRST) { nx1 += FIRST - nx0; nx0 = FIRST; }
    if (nx1 > LAST) { nx0 -= nx1 - LAST; nx1 = LAST; }
    x0 = nx0; x1 = nx1; dragMoved = true; draw(); return;
  }
  const day = ix(px);
  let i = lowerBound(day);
  if (i >= N) i = N - 1;
  if (i > 0 && Math.abs(DATA.d[i - 1] - day) < Math.abs(DATA.d[i] - day)) i--;
  hoverI = i; draw();
});

svg.addEventListener('mouseleave', () => { hoverI = -1; tip.style.opacity = 0; draw(); });

svg.addEventListener('mousedown', e => {
  dragging = true; dragMoved = false;
  dragStart = { px: localX(e), x0, x1 };
  svg.classList.add('dragging');
});

window.addEventListener('mouseup', () => {
  dragging = false; dragStart = null;
  svg.classList.remove('dragging');
});

svg.addEventListener('wheel', e => {
  e.preventDefault();
  zoomAt(localX(e), e.deltaY < 0 ? 0.85 : 1 / 0.85);
}, { passive: false });

svg.addEventListener('dblclick', () => {
  // 双击切换：当前正好是一年窗口 -> 切到全部；其余任意状态 -> 回到一年
  const isOneYear = (x1 === LAST && x0 === LAST - 365);
  document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
  if (isOneYear) {
    setRange('all');
    document.querySelector('[data-range="all"]').classList.add('active');
  } else {
    setRange(365);
    document.querySelector('[data-range="1y"]').classList.add('active');
  }
});

document.querySelectorAll('.controls button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const r = btn.dataset.range;
    setRange(r === 'all' ? 'all' : parseInt(r) * 365);
  });
});

setRange(365);
</script>
</body>
</html>"""

    return html.replace("__STATS__", stats).replace("__PAYLOAD__", data_json)


def main():
    ap = argparse.ArgumentParser(description="M2 ÷ 黄金 日度交互图")
    ap.add_argument("-o", "--out", default=None, help="输出 HTML 路径")
    args = ap.parse_args()

    m2_path = _find(M2_CSV, "m2_monthly.csv")
    gold_path = _find(GOLD_DAILY_CSV, "gold_daily.csv")

    for p, what in ((m2_path, "M2 月度"), (gold_path, "黄金日度")):
        if not os.path.exists(p):
            raise SystemExit(
                f"缺少{what}数据: {p}\n"
                "请先跑 fetch_m2_gold.py 拉取（黄金日度需新版脚本才会落盘），"
                "或把 CSV 放到 data/ 下。"
            )

    m2 = load_m2_monthly(m2_path)
    gold = load_gold_daily(gold_path)
    df = build_daily_ratio(m2, gold)
    if df.empty:
        raise SystemExit("M2 与金价没有重叠区间，无法计算日度比值。")

    payload = build_payload(df)
    latest = float(df["ratio"].iloc[-1])
    last_day = df.index.max()
    one_year_ago = df.index[df.index <= last_day - pd.Timedelta(days=365)]
    year_ago = float(df["ratio"].loc[one_year_ago[-1]]) if len(one_year_ago) else latest
    win = df[df.index > last_day - pd.Timedelta(days=365)]
    low, high = float(win["ratio"].min()), float(win["ratio"].max())

    html = render_html(
        payload,
        df.index.min().date(), last_day.date(),
        latest, year_ago, low, high,
    )

    out = args.out or _default_out(m2_path)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # 原子写入：先写临时文件再 os.replace，避免定时更新时网页撞上半截文件
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, out)

    print(f"生成: {out}")
    print(f"  日度点 {len(df)}，{df.index.min().date()} ~ {last_day.date()}")
    print(f"  最新 {latest:.2f} ｜ 一年前 {year_ago:.2f} ｜ 近一年 {low:.2f} ~ {high:.2f}")


if __name__ == "__main__":
    main()
