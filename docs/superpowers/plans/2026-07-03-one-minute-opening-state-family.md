# One Minute Opening-State Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate `OPENING_STATE_FAMILY_V1`, a deterministic all-template M1 opening-state family candidate with one-active simulated execution and historical freeze gating.

**Architecture:** Reuse the existing opening-state detector and prepared tick replay. Add a focused family module that ranks raw opportunities, selects at most one per minute/local zone, enforces one-active replay, computes existing historical gates, and emits a frozen manifest only when all gates pass.

**Tech Stack:** Python 3, Pydantic, Typer CLI, pytest, existing price-action evidence metrics.

---

## File Structure

- Modify `tradingagents/agents/price_action/opening_tick_replay.py`
  - Add `completed_at` to simulated trades so one-active replay can know when a pending order or position is no longer active.
- Create `tradingagents/agents/price_action/opening_state_family.py`
  - Owns `OPENING_STATE_FAMILY_V1` ranking, one-active replay, metrics, gate result, and frozen manifest payload.
- Create `tests/test_one_minute_opening_state_family.py`
  - Tests ranking, local-zone de-duplication, one-active skips, deterministic report output, and manifest behavior.
- Modify `cli/main.py`
  - Add `one-minute-opening-family-screen --fixture --output`.
- Create `tests/test_one_minute_opening_state_family_cli.py`
  - Tests the CLI writes the same broker-free report as the Python API.
- Create `docs/analysis/2026-07-03-one-minute-opening-state-family-screening.md`
  - Records actual historical gate result from the ignored read-only fixture.

---

### Task 1: Replay completion timestamps

**Files:**
- Modify: `tradingagents/agents/price_action/opening_tick_replay.py`
- Modify: `tests/test_one_minute_opening_tick_replay.py`

- [ ] **Step 1: Write failing tests**

Add assertions:

```python
def test_reaction_order_records_expiry_completion_time():
    opportunity = _buy_opportunity().model_copy(update={"entry_kind": "reaction"})
    ticks = [_tick(0, 99.70, 99.90), _tick(21, 99.75, 99.95)]

    result = simulate_opportunity(opportunity, ticks, ReplayConfig())

    assert result.status == "EXPIRED"
    assert result.completed_at == (START + timedelta(seconds=20)).isoformat()


def test_closed_trade_completion_time_is_close_time():
    result = simulate_opportunity(
        _buy_opportunity(),
        [_tick(0, 100.05, 100.25), _tick(3, 101.50, 101.70)],
        ReplayConfig(),
    )

    assert result.status == "CLOSED"
    assert result.completed_at == result.closed_at
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py -q
```

Expected: FAIL because `completed_at` is missing.

- [ ] **Step 3: Implement completion timestamps**

Add `completed_at: str | None` to `SimulatedOpeningTrade`. Add a
`completed_at` parameter to `_base_result`.

Set:

- missing/no-valid decision tick: `completed_at=opportunity.signal_time`;
- expired pending order: `completed_at=expiry.isoformat()`;
- closed trade: `completed_at=closed_at`;
- ambiguous filled trade: `completed_at` equal to the ambiguous tick time;
- no-exit filled trade: `completed_at` equal to the final valid tick time when available.

Make scalar and `PreparedTickSeries` paths produce identical results.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py -q
```

Expected: all replay tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/opening_tick_replay.py tests/test_one_minute_opening_tick_replay.py
git commit -m "feat: record opening replay completion"
```

---

### Task 2: Family ranking and one-active replay

**Files:**
- Create: `tradingagents/agents/price_action/opening_state_family.py`
- Create: `tests/test_one_minute_opening_state_family.py`

- [ ] **Step 1: Write failing tests**

Create tests that assert:

```python
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_state_family import (
    FAMILY_CANDIDATE_NAME,
    rank_family_opportunities,
    replay_family_fixture,
    screen_family_fixture,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _opportunity(template, direction="BUY", level=100.0, touch_count=2):
    return OpeningOpportunity(
        template=template,
        direction=direction,
        signal_time=START.isoformat(),
        level_side="high",
        level=level,
        touch_count=touch_count,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind="continuation",
    )


def _tick(seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def test_family_ranking_prefers_touch_count_then_lifecycle_priority():
    ranked = rank_family_opportunities(
        (
            _opportunity(OpeningTemplate.REJECTION, touch_count=3),
            _opportunity(OpeningTemplate.BREAK_RETEST_HOLD, touch_count=2),
            _opportunity(OpeningTemplate.FAILED_BREAK, touch_count=3),
        )
    )

    assert [item.template for item in ranked] == [
        OpeningTemplate.FAILED_BREAK,
        OpeningTemplate.REJECTION,
        OpeningTemplate.BREAK_RETEST_HOLD,
    ]


def test_family_replay_enforces_one_active_trade():
    candles = [
        Candle(timestamp=(START + timedelta(minutes=i)).isoformat(), open=100, high=101, low=99, close=100.5, volume=100)
        for i in range(5)
    ]
    fixture = OpeningResearchFixture(
        schema_version=1,
        candles=tuple(candles),
        ticks=(
            _tick(0, 100.05, 100.25),
            _tick(5, 100.06, 100.26),
            _tick(10, 101.50, 101.70),
        ),
    )
    rows = replay_family_fixture(
        fixture,
        opportunities=(
            _opportunity(OpeningTemplate.BREAK_HOLD),
            _opportunity(OpeningTemplate.BREAK_RETEST_HOLD),
        ),
    )

    assert rows[0].accepted is True
    assert rows[0].filled is True
    assert rows[1].accepted is False
    assert rows[1].reasons == ("ONE_ACTIVE_FAMILY_POSITION",)


def test_family_screen_freezes_manifest_when_gates_pass():
    fixture_path = "tests/fixtures/one_minute/opening_state/sample-openings.json"
    report = screen_family_fixture(fixture_path)

    assert report["candidate"] == FAMILY_CANDIDATE_NAME
    assert report["broker_mutation_enabled"] is False
    assert report["gate"]["passed"] is True
    assert report["frozen_manifest"]["candidate"] == FAMILY_CANDIDATE_NAME
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_family.py -q
```

Expected: FAIL because `opening_state_family` does not exist.

- [ ] **Step 3: Implement family module**

Implement:

- `FAMILY_CANDIDATE_NAME = "OPENING_STATE_FAMILY_V1"`;
- `rank_family_opportunities(opportunities)`;
- minute/local-zone deterministic selection;
- `replay_family_fixture(fixture, opportunities=None)`;
- `screen_family_fixture(path_or_fixture)`.

Use `PreparedTickSeries` for replay. Convert accepted closed trades into
`ScreeningRow` objects and evaluate with existing `summarize_variant` and
`evaluate_historical_gate`. Baseline is all raw opening-state template rows
from `opening_state_screening._baseline_rows`.

If gate passes, include:

```python
"frozen_manifest": {
    "candidate": FAMILY_CANDIDATE_NAME,
    "ranking_version": 1,
    "source_fixture_hash": source_hash,
    "historical_metrics": metrics.model_dump(mode="json"),
    "broker_mutation_enabled": False,
    "next_stage": "READ_ONLY_PROSPECTIVE_SHADOW",
}
```

If gate fails, set `frozen_manifest` to `None` and decision to
`NO_OPENING_STATE_FAMILY_EDGE`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_family.py -q
```

Expected: all family tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/opening_state_family.py tests/test_one_minute_opening_state_family.py
git commit -m "feat: screen opening-state family candidate"
```

---

### Task 3: CLI and actual historical report

**Files:**
- Modify: `cli/main.py`
- Create: `tests/test_one_minute_opening_state_family_cli.py`
- Create: `docs/analysis/2026-07-03-one-minute-opening-state-family-screening.md`

- [ ] **Step 1: Write failing CLI test**

Create a CLI test mirroring the existing opening-state CLI test:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_family import (
    screen_family_fixture,
)


FIXTURE = Path("tests/fixtures/one_minute/opening_state/sample-openings.json")


def test_opening_family_cli_writes_deterministic_report(tmp_path):
    output = tmp_path / "family-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-family-screen",
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == screen_family_fixture(FIXTURE)
    assert payload["broker_mutation_enabled"] is False
```

- [ ] **Step 2: Run CLI test and verify RED**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_family_cli.py -q
```

Expected: FAIL because the CLI command does not exist.

- [ ] **Step 3: Add CLI command**

Add `one-minute-opening-family-screen --fixture --output` to `cli/main.py`.
It must import only `screen_family_fixture`, write atomic JSON, and print the
same report.

- [ ] **Step 4: Run actual historical screen**

Use ignored fixture:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe - <<'PY'
from pathlib import Path
from tradingagents.agents.price_action.opening_state_family import screen_family_fixture
import json
report = screen_family_fixture(Path("test-artifacts/opening-state/read-only-mt5-opening-fixture.json"))
Path("test-artifacts/opening-state/read-only-mt5-opening-family-screen.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({
    "decision": report["decision"],
    "gate": report["gate"],
    "metrics": report["metrics"],
    "frozen": report["frozen_manifest"] is not None,
}, indent=2, sort_keys=True))
PY
```

Use PowerShell here-string syntax when executing this command.

- [ ] **Step 5: Write tracked analysis report**

Write `docs/analysis/2026-07-03-one-minute-opening-state-family-screening.md`
with:

- data source counts from the prior report;
- candidate metrics;
- gate reasons;
- whether a frozen manifest exists;
- explicit next stage if frozen;
- safety statement that no broker mutation occurred.

- [ ] **Step 6: Commit**

```powershell
git add cli/main.py tests/test_one_minute_opening_state_family_cli.py docs/analysis/2026-07-03-one-minute-opening-state-family-screening.md
git commit -m "docs: report opening-state family candidate"
```

---

### Task 4: Verification and push

**Files:**
- All above.

- [ ] **Step 1: Run focused family/opening tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state.py tests/test_one_minute_opening_tick_replay.py tests/test_one_minute_opening_screening.py tests/test_one_minute_opening_state_cli.py tests/test_one_minute_opening_state_family.py tests/test_one_minute_opening_state_family_cli.py -q
```

- [ ] **Step 2: Run related scalper tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_one_minute_evidence_gate.py tests/test_one_minute_evidence_metrics.py tests/test_one_minute_historical_screening.py tests/test_one_minute_walk_forward_selector.py tests/test_one_minute_walk_forward_cli.py tests/test_one_minute_signal_replay.py tests/test_one_minute_entry_model.py -q
```

- [ ] **Step 3: Run full suite**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 4: Run safety checks**

Run:

```powershell
git diff --check
git status --short --branch
git grep -n -E 'TRADINGAGENTS_MT5_PASSWORD|TRADINGAGENTS_MT5_LOGIN=.*[0-9]|password[[:space:]]*[:=][[:space:]]*["'']|api[_-]*key[[:space:]]*[:=][[:space:]]*["'']|token[[:space:]]*[:=][[:space:]]*["'']' HEAD
Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -or $_.Name -like 'tradingagents*' } | Select-Object ProcessId,Name,CreationDate,CommandLine
```

Review hits manually; placeholder/test strings are acceptable, populated
secrets are not.

- [ ] **Step 5: Merge and push**

Fast-forward `main` from `codex/opening-state-family`, rerun full tests on
merged `main`, push `main`, and verify `HEAD == origin/main`.

---

## Self-Review

- Spec coverage: ranking, one-active execution, historical gate, frozen
  manifest, prospective boundary, and safety are all covered.
- Placeholder scan: no unfinished implementation placeholders remain.
- Type consistency: `FAMILY_CANDIDATE_NAME`, `rank_family_opportunities`,
  `replay_family_fixture`, and `screen_family_fixture` are introduced before
  CLI/report tasks use them.
