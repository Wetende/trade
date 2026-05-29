import json

from typer.testing import CliRunner

from cli import main as cli_main


app = cli_main.app


runner = CliRunner()


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
        def __init__(self, runner_config, executor, analysis_func):
            calls["runner_config"] = runner_config
            calls["runner_executor"] = executor
            calls["runner_analysis_func"] = analysis_func

        def run_once(self):
            calls["run_once"] = True
            return {
                "status": "ORDER_PLACED",
                "poll_seconds": calls["runner_config"].poll_seconds,
                "max_cycles": calls["runner_config"].max_cycles,
            }

        def run_forever(self):
            raise AssertionError("mt5-run --once should call run_once")

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: config))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_analysis_func",
        lambda: analysis_func,
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
    assert calls["runner_analysis_func"] is analysis_func
    assert calls["run_once"] is True


def test_mt5_run_forever_uses_configured_max_cycles(monkeypatch, tmp_path):
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.brokers import mt5_execution, mt5_runner

    calls = {}

    class Executor:
        def __init__(self, config, results_dir):
            calls["executor"] = (config, results_dir)

    class Runner:
        def __init__(self, runner_config, executor, analysis_func):
            calls["runner_config"] = runner_config

        def run_once(self):
            raise AssertionError("mt5-run without --once should call run_forever")

        def run_forever(self):
            return {
                "status": "STOPPED_MAX_CYCLES",
                "max_cycles": calls["runner_config"].max_cycles,
            }

    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "runner_max_cycles", 3)
    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", Executor)
    monkeypatch.setattr(mt5_runner, "MT5Runner", Runner)
    monkeypatch.setattr(
        cli_main,
        "_mt5_runner_analysis_func",
        lambda: lambda: None,
        raising=False,
    )

    result = runner.invoke(app, ["mt5-run", "--poll-seconds", "8"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "status": "STOPPED_MAX_CYCLES",
        "max_cycles": 3,
    }


def test_mt5_run_rejects_too_short_poll_interval():
    invalid_result = runner.invoke(app, ["mt5-run", "--poll-seconds", "4"])

    assert invalid_result.exit_code != 0


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
