"""JSON state file for the active MT5 order."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.schemas import OrderProposal
from tradingagents.dataflows.utils import safe_ticker_component


def account_state_namespace(server: Any, login: Any) -> str:
    """Return a stable account namespace without exposing broker identity."""
    identity = f"{server or ''}\0{login or ''}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:20]
    return f"account-{digest}"


class ExecutionStateStore:
    """Persist one-symbol MT5 execution state."""

    filename = "mt5_state.json"
    capabilities_file = "broker_capabilities.json"
    max_consumed_openings = 128
    max_completed_positions = 128

    def __init__(self, results_dir: str | Path, symbol: str) -> None:
        self.symbol = symbol
        safe_symbol = safe_ticker_component(symbol)
        self.directory = Path(results_dir) / safe_symbol / "execution_state"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / self.filename
        self.capabilities_path = self.directory / self.capabilities_file

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "symbol": self.symbol,
                "active_order_ticket": None,
                "active_position_ticket": None,
            }
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return state

    def record_pending_order(
        self,
        ticket: int,
        proposal: OrderProposal,
        placed_at_utc: datetime | None = None,
        cancel_after_utc: datetime | None = None,
        pending_policy: dict[str, Any] | None = None,
        execution_timeline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        placed_at = placed_at_utc or datetime.now(timezone.utc)
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=timezone.utc)
        placed_at = placed_at.astimezone(timezone.utc)
        if cancel_after_utc is None:
            activation_window = proposal.activation_window_minutes or 10
            cancel_after = placed_at + timedelta(minutes=activation_window)
        else:
            cancel_after = cancel_after_utc
            if cancel_after.tzinfo is None:
                cancel_after = cancel_after.replace(tzinfo=timezone.utc)
            cancel_after = cancel_after.astimezone(timezone.utc)
        state = {
            **self._durable_state(self.load()),
            "symbol": self.symbol,
            "active_order_ticket": int(ticket),
            "active_position_ticket": None,
            "placed_at_utc": placed_at.isoformat(),
            "cancel_after_utc": cancel_after.isoformat(),
            "pending_policy": dict(pending_policy or {}),
            "proposal": proposal.model_dump(mode="json"),
        }
        if execution_timeline is not None:
            state["execution_timeline"] = dict(execution_timeline)
        return self.save(state)

    @staticmethod
    def _utc_iso(value: datetime | None = None) -> str:
        parsed = value or datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _durable_state(state: dict[str, Any]) -> dict[str, Any]:
        return {
            key: state[key]
            for key in (
                "consumed_openings",
                "completed_position_telemetry",
                "post_close_lifecycle",
                "post_close_loss_control",
                "post_close_consumed_zones",
            )
            if key in state
        }

    def load_broker_capabilities(self) -> dict[str, Any]:
        if not self.capabilities_path.exists():
            return {}
        payload = json.loads(
            self.capabilities_path.read_text(encoding="utf-8")
        )
        return payload if isinstance(payload, dict) else {}

    def record_short_pending_expiration_support(
        self,
        supported: bool,
        *,
        reason: str,
        observed_at_utc: datetime | None = None,
    ) -> dict[str, Any]:
        capabilities = self.load_broker_capabilities()
        capabilities.update(
            {
                "short_pending_expiration_supported": bool(supported),
                "short_pending_expiration_reason": str(reason),
                "short_pending_expiration_updated_at_utc": self._utc_iso(
                    observed_at_utc
                ),
            }
        )
        temporary = self.capabilities_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(capabilities, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.capabilities_path)
        return capabilities

    def record_post_close_lifecycle(
        self,
        lifecycle: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one broker-free armed/triggered lifecycle."""
        state = self.load()
        if state.get("active_order_ticket") is not None:
            raise ValueError("cannot arm post-close lifecycle with an active order")
        if state.get("active_position_ticket") is not None:
            raise ValueError("cannot arm post-close lifecycle with an active position")
        phase = str(lifecycle.get("phase") or "").upper()
        if phase not in {"ARMED", "TRIGGERED"}:
            raise ValueError("post-close lifecycle must be ARMED or TRIGGERED")
        arm = lifecycle.get("arm")
        if not isinstance(arm, dict) or not arm.get("arm_id"):
            raise ValueError("post-close lifecycle requires an arm identity")
        state["post_close_lifecycle"] = dict(lifecycle)
        return self.save(state)

    def clear_post_close_lifecycle(self) -> dict[str, Any]:
        state = self.load()
        state.pop("post_close_lifecycle", None)
        return self.save(state)

    def recover_post_close_lifecycle(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Recover without extending expiry or competing with broker state."""
        state = self.load()
        lifecycle = state.get("post_close_lifecycle")
        if not isinstance(lifecycle, dict):
            return {"status": "NONE", "lifecycle": None}
        if (
            state.get("active_order_ticket") is not None
            or state.get("active_position_ticket") is not None
        ):
            state.pop("post_close_lifecycle", None)
            self.save(state)
            return {
                "status": "ORPHANED_BY_ACTIVE_BROKER_STATE",
                "lifecycle": lifecycle,
            }
        arm = lifecycle.get("arm") or {}
        expires_at = self._parse_utc(arm.get("expires_at"))
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        if expires_at is None:
            state.pop("post_close_lifecycle", None)
            self.save(state)
            return {"status": "INVALID_EXPIRY", "lifecycle": lifecycle}
        if now >= expires_at:
            state.pop("post_close_lifecycle", None)
            self.save(state)
            return {"status": "EXPIRED", "lifecycle": lifecycle}
        return {"status": "ACTIVE", "lifecycle": lifecycle}

    @staticmethod
    def _parse_utc(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def record_post_close_consumed_zone(
        self,
        arm: dict[str, Any],
        *,
        consumed_at_utc: datetime | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        records = list(state.get("post_close_consumed_zones") or [])
        records.insert(
            0,
            {
                "arm": dict(arm),
                "consumed_at_utc": self._utc_iso(consumed_at_utc),
                "moved_away": False,
                "reset_complete": False,
            },
        )
        state["post_close_consumed_zones"] = records[: self.max_consumed_openings]
        return self.save(state)

    def record_post_close_trade_outcome(
        self,
        profit_r: float,
        *,
        closed_at_utc: datetime | None = None,
        pause_minutes: int = 15,
    ) -> dict[str, Any]:
        """Persist the two-loss pause independently of process lifetime."""
        state = self.load()
        control = dict(state.get("post_close_loss_control") or {})
        streak = int(control.get("loss_streak", 0))
        streak = streak + 1 if float(profit_r) < 0 else 0
        closed_at = closed_at_utc or datetime.now(timezone.utc)
        if closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=timezone.utc)
        closed_at = closed_at.astimezone(timezone.utc)
        control = {
            "loss_streak": streak,
            "last_closed_at_utc": closed_at.isoformat(),
            "structural_reset_complete": False,
            "pause_until_utc": (
                (closed_at + timedelta(minutes=max(0, int(pause_minutes)))).isoformat()
                if streak >= 2
                else None
            ),
        }
        state["post_close_loss_control"] = control
        return self.save(state)

    def mark_post_close_structural_reset(self) -> dict[str, Any]:
        state = self.load()
        control = dict(state.get("post_close_loss_control") or {})
        control["structural_reset_complete"] = True
        state["post_close_loss_control"] = control
        return self.save(state)

    def post_close_entry_gate(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        if state.get("active_order_ticket") is not None:
            return {"allowed": False, "reason": "ACTIVE_ORDER"}
        if state.get("active_position_ticket") is not None:
            return {"allowed": False, "reason": "ACTIVE_POSITION"}
        if isinstance(state.get("post_close_lifecycle"), dict):
            return {"allowed": False, "reason": "ACTIVE_POST_CLOSE_LIFECYCLE"}
        control = dict(state.get("post_close_loss_control") or {})
        if int(control.get("loss_streak", 0)) < 2:
            return {"allowed": True, "reason": None}
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        pause_until = self._parse_utc(control.get("pause_until_utc"))
        if pause_until is None or now < pause_until:
            return {
                "allowed": False,
                "reason": "TWO_LOSS_TIME_PAUSE",
                "pause_until_utc": control.get("pause_until_utc"),
            }
        if not bool(control.get("structural_reset_complete")):
            return {"allowed": False, "reason": "TWO_LOSS_RESET_REQUIRED"}
        return {"allowed": True, "reason": None}

    def complete_post_close_pause(
        self,
        *,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        gate = self.post_close_entry_gate(now_utc=now_utc)
        if not gate["allowed"]:
            raise ValueError(str(gate["reason"]))
        state = self.load()
        control = dict(state.get("post_close_loss_control") or {})
        if int(control.get("loss_streak", 0)) >= 2:
            state["post_close_loss_control"] = {
                "loss_streak": 0,
                "last_closed_at_utc": control.get("last_closed_at_utc"),
                "structural_reset_complete": False,
                "pause_until_utc": None,
            }
            self.save(state)
        return state

    def record_consumed_opening(
        self,
        opening_context: dict[str, Any],
        *,
        consumed_at_utc: datetime | None = None,
        order_ticket: int | None = None,
        execution_timeline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        record: dict[str, Any] = {
            "opening_context": dict(opening_context),
            "consumed_at_utc": self._utc_iso(consumed_at_utc),
        }
        if order_ticket is not None:
            record["order_ticket"] = int(order_ticket)
        if execution_timeline is not None:
            record["execution_timeline"] = dict(execution_timeline)
        records = [
            record,
            *list(state.get("consumed_openings") or []),
        ][: self.max_consumed_openings]
        state["consumed_openings"] = records
        return self.save(state)

    def archive_position_telemetry(
        self,
        position_id: str | int,
        telemetry: dict[str, Any],
    ) -> dict[str, Any]:
        state = self.load()
        completed = dict(state.get("completed_position_telemetry") or {})
        key = str(position_id)
        completed.pop(key, None)
        completed[key] = dict(telemetry)
        if len(completed) > self.max_completed_positions:
            completed = dict(
                list(completed.items())[-self.max_completed_positions :]
            )
        state["completed_position_telemetry"] = completed
        return self.save(state)

    def clear_pending_order(self) -> dict[str, Any]:
        state = self.load()
        state["active_order_ticket"] = None
        return self.save(state)

    def mark_position_active(self, ticket: int) -> dict[str, Any]:
        state = self.load()
        state["active_order_ticket"] = None
        state["active_position_ticket"] = int(ticket)
        return self.save(state)

    def clear_trade(self) -> dict[str, Any]:
        return self.save(
            {
                **self._durable_state(self.load()),
                "symbol": self.symbol,
                "active_order_ticket": None,
                "active_position_ticket": None,
            }
        )
