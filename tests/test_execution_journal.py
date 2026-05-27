import json
import math
import threading
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import os
import stat
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


def test_append_creates_owner_only_journal_paths(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path / "results", symbol="XAUUSD")

    path = journal.append("order_submitted", {})

    assert stat.S_IMODE((tmp_path / "results").stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


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


@pytest.mark.parametrize(
    "event_type",
    [" order_submitted", "order_submitted ", "order-submitted", "order\nsubmitted"],
)
def test_append_rejects_event_type_with_invalid_characters(tmp_path, event_type):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    with pytest.raises(ValueError, match="event_type"):
        journal.append(event_type, {})


def test_append_normalizes_cyclic_payloads(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")
    cyclic_dict = {"name": "parent"}
    cyclic_list = ["first"]
    cyclic_object = SimpleNamespace(name="sdk")
    cyclic_dict["self"] = cyclic_dict
    cyclic_list.append(cyclic_list)
    cyclic_object.self = cyclic_object

    path = journal.append(
        "order_submitted",
        {
            "dict": cyclic_dict,
            "list": cyclic_list,
            "object": cyclic_object,
        },
    )

    payload = _read_events(path)[0]["payload"]
    assert payload["dict"] == {"name": "parent", "self": "<cycle>"}
    assert payload["list"] == ["first", "<cycle>"]
    assert payload["object"] == {"name": "sdk", "self": "<cycle>"}


def test_append_normalizes_non_finite_floats_for_strict_json(tmp_path):
    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    path = journal.append(
        "order_submitted",
        {"nan": math.nan, "inf": math.inf, "neg_inf": -math.inf, "finite": 1.5},
    )

    raw_line = path.read_text(encoding="utf-8").strip()
    assert "NaN" not in raw_line
    assert "Infinity" not in raw_line
    payload = json.loads(raw_line)["payload"]
    assert payload == {
        "nan": "nan",
        "inf": "inf",
        "neg_inf": "-inf",
        "finite": 1.5,
    }


def test_append_rejects_symbol_symlink_that_escapes_results_dir(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}_outside"
    outside.mkdir(exist_ok=True)
    symbol_link = tmp_path / "XAUUSD"
    try:
        symbol_link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported: {exc}")

    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    with pytest.raises(ValueError):
        journal.append("order_submitted", {})


def test_append_rejects_execution_journal_symlink_that_escapes_results_dir(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}_journal_outside"
    outside.mkdir(exist_ok=True)
    symbol_dir = tmp_path / "XAUUSD"
    symbol_dir.mkdir()
    journal_link = symbol_dir / "execution_journal"
    try:
        journal_link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported: {exc}")

    journal = ExecutionJournal(results_dir=tmp_path, symbol="XAUUSD")

    with pytest.raises(ValueError):
        journal.append("order_submitted", {})


def test_concurrent_appends_produce_complete_json_lines(tmp_path):
    total_events = 40
    barrier = threading.Barrier(total_events)

    def append_event(index):
        journal = ExecutionJournal(results_dir=tmp_path, symbol="EURUSD")
        barrier.wait(timeout=5)
        return journal.append("order_submitted", {"index": index})

    with ThreadPoolExecutor(max_workers=total_events) as executor:
        paths = list(executor.map(append_event, range(total_events)))

    assert len(set(paths)) == 1
    lines = paths[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == total_events
    events = [json.loads(line) for line in lines]
    assert {event["payload"]["index"] for event in events} == set(range(total_events))


def test_append_retries_short_low_level_writes(tmp_path, monkeypatch):
    real_write = os.write

    def short_write(fd, data):
        if len(data) > 1:
            return real_write(fd, data[: len(data) // 2])
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", short_write)
    journal = ExecutionJournal(results_dir=tmp_path, symbol="EURUSD")

    path = journal.append("order_submitted", {"index": 1})

    assert _read_events(path)[0]["payload"] == {"index": 1}


def test_concurrent_short_writes_produce_complete_json_lines(tmp_path, monkeypatch):
    real_write = os.write
    total_events = 20
    barrier = threading.Barrier(total_events)

    def short_write(fd, data):
        if len(data) > 1:
            written = real_write(fd, data[: len(data) // 2])
            time.sleep(0.001)
            return written
        return real_write(fd, data)

    def append_event(index):
        journal = ExecutionJournal(results_dir=tmp_path, symbol="EURUSD")
        barrier.wait(timeout=5)
        return journal.append("order_submitted", {"index": index})

    monkeypatch.setattr(os, "write", short_write)
    with ThreadPoolExecutor(max_workers=total_events) as executor:
        paths = list(executor.map(append_event, range(total_events)))

    lines = paths[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == total_events
    events = [json.loads(line) for line in lines]
    assert {event["payload"]["index"] for event in events} == set(range(total_events))
