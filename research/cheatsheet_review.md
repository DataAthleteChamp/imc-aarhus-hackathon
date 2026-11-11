# Cheatsheet review vs. today's measurements (written ~16:30)

Sources: cheatsheets 01, 02, 03, 04, 07; params.json, fair.py, bot2.py; the stats listed in the brief.

## Bug-level finding first (fix before 17:20)

1. **The endgame schedule overrides risk-off.** `fair.py` ENDGAME_SCHEDULE writes `take_k`/`max_pos`/`min_take_edge` into
   `model['params']`, and bot2 reads that dict. From **17:20 the bot jumps from cap 10, take_k 99 to cap 90, take_k 1.0**.
   At 17:30 it goes to cap 98, and at 17:38 the take edges drop to WIND 2 / CO2 5 / FLOW 4. Our takes lost -20/unit today.
   At 90 lots, a 1-sigma miss on FLOW (sigma about 30 at 17:20) costs roughly 2-3k.
   Turn it off (`endgame_enabled: false`) or soften it (see the plan below).
2. **The ETF cap is 40, not 10.** `etf_max_pos` defaults to 40 in bot2 DEFAULTS, and params.json does not override it.
   Risk-off ETF exposure is 4x what we intended. Add `"etf_max_pos": 10`.
   From `etf_model_from` 17:30, ETF fair also switches from iNAV to the model.

## Cheatsheet strategies ranked for today

| # | Strategy (cheatsheet) | Applies? | Evidence today | Rough E[PnL] to 17:45 / risk |
|---|---|---|---|---|
| 1 | **Avoid losses / scoring discipline** (01, 02 "losses count") | Yes | -6.3k MTM, mostly FLOW. Per-product scoring: each product we lose counts against us | Saves 1-5k of downside. Biggest lever |
| 2 | **Adverse-selection protection** (03 ★★★, 04 "informed trader") | Yes, confirmed | pizzatrading +18/unit at 60s, trades sec 50..25. Tight replay -605, wide +151 per 9 min | The difference between -4k and +1k over 75 min |
| 3 | **Wide, passive MM in uninformed flow** (03 "±2 beats ±1") | Yes | 7 trades/min, sizes 1-5. Wide replay +151/9 min, about **+1.0-1.5k** to the close if the regime holds | Low risk at cap 10 |
| 4 | **Inventory skew / clear at F** (03 ★★★, v3 lesson) | Yes, for the FLOW +72 | FLOW spread 12, so crossing costs about 6/unit (about 430 for all of it). Holding sd to settle is about 31*sqrt(75/15) ≈ 70/unit, so ±5k | Unwind passively with strong skew. Reach ≤ 30 by 17:20 and ≤ 10 by 17:38 |
| 5 | **"Trade the known part"** (07) in the settle window | Yes, small | Settle = avg 17:40-17:44. Published 17:40 at about 17:41:15, so by 17:44:15 we know 4 of 5 minutes and residual sd is about 1/5 of a 1-min move (WIND about 0.7, CO2 about 1.3, FLOW about 1.6). Market mid lags 2-3 min, so it prices the last published minute, not the average | +200-800 if takes run only after 17:41:15 at modest size. Low risk once mostly known |
| 6 | **Stale-quote taking / nowcast** (02 "house goes stale", 04) | Weak | house_mm is anchored to the lagged value. AR(1) beats persistence by only 4-12% (CO2 best, phi 0.61). That is below the CO2 half-spread of 5 | About 0. Use it only as a quote-side guard (already on), not for takes before 17:40 |
| 7 | Follow the informed trader (04) | Maybe | +18/unit at 60s vs spreads 6-12, so following after their print captures part of it, minus half-spread | +? Untested; skip unless it can be backtested in 5 min |
| 8 | ETF arbitrage (03) | No | Residual mean -3, sd 7 vs ETF spread 25 plus legs 6/10/12 | 0. Keep `arb_enabled:false` |
| 9 | Momentum on F / drift (03 ★☆☆) | Risky | The FLOW +150 research drift built the losing position | Don't add exposure on drift |
| 10 | Options / RANGE pricing (03) | Low | RANGE spread 1-3, 1.1 trades/min. Right-skewed, so never sell it cheap | A small positive MM would score in one more product, but the edge is tiny. Leave disabled unless WIND/ETF are stable |

## Concrete changes (params.json; fair.py only for the endgame)

- Now: `"etf_max_pos": 10`. Keep `take_k: 99`, `mm_min_half` as is. Keep `release_widen: 2.0` (sec 50..25).
  Optionally pull quotes entirely in sec 50..25 (pizzatrading window) instead of only widening.
- FLOW unwind: skew only, never cross. Raise `spread_skew` to about 2 for FLOW if supported.
  Targets: ≤ 30 by 17:20, ≤ 10 by 17:38.
- Endgame: set `endgame_enabled: false` now. If time allows, replace the schedule with:
  - 17:20-17:41: cap 10 (ETF 10), no takes, MM as now.
  - 17:41:15-17:44:50: cap 30, `take_k` 1.0, edges WIND 3 / CO2 5 / FLOW 6 / ETF 10.
    Fair = mean(published 17:40..) blended with the nowcast for the remaining minutes.
  - 17:44:30: stop quoting. Positions settle at the settlement value, which is fine because they are near-known.
- Per product: only quote products where we're already positive or flat. Losing a product costs points.
  If WIND or ETF MM goes negative after 15 min, disable it rather than tuning.
- Don't deploy untested code after 17:25 (01 "freeze").

## Expected total if this plan holds

MM +1k (±1k). FLOW unwind -0.5k to 0 vs the current mark (±2k while held). Endgame known-part +0.3k.
Net from now: about **+1k**, with downside capped at about -2k, instead of ±5-8k exposure under the current endgame schedule.
