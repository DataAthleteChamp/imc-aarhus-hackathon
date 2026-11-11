"""LIVE test of execution.OrderManager using only orders that cannot fill:
BUY @1-5 on 1_WIND / 5_WIND_RANGE, SELL @2900+ on 1_WIND. Never crosses the market.
NOTE: the live bot may share this account, so we only ever cancel OUR test orders
(identified by product + far-away price), never a blanket exchange-wide cancel_all.
Run: .venv/bin/python test_execution.py
"""
import json
import os
import threading
import time

import requests
import sseclient

from bot import load_env
from execution import OrderManager

URL = os.environ.get('CMI_URL', 'https://gamma.cmi-exch.com')
PRODS = ('1_WIND', '5_WIND_RANGE')


def is_test_order(o):
    p = float(o['price'])
    return o['product'] in PRODS and ((o['side'] == 'BUY' and p <= 5) or (o['side'] == 'SELL' and p >= 2900))


def books_snapshot(token, secs=6):
    books = {}

    def listen():
        h = {'Authorization': token, 'Accept': 'text/event-stream'}
        resp = requests.get(URL + '/api/market/stream', stream=True, headers=h, timeout=30)
        for ev in sseclient.SSEClient(resp).events():
            if ev.event == 'order':
                d = json.loads(ev.data)
                books[d['productsymbol']] = d
            if all(p in books for p in PRODS):
                return
    th = threading.Thread(target=listen, daemon=True)
    th.start()
    th.join(secs)
    return books


def safety_check(om):
    books = books_snapshot(om.s.headers['Authorization'])
    for p in PRODS:
        b = books.get(p)
        if b is None:
            print(f'  no book seen for {p} (ok, orders are far away anyway)')
            continue
        asks = [float(x) for x in b['sellOrders']]
        bids = [float(x) for x in b['buyOrders']]
        ba, bb = (min(asks) if asks else None), (max(bids) if bids else None)
        print(f'  {p}: best bid {bb} best ask {ba}')
        assert ba is None or ba > 10, f'{p} best ask {ba} too low - BUY@1-5 could fill'
        if p == '1_WIND':
            assert bb is None or bb < 2850, f'{p} best bid {bb} too high - SELL@2900 could fill'


def mine(om):
    r = om._req('GET', '/api/order/current-user')
    return [o for o in r.json() if is_test_order(o)]


def cleanup(om):
    ids = [o['id'] for o in mine(om)]
    list(om.pool.map(om._cancel, ids))
    left = mine(om)
    print(f'cleanup: cancelled {len(ids)}, test orders left: {len(left)}')
    return left


def main():
    load_env()
    om = OrderManager.login(URL, os.environ['CMI_USER'], os.environ['CMI_PASS'], max_rps=15,
                            order_filter=is_test_order)  # never touch the live bot's orders
    print('safety check'); safety_check(om)
    try:
        for rep in range(3):
            ten = [('BUY', 1 + i % 5, 1 + i // 5) for i in range(10)]
            a = om.set_quotes('1_WIND', ten, parallel=False)['ms']; b = om.set_quotes('1_WIND', [], parallel=False)['ms']
            c = om.set_quotes('1_WIND', ten, parallel=True)['ms']; d = om.set_quotes('1_WIND', [], parallel=True)['ms']
            print(f'rep {rep}: 10 place seq {a:.0f}ms par {c:.0f}ms | 10 cancel seq {b:.0f}ms par {d:.0f}ms')
        # ---- latency: 10 orders sequential vs parallel ----
        ten = [('BUY', 1 + i % 5, 1 + i // 5) for i in range(10)]         # 10 distinct (price, vol)
        r = om.set_quotes('1_WIND', ten, parallel=False)
        print(f'place 10 SEQUENTIAL : {r}')
        r = om.set_quotes('1_WIND', [], parallel=False)
        print(f'cancel 10 SEQUENTIAL: {r}')
        r = om.set_quotes('1_WIND', ten, parallel=True)
        print(f'place 10 PARALLEL   : {r}')
        r = om.set_quotes('1_WIND', [], parallel=True)
        print(f'cancel 10 PARALLEL  : {r}')
        mixed = ten[:5] + [('SELL', 2900 + i, 1) for i in range(5)]
        r = om.set_quotes('1_WIND', mixed)
        print(f'replace 10 PARALLEL (5 kept? no - fresh): {r}')
        r = om.set_quotes('1_WIND', [])
        print(f'cancel  : {r}')

        # ---- diffing: change one quote, others untouched ----
        q = [('BUY', 1, 1), ('BUY', 2, 1), ('SELL', 2950, 1), ('SELL', 2960, 1)]
        r = om.set_quotes('1_WIND', q); print('initial 4  :', r)
        om.set_quotes('5_WIND_RANGE', [('BUY', 1, 1), ('BUY', 3, 2)])
        ids_before = {(o.side, o.price): o.id for o in om.orders('1_WIND')}
        r = om.set_quotes('1_WIND', q); print('same again :', r)
        assert r['placed'] == 0 and r['cancelled'] == 0 and r['kept'] == 4, r
        q2 = [('BUY', 1, 1), ('BUY', 3, 1), ('SELL', 2950, 1), ('SELL', 2960, 1)]   # move BUY 2 -> 3
        r = om.set_quotes('1_WIND', q2); print('move 1     :', r)
        assert r == {**r, 'kept': 3, 'cancelled': 1, 'placed': 1}, r
        ids_after = {(o.side, o.price): o.id for o in om.orders('1_WIND')}
        for k in [('BUY', 1), ('SELL', 2950), ('SELL', 2960)]:
            assert ids_before[k] == ids_after[k], f'{k} id changed!'
        print('  untouched ids preserved OK')
        r = om.set_quotes('1_WIND', [('BUY', 1, 2)] + q2[1:]); print('resize 1   :', r)  # size change -> replace

        # ---- reconcile vs exchange ----
        local = {o.id for o in om.orders()}
        exch = {o['id'] for o in mine(om)}
        print(f'local {len(local)} vs exchange {len(exch)} test orders, equal={local == exch}')
        om.reconcile_orders()
        print('positions:', om.reconcile_positions())

        # ---- take() that cannot fill: must not rest ----
        t0 = time.perf_counter()
        f = om.take('5_WIND_RANGE', 'BUY', 2, 1)
        print(f'take (unfillable) filled={f} in {(time.perf_counter() - t0) * 1000:.0f}ms; '
              f"resting @2 on 5_WIND_RANGE: {[o for o in mine(om) if o['product'] == '5_WIND_RANGE' and float(o['price']) == 2]}")

        # ---- parallel cancel ----
        t0 = time.perf_counter()
        n = len(om.orders())
        list(om.pool.map(om._cancel, [o.id for o in om.orders()]))
        print(f'parallel cancel of {n} tracked orders: {(time.perf_counter() - t0) * 1000:.0f}ms')
        print(f'requests {om.n_requests}, errors {om.n_errors}')
    finally:
        left = cleanup(om)
        assert not left, left
        print('ALL TEST ORDERS CANCELLED')
        om.pool.shutdown()


if __name__ == '__main__':
    main()
