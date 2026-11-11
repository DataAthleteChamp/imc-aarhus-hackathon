"""Live PnL per product marked 3 ways: last trade, current Energinet value, our 17:45 fair (incl. endgame).
Flags products that are negative at fair. Run: .venv/bin/python pnl.py"""
import collections, os
import requests
from bot import load_env
import fair as F

load_env()
U = 'https://gamma.cmi-exch.com'
me = os.environ['CMI_USER']
H = {'Authorization': requests.post(U + '/api/user/authenticate',
                                    json={'username': me, 'password': os.environ['CMI_PASS']}).headers['Authorization']}
pos = requests.get(U + '/api/position/current-user', headers=H).json()
tr = requests.get(U + '/api/trade', headers=H).json()
m = F.compute_fair()
last = {}
for t in tr:
    last.setdefault(t['product'], t['price'])
mine = [t for t in tr if me in (t['buyer'], t['seller'])]
passive = collections.Counter(t['product'] for t in mine if t['aggressor'] != me)
aggr = collections.Counter(t['product'] for t in mine if t['aggressor'] == me)
tl = te = tf = 0
print(f"{'product':13s} {'pos':>4} {'@last':>8} {'@energinet':>10} {'@fair1745':>9}  pas/agg")
for x in sorted(pos, key=lambda x: x['product']):
    p, q, c = x['product'], x['netPosition'], x['cash']
    a, b, f = c + q * last.get(p, 0), c + q * m['actual'][p], c + q * m['fair'][p]
    tl, te, tf = tl + a, te + b, tf + f
    flag = '  <-- NEGATIVE at fair' if f < 0 else ''
    print(f"{p:13s} {q:>4} {a:>8.0f} {b:>10.0f} {f:>9.0f}  {passive[p]}/{aggr[p]}{flag}")
print(f"{'TOTAL':13s} {'':>4} {tl:>8.0f} {te:>10.0f} {tf:>9.0f}   data {m['data_time']}")
