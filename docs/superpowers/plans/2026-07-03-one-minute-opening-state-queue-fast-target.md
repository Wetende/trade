# One Minute Opening-State Queue Fast Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate `OPENING_STATE_QUEUE_FAST_TARGET_V1`, a deterministic read-only opening-state family candidate with queued one-active replay and a `1.0R` target.

**Architecture:** Add absolute-expiry delayed replay support to the broker-free tick replay module, then build a focused queue-fast-target screening module on top of the existing opening-state detector and evidence metrics. Keep generated raw outputs ignored; track only tests, source, pre-registered docs, and sanitized aggregate reports.

**Tech Stack:** Python 3.13, Pydantic models, NumPy tick replay, pytest, existing `tradingagents.agents.price_action` modules.

---

## File structure

- Modify `tradingagents/agents/price_action/opening_tick_replay.py`
  - Add delayed-window replay support that preserves absolute original expiry.
  - Preserve existing `simulate()` behavior and tests.
- Create `tradingagents/agents/price_action/opening_state_queue_fast_target.py`
  - Own candidate constants, signal-zone dedupe, queue policy, same-config baseline replay, metrics, gate, and manifest.
- Modify `cli/main.py`
  - Add `one-minute-opening-queue-fast-screen --fixture --output`.
- Modify `tests/test_one_minute_opening_tick_replay.py`
  - Add delayed-window replay tests.
- Create `tests/test_one_minute_opening_state_queue_fast_target.py`
  - Add queue scheduler and screen tests.
- Create `tests/test_one_minute_opening_state_queue_fast_target_cli.py`
  - Add CLI determinism test.
- Create `docs/analysis/2026-07-03-one-minute-opening-state-queue-fast-target-screening.md`
  - Sanitized historical screening result.

---

### Task 1: Delayed absolute-expiry tick replay

**Files:**
- Modify: `tradingagents/agents/price_action/opening_tick_replay.py`
- Modify: `tests/test_one_minute_opening_tick_replay.py`

- [ ] **Step 1: Write failing delayed replay tests**

Append these tests to `tests/test_one_minute_opening_tick_replay.py`:

```python
def test_window_replay_marks_stale_when_slot_frees_after_expiry():
    opportunity = _opportunity(entry_kind="reaction")
    series = PreparedTickSeries.from_ticks((_tick(21, 100.30, 100.50),))

    result = series.simulate_window(
        opportunity,
        ReplayConfig(),
        available_at=START + timedelta(seconds=20),
        expires_at=START + timedelta(seconds=20),
    )

    assert result.status == "EXPIRED"
    assert result.reason == "QUEUE_EXPIRED_BEFORE_AVAILABLE"
    assert result.placed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.completed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.filled_at is None


def test_window_replay_uses_remaining_absolute_expiry():
    opportunity = _opportunity(entry_kind="reaction")
    series = PreparedTickSeries.from_ticks(
        (
            _tick(10, 100.00, 100.10),
            _tick(25, 100.30, 100.50),
        )
    )

    result = series.simulate_window(
        opportunity,
        ReplayConfig(),
        available_at=START + timedelta(seconds=10),
        expires_at=START + timedelta(seconds=20),
    )

    assert result.status == "EXPIRED"
    assert result.reason == "ENTRY_NOT_TOUCHED_BEFORE_EXPIRY"
    assert result.placed_at == (START + timedelta(seconds=10)).isoformat()
    assert result.completed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.filled_at is None


def test_window_replay_places_after_active_slot_frees_and_closes():
    opportunity = _opportunity(entry_kind="continuation")
    series = PreparedTickSeries.from_ticks(
        (
            _tick(12, 100.05, 100.25),
            _tick(13, 100.12, 100.32),
            _tick(14, 101.00, 101.20),
        )
    )

    result = series.simulate_window(
        opportunity,
        ReplayConfig(risk_reward=1.0),
        available_at=START + timedelta(seconds=12),
        expires_at=START + timedelta(seconds=45),
    )

    assert result.status == "CLOSED"
    assert result.placed_at == (START + timedelta(seconds=12)).isoformat()
    assert result.filled_at == (START + timedelta(seconds=13)).isoformat()
    assert result.exit_reason == "TARGET"
    assert result.profit == 0.4
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py -q
```

Expected: FAIL because `PreparedTickSeries.simulate_window` does not exist.

- [ ] **Step 3: Implement delayed replay**

In `opening_tick_replay.py`:

1. Add `placed_at: str | None = None` to `_base_result` and set:

```python
placed_at=placed_at or opportunity.signal_time
```

2. Add `simulate_window()` to `PreparedTickSeries` with this signature:

```python
def simulate_window(
    self,
    opportunity: OpeningOpportunity,
    config: ReplayConfig,
    *,
    available_at: datetime,
    expires_at: datetime,
) -> SimulatedOpeningTrade:
```

3. Implement the same conservative fill/exit logic as `simulate()`, except:

- `placed_at = max(datetime.fromisoformat(opportunity.signal_time), available_at)`;
- if `placed_at >= expires_at`, return `EXPIRED` with reason
  `QUEUE_EXPIRED_BEFORE_AVAILABLE`;
- the decision tick search starts at `placed_at`;
- the fill window ends at `expires_at`;
- no fill after `expires_at` may be counted;
- existing stop/target/ambiguous/no-exit behavior remains unchanged.

- [ ] **Step 4: Run delayed replay tests and verify GREEN**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py -q
```

Expected: all opening tick replay tests pass.

- [ ] **Step 5: Commit delayed replay checkpoint**

Run:

```powershell
git add tradingagents/agents/price_action/opening_tick_replay.py tests/test_one_minute_opening_tick_replay.py
git commit -m "feat: replay delayed opening entries"
```

---

### Task 2: Queue fast-target candidate module

**Files:**
- Create: `tradingagents/agents/price_action/opening_state_queue_fast_target.py`
- Create: `tests/test_one_minute_opening_state_queue_fast_target.py`

- [ ] **Step 1: Write failing queue candidate tests**

Create `tests/test_one_minute_opening_state_queue_fast_target.py`:

```python
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_state_queue_fast_target import (
    QUEUE_FAST_TARGET_CANDIDATE_NAME,
    dedupe_signal_zone_opportunities,
    replay_queue_fast_target_fixture,
    screen_queue_fast_target_fixture,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _opportunity(template, *, signal_offset=0, entry_kind="reaction", level=100.0):
    return OpeningOpportunity(
        template=template,
        direction="BUY",
        signal_time=(START + timedelta(seconds=signal_offset)).isoformat(),
        level_side="high",
        level=level,
        touch_count=2,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind=entry_kind,
    )


def _tick(seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def _fixture(ticks):
    candles = tuple(
        Candle(
            timestamp=(START + timedelta(minutes=i)).isoformat(),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=100,
        )
        for i in range(5)
    )
    return OpeningResearchFixture(schema_version=1, candles=candles, ticks=tuple(ticks))


def test_dedupe_signal_zone_keeps_distinct_levels_only():
    retained = dedupe_signal_zone_opportunities(
        (
            _opportunity(OpeningTemplate.REJECTION, level=100.0),
            _opportunity(OpeningTemplate.BREAK_HOLD, level=100.1),
            _opportunity(OpeningTemplate.FAILED_BREAK, level=101.0),
        )
    )

    assert len(retained) == 2
    assert retained[0].template == OpeningTemplate.BREAK_HOLD
    assert retained[1].template == OpeningTemplate.FAILED_BREAK


def test_queue_replay_accepts_fresh_second_after_first_expires():
    fixture = _fixture(
        (
            _tick(0, 99.90, 100.00),
            _tick(20, 99.90, 100.00),
            _tick(21, 100.12, 100.32),
            _tick(22, 100.80, 101.00),
        )
    )

    rows = replay_queue_fast_target_fixture(
        fixture,
        opportunities=(
            _opportunity(OpeningTemplate.REJECTION, entry_kind="reaction"),
            _opportunity(OpeningTemplate.BREAK_HOLD, entry_kind="continuation"),
        ),
    )

    assert rows[0].accepted is True
    assert rows[0].filled is False
    assert rows[1].accepted is True
    assert rows[1].filled is True


def test_queue_replay_skips_stale_second_after_active_trade():
    fixture = _fixture(
        (
            _tick(0, 100.12, 100.32),
            _tick(10, 100.80, 101.00),
            _tick(25, 100.12, 100.32),
        )
    )

    rows = replay_queue_fast_target_fixture(
        fixture,
        opportunities=(
            _opportunity(OpeningTemplate.REJECTION, entry_kind="reaction"),
            _opportunity(OpeningTemplate.FAILED_BREAK, entry_kind="reaction"),
        ),
    )

    assert rows[0].accepted is True
    assert rows[0].filled is True
    assert rows[1].accepted is False
    assert rows[1].reasons == ("QUEUE_EXPIRED_BEFORE_AVAILABLE",)


def test_queue_screen_uses_fast_target_manifest_when_gates_pass():
    report = screen_queue_fast_target_fixture(
        "tests/fixtures/one_minute/opening_state/sample-openings.json"
    )

    assert report["candidate"] == QUEUE_FAST_TARGET_CANDIDATE_NAME
    assert report["broker_mutation_enabled"] is False
    assert report["replay_config"]["risk_reward"] == 1.0
    assert report["gate"]["passed"] is True
    assert report["frozen_manifest"]["candidate"] == QUEUE_FAST_TARGET_CANDIDATE_NAME
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_queue_fast_target.py -q
```

Expected: FAIL because `opening_state_queue_fast_target` does not exist.

- [ ] **Step 3: Implement queue fast-target module**

Create `opening_state_queue_fast_target.py` with:

- `QUEUE_FAST_TARGET_CANDIDATE_NAME = "OPENING_STATE_QUEUE_FAST_TARGET_V1"`;
- `QUEUE_POLICY_VERSION = 1`;
- `FAST_TARGET_REPLAY_CONFIG = ReplayConfig(risk_reward=1.0)`;
- deterministic rank and signal-zone dedupe matching the spec;
- same-config baseline replay over all raw opportunities;
- queued one-active replay using `PreparedTickSeries.simulate_window`;
- `screen_queue_fast_target_fixture()`.

The report dictionary must include:

```python
{
    "schema_version": 1,
    "candidate": QUEUE_FAST_TARGET_CANDIDATE_NAME,
    "queue_policy_version": QUEUE_POLICY_VERSION,
    "broker_mutation_enabled": False,
    "source_fixture_hash": source_hash,
    "replay_config": FAST_TARGET_REPLAY_CONFIG.model_dump(mode="json"),
    "baseline": baseline.model_dump(mode="json"),
    "metrics": metrics.model_dump(mode="json"),
    "gate": gate.model_dump(mode="json"),
    "decision": "FREEZE_OPENING_STATE_QUEUE_FAST_TARGET" if gate.passed else "NO_OPENING_STATE_QUEUE_FAST_TARGET_EDGE",
    "frozen_manifest": frozen_manifest,
}
```

- [ ] **Step 4: Run queue candidate tests and verify GREEN**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_queue_fast_target.py -q
```

Expected: all queue candidate tests pass.

- [ ] **Step 5: Commit queue module checkpoint**

Run:

```powershell
git add tradingagents/agents/price_action/opening_state_queue_fast_target.py tests/test_one_minute_opening_state_queue_fast_target.py
git commit -m "feat: screen opening-state queue fast target"
```

---

### Task 3: CLI and historical report

**Files:**
- Modify: `cli/main.py`
- Create: `tests/test_one_minute_opening_state_queue_fast_target_cli.py`
- Create: `docs/analysis/2026-07-03-one-minute-opening-state-queue-fast-target-screening.md`

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_one_minute_opening_state_queue_fast_target_cli.py`:

```python
import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_queue_fast_target import (
    screen_queue_fast_target_fixture,
)


FIXTURE = "tests/fixtures/one_minute/opening_state/sample-openings.json"


def test_opening_queue_fast_cli_writes_deterministic_report(tmp_path):
    output = tmp_path / "queue-fast-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-queue-fast-screen",
            "--fixture",
            FIXTURE,
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == screen_queue_fast_target_fixture(FIXTURE)
```

- [ ] **Step 2: Run CLI test and verify RED**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_queue_fast_target_cli.py -q
```

Expected: FAIL because the CLI command is missing.

- [ ] **Step 3: Implement CLI command**

Add command to `cli/main.py`:

```python
@app.command("one-minute-opening-queue-fast-screen")
def one_minute_opening_queue_fast_screen(
    fixture: Path = typer.Option(..., exists=True, file_okay=True, dir_okay=False),
    output: Path = typer.Option(...),
) -> None:
    from tradingagents.agents.price_action.opening_state_queue_fast_target import (
        screen_queue_fast_target_fixture,
    )

    report = screen_queue_fast_target_fixture(fixture)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    typer.echo(str(output))
```

- [ ] **Step 4: Run CLI test and focused opening tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py tests/test_one_minute_opening_state_queue_fast_target.py tests/test_one_minute_opening_state_queue_fast_target_cli.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Run historical screen**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m cli.main one-minute-opening-queue-fast-screen --fixture test-artifacts/opening-state/read-only-mt5-opening-fixture.json --output test-artifacts/opening-state/read-only-opening-queue-fast-target-screen.json
```

Expected: writes ignored JSON report; no broker access.

- [ ] **Step 6: Write sanitized tracked analysis report**

Write `docs/analysis/2026-07-03-one-minute-opening-state-queue-fast-target-screening.md` with:

- fixture size and source hash;
- baseline metrics;
- candidate metrics;
- gate reasons;
- decision;
- safety statement.

- [ ] **Step 7: Commit CLI/report checkpoint**

Run:

```powershell
git add cli/main.py tests/test_one_minute_opening_state_queue_fast_target_cli.py docs/analysis/2026-07-03-one-minute-opening-state-queue-fast-target-screening.md
git commit -m "docs: report opening-state queue fast target"
```

---

### Task 4: Verification and push

**Files:**
- Review all changed source, tests, and docs.

- [ ] **Step 1: Run focused opening suites**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state.py tests/test_one_minute_opening_tick_replay.py tests/test_one_minute_opening_screening.py tests/test_one_minute_opening_state_cli.py tests/test_one_minute_opening_state_family.py tests/test_one_minute_opening_state_family_cli.py tests/test_one_minute_opening_state_queue_fast_target.py tests/test_one_minute_opening_state_queue_fast_target_cli.py -q
```

- [ ] **Step 2: Run related scalper/evidence suites**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_evidence_metrics.py tests/test_one_minute_evidence_gate.py tests/test_one_minute_replay.py tests/test_one_minute_shadow*.py tests/test_one_minute_entry_model.py -q
```

- [ ] **Step 3: Run full suite**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 4: Run whitespace and status checks**

Run:

```powershell
git diff --check
git status --short --branch --untracked-files=all
```

- [ ] **Step 5: Secret/staged-file inspection**

Run a changed-file scan that prints only filenames, not secret values. Do not
stage `.env`, credentials, account identifiers, terminal stores, or raw MT5
artifacts.

- [ ] **Step 6: Push branch and main only after tests pass**

Run:

```powershell
git push -u origin codex/opening-retention-scheduler
```

Then fast-forward main, rerun full tests, push main, and confirm:

```powershell
git rev-parse HEAD
git rev-parse origin/main
```

## Self-review

- Spec coverage: delayed placement, queue semantics, `1.0R` target, same-config
  baseline, historical gate, failure behavior, and broker-free safety are
  covered by tasks.
- Placeholder scan: no task relies on TBD values or unspecified files.
- Type consistency: candidate constants, replay method, and CLI command names
  are introduced before use.
