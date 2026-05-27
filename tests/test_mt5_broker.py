from types import SimpleNamespace

import pytest

from tradingagents.brokers.mt5 import MT5Broker, MT5BrokerError, MT5ConnectionConfig


class FakeMT5:
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
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
        self.order_retcode = self.TRADE_RETCODE_DONE

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
            retcode=self.order_retcode, order=111222, deal=0, comment="ok"
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


def _valid_pending_request():
    return {
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


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("action", "TRADE_ACTION_DEAL", "action must be TRADE_ACTION_PENDING"),
        ("action", FakeMT5.TRADE_ACTION_PENDING, "action must be symbolic"),
        ("symbol", "EURUSD", "symbol must match configured MT5 symbol"),
        ("type", "BUY_STOP", "type must be BUY_LIMIT or SELL_LIMIT"),
        ("type", FakeMT5.ORDER_TYPE_BUY_LIMIT, "type must be symbolic"),
    ),
)
def test_mt5_broker_rejects_unsafe_pending_order_fields(field, value, match):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    request = _valid_pending_request()
    request[field] = value

    with pytest.raises(MT5BrokerError, match=match):
        broker.place_pending_order(request)

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_pending_order_missing_required_field():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    request = _valid_pending_request()
    del request["price"]

    with pytest.raises(MT5BrokerError, match="missing required MT5 request field: price"):
        broker.place_pending_order(request)

    assert fake_mt5.sent_requests == []


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("volume", 0, "volume must be positive and finite"),
        ("volume", float("nan"), "volume must be positive and finite"),
        ("price", -1, "price must be positive and finite"),
        ("price", float("inf"), "price must be positive and finite"),
        ("sl", 0, "sl must be positive and finite"),
        ("tp", float("-inf"), "tp must be positive and finite"),
    ),
)
def test_mt5_broker_rejects_bad_pending_order_numbers(field, value, match):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    request = _valid_pending_request()
    request[field] = value

    with pytest.raises(MT5BrokerError, match=match):
        broker.place_pending_order(request)

    assert fake_mt5.sent_requests == []


@pytest.mark.parametrize(
    ("field", "config_value", "match"),
    (
        ("deviation", {"deviation": 30}, "deviation must match configured MT5 deviation"),
        ("magic", {"magic": 123}, "magic must match configured MT5 magic"),
    ),
)
def test_mt5_broker_rejects_pending_order_guard_mismatch(
    field, config_value, match
):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        **config_value,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match=match):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_accepts_placed_retcode():
    fake_mt5 = FakeMT5()
    fake_mt5.order_retcode = FakeMT5.TRADE_RETCODE_PLACED
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is True
    assert result["retcode"] == FakeMT5.TRADE_RETCODE_PLACED


def test_mt5_broker_reports_non_success_retcode_with_last_error():
    fake_mt5 = FakeMT5()
    fake_mt5.order_retcode = 10030
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is False
    assert result["retcode"] == 10030
    assert result["last_error"] == (0, "ok")


def test_mt5_broker_rejects_unknown_symbolic_request_value():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(
        MT5BrokerError, match="unknown MT5 request type_time value: ORDER_TIME_DAY"
    ):
        broker._materialize_request(
            {
                "action": "TRADE_ACTION_PENDING",
                "type": "BUY_LIMIT",
                "type_time": "ORDER_TIME_DAY",
                "type_filling": "ORDER_FILLING_RETURN",
            }
        )


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


@pytest.mark.parametrize("ticket", (0, -1, "abc", None))
def test_mt5_broker_rejects_invalid_cancel_ticket(ticket):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match="order ticket must be a positive number"):
        broker.cancel_order(ticket)

    assert fake_mt5.sent_requests == []


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


@pytest.mark.parametrize("ticket", (0, -1, "abc", None))
def test_mt5_broker_rejects_invalid_modify_position_ticket(ticket):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match="position ticket must be a positive number"):
        broker.modify_position_stops(ticket, 2447.99, 2456.79)

    assert fake_mt5.sent_requests == []


@pytest.mark.parametrize(
    ("stop_loss", "take_profit", "match"),
    (
        (0, 2456.79, "stop_loss must be positive and finite"),
        (-1, 2456.79, "stop_loss must be positive and finite"),
        (float("nan"), 2456.79, "stop_loss must be positive and finite"),
        (2447.99, 0, "take_profit must be positive and finite"),
        (2447.99, -1, "take_profit must be positive and finite"),
        (2447.99, float("inf"), "take_profit must be positive and finite"),
    ),
)
def test_mt5_broker_rejects_invalid_modify_position_stops(
    stop_loss, take_profit, match
):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match=match):
        broker.modify_position_stops(222333, stop_loss, take_profit)

    assert fake_mt5.sent_requests == []


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
