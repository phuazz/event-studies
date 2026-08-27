"""Tests for scripts/emit_state.py — the STATE_CONTRACT emission.

Most of this emission is a copy, but two parts are DERIVED and are where the
tests concentrate:

  1. The anchor and the live/not-live state. The consumer currently hard-codes
     the 2026 anchor and reports LIVE unconditionally; both are true today and
     neither will be forever. This reads them from the data instead, so the two
     will part company exactly when the hard-coded copy goes stale — and the
     consumer's shadow comparison reporting that divergence IS the alarm on it.
  2. The forward window. A 9-month window from a month-end anchor must land on
     the corresponding month-end, which a day count does not do.

Every expected date below was computed with dateutil and checked against the
calendar, not written from memory. Per the house rule the boundary cases include
a month boundary, a year boundary and a leap-year clamp. Python datetime months
are 1-indexed (June == 6).

NOTE: this repo has no CI test run, so these are a local guard rather than a
gate. Run them by hand after touching emit_state.py:

    python -m pytest tests/test_emit_state.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import emit_state  # noqa: E402

REQUIRED = {"as_of", "state", "value", "zone", "role", "horizon",
            "evidence_grade", "licence", "action_hint", "source_file"}
OPTIONAL = {"computed_at", "cadence"}
SIGNAL = "event_strong_q2"
EVENT_ID = "spx-strong-q2-9m-forward"


def _episode(date="2026-06-30", fwd=None):
    return {"date": date, "idx": 929, "regime": "on",
            "fwd": fwd if fwd is not None else {"3": None, "6": None, "9": None, "12": None}}


def _results(episodes=None, n_triggers=22, generated="2026-08-27T04:29:49.500Z",
             event_id=EVENT_ID):
    return {
        "generatedAt": generated,
        "events": [
            {"id": "gld-oversold-reversion", "nTriggers": 9,
             "episodes": [_episode("2026-01-15")]},
            {"id": event_id, "nTriggers": n_triggers,
             "nEpisodes": n_triggers,
             "episodes": episodes if episodes is not None else [
                 _episode("2025-06-30", {"3": 0.02, "6": 0.05, "9": 0.08, "12": 0.1}),
                 _episode("2026-06-30")]},
        ],
    }


@pytest.fixture
def store(monkeypatch):
    box = {"d": _results()}
    monkeypatch.setattr(emit_state, "load_results", lambda: box["d"])
    return box


# --- the forward window -----------------------------------------------------

@pytest.mark.parametrize("anchor,expected", [
    ("2026-06-30", "2027-03-30"),   # the live instance; crosses the YEAR boundary
    ("2026-03-31", "2026-12-31"),   # MONTH-end within the same year
    ("2026-05-31", "2027-02-28"),   # clamps to a 28-day February
    ("2023-05-31", "2024-02-29"),   # clamps to a LEAP February
    ("2026-01-31", "2026-10-31"),
    ("2026-12-31", "2027-09-30"),   # September has 30 days
])
def test_the_nine_month_window_lands_on_the_right_day(anchor, expected):
    a, e = emit_state.window(anchor)
    assert a.isoformat() == anchor
    assert e.isoformat() == expected


def test_the_window_is_not_a_day_count():
    """270 days from 30 June 2026 is 27 March 2027, not 30 March. A day count
    would be wrong by three days here and by more at other anchors."""
    import datetime as dt
    a, e = emit_state.window("2026-06-30")
    assert e != a + dt.timedelta(days=270)
    assert e.isoformat() == "2027-03-30"


def test_a_malformed_anchor_date_is_refused(store):
    store["d"] = _results(episodes=[_episode("30-06-2026")])
    with pytest.raises(emit_state.EmitError, match="ISO date"):
        emit_state.build()


# --- the anchor is derived, not hard-coded ----------------------------------

def test_the_anchor_comes_from_the_LAST_episode(store):
    assert emit_state.build()["signals"][SIGNAL]["zone"] == \
        "window 2026-06-30 → 2027-03-30"


def test_a_new_episode_moves_the_anchor(store):
    """The consumer's hard-coded 2026-06-30 would not move here. That is the
    divergence this emitter exists to surface."""
    store["d"] = _results(episodes=[_episode("2026-06-30",
                                             {"3": 0.01, "6": 0.02, "9": 0.03, "12": 0.04}),
                                    _episode("2027-06-30")])
    assert emit_state.build()["signals"][SIGNAL]["zone"] == \
        "window 2027-06-30 → 2028-03-30"


def test_an_empty_episode_list_is_refused(store):
    store["d"] = _results(episodes=[])
    with pytest.raises(emit_state.EmitError, match="no episodes"):
        emit_state.build()


# --- live is derived from the resolved forward return -----------------------

def test_an_unresolved_nine_month_return_reads_LIVE(store):
    assert emit_state.build()["signals"][SIGNAL]["state"] == "LIVE"


def test_a_resolved_nine_month_return_reads_NOT_LIVE(store):
    """The consumer reports LIVE unconditionally, so this is the second place
    the two will part company — correctly, and loudly."""
    store["d"] = _results(episodes=[_episode("2026-06-30",
                                             {"3": 0.02, "6": 0.04, "9": 0.07, "12": None})])
    assert emit_state.build()["signals"][SIGNAL]["state"] == "NOT_LIVE"


def test_a_resolved_SHORTER_horizon_does_not_end_the_window(store):
    """Only the study's own 9-month horizon decides. A resolved 3-month return
    on a 9-month study would otherwise close the window six months early."""
    store["d"] = _results(episodes=[_episode("2026-06-30",
                                             {"3": 0.02, "6": None, "9": None, "12": None})])
    assert emit_state.build()["signals"][SIGNAL]["state"] == "LIVE"


def test_a_missing_nine_month_horizon_is_refused_not_defaulted_to_live(store):
    """Defaulting to LIVE on a schema change would report an open window on the
    strength of a key that no longer exists."""
    store["d"] = _results(episodes=[_episode("2026-06-30", {"3": None, "6": None})])
    with pytest.raises(emit_state.EmitError, match="horizon"):
        emit_state.build()


def test_a_zero_forward_return_is_resolved_not_missing(store):
    """0.0 is falsy. A truthiness test would read a flat 9-month return as
    unresolved and keep reporting the window open forever."""
    store["d"] = _results(episodes=[_episode("2026-06-30",
                                             {"3": 0.0, "6": 0.0, "9": 0.0, "12": 0.0})])
    assert emit_state.build()["signals"][SIGNAL]["state"] == "NOT_LIVE"


# --- shape and selection ----------------------------------------------------

def test_only_the_strong_q2_signal_is_emitted(store):
    """The catalogue holds other events, and the global-ETF breadth lead is a
    recorded GAP with no published state. Neither may appear here."""
    assert set(emit_state.build()["signals"]) == {SIGNAL}


def test_the_right_event_is_selected_from_the_catalogue(store):
    assert emit_state.build()["signals"][SIGNAL]["value"] == 22


def test_a_missing_event_is_refused(store):
    store["d"] = _results(event_id="something-else")
    with pytest.raises(emit_state.EmitError, match=EVENT_ID):
        emit_state.build()


def test_the_block_carries_the_required_fields_and_nothing_unknown(store):
    block = emit_state.build()["signals"][SIGNAL]
    assert REQUIRED <= set(block), f"missing {REQUIRED - set(block)}"
    assert set(block) <= REQUIRED | OPTIONAL, f"unknown {set(block) - REQUIRED - OPTIONAL}"


def test_no_score_or_weight_field_is_emitted(store):
    banned = {"score", "weight", "composite", "rank"}
    assert not (banned & set(emit_state.build()["signals"][SIGNAL]))


def test_as_of_is_the_catalogue_generation_date(store):
    s = emit_state.build()["signals"][SIGNAL]
    assert s["as_of"] == "2026-08-27"
    assert s["computed_at"] == "2026-08-27T04:29:49.500Z"


def test_the_envelope_names_its_version_and_source(store):
    p = emit_state.build()
    assert p["contract_version"] == "1"
    assert p["emitted_by"] == "event-studies"


@pytest.mark.parametrize("key", ["generatedAt", "events"])
def test_a_missing_top_level_key_stops_the_emission(store, key):
    del store["d"][key]
    with pytest.raises(emit_state.EmitError, match=key):
        emit_state.build()


def test_a_missing_trigger_count_stops_the_emission(store):
    del store["d"]["events"][1]["nTriggers"]
    with pytest.raises(emit_state.EmitError, match="nTriggers"):
        emit_state.build()


# --- a failed run must not leave a half-written file -------------------------

def test_a_failed_run_writes_nothing_and_exits_non_zero(store, monkeypatch, tmp_path, capsys):
    out = tmp_path / "state.json"
    out.write_text('{"previous": "emission"}', encoding="utf-8")
    monkeypatch.setattr(emit_state, "OUT", out)
    store["d"] = _results(event_id="gone")

    assert emit_state.main([]) == 1
    assert json.loads(out.read_text(encoding="utf-8")) == {"previous": "emission"}
    assert "FAILED" in capsys.readouterr().err


def test_an_unchanged_state_is_not_rewritten(store, monkeypatch, tmp_path):
    out = tmp_path / "state.json"
    monkeypatch.setattr(emit_state, "OUT", out)
    assert emit_state.main([]) == 0
    first = out.read_text(encoding="utf-8")
    assert emit_state.main([]) == 0
    assert out.read_text(encoding="utf-8") == first, "unchanged state was rewritten"


def test_a_rebuilt_catalogue_DOES_rewrite(store, monkeypatch, tmp_path):
    """generatedAt moves on every catalogue rebuild, so as_of and computed_at
    change daily even when the event state does not. That is a real change and
    must be published; only the pure no-op is suppressed."""
    out = tmp_path / "state.json"
    monkeypatch.setattr(emit_state, "OUT", out)
    assert emit_state.main([]) == 0
    store["d"] = _results(generated="2026-08-28T04:30:00.000Z")
    assert emit_state.main([]) == 0
    assert json.loads(out.read_text(encoding="utf-8")) \
        ["signals"][SIGNAL]["as_of"] == "2026-08-28"


def test_check_mode_writes_nothing(store, monkeypatch, tmp_path):
    out = tmp_path / "state.json"
    monkeypatch.setattr(emit_state, "OUT", out)
    assert emit_state.main(["--check"]) == 0
    assert not out.exists()
