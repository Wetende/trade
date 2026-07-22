from datetime import datetime, timezone

from tradingagents.agents.price_action.one_minute_causal_microburst_v9 import (
    CANDIDATE_NAME,
)
from tradingagents.agents.price_action.one_minute_causal_microburst_v9_screening import (
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
            "pressure_change_count": 8,
            "pressure_window_seconds": 2.0,
            "minimum_nonzero_moves": 4,
            "minimum_directional_pressure": 0.625,
            "minimum_displacement_r": 0.08,
            "maximum_adverse_r": 0.15,
            "maximum_spread_multiple": 1.15,
            "placement_delay_seconds": 2.0,
            "pending_expiry_seconds": 20,
            "minimum_stop_distance": 0.35,
            "minimum_stop_spread_multiple": 1.2,
            "maximum_stop_distance": 1.0,
            "risk_reward": 1.5,
            "tick_size": 0.01,
        },
    }


def _counters():
    return V8EvidenceCounters(
        arms_detected=100,
        valid_triggers=80,
        placements=75,
        fills=70,
    )


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


def test_frozen_v9_strategy_is_exact_and_independently_named():
    strategy = _strategy(_manifest())

    assert strategy.candidate_name == CANDIDATE_NAME
    assert strategy.pressure_change_count == 8
    assert strategy.pressure_window_seconds == 2.0
    assert strategy.placement_delay_seconds == 2.0


def test_all_three_v9_gates_pass_only_complete_metrics():
    metrics = _metrics()
    counters = _counters()

    assert _gate_reasons("DISCOVERY", metrics, counters) == []
    assert _gate_reasons("HELD_OUT", metrics, counters) == []
    assert _gate_reasons("PROSPECTIVE", metrics, counters) == []


def test_discovery_retires_sparse_one_sided_or_operationally_failed_result():
    metrics = _metrics()
    metrics.update(
        {
            "fills": 4,
            "direction_net_r": {"BUY": 1.0, "SELL": -1.0},
            "valid_trigger_placement_fill_rate": 0.2,
        }
    )
    counters = V8EvidenceCounters(
        arms_detected=100,
        valid_triggers=20,
        placements=10,
        fills=4,
        safety_failures=1,
    )

    reasons = _gate_reasons("DISCOVERY", metrics, counters)

    assert "fills_below_30" in reasons
    assert "sell_net_not_positive" in reasons
    assert "valid_trigger_placement_fill_rate_below_0.85" in reasons
    assert "safety_failures_nonzero" in reasons


def test_strategy_rejects_post_freeze_threshold_change():
    changed = _manifest()
    changed["strategy"]["minimum_directional_pressure"] = 0.60

    try:
        _strategy(changed)
    except ValueError as exc:
        assert "minimum_directional_pressure" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("changed frozen threshold was accepted")
