# Results: IMC Aarhus Trading Hackathon (11 Nov 2026)

**Official: 2nd place on points, P&L +13,789.1 (exchange dashboard), all 5 products positive.**

Exchange per-product P&L at close: WIND +121.6, CO2 +1,511.9, FLOW +4,229.5, ETF +2,378.5, WIND_RANGE +5,547.6.
The table below is our own settlement-price calculation, which differs from the exchange's marking.

| Product | Settle (avg 17:40–17:44) | Final pos | PnL |
|---|---|---|---|
| 1_WIND | 443.1 | −36 | +132 |
| 2_CO2 | 727.1 | +3 | +1,502 |
| 3_FLOW | 1768.6 | +25 | +4,257 |
| 4_ETF | 2938.7 | +5 | +2,366 |
| 5_WIND_RANGE | 174.9 | −66 | +1,621 |

## Strategy
- **Model:** AR(1) nowcast + endgame settlement model (`fair.py`, `endgame.py`), backtested on 47 days of Energinet data (`research/`).
- **Gap taker:** market mids lag published data by 2–3 min; take stale quotes (mainly CO2).
- **Market making** (`bot2.py`, `execution.py`): quote a tick inside the touch, inventory skew, cap 10; spreads tuned by replaying recorded books (`research/mm/replay.py`) once the volatility bots joined.
- **Endgame from 17:20:** take toward settlement fair, threshold 1σ → 0.5σ, published settlement minutes locked; WIND_RANGE locked, so we sold it above value.
- **Risk:** an early oversized FLOW position cost ~6k; fixed with hard caps and backtest-only changes.

## Speech (short, technical)
We built an AR(1) nowcast and an endgame settlement model, backtested on 47 days of Energinet data. Market mids lagged the
published data by 2–3 minutes, so a gap taker hit stale quotes, mainly in CO2. For market making we quoted a tick inside the
touch with inventory skew and a cap of 10, tuning spreads by replaying the recorded order book after the volatility bots
joined. ETF was our best earner. From 17:20 the endgame took toward the settlement fair value, tightening from 1σ to 0.5σ
and locking settlement minutes as they published. WIND_RANGE was mathematically locked, so we sold it above value. An early
oversized FLOW position cost ~6k; we fixed it with hard caps and only shipped backtested changes. Result: ~+9,900,
all five products positive.

## Lessons
1. Hard position caps from the start; thin books punish size.
2. Measure before trading: market lag, noise-bot markouts, replay backtests.
3. No manual trades against the bot's rules.
