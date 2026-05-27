from types import SimpleNamespace

import pytest

from tradingagents.brokers.mt5 import MT5Broker, MT5BrokerError, MT5ConnectionConfig


class FakeMT5:
    def __init__(self):
        self.initialized_with = None
        self.selected_symbols = []
        self.shutdown_called = False

    def initialize(self, **kwargs):
        self.initialized_with = kwargs
        return True

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return SimpleNamespace(
            login=123456789,
            server="ExampleBroker-Demo",
            name="Example Demo",
            company="Example Broker Limited",
            currency="USD",
            leverage=100,
            balance=100000.0,
            equity=100000.0,
        )

    def symbol_select(self, symbol, visible):
        self.selected_symbols.append((symbol, visible))
        return True

    def symbol_info(self, symbol):
        return SimpleNamespace(
            description="Gold vs US Dollar",
            digits=2,
            point=0.01,
            spread=33,
            trade_contract_size=100.0,
            trade_tick_size=0.01,
            trade_tick_value=1.0,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=4506.99, ask=4507.32, time=1779610000)

    def shutdown(self):
        self.shutdown_called = True


def test_mt5_config_reads_valetax_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD")

    config = MT5ConnectionConfig.from_env()

    assert config.login == 123456789
    assert config.server == "ExampleBroker-Demo"
    assert config.symbol == "XAUUSD"


def test_mt5_config_reads_demo_execution_guards(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD")
    monkeypatch.setenv("TRADINGAGENTS_MT5_ACCOUNT_MODE", "demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_VOLUME", "0.01")
    monkeypatch.setenv("TRADINGAGENTS_MT5_DEVIATION", "20")
    monkeypatch.setenv("TRADINGAGENTS_MT5_MAGIC", "150015")

    config = MT5ConnectionConfig.from_env()

    assert config.account_mode == "demo"
    assert config.expected_login == 123456789
    assert config.expected_server == "ExampleBroker-Demo"
    assert config.volume == 0.01
    assert config.deviation == 20
    assert config.magic == 150015


def test_mt5_config_rejects_non_demo_execution_mode(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_ACCOUNT_MODE", "live")

    with pytest.raises(MT5BrokerError, match="demo mode is required"):
        MT5ConnectionConfig.from_env()


def test_mt5_config_requires_credentials(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_MT5_LOGIN", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_MT5_PASSWORD", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_MT5_SERVER", raising=False)

    with pytest.raises(MT5BrokerError, match="Missing MT5 environment variables"):
        MT5ConnectionConfig.from_env()


def test_mt5_broker_connects_and_reads_symbol_specs():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )

    result = MT5Broker(config, mt5_module=fake_mt5).connect()

    assert fake_mt5.initialized_with["login"] == 123456789
    assert fake_mt5.selected_symbols == [("XAUUSD", True)]
    assert result["connected"] is True
    assert result["account"]["server"] == "ExampleBroker-Demo"
    assert result["symbol"]["name"] == "XAUUSD"
    assert result["symbol"]["volume_min"] == 0.01
