from types import SimpleNamespace

import pytest

from tradingagents.brokers.mt5 import MT5Broker, MT5BrokerError, MT5ConnectionConfig


class FakeMT5:
    TRADE_RETCODE_DONE = 10009
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2

    def __init__(self):
        self.initialized_with = None
        self.selected_symbols = []
        self.shutdown_called = False
        self.sent_requests = []

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

    def order_send(self, request):
        self.sent_requests.append(request)
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE, order=111222, deal=0, comment="ok"
        )

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


def test_mt5_config_normalizes_direct_demo_account_mode():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        account_mode=" DEMO ",
    )

    assert config.account_mode == "demo"


def test_mt5_config_preserves_zero_execution_guard_values(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_DEVIATION", "0")
    monkeypatch.setenv("TRADINGAGENTS_MT5_MAGIC", "0")

    config = MT5ConnectionConfig.from_env()

    assert config.deviation == 0
    assert config.magic == 0


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("TRADINGAGENTS_MT5_VOLUME", "not-a-number"),
        ("TRADINGAGENTS_MT5_DEVIATION", "not-a-number"),
        ("TRADINGAGENTS_MT5_MAGIC", "not-a-number"),
    ),
)
def test_mt5_config_rejects_invalid_numeric_env_values(monkeypatch, name, value):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv(name, value)

    with pytest.raises(MT5BrokerError, match=f"{name} must be numeric"):
        MT5ConnectionConfig.from_env()


@pytest.mark.parametrize("value", ("nan", "inf", "-inf", "0", "-0.01"))
def test_mt5_config_rejects_non_positive_or_non_finite_volume_env(
    monkeypatch, value
):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_VOLUME", value)

    with pytest.raises(MT5BrokerError, match="MT5 volume must be positive"):
        MT5ConnectionConfig.from_env()


def test_mt5_config_rejects_non_demo_execution_mode(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_ACCOUNT_MODE", "live")

    with pytest.raises(MT5BrokerError, match="demo mode is required"):
        MT5ConnectionConfig.from_env()


def test_mt5_config_rejects_direct_non_demo_execution_mode():
    with pytest.raises(MT5BrokerError, match="demo mode is required"):
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            account_mode="live",
        )


@pytest.mark.parametrize(
    "volume", (float("nan"), float("inf"), float("-inf"), 0, -0.01)
)
def test_mt5_config_rejects_direct_invalid_volume(volume):
    with pytest.raises(MT5BrokerError, match="MT5 volume must be positive"):
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            volume=volume,
        )


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


def test_mt5_broker_sends_pending_order_request():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.01,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(
        {
            "action": "TRADE_ACTION_PENDING",
            "symbol": "XAUUSD",
            "volume": 0.01,
            "type": "BUY_LIMIT",
            "price": 2450.12,
            "sl": 2447.99,
            "tp": 2456.79,
            "deviation": 20,
            "magic": 150015,
            "comment": "TradingAgents demo",
            "type_time": "ORDER_TIME_GTC",
            "type_filling": "ORDER_FILLING_RETURN",
        }
    )

    assert result["ok"] is True
    assert result["order"] == 111222
    assert fake_mt5.sent_requests[0]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert fake_mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT


def test_mt5_broker_cancels_order():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.cancel_order(111222)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["action"] == FakeMT5.TRADE_ACTION_REMOVE
    assert fake_mt5.sent_requests[-1]["order"] == 111222


def test_mt5_broker_modifies_position_stops():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.modify_position_stops(222333, 2447.99, 2456.79)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["action"] == FakeMT5.TRADE_ACTION_SLTP
    assert fake_mt5.sent_requests[-1]["position"] == 222333
    assert fake_mt5.sent_requests[-1]["sl"] == 2447.99
    assert fake_mt5.sent_requests[-1]["tp"] == 2456.79


def test_mt5_broker_rejects_unexpected_account_login():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        expected_login=987654321,
        expected_server="ExampleBroker-Demo",
    )

    with pytest.raises(MT5BrokerError, match="unexpected MT5 account login"):
        MT5Broker(config, mt5_module=fake_mt5).connect()


def test_mt5_broker_rejects_unexpected_account_server():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        expected_login=123456789,
        expected_server="OtherBroker-Demo",
    )

    with pytest.raises(MT5BrokerError, match="unexpected MT5 account server"):
        MT5Broker(config, mt5_module=fake_mt5).connect()
