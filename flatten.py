"""Risk-off: flatten selected products by hitting the top of book, with a max-slippage guard.
Usage: .venv/bin/python flatten.py 3_FLOW 2_CO2 4_ETF      (STOP the bot first)
"""
import os
import sys
import time

from bot import load_env
from execution import OrderManager

URL = 'https://gamma.cmi-exch.com'
MAX_SLIP = {'1_WIND': 10, '2_CO2': 25, '3_FLOW': 35, '4_ETF': 45, '5_WIND_RANGE': 10}
CLIP = 10

books = {}


def on_book(d):
    bids = sorted(((float(p), v['marketVolume'] - v['userVolume']) for p, v in d['buyOrders'].items()), reverse=True)
    asks = sorted((float(p), v['marketVolume'] - v['userVolume']) for p, v in d['sellOrders'].items())
    books[d['productsymbol']] = ([b for b in bids if b[1] > 0], [a for a in asks if a[1] > 0])


def positions(om):
    r = om._req('GET', '/api/position/current-user')
    return {x['product']: x['netPosition'] for x in r.json()} if r is not None and r.ok else {}


def main(products):
    load_env()
    om = OrderManager.login(URL, os.environ['CMI_USER'], os.environ['CMI_PASS'])
    om.cancel_all()
    om.start_stream(on_orderbook=on_book)
    time.sleep(4)
    start_px = {}
    for _ in range(60):
        pos = positions(om)
        todo = [p for p in products if pos.get(p, 0) != 0]
        if not todo:
            break
        for prod in todo:
            q = pos[prod]
            bids, asks = books.get(prod, ([], []))
            side, lvl = ('SELL', bids) if q > 0 else ('BUY', asks)
            if not lvl:
                print(prod, 'no liquidity on', side, 'side')
                continue
            px, vol = lvl[0]
            ref = start_px.setdefault(prod, px)
            if (side == 'SELL' and px < ref - MAX_SLIP[prod]) or (side == 'BUY' and px > ref + MAX_SLIP[prod]):
                print(prod, f'slippage guard hit at {px} (start {ref}); stopping this product')
                products = [p for p in products if p != prod]
                continue
            v = int(min(abs(q), vol, CLIP))
            f = om.take(prod, side, int(px), v)
            print(f'{prod} pos {q:+} {side} {v} @ {px:.0f} filled {f}')
        time.sleep(0.6)
    print('FINAL positions:', positions(om))
    os._exit(0)


if __name__ == '__main__':
    main(sys.argv[1:] or ['3_FLOW', '2_CO2', '4_ETF'])
