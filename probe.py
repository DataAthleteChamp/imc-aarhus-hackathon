"""Exchange probe: latency, order place/cancel, book depth, house_mm behaviour, rate limits.
Places only far-from-market 1-lot orders (cannot fill) and cancels them.
Run: .venv/bin/python probe.py
"""
import json
import os
import statistics as st
import threading
import time

import requests
import sseclient

from bot import load_env

URL = os.environ.get('CMI_URL', 'https://gamma.cmi-exch.com')
S = requests.Session()  # keep-alive: much lower latency than requests.get each time


def timed(method, path, **kw):
    t = time.perf_counter()
    r = S.request(method, URL + path, timeout=10, **kw)
    return r, (time.perf_counter() - t) * 1000


def main():
    load_env()
    r, ms = timed('POST', '/api/user/authenticate',
                  json={'username': os.environ['CMI_USER'], 'password': os.environ['CMI_PASS']})
    print(f'login {r.status_code} {ms:.0f}ms')
    r.raise_for_status()
    S.headers.update({'Authorization': r.headers['Authorization'], 'Content-Type': 'application/json'})

    # ---- latency of reads ----
    for path in ['/api/product', '/api/position/current-user', '/api/order/current-user', '/api/trade']:
        lat = []
        for _ in range(5):
            r, ms = timed('GET', path)
            lat.append(ms)
        print(f'GET {path:28s} {r.status_code} median {st.median(lat):.0f}ms  min {min(lat):.0f}  max {max(lat):.0f}')
    products = S.get(URL + '/api/product').json()
    print('\nPRODUCTS'); [print(' ', p) for p in products]
    print('\nPOSITIONS', S.get(URL + '/api/position/current-user').json())

    trades = S.get(URL + '/api/trade').json()
    print(f'\nTRADES total {len(trades) if isinstance(trades, list) else trades}')
    if isinstance(trades, list):
        for t in trades[:15]:
            print(' ', t.get('timestamp', '')[11:19], t['product'], t['price'], 'x', t['volume'],
                  t.get('buyer'), '<-', t.get('seller'), 'aggr', t.get('aggressor'))

    # ---- SSE: collect books for 8 s ----
    books, sse_trades, n_events = {}, [], [0]

    def listen():
        h = {'Authorization': S.headers['Authorization'], 'Accept': 'text/event-stream'}
        resp = requests.get(URL + '/api/market/stream', stream=True, headers=h, timeout=30)
        for ev in sseclient.SSEClient(resp).events():
            n_events[0] += 1
            if ev.event == 'order':
                d = json.loads(ev.data)
                books[d['productsymbol']] = d
            elif ev.event == 'trade':
                sse_trades.extend(json.loads(ev.data))
    threading.Thread(target=listen, daemon=True).start()
    time.sleep(8)
    print(f'\nSSE: {n_events[0]} events in 8s, {len(sse_trades)} trades')
    for prod in sorted(books):
        d = books[prod]
        bids = sorted(((float(p), v) for p, v in d['buyOrders'].items()), reverse=True)
        asks = sorted((float(p), v) for p, v in d['sellOrders'].items())
        print(f'\n{prod}  levels bid {len(bids)} ask {len(asks)}')
        for (bp, bv), (ap, av) in zip(bids[:5] + [(None, {})] * 5, asks[:5] + [(None, {})] * 5):
            if bp is None and ap is None:
                break
            print(f"   {bv.get('marketVolume', ''):>5} @ {bp!s:>7}   |   {ap!s:<7} @ {av.get('marketVolume', '')}")

    # ---- place far-away order, measure, cancel ----
    prod = '1_WIND'
    r, ms = timed('POST', '/api/order', json={'product': prod, 'side': 'BUY', 'price': 1, 'volume': 1})
    print(f'\nPLACE BUY 1 {prod} @1 -> {r.status_code} {ms:.0f}ms {r.text[:300]}')
    oid = r.json().get('id') if r.ok else None
    r, ms = timed('GET', '/api/order/current-user')
    print(f'my orders {ms:.0f}ms: {r.text[:300]}')
    if oid:
        r, ms = timed('DELETE', f'/api/order/{oid}')
        print(f'CANCEL by id -> {r.status_code} {ms:.0f}ms {r.text[:200]}')
    # cancel by price
    timed('POST', '/api/order', json={'product': prod, 'side': 'BUY', 'price': 2, 'volume': 1})
    r, ms = timed('DELETE', '/api/order', params={'product': prod, 'price': 2})
    print(f'CANCEL by price -> {r.status_code} {ms:.0f}ms {r.text[:200]}')
    # invalid orders: what errors look like
    for bad in [{'product': prod, 'side': 'BUY', 'price': 1.5, 'volume': 1},
                {'product': prod, 'side': 'BUY', 'price': 1, 'volume': 101}]:
        r, ms = timed('POST', '/api/order', json=bad)
        print(f'BAD {bad} -> {r.status_code} {r.text[:200]}')
        if r.ok and r.json().get('id'):
            timed('DELETE', f"/api/order/{r.json()['id']}")

    # ---- burst: rate limit? ----
    codes = []
    t0 = time.perf_counter()
    for _ in range(20):
        r, _ = timed('GET', '/api/order/current-user')
        codes.append(r.status_code)
    print(f'\nBURST 20 GETs in {(time.perf_counter() - t0) * 1000:.0f}ms codes {sorted(set(codes))}')
    left = S.get(URL + '/api/order/current-user').json()
    print('open orders after cleanup:', left)


if __name__ == '__main__':
    main()
