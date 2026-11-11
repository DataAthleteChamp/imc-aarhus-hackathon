"""Show 17:45 settlement predictions from every model side by side + market + current value.
Run: .venv/bin/python predict.py"""
import json, sys
from datetime import datetime
from pathlib import Path
import fair as F
import endgame
sys.path[:0] = ['research/wind', 'research/flow_co2']
import model_wind as MW, model_flow_co2 as MFC

now = datetime.now(F.TZ)
m = F.compute_fair(now)
rows = F.fetch_rows(now)
eg = endgame.endgame_fair(rows, now)
w, ws = MW.wind_fair(rows, now); c, cs = MFC.co2_fair(rows, now); fl, fs = MFC.flow_fair(rows, now)
rf, rs, floor = MW.range_fair(rows, now)
research = {'1_WIND': (w, ws), '2_CO2': (c, cs), '3_FLOW': (fl, fs), '4_ETF': (w + c + fl, MFC.etf_sigma(ws, cs, fs, now)),
            '5_WIND_RANGE': (rf, rs)}
# market mids from the bot's recorded books
mids = {}
for line in Path('data/books.jsonl').read_text().splitlines()[-3000:]:
    d = json.loads(line)
    b = [x for x in d['b'] if x[1] - x[2] > 0]; a = [x for x in d['a'] if x[1] - x[2] > 0]
    if b and a:
        mids[d['p']] = (b[0][0] + a[0][0]) / 2
print(f"time {now:%H:%M:%S}  data {m['data_time']}  minutes to close {m['mins_left']:.0f}  range floor {floor:.1f}\n")
print(f"{'product':13s} {'now':>7} {'nowcast':>8} {'research':>14} {'endgame':>14} {'BOT FAIR':>14} {'market':>7} {'mkt-fair/σ':>10}")
for p in F.PRODUCTS:
    r = research[p]; e = eg.get(p, (float('nan'), float('nan')))
    f, s = m['fair'][p], m['sigma'][p]
    mk = mids.get(p, float('nan'))
    print(f"{p:13s} {m['actual'][p]:7.0f} {m.get('nowcast', {}).get(p, float('nan')):8.0f} "
          f"{r[0]:7.0f} ±{r[1]:5.0f} {e[0]:7.0f} ±{e[1]:5.0f} {f:7.0f} ±{s:5.0f} {mk:7.0f} {(mk - f) / s:+10.2f}")
print('\nBOT FAIR = what the bot trades on (endgame model takes over at 17:20). mkt-fair/σ: + = market rich (sell), - = cheap (buy)')
