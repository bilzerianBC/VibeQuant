"""LiveMore 回测报告：把 summary CSV 渲染为自包含 HTML，并发布到共享网站 /livemore/。

发布命令（在 LiveMoreAmazing/ 下运行）：
    python -m livemore.report --csv results/summary_<start>_<end>.csv
"""
import argparse
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import pandas as pd

# run_backtest.py 生成的成交图文件名：chart_<代码>_<内容哈希16位>.html
CHART_FILE = re.compile(r'chart_[0-9]{6}\.(SH|SZ|BJ)_[a-f0-9]{16}\.html')


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write(content)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def render_report(df, filename):
    if 'code' not in df or 'total_return' not in df:
        raise ValueError('请选择交易回测 summary CSV；signals CSV 不包含收益报告')
    valid = df[df.total_return.notna()]
    if valid.empty:
        raise ValueError('没有有效交易回测结果')
    failed = int(df.get('error', pd.Series('', index=df.index)).fillna('').ne('').sum())
    skipped = int(df.get('skipped', pd.Series('', index=df.index)).fillna('').ne('').sum())
    now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S UTC+8')
    cards = [('总标的', str(len(df))), ('有效', str(len(valid))), ('失败', str(failed)),
             ('跳过', str(skipped))]
    for col, label in [('total_return','中位累计收益'), ('annual_return','中位年化'),
                       ('max_drawdown','中位最大回撤'), ('excess_vs_bh','中位超额收益')]:
        if col in valid:
            cards.append((label, f'{valid[col].median():.2%}'))
    cards_html = ''.join(f'<div class="card"><small>{label}</small><strong>{value}</strong></div>' for label,value in cards)
    # Only chart-bearing successful rows from this report are eligible.
    chart_options = []
    seen_codes = set()
    for row in valid.to_dict('records'):
        code, chart = str(row['code']), row.get('chart_file')
        if (isinstance(chart, str)
                and CHART_FILE.fullmatch(chart)
                and code not in seen_codes):
            chart_options.append(dict(code=code, file=chart))
            seen_codes.add(code)
    chart_json = json.dumps(chart_options, ensure_ascii=False).replace('<', '\\u003c')
    shown = df.copy()
    for col in ['total_return','annual_return','max_drawdown','winrate','buy_and_hold','excess_vs_bh']:
        if col in shown:
            shown[col] = shown[col].map(lambda v: '' if pd.isna(v) else f'{v:.2%}')
    labels = dict(code='代码', bars='日线数', start='实际起点', end='实际终点', end_value='总资产',
                  total_return='累计收益', annual_return='年化收益', max_drawdown='最大回撤',
                  winrate='胜率', buy_and_hold='买入持有', excess_vs_bh='超额收益', trades='已平仓交易',
                  reserve='储备金', end_position='期末持仓', avg_cost='持仓成本', entry_count='买入档位',
                  min_position='最低持仓', orders='订单数', error='错误', trace='异常详情', skipped='跳过原因')
    table = shown.rename(columns=labels).fillna('').to_html(index=False, escape=True, table_id='results', border=0)
    return f'''<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LiveMore 回测报告</title>
<style>body{{font:15px/1.6 system-ui;margin:32px;background:#fbfbf9;color:#16181d}}main{{max-width:1400px;margin:auto}}a{{color:#2f5d8c}}.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}}.card{{background:white;border:1px solid #ddd;padding:14px 20px;min-width:110px}}strong{{display:block;font-size:24px}}small,p{{color:#666}}.scroll{{overflow:auto;max-height:70vh}}table{{border-collapse:collapse;background:white;font-size:13px}}td,th{{padding:10px;border-bottom:1px solid #ddd;white-space:nowrap;text-align:right}}th{{position:sticky;top:0;background:#eef1f4}}input{{padding:10px;margin-bottom:16px;width:240px}}.chart-panel{{margin:24px 0;border:1px solid #ddd;background:white;padding:12px}}.chart-panel h3{{margin:0 0 8px}}.chart-panel iframe{{display:block;width:100%;height:700px;border:0}}button{{padding:10px 18px;cursor:pointer}}button:disabled{{cursor:default}}@media(max-width:600px){{body{{margin:16px}}.chart-panel{{padding:4px}}}}</style>
<main><a href="/">← VibeQuant</a><h1>LiveMore 回测报告</h1>
<p>来源：{escape(filename)} · 报告生成：{now}</p>
<p>每个标的独立账户回测；以下为跨标的统计，不是组合净值。失败和跳过标的不计入收益统计。</p>
{('<p>本次结果含失败标的，请检查表格错误列。</p>' if failed else '')}
<div class="cards">{cards_html}</div><p><a href="summary.csv" download>下载本次 CSV</a></p>
<section aria-labelledby="sample-title">
<h2 id="sample-title">随机十个标的 · BUY / SELL 图</h2>
<button id="shuffle-charts" type="button">换一组</button>
<p id="sample-status" role="status"></p><div id="sample-charts"></div>
</section>
<h2>全部标的明细</h2>
<input id="search" placeholder="输入股票代码筛选" aria-label="筛选股票代码">
<p>点击表格中的图表链接查看 K 线及实际 BUY/SELL 成交标记。</p>
<div class="scroll">{table}</div></main><script>
const chartOptions = {chart_json};
function selectCharts(options, count = 10) {{
 const shuffled = options.slice();
 for (let i = shuffled.length - 1; i > 0; i--) {{
   const j = Math.floor(Math.random() * (i + 1));
   [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
 }}
 return shuffled.slice(0, count);
}}
function showCharts() {{
 const selected = selectCharts(chartOptions);
 const container = document.getElementById('sample-charts');
 container.replaceChildren();
 selected.forEach((item, i) => {{
   const panel = document.createElement('article'); panel.className = 'chart-panel';
   const heading = document.createElement('h3');
   const link = document.createElement('a'); link.href = item.file;
   link.textContent = `${{i + 1}}. ${{item.code}} · 单独打开`;
   heading.appendChild(link);
   const frame = document.createElement('iframe'); frame.src = item.file;
   frame.title = `${{item.code}} K线及BUY/SELL成交标记`; frame.loading = 'lazy';
   panel.append(heading, frame); container.appendChild(panel);
 }});
 document.getElementById('sample-status').textContent = chartOptions.length
   ? `本次报告有 ${{chartOptions.length}} 个可用标的图，当前展示 ${{selected.length}} 个（不重复）。`
   : '本次报告没有成交图，请开启交易重新回测并发布带 chart_file 的结果。';
 document.getElementById('shuffle-charts').disabled = chartOptions.length <= 10;
}}
document.getElementById('shuffle-charts').addEventListener('click', showCharts);
showCharts();
const headers = Array.from(document.querySelectorAll('#results thead th'));
const chartColumn = headers.findIndex(th => th.textContent === 'chart_file');
if (chartColumn >= 0) document.querySelectorAll('#results tbody tr').forEach(row => {{
 const cell=row.cells[chartColumn], file=cell.textContent.trim();
 if (/^chart_[0-9]{{6}}\\.(SH|SZ|BJ)_[a-f0-9]{{16}}\\.html$/.test(file)) {{
   const link=document.createElement('a'); link.href=file; link.textContent='查看 BUY/SELL 图';
   cell.replaceChildren(link);
 }}
}});
document.getElementById('search').addEventListener('input', function() {{
const q=this.value.trim(); document.querySelectorAll('#results tbody tr').forEach(row=>{{
row.hidden=!row.cells[{list(df.columns).index('code')}].textContent.includes(q);
}}); }});
</script></html>'''


def main():
    ap = argparse.ArgumentParser(description='Publish an explicitly selected trading summary to the shared static site.')
    ap.add_argument('--csv', type=Path, required=True, help='明确指定本次 summary CSV')
    ap.add_argument('--site-dir', type=Path, default=os.environ.get('VIBEQUANT_SITE_DIR','/srv/web'))
    ap.add_argument('--portal-template', type=Path, default='/opt/vibequant-front/index.html')
    args = ap.parse_args()
    source = args.csv.read_bytes()
    df = pd.read_csv(io.BytesIO(source))
    html = render_report(df, args.csv.name)
    portal = args.portal_template.read_bytes()
    charts = {}
    for filename in df.get('chart_file', pd.Series(dtype=str)).dropna():
        if not CHART_FILE.fullmatch(filename):
            raise ValueError(f'非法图表文件名: {filename}')
        charts[filename] = (args.csv.parent / filename).read_bytes()
    # Immutable report directory avoids mixing HTML and CSV from different runs.
    target = args.site_dir / 'livemore' / hashlib.sha256(source).hexdigest()[:16]
    for filename, content in charts.items():
        atomic_write(target / filename, content)
    atomic_write(target / 'summary.csv', source)
    atomic_write(target / 'index.html', html.encode())
    atomic_write(args.site_dir / 'livemore/index.html', (
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='
        + target.name + '/"><a href="' + target.name + '/">查看最新回测报告</a>').encode())
    atomic_write(args.site_dir / 'index.html', portal)
    print(f'报告已发布：{target / "index.html"}；入口 /livemore/')


if __name__ == '__main__':
    main()
