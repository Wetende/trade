from tradingagents.agents.price_action.evidence_metrics import (
    HistoricalGateResult,
    VariantMetrics,
)
from tradingagents.agents.price_action import opening_state_target_grid
from tradingagents.agents.price_action.opening_state_target_grid import (
    TARGET_GRID,
    TARGET_GRID_CANDIDATE_NAME,
    rank_training_targets,
    screen_target_grid_fixture,
)


FIXTURE = "tests/fixtures/one_minute/opening_state/sample-openings.json"


def _metrics(name, *, profit_factor, expectancy, fills):
    return VariantMetrics(
        name=name,
        fills=fills,
        wins=fills,
        losses=0,
        net_profit=round(expectancy * fills, 2),
        gross_profit=round(expectancy * fills, 2),
        gross_loss=0.0,
        profit_factor=profit_factor,
        no_gross_loss=profit_factor is None,
        expectancy=expectancy,
        fill_retention=0.8,
        max_loss_streak=0,
        max_session_drawdown=0.0,
        profitable_session_count=2,
    )


def test_target_grid_is_fixed():
    assert TARGET_GRID == (0.60, 0.75, 0.90, 1.00)


def test_rank_training_targets_prefers_pf_expectancy_fills_then_target():
    ranked = rank_training_targets(
        (
            {
                "target": 0.60,
                "metrics": _metrics("a", profit_factor=2.0, expectancy=0.20, fills=20),
                "gate": {"passed": True, "reasons": ()},
            },
            {
                "target": 0.75,
                "metrics": _metrics("b", profit_factor=3.0, expectancy=0.10, fills=30),
                "gate": {"passed": True, "reasons": ()},
            },
            {
                "target": 1.00,
                "metrics": _metrics("c", profit_factor=3.0, expectancy=0.10, fills=40),
                "gate": {"passed": True, "reasons": ()},
            },
            {
                "target": 0.90,
                "metrics": _metrics("d", profit_factor=9.0, expectancy=1.00, fills=99),
                "gate": {"passed": False, "reasons": ("FAIL",)},
            },
        )
    )

    assert [item["target"] for item in ranked] == [1.00, 0.75, 0.60]


def test_rank_training_targets_returns_empty_when_no_target_passes():
    ranked = rank_training_targets(
        (
            {
                "target": 0.60,
                "metrics": _metrics("a", profit_factor=2.0, expectancy=0.20, fills=20),
                "gate": {"passed": False, "reasons": ("FILL_RETENTION_BELOW_0_60",)},
            },
        )
    )

    assert ranked == ()


def test_target_grid_screen_reports_no_edge_for_sample_fixture():
    report = screen_target_grid_fixture(FIXTURE)

    assert report["candidate"] == TARGET_GRID_CANDIDATE_NAME
    assert report["broker_mutation_enabled"] is False
    assert report["target_grid"] == [0.60, 0.75, 0.90, 1.00]
    assert report["decision"] == "NO_OPENING_STATE_QUEUE_TARGET_GRID_EDGE"
    assert report["frozen_manifest"] is None
    assert len(report["folds"]) >= 1


def test_target_grid_screen_freezes_manifest_when_gate_passes(monkeypatch):
    monkeypatch.setattr(
        opening_state_target_grid,
        "evaluate_historical_gate",
        lambda _metrics, _baseline: HistoricalGateResult(passed=True, reasons=()),
    )

    report = screen_target_grid_fixture(FIXTURE)

    assert report["decision"] == "FREEZE_OPENING_STATE_QUEUE_TARGET_GRID"
    assert report["frozen_manifest"]["candidate"] == TARGET_GRID_CANDIDATE_NAME
    assert report["frozen_manifest"]["target_grid"] == [0.60, 0.75, 0.90, 1.00]
