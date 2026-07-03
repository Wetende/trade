"""Pure metrics and qualification gates for historical scalper evidence."""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.price_action.evidence_gate import ScreeningRow


class VariantMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    fills: int
    wins: int
    losses: int
    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    no_gross_loss: bool
    expectancy: float
    fill_retention: float = Field(ge=0)
    max_loss_streak: int
    max_session_drawdown: float
    profitable_session_count: int


class HistoricalGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    reasons: tuple[str, ...]


def _maximum_drawdown(profits: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 2)


def summarize_variant(
    name: str,
    rows: tuple[ScreeningRow, ...],
    *,
    baseline_fill_count: int,
) -> VariantMetrics:
    filled = [
        row
        for row in rows
        if row.accepted and row.filled and row.profit is not None
    ]
    profits = [float(row.profit) for row in filled]
    wins = [profit for profit in profits if profit > 0]
    losses = [profit for profit in profits if profit < 0]
    gross_profit = round(sum(wins), 2)
    gross_loss = round(sum(losses), 2)
    no_gross_loss = not losses
    profit_factor = (
        None
        if no_gross_loss
        else round(gross_profit / abs(gross_loss), 4)
    )
    streak = maximum_streak = 0
    for profit in profits:
        streak = streak + 1 if profit < 0 else 0
        maximum_streak = max(maximum_streak, streak)
    by_session: dict[str, list[float]] = defaultdict(list)
    for row in filled:
        by_session[row.session_id].append(float(row.profit))

    return VariantMetrics(
        name=name,
        fills=len(filled),
        wins=len(wins),
        losses=len(losses),
        net_profit=round(sum(profits), 2),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        no_gross_loss=no_gross_loss,
        expectancy=round(sum(profits) / len(filled), 4) if filled else 0.0,
        fill_retention=(
            round(len(filled) / baseline_fill_count, 4)
            if baseline_fill_count
            else 0.0
        ),
        max_loss_streak=maximum_streak,
        max_session_drawdown=max(
            (_maximum_drawdown(values) for values in by_session.values()),
            default=0.0,
        ),
        profitable_session_count=sum(
            sum(values) > 0 for values in by_session.values()
        ),
    )


def evaluate_historical_gate(
    candidate: VariantMetrics,
    baseline: VariantMetrics,
) -> HistoricalGateResult:
    reasons: list[str] = []
    if candidate.expectancy <= 0:
        reasons.append("NON_POSITIVE_EXPECTANCY")
    profit_factor_passes = (
        candidate.no_gross_loss
        and candidate.net_profit > 0
        and candidate.expectancy > 0
    ) or (
        candidate.profit_factor is not None
        and candidate.profit_factor >= 1.15
    )
    if not profit_factor_passes:
        reasons.append("PROFIT_FACTOR_BELOW_1_15")
    if candidate.profitable_session_count < 2:
        reasons.append("FEWER_THAN_TWO_PROFITABLE_SESSIONS")
    if candidate.fill_retention < 0.60:
        reasons.append("FILL_RETENTION_BELOW_0_60")
    if candidate.max_loss_streak > baseline.max_loss_streak:
        reasons.append("MAX_LOSS_STREAK_WORSE_THAN_BASELINE")
    if candidate.max_session_drawdown > baseline.max_session_drawdown:
        reasons.append("MAX_SESSION_DRAWDOWN_WORSE_THAN_BASELINE")
    return HistoricalGateResult(passed=not reasons, reasons=tuple(reasons))
