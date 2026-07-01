# One-Minute Active Management Design

## Goal

Reduce full-stop losses and capture brief favorable moves without changing the
One Minute Scalper's two-high/two-low entry playbook.

## One-Second Position Management

The runner already wakes every second while an order or position is active, but
the maintenance path only cancels pending orders. It must also call
`manage_open_positions()` so partial closes, break-even moves, candle exits, and
emergency protection evaluate every second. Full market analysis remains on its
configured five-second cadence.

## Spread-Aware Protection

One-minute proposal thresholds use both initial risk and the live spread:

```text
break-even trigger = max(spread * 1.10, risk * 0.45)
first partial       = max(spread * 1.30, risk * 0.60)
second partial      = max(first partial + 0.10, risk * 1.00)
scalp exit          = max(first partial, spread * 1.80, risk * 0.90)
```

Existing upper bounds remain in place. The intent is to protect a genuine net
move after spread without requiring most of the original stop distance.

## Confirmed Intrabar Emergency Exit

For `FAST_PARTIAL_SCALE` positions only, track consecutive adverse observations.
When price is at least 65% of the original stop distance adverse for two
consecutive one-second checks, close the position.

The original proposal entry and stop define the threshold even if the broker
stop later moves. A single adverse observation resets if price recovers, so one
transient tick cannot force an exit.

## Excursion Telemetry

For every active position, persist and return:

- current favorable/adverse movement;
- maximum favorable excursion (MFE);
- maximum adverse excursion (MAE);
- current spread;
- effective break-even, partial, scalp, and emergency thresholds;
- consecutive emergency-exit observations.

This state is stored in the existing account- and ticket-bound durable execution
state and removed when the trade closes.

## Entry Scope

Do not add the proposed impulse-exhaustion or fakeout-delay filters yet. The
available sample contains one winning impulse that was more extended than the
losing impulse, so those filters would be unproven overfitting. Fresh re-entry
remains available whenever the existing playbook detects a new valid opening.

## Verification

Tests must prove:

- active maintenance manages positions every second;
- inactive cycles retain the normal analysis cadence;
- dynamic thresholds incorporate spread;
- one adverse observation does not close a position;
- two consecutive threshold breaches close it;
- recovery resets the confirmation count;
- monitoring returns and persists MFE/MAE and thresholds;
- normal profile positions do not use the M1 emergency exit;
- the complete suite passes.
