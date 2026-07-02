# One Minute Scalper Forensic Review

**Evidence session:** `results/2026-07-01-182530-one-minute-signal-reliability`
**Review date:** 2026-07-02
**Account scope:** DEMO only
**Strategy scope:** deterministic One Minute Scalper, `fast_only`, M1, closed-candle confirmation

## Executive conclusion

The session was operationally healthy but economically unsuccessful.

- 21 trades closed: 7 wins, 14 losses, 0 break-even
- net P/L: -604
- gross profit: 434
- gross loss: -1,038
- profit factor: 0.4181
- expectancy: -28.76 per filled trade
- maximum loss streak: 3
- 23 orders placed, 21 filled, 2 expired and cancelled
- 0 broker entry rejections
- 0 data-health blocks
- 0 orders or positions remained open
- the runner stopped correctly at the configured 600 session-loss limit

The main economic failure was not slow position management. Eleven of the 14
losses recorded no favorable excursion at all, and losses averaged only 0.037
favorable price movement before failing. Winners averaged 0.671 favorable
movement. The losing entries were therefore usually wrong immediately.

The six successful intrabar adverse exits reduced realized loss from an
estimated 489.76 at the original structural stops to 378.00, a reduction of
about 111.76 before any unobserved slippage. Disabling or delaying that
protection is not supported by this evidence.

The sample does not support deleting respect, fakeout, impulse, BUY, SELL,
two-touch, or three-touch families. Fakeouts were 0-for-3, eight-touch levels
were 0-for-3, and BUY trades underperformed, but those samples are too small
and confounded to justify a permanent family ban.

Two confirmed implementation/telemetry gaps require correction:

1. The written strategy requires durable same-opening reset enforcement, but
   the model reconstructs opening memory independently on each analysis and
   does not persist a consumed opening fingerprint across placed, expired, or
   completed orders.
2. The journal does not preserve distinct decision, order-send, fill, and exit
   quote snapshots. Two fills consequently appear 0.47 and 0.58 seconds before
   their journaled order event, and sampled MFE/MAE omit some fill/exit
   extrema. This does not change broker P/L, but it limits forensic certainty.

## Evidence and method

The review used:

- `mt5_runner/cycles.jsonl`
- `mt5_runner/summary.json`
- final heartbeat and runner state
- all 216 engine telemetry payloads
- all 216 order proposals
- 8,667 execution-journal events
- durable execution state
- reconciled broker deal history
- broker M1 history for the signal interval

No credential, account login, private token, terminal credential store, or
populated environment value is reproduced in this report.

All entry judgments use information available at or before the signal. Later
candles are used only to evaluate the already-made decision and management.
A later loss does not make an otherwise valid entry invalid retroactively.

### Measurement conventions

- Times in the trade tables are America/New_York (EDT, UTC-04:00).
- `Touch age` is the number of closed M1 bars since the last matching
  pre-trigger touch emitted in opening memory. `current/-` means the current
  reaction was fresh but the selected level could not be matched uniquely to
  the emitted base-opening indices.
- `Body/med` is confirmation-candle body divided by the median range of the
  preceding 12 closed M1 candles.
- `Opp wick` is the wick against the proposed direction.
- `D/O/F spread` means decision spread, order-send spread, and the first
  monitored spread after fill. The order-send value is the decision snapshot
  because a separate order-send quote was not journaled. The fill value is a
  proxy, not an exact fill-time quote.
- `Drift` is adverse fill drift from the proposed entry. Small negative values
  are favorable rounding.
- MFE and MAE are sampled by the one-second management loop. They are lower
  bounds rather than tick-perfect extrema.
- `P` management means the deterministic proposal's partial, break-even,
  trailing, scalp-profit, emergency-adverse, and candle-rejection rules.

## Aggregate performance

| Metric | Result |
|---|---:|
| Wins / losses / break-even | 7 / 14 / 0 |
| Win rate | 33.33% |
| Net P/L | -604.00 |
| Gross profit / gross loss | 434.00 / -1,038.00 |
| Profit factor | 0.4181 |
| Average win | 62.00 |
| Average loss | -74.14 |
| Expectancy per trade | -28.76 |
| Maximum loss streak | 3 |
| Orders placed / filled / expired | 23 / 21 / 2 |
| Fill / expiration rate | 91.30% / 8.70% |
| Broker entry rejections | 0 |
| Health blocks | 0 |

## Chronological entry reconstruction

Every selected candidate ranked first. Trade 8 had two approved same-direction
candidates; the score-14 impulse correctly ranked ahead of the score-11
fakeout. Every other order cycle had one approved candidate.

| # | Signal | Trigger / side | Level; touches; touch age | Confirmation quality | Rank; score | Pressure / pulse | D/O/F spread | Close; proposed entry; fill; drift | Stop; target; risk; reward; stop/spread | Wait |
|---:|---|---|---|---|---|---|---|---|---|---:|
| 1 | 18:29 | FAILED_HIGH_BREAK_SELL / SELL | 4038.5975; 8; 3 | rejection; body/med 0.30; opp wick 0.23 | 1/1; 8 | neutral / bullish | .33/.33/.29 | 4038.27; 4037.9275; 4037.93; -0.0025 | 4038.7124; 4036.7502; .7849; 1.1773; 2.38 | 7.1s |
| 2 | 18:33 | LOW_RESPECT_BUY / BUY | 4037.4275; 4; 3 | rejection; 0.32; .31 | 1/1; 8 | neutral / neutral | .29/.29/- | 4038.26; 4038.3525; unfilled; - | 4037.3877; 4039.7997; .9648; 1.4472; 3.33 | expired |
| 3 | 18:45 | CLEAN_HIGH_IMPULSE_BUY / BUY | 4040.3840; 5; 1 | strong close; 0.92; .21 | 1/1; 15 | bullish / bullish | .33/.33/.29 | 4041.05; 4041.5425; 4041.54; -0.0025 | 4040.8325; 4042.6075; .7100; 1.0650; 2.15 | 3.4s |
| 4 | 18:54 | CLEAN_LOW_IMPULSE_SELL / SELL | 4043.2033; 3; 2 | strong close; 0.66; .02 | 1/1; 13 | neutral / bullish | .33/.33/- | 4042.58; 4042.5800; unfilled; - | 4043.3383; 4041.4425; .7583; 1.1375; 2.30 | expired |
| 5 | 19:02 | HIGH_RESPECT_SELL / SELL | 4043.8400; 8; 1 | rejection; 0.52; .13 | 1/1; 7 | bullish / neutral | .33/.33/.33 | 4043.21; 4043.1175; 4043.12; -0.0025 | 4043.8527; 4042.0147; .7352; 1.1028; 2.23 | 13.5s |
| 6 | 19:08 | LOW_RESPECT_BUY / BUY | 4041.7900; 3; current/- | rejection; 0.29; .09 | 1/1; 11 | bullish / bearish | .32/.32/.33 | 4042.24; 4042.7000; 4042.70; 0 | 4041.7784; 4044.0824; .9216; 1.3824; 2.88 | 0.2s |
| 7 | 19:12 | CLEAN_LOW_IMPULSE_SELL / SELL | 4041.6133; 3; 3 | strong close; 1.20; .16 | 1/1; 14 | neutral / bearish | .33/.33/.33 | 4041.02; 4040.5575; 4040.56; -0.0025 | 4041.2675; 4039.4925; .7100; 1.0650; 2.15 | 25.4s |
| 8 | 19:14 | CLEAN_LOW_IMPULSE_SELL / SELL | 4038.2000; 4; 1 | strong close; 0.93; .17 | 1/2; 14 | neutral / bearish | .33/.33/.33 | 4037.65; 4037.6500; 4037.65; 0 | 4038.3235; 4036.6398; .6735; 1.0102; 2.04 | 41.8s |
| 9 | 19:15 | CLEAN_HIGH_IMPULSE_BUY / BUY | 4037.7767; 3; 54 | strong close; 0.39; .13 | 1/1; 13 | neutral / bearish | .33/.33/.32 | 4038.42; 4038.8625; 4038.86; -0.0025 | 4038.1525; 4039.9275; .7100; 1.0650; 2.15 | 1.1s |
| 10 | 19:20 | LOW_RESPECT_BUY / BUY | 4038.5100; 3; 42 | rejection; 0.10; .03 | 1/1; 8 | neutral / bearish | .29/.29/.29 | 4039.15; 4039.1125; 4039.11; -0.0025 | 4038.4985; 4040.0335; .6140; .9210; 2.12 | ~0s |
| 11 | 19:21 | HIGH_RESPECT_SELL / SELL | 4039.1083; 6; 1 | rejection; 0.43; .12 | 1/1; 11 | neutral / bearish | .29/.29/.29 | 4038.43; 4038.1675; 4038.17; -0.0025 | 4039.1316; 4036.7213; .9641; 1.4462; 3.32 | 0.1s |
| 12 | 19:22 | CLEAN_LOW_IMPULSE_SELL / SELL | 4037.6667; 6; 3 | strong close; 0.88; .11 | 1/1; 14 | neutral / bearish | .29/.29/.29 | 4037.10; 4037.1000; 4037.10; 0 | 4037.7822; 4036.0768; .6822; 1.0232; 2.35 | 3.9s |
| 13 | 19:26 | HIGH_RESPECT_SELL / SELL | 4036.3400; 2; current/- | rejection; 0.17; .06 | 1/1; 6 | neutral / neutral | .33/.33/.32 | 4035.47; 4035.4175; 4035.42; -0.0025 | 4036.4014; 4033.9416; .9839; 1.4759; 2.98 | 2.8s |
| 14 | 19:35 | HIGH_RESPECT_SELL / SELL | 4039.2075; 4; 14 | rejection; 0.38; 0 | 1/1; 10 | neutral / neutral | .33/.33/.30 | 4038.32; 4038.2775; 4038.28; -0.0025 | 4039.2200; 4036.8638; .9425; 1.4137; 2.86 | 13.3s |
| 15 | 19:41 | FAILED_LOW_BREAK_BUY / BUY | 4035.4433; 3; 15 | rejection; 0.30; 0 | 1/1; 10 | neutral / neutral | .32/.32/.33 | 4036.07; 4036.3100; 4036.31; 0 | 4035.3473; 4037.7541; .9627; 1.4441; 3.01 | 2.3s |
| 16 | 19:44 | FAILED_LOW_BREAK_BUY / BUY | 4035.4360; 5; 1 | rejection; 0.07; .27 | 1/1; 7 | bearish / bearish | .29/.29/.29 | 4035.76; 4035.9725; 4035.97; -0.0025 | 4035.1481; 4037.2091; .8244; 1.2366; 2.84 | 0.6s |
| 17 | 19:48 | CLEAN_LOW_IMPULSE_SELL / SELL | 4035.4360; 5; 5 | strong close; 0.63; 0 | 1/1; 15 | bearish / bearish | .29/.29/.29 | 4034.81; 4034.7075; 4034.71; -0.0025 | 4035.5470; 4033.4483; .8395; 1.2592; 2.89 | 1.0s |
| 18 | 20:40 | CLEAN_LOW_IMPULSE_SELL / SELL | 4041.9600; 3; 8 | strong close; 0.98; .14 | 1/1; 12 | bullish / neutral | .30/.30/.33 | 4041.43; 4041.4300; 4041.43; 0 | 4042.1300; 4040.3800; .7000; 1.0500; 2.33 | 3.0s |
| 19 | 21:27 | CLEAN_LOW_IMPULSE_SELL / SELL | 4051.9300; 2; 2 | strong close; 0.80; .09 | 1/1; 12 | neutral / bearish | .33/.33/.33 | 4051.28; 4051.2800; 4051.28; 0 | 4052.1540; 4049.9690; .8740; 1.3110; 2.65 | 1.3s |
| 20 | 21:28 | CLEAN_HIGH_IMPULSE_BUY / BUY | 4052.4800; 2; 35 | strong close; 0.69; .06 | 1/1; 11 | neutral / bearish | .33/.33/.30 | 4053.22; 4053.4425; 4053.44; -0.0025 | 4052.7325; 4054.5075; .7100; 1.0650; 2.15 | 6.0s |
| 21 | 21:32 | CLEAN_LOW_IMPULSE_SELL / SELL | 4050.9900; 3; 2 | strong close; 1.05; .57 | 1/1; 13 | neutral / neutral | .33/.33/.33 | 4050.26; 4050.2600; 4050.26; 0 | 4051.2215; 4048.8178; .9615; 1.4422; 2.91 | ~0s |
| 22 | 21:43 | CLEAN_HIGH_IMPULSE_BUY / BUY | 4051.3938; 8; 10 | strong close; 0.61; .11 | 1/1; 13 | neutral / neutral | .30/.30/.32 | 4051.77; 4051.9950; 4052.00; .0050 | 4051.1493; 4053.2635; .8457; 1.2685; 2.82 | 1.4s |
| 23 | 21:59 | LOW_RESPECT_BUY / BUY | 4048.8467; 3; 1 | rejection; 0.09; .18 | 1/1; 7 | bearish / neutral | .29/.29/.29 | 4050.16; 4049.8025; 4049.80; -0.0025 | 4048.8200; 4051.2762; .9825; 1.4737; 3.39 | 0.9s |

## Outcome and strict-playbook evaluation

The strict playbook judgment below is made from pre-entry evidence. `TAKE`
means the candidate met the written rules at that time; it does not mean the
trade was certain or even statistically attractive in hindsight. The same
proposed entry, structural stop, target, and `P` management shown above are
the deterministic trader's plan.

| # | MFE / MAE | Management and exit | Hold | P/L | Strict trader | Primary evaluation |
|---:|---|---|---:|---:|---|---|
| 1 | .25 / .77 | emergency adverse exit at -.77 | 71s | -77.0 | TAKE; use listed entry/stop/target/P | FALSE_BREAK_OR_FAKEOUT |
| 3 | 0 / .56 | emergency adverse exit at -.56 | 4s | -56.0 | TAKE | FALSE_BREAK_OR_FAKEOUT |
| 5 | 0 / .49 sampled | original structural stop | 31s | -73.0 | TAKE | SIGNAL_QUALITY; old eight-touch respect against bullish pressure |
| 6 | .73 / 0 | half partial; remaining protected by trailed stop | 2s | +56.0 | TAKE | valid strategy win |
| 7 | .85 / .31 | break-even, second partial/trail, then target | 9s | +93.8 | TAKE | valid strategy win |
| 8 | 0 / .62 | emergency adverse exit at -.62 | 9s | -63.0 | TAKE | LATE_OR_EXTENDED_ENTRY; impulse filled 41.8s after placement |
| 9 | 0 / .48 sampled | original structural stop | 7s | -71.0 | TAKE | DIRECTION_CHANGE_HANDLING; weak immediate reversal while pulse remained bearish |
| 10 | 0 / .42 | emergency adverse exit at -.42 | 6s | -42.0 | TAKE | WEAK_CONFIRMATION; body was 0.10 of recent median range |
| 11 | .88 / .21 | break-even, second partial/trail, scalp exit | 31s | +88.0 | TAKE | valid strategy win |
| 12 | 0 / .67 sampled | original structural stop | 12s | -68.0 | TAKE | VALID_TRADE_NORMAL_LOSS |
| 13 | .79 / .34 | two partials, trail, scalp exit | 28s | +70.2 | TAKE | valid strategy win |
| 14 | 0 / .74 | emergency adverse exit at -.74 | 9s | -74.0 | TAKE | VALID_TRADE_NORMAL_LOSS |
| 15 | .15 / .75 | emergency adverse exit at -.66 | 77s | -66.0 | TAKE | FALSE_BREAK_OR_FAKEOUT |
| 16 | .12 / .76 | emergency close request failed; broker stop completed | 29s | -82.0 | TAKE under literal current reset wording | RAPID_STALE_REENTRY suspected; same failed-low zone retried after three minutes, but a new touch/rejection technically existed |
| 17 | .34 / .04 | break-even stop moved into profit; stop exit | 61s | +9.0 | TAKE | valid win; later M1 reversal supports protection |
| 18 | .66 / .33 | partial raced with broker target; full target already closed | 29s | +105.0 | TAKE | valid strategy win; harmless reconciliation race |
| 19 | 0 / .73 sampled | original structural stop | 4s | -87.0 | TAKE | VALID_TRADE_NORMAL_LOSS |
| 20 | .45 / .12 | break-even stop moved into profit; stop exit | 6s | +12.0 | TAKE | valid win; later bar crossed both original stop and target, so a larger counterfactual win is unknowable |
| 21 | 0 / .63 sampled | original structural stop | 2s | -96.0 | TAKE | DIRECTION_CHANGE_HANDLING; third trade in a rapid sell/buy/sell sequence |
| 22 | 0 / .61 sampled | original structural stop | 3s | -85.0 | TAKE | SIGNAL_QUALITY; eight-touch level did not produce continuation |
| 23 | 0 / .52 sampled | original structural stop | 1s | -98.0 | TAKE | WEAK_CONFIRMATION; tiny rejection against bearish pressure |

### Normal losses versus defects

Trades 12, 14, and 19 are clear examples of valid-strategy normal losses. They
had current closed-candle confirmation, negligible fill drift, legal
structural stops, and no pre-entry fact that deterministically invalidated
them.

Trade 16 exposes a reset-semantics problem but is not proof that every quick
same-zone retry is invalid. The second signal had a new closed rejection and
additional touches, which the current written wording allows as freshness.
The code still needs durable consumed-opening state so this decision is
explicit and testable rather than reconstructed statelessly.

## The two unfilled orders

| # | Signal | Order policy | Cancellation | Later evaluation |
|---:|---|---|---|---|
| 2 | 18:33 LOW_RESPECT_BUY at 4038.3525 | reaction, 20s | cancelled at 20.5s; no rejection | The next full M1 bar stayed below the entry. A later bar crossed both stop and entry, with intrabar order unknowable. Expiration avoided converting a stale reaction into a chase. |
| 4 | 18:54 CLEAN_LOW_IMPULSE_SELL at 4042.5800 | impulse, 45s | cancelled at 46.0s; no rejection | The next recorded bar later traded above the 4043.3383 stop. Broker state proves the entry was not touched while active. Expiration behaved as designed. |

Both orders were valid to place and correct to cancel. Neither should be
counted as a broker rejection or closed trade.

## Missed and duplicate openings

There was no cycle in which an approved candidate was silently ignored. The
summary's 24 approved candidates and 23 orders are explained by the 19:14
cycle, where two SELL candidates were approved and the deterministic best
candidate alone was selected.

Three candidates otherwise passed model scoring and were rejected solely
because the live quote had moved away:

- 20:05 LOW_RESPECT_BUY, score 8
- 20:59 CLEAN_HIGH_IMPULSE_BUY, score 15
- 20:59 LOW_RESPECT_BUY, score 12

The 20:05 and 20:59 respect entries were not revisited at their intended
prices in the following bar. The 20:59 impulse's following M1 bar crossed both
its stop and target, so candle data cannot establish which occurred first.
These are guarded non-entries, not deterministic missed winners.

The clearest same-zone sequence was:

- 19:41 failed-low BUY at level 4035.4433: -66
- 19:44 failed-low BUY at level 4035.4360: -82
- 19:48 clean-low impulse SELL through level 4035.4360: +9

The first two trades lost 148 before the zone resolved down. The second BUY
was a new candle and touch under the literal rules, but the absence of durable
consumed-opening state means the runner could not explicitly distinguish a
new story from a repeated attempt.

## Comparative results

### By trigger

| Trigger | Trades | W-L | Win rate | Net |
|---|---:|---:|---:|---:|
| CLEAN_HIGH_IMPULSE_BUY | 4 | 1-3 | 25.0% | -200.0 |
| CLEAN_LOW_IMPULSE_SELL | 7 | 3-4 | 42.9% | -106.2 |
| FAILED_HIGH_BREAK_SELL | 1 | 0-1 | 0% | -77.0 |
| FAILED_LOW_BREAK_BUY | 2 | 0-2 | 0% | -148.0 |
| HIGH_RESPECT_SELL | 4 | 2-2 | 50.0% | +11.2 |
| LOW_RESPECT_BUY | 3 | 1-2 | 33.3% | -84.0 |

### By family, confirmation, direction, and touches

| Dimension | Group | Trades | W-L | Net |
|---|---|---:|---:|---:|
| Reaction | fakeout | 3 | 0-3 | -225.0 |
| Reaction | impulse | 11 | 4-7 | -306.2 |
| Reaction | respect | 7 | 3-4 | -72.8 |
| Confirmation | rejection | 10 | 3-7 | -297.8 |
| Confirmation | strong close | 11 | 4-7 | -306.2 |
| Direction | BUY | 9 | 2-7 | -432.0 |
| Direction | SELL | 12 | 5-7 | -172.0 |
| Touch count | 2 | 3 | 2-1 | -4.8 |
| Touch count | 3 | 8 | 3-5 | -118.2 |
| Touch count | 4 | 2 | 0-2 | -137.0 |
| Touch count | 5 | 3 | 1-2 | -129.0 |
| Touch count | 6 | 2 | 1-1 | +20.0 |
| Touch count | 8 | 3 | 0-3 | -235.0 |

### Entry economics and candle shape

| Group | Trades | W-L | Net | Interpretation |
|---|---:|---:|---:|---|
| stop/spread under 2.25 | 7 | 2-5 | -199.2 | weak, but not materially worse than other bands |
| stop/spread 2.25-2.75 | 4 | 1-3 | -127.0 | no threshold separation |
| stop/spread 2.75-3.25 | 8 | 3-5 | -267.8 | no threshold separation |
| stop/spread above 3.25 | 2 | 1-1 | -10.0 | too small |
| body/median under .50 | 10 | 3-7 | -295.8 | tiny candles contributed losses, but also included winners |
| body/median .50-.99 | 9 | 3-6 | -306.0 | no separation |
| body/median at least 1.0 | 2 | 1-1 | -2.2 | too small |
| entry distance from level .40-.79 | 11 | 2-9 | -559.0 | materially weak in this sample |
| entry distance from level .80-1.19 | 10 | 5-5 | -45.0 | better, contrary to a simple anti-extension filter |

Candidate score was not monotonic. All three score-11 trades won, but all
three score-13 trades lost, the sole score-6 trade won, and scores 7-10
combined for one win and seven losses. Raising a global score threshold would
fit this sample rather than establish a robust edge.

Pressure and pulse were also not safe global gates. Bullish-pressure trades
netted +32, neutral-pressure trades -465, and bearish-pressure trades -171.
Bearish-pulse trades produced five of seven wins but still netted -154.2.
These remain context features as required by the canonical strategy.

## Excursion and management

| Outcome | Trades | Mean MFE | Mean MAE | Zero sampled MFE |
|---|---:|---:|---:|---:|
| Winners | 7 | .671 | .193 | 0 |
| Losses | 14 | .037 | .625 | 11 |

Observed winning MFE was 4.70 price points, nominally 470 at full 1.0 volume,
against 434 realized gross profit. The apparent 92.3% capture is only a
lower-bound diagnostic because one-second sampling misses some extrema and
partial volumes make a direct full-volume comparison imperfect.

The management evidence supports:

- keeping one-second monitoring
- keeping emergency adverse exits
- keeping break-even and trailing protection
- retaining partial management
- making management races idempotent and explicitly reconciled

It does not support wider stops. Eleven losses had no favorable movement and
would merely have had more room to lose.

### Emergency-exit audit

Six emergency exits realized -378.00. Their original structural risk totaled
about -489.76. Estimated loss avoided was 111.76. The exits helped trades 3,
10, 14, and 15 materially; trades 1 and 8 exited close to their original
stops. No winner was closed by the emergency rule.

One emergency close on trade 16 returned an invalid-request error and the
broker stop then closed the position. One partial request on trade 18 raced
with a target that had already closed the position. Both need explicit
idempotent reconciliation, but neither explains the session's negative edge.

## Trade frequency and direction changes

The 19:12-19:26 cluster contained seven trades in 14 minutes and netted only
+8.0 despite three wins. The 19:41-19:48 same-zone cluster netted -139. The
21:27-21:32 SELL/BUY/SELL sequence netted -171.

Entries within 60 seconds of the preceding close produced one win and two
losses, net -51. Entries within roughly three minutes included both winners
and losses. This supports instrumenting local-zone reuse and direction-change
state, but does not support a global time cooldown. A cooldown would ignore
whether a genuinely new M1 opening formed.

## Findings by confidence

### 1. Confirmed correctness defects

1. Durable consumed-opening/reset state required by the strategy is absent.
2. Decision, send, fill, and exit quote snapshots are not separately
   journaled.
3. MFE/MAE are sampled lower bounds and do not include every fill/exit
   extreme.
4. Selected-level touch indices were not uniquely recoverable for two trades.
5. An emergency close and a partial close produced race-related errors that
   should reconcile as already-closed/stop-completed outcomes.
6. Journal event ordering can make an immediate fill appear slightly earlier
   than the recorded order event.

### 2. Strong repeatable strategy patterns in this session

1. Eleven of 14 losses never moved favorably.
2. Management separated winners from losers quickly and generally reduced
   loss rather than creating it.
3. Local trade clusters consumed substantial risk without establishing
   incremental edge.
4. Score, touch count, pressure, pulse, and stop/spread were not individually
   monotonic predictors.

### 3. Hypotheses requiring more evidence

1. Same-zone retries after a loss may need stricter reset evidence than a
   single new rejection.
2. Fakeout trades may require trigger-specific confirmation strength.
3. An impulse filled near the end of its 45-second window may be stale.
4. Tiny rejection confirmations may be economically weak in some contexts.
5. Eight-touch levels may be exhausted rather than higher priority.
6. Rapid direction changes may require explicit state-change quality, not a
   time cooldown.

### 4. Normal trading variance

1. Valid trades 12, 14, and 19 lost with legal structure and negligible
   execution drift.
2. Winners 6, 7, 11, 13, 17, 18, and 20 demonstrate that respect and impulse
   families can both work.
3. Two orders expired without filling exactly as designed.

### 5. Ideas rejected as overfitting

- ban all BUY trades
- ban fakeouts after only three observations
- ban eight-touch levels after only three observations
- require global pressure or pulse alignment
- raise one global candidate-score floor
- impose a fixed time cooldown
- widen structural stops
- weaken emergency exits
- chase the three quote-drift-rejected candidates
- tune tests to make this one session profitable

## Design implications

The smallest defensible next change is not a broad signal rewrite. It is:

1. implement durable candidate-local consumed-opening/reset state using
   explicit structural evidence rather than elapsed-time cooldowns;
2. make quote, fill, excursion, and management-race telemetry complete enough
   to replay the decision faithfully;
3. record confirmation-strength and zone-reuse features in shadow telemetry
   before turning them into additional entry gates.

Any stricter same-zone reset definition changes strategy behavior and requires
explicit approval before implementation.
