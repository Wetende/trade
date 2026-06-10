import json

from typer.testing import CliRunner

from cli import main as cli_main


app = cli_main.app


runner = CliRunner()


def _isolate_runtime_env(monkeypatch):
    monkeypatch.setattr(cli_main, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("TRADINGAGENTS_RESULTS_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_CACHE_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_TRADING_MODE", raising=False)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "trading_mode", "ENTRY_ONLY")


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
    assert "break-even" in result.output
    assert "trailing" in result.output
    assert "early" in result.output
    assert "scalp" in result.output


def test_mt5_run_once_invokes_runner(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    config = object()
    analysis_func = object()
    calls = {}

    class Executor:
        def __init__(self, received_config, results_dir, exit_management=None):
            calls["executor_config"] = received_config
            calls["executor_results_dir"] = results_dir
            calls["executor_exit_management"] = exit_management

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
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "runner_post_close_cooldown_seconds", 90)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "runner_loss_cooldown_seconds", 600)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_scalp_profit_points", 1.5)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_early_loss_points", 1.5)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_break_even_trigger_points", 1.0)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_break_even_lock_points", 0.2)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_trailing_trigger_points", 3.0)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_trailing_distance_points", 1.2)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "exit_min_stop_update_points", 0.3)
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
    assert calls["executor_exit_management"].scalp_profit_points == 1.5
    assert calls["executor_exit_management"].early_loss_exit_points == 1.5
    assert calls["executor_exit_management"].break_even_trigger_points == 1.0
    assert calls["executor_exit_management"].break_even_lock_points == 0.2
    assert calls["executor_exit_management"].trailing_trigger_points == 3.0
    assert calls["executor_exit_management"].trailing_distance_points == 1.2
    assert calls["executor_exit_management"].min_stop_update_points == 0.3
    assert calls["runner_config"].blocked_strategy_rules == (
        "SUPPORT_RESISTANCE_BOUNCE:SELL",
    )
    assert calls["runner_config"].post_close_cooldown_seconds == 90
    assert calls["runner_config"].loss_cooldown_seconds == 600
    assert calls["runner_analysis_func"] is analysis_func
    assert calls["run_once"] is True


def test_mt5_run_off_mode_places_no_orders(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "OFF")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(
        MT5ConnectionConfig,
        "from_env",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("no MT5 connect"))),
    )

    result = runner.invoke(app, ["mt5-run", "--once"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "TRADING_DISABLED"
    assert payload["trading_mode"] == "OFF"
    assert payload["selected_method"] == "HOLD"
    assert payload["health_gate"]["passed"] is False


def test_mt5_run_rejects_straddle_only_mode(monkeypatch, tmp_path):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "STRADDLE_ONLY")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)

    result = runner.invoke(app, ["mt5-run", "--once"])

    assert result.exit_code != 0
    assert "mt5-run requires ENTRY_ONLY or AUTO_GATED" in result.output


def test_auto_gated_mode_runs_autogate_runner(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_autogate, mt5_execution, mt5_runner, mt5_straddle

    config = SimpleNamespace(symbol="XAUUSD.vx")
    analysis_func = object()
    calls = {}

    class DirectionalExecutor:
        def __init__(self, received_config, results_dir, exit_management=None):
            calls["directional_executor"] = (received_config, results_dir, exit_management)

    class StraddleExecutor:
        def __init__(self, received_config, results_dir, trading_mode=None):
            calls["straddle_executor"] = (received_config, results_dir, trading_mode)

    class AutoGateRunner:
        def __init__(
            self,
            runner_config,
            directional_executor,
            straddle_executor,
            directional_analysis_func,
            straddle_config,
            current_as_of_func=None,
            straddle_exit_management=None,
            straddle_entry_regime=None,
        ):
            calls["runner_config"] = runner_config
            calls["directional_analysis_func"] = directional_analysis_func
            calls["straddle_config"] = straddle_config

        def run_once(self):
            return {
                "status": "NO_TRADE",
                "trading_mode": calls["runner_config"].trading_mode,
            }

        def run_forever(self):
            raise AssertionError("--once should call run_once")

    class DirectionalRunner:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("AUTO_GATED should not instantiate MT5Runner")

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "AUTO_GATED")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_execution, "MT5Executor", DirectionalExecutor)
    monkeypatch.setattr(mt5_straddle, "MT5StraddleExecutor", StraddleExecutor)
    monkeypatch.setattr(mt5_autogate, "MT5AutoGateRunner", AutoGateRunner)
    monkeypatch.setattr(mt5_runner, "MT5Runner", DirectionalRunner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_engine_analysis_func",
        lambda config=None: analysis_func,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--once"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "NO_TRADE",
        "trading_mode": "AUTO_GATED",
    }
    assert calls["runner_config"].trading_mode == "AUTO_GATED"
    assert calls["directional_analysis_func"] is analysis_func
    assert calls["straddle_config"].symbol == "XAUUSD.vx"
    assert calls["straddle_executor"][2] == "AUTO_GATED"


def test_mt5_straddle_run_off_mode_places_no_orders(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "OFF")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(
        MT5ConnectionConfig,
        "from_env",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("no MT5 connect"))),
    )

    result = runner.invoke(app, ["mt5-straddle-run", "--watch"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "TRADING_DISABLED"
    assert payload["trading_mode"] == "OFF"
    assert payload["selected_method"] == "HOLD"


def test_mt5_straddle_run_rejects_entry_only_mode(monkeypatch, tmp_path):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "ENTRY_ONLY")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)

    result = runner.invoke(app, ["mt5-straddle-run", "--watch"])

    assert result.exit_code != 0
    assert "mt5-straddle-run requires STRADDLE_ONLY or AUTO_GATED" in result.output


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
        def __init__(self, received_config, results_dir, trading_mode=None):
            calls["executor_config"] = received_config
            calls["executor_results_dir"] = results_dir

        def build_pair(self, straddle_config):
            calls["straddle_config"] = straddle_config
            return pair

        def execute_pair(self, received_pair, live=False):
            calls["execute_pair"] = (received_pair, live)
            return {"status": "DRY_RUN_PAIR_READY", "live": live}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "STRADDLE_ONLY")
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
    assert calls["straddle_config"].entry_buffer_points == 0.5
    assert calls["straddle_config"].stop_distance_points == 2.0
    assert calls["straddle_config"].target_distance_points == 3.0
    assert calls["straddle_config"].max_box_points == 3.0
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
        def __init__(self, received_config, results_dir, trading_mode=None):
            pass

        def build_pair(self, straddle_config):
            return pair

        def execute_pair(self, received_pair, live=False):
            calls["execute_pair"] = (received_pair, live)
            return {"status": "PAIR_PLACED", "live": live}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "STRADDLE_ONLY")
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
        def __init__(self, received_config, results_dir, trading_mode=None):
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
            exit_management=None,
            entry_regime=None,
        ):
            calls["watch_forever"] = {
                "straddle_config": straddle_config,
                "live": live,
                "poll_seconds": poll_seconds,
                "max_cycles": max_cycles,
                "max_runtime_seconds": max_runtime_seconds,
                "exit_management": exit_management,
                "entry_regime": entry_regime,
            }
            return {"status": "STOPPED_MAX_CYCLES"}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "STRADDLE_ONLY")
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
            "--break-even-trigger-points",
            "2.5",
            "--break-even-lock-points",
            "0.4",
            "--trailing-trigger-points",
            "4.5",
            "--trailing-distance-points",
            "1.8",
            "--min-stop-update-points",
            "0.2",
            "--early-loss-exit-points",
            "3.5",
            "--scalp-profit-points",
            "1.4",
            "--loss-streak-cooldown-trades",
            "3",
            "--loss-cooldown-minutes",
            "12",
            "--wide-box-cooldown-count",
            "4",
            "--wide-box-cooldown-minutes",
            "6",
            "--post-cooldown-momentum-body-points",
            "1.2",
            "--post-cooldown-momentum-breakout-points",
            "0.3",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "STOPPED_MAX_CYCLES"}
    assert calls["watch_forever"]["live"] is True
    assert calls["watch_forever"]["poll_seconds"] == 7
    assert calls["watch_forever"]["max_runtime_seconds"] == 2 * 3600
    exit_management = calls["watch_forever"]["exit_management"]
    assert exit_management.break_even_trigger_points == 2.5
    assert exit_management.break_even_lock_points == 0.4
    assert exit_management.trailing_trigger_points == 4.5
    assert exit_management.trailing_distance_points == 1.8
    assert exit_management.min_stop_update_points == 0.2
    assert exit_management.early_loss_exit_points == 3.5
    assert exit_management.scalp_profit_points == 1.4
    entry_regime = calls["watch_forever"]["entry_regime"]
    assert entry_regime.enabled is True
    assert entry_regime.loss_streak_limit == 3
    assert entry_regime.loss_cooldown_minutes == 12
    assert entry_regime.wide_box_streak_limit == 4
    assert entry_regime.wide_box_cooldown_minutes == 6
    assert entry_regime.post_cooldown_momentum_body_points == 1.2
    assert entry_regime.post_cooldown_momentum_breakout_points == 0.3


def test_mt5_straddle_run_watch_mode_uses_scalper_defaults(monkeypatch, tmp_path):
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
        def __init__(self, received_config, results_dir, trading_mode=None):
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
            exit_management=None,
            entry_regime=None,
        ):
            calls["watch_forever"] = {
                "straddle_config": straddle_config,
                "live": live,
                "poll_seconds": poll_seconds,
                "max_cycles": max_cycles,
                "max_runtime_seconds": max_runtime_seconds,
                "exit_management": exit_management,
                "entry_regime": entry_regime,
            }
            return {"status": "STOPPED_MAX_CYCLES"}

    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "STRADDLE_ONLY")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_straddle, "MT5StraddleExecutor", Executor)

    result = runner.invoke(app, ["mt5-straddle-run", "--watch"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"status": "STOPPED_MAX_CYCLES"}
    assert calls["watch_forever"]["live"] is True
    assert calls["watch_forever"]["poll_seconds"] == 5
    assert calls["watch_forever"]["max_cycles"] == 0
    assert calls["watch_forever"]["max_runtime_seconds"] == 0
    straddle_config = calls["watch_forever"]["straddle_config"]
    assert straddle_config.entry_buffer_points == 0.5
    assert straddle_config.stop_distance_points == 2.0
    assert straddle_config.target_distance_points == 3.0
    assert straddle_config.max_box_points == 3.0
    exit_management = calls["watch_forever"]["exit_management"]
    assert exit_management.break_even_trigger_points == 0.8
    assert exit_management.break_even_lock_points == 0.2
    assert exit_management.trailing_trigger_points == 0.0
    assert exit_management.trailing_distance_points == 0.8
    assert exit_management.min_stop_update_points == 0.3
    assert exit_management.early_loss_exit_points == 1.5
    assert exit_management.scalp_profit_points == 1.5
    entry_regime = calls["watch_forever"]["entry_regime"]
    assert entry_regime.enabled is True
    assert entry_regime.loss_streak_limit == 2
    assert entry_regime.loss_cooldown_minutes == 10.0
    assert entry_regime.wide_box_streak_limit == 3
    assert entry_regime.wide_box_cooldown_minutes == 5.0
    assert entry_regime.post_cooldown_momentum_body_points == 0.8
    assert entry_regime.post_cooldown_momentum_breakout_points == 0.2


def test_mt5_run_forever_uses_configured_max_cycles(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    calls = {}

    class Executor:
        def __init__(self, config, results_dir, exit_management=None):
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
        def __init__(self, config, results_dir, exit_management=None):
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
        def __init__(self, config, results_dir, exit_management=None):
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

    _isolate_runtime_env(monkeypatch)
    calls = {}

    class Executor:
        def __init__(self, config, results_dir, exit_management=None):
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


def test_mt5_run_rejects_graph_decision_mode_for_live_execution(monkeypatch):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "ENTRY_ONLY")

    result = runner.invoke(app, ["mt5-run", "--once", "--decision-mode", "graph"])

    assert result.exit_code != 0
    assert "graph decision mode is not allowed for MT5 execution" in result.output


def test_mt5_run_invalid_decision_mode_is_rejected(monkeypatch):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "ENTRY_ONLY")

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
    assert calls[1]["session_config"]["governing_timeframes"] == ("30m", "15m")


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
