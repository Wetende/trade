"""MetaTrader 5 demo-account broker adapter.

This adapter verifies demo-account connection details and supports guarded demo
order actions for pending limit orders, order cancellation, and stop updates.
"""

from __future__ import annotations

import importlib
import math
import os
from dataclasses import dataclass
from typing import Any

from tradingagents.agents.schemas import OrderProposal


class MT5BrokerError(RuntimeError):
    """Raised when the MT5 terminal bridge cannot connect or inspect symbols."""


@dataclass(frozen=True)
class MT5ConnectionConfig:
    login: int
    password: str
    server: str
    symbol: str = "XAUUSD"
    terminal_path: str | None = None
    account_mode: str = "demo"
    expected_login: int | None = None
    expected_server: str | None = None
    volume: float = 0.01
    deviation: int = 20
    magic: int = 150015

    def __post_init__(self) -> None:
        account_mode = self.account_mode.strip().lower()
        if account_mode != "demo":
            raise MT5BrokerError("MT5 demo mode is required for automated execution")
        object.__setattr__(self, "account_mode", account_mode)

        try:
            volume = float(self.volume)
        except (TypeError, ValueError) as exc:
            raise MT5BrokerError("MT5 volume must be numeric") from exc
        if not math.isfinite(volume) or volume <= 0:
            raise MT5BrokerError("MT5 volume must be positive")
        object.__setattr__(self, "volume", volume)

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

        account_mode = os.environ.get("TRADINGAGENTS_MT5_ACCOUNT_MODE", "demo")
        account_mode = account_mode.strip().lower()
        if account_mode != "demo":
            raise MT5BrokerError("MT5 demo mode is required for automated execution")

        return cls(
            login=login,
            password=os.environ["TRADINGAGENTS_MT5_PASSWORD"],
            server=os.environ["TRADINGAGENTS_MT5_SERVER"],
            symbol=os.environ.get("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD"),
            terminal_path=os.environ.get("TRADINGAGENTS_MT5_PATH") or None,
            account_mode=account_mode,
            expected_login=_int_env("TRADINGAGENTS_MT5_EXPECTED_LOGIN", login),
            expected_server=os.environ.get("TRADINGAGENTS_MT5_EXPECTED_SERVER")
            or os.environ["TRADINGAGENTS_MT5_SERVER"],
            volume=_float_env("TRADINGAGENTS_MT5_VOLUME", 0.01),
            deviation=_int_env("TRADINGAGENTS_MT5_DEVIATION", 20),
            magic=_int_env("TRADINGAGENTS_MT5_MAGIC", 150015),
        )


class MT5OrderRequestBuilder:
    """Build local symbolic MT5 order requests from validated proposals.

    The returned dict is a stable internal contract; it is not passed directly
    to MetaTrader5.order_send until a broker action layer materializes symbolic
    fields into MetaTrader5 constants.
    """

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

    def _order_type(self, side: Any) -> str:
        side_value = str(getattr(side, "value", side)).upper()
        if side_value == "BUY":
            return "BUY_LIMIT"
        if side_value == "SELL":
            return "SELL_LIMIT"
        raise ValueError(f"unsupported proposal side for MT5 limit order: {side_value}")

    def build_pending_limit_request(
        self,
        proposal: OrderProposal,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(getattr(proposal.status, "value", proposal.status)).upper()
        if status != "PROPOSED":
            raise ValueError("MT5 execution requires a PROPOSED order proposal")
        order_type = str(getattr(proposal, "order_type", "")).strip().upper()
        if order_type != "LIMIT":
            raise ValueError("MT5 execution requires LIMIT order proposals")
        if (
            proposal.entry_price is None
            or proposal.stop_loss is None
            or proposal.take_profit is None
        ):
            raise ValueError(
                "MT5 execution requires entry_price, stop_loss, and take_profit"
            )
        if proposal.symbol != self.config.symbol:
            raise ValueError(
                f"proposal symbol {proposal.symbol} does not match MT5 symbol {self.config.symbol}"
            )
        symbol_name = symbol_info.get("name")
        if symbol_name and symbol_name != self.config.symbol:
            raise ValueError(
                f"symbol info {symbol_name} does not match MT5 symbol {self.config.symbol}"
            )

        entry = self._round_price(proposal.entry_price, symbol_info)
        stop = self._round_price(proposal.stop_loss, symbol_info)
        target = self._round_price(proposal.take_profit, symbol_info)
        request_type = self._order_type(proposal.side)
        if request_type == "BUY_LIMIT" and not (stop < entry < target):
            raise ValueError("invalid BUY levels for MT5 limit order")
        if request_type == "SELL_LIMIT" and not (target < entry < stop):
            raise ValueError("invalid SELL levels for MT5 limit order")

        return {
            "action": "TRADE_ACTION_PENDING",
            "symbol": self.config.symbol,
            "volume": self.config.volume,
            "type": request_type,
            "price": entry,
            "sl": stop,
            "tp": target,
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": "TradingAgents demo",
            "type_time": "ORDER_TIME_GTC",
            "type_filling": "ORDER_FILLING_RETURN",
        }


def _int_env(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise MT5BrokerError(f"{name} must be numeric") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise MT5BrokerError(f"{name} must be numeric") from exc


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
        self._connected = True

        return {
            "connected": True,
            "account": {
                "login": account.get("login"),
                "server": account.get("server"),
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
                "volume_min": symbol_info.get("volume_min"),
                "volume_max": symbol_info.get("volume_max"),
                "volume_step": symbol_info.get("volume_step"),
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
                "server_time": tick.get("time"),
            },
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

    def _constants(self) -> dict[str, Any]:
        return {
            "TRADE_ACTION_PENDING": self._constant("TRADE_ACTION_PENDING"),
            "TRADE_ACTION_REMOVE": self._constant("TRADE_ACTION_REMOVE"),
            "TRADE_ACTION_SLTP": self._constant("TRADE_ACTION_SLTP"),
            "BUY_LIMIT": self._constant("ORDER_TYPE_BUY_LIMIT"),
            "SELL_LIMIT": self._constant("ORDER_TYPE_SELL_LIMIT"),
            "ORDER_TIME_GTC": self._constant("ORDER_TIME_GTC"),
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
                "TRADE_ACTION_PENDING": constants["TRADE_ACTION_PENDING"],
                "TRADE_ACTION_REMOVE": constants["TRADE_ACTION_REMOVE"],
                "TRADE_ACTION_SLTP": constants["TRADE_ACTION_SLTP"],
            },
            "type": {
                "BUY_LIMIT": constants["BUY_LIMIT"],
                "SELL_LIMIT": constants["SELL_LIMIT"],
            },
            "type_time": {"ORDER_TIME_GTC": constants["ORDER_TIME_GTC"]},
            "type_filling": {
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
        self._assert_active_session()
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
        account = _asdict(mt5.account_info())
        if not account:
            raise MT5BrokerError(f"MT5 account_info failed: {mt5.last_error()}")
        self._assert_expected_account(account)

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

        if request["symbol"] != self.config.symbol:
            raise MT5BrokerError(
                f"symbol must match configured MT5 symbol {self.config.symbol}"
            )
        if request["type"] not in {"BUY_LIMIT", "SELL_LIMIT"}:
            if not isinstance(request["type"], str):
                raise MT5BrokerError("type must be symbolic BUY_LIMIT or SELL_LIMIT")
            raise MT5BrokerError("type must be BUY_LIMIT or SELL_LIMIT")

        numbers = {
            field: self._positive_float(request[field], field)
            for field in ("volume", "price", "sl", "tp")
        }
        if not math.isclose(
            numbers["volume"],
            self.config.volume,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise MT5BrokerError("volume must match configured MT5 volume")

        if request["magic"] != self.config.magic:
            raise MT5BrokerError("magic must match configured MT5 magic")
        if request["deviation"] != self.config.deviation:
            raise MT5BrokerError("deviation must match configured MT5 deviation")
        return {**request, **numbers}

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
    def _positive_ticket(value: Any, name: str) -> int:
        if isinstance(value, bool):
            raise MT5BrokerError(f"{name} ticket must be a positive number")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise MT5BrokerError(f"{name} ticket must be a positive number") from exc
        if not math.isfinite(number) or number <= 0 or not number.is_integer():
            raise MT5BrokerError(f"{name} ticket must be a positive number")
        return int(number)

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

    def shutdown(self) -> None:
        if self._mt5 is None:
            return
        shutdown = getattr(self._mt5, "shutdown", None)
        if callable(shutdown):
            shutdown()
