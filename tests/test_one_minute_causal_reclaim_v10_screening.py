from tradingagents.agents.price_action.one_minute_causal_reclaim_v10 import (
    CANDIDATE_NAME,
)
from tradingagents.agents.price_action.one_minute_causal_reclaim_v10_screening import (
    _gate_reasons,
    _strategy,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_evidence import (
    V8EvidenceCounters,
)


def _manifest():
    return {
        "candidate": CANDIDATE_NAME,
        "strategy": {
            "history_candles": 60,
            "pressure_change_count": 20,
            "pressure_window_seconds": 3.0,
            "minimum_nonzero_moves": 10,
            "minimum_directional_pressure": 0.60,
            "minimum_displacement_r": 0.10,
            "maximum_adverse_r": 0.15,
            "maximum_spread_multiple": 1.10,
            "placement_delay_seconds": 5.0,
            "pending_expiry_seconds": 20,
            "minimum_stop_distance": 0.35,
            "minimum_stop_spread_multiple": 1.2,
            "maximum_stop_distance": 1.0,
            "risk_reward": 1.5,
            "tick_size": 0.01,
        },
    }


def _metrics():
    return {
        "fills": 70,
        "sessions": 12,
        "net_r": 10.0,
        "profit_factor": 1.5,
        "expectancy_r": 0.14,
        "direction_net_r": {"BUY": 4.0, "SELL": 6.0},
        "profitable_sessions": 8,
        "profitable_folds": 3,
        "maximum_loss_streak": 4,
        "portfolio_drawdown_r": 4.0,
        "maximum_session_drawdown_r": 2.0,
        "trigger_rate": 0.8,
        "valid_trigger_placement_fill_rate": 0.875,
        "crossed_rate": 0.05,
        "geometry_rejection_rate": 0.025,
        "net_without_best_session_r": 5.0,
        "net_with_extra_0_05r_cost_r": 6.5,
        "profitable_session_rate": 2 / 3,
    }


def test_v10_uses_original_strict_quote_pressure_playbook():
    strategy = _strategy(_manifest())
    assert strategy.candidate_name == CANDIDATE_NAME
    assert strategy.pressure_change_count == 20
    assert strategy.pressure_window_seconds == 3.0
    assert strategy.minimum_nonzero_moves == 10
    assert strategy.placement_delay_seconds == 5.0
    assert strategy.maximum_stop_distance == 1.0


def test_v10_uses_unchanged_economic_and_safety_gates():
    counters = V8EvidenceCounters(
        arms_detected=100,
        valid_triggers=80,
        placements=75,
        fills=70,
    )
    assert _gate_reasons("DISCOVERY", _metrics(), counters) == []
    assert _gate_reasons("HELD_OUT", _metrics(), counters) == []
    assert _gate_reasons("PROSPECTIVE", _metrics(), counters) == []


def test_v10_rejects_any_post_freeze_pressure_change():
    changed = _manifest()
    changed["strategy"]["pressure_change_count"] = 19
    try:
        _strategy(changed)
    except ValueError as exc:
        assert "pressure_change_count" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("changed frozen V10 threshold was accepted")
