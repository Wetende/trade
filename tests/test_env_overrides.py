"""Tests for TRADINGAGENTS_* env-var overlay onto DEFAULT_CONFIG."""

from __future__ import annotations

import importlib

import pytest

import tradingagents.default_config as default_config_module


def _reload_with_env(monkeypatch, **overrides):
    """Set/clear env vars then reload default_config to re-evaluate DEFAULT_CONFIG."""
    for key in list(default_config_module._ENV_OVERRIDES) + [
        "TRADINGAGENTS_RESULTS_DIR",
        "TRADINGAGENTS_CACHE_DIR",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, val in overrides.items():
        monkeypatch.setenv(key, val)
    return importlib.reload(default_config_module)


def test_no_env_uses_built_in_defaults(monkeypatch):
    dc = _reload_with_env(monkeypatch)
    assert dc.DEFAULT_CONFIG["llm_provider"] == "openai"
    assert dc.DEFAULT_CONFIG["deep_think_llm"] == "gpt-5.4"
    assert dc.DEFAULT_CONFIG["quick_think_llm"] == "gpt-5.4-mini"
    assert dc.DEFAULT_CONFIG["backend_url"] is None
    assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is False
    assert dc.DEFAULT_CONFIG["timeframe"] == "15m"
    assert dc.DEFAULT_CONFIG["confirmation_timeframe"] == "30m"
    assert dc.DEFAULT_CONFIG["market_timezone"] == "America/New_York"
    assert dc.DEFAULT_CONFIG["runner_poll_seconds"] == 30
    assert dc.DEFAULT_CONFIG["runner_maintenance_poll_seconds"] == 1.0
    assert dc.DEFAULT_CONFIG["runner_max_cycles"] == 0
    assert dc.DEFAULT_CONFIG["runner_post_close_cooldown_seconds"] == 0
    assert dc.DEFAULT_CONFIG["runner_loss_cooldown_seconds"] == 0
    assert dc.DEFAULT_CONFIG["runner_loss_streak_cooldown_count"] == 0
    assert dc.DEFAULT_CONFIG["runner_loss_streak_cooldown_seconds"] == 0
    assert dc.DEFAULT_CONFIG["minimum_setup_grade"] == "B_PLUS"
    assert dc.DEFAULT_CONFIG["b_plus_min_rr"] == 1.1
    assert dc.DEFAULT_CONFIG["fast_confirmation_timeframe"] == "1m"
    assert dc.DEFAULT_CONFIG["fast_history_window_candles"] == 60
    assert dc.DEFAULT_CONFIG["fast_reaction_pending_seconds"] == 20.0
    assert dc.DEFAULT_CONFIG["fast_impulse_pending_seconds"] == 45.0
    assert dc.DEFAULT_CONFIG["fast_early_loss_grace_seconds"] == 5.0
    assert dc.DEFAULT_CONFIG["minimum_stop_distance_price"] == 0.35
    assert dc.DEFAULT_CONFIG["minimum_stop_spread_multiple"] == 1.2
    assert dc.DEFAULT_CONFIG["trading_mode"] == "OFF"
    assert dc.DEFAULT_CONFIG["require_demo_account"] is True
    assert dc.DEFAULT_CONFIG["market_rollover_block_enabled"] is True
    assert dc.DEFAULT_CONFIG["market_rollover_close_time"] == "17:00"
    assert dc.DEFAULT_CONFIG["market_rollover_reopen_time"] == "18:00"
    assert dc.DEFAULT_CONFIG["market_rollover_pre_close_minutes"] == 15
    assert dc.DEFAULT_CONFIG["market_rollover_post_reopen_minutes"] == 15
    assert dc.DEFAULT_CONFIG["entry_profile_mode"] == "auto"
    assert dc.DEFAULT_CONFIG["price_action"]["minimum_setup_grade"] == "B_PLUS"
    assert dc.DEFAULT_CONFIG["price_action"]["b_plus_min_rr"] == 1.1


def test_string_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_ANALYSIS_SYMBOL="GC=F",
        TRADINGAGENTS_BROKER_SYMBOL="XAUUSD.vx",
        TRADINGAGENTS_LLM_PROVIDER="google",
        TRADINGAGENTS_DEEP_THINK_LLM="gemini-3-pro-preview",
        TRADINGAGENTS_QUICK_THINK_LLM="gemini-3-flash-preview",
        TRADINGAGENTS_LLM_BACKEND_URL="https://example.invalid/v1",
        TRADINGAGENTS_OUTPUT_LANGUAGE="Chinese",
        TRADINGAGENTS_TIMEFRAME="15m",
        TRADINGAGENTS_CONFIRMATION_TIMEFRAME="30m",
        TRADINGAGENTS_MARKET_TIMEZONE="America/New_York",
    )
    assert dc.DEFAULT_CONFIG["analysis_symbol"] == "GC=F"
    assert dc.DEFAULT_CONFIG["broker_symbol"] == "XAUUSD.vx"
    assert dc.DEFAULT_CONFIG["llm_provider"] == "google"
    assert dc.DEFAULT_CONFIG["deep_think_llm"] == "gemini-3-pro-preview"
    assert dc.DEFAULT_CONFIG["quick_think_llm"] == "gemini-3-flash-preview"
    assert dc.DEFAULT_CONFIG["backend_url"] == "https://example.invalid/v1"
    assert dc.DEFAULT_CONFIG["output_language"] == "Chinese"
    assert dc.DEFAULT_CONFIG["timeframe"] == "15m"
    assert dc.DEFAULT_CONFIG["confirmation_timeframe"] == "30m"
    assert dc.DEFAULT_CONFIG["market_timezone"] == "America/New_York"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("False", False), ("0", False), ("no", False), ("off", False),
    ],
)
def test_bool_coercion(monkeypatch, raw, expected):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_CHECKPOINT_ENABLED=raw)
    assert dc.DEFAULT_CONFIG["checkpoint_enabled"] is expected


def test_runner_int_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_RUNNER_POLL_SECONDS="45",
        TRADINGAGENTS_RUNNER_MAX_CYCLES="5",
        TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS="250.5",
        TRADINGAGENTS_RUNNER_POST_CLOSE_COOLDOWN_SECONDS="90",
        TRADINGAGENTS_RUNNER_LOSS_COOLDOWN_SECONDS="600",
        TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_COUNT="2",
        TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_SECONDS="900",
    )

    assert dc.DEFAULT_CONFIG["runner_poll_seconds"] == 45
    assert dc.DEFAULT_CONFIG["runner_max_cycles"] == 5
    assert dc.DEFAULT_CONFIG["runner_max_session_loss"] == 250.5
    assert dc.DEFAULT_CONFIG["runner_post_close_cooldown_seconds"] == 90
    assert dc.DEFAULT_CONFIG["runner_loss_cooldown_seconds"] == 600
    assert dc.DEFAULT_CONFIG["runner_loss_streak_cooldown_count"] == 2
    assert dc.DEFAULT_CONFIG["runner_loss_streak_cooldown_seconds"] == 900


def test_one_minute_lifecycle_float_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_RUNNER_MAINTENANCE_POLL_SECONDS="0.75",
        TRADINGAGENTS_FAST_REACTION_PENDING_SECONDS="18.5",
        TRADINGAGENTS_FAST_IMPULSE_PENDING_SECONDS="42.5",
        TRADINGAGENTS_FAST_EARLY_LOSS_GRACE_SECONDS="6.5",
    )

    assert dc.DEFAULT_CONFIG["runner_maintenance_poll_seconds"] == 0.75
    assert dc.DEFAULT_CONFIG["fast_reaction_pending_seconds"] == 18.5
    assert dc.DEFAULT_CONFIG["fast_impulse_pending_seconds"] == 42.5
    assert dc.DEFAULT_CONFIG["fast_early_loss_grace_seconds"] == 6.5
    assert dc.DEFAULT_CONFIG["price_action"]["fast_reaction_pending_seconds"] == 18.5
    assert dc.DEFAULT_CONFIG["price_action"]["fast_impulse_pending_seconds"] == 42.5
    assert dc.DEFAULT_CONFIG["price_action"]["fast_early_loss_grace_seconds"] == 6.5


def test_runner_blocked_strategy_rules_env_override(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_RUNNER_BLOCKED_STRATEGY_RULES=(
            "SUPPORT_RESISTANCE_BOUNCE:SELL, BREAKOUT:*"
        ),
    )

    assert dc.DEFAULT_CONFIG["runner_blocked_strategy_rules"] == (
        "SUPPORT_RESISTANCE_BOUNCE:SELL",
        "BREAKOUT:*",
    )


def test_fast_one_minute_window_env_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES="45",
    )

    assert dc.DEFAULT_CONFIG["fast_history_window_candles"] == 45
    assert dc.DEFAULT_CONFIG["price_action"]["fast_history_window_candles"] == 45


def test_fast_one_minute_quality_env_overrides(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_FAST_MIN_CANDIDATE_SCORE="9.5",
        TRADINGAGENTS_FAST_MIN_STOP_SPREAD_MULTIPLE="2.5",
        TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED="true",
    )

    assert dc.DEFAULT_CONFIG["fast_min_candidate_score"] == 9.5
    assert dc.DEFAULT_CONFIG["fast_min_stop_spread_multiple"] == 2.5
    assert dc.DEFAULT_CONFIG["fast_volume_boost_enabled"] is True
    assert dc.DEFAULT_CONFIG["price_action"]["fast_min_candidate_score"] == 9.5
    assert dc.DEFAULT_CONFIG["price_action"]["fast_min_stop_spread_multiple"] == 2.5
    assert dc.DEFAULT_CONFIG["price_action"]["fast_volume_boost_enabled"] is True


def test_trading_mode_env_override(monkeypatch):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_TRADING_MODE="AUTO_GATED")

    assert dc.DEFAULT_CONFIG["trading_mode"] == "AUTO_GATED"


def test_entry_profile_mode_env_override(monkeypatch):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_ENTRY_PROFILE_MODE="fast_only")

    assert dc.DEFAULT_CONFIG["entry_profile_mode"] == "fast_only"


def test_invalid_trading_mode_rejected():
    from tradingagents.brokers.mode_gate import parse_trading_mode

    with pytest.raises(ValueError, match="TRADINGAGENTS_TRADING_MODE"):
        parse_trading_mode("ENTRY")


def test_time_filter_mode_env_updates_price_action_config(monkeypatch):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_TIME_FILTER_MODE="allow")

    assert dc.DEFAULT_CONFIG["price_action"]["time_filter_mode"] == "allow"


def test_rollover_guard_env_updates_price_action_config(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_MARKET_ROLLOVER_BLOCK_ENABLED="false",
        TRADINGAGENTS_MARKET_ROLLOVER_CLOSE_TIME="16:58",
        TRADINGAGENTS_MARKET_ROLLOVER_REOPEN_TIME="18:05",
        TRADINGAGENTS_MARKET_ROLLOVER_PRE_CLOSE_MINUTES="20",
        TRADINGAGENTS_MARKET_ROLLOVER_POST_REOPEN_MINUTES="10",
    )

    assert dc.DEFAULT_CONFIG["market_rollover_block_enabled"] is False
    assert dc.DEFAULT_CONFIG["market_rollover_close_time"] == "16:58"
    assert dc.DEFAULT_CONFIG["market_rollover_reopen_time"] == "18:05"
    assert dc.DEFAULT_CONFIG["market_rollover_pre_close_minutes"] == 20
    assert dc.DEFAULT_CONFIG["market_rollover_post_reopen_minutes"] == 10
    assert dc.DEFAULT_CONFIG["price_action"]["market_rollover_block_enabled"] is False
    assert dc.DEFAULT_CONFIG["price_action"]["market_rollover_close_time"] == "16:58"
    assert dc.DEFAULT_CONFIG["price_action"]["market_rollover_reopen_time"] == "18:05"
    assert dc.DEFAULT_CONFIG["price_action"]["market_rollover_pre_close_minutes"] == 20
    assert dc.DEFAULT_CONFIG["price_action"]["market_rollover_post_reopen_minutes"] == 10


def test_setup_grade_env_updates_price_action_config(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_MIN_SETUP_GRADE="B_PLUS",
        TRADINGAGENTS_B_PLUS_MIN_RR="1.2",
    )

    assert dc.DEFAULT_CONFIG["minimum_setup_grade"] == "B_PLUS"
    assert dc.DEFAULT_CONFIG["b_plus_min_rr"] == 1.2
    assert dc.DEFAULT_CONFIG["price_action"]["minimum_setup_grade"] == "B_PLUS"
    assert dc.DEFAULT_CONFIG["price_action"]["b_plus_min_rr"] == 1.2


def test_fast_risk_env_updates_price_action_config(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_FAST_ENTRIES_ENABLED="true",
        TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE="2.5",
        TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE="4",
        TRADINGAGENTS_MAX_ENTRY_SPREAD_PRICE="0.6",
        TRADINGAGENTS_MAX_TICK_AGE_SECONDS="90",
    )

    assert dc.DEFAULT_CONFIG["fast_entries_enabled"] is True
    assert dc.DEFAULT_CONFIG["normal_activation_window_minutes"] == 30
    assert dc.DEFAULT_CONFIG["fast_activation_window_minutes"] == 1
    assert dc.DEFAULT_CONFIG["minimum_stop_distance_price"] == 2.5
    assert dc.DEFAULT_CONFIG["minimum_stop_spread_multiple"] == 4.0
    assert dc.DEFAULT_CONFIG["max_entry_spread_price"] == 0.6
    assert dc.DEFAULT_CONFIG["max_tick_age_seconds"] == 90
    assert dc.DEFAULT_CONFIG["price_action"]["minimum_stop_distance_price"] == 2.5
    assert dc.DEFAULT_CONFIG["price_action"]["minimum_stop_spread_multiple"] == 4.0
    assert dc.DEFAULT_CONFIG["price_action"]["max_entry_spread_price"] == 0.6
    assert dc.DEFAULT_CONFIG["price_action"]["max_tick_age_seconds"] == 90


def test_exit_management_env_updates_runner_config(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_EXIT_SCALP_PROFIT_POINTS="1.5",
        TRADINGAGENTS_EXIT_EARLY_LOSS_POINTS="1.5",
        TRADINGAGENTS_EXIT_BREAK_EVEN_TRIGGER_POINTS="1.0",
        TRADINGAGENTS_EXIT_BREAK_EVEN_LOCK_POINTS="0.2",
        TRADINGAGENTS_EXIT_TRAILING_TRIGGER_POINTS="3.0",
        TRADINGAGENTS_EXIT_TRAILING_DISTANCE_POINTS="1.2",
        TRADINGAGENTS_EXIT_MIN_STOP_UPDATE_POINTS="0.3",
        TRADINGAGENTS_EXIT_PARTIAL_FIRST_TRIGGER_POINTS="1.5",
        TRADINGAGENTS_EXIT_PARTIAL_FIRST_TARGET_VOLUME="1.0",
        TRADINGAGENTS_EXIT_PARTIAL_SECOND_TRIGGER_POINTS="2.5",
        TRADINGAGENTS_EXIT_PARTIAL_SECOND_TARGET_VOLUME="0.4",
    )

    assert dc.DEFAULT_CONFIG["exit_scalp_profit_points"] == 1.5
    assert dc.DEFAULT_CONFIG["exit_early_loss_points"] == 1.5
    assert dc.DEFAULT_CONFIG["exit_break_even_trigger_points"] == 1.0
    assert dc.DEFAULT_CONFIG["exit_break_even_lock_points"] == 0.2
    assert dc.DEFAULT_CONFIG["exit_trailing_trigger_points"] == 3.0
    assert dc.DEFAULT_CONFIG["exit_trailing_distance_points"] == 1.2
    assert dc.DEFAULT_CONFIG["exit_min_stop_update_points"] == 0.3
    assert dc.DEFAULT_CONFIG["exit_partial_first_trigger_points"] == 1.5
    assert dc.DEFAULT_CONFIG["exit_partial_first_target_volume"] == 1.0
    assert dc.DEFAULT_CONFIG["exit_partial_second_trigger_points"] == 2.5
    assert dc.DEFAULT_CONFIG["exit_partial_second_target_volume"] == 0.4


def test_empty_env_value_is_passthrough(monkeypatch):
    """Empty TRADINGAGENTS_* values must not clobber the built-in default."""
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_LLM_PROVIDER="",
        TRADINGAGENTS_TIMEFRAME="",
        TRADINGAGENTS_RESULTS_DIR="",
        TRADINGAGENTS_CACHE_DIR="",
    )
    assert dc.DEFAULT_CONFIG["llm_provider"] == "openai"
    assert dc.DEFAULT_CONFIG["timeframe"] == "15m"
    assert dc.DEFAULT_CONFIG["results_dir"] != ""
    assert dc.DEFAULT_CONFIG["data_cache_dir"] != ""


def test_unknown_env_var_is_ignored(monkeypatch):
    """Env vars outside _ENV_OVERRIDES must not bleed into DEFAULT_CONFIG."""
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_NONEXISTENT_KEY="oops",
    )
    assert "nonexistent_key" not in dc.DEFAULT_CONFIG
