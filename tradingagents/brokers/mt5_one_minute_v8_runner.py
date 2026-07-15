"""Promoted DEMO-only live runner for One Minute Quote Pressure V8."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_post_close_state import (
    QuoteObservation,
    parse_utc,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    AtomicV8StateStore,
    CANDIDATE_NAME,
    TERMINAL_PHASES,
    V8Config,
    V8Phase,
    V8State,
    detect_v8_arms,
    evaluate_v8_stop_order,
    mark_v8_placed,
    observe_v8_quote,
    start_v8_state,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    V8PromotionValidation,
    validate_v8_promotion,
)
from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mode_gate import account_safety_from_connection
from tradingagents.brokers.mt5_one_minute_v8_risk import (
    V8RiskBudget,
    calculate_reserved_exposure_currency,
    calculate_v8_unit_risk_currency,
    evaluate_v8_risk_budget,
)


@dataclass(frozen=True)
class MT5OneMinuteV8RunnerConfig:
    results_dir: str | Path
    candidate_manifest: str | Path
    promotion_record: str | Path
    repo_root: str | Path
    volume: float
    max_runtime_seconds: int = 0
    max_session_r: float = 2.0
    shutdown_grace_seconds: int = 120
    quote_poll_seconds: float = 0.05
    idle_poll_seconds: float = 0.5
    flat_verification_count: int = 3
    loss_pause_seconds: int = 900

    def __post_init__(self) -> None:
        for name in ("volume", "max_session_r", "quote_poll_seconds", "idle_poll_seconds"):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be numeric") from exc
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
            object.__setattr__(self, name, value)
        if self.max_session_r > 2.0:
            raise ValueError("max_session_r cannot exceed the frozen 2R limit")
        if self.volume not in {0.01, 1.0}:
            raise ValueError("V8 volume must be exactly 0.01 or 1.0")
        for name in (
            "max_runtime_seconds",
            "shutdown_grace_seconds",
            "flat_verification_count",
            "loss_pause_seconds",
        ):
            value = int(getattr(self, name))
            if value < 0 or (name != "max_runtime_seconds" and value <= 0):
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "results_dir", Path(self.results_dir))
        object.__setattr__(self, "candidate_manifest", Path(self.candidate_manifest))
        object.__setattr__(self, "promotion_record", Path(self.promotion_record))
        object.__setattr__(self, "repo_root", Path(self.repo_root))


class MT5OneMinuteV8Runner:
    """Run exactly one durable V8 lifecycle on a promoted DEMO account."""

    STATE_SCHEMA_VERSION = 1

    def __init__(
        self,
        config: MT5OneMinuteV8RunnerConfig,
        *,
        executor: Any,
        promotion_validation: V8PromotionValidation | None = None,
        now_func: Callable[[], datetime] | None = None,
        sleep_func: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self.executor = executor
        self.broker = executor.broker
        self.now_func = now_func or (lambda: datetime.now(timezone.utc))
        self.sleep_func = sleep_func or time.sleep
        self.runner_dir = Path(config.results_dir) / "mt5_one_minute_v8"
        self.runner_dir.mkdir(parents=True, exist_ok=True)
        self.state_store = AtomicV8StateStore(self.runner_dir / "state.json")
        self.heartbeat_store = AtomicV8StateStore(self.runner_dir / "heartbeat.json")
        self.receipt_store = AtomicV8StateStore(self.runner_dir / "promotion_receipt.json")
        self.events_path = self.runner_dir / "events.jsonl"
        self.validation = promotion_validation or validate_v8_promotion(
            config.candidate_manifest,
            config.promotion_record,
            requested_volume=config.volume,
            repo_root=config.repo_root,
        )
        self.runtime: dict[str, Any] | None = None

    def initialize(self) -> dict[str, Any]:
        if self.runtime is not None:
            return self.runtime
        connection = self._connect_demo()
        existing = self.state_store.load()
        if existing is not None:
            self._validate_recovered_runtime(existing)
            self.runtime = existing
            self._event("RUNNER_RECOVERED", phase=existing.get("phase"))
            return existing

        orders = self.broker.open_orders(self.executor.config.symbol)
        positions = self.broker.open_positions(self.executor.config.symbol)
        if orders or positions:
            raise ValueError(
                "V8 requires zero initial exposure; existing MT5 orders or positions found"
            )
        symbol = connection.get("symbol") or {}
        if symbol.get("supports_stop_orders") is not True:
            raise ValueError("MT5 symbol does not prove pending-stop capability")
        snapshot = self.broker.current_symbol_snapshot()
        quote = self._quote_from_snapshot(snapshot)
        unit_risk = calculate_v8_unit_risk_currency(
            self.broker,
            volume=self.config.volume,
            bid=quote.bid,
            ask=quote.ask,
            maximum_stop_distance=1.0,
        )
        now = self._now()
        deadline = (
            now + timedelta(seconds=self.config.max_runtime_seconds)
            if self.config.max_runtime_seconds
            else None
        )
        self.runtime = {
            "schema_version": self.STATE_SCHEMA_VERSION,
            "candidate": CANDIDATE_NAME,
            "phase": "RUNNING",
            "started_at_utc": now.isoformat(),
            "runtime_deadline_utc": deadline.isoformat() if deadline else None,
            "drain_started_at_utc": None,
            "drain_deadline_utc": None,
            "flat_verification_count": 0,
            "promotion_sha256": self.validation.promotion_sha256,
            "manifest_sha256": self.validation.manifest_sha256,
            "approved_volume_cap": self.validation.approved_volume_cap,
            "volume": self.config.volume,
            "max_session_r": self.config.max_session_r,
            "unit_risk_currency": unit_risk,
            "budget_currency": unit_risk * self.config.max_session_r,
            "last_closed_candle": None,
            "consumed_arm_ids": [],
            "lifecycle": None,
            "last_closed_trade_ids": [],
            "consecutive_losses": 0,
            "cooldown_until_utc": None,
            "structural_reset_after_utc": None,
            "last_history": {},
            "safety_failures": 0,
            "telemetry_failures": 0,
            "reconciliation_failures": 0,
            "entry_drift_failures": 0,
            "lifecycle_failures": 0,
            "restart_failures": 0,
            "submissions": {},
            "evidence_rows": [],
        }
        self._save_runtime()
        self.receipt_store.save(
            {
                **self.validation.as_dict(),
                "account_safety": account_safety_from_connection(
                    connection, require_demo=True
                ),
                "zero_initial_orders": True,
                "zero_initial_positions": True,
                "symbol_capabilities": {
                    key: symbol.get(key)
                    for key in (
                        "expiration_mode",
                        "order_mode",
                        "filling_mode",
                        "trade_exemode",
                        "supports_order_time_specified",
                        "supports_stop_orders",
                        "trade_stops_level",
                        "trade_freeze_level",
                        "trade_stops_distance_price",
                        "trade_freeze_distance_price",
                        "pending_filling_mode",
                    )
                },
                "unit_risk_currency": unit_risk,
                "budget_currency": unit_risk * self.config.max_session_r,
                "started_at_utc": now.isoformat(),
            }
        )
        self._event("RUNNER_INITIALIZED", deadline_utc=self.runtime["runtime_deadline_utc"])
        return self.runtime

    def run_once(self) -> dict[str, Any]:
        runtime = self.initialize()
        if runtime["phase"] == "COMPLETE":
            return self._heartbeat(
                "DRAINED_FLAT",
                flat_verification_count=runtime["flat_verification_count"],
            )
        now = self._now()
        deadline = _optional_datetime(runtime.get("runtime_deadline_utc"))
        if runtime["phase"] == "RUNNING" and deadline is not None and now >= deadline:
            self._enter_draining(now)
        if runtime["phase"] == "DRAINING":
            return self._drain_once(now)

        connection = self._connect_demo()
        snapshot = self.broker.current_symbol_snapshot()
        quote = self._quote_from_snapshot(snapshot)
        orders = self.broker.open_orders(self.executor.config.symbol)
        positions = self.broker.open_positions(self.executor.config.symbol)
        lifecycle = self._lifecycle_state()
        if lifecycle is not None and lifecycle.phase == V8Phase.PLACED:
            return self._maintain_external(lifecycle, orders, positions, quote, now)
        if orders or positions:
            runtime["safety_failures"] += 1
            self._save_runtime()
            return self._heartbeat(
                "UNTRACKED_EXPOSURE_BLOCK",
                orders=orders,
                positions=positions,
                account_safety=account_safety_from_connection(
                    connection, require_demo=True
                ),
            )
        if lifecycle is None:
            arm_result = self._maybe_arm(quote, snapshot, now)
            if arm_result is not None:
                return arm_result
            lifecycle = self._lifecycle_state()
            if lifecycle is None:
                return self._heartbeat(
                    "NO_ARM",
                    account_safety=account_safety_from_connection(
                        connection, require_demo=True
                    ),
                )

        transition = observe_v8_quote(
            lifecycle,
            quote,
            config=self._strategy_config(snapshot),
        )
        self._set_lifecycle(transition.state, transition=transition.as_dict())
        self._event(
            "STATE_TRANSITION",
            transition_event=transition.event,
            arm_id=transition.state.arm.arm_id,
            sequence=transition.state.sequence,
            phase=transition.state.phase.value,
        )
        if transition.state.phase in TERMINAL_PHASES:
            reason = transition.state.terminal_reason or transition.event
            self._consume_lifecycle(reason)
            return self._heartbeat("LIFECYCLE_TERMINAL", reason=reason)
        if transition.event != "PLACEMENT_READY":
            return self._heartbeat(
                transition.event,
                lifecycle=transition.state.as_dict(),
            )
        return self._submit(transition.state, quote, snapshot, now)

    def run_forever(self) -> dict[str, Any]:
        while True:
            try:
                result = self.run_once()
            except Exception as exc:
                if self.runtime is None or self.runtime.get("phase") != "DRAINING":
                    raise
                self.runtime["safety_failures"] = int(
                    self.runtime.get("safety_failures", 0)
                ) + 1
                self._save_runtime()
                self._event(
                    "DRAIN_RETRY_ERROR",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                self.sleep_func(self.config.idle_poll_seconds)
                continue
            if result.get("status") == "DRAINED_FLAT":
                return result
            lifecycle = self._lifecycle_state()
            active_quote_phase = lifecycle is not None and lifecycle.phase in {
                V8Phase.ARMED,
                V8Phase.PRESSURE,
                V8Phase.WAITING,
            }
            wait = (
                self.config.quote_poll_seconds
                if active_quote_phase
                else self.config.idle_poll_seconds
            )
            self.sleep_func(wait)

    def _maybe_arm(
        self,
        quote: QuoteObservation,
        snapshot: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any] | None:
        candles_raw = self.broker.fetch_closed_rates("1m", 60)
        if len(candles_raw) < 60:
            return self._heartbeat(
                "MISSING_CLOSED_CANDLES",
                closed_candle_count=len(candles_raw),
            )
        candles = tuple(_candle(value) for value in candles_raw[-60:])
        latest = max(candles, key=lambda candle: parse_utc(candle.timestamp))
        latest_time = parse_utc(latest.timestamp).isoformat()
        if self.runtime.get("last_closed_candle") == latest_time:
            return None
        self.runtime["last_closed_candle"] = latest_time
        arms = detect_v8_arms(candles, config=self._strategy_config(snapshot))
        if not arms:
            self._save_runtime()
            return None
        arm = arms[0]
        if arm.arm_id in set(self.runtime.get("consumed_arm_ids") or []):
            self._save_runtime()
            return None
        cooldown = _optional_datetime(self.runtime.get("cooldown_until_utc"))
        reset_after = _optional_datetime(
            self.runtime.get("structural_reset_after_utc")
        )
        if cooldown is not None and now < cooldown:
            self._remember_consumed(arm.arm_id)
            self._save_runtime()
            return self._heartbeat(
                "TWO_LOSS_PAUSE_ACTIVE",
                cooldown_until_utc=cooldown.isoformat(),
            )
        if reset_after is not None and parse_utc(arm.confirmation_closed_at) <= reset_after:
            self._remember_consumed(arm.arm_id)
            self._save_runtime()
            return self._heartbeat(
                "STRUCTURAL_RESET_REQUIRED",
                structural_reset_after_utc=reset_after.isoformat(),
            )
        if reset_after is not None:
            self.runtime["cooldown_until_utc"] = None
            self.runtime["structural_reset_after_utc"] = None
        state = start_v8_state(arm, quote)
        self._set_lifecycle(state, transition={"event": "ARMED"})
        self._event("ARMED", arm_id=arm.arm_id, family=arm.family, direction=arm.direction)
        return self._heartbeat("ARMED", lifecycle=state.as_dict())

    def _submit(
        self,
        state: V8State,
        quote: QuoteObservation,
        snapshot: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        strategy = self._strategy_config(snapshot)
        decision = evaluate_v8_stop_order(state, quote, config=strategy)
        if not decision.accepted:
            terminal = replace(
                state,
                phase=V8Phase.REJECTED,
                terminal_reason=decision.reason,
                sequence=state.sequence + 1,
            )
            self._set_lifecycle(terminal, transition={"event": decision.reason})
            self._consume_lifecycle(decision.reason)
            return self._heartbeat("ORDER_NOT_PREPARED", decision=decision.as_dict())

        prepared = mark_v8_placed(state, decision)
        self._set_lifecycle(
            prepared,
            transition={"event": "SUBMISSION_PREPARED", "decision": decision.as_dict()},
            submission_status="PREPARED",
        )
        proposal = self._proposal(prepared, decision, quote)
        history = self._reconcile_history(now)
        if history.get("status") != "RECONCILED":
            self.runtime["telemetry_failures"] += 1
            self._save_runtime()
            self._consume_lifecycle("HISTORY_RECONCILIATION_REQUIRED")
            return self._heartbeat("ORDER_BLOCKED_RECONCILIATION", history=history)
        orders = self.broker.open_orders(self.executor.config.symbol)
        positions = self.broker.open_positions(self.executor.config.symbol)
        reserved, unpriced = calculate_reserved_exposure_currency(
            self.broker, orders, positions
        )
        proposed = self.broker.estimate_stop_loss_account_currency(
            prepared.arm.direction,
            self.config.volume,
            float(decision.entry),
            float(decision.stop_loss),
        )
        budget = V8RiskBudget(
            unit_risk_currency=float(self.runtime["unit_risk_currency"]),
            max_session_r=self.config.max_session_r,
        )
        risk = evaluate_v8_risk_budget(
            budget,
            realized_net_currency=float(history.get("net_profit") or 0.0),
            reserved_exposure_currency=reserved,
            proposed_stop_risk_currency=proposed,
            unpriced_exposure_count=unpriced,
        )
        self.runtime["last_risk_decision"] = risk.as_dict()
        self._save_runtime()
        if not risk.accepted:
            self._consume_lifecycle(risk.reason)
            return self._heartbeat("ORDER_BLOCKED_RISK_BUDGET", risk=risk.as_dict())

        execution = self.executor.execute_proposal(proposal)
        if execution.get("status") != "PLACED":
            self._consume_lifecycle(
                "BROKER_ORDER_NOT_PLACED",
                extra={"execution": execution},
            )
            return self._heartbeat(
                "ORDER_NOT_PLACED",
                execution=execution,
                risk=risk.as_dict(),
            )
        lifecycle = self.runtime["lifecycle"]
        lifecycle["submission_status"] = "ACKNOWLEDGED"
        lifecycle["order_ticket"] = execution.get("order")
        lifecycle["execution"] = execution
        order_ticket = str(execution.get("order"))
        allowed_drift = max(
            float(prepared.pressure_median_spread or 0.0),
            float(strategy.tick_size),
        )
        self.runtime.setdefault("submissions", {})[order_ticket] = {
            "arm_id": prepared.arm.arm_id,
            "family": prepared.arm.family,
            "direction": prepared.arm.direction,
            "armed_at": prepared.arm.confirmation_closed_at,
            "triggered_at": prepared.structural.triggered_at,
            "placed_at": now.isoformat(),
            "planned_entry": float(decision.entry),
            "planned_stop": float(decision.stop_loss),
            "planned_target": float(decision.take_profit),
            "pending_expires_at": decision.expires_at,
            "allowed_entry_drift": allowed_drift,
            "entry_drift_checked": False,
            "entry_drift": None,
            "entry_drift_compliant": None,
        }
        self._save_runtime()
        self._event(
            "ORDER_ACKNOWLEDGED",
            arm_id=prepared.arm.arm_id,
            order_ticket=execution.get("order"),
            family=prepared.arm.family,
            direction=prepared.arm.direction,
            planned_entry=float(decision.entry),
            planned_stop=float(decision.stop_loss),
            planned_target=float(decision.take_profit),
            allowed_entry_drift=allowed_drift,
            pending_expires_at=decision.expires_at,
        )
        return self._heartbeat(
            "ORDER_PLACED",
            execution=execution,
            risk=risk.as_dict(),
        )

    def _maintain_external(
        self,
        lifecycle: V8State,
        orders: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        quote: QuoteObservation,
        now: datetime,
    ) -> dict[str, Any]:
        expires = _optional_datetime(lifecycle.pending_expires_at)
        cancellations = []
        if orders and expires is not None and now >= expires:
            for order in orders:
                ticket = int(order["ticket"])
                result = self.broker.cancel_order(ticket)
                cancellations.append({"ticket": ticket, "result": result})
            self._event("PENDING_EXPIRY_CANCEL", cancellations=cancellations)
            orders = self.broker.open_orders(self.executor.config.symbol)
        if orders:
            return self._heartbeat(
                "PENDING_MONITORED",
                pending_expires_at=lifecycle.pending_expires_at,
                orders=orders,
                cancellations=cancellations,
            )
        if positions:
            return self._heartbeat("POSITION_MONITORED", positions=positions)
        history = self._reconcile_history(now)
        reason = (
            "TRADE_LIFECYCLE_CLOSED"
            if history.get("closed_trade_count", 0)
            else "PENDING_LIFECYCLE_ENDED"
        )
        self._consume_lifecycle(reason)
        return self._heartbeat(reason, history=history, cancellations=cancellations)

    def _enter_draining(self, now: datetime) -> None:
        self.runtime["phase"] = "DRAINING"
        self.runtime["drain_started_at_utc"] = now.isoformat()
        self.runtime["drain_deadline_utc"] = (
            now + timedelta(seconds=self.config.shutdown_grace_seconds)
        ).isoformat()
        self.runtime["flat_verification_count"] = 0
        self._save_runtime()
        self._event(
            "DRAINING_STARTED",
            drain_deadline_utc=self.runtime["drain_deadline_utc"],
        )

    def _drain_once(self, now: datetime) -> dict[str, Any]:
        connection = self._connect_demo()
        orders = self.broker.open_orders(self.executor.config.symbol)
        cancel_actions = []
        for order in orders:
            ticket = int(order["ticket"])
            result = self.broker.cancel_order(ticket)
            cancel_actions.append({"ticket": ticket, "result": result})
        drain_deadline = parse_utc(self.runtime["drain_deadline_utc"])
        management = None
        close_actions = []
        positions = self.broker.open_positions(self.executor.config.symbol)
        if positions and now < drain_deadline:
            try:
                management = self.executor.manage_open_positions()
            except Exception as exc:
                management = {
                    "status": "MANAGEMENT_ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
        elif positions:
            for position in positions:
                result = self.broker.close_position(
                    position,
                    comment="TA V8 drain close",
                )
                close_actions.append(
                    {"ticket": position.get("ticket"), "result": result}
                )

        # A new DEMO proof and broker reads are required for every flat count.
        fresh_connection = self._connect_demo()
        fresh_orders = self.broker.open_orders(self.executor.config.symbol)
        fresh_positions = self.broker.open_positions(self.executor.config.symbol)
        if fresh_orders or fresh_positions:
            self.runtime["flat_verification_count"] = 0
        else:
            self.runtime["flat_verification_count"] += 1
        complete = (
            self.runtime["flat_verification_count"]
            >= self.config.flat_verification_count
        )
        if complete:
            self.runtime["phase"] = "COMPLETE"
            self.runtime["completed_at_utc"] = now.isoformat()
            lifecycle = self._lifecycle_state()
            if lifecycle is not None:
                self._remember_consumed(lifecycle.arm.arm_id)
                self.runtime["lifecycle"] = None
        self._save_runtime()
        status = "DRAINED_FLAT" if complete else "DRAINING"
        if cancel_actions:
            self._event("DRAIN_CANCEL_ACTIONS", actions=cancel_actions)
        if close_actions:
            self._event("DRAIN_CLOSE_ACTIONS", actions=close_actions)
        return self._heartbeat(
            status,
            account_safety=account_safety_from_connection(
                fresh_connection, require_demo=True
            ),
            cancel_actions=cancel_actions,
            management=management,
            close_actions=close_actions,
            orders=fresh_orders,
            positions=fresh_positions,
            flat_verification_count=self.runtime["flat_verification_count"],
            required_flat_verifications=self.config.flat_verification_count,
            drain_deadline_utc=self.runtime["drain_deadline_utc"],
        )

    def _reconcile_history(self, now: datetime) -> dict[str, Any]:
        try:
            result = self.executor.reconcile_trade_history(
                since_utc=parse_utc(self.runtime["started_at_utc"]),
                now_utc=now,
            )
        except Exception as exc:
            self.runtime["reconciliation_failures"] = int(
                self.runtime.get("reconciliation_failures", 0)
            ) + 1
            self._save_runtime()
            return {
                "status": "RECONCILE_ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        if result.get("status") != "RECONCILED":
            self.runtime["reconciliation_failures"] = int(
                self.runtime.get("reconciliation_failures", 0)
            ) + 1
            self._save_runtime()
            return result
        trades = sorted(
            result.get("closed_trades") or [],
            key=lambda trade: (
                str(trade.get("closed_at_utc") or ""),
                int(trade.get("exit_deal_ticket") or 0),
            ),
        )
        ids = [str(trade.get("exit_deal_ticket") or trade.get("position_id")) for trade in trades]
        previous = set(self.runtime.get("last_closed_trade_ids") or [])
        if any(identifier not in previous for identifier in ids):
            streak = 0
            for trade in trades:
                profit = float(trade.get("profit") or 0.0)
                streak = streak + 1 if profit < 0 else 0
            self.runtime["consecutive_losses"] = streak
            if streak >= 2 and trades:
                closed_at = _optional_datetime(trades[-1].get("closed_at_utc")) or now
                cooldown = closed_at + timedelta(seconds=self.config.loss_pause_seconds)
                existing = _optional_datetime(self.runtime.get("cooldown_until_utc"))
                if existing is None or cooldown > existing:
                    self.runtime["cooldown_until_utc"] = cooldown.isoformat()
                    self.runtime["structural_reset_after_utc"] = cooldown.isoformat()
                    self._event(
                        "TWO_LOSS_PAUSE_STARTED",
                        cooldown_until_utc=cooldown.isoformat(),
                        consecutive_losses=streak,
                    )
            elif streak == 0:
                self.runtime["cooldown_until_utc"] = None
                self.runtime["structural_reset_after_utc"] = None
        self.runtime["last_closed_trade_ids"] = ids
        self.runtime["last_history"] = result
        self._update_live_evidence(result)
        self._save_runtime()
        return result

    def _update_live_evidence(self, history: dict[str, Any]) -> None:
        submissions = self.runtime.setdefault("submissions", {})
        fills = {
            str(trade.get("entry_order")): trade
            for trade in history.get("filled_trades") or []
            if trade.get("entry_order") not in (None, "")
        }
        closed = {
            str(trade.get("entry_order")): trade
            for trade in history.get("closed_trades") or []
            if trade.get("entry_order") not in (None, "")
        }
        rows: list[dict[str, Any]] = []
        for ticket, submission in sorted(submissions.items()):
            fill = fills.get(str(ticket))
            trade = closed.get(str(ticket))
            if fill is not None:
                drift = abs(
                    float(fill.get("entry_price") or 0.0)
                    - float(submission["planned_entry"])
                )
                compliant = drift <= float(submission["allowed_entry_drift"]) + 1e-12
                if not submission.get("entry_drift_checked") and not compliant:
                    self.runtime["entry_drift_failures"] = int(
                        self.runtime.get("entry_drift_failures", 0)
                    ) + 1
                submission["entry_drift_checked"] = True
                submission["entry_drift"] = drift
                submission["entry_drift_compliant"] = compliant
                submission["position_id"] = fill.get("position_id")
                submission["filled_at"] = fill.get("opened_at_utc")
                submission["fill_price"] = fill.get("entry_price")
            profit_r = None
            if trade is not None:
                profit_r = float(trade.get("profit") or 0.0) / float(
                    self.runtime["unit_risk_currency"]
                )
                submission["closed_at"] = trade.get("closed_at_utc")
                submission["profit_currency"] = float(trade.get("profit") or 0.0)
                submission["profit_r"] = profit_r
            rows.append(
                {
                    "arm_id": str(submission["arm_id"]),
                    "session_id": Path(self.config.results_dir).name,
                    "family": str(submission["family"]),
                    "direction": str(submission["direction"]),
                    "armed_at": str(submission["armed_at"]),
                    "triggered_at": submission.get("triggered_at"),
                    "placed_at": submission.get("placed_at"),
                    "filled_at": fill.get("opened_at_utc") if fill else None,
                    "closed_at": trade.get("closed_at_utc") if trade else None,
                    "outcome": (
                        str(trade.get("outcome") or "CLOSED")
                        if trade
                        else ("FILLED" if fill else "PLACED")
                    ),
                    "reason": str(trade.get("exit_comment") or "") if trade else "",
                    "profit_r": profit_r,
                }
            )
        self.runtime["evidence_rows"] = rows

    def _strategy_config(self, snapshot: dict[str, Any]) -> V8Config:
        symbol = snapshot.get("symbol") or {}
        return V8Config(
            tick_size=float(
                symbol.get("trade_tick_size") or symbol.get("point") or 0.01
            ),
            broker_stop_distance=float(
                symbol.get("trade_stops_distance_price") or 0.0
            ),
            broker_freeze_distance=float(
                symbol.get("trade_freeze_distance_price") or 0.0
            ),
        )

    def _proposal(self, state: V8State, decision: Any, quote: QuoteObservation) -> OrderProposal:
        arm = state.arm
        return OrderProposal(
            symbol=self.executor.config.symbol,
            broker_symbol=self.executor.config.symbol,
            side=TradeAction(arm.direction),
            order_type=str(decision.order_kind),
            setup_name=CANDIDATE_NAME,
            strategy_type="quote_pressure",
            trigger_name=arm.family,
            reaction_type="quote_pressure",
            confirmation_type=arm.confirmation_type,
            touch_count=arm.touch_count,
            candidate_score=state.pressure_score,
            volume_decision="FIXED_NO_BOOST",
            opening_context={
                "model_name": CANDIDATE_NAME,
                "arm_id": arm.arm_id,
                "direction": arm.direction,
                "trigger": arm.family,
                "reaction_type": "quote_pressure",
                "confirmation_type": arm.confirmation_type,
                "level": arm.level,
                "level_side": arm.level_side,
                "tolerance": arm.tolerance,
                "touch_count": arm.touch_count,
                "confirmation_timestamp": arm.confirmation_time,
            },
            signal_quality={
                "directional_quote_pressure": state.pressure_score,
                "directional_displacement": state.pressure_displacement,
                "adverse_movement": state.pressure_adverse,
                "median_spread": state.pressure_median_spread,
                "quote_pressure_not_order_flow": True,
            },
            decision_quote={
                "observed_at_utc": quote.time,
                "bid": quote.bid,
                "ask": quote.ask,
                "spread_price": quote.spread,
            },
            entry_price=decision.entry,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            volume=self.config.volume,
            volume_multiplier=None,
            position_lifecycle="FAST_PARTIAL_SCALE",
            timeframe="1m",
            confirmation_timeframe="1m",
            valid_until=str(decision.expires_at),
            activation_window_minutes=1,
            cancel_if_not_triggered_after=str(decision.expires_at),
            status=OrderStatus.PROPOSED,
            reason="Frozen V8 quote-pressure gate passed",
        )

    def _connect_demo(self) -> dict[str, Any]:
        connection = self.broker.connect()
        safety = account_safety_from_connection(connection, require_demo=True)
        if safety.get("trade_mode") == "REAL" or not safety.get("passed"):
            if self.runtime is not None:
                self.runtime["safety_failures"] += 1
                self._save_runtime()
            raise ValueError(safety.get("reason") or "V8 refuses non-DEMO account")
        return connection

    def _quote_from_snapshot(self, snapshot: dict[str, Any]) -> QuoteObservation:
        symbol = snapshot.get("symbol") or {}
        tick = snapshot.get("tick") or {}
        when = tick.get("time_utc") or self._now().isoformat()
        quote = QuoteObservation(
            time=str(when),
            bid=float(symbol.get("bid")),
            ask=float(symbol.get("ask")),
        )
        if not quote.valid:
            raise ValueError("MT5 returned an invalid V8 quote")
        return quote

    def _lifecycle_state(self) -> V8State | None:
        lifecycle = (self.runtime or {}).get("lifecycle")
        if not isinstance(lifecycle, dict) or not isinstance(lifecycle.get("state"), dict):
            return None
        return V8State.from_dict(lifecycle["state"])

    def _set_lifecycle(
        self,
        state: V8State,
        *,
        transition: dict[str, Any],
        submission_status: str | None = None,
    ) -> None:
        current = self.runtime.get("lifecycle") or {}
        self.runtime["lifecycle"] = {
            **current,
            "arm_id": state.arm.arm_id,
            "state": state.as_dict(),
            "last_transition": transition,
            "submission_status": submission_status
            if submission_status is not None
            else current.get("submission_status"),
        }
        self._save_runtime()

    def _consume_lifecycle(
        self,
        reason: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        lifecycle = self._lifecycle_state()
        if lifecycle is not None:
            self._remember_consumed(lifecycle.arm.arm_id)
            self._event("LIFECYCLE_CONSUMED", arm_id=lifecycle.arm.arm_id, reason=reason)
        self.runtime["last_lifecycle_result"] = {"reason": reason, **(extra or {})}
        self.runtime["lifecycle"] = None
        self._save_runtime()

    def _remember_consumed(self, arm_id: str) -> None:
        consumed = list(self.runtime.get("consumed_arm_ids") or [])
        if arm_id not in consumed:
            consumed.append(arm_id)
        self.runtime["consumed_arm_ids"] = consumed[-500:]

    def _validate_recovered_runtime(self, runtime: dict[str, Any]) -> None:
        if runtime.get("schema_version") != self.STATE_SCHEMA_VERSION:
            raise ValueError("unsupported recovered V8 runtime schema")
        if runtime.get("candidate") != CANDIDATE_NAME:
            raise ValueError("recovered V8 candidate mismatch")
        if runtime.get("promotion_sha256") != self.validation.promotion_sha256:
            raise ValueError("recovered V8 promotion hash mismatch")
        if runtime.get("manifest_sha256") != self.validation.manifest_sha256:
            raise ValueError("recovered V8 manifest hash mismatch")
        if float(runtime.get("volume")) != self.config.volume:
            raise ValueError("recovered V8 volume mismatch")
        if runtime.get("phase") not in {"RUNNING", "DRAINING", "COMPLETE"}:
            raise ValueError("invalid recovered V8 runtime phase")

    def _save_runtime(self) -> None:
        assert self.runtime is not None
        self.state_store.save(self.runtime)

    def _heartbeat(self, status: str, **details: Any) -> dict[str, Any]:
        payload = {
            "candidate": CANDIDATE_NAME,
            "status": status,
            "phase": (self.runtime or {}).get("phase"),
            "heartbeat_utc": self._now().isoformat(),
            "runtime_deadline_utc": (self.runtime or {}).get("runtime_deadline_utc"),
            "drain_deadline_utc": (self.runtime or {}).get("drain_deadline_utc"),
            "volume": self.config.volume,
            "max_session_r": self.config.max_session_r,
            "unit_risk_currency": (self.runtime or {}).get("unit_risk_currency"),
            "budget_currency": (self.runtime or {}).get("budget_currency"),
            "consecutive_losses": (self.runtime or {}).get("consecutive_losses"),
            "cooldown_until_utc": (self.runtime or {}).get("cooldown_until_utc"),
            "safety_failures": (self.runtime or {}).get("safety_failures", 0),
            "telemetry_failures": (self.runtime or {}).get("telemetry_failures", 0),
            **details,
        }
        self.heartbeat_store.save(payload)
        return payload

    def _event(self, event: str, **details: Any) -> None:
        payload = {
            "event": event,
            "time_utc": self._now().isoformat(),
            **details,
        }
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
            handle.flush()

    def _now(self) -> datetime:
        value = self.now_func()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return parse_utc(str(value))


def _candle(value: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=str(value["timestamp"]),
        open=float(value["open"]),
        high=float(value["high"]),
        low=float(value["low"]),
        close=float(value["close"]),
        volume=float(
            value.get("real_volume")
            or value.get("tick_volume")
            or value.get("volume")
            or 0.0
        ),
    )


__all__ = ["MT5OneMinuteV8Runner", "MT5OneMinuteV8RunnerConfig"]
