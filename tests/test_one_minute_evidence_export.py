import json
from pathlib import Path

from tradingagents.agents.price_action.evidence_export import export_session
from tradingagents.agents.price_action.evidence_gate import EvidenceSession


def _write_session(root: Path):
    runner = root / "mt5_runner"
    runner.mkdir(parents=True)
    cycle = {
        "status": "ORDER_PLACED",
        "heartbeat_utc": "2026-07-02T20:00:00+00:00",
        "execution": {
            "order": 987654,
            "status": "PLACED",
            "execution_timeline": {
                "submitted_at_utc": "2026-07-02T20:00:00.409367+00:00"
            },
        },
        "proposal": {
            "trigger_name": "CLEAN_HIGH_IMPULSE_BUY",
            "side": "BUY",
            "reaction_type": "impulse_break",
            "touch_count": 3,
            "decision_quote": {"spread_price": 0.33},
        },
        "analysis": {
            "telemetry": {
                "selected_candidate": {
                    "approved": True,
                    "trigger": "CLEAN_HIGH_IMPULSE_BUY",
                    "direction": "BUY",
                    "reaction_type": "impulse_break",
                    "touch_count": 3,
                    "signal_quality": {
                        "body_to_recent_median_range": 0.75
                    },
                }
            }
        },
    }
    (runner / "cycles.jsonl").write_text(json.dumps(cycle) + "\n")
    summary = {
        "trade_history": {
            "closed_trades": [
                {
                    "entry_order": 987654,
                    "position_id": 123456,
                    "entry_deal_ticket": 444,
                    "opened_at_utc": "2026-07-02T20:00:00+00:00",
                    "closed_at_utc": "2026-07-02T20:00:30+00:00",
                    "profit": 50.0,
                    "mfe_points": 0.8,
                    "mae_points": -0.2,
                }
            ]
        }
    }
    (runner / "summary.json").write_text(json.dumps(summary))


def test_export_session_is_strict_and_contains_no_broker_identifiers(tmp_path):
    session_root = tmp_path / "session-a"
    _write_session(session_root)

    exported = export_session(session_root)
    payload = exported.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True).lower()

    assert EvidenceSession.model_validate(payload) == exported
    assert len(exported.decisions) == 1
    assert exported.trades[0].profit == 50.0
    assert exported.trades[0].filled_at == exported.trades[0].placed_at
    for forbidden in (
        "account",
        "login",
        "password",
        "server",
        "terminal",
        "ticket",
        "order",
        "deal",
        "position_id",
    ):
        assert forbidden not in encoded


def test_export_session_preserves_unfilled_order_without_fake_outcome(tmp_path):
    session_root = tmp_path / "session-b"
    _write_session(session_root)
    summary_path = session_root / "mt5_runner" / "summary.json"
    summary_path.write_text(json.dumps({"trade_history": {"closed_trades": []}}))

    exported = export_session(session_root)

    assert exported.trades[0].filled is False
    assert exported.trades[0].profit is None
