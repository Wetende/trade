"""MetaTrader 5 demo-account connection probe.

This adapter intentionally starts with read-only account and symbol checks.
Order placement can be layered on after the terminal connection, symbol specs,
and server time are verified.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any


class MT5BrokerError(RuntimeError):
    """Raised when the MT5 terminal bridge cannot connect or inspect symbols."""


@dataclass(frozen=True)
class MT5ConnectionConfig:
    login: int
    password: str
    server: str
    symbol: str = "XAUUSD"
    terminal_path: str | None = None

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

        return cls(
            login=login,
            password=os.environ["TRADINGAGENTS_MT5_PASSWORD"],
            server=os.environ["TRADINGAGENTS_MT5_SERVER"],
            symbol=os.environ.get("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD"),
            terminal_path=os.environ.get("TRADINGAGENTS_MT5_PATH") or None,
        )


def _asdict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "_asdict"):
        return dict(value._asdict())
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


class MT5Broker:
    def __init__(self, config: MT5ConnectionConfig, mt5_module: Any | None = None):
        self.config = config
        self._mt5 = mt5_module

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

    def shutdown(self) -> None:
        if self._mt5 is None:
            return
        shutdown = getattr(self._mt5, "shutdown", None)
        if callable(shutdown):
            shutdown()
