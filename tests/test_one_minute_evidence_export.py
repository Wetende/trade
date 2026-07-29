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
                    "confirmation_type": "strong_close",
                    "score": 12.0,
                    "level_type": "three_touch",
                    "touch_count": 3,
                    "pressure": {"direction": "bullish"},
                    "active_pulse": {"direction": "bearish"},
                    "signal_quality": {
                        "body_to_recent_median_range": 0.75,
                        "touch_age_closed_bars": 2,
                        "entry_distance_from_level": 1.1,
                        "opposing_wick_to_range": 0.1,
                        "stop_to_spread_ratio": 2.5,
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
    decision = exported.decisions[0]
    assert decision.confirmation_type == "strong_close"
    assert decision.score == 12.0
    assert decision.pressure_relation == "aligned"
    assert decision.pulse_relation == "opposed"
    assert decision.utc_hour == 20
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


def test_export_session_maps_closed_candle_families_to_evidence_taxonomy(
    tmp_path,
):
    cases = (
        ("HIGH_RESPECT_SELL", "respect"),
        ("LOW_RESPECT_BUY", "respect"),
        ("HIGH_BREAK_BUY", "impulse_break"),
        ("LOW_BREAK_SELL", "impulse_break"),
        ("FAILED_HIGH_BREAK_SELL", "fakeout"),
        ("FAILED_LOW_BREAK_BUY", "fakeout"),
    )
    for index, (trigger, expected) in enumerate(cases):
        session_root = tmp_path / f"closed-candle-{index}"
        _write_session(session_root)
        cycles_path = session_root / "mt5_runner" / "cycles.jsonl"
        cycle = json.loads(cycles_path.read_text(encoding="utf-8"))
        cycle["proposal"]["trigger_name"] = trigger
        cycle["proposal"]["reaction_type"] = "closed_candle_reconfirmation"
        selected = cycle["analysis"]["telemetry"]["selected_candidate"]
        selected["trigger"] = trigger
        selected["reaction_type"] = "closed_candle_reconfirmation"
        cycles_path.write_text(json.dumps(cycle) + "\n", encoding="utf-8")

        exported = export_session(session_root)

        assert exported.decisions[0].reaction_type == expected


def test_export_session_excludes_closed_trade_without_session_placement(tmp_path):
    session_root = tmp_path / "session-c"
    _write_session(session_root)
    summary_path = session_root / "mt5_runner" / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["trade_history"]["closed_trades"].append(
        {
            "entry_order": 123456,
            "opened_at_utc": "2026-07-02T19:00:00+00:00",
            "closed_at_utc": "2026-07-02T19:00:30+00:00",
            "profit": -12.0,
            "mfe_points": 0.0,
            "mae_points": -0.5,
        }
    )
    summary_path.write_text(json.dumps(summary))

    exported = export_session(session_root)

    assert len(exported.decisions) == 1
    assert len(exported.trades) == 1
    assert exported.trades[0].profit == 50.0
    assert exported.unmatched_closed_trade_count == 1
