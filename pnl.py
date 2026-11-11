"""Live PnL per product: MTM at last trade + at our fair; spread capture stats. Run: .venv/bin/python pnl.py"""
import collections, json, os
import requests
from bot import load_env

load_env()
U = 'https://gamma.cmi-exch.com'
me = os.environ['CMI_USER']
H = {'Authorization': requests.post(U + '/api/user/authenticate',
                                    json={'username': me, 'password': os.environ['CMI_PASS']}).headers['Authorization']}
pos = requests.get(U + '/api/position/current-user', headers=H).json()
tr = requests.get(U + '/api/trade', headers=H).json()
last = {}
for t in tr:
    last.setdefault(t['product'], t['price'])
mine = [t for t in tr if me in (t['buyer'], t['seller'])]
passive = collections.Counter(t['product'] for t in mine if t['aggressor'] != me)
aggr = collections.Counter(t['product'] for t in mine if t['aggressor'] == me)
tot = 0
print(f"{'product':13s} {'pos':>5} {'MTM@last':>9} {'passive':>7} {'aggr':>5}")
for x in sorted(pos, key=lambda x: x['product']):
    p = x['product']
    m = x['cash'] + x['netPosition'] * last.get(p, 0)
    tot += m
    print(f"{p:13s} {x['netPosition']:>5} {m:>9.0f} {passive[p]:>7} {aggr[p]:>5}")
print(f"TOTAL MTM {tot:.0f}   my trades {len(mine)} / market {len(tr)}")
