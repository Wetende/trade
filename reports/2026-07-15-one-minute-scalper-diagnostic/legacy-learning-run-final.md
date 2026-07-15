# Legacy M1 learning run — final audit

The unchanged legacy order-capable learning run stopped early at 2026-07-15 17:59:41 UTC after MT5 returned `Terminal: Authorization failed`. It was not restarted. A fresh read-only broker probe at 18:03:44 UTC proved that the connected account was still DEMO and had zero open orders and zero open positions.

The run recorded 4 placed and filled orders, all closed: 2 wins, 2 losses, no break-even trades, and net account-currency P/L of -76.80. Gross profit was 68.20, gross loss was 145.00, profit factor was 0.4703, and expectancy was -19.20 per closed trade. One additional broker submission was rejected with MT5 retcode 10015 (`Invalid price`). The earlier invalid-expiration response was recovered through the legacy fallback and is counted as the known expiration-capability defect, not as a lost trade.

The terminal state is flat. No cancellation or forced close was necessary because the fresh broker snapshot returned zero pending orders and zero positions. The complete session remains at `C:/Users/Administrator/Desktop/trade/results/2026-07-15-112146-one-minute-scalper-evidence`; SHA-256 hashes for the final summary, heartbeat, cycle log, stdout, and stderr are recorded in `legacy-learning-run-final.json`.

This is the final order-capable use of the unchanged legacy M1 engine. The V8 startup lock prevents another legacy M1 order-capable restart.
