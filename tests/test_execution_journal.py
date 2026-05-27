import json
from datetime import datetime, timezone

import pytest

from tradingagents.brokers.execution_journal import ExecutionJournal


def _read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_append_one_event_creates_file_and_preserves_payload(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    path = journal.append("order_submitted", {"ticket": 123, "status": "placed"})

    assert path == tmp_path / "XAUUSD" / "execution_journal" / "mt5_demo_events.jsonl"
    events = _read_events(path)
    assert len(events) == 1
    assert events[0]["event_type"] == "order_submitted"
    assert events[0]["symbol"] == "XAUUSD"
    assert events[0]["payload"] == {"ticket": 123, "status": "placed"}


def test_append_multiple_events_adds_lines_without_overwriting(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="EURUSD")

    path = journal.append("order_submitted", {"ticket": 123})
    journal.append("order_filled", {"ticket": 123, "price": 1.085})

    events = _read_events(path)
    assert [event["event_type"] for event in events] == [
        "order_submitted",
        "order_filled",
    ]
    assert [event["payload"] for event in events] == [
        {"ticket": 123},
        {"price": 1.085, "ticket": 123},
    ]


def test_symbol_path_accepts_broker_suffix_punctuation(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="EURUSD.pro")

    path = journal.append("order_submitted", {})

    assert path.parent == tmp_path / "EURUSD.pro" / "execution_journal"


def test_symbol_path_rejects_unsafe_punctuation(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="../EURUSD")

    with pytest.raises(ValueError, match="not allowed"):
        journal.append("order_submitted", {})


def test_timestamp_is_parseable_timezone_aware_utc(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    path = journal.append("order_submitted", {})

    timestamp = _read_events(path)[0]["timestamp_utc"]
    parsed = datetime.fromisoformat(timestamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)
