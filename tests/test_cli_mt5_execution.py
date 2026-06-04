import json

from typer.testing import CliRunner

from cli import main as cli_main


app = cli_main.app


runner = CliRunner()


def _isolate_runtime_env(monkeypatch):
    monkeypatch.setattr(cli_main, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("TRADINGAGENTS_RESULTS_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_CACHE_DIR", raising=False)


def test_mt5_execute_command_help_mentions_proposal():
    result = runner.invoke(app, ["mt5-execute", "--help"])

    assert result.exit_code == 0
    assert "--proposal" in result.output


def test_mt5_monitor_command_exists():
    result = runner.invoke(app, ["mt5-monitor", "--help"])

    assert result.exit_code == 0
    assert "Monitor MT5 orders and positions" in result.output
    assert "--cancel-stale" in result.output
    assert "--manage-stops" in result.output


def test_mt5_run_command_exists():
    result = runner.invoke(app, ["mt5-run", "--help"])

    assert result.exit_code == 0
    assert "Run unattended MT5 automation" in result.output
    assert "Seconds between runner cycles." in result.output
    assert "--decision-mode" in result.output


def test_mt5_straddle_run_command_exists():
    result = runner.invoke(app, ["mt5-straddle-run", "--help"])

    assert result.exit_code == 0
    assert "Run isolated MT5 straddle breakout" in result.output
    assert "--live" in result.output
    assert "--watch" in result.output


def test_mt5_run_once_invokes_runner(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    config = object()
    analysis_func = object()
    calls = {}

    class Executor:
        def __init__(self, received_config, results_dir):
            calls["executor_config"] = received_config
            calls["executor_results_dir"] = results_dir

    class Runner:
        def __init__(self, runner_config, executor, analysis_func, current_as_of_func=None):
            calls["runner_config"] = runner_config
            calls["runner_executor"] = executor
            calls["runner_analysis_func"] = analysis_func
            calls["runner_current_as_of_func"] = current_as_of_func

        def run_once(self):
            calls["run_once"] = True
            return {
                "status": "ORDER_PLACED",
                "poll_seconds": calls["runner_config"].poll_seconds,
                "max_cycles": calls["runner_config"].max_cycles,
            }

        def run_forever(self):
            raise AssertionError("mt5-run --once should call run_once")

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(
        cli_main.DEFAULT_CONFIG,
        "runner_blocked_strategy_rules",
        ("SUPPORT_RESISTANCE_BOUNCE:SELL",),
    )
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: analysis_func,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--once", "--poll-seconds", "7"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "ORDER_PLACED",
        "poll_seconds": 7,
        "max_cycles": 1,
    }
    assert calls["executor_config"] is config
    assert calls["executor_results_dir"] == tmp_path
    assert calls["runner_config"].blocked_strategy_rules == (
        "SUPPORT_RESISTANCE_BOUNCE:SELL",
    )
    assert calls["runner_analysis_func"] is analysis_func
    assert calls["run_once"] is True


def test_mt5_straddle_run_defaults_to_dry_run(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_straddle

    config = MT5ConnectionConfig(
        login=123,
        password="secret",
        server="Example",
        symbol="XAUUSD.vx",
    )
    pair = object()
    calls = {}

    class Executor:
        def __init__(self, received_config, results_dir):
            calls["executor_config"] = received_config
            calls["executor_results_dir"] = results_dir

        def build_pair(self, straddle_config):
            calls["straddle_config"] = straddle_config
            return pair

        def execute_pair(self, received_pair, live=False):
            calls["execute_pair"] = (received_pair, live)
            return {"status": "DRY_RUN_PAIR_READY", "live": live}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_straddle, "MT5StraddleExecutor", Executor)

    result = runner.invoke(
        app,
        [
            "mt5-straddle-run",
            "--lookback-candles",
            "4",
            "--max-spread-points",
            "0.4",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "DRY_RUN_PAIR_READY",
        "live": False,
    }
    assert calls["executor_config"] is config
    assert calls["executor_results_dir"] == tmp_path
    assert calls["straddle_config"].symbol == "XAUUSD.vx"
    assert calls["straddle_config"].broker_symbol == "XAUUSD.vx"
    assert calls["straddle_config"].lookback_candles == 4
    assert calls["straddle_config"].max_spread_points == 0.4
    assert calls["execute_pair"] == (pair, False)


def test_mt5_straddle_run_live_flag_places_pair(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_straddle

    config = MT5ConnectionConfig(
        login=123,
        password="secret",
        server="Example",
        symbol="XAUUSD.vx",
    )
    pair = object()
    calls = {}

    class Executor:
        def __init__(self, received_config, results_dir):
            pass

        def build_pair(self, straddle_config):
            return pair

        def execute_pair(self, received_pair, live=False):
            calls["execute_pair"] = (received_pair, live)
            return {"status": "PAIR_PLACED", "live": live}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_straddle, "MT5StraddleExecutor", Executor)

    result = runner.invoke(app, ["mt5-straddle-run", "--live"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "PAIR_PLACED", "live": True}
    assert calls["execute_pair"] == (pair, True)


def test_mt5_straddle_run_watch_mode_uses_watch_forever(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_straddle

    config = MT5ConnectionConfig(
        login=123,
        password="secret",
        server="Example",
        symbol="XAUUSD.vx",
    )
    calls = {}

    class Executor:
        def __init__(self, received_config, results_dir):
            calls["executor_config"] = received_config
            calls["executor_results_dir"] = results_dir

        def build_pair(self, straddle_config):
            raise AssertionError("watch mode should not call build_pair directly")

        def execute_pair(self, pair, live=False):
            raise AssertionError("watch mode should not call execute_pair directly")

        def watch_forever(
            self,
            straddle_config,
            *,
            live=False,
            poll_seconds=30,
            max_cycles=0,
            max_runtime_seconds=0,
        ):
            calls["watch_forever"] = {
                "straddle_config": straddle_config,
                "live": live,
                "poll_seconds": poll_seconds,
                "max_cycles": max_cycles,
                "max_runtime_seconds": max_runtime_seconds,
            }
            return {"status": "STOPPED_MAX_CYCLES"}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_straddle, "MT5StraddleExecutor", Executor)

    result = runner.invoke(
        app,
        [
            "mt5-straddle-run",
            "--watch",
            "--live",
            "--poll-seconds",
            "7",
            "--duration-hours",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "STOPPED_MAX_CYCLES"}
    assert calls["watch_forever"]["live"] is True
    assert calls["watch_forever"]["poll_seconds"] == 7
    assert calls["watch_forever"]["max_runtime_seconds"] == 2 * 3600


def test_mt5_run_forever_uses_configured_max_cycles(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    calls = {}

    class Executor:
        def __init__(self, config, results_dir):
            calls["executor"] = (config, results_dir)

    class Runner:
        def __init__(self, runner_config, executor, analysis_func, current_as_of_func=None):
            calls["runner_config"] = runner_config

        def run_once(self):
            raise AssertionError("mt5-run without --once should call run_forever")

        def run_forever(self):
            return {
                "status": "STOPPED_MAX_CYCLES",
                "max_cycles": calls["runner_config"].max_cycles,
            }

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "runner_max_cycles", 3)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: lambda: None,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--poll-seconds", "8"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "STOPPED_MAX_CYCLES",
        "max_cycles": 3,
    }


def test_mt5_run_passes_configured_session_loss_limit(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    calls = {}

    class Executor:
        def __init__(self, config, results_dir):
            calls["executor"] = (config, results_dir)

    class Runner:
        def __init__(self, runner_config, executor, analysis_func, current_as_of_func=None):
            calls["runner_config"] = runner_config

        def run_once(self):
            raise AssertionError("mt5-run without --once should call run_forever")

        def run_forever(self):
            return {
                "status": "STOPPED_RISK_LIMIT",
                "max_session_loss": calls["runner_config"].max_session_loss,
            }

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "runner_max_session_loss", 300.0)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: lambda: None,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--poll-seconds", "8"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "STOPPED_RISK_LIMIT",
        "max_session_loss": 300.0,
    }


def test_mt5_run_duration_hours_sets_runner_runtime_limit(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    calls = {}

    class Executor:
        def __init__(self, config, results_dir):
            calls["executor"] = (config, results_dir)

    class Runner:
        def __init__(self, runner_config, executor, analysis_func, current_as_of_func=None):
            calls["runner_config"] = runner_config
            calls["runner_executor"] = executor
            calls["runner_analysis_func"] = analysis_func

        def run_once(self):
            raise AssertionError("mt5-run with duration-hours should call run_forever")

        def run_forever(self):
            return {
                "status": "STOPPED_MAX_RUNTIME_SECONDS",
                "max_runtime_seconds": calls["runner_config"].max_runtime_seconds,
            }

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: lambda: None,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--duration-hours", "4"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "STOPPED_MAX_RUNTIME_SECONDS",
        "max_runtime_seconds": 4 * 3600,
    }
    assert calls["runner_config"].max_runtime_seconds == 4 * 3600
    assert calls["runner_config"].max_cycles == 0


def test_mt5_run_tiny_duration_hours_sets_at_least_one_second(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    calls = {}

    class Executor:
        def __init__(self, config, results_dir):
            calls["executor"] = (config, results_dir)

    class Runner:
        def __init__(self, runner_config, executor, analysis_func, current_as_of_func=None):
            calls["runner_config"] = runner_config

        def run_once(self):
            raise AssertionError("mt5-run with duration-hours should call run_forever")

        def run_forever(self):
            return {
                "status": "STOPPED_MAX_RUNTIME_SECONDS",
                "max_runtime_seconds": calls["runner_config"].max_runtime_seconds,
            }

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "runner_max_cycles", 3)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: lambda: None,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--duration-hours", "0.0001"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "STOPPED_MAX_RUNTIME_SECONDS",
        "max_runtime_seconds": 1,
    }
    assert calls["runner_config"].max_runtime_seconds == 1
    assert calls["runner_config"].max_cycles == 0


def test_mt5_run_rejects_too_short_poll_interval():
    invalid_result = runner.invoke(app, ["mt5-run", "--poll-seconds", "4"])

    assert invalid_result.exit_code != 0


def test_mt5_run_graph_decision_mode_uses_graph_analysis_func(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    graph_analysis_func = object()
    engine_analysis_func = object()
    calls = {}

    class Executor:
        def __init__(self, config, results_dir):
            pass

    class Runner:
        def __init__(self, runner_config, executor, analysis_func, current_as_of_func=None):
            calls["analysis_func"] = analysis_func

        def run_once(self):
            return {"status": "NO_TRADE"}

        def run_forever(self):
            raise AssertionError("--once should call run_once")

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_analysis_func",
        lambda: graph_analysis_func,
        raising=False,
    )
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: engine_analysis_func,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--once", "--decision-mode", "graph"])

    assert result.exit_code == 0
    assert calls["analysis_func"] is graph_analysis_func


def test_mt5_run_invalid_decision_mode_is_rejected():
    result = runner.invoke(app, ["mt5-run", "--once", "--decision-mode", "llm"])

    assert result.exit_code != 0
    assert "decision-mode must be 'engine' or 'graph'" in result.output


def test_mt5_runner_analysis_func_attaches_engine_telemetry(monkeypatch, tmp_path):
    proposal_path = tmp_path / "order_proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "activation_window_minutes": None,
                "broker_symbol": "XAUUSD.vx",
                "cancel_if_not_triggered_after": None,
                "confirmation_timeframe": "30m",
                "entry_price": None,
                "order_type": "LIMIT",
                "reason": "No setup.",
                "side": "HOLD",
                "status": "NO_TRADE",
                "stop_loss": None,
                "symbol": "GC=F",
                "take_profit": None,
                "timeframe": "15m",
                "valid_until": "2026-05-29 08:30 EDT",
            }
        ),
        encoding="utf-8",
    )
    telemetry_dir = tmp_path / "GC=F" / "engine_telemetry"
    telemetry_dir.mkdir(parents=True)
    telemetry_path = telemetry_dir / "engine_payload_2026-05-29_08_15.json"
    telemetry_path.write_text(
        json.dumps(
            {
                "telemetry": {"decision_stage": "time_filter"},
                "data_status": {"healthy": True},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", False)
    monkeypatch.setattr(
        cli_main,
        "build_env_selections",
        lambda: {"ticker": "GC=F", "as_of": "2026-05-29 08:15"},
    )
    monkeypatch.setattr(
        cli_main,
        "run_analysis",
        lambda checkpoint, selections: (
            {
                "order_proposal_path": str(proposal_path),
                "price_action_report": "report",
                "trade_plan": "plan",
            },
            "HOLD",
        ),
    )

    as_of, proposal, analysis = cli_main._mt5_runner_analysis_func()()

    assert as_of == "2026-05-29 08:15"
    assert proposal.status.value == "NO_TRADE"
    assert analysis["telemetry_path"] == str(telemetry_path)
    assert analysis["telemetry"]["decision_stage"] == "time_filter"
    assert analysis["data_status"]["healthy"] is True


def test_mt5_runner_engine_analysis_func_builds_proposal_from_engine(monkeypatch, tmp_path):
    from tradingagents.agents.price_action import decision

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", False)
    monkeypatch.setattr(
        cli_main,
        "build_env_selections",
        lambda: {
            "ticker": "GC=F",
            "broker_symbol": "XAUUSD.vx",
            "as_of": "2026-06-01 08:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
        },
    )

    def fake_run_engine_decision(**kwargs):
        return {
            "company_of_interest": kwargs["symbol"],
            "broker_symbol": kwargs["broker_symbol"],
            "as_of": kwargs["as_of"],
            "timeframe": kwargs["timeframe"],
            "confirmation_timeframe": kwargs["confirmation_timeframe"],
            "market_timezone": kwargs["market_timezone"],
            "price_action_report": "Final Action: HOLD",
            "trade_plan": "Action: HOLD",
            "data_status": {"healthy": True},
            "telemetry_path": str(tmp_path / "GC=F" / "engine_telemetry" / "engine_payload_2026-06-01_08_15.json"),
            "engine_telemetry": {
                "decision_stage": "no_m15_setup",
                "primary_hold_reason": "No valid M15 setup. Default to HOLD.",
            },
            "engine_payload": {
                "symbol": "GC=F",
                "as_of": "2026-06-01 08:15",
                "status": "NO_SETUP",
                "recommendation": "HOLD",
                "message": "No valid M15 setup. Default to HOLD.",
                "checklist": {"playbook_setup": "failed"},
                "risk": {},
                "telemetry": {
                    "decision_stage": "no_m15_setup",
                    "primary_hold_reason": "No valid M15 setup. Default to HOLD.",
                },
                "data_status": {"healthy": True},
            },
        }

    monkeypatch.setattr(decision, "run_engine_decision", fake_run_engine_decision)

    as_of, proposal, analysis = cli_main._mt5_runner_engine_analysis_func()()

    assert as_of == "2026-06-01 08:15"
    assert proposal.status.value == "NO_TRADE"
    assert proposal.broker_symbol == "XAUUSD.vx"
    assert analysis["telemetry"]["decision_stage"] == "no_m15_setup"
    assert analysis["data_status"]["healthy"] is True
    assert analysis["order_proposal_path"].endswith("order_proposal_2026-06-01_08_15.json")


def test_mt5_runner_engine_analysis_func_returns_fast_and_normal_profiles(monkeypatch, tmp_path):
    from tradingagents.agents.price_action import decision

    calls = []
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", True)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_timeframe", "1m")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_confirmation_timeframe", "3m")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "normal_activation_window_minutes", 30)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_activation_window_minutes", 6)
    monkeypatch.setattr(
        cli_main,
        "build_env_selections",
        lambda as_of=None: {
            "ticker": "XAUUSD.vx",
            "broker_symbol": "XAUUSD.vx",
            "as_of": as_of or "2026-06-03 08:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
        },
    )
    monkeypatch.setattr(
        cli_main,
        "last_closed_candle",
        lambda timeframe, market_timezone: (
            "2026-06-03 08:16" if timeframe == "1m" else "2026-06-03 08:15"
        ),
    )

    def fake_run_engine_decision(**kwargs):
        calls.append(kwargs)
        return {
            "company_of_interest": kwargs["symbol"],
            "broker_symbol": kwargs["broker_symbol"],
            "as_of": kwargs["as_of"],
            "timeframe": kwargs["timeframe"],
            "confirmation_timeframe": kwargs["confirmation_timeframe"],
            "market_timezone": kwargs["market_timezone"],
            "price_action_report": "Action: HOLD",
            "trade_plan": "Action: HOLD",
            "telemetry_path": str(tmp_path / f"{kwargs['timeframe']}.json"),
            "engine_payload": {
                "status": "NO_SETUP",
                "recommendation": "HOLD",
                "message": "No setup.",
                "telemetry": {"decision_stage": "no_m15_setup"},
                "data_status": {"healthy": True},
            },
        }

    monkeypatch.setattr(decision, "run_engine_decision", fake_run_engine_decision)

    results = cli_main._mt5_runner_engine_analysis_func()()

    assert len(results) == 2
    assert results[0][0] == "normal"
    assert results[1][0] == "fast"
    assert results[0][1] == "2026-06-03 08:15"
    assert results[1][1] == "2026-06-03 08:16"
    assert calls[0]["timeframe"] == "15m"
    assert calls[1]["timeframe"] == "1m"
    assert calls[0]["session_config"]["entry_profile"] == "normal"
    assert calls[1]["session_config"]["entry_profile"] == "fast"


def test_mt5_runner_current_as_of_uses_fast_timeframe_when_enabled(monkeypatch):
    seen = []
    monkeypatch.setattr(cli_main, "_load_runtime_env", lambda: None)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", True)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_timeframe", "1m")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "market_timezone", "America/New_York")
    monkeypatch.setattr(
        cli_main,
        "last_closed_candle",
        lambda timeframe, market_timezone: seen.append((timeframe, market_timezone))
        or "2026-06-03 08:16",
    )

    as_of = cli_main._mt5_runner_current_as_of_func()()

    assert as_of == "2026-06-03 08:16"
    assert seen == [("1m", "America/New_York")]


def test_mt5_runner_engine_analysis_rebuilds_mt5_snapshot_health_by_profile(
    monkeypatch,
    tmp_path,
):
    from tradingagents.agents.price_action import decision
    from tradingagents.agents.price_action.models import Candle
    from tradingagents.brokers import mt5
    from tradingagents.dataflows import mt5_price_action
    from tradingagents.dataflows.price_action import PriceActionSnapshot

    calls = []

    class Config:
        symbol = "XAUUSD.vx"

    class FakeMT5Broker:
        def __init__(self, config):
            self.config = config

        def connect(self):
            return {"connected": True}

    rows = {
        "1d": [Candle("2026-06-03 00:00:00", 100, 102, 99, 101, 1000)],
        "4h": [Candle("2026-06-03 08:00:00", 100, 102, 99, 101, 1000)],
        "1h": [Candle("2026-06-03 08:00:00", 100, 102, 99, 101, 1000)],
        "30m": [Candle("2026-06-03 08:00:00", 100, 102, 99, 101, 1000)],
        "15m": [Candle("2026-06-03 08:15:00", 100, 102, 99, 101, 1000)],
        "3m": [Candle("2026-06-03 08:15:00", 100, 102, 99, 101, 1000)],
        "1m": [Candle("2026-06-03 08:16:00", 100, 102, 99, 101, 1000)],
    }

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", True)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_timeframe", "1m")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_confirmation_timeframe", "3m")
    monkeypatch.setattr(
        cli_main,
        "build_env_selections",
        lambda as_of=None: {
            "ticker": "XAUUSD.vx",
            "broker_symbol": "XAUUSD.vx",
            "as_of": as_of or "2026-06-03 08:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
        },
    )
    monkeypatch.setattr(
        cli_main,
        "last_closed_candle",
        lambda timeframe, market_timezone: (
            "2026-06-03 08:16" if timeframe == "1m" else "2026-06-03 08:15"
        ),
    )
    monkeypatch.setattr(mt5, "MT5Broker", FakeMT5Broker)
    monkeypatch.setattr(
        mt5_price_action,
        "fetch_mt5_price_action_snapshot",
        lambda broker, *, as_of, market_timezone: PriceActionSnapshot(
            candles=rows,
            data_status={"healthy": False, "blocking_timeframes": ["1m", "3m"]},
        ),
    )

    def fake_run_engine_decision(**kwargs):
        calls.append(kwargs)
        return {
            "company_of_interest": kwargs["symbol"],
            "broker_symbol": kwargs["broker_symbol"],
            "as_of": kwargs["as_of"],
            "timeframe": kwargs["timeframe"],
            "confirmation_timeframe": kwargs["confirmation_timeframe"],
            "market_timezone": kwargs["market_timezone"],
            "price_action_report": "Action: HOLD",
            "trade_plan": "Action: HOLD",
            "telemetry_path": str(tmp_path / f"{kwargs['timeframe']}.json"),
            "engine_payload": {
                "status": "NO_SETUP",
                "recommendation": "HOLD",
                "message": "No setup.",
                "entry_profile": kwargs["session_config"]["entry_profile"],
                "telemetry": {"decision_stage": "no_m15_setup"},
                "data_status": kwargs["snapshot"].data_status,
            },
        }

    monkeypatch.setattr(decision, "run_engine_decision", fake_run_engine_decision)

    cli_main._mt5_runner_engine_analysis_func(Config())()

    assert calls[0]["snapshot"].data_status["healthy"] is True
    assert calls[0]["snapshot"].data_status["trading_timeframe"]["interval"] == "15m"
    assert calls[0]["snapshot"].data_status["confirmation_timeframe"]["interval"] == "30m"
    assert calls[1]["snapshot"].data_status["healthy"] is True
    assert calls[1]["snapshot"].data_status["trading_timeframe"]["interval"] == "1m"
    assert calls[1]["snapshot"].data_status["confirmation_timeframe"]["interval"] == "3m"


def test_mt5_runner_engine_analysis_func_uses_mt5_snapshot(monkeypatch, tmp_path):
    from tradingagents.brokers import mt5
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.dataflows.price_action import PriceActionSnapshot
    from tradingagents.dataflows import mt5_price_action

    seen = {}

    class FakeMT5Broker:
        def __init__(self, config):
            self.config = config

        def connect(self):
            seen["connected_symbol"] = self.config.symbol
            return {"connected": True}

    def fake_snapshot(broker, *, as_of, market_timezone):
        seen["snapshot_symbol"] = broker.config.symbol
        seen["as_of"] = as_of
        seen["market_timezone"] = market_timezone
        return PriceActionSnapshot(
            candles={timeframe: [] for timeframe in ("1d", "4h", "1h", "30m", "15m")},
            data_status={
                "healthy": False,
                "blocking_timeframes": ["15m"],
                "timeframes": {"15m": {"rows": 0}},
            },
        )

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", False)
    monkeypatch.setattr(
        cli_main,
        "build_env_selections",
        lambda: {
            "ticker": "GC=F",
            "broker_symbol": "XAUUSD.vx",
            "as_of": "2026-06-02T19:16:00-04:00",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
        },
    )
    monkeypatch.setattr(mt5, "MT5Broker", FakeMT5Broker)
    monkeypatch.setattr(
        mt5_price_action,
        "fetch_mt5_price_action_snapshot",
        fake_snapshot,
    )

    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD.vx",
    )

    as_of, proposal, analysis = cli_main._mt5_runner_engine_analysis_func(config)()

    assert as_of == "2026-06-02T19:16:00-04:00"
    assert seen == {
        "connected_symbol": "XAUUSD.vx",
        "snapshot_symbol": "XAUUSD.vx",
        "as_of": "2026-06-02T19:16:00-04:00",
        "market_timezone": "America/New_York",
    }
    assert proposal.symbol == "XAUUSD.vx"
    assert proposal.broker_symbol == "XAUUSD.vx"
    assert analysis["engine_status"] == "NO_SETUP"


def test_retired_account_specific_commands_are_not_registered():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "mt5-execute" in result.output
    assert "mt5-monitor" in result.output

    retired_execute = "mt5-" + "demo" + "-execute"
    retired_monitor = "mt5-" + "demo" + "-monitor"
    assert retired_execute not in result.output
    assert retired_monitor not in result.output
    assert runner.invoke(app, [retired_execute, "--help"]).exit_code != 0
    assert runner.invoke(app, [retired_monitor, "--help"]).exit_code != 0
