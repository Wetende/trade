"""MT5 execution service for local order proposals."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.execution_journal import ExecutionJournal
from tradingagents.brokers.execution_state import (
    ExecutionStateStore,
    account_state_namespace,
)
from tradingagents.brokers.opening_freshness import stale_consumed_opening
from tradingagents.brokers.mode_gate import account_safety_from_connection
from tradingagents.brokers.mt5 import (
    MT5Broker,
    MT5ConnectionConfig,
    MT5OrderRequestBuilder,
    safe_mt5_connection_status,
)

ONE_MINUTE_POSITION_COMMENT = "TA|M1|FAST"
ONE_MINUTE_MIN_SUBMISSION_WINDOW_SECONDS = 1.0
ONE_MINUTE_INVALID_PRICE_RETCODE = 10015
ONE_MINUTE_MAX_EXECUTION_REPRICE_R = 0.15
ONE_MINUTE_MAX_STOP_DISTANCE_PRICE = 1.0


@dataclass(frozen=True)
class MT5ExitManagementConfig:
    """Point-based active-position management for engine trades."""

    enabled: bool = True
    break_even_trigger_points: float = 2.0
    break_even_lock_points: float = 0.0
    trailing_trigger_points: float = 0.0
    trailing_distance_points: float = 0.0
    min_stop_update_points: float = 0.0
    early_loss_exit_points: float = 0.0
    scalp_profit_points: float = 0.0
    partial_first_trigger_points: float = 0.0
    partial_first_target_volume: float = 0.0
    partial_second_trigger_points: float = 0.0
    partial_second_target_volume: float = 0.0
    candle_rejection_exit_enabled: bool = True
    candle_rejection_timeframe: str = "1m"
    candle_rejection_partial_fraction: float = 0.5
    intrabar_adverse_exit_fraction: float = 0.65
    intrabar_adverse_confirmations: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not isinstance(self.candle_rejection_exit_enabled, bool):
            raise ValueError("candle_rejection_exit_enabled must be a boolean")
        timeframe = str(self.candle_rejection_timeframe or "").strip().lower()
        if not timeframe:
            raise ValueError("candle_rejection_timeframe must be non-empty")
        object.__setattr__(self, "candle_rejection_timeframe", timeframe)
        for name in (
            "break_even_trigger_points",
            "break_even_lock_points",
            "trailing_trigger_points",
            "trailing_distance_points",
            "min_stop_update_points",
            "early_loss_exit_points",
            "scalp_profit_points",
            "partial_first_trigger_points",
            "partial_first_target_volume",
            "partial_second_trigger_points",
            "partial_second_target_volume",
            "candle_rejection_partial_fraction",
            "intrabar_adverse_exit_fraction",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
            object.__setattr__(self, name, value)
        if self.candle_rejection_partial_fraction > 1:
            raise ValueError("candle_rejection_partial_fraction must be <= 1")
        if not 0 < self.intrabar_adverse_exit_fraction <= 1:
            raise ValueError("intrabar_adverse_exit_fraction must be > 0 and <= 1")
        confirmations = self.intrabar_adverse_confirmations
        if (
            isinstance(confirmations, bool)
            or not isinstance(confirmations, int)
            or confirmations < 1
        ):
            raise ValueError("intrabar_adverse_confirmations must be a positive integer")


@dataclass(frozen=True)
class MT5OneMinuteLifecycleConfig:
    """Execution timing rules for one-minute scalper proposals."""

    reaction_pending_seconds: float = 20.0
    impulse_pending_seconds: float = 45.0
    candle_boundary_lead_seconds: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "reaction_pending_seconds",
            "impulse_pending_seconds",
            "candle_boundary_lead_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
            object.__setattr__(self, name, value)


def _is_one_minute_scalper_proposal(proposal: OrderProposal) -> bool:
    timeframe = str(proposal.timeframe or "").strip().lower()
    lifecycle = str(proposal.position_lifecycle or "").strip().upper()
    return timeframe == "1m" and lifecycle == "FAST_PARTIAL_SCALE"


def build_pending_order_policy(
    proposal: OrderProposal,
    placed_at_utc: datetime,
    lifecycle: MT5OneMinuteLifecycleConfig,
) -> dict[str, Any]:
    """Return the effective deterministic expiry policy for a proposal."""
    placed_at = _parse_utc_datetime(placed_at_utc)
    if placed_at is None:
        raise ValueError("placed_at_utc must be a valid datetime")

    activation_minutes = int(proposal.activation_window_minutes or 10)
    if not _is_one_minute_scalper_proposal(proposal):
        max_age_seconds = float(activation_minutes * 60)
        cancel_after = placed_at + timedelta(seconds=max_age_seconds)
        return {
            "policy": "ACTIVATION_WINDOW",
            "max_age_seconds": max_age_seconds,
            "cancel_after_utc": cancel_after.isoformat(),
            "candle_boundary_utc": None,
        }

    reaction_type = str(proposal.reaction_type or "").strip().lower()
    if reaction_type in {"impulse_break", "break"}:
        policy_name = "ONE_MINUTE_IMPULSE"
        max_age_seconds = lifecycle.impulse_pending_seconds
    else:
        policy_name = "ONE_MINUTE_REACTION"
        max_age_seconds = lifecycle.reaction_pending_seconds

    age_expiry = placed_at + timedelta(seconds=max_age_seconds)
    candle_boundary = placed_at.replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    boundary_expiry = candle_boundary - timedelta(
        seconds=lifecycle.candle_boundary_lead_seconds
    )
    cancel_after = min(age_expiry, boundary_expiry)
    return {
        "policy": policy_name,
        "reaction_type": reaction_type or None,
        "max_age_seconds": max_age_seconds,
        "cancel_after_utc": cancel_after.isoformat(),
        "candle_boundary_utc": candle_boundary.isoformat(),
    }


def load_order_proposal(path: str | Path) -> OrderProposal:
    """Load an order proposal JSON artifact from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return OrderProposal.model_validate(data)


def _parse_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timeframe_duration(timeframe: str) -> timedelta | None:
    normalized = str(timeframe or "").strip().lower()
    durations = {
        "1m": timedelta(minutes=1),
        "2m": timedelta(minutes=2),
        "3m": timedelta(minutes=3),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }
    return durations.get(normalized)


def _safe_quote_snapshot(
    snapshot: dict[str, Any] | None,
    observed_at_utc: datetime,
) -> dict[str, Any]:
    raw = snapshot or {}
    symbol = raw.get("symbol") or {}
    tick = raw.get("tick") or {}
    bid = _first_float(symbol, "bid")
    ask = _first_float(symbol, "ask")
    spread = _first_float(symbol, "spread_price")
    if spread is None and bid is not None and ask is not None:
        spread = max(0.0, ask - bid)
    return {
        "observed_at_utc": observed_at_utc.astimezone(timezone.utc).isoformat(),
        "tick_time_utc": tick.get("time_utc"),
        "bid": round(bid, 8) if bid is not None else None,
        "ask": round(ask, 8) if ask is not None else None,
        "spread_price": round(spread, 8) if spread is not None else None,
    }


class MT5Executor:
    """Coordinate one-symbol guarded MT5 proposal execution."""

    def __init__(
        self,
        config: MT5ConnectionConfig,
        results_dir: str | Path,
        broker: Any | None = None,
        journal: ExecutionJournal | None = None,
        exit_management: MT5ExitManagementConfig | None = None,
        one_minute_lifecycle: MT5OneMinuteLifecycleConfig | None = None,
        state_dir: str | Path | None = None,
    ) -> None:
        self.config = config
        self.broker = broker or MT5Broker(config)
        self.builder = MT5OrderRequestBuilder(config)
        self.journal = journal or ExecutionJournal(results_dir, config.symbol)
        effective_state_dir = (
            state_dir
            or getattr(config, "execution_state_dir", None)
            or results_dir
        )
        account_namespace = account_state_namespace(
            config.expected_server or config.server,
            config.expected_login or config.login,
        )
        self.state = ExecutionStateStore(
            Path(effective_state_dir) / account_namespace,
            config.symbol,
        )
        self.exit_management = exit_management or MT5ExitManagementConfig()
        self.one_minute_lifecycle = (
            one_minute_lifecycle or MT5OneMinuteLifecycleConfig()
        )
        persisted_capabilities = self.state.load_broker_capabilities()
        persisted_short_expiration = (
            persisted_capabilities.get("short_pending_expiration_supported")
            if isinstance(persisted_capabilities, dict)
            else None
        )
        self._server_expiration_supported: bool | None = (
            persisted_short_expiration
            if isinstance(persisted_short_expiration, bool)
            else None
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _timeline_now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def _safe_connection_status(
        self,
        connection: dict[str, Any],
        account_safety: dict[str, Any],
    ) -> dict[str, Any]:
        """Return truthful capability telemetry without inventing false flags."""
        symbol_snapshot = None
        snapshot = getattr(self.broker, "current_symbol_snapshot", None)
        if callable(snapshot):
            try:
                symbol_snapshot = snapshot()
            except Exception:
                # Connection/account safety still has to be journaled. Unknown
                # terminal permissions are omitted rather than recorded false.
                symbol_snapshot = None
        return safe_mt5_connection_status(
            connection,
            account_safety=account_safety,
            symbol_snapshot=symbol_snapshot,
        )

    def _rebuild_expiration_fallback_request(
        self,
        proposal: OrderProposal,
        symbol_info: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            return self.builder.build_pending_order_request(
                proposal,
                symbol_info,
            ), None
        except ValueError as exc:
            if "entry price is stale or inside spread" not in str(exc):
                raise
        adjustment = self._fallback_entry_adjustment(proposal, symbol_info)
        if adjustment is None:
            raise ValueError("entry price is stale or inside spread")
        adjusted = proposal.model_copy(
            update={"entry_price": adjustment["adjusted_entry"]}
        )
        request = self.builder.build_pending_order_request(
            adjusted,
            symbol_info,
        )
        return request, adjustment

    def _fallback_entry_adjustment(
        self,
        proposal: OrderProposal,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            bid = float(symbol_info.get("bid"))
            ask = float(symbol_info.get("ask"))
            entry = float(proposal.entry_price)
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(bid) and math.isfinite(ask) and math.isfinite(entry)):
            return None
        if not bid < entry < ask:
            return None
        tick_size = float(symbol_info.get("trade_tick_size") or 0.0)
        point = float(symbol_info.get("point") or 0.0)
        buffer = max(tick_size, point, 0.0)
        side = str(getattr(proposal.side, "value", proposal.side)).upper()
        if side == "BUY":
            adjusted_entry = ask + buffer
        elif side == "SELL":
            adjusted_entry = bid - buffer
        else:
            return None
        return {
            "reason": "ENTRY_INSIDE_SPREAD_AFTER_EXPIRATION_FALLBACK",
            "original_entry": round(entry, 8),
            "adjusted_entry": round(adjusted_entry, 8),
            "bid": round(bid, 8),
            "ask": round(ask, 8),
            "buffer": round(buffer, 8),
        }

    def _expired_pending_window_result(
        self,
        proposal: OrderProposal,
        pending_policy: dict[str, Any],
        checked_at: datetime,
        account_safety: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not _is_one_minute_scalper_proposal(proposal):
            return None
        cancel_after = _parse_utc_datetime(pending_policy["cancel_after_utc"])
        usable_seconds = (
            (cancel_after - checked_at).total_seconds()
            if cancel_after is not None
            else 0.0
        )
        if usable_seconds > ONE_MINUTE_MIN_SUBMISSION_WINDOW_SECONDS:
            return None
        return {
            "status": "SKIPPED_PENDING_WINDOW_EXPIRED",
            "reason": "ONE_MINUTE_PENDING_WINDOW_EXPIRED",
            "proposal": proposal.model_dump(mode="json"),
            "pending_policy": pending_policy,
            "usable_submission_seconds": max(0.0, usable_seconds),
            "account_safety": account_safety,
        }

    def _persist_short_expiration_support(
        self,
        supported: bool,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return self.state.record_short_pending_expiration_support(
            supported,
            reason=reason,
            observed_at_utc=self._now_utc(),
        )

    @staticmethod
    def _invalid_price_order_check(result: dict[str, Any]) -> bool:
        if result.get("retcode") == ONE_MINUTE_INVALID_PRICE_RETCODE:
            return True
        return "invalid price" in str(result.get("comment") or "").strip().lower()

    def _reprice_after_invalid_price(
        self,
        proposal: OrderProposal,
        request: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Rebuild one pending stop once against a fresh quote.

        MT5 can reject a direction-safe stop when the quote crosses its price
        between request construction and ``order_check``. The rebuild is
        deliberately bounded: it keeps the structural stop, preserves the
        reward/risk multiple, permits at most 0.15R of entry drift, and never
        permits an M1 stop wider than one price unit.
        """
        request_type = str(request.get("type") or "").strip().upper()
        if (
            not _is_one_minute_scalper_proposal(proposal)
            or request_type not in {"BUY_STOP", "SELL_STOP"}
        ):
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_NOT_APPLICABLE",
            }

        symbol_info = dict(snapshot.get("symbol") or {})
        observed_at = self._timeline_now_utc()
        fresh_quote = _safe_quote_snapshot(snapshot, observed_at)
        try:
            bid = float(symbol_info.get("bid"))
            ask = float(symbol_info.get("ask"))
            entry = float(request["price"])
            stop = float(request["sl"])
            target = float(request["tp"])
            digits = int(symbol_info.get("digits") or 2)
            point = float(symbol_info.get("point") or 0.0)
            tick_size = float(symbol_info.get("trade_tick_size") or 0.0)
            stops_distance = float(
                symbol_info.get("trade_stops_distance_price") or 0.0
            )
            if stops_distance <= 0:
                stops_distance = (
                    float(symbol_info.get("trade_stops_level") or 0.0) * point
                )
        except (KeyError, TypeError, ValueError):
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_QUOTE_UNAVAILABLE",
                "fresh_quote": fresh_quote,
            }
        if not all(
            math.isfinite(value)
            for value in (
                bid,
                ask,
                entry,
                stop,
                target,
                point,
                tick_size,
                stops_distance,
            )
        ) or bid <= 0 or ask <= 0 or bid > ask:
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_QUOTE_INVALID",
                "fresh_quote": fresh_quote,
            }

        grid = max(tick_size, point, 10 ** (-digits))
        broker_clearance = max(0.0, stops_distance) + grid

        def snap_up(value: float) -> float:
            return round(math.ceil((value / grid) - 1e-12) * grid, digits)

        def snap_down(value: float) -> float:
            return round(math.floor((value / grid) + 1e-12) * grid, digits)

        original_risk = abs(entry - stop)
        original_reward = abs(target - entry)
        if original_risk <= 0 or original_reward <= 0:
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_GEOMETRY_INVALID",
                "fresh_quote": fresh_quote,
            }
        reward_multiple = original_reward / original_risk
        if request_type == "BUY_STOP":
            safe_entry = snap_up(ask + broker_clearance)
            adjusted_entry = max(safe_entry, snap_up(entry + grid))
            adjusted_risk = adjusted_entry - stop
            adjusted_target = adjusted_entry + (adjusted_risk * reward_multiple)
        else:
            safe_entry = snap_down(bid - broker_clearance)
            adjusted_entry = min(safe_entry, snap_down(entry - grid))
            adjusted_risk = stop - adjusted_entry
            adjusted_target = adjusted_entry - (adjusted_risk * reward_multiple)

        entry_drift = abs(adjusted_entry - entry)
        allowed_entry_drift = original_risk * ONE_MINUTE_MAX_EXECUTION_REPRICE_R
        adjustment = {
            "reason": "FRESH_QUOTE_AFTER_INVALID_PRICE",
            "request_type": request_type,
            "original_entry": round(entry, 8),
            "adjusted_entry": round(adjusted_entry, 8),
            "entry_drift": round(entry_drift, 8),
            "allowed_entry_drift": round(allowed_entry_drift, 8),
            "original_risk": round(original_risk, 8),
            "adjusted_risk": round(adjusted_risk, 8),
            "reward_multiple": round(reward_multiple, 8),
            "broker_clearance": round(broker_clearance, 8),
            "fresh_quote": fresh_quote,
        }
        if entry_drift > allowed_entry_drift + 1e-12:
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_MOVED_TOO_FAR",
                "adjustment": adjustment,
                "fresh_quote": fresh_quote,
            }
        if (
            adjusted_risk <= 0
            or adjusted_risk > ONE_MINUTE_MAX_STOP_DISTANCE_PRICE + 1e-12
        ):
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_STOP_OUT_OF_RANGE",
                "adjustment": adjustment,
                "fresh_quote": fresh_quote,
            }

        adjusted_proposal = proposal.model_copy(
            update={
                "order_type": request_type,
                "entry_price": adjusted_entry,
                "stop_loss": stop,
                "take_profit": adjusted_target,
            }
        )
        try:
            retry_request = self.builder.build_pending_order_request(
                adjusted_proposal,
                symbol_info,
            )
        except ValueError as exc:
            return {
                "ok": False,
                "reason": "INVALID_PRICE_REPRICE_REQUEST_INVALID",
                "error": str(exc),
                "adjustment": adjustment,
                "fresh_quote": fresh_quote,
            }
        retry_request["comment"] = request.get(
            "comment",
            retry_request.get("comment"),
        )
        retry_request["type_time"] = request.get(
            "type_time",
            retry_request.get("type_time"),
        )
        if request.get("expiration") not in (None, ""):
            retry_request["expiration"] = request["expiration"]
        else:
            retry_request.pop("expiration", None)
        adjustment.update(
            {
                "adjusted_stop": retry_request["sl"],
                "adjusted_target": retry_request["tp"],
            }
        )
        return {
            "ok": True,
            "request": retry_request,
            "adjustment": adjustment,
            "fresh_quote": fresh_quote,
        }

    @staticmethod
    def _pending_stop_is_valid_for_quote(
        request: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> bool:
        """Validate a checked stop request against the final pre-send quote."""
        request_type = str(request.get("type") or "").strip().upper()
        if request_type not in {"BUY_STOP", "SELL_STOP"}:
            return True
        symbol = snapshot.get("symbol") or {}
        try:
            entry = float(request["price"])
            bid = float(symbol["bid"])
            ask = float(symbol["ask"])
            point = float(symbol.get("point") or 0.0)
            stop_distance = float(
                symbol.get("trade_stops_distance_price") or 0.0
            )
            if stop_distance <= 0:
                stop_distance = float(symbol.get("trade_stops_level") or 0.0) * point
        except (KeyError, TypeError, ValueError):
            return False
        if not all(math.isfinite(value) for value in (entry, bid, ask, stop_distance)):
            return False
        if bid <= 0 or ask <= 0 or bid > ask:
            return False
        if request_type == "BUY_STOP":
            return entry + 1e-12 >= ask + max(0.0, stop_distance)
        return entry - 1e-12 <= bid - max(0.0, stop_distance)

    def _active_trade_exists(self) -> bool:
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        return bool(orders or positions)

    def _sync_tracked_ticket(self, ticket: int) -> dict[str, Any] | None:
        """Clear stale local state when MT5 no longer has the pending ticket."""
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        open_order_tickets = {
            int(order["ticket"]) for order in orders if order.get("ticket")
        }
        open_position_tickets = {
            int(position["ticket"]) for position in positions if position.get("ticket")
        }

        if ticket in open_order_tickets:
            return None
        if ticket in open_position_tickets:
            self.state.mark_position_active(ticket)
            result = {
                "status": "ORDER_ALREADY_FILLED",
                "ticket": ticket,
                "symbol": self.config.symbol,
            }
            self.journal.append("ORDER_STATE_SYNCED", result)
            return result

        tagged_positions = [
            position
            for position in positions
            if str(position.get("comment") or "").strip()
            == ONE_MINUTE_POSITION_COMMENT
        ]
        if len(tagged_positions) == 1 and tagged_positions[0].get("ticket"):
            position_ticket = int(tagged_positions[0]["ticket"])
            self.state.mark_position_active(position_ticket)
            result = {
                "status": "ORDER_ALREADY_FILLED",
                "ticket": ticket,
                "position_ticket": position_ticket,
                "symbol": self.config.symbol,
            }
            self.journal.append("ORDER_STATE_SYNCED", result)
            return result

        self.state.clear_trade()
        result = {
            "status": "ORDER_NOT_OPEN",
            "ticket": ticket,
            "symbol": self.config.symbol,
        }
        self.journal.append("ORDER_STATE_SYNCED", result)
        return result

    def execute_proposal(self, proposal: OrderProposal) -> dict[str, Any]:
        """Place a pending order when no active trade exists."""
        connection = self.broker.connect()
        account_safety = self._account_safety(connection)
        self.journal.append(
            "CONNECTED",
            safe_mt5_connection_status(
                connection,
                account_safety=account_safety,
            ),
        )

        if not account_safety["passed"]:
            result = {
                "status": "SKIPPED_ACCOUNT_SAFETY",
                "reason": "ACCOUNT_SAFETY_FAILED",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
            self.journal.append("ORDER_SKIPPED", result)
            return result

        expiration_capability = (connection.get("symbol") or {}).get(
            "supports_order_time_specified"
        )
        if expiration_capability is False:
            self._server_expiration_supported = False
            self._persist_short_expiration_support(
                False,
                reason="SYMBOL_CAPABILITY_REJECTS_SPECIFIED_EXPIRATION",
            )
        elif (
            expiration_capability is True
            and self._server_expiration_supported is None
        ):
            self._server_expiration_supported = True
        elif not isinstance(expiration_capability, bool):
            self._server_expiration_supported = False
        self.journal.append(
            "ORDER_CAPABILITIES_READ",
            {
                key: (connection.get("symbol") or {}).get(key)
                for key in (
                    "expiration_mode",
                    "order_mode",
                    "filling_mode",
                    "trade_exemode",
                    "supports_order_time_gtc",
                    "supports_order_time_specified",
                    "supports_stop_orders",
                    "trade_stops_level",
                    "trade_freeze_level",
                    "trade_stops_distance_price",
                    "trade_freeze_distance_price",
                    "pending_filling_mode",
                )
            }
            | {
                "persistent_short_expiration_supported": (
                    self._server_expiration_supported
                )
            },
        )

        if self._active_trade_exists():
            result = {
                "status": "SKIPPED_ACTIVE_TRADE",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
            self.journal.append("SKIPPED_ACTIVE_TRADE", result)
            return result

        opening_context = (
            dict(proposal.opening_context)
            if isinstance(proposal.opening_context, dict)
            else None
        )
        if _is_one_minute_scalper_proposal(proposal):
            if opening_context is None:
                self.journal.append(
                    "OPENING_FRESHNESS_UNAVAILABLE",
                    {
                        "reason": "OPENING_FRESHNESS_UNAVAILABLE",
                        "trigger": proposal.trigger_name,
                        "side": str(getattr(proposal.side, "value", proposal.side)),
                    },
                )
            else:
                state = self.state.load()
                consumed = list(state.get("consumed_openings") or [])
                stale_record = stale_consumed_opening(
                    opening_context,
                    consumed,
                )
                if stale_record is not None:
                    result = {
                        "status": "SKIPPED_STALE_OPENING",
                        "reason": "STALE_CONSUMED_OPENING",
                        "opening_context": opening_context,
                        "consumed_opening": stale_record,
                        "account_safety": account_safety,
                    }
                    self.journal.append("OPENING_SKIPPED_STALE", result)
                    return result

        try:
            request = self.builder.build_pending_order_request(
                proposal,
                connection["symbol"],
            )
        except ValueError as exc:
            result = {
                "status": "SKIPPED_INVALID_ENTRY",
                "reason": "ENTRY_PRICE_STALE_OR_INVALID",
                "error": str(exc),
                "proposal": proposal.model_dump(mode="json"),
                "account_safety": account_safety,
            }
            self.journal.append("ORDER_SKIPPED", result)
            return result

        policy_started_at = self._now_utc()
        pending_policy = build_pending_order_policy(
            proposal,
            policy_started_at,
            self.one_minute_lifecycle,
        )
        if _is_one_minute_scalper_proposal(proposal):
            expired_result = self._expired_pending_window_result(
                proposal,
                pending_policy,
                policy_started_at,
                account_safety,
            )
            if expired_result is not None:
                result = expired_result
                self.journal.append("ORDER_SKIPPED", result)
                return result
            request["comment"] = ONE_MINUTE_POSITION_COMMENT
            cancel_after = _parse_utc_datetime(pending_policy["cancel_after_utc"])
            if (
                cancel_after is not None
                and self._server_expiration_supported is True
            ):
                request["type_time"] = "ORDER_TIME_SPECIFIED"
                request["expiration"] = int(cancel_after.timestamp())
        self.journal.append("ORDER_REQUEST_BUILT", request)

        order_check_result = None
        initial_order_check_result = None
        price_reprice = None
        check_order = getattr(self.broker, "check_order", None)
        if callable(check_order):
            order_check_result = check_order(request)
            self.journal.append("ORDER_CHECKED", order_check_result)
            if order_check_result.get("ok") is False:
                if self._invalid_price_order_check(order_check_result):
                    initial_order_check_result = dict(order_check_result)
                    snapshot_func = getattr(
                        self.broker,
                        "current_symbol_snapshot",
                        None,
                    )
                    if callable(snapshot_func):
                        price_reprice = self._reprice_after_invalid_price(
                            proposal,
                            request,
                            snapshot_func(),
                        )
                    else:
                        price_reprice = {
                            "ok": False,
                            "reason": "INVALID_PRICE_REPRICE_QUOTE_UNAVAILABLE",
                        }
                    self.journal.append(
                        "ORDER_INVALID_PRICE_REPRICE_EVALUATED",
                        price_reprice,
                    )
                    if price_reprice.get("ok") is True:
                        request = dict(price_reprice["request"])
                        self.journal.append("ORDER_REQUEST_REPRICED", request)
                        order_check_result = check_order(request)
                        self.journal.append("ORDER_CHECKED", order_check_result)
                        if order_check_result.get("ok") is False:
                            result = {
                                "status": "SKIPPED_ORDER_CHECK",
                                "reason": (
                                    "ORDER_CHECK_FAILED_AFTER_INVALID_PRICE_REPRICE"
                                ),
                                "proposal": proposal.model_dump(mode="json"),
                                "request": request,
                                "initial_order_check_result": (
                                    initial_order_check_result
                                ),
                                "order_check_result": order_check_result,
                                "price_reprice": price_reprice,
                                "account_safety": account_safety,
                            }
                            self.journal.append("ORDER_SKIPPED", result)
                            return result
                    else:
                        result = {
                            "status": "SKIPPED_ORDER_CHECK",
                            "reason": price_reprice.get("reason")
                            or "INVALID_PRICE_REPRICE_REJECTED",
                            "proposal": proposal.model_dump(mode="json"),
                            "request": request,
                            "initial_order_check_result": (
                                initial_order_check_result
                            ),
                            "order_check_result": order_check_result,
                            "price_reprice": price_reprice,
                            "account_safety": account_safety,
                        }
                        self.journal.append("ORDER_SKIPPED", result)
                        return result
                else:
                    result = {
                        "status": "SKIPPED_ORDER_CHECK",
                        "reason": "ORDER_CHECK_FAILED",
                        "proposal": proposal.model_dump(mode="json"),
                        "request": request,
                        "order_check_result": order_check_result,
                        "account_safety": account_safety,
                    }
                    self.journal.append("ORDER_SKIPPED", result)
                    return result

        expired_result = self._expired_pending_window_result(
            proposal,
            pending_policy,
            self._now_utc(),
            account_safety,
        )
        if expired_result is not None:
            result = {
                **expired_result,
                "request": request,
                "order_check_result": order_check_result,
            }
            self.journal.append("ORDER_SKIPPED", result)
            return result

        pre_send_observed_at = self._timeline_now_utc()
        snapshot_func = getattr(self.broker, "current_symbol_snapshot", None)
        if callable(snapshot_func):
            pre_send_source = snapshot_func()
        else:
            pre_send_source = {"symbol": connection.get("symbol") or {}}
        pre_send_quote = _safe_quote_snapshot(
            pre_send_source,
            pre_send_observed_at,
        )
        if (
            _is_one_minute_scalper_proposal(proposal)
            and callable(check_order)
            and not self._pending_stop_is_valid_for_quote(request, pre_send_source)
        ):
            if price_reprice is not None:
                result = {
                    "status": "SKIPPED_ORDER_CHECK",
                    "reason": "PRE_SEND_QUOTE_MOVED_AFTER_BOUNDED_REPRICE",
                    "proposal": proposal.model_dump(mode="json"),
                    "request": request,
                    "order_check_result": order_check_result,
                    "price_reprice": price_reprice,
                    "pre_send_quote": pre_send_quote,
                    "account_safety": account_safety,
                }
                self.journal.append("ORDER_SKIPPED", result)
                return result
            price_reprice = self._reprice_after_invalid_price(
                proposal,
                request,
                pre_send_source,
            )
            self.journal.append(
                "ORDER_PRE_SEND_REPRICE_EVALUATED",
                price_reprice,
            )
            if price_reprice.get("ok") is not True:
                result = {
                    "status": "SKIPPED_ORDER_CHECK",
                    "reason": price_reprice.get("reason")
                    or "PRE_SEND_REPRICE_REJECTED",
                    "proposal": proposal.model_dump(mode="json"),
                    "request": request,
                    "order_check_result": order_check_result,
                    "price_reprice": price_reprice,
                    "pre_send_quote": pre_send_quote,
                    "account_safety": account_safety,
                }
                self.journal.append("ORDER_SKIPPED", result)
                return result
            request = dict(price_reprice["request"])
            self.journal.append("ORDER_REQUEST_REPRICED_PRE_SEND", request)
            order_check_result = check_order(request)
            self.journal.append("ORDER_CHECKED", order_check_result)
            if order_check_result.get("ok") is False:
                result = {
                    "status": "SKIPPED_ORDER_CHECK",
                    "reason": "ORDER_CHECK_FAILED_AFTER_PRE_SEND_REPRICE",
                    "proposal": proposal.model_dump(mode="json"),
                    "request": request,
                    "order_check_result": order_check_result,
                    "price_reprice": price_reprice,
                    "pre_send_quote": pre_send_quote,
                    "account_safety": account_safety,
                }
                self.journal.append("ORDER_SKIPPED", result)
                return result
        submitted_at = pre_send_observed_at
        broker_result = self.broker.place_pending_order(request)
        acknowledged_at = self._timeline_now_utc()
        execution_timeline = {
            "decision_quote": (
                dict(proposal.decision_quote)
                if isinstance(proposal.decision_quote, dict)
                else None
            ),
            "pre_send_quote": pre_send_quote,
            "submitted_at_utc": submitted_at.astimezone(timezone.utc).isoformat(),
            "acknowledged_at_utc": acknowledged_at.astimezone(
                timezone.utc
            ).isoformat(),
            "attempt": 1,
        }
        if isinstance(price_reprice, dict):
            execution_timeline["price_reprice"] = dict(price_reprice)
        self.journal.append("ORDER_EXECUTION_TIMELINE", execution_timeline)
        expiration_fallback = False
        if (
            not bool(broker_result.get("ok"))
            and _is_one_minute_scalper_proposal(proposal)
            and request.get("type_time") == "ORDER_TIME_SPECIFIED"
            and (
                broker_result.get("retcode") == 10022
                or "invalid expiration"
                in str(broker_result.get("comment") or "").strip().lower()
            )
        ):
            self._server_expiration_supported = False
            self._persist_short_expiration_support(
                False,
                reason="BROKER_REJECTED_SHORT_EXPIRATION",
            )
            self.journal.append(
                "ORDER_EXPIRATION_FALLBACK",
                {
                    "reason": "BROKER_REJECTED_SHORT_EXPIRATION",
                    "result": broker_result,
                    "pending_policy": pending_policy,
                },
            )
            fallback_request = dict(request)
            fallback_request["type_time"] = "ORDER_TIME_GTC"
            fallback_request.pop("expiration", None)
            expired_result = self._expired_pending_window_result(
                proposal,
                pending_policy,
                self._now_utc(),
                account_safety,
            )
            if expired_result is not None:
                result = {
                    **expired_result,
                    "request": fallback_request,
                    "order_check_result": order_check_result,
                    "expiration_fallback": True,
                }
                self.journal.append("ORDER_SKIPPED", result)
                return result
            fallback_submitted_at = self._timeline_now_utc()
            if callable(snapshot_func):
                fallback_snapshot = snapshot_func()
            else:
                fallback_snapshot = {"symbol": connection.get("symbol") or {}}
            fallback_quote = _safe_quote_snapshot(
                fallback_snapshot,
                fallback_submitted_at,
            )
            fallback_symbol_info = fallback_snapshot.get("symbol") or (
                connection.get("symbol") or {}
            )
            fallback_adjustment = None
            try:
                (
                    fallback_request,
                    fallback_adjustment,
                ) = self._rebuild_expiration_fallback_request(
                    proposal,
                    fallback_symbol_info,
                )
            except ValueError as exc:
                result = {
                    "status": "SKIPPED_INVALID_ENTRY",
                    "reason": (
                        "ENTRY_PRICE_STALE_OR_INVALID_AFTER_EXPIRATION_FALLBACK"
                    ),
                    "error": str(exc),
                    "proposal": proposal.model_dump(mode="json"),
                    "request": request,
                    "pending_policy": pending_policy,
                    "expiration_fallback": True,
                    "fallback_quote": fallback_quote,
                    "account_safety": account_safety,
                }
                self.journal.append("ORDER_SKIPPED", result)
                return result
            fallback_request["comment"] = ONE_MINUTE_POSITION_COMMENT
            fallback_request["type_time"] = "ORDER_TIME_GTC"
            fallback_request.pop("expiration", None)
            self.journal.append(
                "ORDER_EXPIRATION_FALLBACK_REBUILT",
                {
                    "reason": "REBUILT_WITH_LATEST_QUOTE",
                    "original_request": request,
                    "fallback_request": fallback_request,
                    "fallback_adjustment": fallback_adjustment,
                    "fallback_quote": fallback_quote,
                    "pending_policy": pending_policy,
                },
            )
            if callable(check_order):
                order_check_result = check_order(fallback_request)
                self.journal.append("ORDER_CHECKED", order_check_result)
                if order_check_result.get("ok") is False:
                    result = {
                        "status": "SKIPPED_ORDER_CHECK",
                        "reason": "ORDER_CHECK_FAILED_AFTER_EXPIRATION_FALLBACK",
                        "proposal": proposal.model_dump(mode="json"),
                        "request": fallback_request,
                        "order_check_result": order_check_result,
                        "pending_policy": pending_policy,
                        "expiration_fallback": True,
                        "account_safety": account_safety,
                    }
                    self.journal.append("ORDER_SKIPPED", result)
                    return result
            request = fallback_request
            broker_result = self.broker.place_pending_order(request)
            fallback_acknowledged_at = self._timeline_now_utc()
            execution_timeline = {
                "decision_quote": execution_timeline["decision_quote"],
                "pre_send_quote": fallback_quote,
                "submitted_at_utc": fallback_submitted_at.astimezone(
                    timezone.utc
                ).isoformat(),
                "acknowledged_at_utc": fallback_acknowledged_at.astimezone(
                    timezone.utc
                ).isoformat(),
                "attempt": 2,
                "previous_attempt": execution_timeline,
            }
            self.journal.append("ORDER_EXECUTION_TIMELINE", execution_timeline)
            submitted_at = fallback_submitted_at
            acknowledged_at = fallback_acknowledged_at
            expiration_fallback = True
        ok = bool(broker_result.get("ok"))
        event_type = "ORDER_PLACED" if ok else "ORDER_REJECTED"
        self.journal.append(event_type, broker_result)
        if ok:
            self.state.record_pending_order(
                broker_result["order"],
                proposal,
                placed_at_utc=submitted_at,
                cancel_after_utc=_parse_utc_datetime(
                    pending_policy["cancel_after_utc"]
                ),
                pending_policy=pending_policy,
                execution_timeline=execution_timeline,
            )
            if opening_context is not None:
                self.state.record_consumed_opening(
                    opening_context,
                    consumed_at_utc=acknowledged_at,
                    order_ticket=broker_result["order"],
                    execution_timeline=execution_timeline,
                )
                self.journal.append(
                    "OPENING_CONSUMED",
                    {
                        "opening_context": opening_context,
                        "consumed_at_utc": acknowledged_at.isoformat(),
                        "order": broker_result["order"],
                    },
                )

        return {
            "status": "PLACED" if ok else "REJECTED",
            "order": broker_result.get("order"),
            "broker_result": broker_result,
            "initial_order_check_result": initial_order_check_result,
            "order_check_result": order_check_result,
            "price_reprice": price_reprice,
            "pending_policy": pending_policy,
            "expiration_fallback": expiration_fallback,
            "execution_timeline": execution_timeline,
            "account_safety": account_safety,
        }

    def _account_safety(self, connection: dict[str, Any]) -> dict[str, Any]:
        return account_safety_from_connection(
            connection,
            require_demo=bool(getattr(self.config, "require_demo_account", True)),
        )

    def cancel_stale_pending_orders(
        self,
        now_utc: str | None = None,
    ) -> dict[str, Any]:
        """Cancel the tracked pending order after its activation window expires."""
        self.broker.connect()
        state = self.state.load()
        ticket = state.get("active_order_ticket")
        if ticket is None:
            result = {"status": "NO_ACTIVE_ORDER", "symbol": self.config.symbol}
            self.journal.append("ORDER_CANCEL_SKIPPED", result)
            return result
        ticket = int(ticket)
        sync_result = self._sync_tracked_ticket(ticket)
        if sync_result is not None:
            return sync_result

        invalidation = self._pending_opening_invalidation(state)
        if invalidation is not None:
            broker_result = self.broker.cancel_order(ticket)
            ok = bool(broker_result.get("ok"))
            if ok:
                self.state.clear_trade()
            result = {
                "status": "CANCELLED" if ok else "CANCEL_FAILED",
                "ticket": ticket,
                "reason": invalidation["reason"],
                "candle": invalidation["candle"],
                "proposal": state.get("proposal"),
                "result": broker_result,
            }
            self.journal.append(
                "ORDER_CANCELLED_OPENING_INVALIDATED"
                if ok
                else "ORDER_CANCEL_FAILED",
                result,
            )
            return result

        current = (
            datetime.fromisoformat(now_utc)
            if now_utc
            else datetime.now(timezone.utc)
        )
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        cancel_after = datetime.fromisoformat(state["cancel_after_utc"])
        if cancel_after.tzinfo is None:
            cancel_after = cancel_after.replace(tzinfo=timezone.utc)
        cancel_after = cancel_after.astimezone(timezone.utc)
        if current < cancel_after:
            result = {
                "status": "ORDER_STILL_ACTIVE",
                "ticket": ticket,
                "cancel_after_utc": cancel_after.isoformat(),
            }
            self.journal.append("ORDER_CANCEL_SKIPPED", result)
            return result

        broker_result = self.broker.cancel_order(ticket)
        ok = bool(broker_result.get("ok"))
        if ok:
            self.state.clear_trade()
        result = {
            "status": "CANCELLED" if ok else "CANCEL_FAILED",
            "ticket": ticket,
            "result": broker_result,
        }
        self.journal.append("ORDER_CANCELLED" if ok else "ORDER_CANCEL_FAILED", result)
        return result

    def cancel_all_pending_orders(
        self,
        *,
        reason: str = "RUNNER_DRAIN",
    ) -> dict[str, Any]:
        """Cancel every configured-symbol pending order during DEMO draining."""
        connection = self.broker.connect()
        account_safety = self._account_safety(connection)
        if not account_safety.get("passed") or account_safety.get("trade_mode") != "DEMO":
            raise ValueError("cancel-all draining requires a verified DEMO account")
        orders = self.broker.open_orders(self.config.symbol)
        actions = []
        for order in orders:
            ticket = int(order["ticket"])
            result = self.broker.cancel_order(ticket)
            actions.append({"ticket": ticket, "result": result})
        remaining = self.broker.open_orders(self.config.symbol)
        if not remaining:
            self.state.clear_trade()
        payload = {
            "status": "CANCELLED_ALL" if not remaining else "CANCEL_ALL_INCOMPLETE",
            "reason": reason,
            "actions": actions,
            "remaining_orders": remaining,
            "account_safety": account_safety,
        }
        self.journal.append("DRAIN_CANCEL_ALL_PENDING", payload)
        return payload

    def close_all_positions(
        self,
        *,
        reason: str = "RUNNER_DRAIN_DEADLINE",
    ) -> dict[str, Any]:
        """Close every configured-symbol position after the DEMO drain grace."""
        connection = self.broker.connect()
        account_safety = self._account_safety(connection)
        if not account_safety.get("passed") or account_safety.get("trade_mode") != "DEMO":
            raise ValueError("close-all draining requires a verified DEMO account")
        positions = self.broker.open_positions(self.config.symbol)
        actions = []
        for position in positions:
            result = self.broker.close_position(
                position,
                comment="TradingAgents experimental drain",
            )
            actions.append(
                {
                    "position": position.get("ticket"),
                    "result": result,
                }
            )
        remaining = self.broker.open_positions(self.config.symbol)
        if not remaining and not self.broker.open_orders(self.config.symbol):
            self.state.clear_trade()
        payload = {
            "status": "CLOSED_ALL" if not remaining else "CLOSE_ALL_INCOMPLETE",
            "reason": reason,
            "actions": actions,
            "remaining_positions": remaining,
            "account_safety": account_safety,
        }
        self.journal.append("DRAIN_CLOSE_ALL_POSITIONS", payload)
        return payload

    def _pending_opening_invalidation(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposal = state.get("proposal")
        if not isinstance(proposal, dict):
            return None
        if not self._one_minute_partial_scale_enabled(proposal):
            return None
        side = str(proposal.get("side") or "").strip().upper()
        if side not in {"BUY", "SELL"}:
            return None
        fetch_rates = getattr(self.broker, "fetch_closed_rates", None)
        if not callable(fetch_rates):
            return None
        try:
            candles = fetch_rates("1m", 3)
        except Exception as exc:  # pragma: no cover - defensive live guard
            self.journal.append(
                "PENDING_OPENING_INVALIDATION_CHECK_FAILED",
                {"reason": str(exc), "timeframe": "1m", "proposal": proposal},
            )
            return None
        ordered = sorted(
            (candle for candle in candles if isinstance(candle, dict)),
            key=lambda candle: str(candle.get("timestamp") or ""),
        )
        if not ordered:
            return None
        placed_at = _parse_utc_datetime(state.get("placed_at_utc"))
        if placed_at is None:
            return None
        invalidating_candle = None
        for candle in ordered:
            candle_time = _parse_utc_datetime(candle.get("timestamp"))
            if candle_time is None or candle_time <= placed_at:
                continue
            if self._closed_candle_rejects_side(candle, side):
                invalidating_candle = candle
                break
        if invalidating_candle is None:
            return None
        reason = (
            "OPENING_INVALIDATED_BEARISH_CANDLE"
            if side == "BUY"
            else "OPENING_INVALIDATED_BULLISH_CANDLE"
        )
        return {
            "reason": reason,
            "candle": {
                "timestamp": invalidating_candle.get("timestamp"),
                "open": _first_float(invalidating_candle, "open"),
                "high": _first_float(invalidating_candle, "high"),
                "low": _first_float(invalidating_candle, "low"),
                "close": _first_float(invalidating_candle, "close"),
                "timeframe": "1m",
            },
        }

    def manage_open_positions(
        self,
        break_even_threshold_pips: float | None = None,
        exit_management: MT5ExitManagementConfig | None = None,
    ) -> dict[str, Any]:
        """Manage active positions with scalp, early-loss, break-even, and trailing rules."""
        connection = self.broker.connect()
        account_safety = self._account_safety(connection)
        if not account_safety["passed"]:
            return {
                "status": "SKIPPED_ACCOUNT_SAFETY",
                "reason": "ACCOUNT_SAFETY_FAILED",
                "actions": [],
                "monitoring": [],
                "account_safety": account_safety,
            }
        positions = self.broker.open_positions(self.config.symbol)
        if not positions:
            state = self.state.load()
            if state.get("active_position_ticket") is not None:
                self._archive_active_position_telemetry(state)
                self.state.clear_trade()
        legacy_mode = break_even_threshold_pips is not None and exit_management is None
        management = exit_management or self.exit_management
        if legacy_mode:
            management = MT5ExitManagementConfig(
                break_even_trigger_points=float(break_even_threshold_pips) / 10.0,
                break_even_lock_points=0.0,
                trailing_trigger_points=0.0,
                trailing_distance_points=0.0,
                min_stop_update_points=0.0,
                early_loss_exit_points=0.0,
                scalp_profit_points=0.0,
                partial_first_trigger_points=0.0,
                partial_first_target_volume=0.0,
                partial_second_trigger_points=0.0,
                partial_second_target_volume=0.0,
            )
        if not management.enabled:
            return {
                "status": "NO_POSITION_ACTION",
                "actions": [],
                "monitoring": [],
                "account_safety": account_safety,
            }

        actions = []
        monitoring = []
        closed = False
        closed_scalp = False
        closed_rejection = False
        partial = False
        moved = False
        failed = False
        for position in positions:
            position_management = (
                management
                if legacy_mode or exit_management is not None
                else self._proposal_exit_management(management, position)
            )
            monitoring_snapshot = self._record_position_excursion(
                position,
                position_management,
                connection.get("symbol") or {},
            )
            if monitoring_snapshot is not None:
                monitoring.append(monitoring_snapshot)
            managed_action = self._manage_position(position, position_management)
            if managed_action is None:
                continue
            position_actions = (
                managed_action if isinstance(managed_action, list) else [managed_action]
            )
            for action in position_actions:
                if legacy_mode and action.get("management_action") == "MOVE_TO_BREAK_EVEN":
                    action = {**action, "action": "MOVE_TO_BREAK_EVEN"}
                actions.append(action)
                closed = closed or action.get("action") in {"CLOSE_POSITION", "FULL_CLOSE"}
                closed_scalp = closed_scalp or action.get("reason") == "SCALP_PROFIT_EXIT"
                closed_rejection = closed_rejection or action.get("reason") in {
                    "CANDLE_REJECTION_FULL_EXIT",
                    "CANDLE_REJECTION_FULL_EXIT_UNPROTECTED",
                }
                partial = partial or action.get("action") == "PARTIAL_CLOSE"
                moved = moved or action.get("action") == "MODIFY_STOP"
                failed = (
                    failed
                    or str(action.get("action") or "").endswith("_FAILED")
                    or bool(action.get("management_failed"))
                )

        if legacy_mode:
            status = "MANAGED" if actions else "NO_POSITION_ACTION"
        elif failed:
            status = "POSITION_MANAGEMENT_FAILED"
        elif partial:
            status = "POSITION_PARTIALLY_CLOSED"
        elif closed_rejection:
            status = "POSITION_CLOSED_REJECTION"
        elif closed_scalp:
            status = "POSITION_CLOSED_SCALP"
        elif closed:
            status = "POSITION_CLOSED_EARLY"
        elif moved:
            status = "POSITION_STOP_MOVED"
        else:
            status = "NO_POSITION_ACTION"
        return {
            "status": status,
            "actions": actions,
            "monitoring": monitoring,
            "account_safety": account_safety,
        }

    def _proposal_exit_management(
        self,
        management: MT5ExitManagementConfig,
        position: dict[str, Any],
    ) -> MT5ExitManagementConfig:
        state = self.state.load()
        if not self._state_matches_position(state, position):
            return management
        proposal = state.get("proposal") or {}
        fields = (
            "break_even_trigger_points",
            "break_even_lock_points",
            "trailing_trigger_points",
            "trailing_distance_points",
            "min_stop_update_points",
            "early_loss_exit_points",
            "scalp_profit_points",
            "partial_first_trigger_points",
            "partial_first_target_volume",
            "partial_second_trigger_points",
            "partial_second_target_volume",
            "intrabar_adverse_exit_fraction",
            "intrabar_adverse_confirmations",
        )
        overrides: dict[str, float] = {}
        for field in fields:
            if field not in proposal or proposal[field] is None:
                continue
            try:
                overrides[field] = float(proposal[field])
            except (TypeError, ValueError):
                continue
        if not overrides:
            return management
        values = {field: getattr(management, field) for field in fields}
        values.update(overrides)
        return MT5ExitManagementConfig(enabled=management.enabled, **values)

    def _manage_position(
        self,
        position: dict[str, Any],
        management: MT5ExitManagementConfig,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        side = str(position.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            return None
        entry = _first_float(position, "entry_price", "price_open")
        current = _first_float(position, "current_price", "price_current")
        if entry is None or current is None:
            return None

        favorable_points = current - entry if side == "BUY" else entry - current
        target = _first_float(position, "take_profit", "tp")
        stop = _first_float(position, "stop_loss", "sl")
        ticket = position.get("ticket")
        proposal = self.state.load().get("proposal") or {}
        one_minute_partial_scale = self._one_minute_partial_scale_enabled(
            proposal,
            position,
        )
        rejection_action = self._candle_rejection_action(position, side, management)
        if rejection_action is not None:
            return rejection_action

        partial_action = self._partial_close_action(
            position,
            side,
            entry,
            current,
            favorable_points,
            management,
            target,
            stop,
            ticket,
        )
        if partial_action is not None:
            return partial_action

        if (
            management.scalp_profit_points > 0
            and favorable_points >= management.scalp_profit_points
        ):
            close_result = self.broker.close_position(
                position,
                comment="TA scalp exit",
            )
            if not bool(close_result.get("ok")):
                action = {
                    "ticket": position.get("ticket"),
                    "action": "CLOSE_POSITION_FAILED",
                    "reason": "SCALP_PROFIT_EXIT_FAILED",
                    "favorable_points": round(favorable_points, 2),
                    "result": close_result,
                }
                self.journal.append("POSITION_CLOSE_FAILED", action)
                return action
            action = {
                "ticket": position.get("ticket"),
                "action": "CLOSE_POSITION",
                "reason": "SCALP_PROFIT_EXIT",
                "favorable_points": round(favorable_points, 2),
                "result": close_result,
            }
            self.journal.append("POSITION_CLOSED_SCALP", action)
            return action

        intrabar_action = self._intrabar_adverse_action(
            position,
            management,
            favorable_points,
        )
        if intrabar_action is not None:
            return intrabar_action

        if (
            management.early_loss_exit_points > 0
            and not one_minute_partial_scale
            and favorable_points <= -management.early_loss_exit_points
        ):
            close_result = self.broker.close_position(
                position,
                comment="TA early loss",
            )
            if not bool(close_result.get("ok")):
                action = {
                    "ticket": position.get("ticket"),
                    "action": "CLOSE_POSITION_FAILED",
                    "reason": "EARLY_LOSS_EXIT_FAILED",
                    "favorable_points": round(favorable_points, 2),
                    "result": close_result,
                }
                self.journal.append("POSITION_CLOSE_FAILED", action)
                return action
            action = {
                "ticket": position.get("ticket"),
                "action": "CLOSE_POSITION",
                "reason": "EARLY_LOSS_EXIT",
                "favorable_points": round(favorable_points, 2),
                "result": close_result,
            }
            self.journal.append("POSITION_CLOSED_EARLY", action)
            return action

        if target is None or stop is None or ticket in (None, ""):
            return None

        candidate, reason = _managed_stop_candidate(
            side,
            entry,
            current,
            favorable_points,
            management,
        )
        if candidate is None or reason is None:
            return None

        connection = self.broker.connect()
        symbol_info = connection["symbol"]
        rounded_stop = self.builder._round_price(candidate, symbol_info)
        rounded_target = self.builder._round_price(target, symbol_info)
        if not _is_valid_managed_stop(side, rounded_stop, current):
            return None
        improvement = _stop_improvement_points(side, rounded_stop, stop)
        if improvement <= 0 or improvement < management.min_stop_update_points:
            return None

        result = self.broker.modify_position_stops(
            int(ticket),
            rounded_stop,
            rounded_target,
        )
        if not bool(result.get("ok")):
            action = {
                "ticket": position.get("ticket"),
                "action": "MODIFY_STOP_FAILED",
                "reason": f"{reason}_FAILED",
                "stop_loss": rounded_stop,
                "take_profit": rounded_target,
                "favorable_points": round(favorable_points, 2),
                "result": result,
            }
            self.journal.append("POSITION_STOP_MOVE_FAILED", action)
            return action
        action_name = "MOVE_TO_BREAK_EVEN" if reason == "BREAK_EVEN" else "TRAIL_STOP"
        action = {
            "ticket": position.get("ticket"),
            "action": "MODIFY_STOP",
            "management_action": action_name,
            "reason": reason,
            "stop_loss": rounded_stop,
            "take_profit": rounded_target,
            "favorable_points": round(favorable_points, 2),
            "result": result,
        }
        self.journal.append("POSITION_STOP_MOVED", action)
        return action

    def _record_position_excursion(
        self,
        position: dict[str, Any],
        management: MT5ExitManagementConfig,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any] | None:
        side = str(position.get("side") or "").upper()
        entry = _first_float(position, "entry_price", "price_open")
        current = _first_float(position, "current_price", "price_current")
        position_key = self._position_state_key(position)
        if side not in {"BUY", "SELL"} or entry is None or current is None:
            return None
        if position_key is None:
            return None

        favorable_points = current - entry if side == "BUY" else entry - current
        bid = _first_float(symbol_info, "bid")
        ask = _first_float(symbol_info, "ask")
        spread_points = (
            max(0.0, ask - bid)
            if bid is not None and ask is not None
            else 0.0
        )

        state = self.state.load()
        proposal = state.get("proposal") or {}
        one_minute_lifecycle = self._one_minute_partial_scale_enabled(
            proposal,
            position,
        )
        proposal_entry = _first_float(proposal, "entry_price")
        proposal_stop = _first_float(proposal, "stop_loss")
        if (
            one_minute_lifecycle
            and self._state_matches_position(state, position)
            and proposal_entry is not None
            and proposal_stop is not None
        ):
            initial_risk_points = abs(proposal_entry - proposal_stop)
        else:
            position_stop = _first_float(position, "stop_loss", "sl")
            initial_risk_points = (
                abs(entry - position_stop) if position_stop is not None else 0.0
            )
        adverse_threshold = (
            initial_risk_points * management.intrabar_adverse_exit_fraction
            if one_minute_lifecycle
            else 0.0
        )

        excursion_state = state.setdefault("position_excursion_state", {})
        first_observations = state.setdefault(
            "position_first_observation",
            {},
        )
        first_observation = first_observations.get(position_key)
        if not isinstance(first_observation, dict):
            observed_at = self._timeline_now_utc()
            opened_at = _parse_utc_datetime(position.get("opened_at_utc"))
            first_observation = {
                "position_id": position_key,
                "opened_at_utc": (
                    opened_at.isoformat() if opened_at is not None else None
                ),
                "entry_price": entry,
                "observed_at_utc": observed_at.isoformat(),
                "quote": _safe_quote_snapshot(
                    {"symbol": symbol_info},
                    observed_at,
                ),
                "fill_to_observation_seconds": (
                    round((observed_at - opened_at).total_seconds(), 4)
                    if opened_at is not None
                    else None
                ),
            }
            first_observations[position_key] = first_observation
            self.journal.append(
                "POSITION_FIRST_OBSERVED",
                first_observation,
            )
        previous = dict(excursion_state.get(position_key) or {})
        previous_mfe = float(previous.get("mfe_points", 0.0))
        previous_mae = float(previous.get("mae_points", 0.0))
        observations = int(previous.get("intrabar_adverse_observations", 0))
        if adverse_threshold > 0 and favorable_points <= -adverse_threshold:
            observations += 1
        else:
            observations = 0

        snapshot = {
            "ticket": position.get("ticket"),
            "side": side,
            "favorable_points": round(favorable_points, 4),
            "mfe_points": round(max(0.0, previous_mfe, favorable_points), 4),
            "mae_points": round(min(0.0, previous_mae, favorable_points), 4),
            "spread_points": round(spread_points, 4),
            "break_even_trigger_points": management.break_even_trigger_points,
            "partial_first_trigger_points": management.partial_first_trigger_points,
            "scalp_profit_points": management.scalp_profit_points,
            "initial_risk_points": round(initial_risk_points, 4),
            "intrabar_adverse_threshold_points": round(adverse_threshold, 4),
            "intrabar_adverse_observations": observations,
            "intrabar_adverse_confirmations": management.intrabar_adverse_confirmations,
            "one_minute_lifecycle": one_minute_lifecycle,
        }
        excursion_state[position_key] = dict(snapshot)
        self.state.save(state)
        self.journal.append("POSITION_MONITORED", snapshot)
        return snapshot

    def _archive_active_position_telemetry(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        position_id = state.get("active_position_ticket")
        if position_id in (None, ""):
            return None
        key = str(position_id)
        telemetry = {
            "position_id": key,
            "placed_at_utc": state.get("placed_at_utc"),
            "proposal": state.get("proposal"),
            "execution_timeline": state.get("execution_timeline"),
            "position_first_observation": (
                (state.get("position_first_observation") or {}).get(key)
            ),
            "position_excursion": (
                (state.get("position_excursion_state") or {}).get(key)
            ),
            "archived_at_utc": self._timeline_now_utc().isoformat(),
        }
        self.state.archive_position_telemetry(key, telemetry)
        self.journal.append("POSITION_EXCURSION_ARCHIVED", telemetry)
        return telemetry

    def _intrabar_adverse_action(
        self,
        position: dict[str, Any],
        management: MT5ExitManagementConfig,
        favorable_points: float,
    ) -> dict[str, Any] | None:
        state = self.state.load()
        proposal = state.get("proposal") or {}
        if not self._one_minute_partial_scale_enabled(proposal, position):
            return None
        position_key = self._position_state_key(position)
        if position_key is None:
            return None
        monitoring = (
            state.get("position_excursion_state", {}).get(position_key) or {}
        )
        observations = int(monitoring.get("intrabar_adverse_observations", 0))
        threshold = float(
            monitoring.get("intrabar_adverse_threshold_points", 0.0)
        )
        if (
            threshold <= 0
            or observations < management.intrabar_adverse_confirmations
        ):
            return None

        close_result = self.broker.close_position(
            position,
            comment="TA intrabar adverse",
        )
        if not bool(close_result.get("ok")):
            reconciled = self._reconcile_failed_close_race(
                position,
                close_result,
                requested_action="INTRABAR_ADVERSE_EXIT",
            )
            if reconciled is not None:
                return reconciled
            action = {
                "ticket": position.get("ticket"),
                "action": "CLOSE_POSITION_FAILED",
                "reason": "INTRABAR_ADVERSE_EXIT_FAILED",
                "favorable_points": round(favorable_points, 2),
                "intrabar_adverse_threshold_points": threshold,
                "intrabar_adverse_observations": observations,
                "result": close_result,
            }
            self.journal.append("POSITION_CLOSE_FAILED", action)
            return action
        action = {
            "ticket": position.get("ticket"),
            "action": "CLOSE_POSITION",
            "reason": "INTRABAR_ADVERSE_EXIT",
            "favorable_points": round(favorable_points, 2),
            "intrabar_adverse_threshold_points": threshold,
            "intrabar_adverse_observations": observations,
            "result": close_result,
        }
        self.journal.append("POSITION_CLOSED_INTRABAR", action)
        return action

    @staticmethod
    def _position_identity_values(position: dict[str, Any]) -> set[str]:
        return {
            str(value)
            for value in (
                position.get("identifier"),
                position.get("position_id"),
                position.get("ticket"),
            )
            if value not in (None, "")
        }

    @staticmethod
    def _is_close_race_response(result: dict[str, Any]) -> bool:
        comment = str(result.get("comment") or "").strip().lower()
        return bool(
            result.get("retcode") in {10013, 10036}
            or "position doesn't exist" in comment
            or "position does not exist" in comment
            or "invalid request" in comment
        )

    def _reconcile_failed_close_race(
        self,
        position: dict[str, Any],
        close_result: dict[str, Any],
        *,
        requested_action: str,
    ) -> dict[str, Any] | None:
        if not self._is_close_race_response(close_result):
            return None
        target_ids = self._position_identity_values(position)
        refreshed = self.broker.open_positions(self.config.symbol)
        still_open = any(
            target_ids & self._position_identity_values(candidate)
            for candidate in refreshed
        )
        if still_open:
            return None
        action = {
            "ticket": position.get("ticket"),
            "action": "NO_ACTION",
            "reason": "POSITION_ALREADY_CLOSED",
            "requested_action": requested_action,
            "result": close_result,
        }
        self.journal.append("POSITION_CLOSE_RECONCILED", action)
        return action

    def _candle_rejection_action(
        self,
        position: dict[str, Any],
        side: str,
        management: MT5ExitManagementConfig,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        if not management.candle_rejection_exit_enabled:
            return None
        state = self.state.load()
        proposal = state.get("proposal") or {}
        if not self._one_minute_partial_scale_enabled(proposal, position):
            return None

        candle = self._latest_rejection_candle(side, management, state, position)
        if candle is None:
            return None

        position_key = self._position_state_key(position)
        if position_key is None:
            return None
        candle_timestamp = str(candle["timestamp"])
        rejection_state = state.setdefault("rejection_exit_state", {})
        position_state = dict(rejection_state.get(position_key) or {})
        if position_state.get("last_candle_timestamp") == candle_timestamp:
            return None

        volume = _first_float(position, "volume", "volume_current")
        if volume is None or volume <= 0:
            return None
        entry = _first_float(position, "entry_price", "price_open")
        current = _first_float(position, "current_price", "price_current")
        if entry is None or current is None:
            return None
        favorable_points = current - entry if side == "BUY" else entry - current

        if position_state.get("stage") == "PARTIAL":
            close_result = self.broker.close_position(
                position,
                comment="TA candle rejection exit",
            )
            if not bool(close_result.get("ok")):
                reconciled = self._reconcile_failed_close_race(
                    position,
                    close_result,
                    requested_action="CANDLE_REJECTION_FULL_EXIT",
                )
                if reconciled is not None:
                    return reconciled
                action = {
                    "ticket": position.get("ticket"),
                    "action": "CLOSE_POSITION_FAILED",
                    "reason": "CANDLE_REJECTION_FULL_EXIT_FAILED",
                    "candle": candle,
                    "result": close_result,
                }
                self.journal.append("POSITION_CLOSE_FAILED", action)
                return action
            position_state.update(
                {
                    "stage": "CLOSED",
                    "last_candle_timestamp": candle_timestamp,
                    "side": side,
                }
            )
            rejection_state[position_key] = position_state
            self.state.save(state)
            action = {
                "ticket": position.get("ticket"),
                "action": "CLOSE_POSITION",
                "reason": "CANDLE_REJECTION_FULL_EXIT",
                "candle": candle,
                "result": close_result,
            }
            self.journal.append("POSITION_CLOSED_REJECTION", action)
            return action

        if favorable_points <= 0:
            close_result = self.broker.close_position(
                position,
                comment="TA candle rejection full",
            )
            if not bool(close_result.get("ok")):
                reconciled = self._reconcile_failed_close_race(
                    position,
                    close_result,
                    requested_action="CANDLE_REJECTION_FULL_EXIT_UNPROTECTED",
                )
                if reconciled is not None:
                    return reconciled
                action = {
                    "ticket": position.get("ticket"),
                    "action": "CLOSE_POSITION_FAILED",
                    "reason": "CANDLE_REJECTION_FULL_EXIT_FAILED",
                    "favorable_points": round(favorable_points, 2),
                    "candle": candle,
                    "result": close_result,
                }
                self.journal.append("POSITION_CLOSE_FAILED", action)
                return action
            position_state.update(
                {
                    "stage": "CLOSED",
                    "last_candle_timestamp": candle_timestamp,
                    "side": side,
                }
            )
            rejection_state[position_key] = position_state
            self.state.save(state)
            action = {
                "ticket": position.get("ticket"),
                "action": "FULL_CLOSE",
                "reason": "CANDLE_REJECTION_FULL_EXIT_UNPROTECTED",
                "favorable_points": round(favorable_points, 2),
                "candle": candle,
                "result": close_result,
            }
            self.journal.append("POSITION_CLOSED_REJECTION", action)
            return action

        close_volume = round(volume * management.candle_rejection_partial_fraction, 8)
        if close_volume <= 0:
            return None
        if close_volume >= volume:
            close_volume = volume
        close_result = self.broker.close_position(
            position,
            comment="TA candle rejection partial",
            volume=close_volume,
        )
        if not bool(close_result.get("ok")):
            action = {
                "ticket": position.get("ticket"),
                "action": "PARTIAL_CLOSE_FAILED",
                "reason": "CANDLE_REJECTION_PARTIAL_EXIT_FAILED",
                "closed_volume": 0.0,
                "requested_close_volume": close_volume,
                "favorable_points": round(favorable_points, 2),
                "candle": candle,
                "result": close_result,
            }
            self.journal.append("POSITION_PARTIAL_CLOSE_FAILED", action)
            return action
        position_state.update(
            {
                "stage": "PARTIAL",
                "last_candle_timestamp": candle_timestamp,
                "side": side,
                "closed_volume": close_volume,
            }
        )
        rejection_state[position_key] = position_state
        self.state.save(state)
        action = {
            "ticket": position.get("ticket"),
            "action": "PARTIAL_CLOSE",
            "reason": "CANDLE_REJECTION_PARTIAL_EXIT",
            "closed_volume": close_volume,
            "remaining_volume": round(volume - close_volume, 8),
            "favorable_points": round(favorable_points, 2),
            "candle": candle,
            "result": close_result,
        }
        self.journal.append("POSITION_PARTIALLY_CLOSED", action)
        protect_action = self._protect_rejection_remainder(
            position,
            side,
            entry,
            current,
            management,
        )
        if protect_action is None:
            return action
        return [action, protect_action]

    def _protect_rejection_remainder(
        self,
        position: dict[str, Any],
        side: str,
        entry: float,
        current: float,
        management: MT5ExitManagementConfig,
    ) -> dict[str, Any] | None:
        target = _first_float(position, "take_profit", "tp")
        stop = _first_float(position, "stop_loss", "sl")
        ticket = position.get("ticket")
        if target is None or stop is None or ticket in (None, ""):
            return None
        candidate = (
            entry + management.break_even_lock_points
            if side == "BUY"
            else entry - management.break_even_lock_points
        )
        connection = self.broker.connect()
        symbol_info = connection["symbol"]
        rounded_stop = self.builder._round_price(candidate, symbol_info)
        rounded_target = self.builder._round_price(target, symbol_info)
        if not _is_valid_managed_stop(side, rounded_stop, current):
            return None
        improvement = _stop_improvement_points(side, rounded_stop, stop)
        if improvement <= 0:
            return None
        result = self.broker.modify_position_stops(
            int(ticket),
            rounded_stop,
            rounded_target,
        )
        if not bool(result.get("ok")):
            action = {
                "ticket": position.get("ticket"),
                "action": "MODIFY_STOP_FAILED",
                "reason": "CANDLE_REJECTION_PROTECTION_FAILED",
                "stop_loss": rounded_stop,
                "take_profit": rounded_target,
                "result": result,
            }
            self.journal.append("POSITION_STOP_MOVE_FAILED", action)
            return action
        action = {
            "ticket": position.get("ticket"),
            "action": "MODIFY_STOP",
            "reason": "CANDLE_REJECTION_PROTECT_REMAINDER",
            "stop_loss": rounded_stop,
            "take_profit": rounded_target,
            "result": result,
        }
        self.journal.append("POSITION_STOP_MOVED", action)
        return action

    def _latest_rejection_candle(
        self,
        side: str,
        management: MT5ExitManagementConfig,
        state: dict[str, Any],
        position: dict[str, Any],
    ) -> dict[str, Any] | None:
        fetch_rates = getattr(self.broker, "fetch_closed_rates", None)
        if not callable(fetch_rates):
            return None
        try:
            candles = fetch_rates(management.candle_rejection_timeframe, 3)
        except Exception as exc:  # pragma: no cover - defensive live guard
            self.journal.append(
                "CANDLE_REJECTION_CHECK_FAILED",
                {"reason": str(exc), "timeframe": management.candle_rejection_timeframe},
            )
            return None
        ordered = sorted(
            (candle for candle in candles if isinstance(candle, dict)),
            key=lambda candle: str(candle.get("timestamp") or ""),
        )
        if not ordered:
            return None
        latest = ordered[-1]
        candle_time = _parse_utc_datetime(latest.get("timestamp"))
        candle_duration = _timeframe_duration(management.candle_rejection_timeframe)
        position_opened_at = _parse_utc_datetime(position.get("opened_at_utc"))
        lifecycle_started_at = position_opened_at or _parse_utc_datetime(
            state.get("placed_at_utc")
        )
        if (
            candle_time is None
            or candle_duration is None
            or lifecycle_started_at is None
        ):
            return None
        candle_closed_at = candle_time + candle_duration
        if candle_closed_at <= lifecycle_started_at:
            return None
        if not self._closed_candle_rejects_side(latest, side):
            return None
        return {
            "timestamp": latest.get("timestamp"),
            "closed_at_utc": candle_closed_at.isoformat(),
            "open": _first_float(latest, "open"),
            "high": _first_float(latest, "high"),
            "low": _first_float(latest, "low"),
            "close": _first_float(latest, "close"),
            "timeframe": management.candle_rejection_timeframe,
        }

    @staticmethod
    def _closed_candle_rejects_side(candle: dict[str, Any], side: str) -> bool:
        open_price = _first_float(candle, "open")
        close_price = _first_float(candle, "close")
        if open_price is None or close_price is None or close_price == open_price:
            return False
        if side == "SELL":
            return close_price > open_price
        if side == "BUY":
            return close_price < open_price
        return False

    @staticmethod
    def _position_state_key(position: dict[str, Any]) -> str | None:
        value = (
            position.get("identifier")
            or position.get("position_id")
            or position.get("ticket")
        )
        if value in (None, ""):
            return None
        return str(value)

    def _one_minute_partial_scale_enabled(
        self,
        proposal: dict[str, Any],
        position: dict[str, Any] | None = None,
    ) -> bool:
        timeframe = str(proposal.get("timeframe") or "").strip().lower()
        lifecycle = str(proposal.get("position_lifecycle") or "").strip().upper()
        proposal_matches = timeframe == "1m" and lifecycle == "FAST_PARTIAL_SCALE"
        broker_comment = str((position or {}).get("comment") or "").strip()
        if broker_comment == ONE_MINUTE_POSITION_COMMENT:
            return True
        if not proposal_matches:
            return False
        if position is None:
            return True
        return self._state_matches_position(self.state.load(), position)

    @staticmethod
    def _state_matches_position(
        state: dict[str, Any],
        position: dict[str, Any],
    ) -> bool:
        position_ticket = position.get("ticket")
        if position_ticket in (None, ""):
            return False
        try:
            normalized_ticket = int(position_ticket)
        except (TypeError, ValueError):
            return False
        for field in ("active_position_ticket", "active_order_ticket"):
            tracked = state.get(field)
            if tracked in (None, ""):
                continue
            try:
                if int(tracked) == normalized_ticket:
                    return True
            except (TypeError, ValueError):
                continue
        is_legacy_state = "active_position_ticket" not in state
        has_no_broker_comment = not str(position.get("comment") or "").strip()
        return is_legacy_state and has_no_broker_comment

    def _partial_close_action(
        self,
        position: dict[str, Any],
        side: str,
        entry: float,
        current: float,
        favorable_points: float,
        management: MT5ExitManagementConfig,
        target: float | None,
        stop: float | None,
        ticket: Any,
    ) -> dict[str, Any] | None:
        if not self._partial_scale_lifecycle_enabled(position):
            return None
        volume = _first_float(position, "volume", "volume_current")
        if volume is None:
            return None
        state = self.state.load()
        position_key = self._position_state_key(position)
        partial_state = state.setdefault("partial_close_state", {})
        position_state = dict(partial_state.get(position_key) or {})
        completed_stages = set(position_state.get("completed_stages") or [])

        stages = (
            (
                management.partial_first_trigger_points,
                management.partial_first_target_volume,
                "TA partial 1",
                "PARTIAL_1_AND_BREAK_EVEN",
                True,
            ),
            (
                management.partial_second_trigger_points,
                management.partial_second_target_volume,
                "TA partial 2",
                "PARTIAL_2_AND_TRAIL",
                False,
            ),
        )
        for trigger_points, target_volume, comment, reason, is_first_stage in stages:
            if reason in completed_stages:
                continue
            if trigger_points <= 0 or target_volume <= 0:
                continue
            effective_target_volume = target_volume
            if is_first_stage and volume <= target_volume:
                if not math.isclose(volume, target_volume, abs_tol=1e-8):
                    continue
                stop_is_protected = stop is not None and (
                    (side == "BUY" and stop >= entry)
                    or (side == "SELL" and stop <= entry)
                )
                if stop_is_protected:
                    continue
                effective_target_volume = round(volume * 0.5, 8)
            if (
                favorable_points < trigger_points
                or effective_target_volume <= 0
                or volume <= effective_target_volume
            ):
                continue

            close_volume = round(volume - effective_target_volume, 8)
            if close_volume <= 0:
                continue
            close_result = self.broker.close_position(
                position,
                comment=comment,
                volume=close_volume,
            )
            if not bool(close_result.get("ok")):
                reconciled = self._reconcile_failed_close_race(
                    position,
                    close_result,
                    requested_action=reason,
                )
                if reconciled is not None:
                    return reconciled
                action = {
                    "ticket": position.get("ticket"),
                    "action": "PARTIAL_CLOSE_FAILED",
                    "reason": f"{reason}_FAILED",
                    "closed_volume": 0.0,
                    "requested_close_volume": close_volume,
                    "remaining_volume": volume,
                    "favorable_points": round(favorable_points, 2),
                    "result": close_result,
                }
                self.journal.append("POSITION_PARTIAL_CLOSE_FAILED", action)
                return action
            if position_key is not None:
                completed_stages.add(reason)
                position_state.update(
                    {
                        "completed_stages": sorted(completed_stages),
                        "last_closed_volume": close_volume,
                        "last_remaining_volume": effective_target_volume,
                    }
                )
                partial_state[position_key] = position_state
                self.state.save(state)
            action = {
                "ticket": position.get("ticket"),
                "action": "PARTIAL_CLOSE",
                "reason": reason,
                "closed_volume": close_volume,
                "remaining_volume": effective_target_volume,
                "favorable_points": round(favorable_points, 2),
                "result": close_result,
            }
            stop_result = self._move_stop_after_partial(
                side,
                entry,
                current,
                favorable_points,
                management,
                target,
                stop,
                ticket,
            )
            if stop_result is not None:
                action.update(stop_result)
            self.journal.append("POSITION_PARTIALLY_CLOSED", action)
            return action
        return None

    def _partial_scale_lifecycle_enabled(self, position: dict[str, Any]) -> bool:
        proposal = self.state.load().get("proposal") or {}
        return self._one_minute_partial_scale_enabled(proposal, position)

    def _move_stop_after_partial(
        self,
        side: str,
        entry: float,
        current: float,
        favorable_points: float,
        management: MT5ExitManagementConfig,
        target: float | None,
        stop: float | None,
        ticket: Any,
    ) -> dict[str, Any] | None:
        if target is None or stop is None or ticket in (None, ""):
            return None
        candidate, stop_reason = _managed_stop_candidate(
            side,
            entry,
            current,
            favorable_points,
            management,
        )
        if candidate is None or stop_reason is None:
            return None

        connection = self.broker.connect()
        symbol_info = connection["symbol"]
        rounded_stop = self.builder._round_price(candidate, symbol_info)
        rounded_target = self.builder._round_price(target, symbol_info)
        if not _is_valid_managed_stop(side, rounded_stop, current):
            return None
        improvement = _stop_improvement_points(side, rounded_stop, stop)
        if improvement <= 0 or improvement < management.min_stop_update_points:
            return None

        result = self.broker.modify_position_stops(
            int(ticket),
            rounded_stop,
            rounded_target,
        )
        if not bool(result.get("ok")):
            failure = {
                "ticket": ticket,
                "action": "MODIFY_STOP_FAILED",
                "reason": f"{stop_reason}_FAILED",
                "stop_loss": rounded_stop,
                "take_profit": rounded_target,
                "result": result,
            }
            self.journal.append("POSITION_STOP_MOVE_FAILED", failure)
            return {
                "stop_management_action": "MODIFY_STOP_FAILED",
                "stop_reason": f"{stop_reason}_FAILED",
                "stop_loss": rounded_stop,
                "take_profit": rounded_target,
                "stop_result": result,
                "management_failed": True,
            }
        return {
            "stop_management_action": (
                "MOVE_TO_BREAK_EVEN"
                if stop_reason == "BREAK_EVEN"
                else "TRAIL_STOP"
            ),
            "stop_reason": stop_reason,
            "stop_loss": rounded_stop,
            "take_profit": rounded_target,
            "stop_result": result,
        }

    def reconcile_trade_history(
        self,
        *,
        lookback_hours: int = 24,
        since_utc: datetime | str | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Summarize recently filled and closed MT5 deals for this bot."""
        self.broker.connect()
        current = now_utc or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        if since_utc is None:
            start = current - timedelta(hours=int(lookback_hours))
        elif isinstance(since_utc, str):
            start = datetime.fromisoformat(since_utc)
        else:
            start = since_utc
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        start = start.astimezone(timezone.utc)
        deals = self.broker.history_deals(self.config.symbol, start, current)
        result = self._summarize_trade_history(deals, start, current)
        self.journal.append("TRADE_HISTORY_RECONCILED", result)
        return result

    def _summarize_trade_history(
        self,
        deals: list[dict[str, Any]],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[str, Any]:
        bot_position_ids = {
            self._deal_position_id(deal)
            for deal in deals
            if self._is_bot_entry_deal(deal)
        }
        bot_position_ids.discard(None)

        grouped: dict[int, list[dict[str, Any]]] = {}
        for deal in deals:
            position_id = self._deal_position_id(deal)
            if position_id in bot_position_ids:
                grouped.setdefault(position_id, []).append(deal)

        filled_trades = []
        closed_trades = []
        for position_id, position_deals in grouped.items():
            ordered = sorted(position_deals, key=self._deal_sort_key)
            entry_deal = next(
                (deal for deal in ordered if self._is_entry_deal(deal)),
                ordered[0],
            )
            exit_deals = [deal for deal in ordered if self._is_exit_deal(deal)]
            filled_trades.append(self._trade_fill_summary(position_id, entry_deal))
            if exit_deals:
                closed_trades.append(
                    self._closed_trade_summary(position_id, entry_deal, exit_deals)
                )

        net_profit = round(
            sum(float(trade.get("profit") or 0.0) for trade in closed_trades),
            2,
        )
        wins = sum(1 for trade in closed_trades if float(trade["profit"]) > 0)
        losses = sum(1 for trade in closed_trades if float(trade["profit"]) < 0)
        break_even = len(closed_trades) - wins - losses

        return {
            "status": "RECONCILED",
            "symbol": self.config.symbol,
            "lookback_start_utc": start_utc.isoformat(),
            "lookback_end_utc": end_utc.isoformat(),
            "deal_count": len(deals),
            "filled_trade_count": len(filled_trades),
            "closed_trade_count": len(closed_trades),
            "wins": wins,
            "losses": losses,
            "break_even": break_even,
            "net_profit": net_profit,
            "filled_trades": filled_trades,
            "closed_trades": closed_trades,
            "latest_closed_trade": closed_trades[-1] if closed_trades else {},
        }

    def _is_bot_entry_deal(self, deal: dict[str, Any]) -> bool:
        if not self._is_entry_deal(deal):
            return False
        if self._deal_int(deal.get("magic")) == int(self.config.magic):
            return True
        comment = str(deal.get("comment") or "")
        return bool(self.config.order_comment and self.config.order_comment in comment)

    @staticmethod
    def _deal_position_id(deal: dict[str, Any]) -> int | None:
        value = deal.get("position_id") or deal.get("position") or deal.get("order")
        try:
            position_id = int(value)
        except (TypeError, ValueError):
            return None
        return position_id if position_id > 0 else None

    @staticmethod
    def _deal_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _deal_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _is_entry_deal(cls, deal: dict[str, Any]) -> bool:
        value = str(deal.get("entry", "")).upper()
        return value in {"0", "IN", "DEAL_ENTRY_IN"}

    @classmethod
    def _is_exit_deal(cls, deal: dict[str, Any]) -> bool:
        value = str(deal.get("entry", "")).upper()
        return value in {"1", "OUT", "DEAL_ENTRY_OUT"}

    @classmethod
    def _deal_sort_key(cls, deal: dict[str, Any]) -> tuple[int, int]:
        return (
            cls._deal_int(deal.get("time")) or 0,
            cls._deal_int(deal.get("ticket")) or 0,
        )

    @classmethod
    def _deal_time_utc(cls, deal: dict[str, Any]) -> str | None:
        normalized = deal.get("time_utc")
        if normalized:
            return str(normalized)
        timestamp = cls._deal_int(deal.get("time"))
        if timestamp is None:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    @classmethod
    def _deal_side(cls, deal: dict[str, Any]) -> str | None:
        value = str(deal.get("type", "")).upper()
        if value in {"0", "BUY", "DEAL_TYPE_BUY"}:
            return "BUY"
        if value in {"1", "SELL", "DEAL_TYPE_SELL"}:
            return "SELL"
        return None

    def _trade_fill_summary(
        self,
        position_id: int,
        entry_deal: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "position_id": position_id,
            "entry_deal_ticket": self._deal_int(entry_deal.get("ticket")),
            "entry_order": self._deal_int(entry_deal.get("order")),
            "side": self._deal_side(entry_deal),
            "volume": self._deal_float(entry_deal.get("volume")),
            "entry_price": self._deal_float(entry_deal.get("price")),
            "opened_at_utc": self._deal_time_utc(entry_deal),
        }

    def _closed_trade_summary(
        self,
        position_id: int,
        entry_deal: dict[str, Any],
        exit_deals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        last_exit = sorted(exit_deals, key=self._deal_sort_key)[-1]
        all_deals = [entry_deal, *exit_deals]
        profit = round(
            sum(
                self._deal_float(deal.get("profit"))
                + self._deal_float(deal.get("commission"))
                + self._deal_float(deal.get("swap"))
                for deal in all_deals
            ),
            2,
        )
        summary = {
            **self._trade_fill_summary(position_id, entry_deal),
            "exit_deal_ticket": self._deal_int(last_exit.get("ticket")),
            "exit_order": self._deal_int(last_exit.get("order")),
            "exit_price": self._deal_float(last_exit.get("price")),
            "closed_at_utc": self._deal_time_utc(last_exit),
            "profit": profit,
            "outcome": self._deal_outcome(last_exit, profit),
            "exit_comment": last_exit.get("comment"),
        }
        completed = (
            self.state.load().get("completed_position_telemetry") or {}
        ).get(str(position_id))
        if not isinstance(completed, dict):
            return summary

        reconciled_close = self._reconcile_closed_timestamp(
            summary.get("closed_at_utc"),
            completed.get("archived_at_utc"),
        )
        if reconciled_close is not None:
            summary["broker_closed_at_utc"] = summary["closed_at_utc"]
            summary["closed_at_utc"] = reconciled_close
            summary["closed_time_source"] = "position_archive_reconciliation"
        else:
            summary["closed_time_source"] = "broker_history"

        excursion = completed.get("position_excursion") or {}
        sampled_mfe = self._deal_float(excursion.get("mfe_points"))
        sampled_mae = self._deal_float(excursion.get("mae_points"))
        entry_price = summary["entry_price"]
        exit_price = summary["exit_price"]
        side = summary.get("side")
        exit_movement = (
            exit_price - entry_price
            if side == "BUY"
            else entry_price - exit_price
        )
        summary.update(
            {
                "mfe_points": round(max(0.0, sampled_mfe, exit_movement), 4),
                "mae_points": round(min(0.0, sampled_mae, exit_movement), 4),
                "excursion_source": "one_second_samples_plus_exit",
                "first_position_observation": completed.get(
                    "position_first_observation"
                ),
                "execution_timeline": completed.get("execution_timeline"),
            }
        )
        proposal = completed.get("proposal") or {}
        for key in (
            "setup_name",
            "strategy_type",
            "trigger_name",
            "reaction_type",
            "confirmation_type",
        ):
            value = proposal.get(key)
            if value not in (None, ""):
                summary[key] = value
        proposed_entry = _first_float(proposal, "entry_price")
        if proposed_entry is not None:
            summary["entry_drift"] = round(
                (entry_price - proposed_entry)
                * (1.0 if side == "BUY" else -1.0),
                4,
            )
        timeline = completed.get("execution_timeline") or {}
        submitted_at = _parse_utc_datetime(timeline.get("submitted_at_utc"))
        opened_at = _parse_utc_datetime(summary.get("opened_at_utc"))
        if submitted_at is not None and opened_at is not None:
            summary["order_wait_seconds"] = round(
                (opened_at - submitted_at).total_seconds(),
                4,
            )
        return summary

    @staticmethod
    def _reconcile_closed_timestamp(
        broker_closed_at_utc: Any,
        archived_at_utc: Any,
    ) -> str | None:
        """Correct an impossible future deal time using durable close telemetry.

        Some MT5 terminals expose deal-history timestamps in broker-local time
        while ticks are already UTC.  An archival observation necessarily occurs
        after a position has disappeared, so a broker close recorded more than
        one minute *after* that observation cannot be chronological truth.
        """
        broker_closed = _parse_utc_datetime(broker_closed_at_utc)
        archived = _parse_utc_datetime(archived_at_utc)
        if (
            broker_closed is None
            or archived is None
            or broker_closed <= archived + timedelta(minutes=1)
        ):
            return None
        return archived.isoformat()

    @staticmethod
    def _deal_outcome(exit_deal: dict[str, Any], profit: float) -> str:
        comment = str(exit_deal.get("comment") or "").lower()
        if "[tp" in comment or "tp " in comment:
            return "TP"
        if "[sl" in comment or "sl " in comment:
            return "SL"
        if profit > 0:
            return "PROFIT"
        if profit < 0:
            return "LOSS"
        return "BREAK_EVEN"

    def snapshot_state(self) -> dict[str, Any]:
        """Read current broker orders and positions without placing orders."""
        connection = self.broker.connect()
        account_safety = self._account_safety(connection)
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        state = {
            "connection": self._safe_connection_status(connection, account_safety),
            "account_safety": account_safety,
            "orders": orders,
            "positions": positions,
        }
        self.journal.append("STATE_SNAPSHOT", state)
        return state


def _managed_stop_candidate(
    side: str,
    entry: float,
    current: float,
    favorable_points: float,
    management: MT5ExitManagementConfig,
) -> tuple[float | None, str | None]:
    candidate = None
    reason = None
    if (
        management.break_even_trigger_points > 0
        and favorable_points >= management.break_even_trigger_points
    ):
        candidate = (
            entry + management.break_even_lock_points
            if side == "BUY"
            else entry - management.break_even_lock_points
        )
        reason = "BREAK_EVEN"
    if (
        management.trailing_trigger_points > 0
        and favorable_points >= management.trailing_trigger_points
    ):
        trailing = (
            current - management.trailing_distance_points
            if side == "BUY"
            else current + management.trailing_distance_points
        )
        if candidate is None or _stop_improvement_points(side, trailing, candidate) > 0:
            candidate = trailing
            reason = "TRAILING_STOP"
    return candidate, reason


def _first_float(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _is_valid_managed_stop(side: str, stop: float, current: float) -> bool:
    if side == "BUY":
        return stop < current
    if side == "SELL":
        return stop > current
    return False


def _stop_improvement_points(side: str, candidate: float, current_stop: float) -> float:
    if side == "BUY":
        return candidate - current_stop
    if side == "SELL":
        return current_stop - candidate
    return 0.0
