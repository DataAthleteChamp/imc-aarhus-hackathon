"""Follow the informed trader (pizzatrading): copy their AGGRESSIVE trades, small and capped.
Hypothesis (teammate stats, 43 signals): +4.6/lot @1min, +23.6 @5min, 90% profitable; our markout +11 @120s.
Rules: 3 lots/signal, |net| <= 12 per product, only if our fair agrees, exit after 5 min, hard flat by 17:38,
no entries after 17:36, products WIND/CO2/FLOW/ETF. Separate process; main bot untouched.
Run: DRY=1 .venv/bin/python -u copy_pizza.py   |   live: nohup .venv/bin/python -u copy_pizza.py >> copy.log &
"""
import csv
import os
import time
from datetime import datetime
from pathlib import Path

from bot import load_env
from execution import OrderManager
from fair import TZ

URL = 'https://gamma.cmi-exch.com'
LEADER = 'pizzatrading'
PRODS = {'1_WIND', '2_CO2', '3_FLOW', '4_ETF'}
SIZE, CAP, HOLD_S, SLIP = 3, 12, 300, {'1_WIND': 3, '2_CO2': 5, '3_FLOW': 6, '4_ETF': 10}
NO_ENTRY_AFTER, FLAT_BY = '17:36', '17:38'
DRY = os.environ.get('DRY') == '1'
PRED = Path(__file__).with_name('data') / 'predictions.csv'


def log(*a):
    print(datetime.now(TZ).strftime('%H:%M:%S'), *a, flush=True)


def latest_fair():
    """Last fair per product written by bot2's status (every ~15s)."""
    out = {}
    try:
        lines = PRED.read_text().splitlines()[-20:]
        for row in csv.reader(lines):
            if len(row) >= 5 and row[2] in PRODS:
                out[row[2]] = float(row[4])
    except Exception:
        pass
    return out


def main():
    load_env()
    om = OrderManager.login(URL, os.environ['CMI_USER'], os.environ['CMI_PASS'])
    seen, first = set(), True
    lots = []          # open copy lots: dict(prod, side, vol, t)
    net = {p: 0 for p in PRODS}
    last_px = {}
    log('copy_pizza started', 'DRY' if DRY else 'LIVE')

    def trade(prod, side, px, vol, tag):
        if DRY:
            log(f'DRY {tag} {side} {vol} {prod} @ {px}')
            return vol
        f = om.take(prod, side, int(px), int(vol))
        log(f'{tag} {side} {vol} {prod} @ {int(px)} filled {f}')
        return f

    while True:
        now = datetime.now(TZ)
        hm = now.strftime('%H:%M')
        try:
            r = om._req('GET', '/api/trade')
            trades = r.json() if r is not None and r.ok else []
        except Exception as e:
            log('poll error', repr(e)); time.sleep(1); continue
        for t in trades:
            last_px.setdefault(t['product'], t['price'])
        for t in trades:
            last_px[t['product']] = last_px.get(t['product'], t['price'])
        newest = {}
        for t in trades:  # trades are newest-first
            newest.setdefault(t['product'], t['price'])
        last_px.update(newest)
        fresh = [t for t in trades if t.get('id') not in seen]
        for t in fresh:
            seen.add(t.get('id'))
        if first:
            first = False
            time.sleep(1); continue
        fair = latest_fair()
        # ---- entries
        for t in reversed(fresh):
            p = t['product']
            if p not in PRODS or t.get('aggressor') != LEADER or hm >= NO_ENTRY_AFTER:
                continue
            side = 'BUY' if t.get('buyer') == LEADER else 'SELL'
            f = fair.get(p)
            if f is None or (side == 'BUY' and f <= t['price']) or (side == 'SELL' and f >= t['price']):
                log(f'skip {LEADER} {side} {p} @ {t["price"]}: fair {f} disagrees')
                continue
            room = CAP - net[p] if side == 'BUY' else CAP + net[p]
            vol = min(SIZE, room)
            if vol <= 0:
                continue
            px = t['price'] + SLIP[p] if side == 'BUY' else t['price'] - SLIP[p]
            filled = trade(p, side, px, vol, f'COPY({LEADER} {side} @ {t["price"]}, fair {f:.0f})')
            if filled:
                net[p] += filled if side == 'BUY' else -filled
                lots.append({'p': p, 'side': side, 'vol': filled, 't': time.time()})
        # ---- exits: after HOLD_S or at FLAT_BY
        keep = []
        for lot in lots:
            if time.time() - lot['t'] >= HOLD_S or hm >= FLAT_BY:
                p = lot['p']
                xs = 'SELL' if lot['side'] == 'BUY' else 'BUY'
                ref = last_px.get(p)
                if ref is None:
                    keep.append(lot); continue
                px = ref - SLIP[p] if xs == 'SELL' else ref + SLIP[p]
                f = trade(p, xs, px, lot['vol'], 'EXIT')
                net[p] += -f if xs == 'SELL' else f
                if f < lot['vol']:
                    lot['vol'] -= f; keep.append(lot)
            else:
                keep.append(lot)
        lots = keep
        if hm >= FLAT_BY and not lots:
            log('flat by', FLAT_BY, 'net', net, '- exiting'); return
        time.sleep(1)


if __name__ == '__main__':
    main()
