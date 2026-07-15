from dataclasses import replace

from tradingagents.agents.price_action.one_minute_post_close_evaluation import (
    evaluate_post_close_result,
    summarize_post_close_rows,
)
from tradingagents.agents.price_action.one_minute_post_close_replay import (
    PostCloseReplayResult,
    PostCloseReplayRow,
)


def _row(index: int, profit_r: float, *, family="HIGH_BREAK_BUY", direction="BUY"):
    return PostCloseReplayRow(
        arm_id=f"arm-{index}",
        session_id=f"2026-07-{index % 10 + 1:02d}",
        family=family,
        direction=direction,
        touch_count=2 + index % 3,
        confirmation_type="strong_close",
        armed_at="2026-07-01T00:00:00+00:00",
        triggered_at="2026-07-01T00:00:06+00:00",
        retest_at=None,
        placed_at="2026-07-01T00:00:11+00:00",
        filled_at="2026-07-01T00:00:11+00:00",
        closed_at="2026-07-01T00:00:20+00:00",
        accepted=True,
        filled=True,
        outcome="WIN" if profit_r > 0 else "LOSS",
        reason="TARGET_EXIT" if profit_r > 0 else "STOP_EXIT",
        profit_r=profit_r,
        mfe_r=max(0.0, profit_r),
        mae_r=min(0.0, profit_r),
        spread_r=0.1,
        entry_drift_r=0.1,
        trigger_delay_seconds=6.0,
        placement_delay_seconds=5.0,
    )


def test_summary_reports_r_economics_drawdown_and_cost_stress():
    rows = [_row(0, 1.0), _row(1, -0.5), _row(2, 1.0), _row(3, -0.5)]

    metrics = summarize_post_close_rows(rows)

    assert metrics["fills"] == 4
    assert metrics["net_r"] == 1.0
    assert metrics["profit_factor"] == 2.0
    assert metrics["expectancy_r"] == 0.25
    assert metrics["max_loss_streak"] == 1
    assert metrics["max_portfolio_drawdown_r"] == 0.5
    assert metrics["net_with_extra_0_05r_cost"] == 0.8


def test_discovery_never_authorizes_candidate_even_when_metrics_are_positive():
    rows = tuple(
        _row(
            index,
            0.3 if index % 4 else -0.2,
            family="HIGH_BREAK_BUY" if index % 2 else "LOW_BREAK_SELL",
            direction="BUY" if index % 2 else "SELL",
        )
        for index in range(120)
    )
    result = PostCloseReplayResult(rows=rows, events=(), arms_detected=120)

    report = evaluate_post_close_result(result, stage="DISCOVERY")

    assert report["decision"] == "DISCOVERY_ONLY_NOT_APPROVAL"
    assert report["evaluable"] is False
    assert report["broker_mutation_enabled"] is False


def test_held_out_gate_rejects_weak_or_concentrated_result():
    rows = tuple(_row(index, 0.01 if index % 2 else -0.01) for index in range(100))
    result = PostCloseReplayResult(rows=rows, events=(), arms_detected=100)

    report = evaluate_post_close_result(result, stage="HELD_OUT")

    assert report["decision"] == "FAIL"
    assert "EXPECTANCY_BELOW_GATE" in report["gate_reasons"]
    assert "FAMILY_PROFIT_CONCENTRATION" in report["gate_reasons"]


def test_non_filled_rows_affect_executability_but_not_profit_metrics():
    filled = _row(0, 0.5)
    expired = replace(
        _row(1, -0.5),
        filled=False,
        profit_r=None,
        triggered_at=None,
        placed_at=None,
        outcome="EXPIRED",
        reason="ARM_EXPIRED",
    )
    result = PostCloseReplayResult(rows=(filled, expired), events=(), arms_detected=2)

    report = evaluate_post_close_result(result, stage="DISCOVERY")

    assert report["metrics"]["fills"] == 1
    assert report["metrics"]["net_r"] == 0.5
    assert report["executability"]["expiry_rate"] == 0.5


def test_v3_discovery_stop_requires_both_directions_and_two_families():
    rows = tuple(
        replace(
            _row(
                index,
                0.4 if index % 4 else -0.2,
                family="HIGH_RESPECT_SELL" if index % 2 else "LOW_RESPECT_BUY",
                direction="SELL" if index % 2 else "BUY",
            ),
            retest_at="2026-07-01T00:00:08+00:00",
        )
        for index in range(40)
    )
    result = PostCloseReplayResult(rows=rows, events=(), arms_detected=40)

    report = evaluate_post_close_result(
        result,
        stage="DISCOVERY",
        candidate="ONE_MINUTE_RETEST_RECONFIRMATION_V3",
    )

    assert report["decision"] == "DISCOVERY_ONLY_NOT_APPROVAL"
    assert report["discovery_stop"]["passed"] is True
    assert report["discovery_stop"]["positive_directions"] == 2
    assert report["discovery_stop"]["positive_families"] == 2


def test_v6_discovery_requires_two_positive_preregistered_folds():
    rows = tuple(
        _row(
            index,
            -0.2 if index % 4 == 0 else 0.3,
            family=(
                "FAILED_HIGH_BREAK_SELL"
                if index % 2 == 0
                else "FAILED_LOW_BREAK_BUY"
            ),
            direction="SELL" if index % 2 == 0 else "BUY",
        )
        for index in range(40)
    )
    result = PostCloseReplayResult(rows=rows, events=(), arms_detected=40)

    passed = evaluate_post_close_result(
        result,
        stage="DISCOVERY",
        candidate="ONE_MINUTE_SHOCK_RECLAIM_V6",
        fold_metrics=({"net_r": 1.0}, {"net_r": -0.5}, {"net_r": 0.2}),
    )
    missing = evaluate_post_close_result(
        result,
        stage="DISCOVERY",
        candidate="ONE_MINUTE_SHOCK_RECLAIM_V6",
    )

    assert passed["discovery_stop"]["passed"] is True
    assert passed["discovery_stop"]["positive_folds"] == 2
    assert "DISCOVERY_REQUIRES_THREE_FOLDS" in missing["discovery_stop"]["reasons"]
    assert "DISCOVERY_FEWER_THAN_TWO_POSITIVE_FOLDS" in missing["discovery_stop"]["reasons"]
