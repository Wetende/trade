from types import SimpleNamespace

import pytest

from tradingagents.brokers.mt5 import MT5Broker, MT5BrokerError, MT5ConnectionConfig


class FakeMT5:
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    TRADE_ACTION_SLTP = 6
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
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
        self.account_login = 123456789
        self.account_server = "ExampleBroker-Demo"
        self.account_trade_mode = self.ACCOUNT_TRADE_MODE_DEMO
        self.terminal_connected = True
        self.result_request = None
        self.order_send_returns_none = False

    def initialize(self, **kwargs):
        self.initialized_with = kwargs
        return True

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return SimpleNamespace(
            login=self.account_login,
            server=self.account_server,
            name="Example Demo",
            company="Example Broker Limited",
            currency="USD",
            leverage=100,
            balance=100000.0,
            equity=100000.0,
            trade_mode=self.account_trade_mode,
        )

    def terminal_info(self):
        return SimpleNamespace(connected=self.terminal_connected)

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
        if self.order_send_returns_none:
            return None
        result_request = self.result_request
        if result_request == "echo":
            result_request = SimpleNamespace(**request)
        return SimpleNamespace(
            retcode=self.order_retcode,
            order=111222,
            deal=0,
            comment="ok",
            request=result_request,
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


def test_mt5_config_defaults_direct_expected_account_guards():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
    )

    assert config.expected_login == 123456789
    assert config.expected_server == "ExampleBroker-Demo"


def test_mt5_config_normalizes_direct_integer_guards():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        deviation="20",
        magic="150015",
    )

    assert config.deviation == 20
    assert config.magic == 150015
    assert isinstance(config.deviation, int)
    assert isinstance(config.magic, int)


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
    assert result["request"] == fake_mt5.sent_requests[0]
    assert result["request"]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert result["request"]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT
    assert result["request"]["type_time"] == FakeMT5.ORDER_TIME_GTC
    assert result["request"]["type_filling"] == FakeMT5.ORDER_FILLING_RETURN
    assert isinstance(result["request"]["volume"], float)
    assert isinstance(result["request"]["price"], float)
    assert isinstance(result["request"]["sl"], float)
    assert isinstance(result["request"]["tp"], float)


def test_mt5_broker_rejects_order_send_before_connect():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match="MT5 broker is not connected"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


@pytest.mark.parametrize(
    ("method_name", "args"),
    (
        ("cancel_order", (111222,)),
        ("modify_position_stops", (222333, 2447.99, 2456.79)),
    ),
)
def test_mt5_broker_rejects_management_order_send_before_connect(
    method_name, args
):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match="MT5 broker is not connected"):
        getattr(broker, method_name)(*args)

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rechecks_expected_account_before_order_send():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        expected_login=123456789,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    fake_mt5.account_login = 987654321

    with pytest.raises(MT5BrokerError, match="unexpected MT5 account login"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_real_account_on_connect():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )

    with pytest.raises(MT5BrokerError, match="MT5 demo account is required"):
        MT5Broker(config, mt5_module=fake_mt5).connect()

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rechecks_demo_account_before_order_send():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL

    with pytest.raises(MT5BrokerError, match="MT5 demo account is required"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_disconnected_terminal_before_order_send():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    fake_mt5.terminal_connected = False

    with pytest.raises(MT5BrokerError, match="MT5 terminal is not connected"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_order_send_after_shutdown():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    broker.shutdown()

    with pytest.raises(MT5BrokerError, match="MT5 broker is not connected"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.shutdown_called is True
    assert fake_mt5.sent_requests == []


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
        ("type_time", FakeMT5.ORDER_TIME_GTC, "type_time must be symbolic"),
        (
            "type_filling",
            FakeMT5.ORDER_FILLING_RETURN,
            "type_filling must be symbolic",
        ),
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


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("type_time", "TRADE_ACTION_REMOVE", "unknown MT5 request type_time value"),
        ("type_filling", "ORDER_TIME_GTC", "unknown MT5 request type_filling value"),
        ("type", "ORDER_TIME_GTC", "type must be BUY_LIMIT or SELL_LIMIT"),
    ),
)
def test_mt5_broker_rejects_symbolic_values_for_wrong_field(field, value, match):
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


def test_mt5_broker_rejects_pending_order_extra_fields():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    request = _valid_pending_request()
    request["position"] = 222333

    with pytest.raises(MT5BrokerError, match="unexpected MT5 request field: position"):
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
        ("volume", True, "volume must be positive and finite"),
        ("price", False, "price must be positive and finite"),
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


def test_mt5_broker_normalizes_pending_order_numbers_before_send():
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
    request = _valid_pending_request()
    request.update(
        {
            "volume": "0.01",
            "price": "2450.12",
            "sl": "2447.99",
            "tp": "2456.79",
        }
    )

    result = broker.place_pending_order(request)

    assert result["request"]["volume"] == 0.01
    assert result["request"]["price"] == 2450.12
    assert result["request"]["sl"] == 2447.99
    assert result["request"]["tp"] == 2456.79
    assert all(
        isinstance(result["request"][field], float)
        for field in ("volume", "price", "sl", "tp")
    )


def test_mt5_broker_normalizes_magic_and_deviation_before_send():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    request = _valid_pending_request()
    request["magic"] = "150015"
    request["deviation"] = "20"

    result = broker.place_pending_order(request)

    assert result["request"]["magic"] == 150015
    assert result["request"]["deviation"] == 20
    assert isinstance(result["request"]["magic"], int)
    assert isinstance(result["request"]["deviation"], int)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("magic", True, "magic must be an integer"),
        ("deviation", False, "deviation must be an integer"),
        ("magic", "150015.0", "magic must be an integer"),
        ("deviation", -1, "deviation must match configured MT5 deviation"),
    ),
)
def test_mt5_broker_rejects_invalid_integer_guards(field, value, match):
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
    ("order_type", "price", "sl", "tp", "match"),
    (
        ("BUY_LIMIT", 2450.12, 2451.00, 2456.79, "invalid BUY levels"),
        ("BUY_LIMIT", 2450.12, 2447.99, 2449.00, "invalid BUY levels"),
        ("SELL_LIMIT", 2450.12, 2451.00, 2456.79, "invalid SELL levels"),
        ("SELL_LIMIT", 2450.12, 2449.00, 2448.00, "invalid SELL levels"),
    ),
)
def test_mt5_broker_rejects_invalid_pending_level_ordering(
    order_type, price, sl, tp, match
):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    request = _valid_pending_request()
    request.update({"type": order_type, "price": price, "sl": sl, "tp": tp})

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


def test_mt5_broker_rejects_pending_order_volume_mismatch():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.02,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match="volume must match configured MT5 volume"):
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
    broker.connect()

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
    broker.connect()

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is False
    assert result["retcode"] == 10030
    assert result["last_error"] == (0, "ok")
    assert result["request"] == fake_mt5.sent_requests[0]
    assert result["request"]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert result["request"]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT
    assert result["request"]["type_time"] == FakeMT5.ORDER_TIME_GTC
    assert result["request"]["type_filling"] == FakeMT5.ORDER_FILLING_RETURN


def test_mt5_broker_reports_order_send_none_as_structured_failure():
    fake_mt5 = FakeMT5()
    fake_mt5.order_send_returns_none = True
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is False
    assert result["retcode"] is None
    assert result["order"] is None
    assert result["deal"] is None
    assert result["comment"] is None
    assert result["last_error"] == (0, "ok")
    assert result["request"] == fake_mt5.sent_requests[0]


def test_mt5_broker_prefers_result_request_echo_when_available():
    fake_mt5 = FakeMT5()
    fake_mt5.result_request = SimpleNamespace(
        action=FakeMT5.TRADE_ACTION_PENDING,
        symbol="XAUUSD",
        volume=0.01,
        type=FakeMT5.ORDER_TYPE_BUY_LIMIT,
        price=2450.12,
        sl=2447.99,
        tp=2456.79,
        deviation=20,
        magic=150015,
        comment="server echo",
        type_time=FakeMT5.ORDER_TIME_GTC,
        type_filling=FakeMT5.ORDER_FILLING_RETURN,
    )
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(_valid_pending_request())

    assert result["request"] != fake_mt5.sent_requests[0]
    assert result["request"]["comment"] == "server echo"
    assert result["request"]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert result["request"]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT


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


def test_mt5_broker_wraps_missing_mt5_constants():
    class MissingPendingActionMT5(FakeMT5):
        @property
        def TRADE_ACTION_PENDING(self):
            raise AttributeError("TRADE_ACTION_PENDING")

    fake_mt5 = MissingPendingActionMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match="missing MT5 constant: TRADE_ACTION_PENDING"):
        broker._materialize_request({"action": "TRADE_ACTION_PENDING"})


def test_mt5_broker_wraps_missing_demo_trade_mode_constant():
    class MissingDemoModeMT5(FakeMT5):
        def __init__(self):
            self.initialized_with = None
            self.selected_symbols = []
            self.shutdown_called = False
            self.sent_requests = []
            self.order_retcode = self.TRADE_RETCODE_DONE
            self.account_login = 123456789
            self.account_server = "ExampleBroker-Demo"
            self.account_trade_mode = 0
            self.terminal_connected = True
            self.result_request = None
            self.order_send_returns_none = False

        @property
        def ACCOUNT_TRADE_MODE_DEMO(self):
            raise AttributeError("ACCOUNT_TRADE_MODE_DEMO")

    fake_mt5 = MissingDemoModeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )

    with pytest.raises(MT5BrokerError, match="missing MT5 constant: ACCOUNT_TRADE_MODE_DEMO"):
        MT5Broker(config, mt5_module=fake_mt5).connect()


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("action", FakeMT5.TRADE_ACTION_PENDING, "action must be symbolic"),
        ("type", FakeMT5.ORDER_TYPE_BUY_LIMIT, "type must be symbolic"),
        ("type_time", FakeMT5.ORDER_TIME_GTC, "type_time must be symbolic"),
        (
            "type_filling",
            FakeMT5.ORDER_FILLING_RETURN,
            "type_filling must be symbolic",
        ),
    ),
)
def test_mt5_broker_rejects_raw_symbolic_field_materialization(
    field, value, match
):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    request = {
        "action": "TRADE_ACTION_PENDING",
        "type": "BUY_LIMIT",
        "type_time": "ORDER_TIME_GTC",
        "type_filling": "ORDER_FILLING_RETURN",
    }
    request[field] = value

    with pytest.raises(MT5BrokerError, match=match):
        broker._materialize_request(request)


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


def test_mt5_broker_cancel_rejects_placed_retcode():
    fake_mt5 = FakeMT5()
    fake_mt5.order_retcode = FakeMT5.TRADE_RETCODE_PLACED
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.cancel_order(111222)

    assert result["ok"] is False
    assert result["retcode"] == FakeMT5.TRADE_RETCODE_PLACED
    assert result["last_error"] == (0, "ok")


def test_mt5_broker_preserves_large_integer_ticket_exactly():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    ticket = 1234567890123456789

    result = broker.cancel_order(str(ticket))

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["order"] == ticket


@pytest.mark.parametrize("ticket", (0, -1, "abc", None, True, 1.5, 123.0, "1.5"))
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


def test_mt5_broker_modify_stops_rejects_placed_retcode():
    fake_mt5 = FakeMT5()
    fake_mt5.order_retcode = FakeMT5.TRADE_RETCODE_PLACED
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.modify_position_stops(222333, 2447.99, 2456.79)

    assert result["ok"] is False
    assert result["retcode"] == FakeMT5.TRADE_RETCODE_PLACED
    assert result["last_error"] == (0, "ok")


@pytest.mark.parametrize("ticket", (0, -1, "abc", None, False, 2.25, 123.0, "2.25"))
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
