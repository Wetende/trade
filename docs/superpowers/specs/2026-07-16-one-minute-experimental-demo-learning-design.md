# One Minute Experimental DEMO Learning V1

## Purpose

Run the existing deterministic M1 engine on a verified MT5 DEMO account at
volume `0.1` to collect broker-real execution evidence while the strategy
remains economically unpromoted. This exception exists because the user
explicitly requested an order-capable learning run rather than another shadow.

The run is research, not evidence that the strategy has positive expectancy.
It cannot produce a promotion record or authorize REAL trading.

## Lessons applied before the run

The frozen learning ledger contains 54 fills, 15 wins, 39 losses, net
`-1963.10`, profit factor `0.2761`, and six negative trigger groups. Of 22
losses with sampled MFE, 18 recorded zero favorable excursion.

The admission firewall therefore:

- blocks both failed-break triggers, which were 0-for-7 in the learning set;
- requires candidate score at least `8`;
- requires stop-to-spread multiple at least `2.2`;
- disables volume boosting;
- keeps every existing closed-candle, stale-entry, geometry, pressure, pulse,
  one-lifecycle, and broker-safety rejection.

These are experimental protections. Historical exclusion results are not
causal proof and cannot be promoted.

## Runtime contract

- Account: DEMO only; REAL mutations are always forbidden.
- Symbol/timeframe: configured broker Gold symbol, M1 only.
- Volume: exactly `0.1`.
- Each session: no more than three hours.
- Overall authorization: expires after 48 hours.
- Session loss limit: `20` account-currency units.
- Two-loss pause: 15 minutes.
- Volume boost, martingale, grid, straddle, LLM decisions: disabled.
- M15/M30: untouched.

At any runtime or risk deadline, new entries stop. The runner cancels all
pending orders, manages open positions during a 120-second grace period, then
closes remaining DEMO positions. It does not terminate until two fresh
snapshots prove zero orders and zero positions.

MT5 lifecycle hardening is part of the frozen runtime:

- A pending M1 stop rejected once with MT5 `10015 Invalid price` may be rebuilt
  once from a fresh quote. Entry drift is capped at `0.15R`, the structural
  stop is retained, reward/risk is preserved, and stop distance remains no
  greater than one price unit. A second rejection or excessive movement skips
  the order.
- A transient MT5 bridge/terminal authorization error records a failed-health
  heartbeat and retries without analysis or an order attempt. It does not
  terminate the session.
- The 48-hour supervisor never opens a competing MT5 connection while a runner
  is active. Between three-hour sessions it proves DEMO and flat state, writes
  a checkpoint, then starts the same frozen `0.1` runner.

## Evidence handling

Every session is labeled:

- `EXPERIMENTAL_DEMO_ONLY`;
- `HYPOTHESIS_GENERATION_ONLY`;
- `promotion_eligible=false`.

Three-hour reviews must reconcile orders, fills, closes, wins, losses,
break-even, net, profit factor, expectancy, MFE/MAE coverage, entry drift,
rejections, cooldowns, safety failures, and verified-flat shutdown. Findings
may generate fixes and new preregistered candidates, but this experiment cannot
bypass the normal discovery, held-out, prospective, and promoted-DEMO gates.
The supervisor records descriptive checkpoints only; it cannot mutate live
rules or promote a candidate automatically.
