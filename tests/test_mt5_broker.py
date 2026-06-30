from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5 import (
    MT5Broker,
    MT5BrokerError,
    MT5ConnectionConfig,
    MT5OrderRequestBuilder,
)


class FakeMT5:
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    TRADE_ACTION_SLTP = 6
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    ACCOUNT_TRADE_MODE_REAL = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_TIME_SPECIFIED = 2
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TIMEFRAME_M1 = 1
    TIMEFRAME_M3 = 3
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60
    TIMEFRAME_D1 = 1440

    def __init__(self):
        self.initialized_with = None
        self.selected_symbols = []
        self.shutdown_called = False
        self.sent_requests = []
        self.rates = []
        self.copy_rates_calls = []
        self.order_retcode = self.TRADE_RETCODE_DONE
        self.order_check_retcode = self.TRADE_RETCODE_DONE
        self.account = SimpleNamespace(
            login=123456789,
            server="ExampleBroker-Demo",
            trade_mode=self.ACCOUNT_TRADE_MODE_DEMO,
        )
        self.terminal_connected = True
        self.result_request = None
        self.order_send_returns_none = False
        self.order_check_returns_none = False
        self.deal_results_by_filling = {}
        self.history_deals = []
        self.history_deals_calls = []
        self.checked_requests = []
        self.terminal_trade_allowed = True
        self.terminal_tradeapi_disabled = False
        self.account_trade_allowed = True
        self.account_trade_expert = True
        self.orders = [
            SimpleNamespace(ticket=111222, symbol="XAUUSD", price_open=2450.12)
        ]
        self.positions = [
            SimpleNamespace(
                ticket=333444,
                symbol="XAUUSD",
                type=self.POSITION_TYPE_BUY,
                price_open=2450.12,
                price_current=2453.12,
                sl=2447.99,
                tp=2456.79,
            )
        ]

    def initialize(self, **kwargs):
        self.initialized_with = kwargs
        self.account_login = kwargs["login"]
        self.account_server = kwargs["server"]
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
            trade_allowed=getattr(self, "account_trade_allowed", True),
            trade_expert=getattr(self, "account_trade_expert", True),
        )

    @property
    def account_login(self):
        return self.account.login

    @account_login.setter
    def account_login(self, value):
        if not hasattr(self, "account"):
            self.account = SimpleNamespace()
        self.account.login = value

    @property
    def account_server(self):
        return self.account.server

    @account_server.setter
    def account_server(self, value):
        if not hasattr(self, "account"):
            self.account = SimpleNamespace()
        self.account.server = value

    @property
    def account_trade_mode(self):
        return self.account.trade_mode

    @account_trade_mode.setter
    def account_trade_mode(self, value):
        if not hasattr(self, "account"):
            self.account = SimpleNamespace()
        self.account.trade_mode = value

    def terminal_info(self):
        return SimpleNamespace(
            connected=self.terminal_connected,
            trade_allowed=self.terminal_trade_allowed,
            tradeapi_disabled=self.terminal_tradeapi_disabled,
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
            trade_stops_level=50,
            trade_freeze_level=20,
            volume_min=0.01,
            volume_max=100.0,
            volume_step=0.01,
            filling_mode=self.ORDER_FILLING_IOC,
        )

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=4506.99, ask=4507.32, time=1779610000)

    def order_send(self, request):
        self.sent_requests.append(request)
        if self.order_send_returns_none:
            return None
        retcode = self.order_retcode
        comment = "ok"
        if (
            request.get("action") == self.TRADE_ACTION_DEAL
            and self.deal_results_by_filling
        ):
            fill_result = self.deal_results_by_filling.get(request.get("type_filling"))
            if fill_result is not None:
                retcode, comment = fill_result
        result_request = self.result_request
        if result_request == "echo":
            result_request = SimpleNamespace(**request)
        return SimpleNamespace(
            retcode=retcode,
            order=111222,
            deal=0,
            comment=comment,
            request=result_request,
        )

    def order_check(self, request):
        self.checked_requests.append(request)
        if self.order_check_returns_none:
            return None
        return SimpleNamespace(
            retcode=self.order_check_retcode,
            balance=100000.0,
            equity=100000.0,
            margin=1000.0,
            margin_free=99000.0,
            comment="check ok",
            request=SimpleNamespace(**request),
        )

    def shutdown(self):
        self.shutdown_called = True

    def orders_get(self, symbol=None):
        return [order for order in self.orders if symbol is None or order.symbol == symbol]

    def positions_get(self, symbol=None):
        return [
            position
            for position in self.positions
            if symbol is None or position.symbol == symbol
        ]

    def history_deals_get(self, date_from, date_to, group=None):
        self.history_deals_calls.append((date_from, date_to, group))
        return self.history_deals

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        self.copy_rates_calls.append((symbol, timeframe, start_pos, count))
        return self.rates


def _set_required_mt5_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Server")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_SERVER", "ExampleBroker-Server")


def test_mt5_config_from_env_does_not_require_account_or_execution_mode(monkeypatch):
    _set_required_mt5_env(monkeypatch)

    config = MT5ConnectionConfig.from_env()

    assert not hasattr(config, "account_mode")
    assert not hasattr(config, "execution_mode")
    assert config.allow_real_orders is False
    assert config.require_demo_account is True


def test_mt5_config_reads_real_order_acknowledgement(monkeypatch):
    _set_required_mt5_env(monkeypatch)
    monkeypatch.setenv(
        "TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS",
        "I_UNDERSTAND_REAL_MONEY_IS_AT_RISK",
    )

    config = MT5ConnectionConfig.from_env()

    assert config.allow_real_orders is True


def test_mt5_config_rejects_direct_non_bool_allow_real_orders():
    with pytest.raises(MT5BrokerError, match="allow_real_orders must be a boolean"):
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Real",
            allow_real_orders="false",
        )


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
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_VOLUME", "0.01")
    monkeypatch.setenv("TRADINGAGENTS_MT5_DEVIATION", "20")
    monkeypatch.setenv("TRADINGAGENTS_MT5_MAGIC", "150015")
    monkeypatch.setenv("TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS", "8.5")

    config = MT5ConnectionConfig.from_env()

    assert config.expected_login == 123456789
    assert config.expected_server == "ExampleBroker-Demo"
    assert config.volume == 0.01
    assert config.deviation == 20
    assert config.magic == 150015
    assert config.max_entry_distance_points == 8.5


def test_mt5_config_reads_min_stop_distance_guards(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE", "2.5")
    monkeypatch.setenv("TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE", "4")

    config = MT5ConnectionConfig.from_env()

    assert config.min_stop_distance_price == 2.5
    assert config.min_stop_spread_multiple == 4.0


def test_mt5_config_accepts_direct_connection_without_mode_fields():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
    )

    assert not hasattr(config, "account_mode")
    assert not hasattr(config, "execution_mode")
    assert config.expected_login == 123456789


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


def test_mt5_request_builder_uses_configured_order_comment():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        order_comment="TradingAgents contest",
    )
    proposal = OrderProposal(
        symbol="XAUUSD",
        side=TradeAction.BUY,
        entry_price=2450.12,
        stop_loss=2447.99,
        take_profit=2456.79,
        valid_until="2026-05-28T12:00:00Z",
        status=OrderStatus.PROPOSED,
        reason="test setup",
    )

    request = MT5OrderRequestBuilder(config).build_pending_limit_request(
        proposal,
        {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.01},
    )

    assert request["comment"] == "TradingAgents contest"


def test_mt5_request_builder_defaults_one_minute_orders_to_gtc():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    proposal = OrderProposal(
        symbol="XAUUSD",
        broker_symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="AUTO",
        entry_price=2450.12,
        stop_loss=2447.99,
        take_profit=2456.79,
        valid_until="2026-05-28T12:00:00Z",
        activation_window_minutes=1,
        cancel_if_not_triggered_after="2026-05-28T12:01:00Z",
        timeframe="1m",
        confirmation_timeframe="1m",
        status=OrderStatus.PROPOSED,
        reason="one-minute setup",
    )

    request = MT5OrderRequestBuilder(config).build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_stops_level": 1,
            "bid": 2450.20,
            "ask": 2450.40,
        },
    )

    assert request["type_time"] == "ORDER_TIME_GTC"
    assert "expiration" not in request


def test_mt5_request_builder_can_opt_into_server_expiration():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        use_server_expiration=True,
    )
    proposal = OrderProposal(
        symbol="XAUUSD",
        broker_symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="AUTO",
        entry_price=2450.12,
        stop_loss=2447.99,
        take_profit=2456.79,
        valid_until="2026-05-28T12:00:00Z",
        activation_window_minutes=1,
        cancel_if_not_triggered_after="2026-05-28T12:01:00Z",
        timeframe="1m",
        confirmation_timeframe="1m",
        status=OrderStatus.PROPOSED,
        reason="one-minute setup",
    )

    request = MT5OrderRequestBuilder(config).build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_stops_level": 1,
            "bid": 2450.20,
            "ask": 2450.40,
        },
    )

    assert request["type_time"] == "ORDER_TIME_SPECIFIED"
    assert request["expiration"] == 1779969660


def test_mt5_broker_materializes_specified_pending_order_expiration():
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
            "comment": "TradingAgents",
            "type_time": "ORDER_TIME_SPECIFIED",
            "expiration": 1779969660,
            "type_filling": "ORDER_FILLING_RETURN",
        }
    )

    assert result["ok"] is True
    assert result["request"]["type_time"] == FakeMT5.ORDER_TIME_SPECIFIED
    assert result["request"]["expiration"] == 1779969660


def test_mt5_request_builder_rejects_stop_distance_below_gold_guard():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        min_stop_distance_price=2.5,
        min_stop_spread_multiple=4.0,
    )
    proposal = OrderProposal(
        symbol="XAUUSD",
        broker_symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="AUTO",
        entry_price=4460.87,
        stop_loss=4460.35,
        take_profit=4462.42,
        valid_until="2026-06-03 06:30 EDT",
        status=OrderStatus.PROPOSED,
        reason="too tight stop",
    )

    with pytest.raises(ValueError, match="stop distance is below minimum"):
        MT5OrderRequestBuilder(config).build_pending_order_request(
            proposal,
            {
                "name": "XAUUSD",
                "digits": 2,
                "point": 0.01,
                "trade_tick_size": 0.01,
                "trade_stops_level": 1,
                "bid": 4460.50,
                "ask": 4460.83,
            },
        )


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
        ("TRADINGAGENTS_MT5_DEVIATION", "-1"),
        ("TRADINGAGENTS_MT5_MAGIC", "-1"),
    ),
)
def test_mt5_config_rejects_negative_integer_guard_env_values(
    monkeypatch, name, value
):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv(name, value)

    with pytest.raises(MT5BrokerError, match=f"{name} must be non-negative"):
        MT5ConnectionConfig.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("TRADINGAGENTS_MT5_VOLUME", "not-a-number"),
        ("TRADINGAGENTS_MT5_DEVIATION", "not-a-number"),
        ("TRADINGAGENTS_MT5_MAGIC", "not-a-number"),
        ("TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS", "not-a-number"),
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


@pytest.mark.parametrize("value", ("nan", "inf", "-inf", "-0.01"))
def test_mt5_config_rejects_negative_or_non_finite_entry_distance_env(
    monkeypatch,
    value,
):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS", value)

    with pytest.raises(
        MT5BrokerError,
        match="MT5 max entry distance points must be non-negative",
    ):
        MT5ConnectionConfig.from_env()


@pytest.mark.parametrize(
    ("kwargs", "match"),
    (
        ({"deviation": -1}, "MT5 deviation must be non-negative"),
        ({"magic": -1}, "MT5 magic must be non-negative"),
        ({"deviation": "-1"}, "MT5 deviation must be non-negative"),
        ({"magic": "-1"}, "MT5 magic must be non-negative"),
        (
            {"max_entry_distance_points": -1},
            "MT5 max entry distance points must be non-negative",
        ),
        (
            {"max_entry_distance_points": "-1"},
            "MT5 max entry distance points must be non-negative",
        ),
        ({"deviation": True}, "MT5 deviation must be numeric"),
        ({"magic": False}, "MT5 magic must be numeric"),
        ({"deviation": 1.0}, "MT5 deviation must be numeric"),
        ({"magic": 1.0}, "MT5 magic must be numeric"),
        (
            {"max_entry_distance_points": "not-a-number"},
            "MT5 max entry distance points must be numeric",
        ),
    ),
)
def test_mt5_config_rejects_direct_invalid_integer_guards(kwargs, match):
    with pytest.raises(MT5BrokerError, match=match):
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            **kwargs,
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
    assert result["account"]["trade_mode_label"] == "DEMO"
    assert result["symbol"]["name"] == "XAUUSD"
    assert result["symbol"]["trade_stops_level"] == 50
    assert result["symbol"]["trade_freeze_level"] == 20
    assert result["symbol"]["volume_min"] == 0.01


def test_mt5_broker_reports_detected_real_trade_mode():
    fake = FakeMT5()
    fake.account.trade_mode = fake.ACCOUNT_TRADE_MODE_REAL
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Live",
        expected_server="ExampleBroker-Live",
    )

    result = MT5Broker(config, mt5_module=fake).connect()

    assert result["account"]["login"] == 123456789
    assert result["account"]["trade_mode_label"] == "REAL"


def test_mt5_broker_reports_detected_contest_trade_mode():
    fake = FakeMT5()
    fake.account.trade_mode = fake.ACCOUNT_TRADE_MODE_CONTEST
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Contest",
        expected_server="ExampleBroker-Contest",
    )

    result = MT5Broker(config, mt5_module=fake).connect()

    assert result["account"]["login"] == 123456789
    assert result["account"]["trade_mode_label"] == "CONTEST"


def test_mt5_broker_reads_open_orders_and_positions():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    orders = broker.open_orders("XAUUSD")
    positions = broker.open_positions("XAUUSD")

    assert orders[0]["ticket"] == 111222
    assert orders[0]["symbol"] == "XAUUSD"
    assert positions[0]["ticket"] == 333444
    assert positions[0]["side"] == "BUY"
    assert positions[0]["entry_price"] == 2450.12
    assert positions[0]["current_price"] == 2453.12
    assert positions[0]["stop_loss"] == 2447.99
    assert positions[0]["take_profit"] == 2456.79


def test_mt5_broker_normalizes_position_open_time_from_server_offset():
    fake_mt5 = FakeMT5()
    fake_mt5.positions = [
        SimpleNamespace(
            ticket=333444,
            symbol="XAUUSD",
            type=fake_mt5.POSITION_TYPE_BUY,
            time=1779610000,
            time_msc=1779610000123,
            price_open=2450.12,
            price_current=2453.12,
            sl=2447.99,
            tp=2456.79,
        )
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake_mt5,
    )
    broker.connect()
    broker._server_time_offset_seconds = lambda mt5: 3 * 3600

    positions = broker.open_positions("XAUUSD")

    assert positions[0]["opened_at_utc"] == "2026-05-24T05:06:40.123000+00:00"


def test_mt5_broker_reads_history_deals_for_symbol():
    fake_mt5 = FakeMT5()
    fake_mt5.history_deals = [
        SimpleNamespace(
            ticket=555,
            order=111222,
            position_id=111222,
            symbol="XAUUSD",
            time=1779610000,
            type=fake_mt5.POSITION_TYPE_BUY,
            entry=0,
            volume=0.01,
            price=2450.12,
            profit=0.0,
            commission=0.0,
            swap=0.0,
            magic=150015,
            comment="TradingAgents",
        ),
        SimpleNamespace(
            ticket=556,
            order=111333,
            position_id=111222,
            symbol="XAUUSD",
            time=1779610300,
            type=fake_mt5.POSITION_TYPE_SELL,
            entry=1,
            volume=0.01,
            price=2456.79,
            profit=6.67,
            commission=0.0,
            swap=0.0,
            magic=150015,
            comment="[tp 2456.79]",
        ),
        SimpleNamespace(ticket=777, symbol="EURUSD", position_id=777),
    ]
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker._server_time_offset_seconds = lambda mt5: 3 * 3600
    broker.connect()

    deals = broker.history_deals(
        "XAUUSD",
        datetime.fromtimestamp(1779609900, tz=timezone.utc),
        datetime.fromtimestamp(1779610400, tz=timezone.utc),
    )

    assert fake_mt5.history_deals_calls
    queried_start, queried_end, _group = fake_mt5.history_deals_calls[0]
    assert queried_start.tzinfo is timezone.utc
    assert queried_end.tzinfo is timezone.utc
    assert queried_start == datetime.fromtimestamp(
        1779609900 + 3 * 3600,
        tz=timezone.utc,
    )
    assert queried_end == datetime.fromtimestamp(
        1779610400 + 3 * 3600,
        tz=timezone.utc,
    )
    assert [deal["ticket"] for deal in deals] == [555, 556]
    assert deals[1]["position_id"] == 111222
    assert deals[1]["profit"] == 6.67
    assert deals[1]["time_utc"] == "2026-05-24T05:11:40+00:00"


def test_mt5_broker_fetch_rates_normalizes_mt5_candles():
    fake = FakeMT5()
    fake.rates = [
        {
            "time": 1779613200,
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "tick_volume": 123,
            "spread": 3,
            "real_volume": 0,
        },
        {
            "time": 1779614100,
            "open": 4500.80,
            "high": 4502.00,
            "low": 4500.40,
            "close": 4501.60,
            "tick_volume": 140,
            "spread": 4,
            "real_volume": 0,
        },
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    candles = broker.fetch_rates("15m", count=2)

    assert fake.copy_rates_calls == [("XAUUSD", fake.TIMEFRAME_M15, 0, 2)]
    assert candles == [
        {
            "timestamp": "2026-05-24T09:00:00+00:00",
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "volume": 123.0,
            "spread": 3.0,
            "real_volume": 0.0,
        },
        {
            "timestamp": "2026-05-24T09:15:00+00:00",
            "open": 4500.80,
            "high": 4502.00,
            "low": 4500.40,
            "close": 4501.60,
            "volume": 140.0,
            "spread": 4.0,
            "real_volume": 0.0,
        },
    ]


def test_mt5_broker_fetch_closed_rates_skips_current_bar():
    fake = FakeMT5()
    fake.rates = [
        {
            "time": 1779613200,
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "tick_volume": 123,
            "spread": 3,
            "real_volume": 0,
        },
        {
            "time": 1779614100,
            "open": 4500.80,
            "high": 4502.00,
            "low": 4500.40,
            "close": 4501.60,
            "tick_volume": 140,
            "spread": 4,
            "real_volume": 0,
        },
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    candles = broker.fetch_closed_rates("15m", count=2)

    assert fake.copy_rates_calls == [("XAUUSD", fake.TIMEFRAME_M15, 1, 2)]
    assert len(candles) == 2
    assert candles[0]["spread"] == 3.0
    assert candles[0]["real_volume"] == 0.0


def test_mt5_broker_fetch_rates_supports_one_and_three_minute_timeframes():
    fake = FakeMT5()
    fake.rates = [
        {
            "time": 1779613200,
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "tick_volume": 123,
        }
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    broker.fetch_rates("1m", 1)
    broker.fetch_rates("3m", 1)

    assert fake.copy_rates_calls[-2:] == [
        ("XAUUSD", fake.TIMEFRAME_M1, 0, 1),
        ("XAUUSD", fake.TIMEFRAME_M3, 0, 1),
    ]


def test_mt5_broker_fetch_rates_supports_named_field_rows():
    class NamedFieldRow:
        def __init__(self, values):
            self.values = values

        def __getitem__(self, key):
            return self.values[key]

    fake = FakeMT5()
    fake.rates = [
        NamedFieldRow(
            {
                "time": 1779613200,
                "open": 4500.10,
                "high": 4501.20,
                "low": 4499.50,
                "close": 4500.80,
                "real_volume": 456,
            }
        )
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    candles = broker.fetch_rates("15m", count=1)

    assert candles == [
        {
            "timestamp": "2026-05-24T09:00:00+00:00",
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "volume": 456.0,
            "spread": 0.0,
            "real_volume": 456.0,
        }
    ]


def test_mt5_broker_fetch_rates_adjusts_broker_server_time_offset(monkeypatch):
    fake = FakeMT5()
    fake.rates = [
        {
            "time": 1780455600,
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "tick_volume": 123,
        },
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()
    monkeypatch.setattr(
        broker,
        "_server_time_offset_seconds",
        lambda mt5: 3 * 60 * 60,
    )

    candles = broker.fetch_rates("15m", count=1)

    assert candles[0]["timestamp"] == "2026-06-03T00:00:00+00:00"


def test_mt5_broker_detects_broker_server_time_offset():
    fake = FakeMT5()
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    now_utc = datetime.fromtimestamp(
        fake.symbol_info_tick("XAUUSD").time - (3 * 60 * 60),
        timezone.utc,
    )

    assert broker._server_time_offset_seconds(fake, now_utc=now_utc) == 3 * 60 * 60


@pytest.mark.parametrize("count", (None, True, False, "2", 2.5, 0, -1))
def test_mt5_broker_fetch_rates_rejects_invalid_count(count):
    fake = FakeMT5()
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    with pytest.raises(
        MT5BrokerError, match="MT5 rate count must be a positive integer"
    ):
        broker.fetch_rates("15m", count=count)

    assert fake.copy_rates_calls == []


def test_mt5_broker_fetch_rates_rejects_unsupported_timeframe():
    fake = FakeMT5()
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    with pytest.raises(MT5BrokerError, match="unsupported MT5 timeframe: 5m"):
        broker.fetch_rates("5m", count=1)

    assert fake.copy_rates_calls == []


def test_mt5_broker_fetch_rates_reports_mt5_copy_rates_failure():
    fake = FakeMT5()
    fake.rates = None
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    with pytest.raises(MT5BrokerError, match="MT5 copy_rates_from_pos failed"):
        broker.fetch_rates("15m", count=1)

    assert fake.copy_rates_calls == [("XAUUSD", fake.TIMEFRAME_M15, 0, 1)]


def test_mt5_broker_reads_sell_position_side():
    fake_mt5 = FakeMT5()
    fake_mt5.positions = [
        SimpleNamespace(
            ticket=333445,
            symbol="XAUUSD",
            type=FakeMT5.POSITION_TYPE_SELL,
            price_open=2450.12,
            price_current=2448.12,
            sl=2456.79,
            tp=2447.99,
        )
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake_mt5,
    )
    broker.connect()

    positions = broker.open_positions("XAUUSD")

    assert positions[0]["side"] == "SELL"


def test_mt5_broker_state_reads_require_active_session():
    fake_mt5 = FakeMT5()
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake_mt5,
    )

    with pytest.raises(MT5BrokerError, match="not connected"):
        broker.open_orders("XAUUSD")


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
            "comment": "TradingAgents",
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


def test_mt5_broker_order_check_materializes_pending_request():
    fake_mt5 = FakeMT5()
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake_mt5,
    )
    broker.connect()

    result = broker.check_order(_valid_pending_request())

    assert result["ok"] is True
    assert fake_mt5.checked_requests[0]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert fake_mt5.checked_requests[0]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT
    assert result["request"]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert result["request"]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT


def test_mt5_broker_order_check_reports_rejected_request():
    fake_mt5 = FakeMT5()
    fake_mt5.order_check_retcode = 10030
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake_mt5,
    )
    broker.connect()

    result = broker.check_order(_valid_pending_request())

    assert result["ok"] is False
    assert result["retcode"] == 10030
    assert result["last_error"] == (0, "ok")
    assert fake_mt5.sent_requests == []


def test_mt5_broker_materializes_buy_stop_order():
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
    request.update(
        {
            "type": "BUY_STOP",
            "price": 4510.00,
            "sl": 4508.00,
            "tp": 4515.00,
        }
    )

    result = broker.place_pending_order(request)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_BUY_STOP


def test_mt5_broker_materializes_sell_stop_order():
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
    request.update(
        {
            "type": "SELL_STOP",
            "price": 4500.00,
            "sl": 4502.00,
            "tp": 4495.00,
        }
    )

    result = broker.place_pending_order(request)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_SELL_STOP


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
        ("close_position", ({"ticket": 333444, "side": "BUY", "volume": 0.01},)),
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


def test_mt5_broker_rejects_missing_terminal_info_before_order_send():
    class NoTerminalInfoMT5(FakeMT5):
        terminal_info = None

    fake_mt5 = NoTerminalInfoMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="MT5 terminal_info is unavailable"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_terminal_with_trading_disabled_before_order_send():
    fake_mt5 = FakeMT5()
    fake_mt5.terminal_trade_allowed = False
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="MT5 terminal trading is not allowed"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_terminal_with_trade_api_disabled_before_order_send():
    fake_mt5 = FakeMT5()
    fake_mt5.terminal_tradeapi_disabled = True
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="MT5 terminal trade API is disabled"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_account_with_trading_disabled_before_order_send():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_allowed = False
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="MT5 account trading is not allowed"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_rejects_account_with_expert_trading_disabled_before_order_send():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_expert = False
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="MT5 account expert trading is not allowed"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_mt5_broker_connects_real_account_as_metadata_without_sending():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )

    result = MT5Broker(config, mt5_module=fake_mt5).connect()

    assert result["account"]["trade_mode_label"] == "REAL"
    assert fake_mt5.shutdown_called is False
    assert fake_mt5.sent_requests == []


def test_mt5_broker_shuts_down_after_wrong_account_connect_failure():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        expected_login=987654321,
    )

    with pytest.raises(MT5BrokerError, match="unexpected MT5 account login"):
        MT5Broker(config, mt5_module=fake_mt5).connect()

    assert fake_mt5.shutdown_called is True
    assert fake_mt5.sent_requests == []


def test_mt5_broker_blocks_real_account_before_order_send_without_acknowledgement():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        require_demo_account=False,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL

    with pytest.raises(MT5BrokerError, match="real-money acknowledgement"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_demo_only_guard_rejects_real_account_order_send_even_with_acknowledgement():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        allow_real_orders=True,
        require_demo_account=True,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="demo account"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


def test_demo_only_guard_allows_demo_account_order_send():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        require_demo_account=True,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is True
    assert fake_mt5.sent_requests[0]["action"] == FakeMT5.TRADE_ACTION_PENDING


def test_mt5_broker_allows_real_account_order_with_acknowledgement():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        allow_real_orders=True,
        require_demo_account=False,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is True
    assert fake_mt5.sent_requests[0]["action"] == FakeMT5.TRADE_ACTION_PENDING


@pytest.mark.parametrize(
    ("method_name", "args"),
    (
        ("cancel_order", (111222,)),
        ("modify_position_stops", (222333, 2447.99, 2456.79)),
        ("close_position", ({"ticket": 333444, "side": "BUY", "volume": 0.01},)),
    ),
)
def test_mt5_broker_management_actions_block_real_account_without_acknowledgement(
    method_name, args
):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        require_demo_account=False,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    fake_mt5.account_trade_mode = FakeMT5.ACCOUNT_TRADE_MODE_REAL

    with pytest.raises(MT5BrokerError, match="real-money acknowledgement"):
        getattr(broker, method_name)(*args)

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


@pytest.mark.parametrize(
    ("method_name", "args"),
    (
        ("cancel_order", (111222,)),
        ("modify_position_stops", (222333, 2447.99, 2456.79)),
        ("close_position", ({"ticket": 333444, "side": "BUY", "volume": 0.01},)),
    ),
)
def test_mt5_broker_management_actions_recheck_disconnected_terminal_before_send(
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
    broker.connect()
    fake_mt5.terminal_connected = False

    with pytest.raises(MT5BrokerError, match="MT5 terminal is not connected"):
        getattr(broker, method_name)(*args)

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
        "comment": "TradingAgents",
        "type_time": "ORDER_TIME_GTC",
        "type_filling": "ORDER_FILLING_RETURN",
    }


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("action", "TRADE_ACTION_DEAL", "action must be TRADE_ACTION_PENDING"),
        ("action", FakeMT5.TRADE_ACTION_PENDING, "action must be symbolic"),
        ("symbol", "EURUSD", "symbol must match configured MT5 symbol"),
        ("type", "BUY_MARKET", "type must be BUY_LIMIT, SELL_LIMIT, BUY_STOP, or SELL_STOP"),
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
        ("type", "ORDER_TIME_GTC", "type must be BUY_LIMIT, SELL_LIMIT, BUY_STOP, or SELL_STOP"),
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
        ("magic", -1, "magic must be non-negative"),
        ("deviation", "-1", "deviation must be non-negative"),
        ("deviation", -1, "deviation must be non-negative"),
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


def test_mt5_broker_allows_dynamic_pending_order_volume():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.02,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(_valid_pending_request())

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["volume"] == 0.01


def test_mt5_broker_closes_partial_position_volume():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.close_position(
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.5,
        },
        comment="TA partial 1",
        volume=0.5,
    )

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["position"] == 333444
    assert fake_mt5.sent_requests[-1]["volume"] == 0.5
    assert fake_mt5.sent_requests[-1]["comment"] == "TA partial 1"


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


def test_mt5_broker_reports_unknown_trade_mode_when_mt5_trade_constants_are_missing():
    class MissingTradeModeConstantsMT5(FakeMT5):
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

    fake_mt5 = MissingTradeModeConstantsMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )

    result = MT5Broker(config, mt5_module=fake_mt5).connect()

    assert result["account"]["trade_mode_label"] == "UNKNOWN"


def test_mt5_broker_blocks_order_send_when_trade_mode_is_unknown():
    fake_mt5 = FakeMT5()
    fake_mt5.account_trade_mode = 999
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="trade mode is unknown"):
        broker.place_pending_order(_valid_pending_request())

    assert fake_mt5.sent_requests == []


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


def test_mt5_broker_closes_buy_position_with_market_sell():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.close_position(
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.01,
        },
        comment="straddle early exit",
    )

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["action"] == FakeMT5.TRADE_ACTION_DEAL
    assert fake_mt5.sent_requests[-1]["type"] == FakeMT5.ORDER_TYPE_SELL
    assert fake_mt5.sent_requests[-1]["position"] == 333444
    assert fake_mt5.sent_requests[-1]["volume"] == 0.01
    assert fake_mt5.sent_requests[-1]["price"] == 4506.99
    assert fake_mt5.sent_requests[-1]["comment"] == "straddle early exit"
    assert fake_mt5.sent_requests[-1]["type_filling"] == FakeMT5.ORDER_FILLING_FOK


def test_mt5_broker_sanitizes_long_close_comment_before_order_send():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.close_position(
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.01,
        },
        comment='TradingAgents scalp profit exit "bad"',
    )

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["comment"] == "TradingAgents scalp"
    assert len(fake_mt5.sent_requests[-1]["comment"]) <= 20


def test_mt5_broker_closes_sell_position_with_market_buy():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.close_position(
        {
            "ticket": 333445,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": "0.01",
        }
    )

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["action"] == FakeMT5.TRADE_ACTION_DEAL
    assert fake_mt5.sent_requests[-1]["type"] == FakeMT5.ORDER_TYPE_BUY
    assert fake_mt5.sent_requests[-1]["position"] == 333445
    assert fake_mt5.sent_requests[-1]["volume"] == 0.01
    assert fake_mt5.sent_requests[-1]["price"] == 4507.32
    assert fake_mt5.sent_requests[-1]["type_filling"] == FakeMT5.ORDER_FILLING_FOK


def test_mt5_broker_close_position_retries_next_filling_mode_when_fok_is_rejected():
    fake_mt5 = FakeMT5()
    fake_mt5.deal_results_by_filling = {
        fake_mt5.ORDER_FILLING_FOK: (10030, "Unsupported filling mode"),
        fake_mt5.ORDER_FILLING_IOC: (fake_mt5.TRADE_RETCODE_DONE, "Request executed"),
    }
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.close_position(
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.01,
        }
    )

    assert result["ok"] is True
    assert [request["type_filling"] for request in fake_mt5.sent_requests[-2:]] == [
        fake_mt5.ORDER_FILLING_FOK,
        fake_mt5.ORDER_FILLING_IOC,
    ]
    assert result["filling_attempts"][0]["comment"] == "Unsupported filling mode"
    assert result["request"]["type_filling"] == fake_mt5.ORDER_FILLING_IOC


def test_mt5_broker_close_position_retries_next_filling_mode_on_invalid_request():
    fake_mt5 = FakeMT5()
    fake_mt5.deal_results_by_filling = {
        fake_mt5.ORDER_FILLING_FOK: (10013, "Invalid request"),
        fake_mt5.ORDER_FILLING_IOC: (fake_mt5.TRADE_RETCODE_DONE, "Request executed"),
    }
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.close_position(
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.01,
        },
        comment="TA early loss",
    )

    assert result["ok"] is True
    assert [request["type_filling"] for request in fake_mt5.sent_requests[-2:]] == [
        fake_mt5.ORDER_FILLING_FOK,
        fake_mt5.ORDER_FILLING_IOC,
    ]
    assert result["filling_attempts"][0]["retcode"] == 10013
    assert result["request"]["type_filling"] == fake_mt5.ORDER_FILLING_IOC


@pytest.mark.parametrize(
    ("position", "match"),
    (
        ({"ticket": 0, "side": "BUY", "volume": 0.01}, "position ticket"),
        ({"ticket": 333444, "side": "HOLD", "volume": 0.01}, "position side"),
        ({"ticket": 333444, "side": "BUY", "volume": 0}, "volume"),
        (
            {"ticket": 333444, "symbol": "EURUSD", "side": "BUY", "volume": 0.01},
            "symbol must match configured MT5 symbol",
        ),
    ),
)
def test_mt5_broker_rejects_invalid_close_position(position, match):
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)

    with pytest.raises(MT5BrokerError, match=match):
        broker.close_position(position)

    assert fake_mt5.sent_requests == []


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
