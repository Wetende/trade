"""MetaTrader 5 broker adapter.

This adapter verifies configured account details and supports guarded pending
order actions, order cancellation, and stop updates.
"""

from __future__ import annotations

import importlib
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from numbers import Integral
from pathlib import Path
from typing import Any

from tradingagents.agents.schemas import OrderProposal


class MT5BrokerError(RuntimeError):
    """Raised when the MT5 terminal bridge cannot connect or inspect symbols."""


_TRADE_MODE_LABEL_CONSTANTS = {
    "DEMO": "ACCOUNT_TRADE_MODE_DEMO",
    "REAL": "ACCOUNT_TRADE_MODE_REAL",
    "CONTEST": "ACCOUNT_TRADE_MODE_CONTEST",
}
_REAL_ORDER_ACK = "I_UNDERSTAND_REAL_MONEY_IS_AT_RISK"
_MISSING = object()
_MT5_COMMENT_MAX_LENGTH = 20


def _parse_pending_expiration_epoch(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    tz_abbreviations = {
        "EDT": timezone(timedelta(hours=-4)),
        "EST": timezone(timedelta(hours=-5)),
        "UTC": timezone.utc,
    }
    parsed: datetime
    parts = text.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].upper() in tz_abbreviations:
        try:
            parsed = datetime.fromisoformat(parts[0].replace(" ", "T"))
        except ValueError:
            return None
        parsed = parsed.replace(tzinfo=tz_abbreviations[parts[1].upper()])
    else:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _safe_mt5_comment(value: Any, *, fallback: str = "TA close") -> str:
    text = str(value or fallback)
    text = "".join(
        ch for ch in text if 32 <= ord(ch) < 127 and ch not in {'"', "'"}
    )
    text = " ".join(text.split())
    if not text:
        text = fallback
    return text[:_MT5_COMMENT_MAX_LENGTH].rstrip() or fallback[:_MT5_COMMENT_MAX_LENGTH]


@dataclass(frozen=True)
class MT5ConnectionConfig:
    login: int
    password: str
    server: str
    symbol: str = "XAUUSD"
    terminal_path: str | None = None
    allow_real_orders: bool = False
    require_demo_account: bool = True
    expected_login: int | None = None
    expected_server: str | None = None
    volume: float = 0.01
    deviation: int = 20
    magic: int = 150015
    order_comment: str = "TradingAgents"
    use_server_expiration: bool = False
    execution_state_dir: str | None = None
    max_entry_distance_points: float = 10.0
    min_stop_distance_price: float = 0.0
    min_stop_spread_multiple: float = 4.0

    def __post_init__(self) -> None:
        if not isinstance(self.allow_real_orders, bool):
            raise MT5BrokerError("allow_real_orders must be a boolean")
        if not isinstance(self.require_demo_account, bool):
            raise MT5BrokerError("require_demo_account must be a boolean")
        if not isinstance(self.use_server_expiration, bool):
            raise MT5BrokerError("use_server_expiration must be a boolean")

        if self.expected_login is None:
            object.__setattr__(self, "expected_login", self.login)
        if self.expected_server is None:
            object.__setattr__(self, "expected_server", self.server)

        try:
            volume = float(self.volume)
        except (TypeError, ValueError) as exc:
            raise MT5BrokerError("MT5 volume must be numeric") from exc
        if not math.isfinite(volume) or volume <= 0:
            raise MT5BrokerError("MT5 volume must be positive")
        object.__setattr__(self, "volume", volume)
        object.__setattr__(
            self,
            "deviation",
            _coerce_nonnegative_int_guard(self.deviation, "MT5 deviation"),
        )
        object.__setattr__(
            self, "magic", _coerce_nonnegative_int_guard(self.magic, "MT5 magic")
        )
        try:
            max_entry_distance_points = float(self.max_entry_distance_points)
        except (TypeError, ValueError) as exc:
            raise MT5BrokerError(
                "MT5 max entry distance points must be numeric"
            ) from exc
        if (
            not math.isfinite(max_entry_distance_points)
            or max_entry_distance_points < 0
        ):
            raise MT5BrokerError(
                "MT5 max entry distance points must be non-negative"
            )
        object.__setattr__(
            self,
            "max_entry_distance_points",
            max_entry_distance_points,
        )
        for attr, label in (
            ("min_stop_distance_price", "MT5 minimum stop distance price"),
            ("min_stop_spread_multiple", "MT5 minimum stop spread multiple"),
        ):
            try:
                value = float(getattr(self, attr))
            except (TypeError, ValueError) as exc:
                raise MT5BrokerError(f"{label} must be numeric") from exc
            if not math.isfinite(value) or value < 0:
                raise MT5BrokerError(f"{label} must be non-negative")
            object.__setattr__(self, attr, value)

    @classmethod
    def from_env(cls) -> "MT5ConnectionConfig":
        missing = [
            name
            for name in (
                "TRADINGAGENTS_MT5_LOGIN",
                "TRADINGAGENTS_MT5_PASSWORD",
                "TRADINGAGENTS_MT5_SERVER",
            )
            if not os.environ.get(name)
        ]
        if missing:
            raise MT5BrokerError(
                "Missing MT5 environment variables: " + ", ".join(missing)
            )
        try:
            login = int(os.environ["TRADINGAGENTS_MT5_LOGIN"])
        except ValueError as exc:
            raise MT5BrokerError("TRADINGAGENTS_MT5_LOGIN must be numeric") from exc

        allow_real_orders = (
            os.environ.get("TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS") == _REAL_ORDER_ACK
        )

        return cls(
            login=login,
            password=os.environ["TRADINGAGENTS_MT5_PASSWORD"],
            server=os.environ["TRADINGAGENTS_MT5_SERVER"],
            symbol=os.environ.get("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD"),
            terminal_path=os.environ.get("TRADINGAGENTS_MT5_PATH") or None,
            allow_real_orders=allow_real_orders,
            require_demo_account=_bool_env(
                "TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT",
                True,
            ),
            expected_login=_int_env("TRADINGAGENTS_MT5_EXPECTED_LOGIN", login),
            expected_server=os.environ.get("TRADINGAGENTS_MT5_EXPECTED_SERVER")
            or os.environ["TRADINGAGENTS_MT5_SERVER"],
            volume=_float_env("TRADINGAGENTS_MT5_VOLUME", 0.01),
            deviation=_nonnegative_int_env("TRADINGAGENTS_MT5_DEVIATION", 20),
            magic=_nonnegative_int_env("TRADINGAGENTS_MT5_MAGIC", 150015),
            order_comment=os.environ.get(
                "TRADINGAGENTS_MT5_ORDER_COMMENT", "TradingAgents"
            ),
            use_server_expiration=_bool_env(
                "TRADINGAGENTS_MT5_USE_SERVER_EXPIRATION",
                False,
            ),
            execution_state_dir=os.environ.get(
                "TRADINGAGENTS_MT5_EXECUTION_STATE_DIR",
                str(Path.cwd() / "runtime" / "mt5_execution_state"),
            ),
            max_entry_distance_points=_float_env(
                "TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS",
                10.0,
            ),
            min_stop_distance_price=_float_env(
                "TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE",
                2.5,
            ),
            min_stop_spread_multiple=_float_env(
                "TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE",
                4.0,
            ),
        )


class MT5OrderRequestBuilder:
    """Build local symbolic MT5 order requests from validated proposals.

    The returned dict is a stable internal contract; it is not passed directly
    to MetaTrader5.order_send until a broker action layer materializes symbolic
    fields into MetaTrader5 constants.
    """

    PENDING_ORDER_TYPES = {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}

    def __init__(self, config: MT5ConnectionConfig):
        self.config = config

    def _round_price(self, value: float, symbol_info: dict[str, Any]) -> float:
        price = float(value)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("MT5 price must be positive and finite")

        raw_digits = symbol_info.get("digits")
        digits = 2 if raw_digits in (None, "") else int(raw_digits)
        tick_size = float(symbol_info.get("trade_tick_size") or 0)
        if tick_size > 0:
            price = round(price / tick_size) * tick_size
        return round(price, digits)

    def _request_volume(self, proposal: OrderProposal) -> float:
        raw_volume = getattr(proposal, "volume", None)
        if raw_volume in (None, ""):
            multiplier = getattr(proposal, "volume_multiplier", None)
            raw_volume = (
                self.config.volume
                if multiplier in (None, "")
                else float(self.config.volume) * float(multiplier)
            )
        volume = float(raw_volume)
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("MT5 volume must be positive and finite")
        return volume

    def _legacy_limit_order_type(self, side: Any) -> str:
        side_value = str(getattr(side, "value", side)).upper()
        if side_value == "BUY":
            return "BUY_LIMIT"
        if side_value == "SELL":
            return "SELL_LIMIT"
        raise ValueError(f"unsupported proposal side for MT5 pending order: {side_value}")

    def _quote(self, symbol_info: dict[str, Any]) -> tuple[float, float]:
        bid = self._round_price(symbol_info.get("bid"), symbol_info)
        ask = self._round_price(symbol_info.get("ask"), symbol_info)
        if bid <= 0 or ask <= 0 or bid > ask:
            raise ValueError(
                "symbol bid/ask are required for AUTO pending order selection"
            )
        return bid, ask

    def _explicit_order_type(self, proposal: OrderProposal) -> str:
        value = str(getattr(proposal, "order_type", "")).strip().upper()
        if value == "LIMIT":
            return self._legacy_limit_order_type(proposal.side)
        if value in self.PENDING_ORDER_TYPES:
            return value
        if value == "AUTO":
            raise ValueError("AUTO order type must be resolved from current bid/ask")
        raise ValueError(f"unsupported MT5 pending order type: {value}")

    def _auto_order_type(
        self,
        proposal: OrderProposal,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> str:
        bid, ask = self._quote(symbol_info)
        side_value = str(getattr(proposal.side, "value", proposal.side)).upper()
        if bid < entry < ask:
            raise ValueError("entry price is stale or inside spread")
        if side_value == "BUY":
            return "BUY_STOP" if entry >= ask else "BUY_LIMIT"
        if side_value == "SELL":
            return "SELL_STOP" if entry <= bid else "SELL_LIMIT"
        raise ValueError(f"unsupported proposal side for MT5 pending order: {side_value}")

    def _resolve_order_type(
        self,
        proposal: OrderProposal,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> str:
        value = str(getattr(proposal, "order_type", "")).strip().upper()
        if value == "AUTO":
            return self._auto_order_type(proposal, entry, symbol_info)
        return self._explicit_order_type(proposal)

    def _assert_stop_level_distance(
        self,
        request_type: str,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> None:
        raw_stops_level = symbol_info.get("trade_stops_level")
        if raw_stops_level in (None, ""):
            return
        try:
            stops_level = float(raw_stops_level)
            point = float(symbol_info.get("point") or 0)
        except (TypeError, ValueError):
            return
        min_distance = stops_level * point
        if min_distance <= 0:
            return

        bid, ask = self._quote(symbol_info)
        distances = {
            "BUY_LIMIT": ask - entry,
            "SELL_LIMIT": entry - bid,
            "BUY_STOP": entry - ask,
            "SELL_STOP": bid - entry,
        }
        distance = distances.get(request_type)
        if distance is not None and distance < min_distance:
            raise ValueError("entry price is inside broker stop level")

    def _stop_level_min_distance(self, symbol_info: dict[str, Any]) -> float:
        raw_stops_level = symbol_info.get("trade_stops_level")
        if raw_stops_level in (None, ""):
            return 0.0
        try:
            stops_level = float(raw_stops_level)
            point = float(symbol_info.get("point") or 0)
        except (TypeError, ValueError):
            return 0.0
        minimum = stops_level * point
        return minimum if math.isfinite(minimum) and minimum > 0 else 0.0

    def _stop_level_distance(
        self,
        request_type: str,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> float | None:
        bid, ask = self._quote(symbol_info)
        distances = {
            "BUY_LIMIT": ask - entry,
            "SELL_LIMIT": entry - bid,
            "BUY_STOP": entry - ask,
            "SELL_STOP": bid - entry,
        }
        return distances.get(request_type)

    def _reprice_entry_outside_stop_level(
        self,
        request_type: str,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> float:
        minimum = self._stop_level_min_distance(symbol_info)
        if minimum <= 0:
            return entry
        distance = self._stop_level_distance(request_type, entry, symbol_info)
        if distance is None or distance >= minimum:
            return entry

        bid, ask = self._quote(symbol_info)
        tick_size = float(symbol_info.get("trade_tick_size") or 0)
        point = float(symbol_info.get("point") or 0)
        buffer = max(tick_size, point, 0.0)
        if request_type == "BUY_STOP":
            return self._round_price(ask + minimum + buffer, symbol_info)
        if request_type == "SELL_STOP":
            return self._round_price(bid - minimum - buffer, symbol_info)
        if request_type == "BUY_LIMIT":
            return self._round_price(ask - minimum - buffer, symbol_info)
        if request_type == "SELL_LIMIT":
            return self._round_price(bid + minimum + buffer, symbol_info)
        return entry

    def _assert_entry_near_quote(
        self,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> None:
        max_distance = float(self.config.max_entry_distance_points)
        if max_distance <= 0:
            return
        if symbol_info.get("bid") in (None, "") or symbol_info.get("ask") in (None, ""):
            return

        bid, ask = self._quote(symbol_info)
        distance = min(abs(entry - bid), abs(entry - ask))
        if distance > max_distance:
            raise ValueError(
                "entry price is too far from live MT5 quote: "
                f"entry={entry}, bid={bid}, ask={ask}, "
                f"distance={distance:.2f}, max_distance={max_distance:.2f}"
            )

    def _assert_stop_distance(
        self,
        entry: float,
        stop: float,
        symbol_info: dict[str, Any],
    ) -> None:
        minimum = float(self.config.min_stop_distance_price)
        if symbol_info.get("bid") not in (None, "") and symbol_info.get("ask") not in (
            None,
            "",
        ):
            bid, ask = self._quote(symbol_info)
            spread_distance = abs(ask - bid) * float(
                self.config.min_stop_spread_multiple
            )
            minimum = max(minimum, spread_distance)
        stop_distance = abs(entry - stop)
        if stop_distance < minimum:
            raise ValueError(
                "stop distance is below minimum: "
                f"distance={stop_distance:.2f}, minimum={minimum:.2f}"
            )

    def build_pending_order_request(
        self,
        proposal: OrderProposal,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(getattr(proposal.status, "value", proposal.status)).upper()
        if status != "PROPOSED":
            raise ValueError("MT5 execution requires a PROPOSED order proposal")
        if (
            proposal.entry_price is None
            or proposal.stop_loss is None
            or proposal.take_profit is None
        ):
            raise ValueError(
                "MT5 execution requires entry_price, stop_loss, and take_profit"
            )
        proposal_broker_symbol = proposal.broker_symbol or proposal.symbol
        if proposal_broker_symbol != self.config.symbol:
            raise ValueError(
                f"proposal broker symbol {proposal_broker_symbol} does not match MT5 symbol {self.config.symbol}"
            )
        symbol_name = symbol_info.get("name")
        if symbol_name and symbol_name != self.config.symbol:
            raise ValueError(
                f"symbol info {symbol_name} does not match MT5 symbol {self.config.symbol}"
            )

        entry = self._round_price(proposal.entry_price, symbol_info)
        stop = self._round_price(proposal.stop_loss, symbol_info)
        target = self._round_price(proposal.take_profit, symbol_info)
        request_type = self._resolve_order_type(proposal, entry, symbol_info)
        if str(getattr(proposal, "order_type", "")).strip().upper() == "AUTO":
            entry = self._reprice_entry_outside_stop_level(
                request_type,
                entry,
                symbol_info,
            )
        self._assert_stop_distance(entry, stop, symbol_info)
        self._assert_entry_near_quote(entry, symbol_info)
        self._assert_stop_level_distance(request_type, entry, symbol_info)
        if request_type in {"BUY_LIMIT", "BUY_STOP"} and not (stop < entry < target):
            raise ValueError("invalid BUY levels for MT5 pending order")
        if request_type in {"SELL_LIMIT", "SELL_STOP"} and not (target < entry < stop):
            raise ValueError("invalid SELL levels for MT5 pending order")

        request = {
            "action": "TRADE_ACTION_PENDING",
            "symbol": self.config.symbol,
            "volume": self._request_volume(proposal),
            "type": request_type,
            "price": entry,
            "sl": stop,
            "tp": target,
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": self.config.order_comment,
            "type_time": "ORDER_TIME_GTC",
            "type_filling": "ORDER_FILLING_RETURN",
        }
        if (
            self.config.use_server_expiration
            and str(proposal.timeframe).strip().lower() in {"1m", "m1"}
        ):
            expiration = _parse_pending_expiration_epoch(
                proposal.cancel_if_not_triggered_after or proposal.valid_until
            )
            if expiration is not None:
                request["type_time"] = "ORDER_TIME_SPECIFIED"
                request["expiration"] = expiration
        return request

    def build_pending_limit_request(
        self,
        proposal: OrderProposal,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any]:
        return self.build_pending_order_request(proposal, symbol_info)


def _int_env(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise MT5BrokerError(f"{name} must be numeric") from exc


def _nonnegative_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value is None:
        return default
    if value < 0:
        raise MT5BrokerError(f"{name} must be non-negative")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise MT5BrokerError(f"{name} must be numeric") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise MT5BrokerError(f"{name} must be boolean")


def _coerce_nonnegative_int_guard(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise MT5BrokerError(f"{name} must be numeric")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    elif isinstance(value, str) and value.startswith("-") and value[1:].isdigit():
        raise MT5BrokerError(f"{name} must be non-negative")
    else:
        raise MT5BrokerError(f"{name} must be numeric")
    if number < 0:
        raise MT5BrokerError(f"{name} must be non-negative")
    return number


def _asdict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _mt5_history_datetime(
    value: datetime,
    server_time_offset_seconds: int = 0,
) -> datetime:
    if value.tzinfo is None:
        current = value.replace(tzinfo=timezone.utc)
    else:
        current = value.astimezone(timezone.utc)
    if server_time_offset_seconds:
        current = current + timedelta(seconds=int(server_time_offset_seconds))
    return current


class MT5Broker:
    def __init__(self, config: MT5ConnectionConfig, mt5_module: Any | None = None):
        self.config = config
        self._mt5 = mt5_module
        self._connected = False

    def _module(self):
        if self._mt5 is not None:
            return self._mt5
        try:
            self._mt5 = importlib.import_module("MetaTrader5")
        except ImportError as exc:
            raise MT5BrokerError(
                "MetaTrader5 Python bridge is not installed. The official bridge "
                "requires a Windows MT5 desktop terminal; the WebTerminal is not "
                "a broker API."
            ) from exc
        return self._mt5

    def connect(self) -> dict[str, Any]:
        mt5 = self._module()
        self._connected = False
        init_kwargs = {
            "login": self.config.login,
            "password": self.config.password,
            "server": self.config.server,
        }
        if self.config.terminal_path:
            init_kwargs["path"] = self.config.terminal_path

        if not mt5.initialize(**init_kwargs):
            raise MT5BrokerError(f"MT5 initialize failed: {mt5.last_error()}")

        try:
            account = _asdict(mt5.account_info())
            if not account:
                raise MT5BrokerError(f"MT5 account_info failed: {mt5.last_error()}")
            self._assert_expected_account(account)

            if not mt5.symbol_select(self.config.symbol, True):
                raise MT5BrokerError(
                    f"MT5 could not select symbol {self.config.symbol}: {mt5.last_error()}"
                )

            symbol_info = _asdict(mt5.symbol_info(self.config.symbol))
            if not symbol_info:
                raise MT5BrokerError(
                    f"MT5 symbol_info failed for {self.config.symbol}: {mt5.last_error()}"
                )
            tick = _asdict(mt5.symbol_info_tick(self.config.symbol))
            if not tick:
                raise MT5BrokerError(
                    f"MT5 symbol_info_tick failed for {self.config.symbol}: {mt5.last_error()}"
                )
            self._connected = True
        except Exception:
            self._connected = False
            shutdown = getattr(mt5, "shutdown", None)
            if callable(shutdown):
                shutdown()
            raise

        return {
            "connected": True,
            "account": {
                "login": account.get("login"),
                "server": account.get("server"),
                "trade_mode": account.get("trade_mode"),
                "trade_mode_label": self._trade_mode_label(account.get("trade_mode")),
                "name": account.get("name"),
                "company": account.get("company"),
                "currency": account.get("currency"),
                "leverage": account.get("leverage"),
                "balance": account.get("balance"),
                "equity": account.get("equity"),
            },
            "symbol": {
                "name": self.config.symbol,
                "description": symbol_info.get("description"),
                "digits": symbol_info.get("digits"),
                "point": symbol_info.get("point"),
                "spread": symbol_info.get("spread"),
                "trade_contract_size": symbol_info.get("trade_contract_size"),
                "trade_tick_size": symbol_info.get("trade_tick_size"),
                "trade_tick_value": symbol_info.get("trade_tick_value"),
                "trade_stops_level": symbol_info.get("trade_stops_level"),
                "trade_freeze_level": symbol_info.get("trade_freeze_level"),
                "volume_min": symbol_info.get("volume_min"),
                "volume_max": symbol_info.get("volume_max"),
                "volume_step": symbol_info.get("volume_step"),
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
                "server_time": tick.get("time"),
            },
        }

    def current_symbol_snapshot(self) -> dict[str, Any]:
        """Read current symbol and tick metadata from MT5.

        Closed candles drive analysis; this live snapshot drives spread/tick
        health gates and execution journaling.
        """
        self._assert_active_session()
        mt5 = self._module()
        symbol_info = _asdict(mt5.symbol_info(self.config.symbol))
        if not symbol_info:
            raise MT5BrokerError(
                f"MT5 symbol_info failed for {self.config.symbol}: {mt5.last_error()}"
            )
        tick = _asdict(mt5.symbol_info_tick(self.config.symbol))
        if not tick:
            raise MT5BrokerError(
                f"MT5 symbol_info_tick failed for {self.config.symbol}: {mt5.last_error()}"
            )
        terminal_info = {}
        terminal_info_func = getattr(mt5, "terminal_info", None)
        if callable(terminal_info_func):
            terminal_info = _asdict(terminal_info_func())
        server_time_offset_seconds = self._server_time_offset_seconds(mt5)
        raw_tick_time = tick.get("time")
        tick_time_utc = None
        if raw_tick_time not in (None, ""):
            tick_time_utc = datetime.fromtimestamp(
                int(raw_tick_time) - server_time_offset_seconds,
                tz=timezone.utc,
            ).isoformat()
        bid = tick.get("bid", symbol_info.get("bid"))
        ask = tick.get("ask", symbol_info.get("ask"))
        spread_price = None
        if bid not in (None, "") and ask not in (None, ""):
            spread_price = float(ask) - float(bid)
        return {
            "symbol": {
                "name": self.config.symbol,
                "description": symbol_info.get("description"),
                "digits": symbol_info.get("digits"),
                "point": symbol_info.get("point"),
                "spread": symbol_info.get("spread"),
                "spread_price": spread_price,
                "trade_contract_size": symbol_info.get("trade_contract_size"),
                "trade_tick_size": symbol_info.get("trade_tick_size"),
                "trade_tick_value": symbol_info.get("trade_tick_value"),
                "trade_stops_level": symbol_info.get("trade_stops_level"),
                "trade_freeze_level": symbol_info.get("trade_freeze_level"),
                "bid": bid,
                "ask": ask,
            },
            "tick": {
                **tick,
                "time_utc": tick_time_utc,
            },
            "terminal": terminal_info,
        }

    def _assert_expected_account(self, account: dict[str, Any]) -> None:
        login = account.get("login")
        server = account.get("server")
        if self.config.expected_login is not None and login != self.config.expected_login:
            raise MT5BrokerError(
                f"unexpected MT5 account login: got {login}, expected {self.config.expected_login}"
            )
        if self.config.expected_server and server != self.config.expected_server:
            raise MT5BrokerError(
                f"unexpected MT5 account server: got {server}, expected {self.config.expected_server}"
            )

    def _trade_mode_label(self, trade_mode: Any) -> str:
        for label, constant_name in _TRADE_MODE_LABEL_CONSTANTS.items():
            try:
                if trade_mode == self._constant(constant_name):
                    return label
            except MT5BrokerError:
                continue
        return "UNKNOWN"

    def _constants(self) -> dict[str, Any]:
        return {
            "TRADE_ACTION_DEAL": self._constant("TRADE_ACTION_DEAL"),
            "TRADE_ACTION_PENDING": self._constant("TRADE_ACTION_PENDING"),
            "TRADE_ACTION_REMOVE": self._constant("TRADE_ACTION_REMOVE"),
            "TRADE_ACTION_SLTP": self._constant("TRADE_ACTION_SLTP"),
            "BUY": self._constant("ORDER_TYPE_BUY"),
            "SELL": self._constant("ORDER_TYPE_SELL"),
            "BUY_LIMIT": self._constant("ORDER_TYPE_BUY_LIMIT"),
            "SELL_LIMIT": self._constant("ORDER_TYPE_SELL_LIMIT"),
            "BUY_STOP": self._constant("ORDER_TYPE_BUY_STOP"),
            "SELL_STOP": self._constant("ORDER_TYPE_SELL_STOP"),
            "ORDER_TIME_GTC": self._constant("ORDER_TIME_GTC"),
            "ORDER_TIME_SPECIFIED": self._constant("ORDER_TIME_SPECIFIED"),
            "ORDER_FILLING_FOK": self._constant("ORDER_FILLING_FOK"),
            "ORDER_FILLING_IOC": self._constant("ORDER_FILLING_IOC"),
            "ORDER_FILLING_RETURN": self._constant("ORDER_FILLING_RETURN"),
            "TRADE_RETCODE_DONE": self._constant("TRADE_RETCODE_DONE"),
            "TRADE_RETCODE_PLACED": self._constant("TRADE_RETCODE_PLACED"),
        }

    def _constant(self, name: str) -> Any:
        mt5 = self._module()
        try:
            return getattr(mt5, name)
        except AttributeError as exc:
            raise MT5BrokerError(f"missing MT5 constant: {name}") from exc

    def _symbolic_maps(self) -> dict[str, dict[str, Any]]:
        constants = self._constants()
        return {
            "action": {
                "TRADE_ACTION_DEAL": constants["TRADE_ACTION_DEAL"],
                "TRADE_ACTION_PENDING": constants["TRADE_ACTION_PENDING"],
                "TRADE_ACTION_REMOVE": constants["TRADE_ACTION_REMOVE"],
                "TRADE_ACTION_SLTP": constants["TRADE_ACTION_SLTP"],
            },
            "type": {
                "BUY": constants["BUY"],
                "SELL": constants["SELL"],
                "BUY_LIMIT": constants["BUY_LIMIT"],
                "SELL_LIMIT": constants["SELL_LIMIT"],
                "BUY_STOP": constants["BUY_STOP"],
                "SELL_STOP": constants["SELL_STOP"],
            },
            "type_time": {
                "ORDER_TIME_GTC": constants["ORDER_TIME_GTC"],
                "ORDER_TIME_SPECIFIED": constants["ORDER_TIME_SPECIFIED"],
            },
            "type_filling": {
                "ORDER_FILLING_FOK": constants["ORDER_FILLING_FOK"],
                "ORDER_FILLING_IOC": constants["ORDER_FILLING_IOC"],
                "ORDER_FILLING_RETURN": constants["ORDER_FILLING_RETURN"]
            },
        }

    def _materialize_request(self, request: dict[str, Any]) -> dict[str, Any]:
        symbolic_maps = self._symbolic_maps()
        converted = dict(request)
        for field in ("action", "type", "type_time", "type_filling"):
            if field not in converted:
                continue
            value = self._symbolic_value(converted[field], field)
            try:
                converted[field] = symbolic_maps[field][value]
            except KeyError as exc:
                raise MT5BrokerError(
                    f"unknown MT5 request {field} value: {value}"
                ) from exc
        return converted

    def _send(self, request: dict[str, Any]) -> dict[str, Any]:
        self._assert_order_send_allowed()
        mt5 = self._module()
        result = mt5.order_send(request)
        result_data = _asdict(result)
        ok_retcode = self._success_retcodes_for_action(request.get("action"))
        ok = result_data.get("retcode") in ok_retcode
        echoed_request = _asdict(result_data.get("request")) or dict(request)
        response = {
            "ok": ok,
            "retcode": result_data.get("retcode"),
            "order": result_data.get("order"),
            "deal": result_data.get("deal"),
            "comment": result_data.get("comment"),
            "request": echoed_request,
        }
        if not ok:
            response["last_error"] = mt5.last_error()
        return response

    def _assert_active_session(self) -> None:
        if not self._connected:
            raise MT5BrokerError("MT5 broker is not connected")
        mt5 = self._module()
        terminal_info = getattr(mt5, "terminal_info", None)
        if not callable(terminal_info):
            raise MT5BrokerError("MT5 terminal_info is unavailable")
        terminal = _asdict(terminal_info())
        if not terminal or terminal.get("connected") is not True:
            raise MT5BrokerError("MT5 terminal is not connected")
        account = _asdict(mt5.account_info())
        if not account:
            raise MT5BrokerError(f"MT5 account_info failed: {mt5.last_error()}")
        self._assert_expected_account(account)

    def _assert_order_send_allowed(self) -> None:
        self._assert_active_session()
        mt5 = self._module()
        terminal = _asdict(mt5.terminal_info())
        if terminal.get("trade_allowed") is False:
            raise MT5BrokerError("MT5 terminal trading is not allowed")
        if terminal.get("tradeapi_disabled") is True:
            raise MT5BrokerError("MT5 terminal trade API is disabled")
        account = _asdict(mt5.account_info())
        if account.get("trade_allowed") is False:
            raise MT5BrokerError("MT5 account trading is not allowed")
        if account.get("trade_expert") is False:
            raise MT5BrokerError("MT5 account expert trading is not allowed")
        trade_mode_label = self._trade_mode_label(account.get("trade_mode"))
        if trade_mode_label == "UNKNOWN":
            raise MT5BrokerError(
                "MT5 account trade mode is unknown; refusing broker order"
            )
        if self.config.require_demo_account and trade_mode_label != "DEMO":
            raise MT5BrokerError(
                "MT5 demo account is required for broker execution; "
                f"connected trade mode is {trade_mode_label}"
            )
        if trade_mode_label == "REAL" and not self.config.allow_real_orders:
            raise MT5BrokerError(
                "Real-account broker execution requires real-money acknowledgement"
            )

    def _success_retcodes_for_action(self, action: Any) -> set[Any]:
        constants = self._constants()
        if action == constants["TRADE_ACTION_PENDING"]:
            return {
                constants["TRADE_RETCODE_DONE"],
                constants["TRADE_RETCODE_PLACED"],
            }
        return {constants["TRADE_RETCODE_DONE"]}

    def place_pending_order(self, request: dict[str, Any]) -> dict[str, Any]:
        validated = self._validate_pending_order_request(request)
        return self._send(self._materialize_request(validated))

    def check_order(self, request: dict[str, Any]) -> dict[str, Any]:
        """Preflight a pending order request with MT5 ``order_check``."""
        self._assert_order_send_allowed()
        mt5 = self._module()
        order_check = getattr(mt5, "order_check", None)
        if not callable(order_check):
            raise MT5BrokerError("MT5 order_check is unavailable")
        validated = self._validate_pending_order_request(request)
        materialized = self._materialize_request(validated)
        result = order_check(materialized)
        result_data = _asdict(result)
        ok_retcode = self._success_retcodes_for_action(materialized.get("action"))
        retcode = result_data.get("retcode")
        ok = retcode in ok_retcode or retcode == 0
        echoed_request = _asdict(result_data.get("request")) or dict(materialized)
        response = {
            "ok": ok,
            "retcode": retcode,
            "comment": result_data.get("comment"),
            "balance": result_data.get("balance"),
            "equity": result_data.get("equity"),
            "margin": result_data.get("margin"),
            "margin_free": result_data.get("margin_free"),
            "request": echoed_request,
        }
        if not ok:
            response["last_error"] = mt5.last_error()
        return response

    def _validate_pending_order_request(
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        required_fields = (
            "action",
            "symbol",
            "volume",
            "type",
            "price",
            "sl",
            "tp",
            "deviation",
            "magic",
            "comment",
            "type_time",
            "type_filling",
        )
        allowed_fields = set(required_fields)
        if request.get("type_time") == "ORDER_TIME_SPECIFIED":
            allowed_fields.add("expiration")
        extra_fields = sorted(set(request) - allowed_fields)
        if extra_fields:
            raise MT5BrokerError(
                f"unexpected MT5 request field: {extra_fields[0]}"
            )

        for field in required_fields:
            if field not in request:
                raise MT5BrokerError(f"missing required MT5 request field: {field}")

        if request.get("action") != "TRADE_ACTION_PENDING":
            if not isinstance(request.get("action"), str):
                raise MT5BrokerError("action must be symbolic TRADE_ACTION_PENDING")
            raise MT5BrokerError("action must be TRADE_ACTION_PENDING")

        for field in ("action", "type", "type_time", "type_filling"):
            self._symbolic_value(request[field], field)
        if request["type_time"] == "ORDER_TIME_SPECIFIED":
            if "expiration" not in request:
                raise MT5BrokerError("missing required MT5 request field: expiration")
            expiration = self._int_value(request["expiration"], "expiration")
        else:
            expiration = None

        if request["symbol"] != self.config.symbol:
            raise MT5BrokerError(
                f"symbol must match configured MT5 symbol {self.config.symbol}"
            )
        if request["type"] not in MT5OrderRequestBuilder.PENDING_ORDER_TYPES:
            if not isinstance(request["type"], str):
                raise MT5BrokerError(
                    "type must be symbolic BUY_LIMIT, SELL_LIMIT, BUY_STOP, or SELL_STOP"
                )
            raise MT5BrokerError(
                "type must be BUY_LIMIT, SELL_LIMIT, BUY_STOP, or SELL_STOP"
            )

        numbers = {
            field: self._positive_float(request[field], field)
            for field in ("volume", "price", "sl", "tp")
        }
        if request["type"] in {"BUY_LIMIT", "BUY_STOP"} and not (
            numbers["sl"] < numbers["price"] < numbers["tp"]
        ):
            raise MT5BrokerError("invalid BUY levels for MT5 pending order")
        if request["type"] in {"SELL_LIMIT", "SELL_STOP"} and not (
            numbers["tp"] < numbers["price"] < numbers["sl"]
        ):
            raise MT5BrokerError("invalid SELL levels for MT5 pending order")

        magic = self._int_value(request["magic"], "magic")
        deviation = self._int_value(request["deviation"], "deviation")
        if magic != self.config.magic:
            raise MT5BrokerError("magic must match configured MT5 magic")
        if deviation != self.config.deviation:
            raise MT5BrokerError("deviation must match configured MT5 deviation")
        validated = {**request, **numbers, "magic": magic, "deviation": deviation}
        if expiration is not None:
            validated["expiration"] = expiration
        return validated

    @staticmethod
    def _symbolic_value(value: Any, field: str) -> str:
        if not isinstance(value, str):
            raise MT5BrokerError(f"{field} must be symbolic")
        return value

    @staticmethod
    def _positive_float(value: Any, name: str) -> float:
        if isinstance(value, bool):
            raise MT5BrokerError(f"{name} must be positive and finite")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise MT5BrokerError(f"{name} must be positive and finite") from exc
        if not math.isfinite(number) or number <= 0:
            raise MT5BrokerError(f"{name} must be positive and finite")
        return number

    @staticmethod
    def _int_value(value: Any, name: str) -> int:
        if isinstance(value, bool):
            raise MT5BrokerError(f"{name} must be an integer")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.isdigit():
            number = int(value)
        elif isinstance(value, str) and value.startswith("-") and value[1:].isdigit():
            raise MT5BrokerError(f"{name} must be non-negative")
        else:
            raise MT5BrokerError(f"{name} must be an integer")
        if number < 0:
            raise MT5BrokerError(f"{name} must be non-negative")
        return number

    @staticmethod
    def _positive_ticket(value: Any, name: str) -> int:
        if isinstance(value, bool):
            raise MT5BrokerError(f"{name} ticket must be a positive number")
        if isinstance(value, int):
            ticket = value
        elif isinstance(value, str) and value.isdigit():
            ticket = int(value)
        else:
            raise MT5BrokerError(f"{name} ticket must be a positive number")
        if ticket <= 0:
            raise MT5BrokerError(f"{name} ticket must be a positive number")
        return ticket

    def cancel_order(self, ticket: int) -> dict[str, Any]:
        order_ticket = self._positive_ticket(ticket, "order")
        return self._send(
            self._materialize_request(
                {"action": "TRADE_ACTION_REMOVE", "order": order_ticket}
            )
        )

    def modify_position_stops(
        self, position_ticket: int, stop_loss: float, take_profit: float
    ) -> dict[str, Any]:
        ticket = self._positive_ticket(position_ticket, "position")
        stop = self._positive_float(stop_loss, "stop_loss")
        target = self._positive_float(take_profit, "take_profit")
        return self._send(
            self._materialize_request(
                {
                    "action": "TRADE_ACTION_SLTP",
                    "position": ticket,
                    "sl": stop,
                    "tp": target,
                }
            )
        )

    def close_position(
        self,
        position: dict[str, Any],
        *,
        comment: str = "TradingAgents close",
        volume: float | None = None,
    ) -> dict[str, Any]:
        item = _asdict(position)
        ticket = self._positive_ticket(item.get("ticket"), "position")
        symbol = item.get("symbol")
        if symbol not in (None, "") and symbol != self.config.symbol:
            raise MT5BrokerError(
                f"symbol must match configured MT5 symbol {self.config.symbol}"
            )

        side = str(item.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            raise MT5BrokerError("position side must be BUY or SELL")
        open_volume = self._positive_float(item.get("volume"), "volume")
        close_volume = (
            open_volume
            if volume in (None, "")
            else self._positive_float(volume, "close volume")
        )
        if close_volume - open_volume > 1e-12:
            raise MT5BrokerError("close volume cannot exceed open position volume")

        self._assert_active_session()
        mt5 = self._module()
        tick = _asdict(mt5.symbol_info_tick(self.config.symbol))
        if not tick:
            raise MT5BrokerError(
                f"MT5 symbol_info_tick failed for {self.config.symbol}: {mt5.last_error()}"
            )
        close_type = "SELL" if side == "BUY" else "BUY"
        price_field = "bid" if close_type == "SELL" else "ask"
        price = self._positive_float(tick.get(price_field), "price")
        base_request = {
            "action": "TRADE_ACTION_DEAL",
            "symbol": self.config.symbol,
            "volume": close_volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": _safe_mt5_comment(comment),
        }
        attempts = []
        last_response = None
        for filling_name in (
            "ORDER_FILLING_FOK",
            "ORDER_FILLING_IOC",
            "ORDER_FILLING_RETURN",
        ):
            response = self._send(
                self._materialize_request(
                    {**base_request, "type_filling": filling_name}
                )
            )
            attempts.append(
                {
                    "type_filling": filling_name,
                    "retcode": response.get("retcode"),
                    "comment": response.get("comment"),
                    "ok": response.get("ok"),
                }
            )
            response["filling_attempts"] = attempts
            last_response = response
            if response.get("ok"):
                return response
            if not self._is_retryable_close_response(response):
                return response
        return last_response or {
            "ok": False,
            "retcode": None,
            "order": None,
            "deal": None,
            "comment": "no close filling mode attempted",
            "request": {},
            "filling_attempts": attempts,
        }

    @staticmethod
    def _is_unsupported_filling_response(response: dict[str, Any]) -> bool:
        comment = str(response.get("comment") or "").lower()
        return "filling" in comment and "unsupported" in comment

    @classmethod
    def _is_retryable_close_response(cls, response: dict[str, Any]) -> bool:
        if cls._is_unsupported_filling_response(response):
            return True
        comment = str(response.get("comment") or "").lower()
        return response.get("retcode") == 10013 and "invalid request" in comment

    def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        self._assert_active_session()
        mt5 = self._module()
        orders = mt5.orders_get(symbol=symbol) or []
        return [_asdict(order) for order in orders]

    def open_positions(self, symbol: str) -> list[dict[str, Any]]:
        self._assert_active_session()
        mt5 = self._module()
        positions = mt5.positions_get(symbol=symbol) or []
        server_time_offset_seconds = self._server_time_offset_seconds(mt5)
        buy_type = getattr(mt5, "POSITION_TYPE_BUY", 0)
        sell_type = getattr(mt5, "POSITION_TYPE_SELL", 1)
        normalized = []
        for position in positions:
            item = _asdict(position)
            position_type = item.get("type")
            if position_type == buy_type:
                side = "BUY"
            elif position_type == sell_type:
                side = "SELL"
            else:
                side = str(item.get("side", "")).upper()
            opened_at_utc = None
            raw_time_msc = item.get("time_msc")
            raw_time = item.get("time")
            if raw_time_msc not in (None, ""):
                opened_at_utc = datetime.fromtimestamp(
                    (float(raw_time_msc) / 1000.0) - server_time_offset_seconds,
                    tz=timezone.utc,
                ).isoformat()
            elif raw_time not in (None, ""):
                opened_at_utc = datetime.fromtimestamp(
                    float(raw_time) - server_time_offset_seconds,
                    tz=timezone.utc,
                ).isoformat()
            normalized.append(
                {
                    **item,
                    "side": side,
                    "entry_price": item.get("price_open"),
                    "current_price": item.get("price_current"),
                    "stop_loss": item.get("sl"),
                    "take_profit": item.get("tp"),
                    "opened_at_utc": opened_at_utc,
                }
            )
        return normalized

    def history_deals(
        self,
        symbol: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict[str, Any]]:
        """Read normalized MT5 deal history for one symbol."""
        self._assert_active_session()
        mt5 = self._module()
        server_time_offset_seconds = self._server_time_offset_seconds(mt5)
        query_start = start_utc + timedelta(seconds=server_time_offset_seconds)
        query_end = end_utc + timedelta(seconds=server_time_offset_seconds)
        deals = mt5.history_deals_get(
            _mt5_history_datetime(query_start),
            _mt5_history_datetime(query_end),
        )
        if deals is None:
            raise MT5BrokerError(f"MT5 history_deals_get failed: {mt5.last_error()}")

        normalized = []
        for deal in deals:
            item = _asdict(deal)
            if item.get("symbol") != symbol:
                continue
            raw_time = item.get("time")
            if raw_time not in (None, ""):
                try:
                    item["time_utc"] = datetime.fromtimestamp(
                        int(raw_time) - server_time_offset_seconds,
                        tz=timezone.utc,
                    ).isoformat()
                except (TypeError, ValueError, OSError):
                    pass
            normalized.append(item)
        return normalized

    def fetch_rates(self, timeframe: str, count: int) -> list[dict[str, Any]]:
        """Fetch normalized OHLCV bars including MT5 bar 0, the forming bar."""
        return self._fetch_rates_from_pos(timeframe, count, start_pos=0)

    def fetch_closed_rates(self, timeframe: str, count: int) -> list[dict[str, Any]]:
        """Fetch normalized closed OHLCV bars.

        The official MT5 Python API defines ``copy_rates_from_pos`` position
        ``0`` as the current, still-forming bar. Analysis must start at
        position ``1`` so setup detection only reads completed candles.
        """
        return self._fetch_rates_from_pos(timeframe, count, start_pos=1)

    def _fetch_rates_from_pos(
        self,
        timeframe: str,
        count: int,
        *,
        start_pos: int,
    ) -> list[dict[str, Any]]:
        self._assert_active_session()
        rate_count = self._positive_count(count)
        if isinstance(start_pos, bool) or not isinstance(start_pos, Integral) or start_pos < 0:
            raise MT5BrokerError("MT5 rate start_pos must be a non-negative integer")

        mt5 = self._module()
        timeframe_constants = {
            "1m": getattr(mt5, "TIMEFRAME_M1", None),
            "3m": getattr(mt5, "TIMEFRAME_M3", None),
            "15m": getattr(mt5, "TIMEFRAME_M15", None),
            "30m": getattr(mt5, "TIMEFRAME_M30", None),
            "1h": getattr(mt5, "TIMEFRAME_H1", None),
            "1d": getattr(mt5, "TIMEFRAME_D1", None),
        }
        mt5_timeframe = timeframe_constants.get(timeframe)
        if mt5_timeframe is None:
            raise MT5BrokerError(f"unsupported MT5 timeframe: {timeframe}")

        rates = mt5.copy_rates_from_pos(
            self.config.symbol,
            mt5_timeframe,
            int(start_pos),
            rate_count,
        )
        if rates is None:
            raise MT5BrokerError(f"MT5 copy_rates_from_pos failed: {mt5.last_error()}")

        server_time_offset_seconds = self._server_time_offset_seconds(mt5)
        return [self._normalize_rate(rate, server_time_offset_seconds) for rate in rates]

    def _normalize_rate(
        self,
        rate: Any,
        server_time_offset_seconds: int,
    ) -> dict[str, Any]:
        item = _asdict(rate)
        raw_timestamp = int(self._rate_value(rate, item, "time"))
        return {
            "timestamp": datetime.fromtimestamp(
                raw_timestamp - server_time_offset_seconds,
                tz=timezone.utc,
            ).isoformat(),
            "open": float(self._rate_value(rate, item, "open")),
            "high": float(self._rate_value(rate, item, "high")),
            "low": float(self._rate_value(rate, item, "low")),
            "close": float(self._rate_value(rate, item, "close")),
            "volume": float(
                self._rate_value(
                    rate,
                    item,
                    "tick_volume",
                    self._rate_value(rate, item, "real_volume", 0),
                )
            ),
            "spread": float(self._rate_value(rate, item, "spread", 0)),
            "real_volume": float(self._rate_value(rate, item, "real_volume", 0)),
        }

    def _server_time_offset_seconds(
        self,
        mt5: Any,
        *,
        now_utc: datetime | None = None,
    ) -> int:
        tick = _asdict(mt5.symbol_info_tick(self.config.symbol))
        raw_tick_time = tick.get("time")
        if raw_tick_time in (None, ""):
            return 0

        current = now_utc or datetime.now(timezone.utc)
        raw_offset = int(raw_tick_time) - int(current.timestamp())
        rounded_offset = int(round(raw_offset / 3600)) * 3600
        if abs(rounded_offset) > 14 * 3600:
            return 0
        return rounded_offset

    @staticmethod
    def _positive_count(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise MT5BrokerError("MT5 rate count must be a positive integer")
        return int(value)

    @staticmethod
    def _rate_value(
        rate: Any,
        item: dict[str, Any],
        field: str,
        default: Any = _MISSING,
    ) -> Any:
        if field in item:
            return item[field]
        try:
            return rate[field]
        except (KeyError, IndexError, TypeError, ValueError):
            if default is not _MISSING:
                return default
            raise MT5BrokerError(f"MT5 rate row missing field: {field}") from None

    def shutdown(self) -> None:
        self._connected = False
        if self._mt5 is None:
            return
        shutdown = getattr(self._mt5, "shutdown", None)
        if callable(shutdown):
            shutdown()
