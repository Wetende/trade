import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "setup-windows.ps1"
RUNNER_SCRIPT = ROOT / "scripts" / "start-one-minute-demo.ps1"
SHADOW_WATCH_SCRIPT = ROOT / "scripts" / "start-opening-state-shadow-watch.ps1"


def _powershell_parse(path: Path) -> subprocess.CompletedProcess[str]:
    escaped = str(path).replace("'", "''")
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$errors=$null; "
                f"[void][System.Management.Automation.Language.Parser]::"
                f"ParseFile('{escaped}',[ref]$null,[ref]$errors); "
                "if ($errors.Count) { $errors | ForEach-Object { "
                "Write-Error $_.Message }; exit 1 }"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_windows_scripts_exist_and_parse_as_powershell():
    for script in (SETUP_SCRIPT, RUNNER_SCRIPT, SHADOW_WATCH_SCRIPT):
        assert script.is_file()
        parsed = _powershell_parse(script)
        assert parsed.returncode == 0, parsed.stderr


def test_setup_script_installs_project_tests_and_mt5_bridge():
    text = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "py -0p" in text
    assert "VersionInfo.Minor" in text
    assert "PythonPath" in text
    assert "catch {" in text
    assert "-m venv" in text
    assert "-m pip install -e" in text
    assert "pytest" in text
    assert "MetaTrader5" in text


def test_runner_script_enforces_canonical_demo_profile_and_hidden_worker():
    text = RUNNER_SCRIPT.read_text(encoding="utf-8")
    required_assignments = {
        "TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT": "true",
        "TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS": "false",
        "TRADINGAGENTS_MT5_VOLUME": "1.0",
        "TRADINGAGENTS_TRADING_MODE": "ENTRY_ONLY",
        "TRADINGAGENTS_DECISION_MODE": "engine",
        "TRADINGAGENTS_ENTRY_PROFILE_MODE": "fast_only",
        "TRADINGAGENTS_TIMEFRAME": "1m",
        "TRADINGAGENTS_CONFIRMATION_TIMEFRAME": "1m",
        "TRADINGAGENTS_FAST_TIMEFRAME": "1m",
        "TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME": "1m",
        "TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED": "false",
        "TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS": "600",
    }
    for name, value in required_assignments.items():
        pattern = rf'\$env:{name}\s*=\s*"{re.escape(value)}"'
        assert re.search(pattern, text)

    assert "broker-probe" in text
    assert "--json-only" in text
    assert "account_safety.passed" in text
    assert 'trade_mode -ne "DEMO"' in text
    assert "open_order_count -ne 0" in text
    assert "open_position_count -ne 0" in text
    assert "trade_allowed" in text
    assert "tradeapi_disabled" in text
    assert "TotalSeconds" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "-WindowStyle Hidden" in text
    assert "Start-Process" in text


def test_shadow_watch_script_is_read_only_and_stops_on_terminal_decision():
    text = SHADOW_WATCH_SCRIPT.read_text(encoding="utf-8")

    assert "one-minute-opening-target-grid-shadow-step" in text
    assert "OPENING_STATE_QUEUE_TARGET_GRID_V1" in text
    assert "PASS_PROSPECTIVE_SHADOW" in text
    assert "FAIL_PROSPECTIVE_SHADOW" in text
    assert "COLLECTING_PROSPECTIVE_SHADOW" in text
    assert "shadow-heartbeat.json" in text
    assert "shadow-watch.stop" in text
    assert "mt5-run" not in text
    assert "order-send" not in text.lower()
    assert "Start-Process" in text
    assert "-WindowStyle Hidden" in text


def test_env_template_keeps_credentials_blank_and_real_orders_disabled():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    for name in (
        "TRADINGAGENTS_MT5_LOGIN",
        "TRADINGAGENTS_MT5_PASSWORD",
        "TRADINGAGENTS_MT5_SERVER",
        "TRADINGAGENTS_MT5_EXPECTED_LOGIN",
        "TRADINGAGENTS_MT5_EXPECTED_SERVER",
    ):
        assert re.search(rf"^#{name}=\s*$", text, flags=re.MULTILINE)
    assert "I_UNDERSTAND_REAL_MONEY_IS_AT_RISK" not in text
    assert "#TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=false" in text


def test_readme_local_markdown_links_resolve():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    local_links = re.findall(r"\[[^\]]+\]\((?!https?://|#)([^)]+)\)", readme)

    assert "scripts/setup-windows.ps1" in local_links
    assert "scripts/start-one-minute-demo.ps1" in local_links
    for link in local_links:
        assert (ROOT / link).exists(), link
