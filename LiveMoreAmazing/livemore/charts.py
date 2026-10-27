# -*- coding: utf-8 -*-
"""利弗莫尔六列状态机的 K 线阶段图：分段、极值点、成交标记，渲染为自包含 HTML。

被 run_backtest.py 用来生成每只标的的 BUY/SELL 成交图。
"""

from __future__ import annotations

import json

from .livermore_strategy import LivermoreMarketKey

# 六阶段配色（A 股红涨绿跌；阶段用半透明背景区分）
PHASE_COLOR = {
    "上涨趋势": "rgba(239,83,80,0.16)",   # 红
    "下跌趋势": "rgba(38,166,154,0.16)",  # 青绿
    "自然回调": "rgba(255,167,38,0.18)",  # 橙
    "自然反弹": "rgba(66,165,245,0.18)",  # 蓝
    "二次回调": "rgba(171,71,188,0.18)",  # 紫
    "二次反弹": "rgba(38,198,218,0.18)",  # 青
}
# 向上列（极值取最高） / 向下列（极值取最低）
UP_COLS = {"上涨趋势", "自然反弹", "二次反弹"}


def analyze(code: str, df):
    """跑状态机，返回每 bar 阶段 + 分段 + 各段极值点。"""
    key = LivermoreMarketKey(0.06, 0.03)
    cols = []
    for c in df["close"]:
        key.update(float(c))
        cols.append(key.col.value if key.col else None)

    # 合并连续相同阶段为分段
    segments = []
    s = 0
    n = len(cols)
    for i in range(1, n + 1):
        if i == n or cols[i] != cols[s]:
            if cols[s] is not None:
                segments.append({"start": s, "end": i - 1, "phase": cols[s]})
            s = i

    # 每段的极值点（最值点）：向上列取该段 high 最高，向下列取 low 最低
    pivots = []
    for seg in segments:
        sub = df.iloc[seg["start"]:seg["end"] + 1]
        if seg["phase"] in UP_COLS:
            j = sub["high"].values.argmax()
            idx = seg["start"] + int(j)
            pivots.append({"idx": idx, "price": float(sub["high"].values[j]),
                           "dir": "high", "phase": seg["phase"]})
        else:
            j = sub["low"].values.argmin()
            idx = seg["start"] + int(j)
            pivots.append({"idx": idx, "price": float(sub["low"].values[j]),
                           "dir": "low", "phase": seg["phase"]})
    return segments, pivots


def trade_chart(code, df, fills):
    segments, pivots = analyze(code, df)
    return dict(code=code, dates=[d.strftime('%Y-%m-%d') for d in df.index],
                ohlc=df[['open', 'close', 'low', 'high']].values.tolist(),
                segments=segments, pivots=pivots, fills=fills, trading_enabled=True)


def build_html(charts):
    data_json = json.dumps(charts, ensure_ascii=False).replace("<", "\\u003c")
    color_json = json.dumps(PHASE_COLOR, ensure_ascii=False)
    legend = "".join(
        f'<span style="display:inline-block;margin:0 10px;">'
        f'<span style="display:inline-block;width:14px;height:14px;background:{c};'
        f'border:1px solid #888;vertical-align:middle;"></span> {name}</span>'
        for name, c in PHASE_COLOR.items()
    )
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>利弗莫尔六列状态机 · K线阶段可视化</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  body{{font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;margin:0;background:#fafafa;color:#222;}}
  h1{{font-size:20px;padding:16px 20px 4px;}}
  .legend{{padding:6px 20px 14px;font-size:13px;color:#444;}}
  .note{{padding:0 20px 14px;font-size:12px;color:#888;}}
  .chart{{width:100%;height:460px;margin-bottom:8px;}}
  .title{{padding:14px 20px 0;font-size:15px;font-weight:600;}}
</style></head>
<body>
  <h1>利弗莫尔《股票大作手操盘术》六列状态机 — K 线阶段可视化</h1>
  <div class="legend">阶段背景色：{legend}</div>
  <div class="note">阈值：转向 = 当前列极值价的 6%（原书 6 美元）、次级 = 3%（原书 3 美元）。
    ▼=向上列(上涨趋势/反弹)的最高极值点，▲=向下列(下跌趋势/回调)的最低极值点。可框选缩放。红色 BUY / 蓝色 SELL 表示实际成交，悬停查看成交价与股数；不是信号日期。<a href="index.html">返回报告</a></div>
  <div id="container"></div>
<script>
const CHARTS = {data_json};
const PHASE_COLOR = {color_json};
const container = document.getElementById('container');

CHARTS.forEach((ch, k) => {{
  const title = document.createElement('div');
  title.className = 'title';
  title.innerHTML = `${{k+1}}. ${{ch.code}} &nbsp; `
    + ` <span style="color:#888">${{ch.trading_enabled ? '实际成交 BUY / SELL' : '交易已关闭'}} · ${{ch.dates[0]}} ~ ${{ch.dates[ch.dates.length-1]}}</span>`;
  container.appendChild(title);

  const div = document.createElement('div');
  div.className = 'chart';
  container.appendChild(div);
  const chart = echarts.init(div);

  // 阶段背景 markArea
  const areas = ch.segments.map(s => ([
    {{ xAxis: ch.dates[s.start], itemStyle: {{ color: PHASE_COLOR[s.phase] || 'transparent' }} }},
    {{ xAxis: ch.dates[s.end] }}
  ]));

  // 极值点：向上列▼(红，标在上方)，向下列▲(绿，标在下方)
  const upPts = ch.pivots.filter(p => p.dir === 'high')
      .map(p => ({{ coord: [ch.dates[p.idx], p.price], value: p.price }}));
  const dnPts = ch.pivots.filter(p => p.dir === 'low')
      .map(p => ({{ coord: [ch.dates[p.idx], p.price], value: p.price }}));

  chart.setOption({{
    animation: false,
    tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
    grid: {{ left: 56, right: 24, top: 16, bottom: 70 }},
    xAxis: {{ type: 'category', data: ch.dates, boundaryGap: true,
              axisLine: {{ onZero: false }}, splitLine: {{ show: false }} }},
    yAxis: {{ scale: true, splitLine: {{ show: true, lineStyle: {{ color: '#eee' }} }} }},
    dataZoom: [
      {{ type: 'inside', start: 0, end: 100 }},
      {{ type: 'slider', start: 0, end: 100, bottom: 18 }}
    ],
    series: [{{
      type: 'candlestick',
      data: ch.ohlc,
      itemStyle: {{ color: '#e53935', color0: '#26a69a',
                    borderColor: '#e53935', borderColor0: '#26a69a' }},
      markArea: {{ silent: true, data: areas }},
      markPoint: {{
        symbolSize: 10,
        data: [
          ...upPts.map(p => ({{ ...p, symbol: 'triangle', symbolRotate: 180,
              itemStyle: {{ color: '#c62828' }}, label: {{ show: false }} }})),
          ...dnPts.map(p => ({{ ...p, symbol: 'triangle',
              itemStyle: {{ color: '#00897b' }}, label: {{ show: false }} }})),
        ]
      }}
    }}, ...['BUY', 'SELL'].map(side => ({{
      name: side, type: 'scatter', symbol: side === 'BUY' ? 'triangle' : 'diamond',
      symbolSize: 14, z: 10,
      itemStyle: {{ color: side === 'BUY' ? '#c62828' : '#1565c0' }},
      label: {{ show: true, formatter: side, position: side === 'BUY' ? 'bottom' : 'top' }},
      tooltip: {{ trigger: 'item', formatter: p =>
        `${{side}} · ${{p.data.value[0]}}<br>成交价 ${{p.data.value[1].toFixed(3)}}<br>股数 ${{p.data.size}}` }},
      data: (ch.fills || []).filter(f => f.side === side).map(f => ({{
        value: [f.date, f.price], size: f.size
      }}))
    }}))]
  }});
  window.addEventListener('resize', () => chart.resize());
}});
</script>
</body></html>"""
