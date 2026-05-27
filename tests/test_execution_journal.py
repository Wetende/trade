import json
from collections import namedtuple
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

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


class ExecutionState(Enum):
    ACCEPTED = "accepted"


class BrokerModel(BaseModel):
    ticket: int
    received_at: datetime


def test_append_normalizes_common_payload_values(tmp_path):
    Fill = namedtuple("Fill", ["price", "quantity"])
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    path = journal.append(
        "order_submitted",
        {
            "submitted_at": datetime(2026, 5, 27, 3, 4, 5, tzinfo=timezone.utc),
            "trade_date": date(2026, 5, 27),
            "price": Decimal("2450.123"),
            "state": ExecutionState.ACCEPTED,
            "model": BrokerModel(
                ticket=123,
                received_at=datetime(2026, 5, 27, 3, 4, 6, tzinfo=timezone.utc),
            ),
            "fill": Fill(price=Decimal("2450.50"), quantity=1),
            "sdk_object": SimpleNamespace(order_id=456, status=ExecutionState.ACCEPTED),
            "unknown": object(),
        },
    )

    payload = _read_events(path)[0]["payload"]
    assert payload["submitted_at"] == "2026-05-27T03:04:05+00:00"
    assert payload["trade_date"] == "2026-05-27"
    assert payload["price"] == "2450.123"
    assert payload["state"] == "accepted"
    assert payload["model"] == {
        "ticket": 123,
        "received_at": "2026-05-27T03:04:06+00:00",
    }
    assert payload["fill"] == {"price": "2450.50", "quantity": 1}
    assert payload["sdk_object"] == {"order_id": 456, "status": "accepted"}
    assert isinstance(payload["unknown"], str)


@pytest.mark.parametrize("event_type", ["", "   "])
def test_append_rejects_blank_event_type(tmp_path, event_type):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    with pytest.raises(ValueError, match="event_type"):
        journal.append(event_type, {})


def test_append_rejects_symbol_symlink_that_escapes_results_dir(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}_outside"
    outside.mkdir(exist_ok=True)
    symbol_link = tmp_path / "XAUUSD"
    try:
        symbol_link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported: {exc}")

    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    with pytest.raises(ValueError, match="outside results_dir"):
        journal.append("order_submitted", {})


def test_multiple_low_level_appends_produce_complete_json_lines(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="EURUSD")

    path = journal.append("event_0", {"index": 0})
    for index in range(1, 20):
        journal.append(f"event_{index}", {"index": index})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    events = [json.loads(line) for line in lines]
    assert [event["payload"]["index"] for event in events] == list(range(20))
