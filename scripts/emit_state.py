"""emit_state.py — publish the strong-Q2 event state in the STATE_CONTRACT shape.

WHAT THIS IS FOR
----------------
A private consumer (the command centre) renders this catalogue's live strong-Q2
instance beside signals from seven other projects. Until now it did that by
reaching INTO this repo for exact JSON pointers in events_results.json from its
own side. That works, and it is guarded there, but it puts knowledge of THIS
repo's field names in somebody else's codebase.

This writes `state.json` beside the results it describes.

WHY THE EMISSION SITS AT THE REPO ROOT
---------------------------------------
This repo gitignores `data/` in its entirety — it holds regenerable price
history — so an emission written there would never be committed and the
consumer would read nothing. It goes to the root, next to events_results.json,
which is where this repo already publishes its committed results.

THE ANCHOR IS DERIVED, NOT WRITTEN DOWN
----------------------------------------
The consumer currently hard-codes the 2026 instance's anchor as 30 June 2026 and
reports the state as LIVE unconditionally. Both are true today and neither will
be true forever: the anchor moves with each new episode, and the instance stops
being live once its 9-month forward return resolves.

Rather than copy a date that expires, this reads both from the data:

  * anchor      = the LAST episode's date.
  * LIVE        = that episode's 9-month forward return is still unresolved.
                  Once it resolves, the instance is complete and reads NOT_LIVE.
  * window ends = anchor plus 9 months, via dateutil.relativedelta rather than a
                  hand-rolled day count, so month-end anchors land correctly
                  (30 June 2026 -> 30 March 2027).

Today this agrees with the consumer exactly. When it stops agreeing — which is
what will happen when the window resolves or a new episode triggers — the
consumer's shadow comparison reports the difference, and that report IS the
alarm on its hard-coded date. That is the reason for deriving rather than
duplicating: a second copy of the constant would have gone stale silently
alongside the first.

WHAT IS NOT EMITTED
-------------------
The global-ETF breadth lead is a RECORDED GAP in the consumer's contract: its
records live under the gitignored `private/` store and there is no standing
published state. It is deliberately not computed or emitted here — the consumer
renders it as a gap, which is an honest answer, where a freshly computed value
would be a new number wearing the authority of a published one.

Nothing under `private/` is read by this script. That store is paid, licensed
third-party IP and this repo is public.

WHAT IT IS NOT
--------------
  * NOT a new study and not a recomputation. Values are copied or derived from
    a file this repo already publishes. If this and events_results.json ever
    disagree, events_results.json is right and this is broken.
  * NOT load-bearing here. Nothing in this repo reads state.json, which is why
    it runs in its own workflow.

NOTE ON COVERAGE. This repo has no CI test run, so tests/test_emit_state.py is a
local guard rather than a gate. The enforcing check is the consumer's validator
plus its shadow comparison against its own independent extraction.

Usage:
    python scripts/emit_state.py           # write state.json
    python scripts/emit_state.py --check   # validate and print, write nothing
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from dateutil.relativedelta import relativedelta

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parent.parent
SOURCE_JSON = REPO / "events_results.json"
OUT = REPO / "state.json"

CONTRACT_VERSION = "1"
SOURCE = "event-studies"
SIGNAL = "event_strong_q2"

# Both constants of the study itself, and both stated in its id. The horizon is
# part of the event's identity; the ANCHOR is not, and is read from the data.
EVENT_ID = "spx-strong-q2-9m-forward"
HORIZON_MONTHS = 9


class EmitError(Exception):
    """A required input was missing or malformed. Never emit a guess."""


def require(obj, path: str, kind=None):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise EmitError(f"missing key `{part}` at pointer `{path}`")
        cur = cur[part]
    if cur is None:
        raise EmitError(f"pointer `{path}` is null")
    if kind is not None and not isinstance(cur, kind):
        # `kind` is often a tuple of accepted types, which has no __name__.
        want = kind.__name__ if isinstance(kind, type) else "/".join(k.__name__ for k in kind)
        raise EmitError(f"pointer `{path}` is {type(cur).__name__}, expected {want}")
    return cur


def load_results():
    if not SOURCE_JSON.exists():
        raise EmitError(f"source file not found: {SOURCE_JSON}")
    try:
        return json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmitError(f"events_results.json is not valid JSON: {exc}") from exc


def window(anchor_iso: str) -> tuple[dt.date, dt.date]:
    """(anchor, window end) for a month-end anchored forward window.

    relativedelta rather than a day count: a 9-month window from 30 June must
    land on 30 March, and 270 days would not. Python datetime months are
    1-indexed (June == 6).
    """
    try:
        anchor = dt.date.fromisoformat(anchor_iso)
    except (TypeError, ValueError) as exc:
        raise EmitError(f"episode date {anchor_iso!r} is not an ISO date") from exc
    return anchor, anchor + relativedelta(months=HORIZON_MONTHS)


def build() -> dict:
    d = load_results()
    generated = require(d, "generatedAt", str)
    events = require(d, "events", list)

    ev = next((e for e in events if isinstance(e, dict) and e.get("id") == EVENT_ID), None)
    if ev is None:
        raise EmitError(f"event `{EVENT_ID}` absent from events_results.json")

    n_trig = require(ev, "nTriggers", int)
    episodes = require(ev, "episodes", list)
    if not episodes:
        raise EmitError(f"event `{EVENT_ID}` has no episodes")

    last = episodes[-1]
    if not isinstance(last, dict):
        raise EmitError(f"episodes[-1] is {type(last).__name__}, expected an object")
    anchor, ends = window(require(last, "date", str))

    # The instance is live while its own horizon is unresolved. Asserting the
    # key exists keeps a schema change loud rather than defaulting to "live".
    fwd = require(last, "fwd", dict)
    key = str(HORIZON_MONTHS)
    if key not in fwd:
        raise EmitError(
            f"episodes[-1].fwd has no `{key}` horizon — the forward keys are "
            f"{sorted(fwd)}, so the live test cannot be applied"
        )
    state = "LIVE" if fwd[key] is None else "NOT_LIVE"

    return {
        "contract_version": CONTRACT_VERSION,
        "emitted_by": SOURCE,
        "emitted_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "signals": {
            SIGNAL: {
                "as_of": generated[:10],
                "state": state,
                "value": n_trig,
                "zone": f"window {anchor.isoformat()} → {ends.isoformat()}",
                "role": "view-only",
                "horizon": f"{HORIZON_MONTHS}m",
                "evidence_grade": "informational",
                "licence": "public",
                "action_hint": "none",
                "source_file": "events_results.json",
                "computed_at": generated,
                "cadence": "daily",
            }
        },
    }


def unchanged(payload: dict) -> bool:
    """Same emission as the one on disk, apart from the run's own timestamp?

    This matters more here than elsewhere. `generatedAt` moves on EVERY
    catalogue rebuild, so `as_of` and `computed_at` change daily even when the
    event state does not — the emission genuinely differs most days and will
    commit. What this prevents is the pure no-op: a rerun on an unchanged
    catalogue, where only this script's own timestamp would have moved.
    """
    if not OUT.exists():
        return False
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    strip = lambda d: {k: v for k, v in d.items() if k != "emitted_at"}
    return strip(prev) == strip(payload)


def main(argv: list[str]) -> int:
    try:
        payload = build()
    except EmitError as exc:
        print(f"emit_state: FAILED — {exc}", file=sys.stderr)
        print("emit_state: nothing written; the previous state.json is left as it was.",
              file=sys.stderr)
        return 1

    s = payload["signals"][SIGNAL]
    print(f"emit_state: strong-Q2 {s['state']} @ {s['as_of']} — "
          f"{s['value']} triggers, {s['zone']}")

    if "--check" in argv:
        print("emit_state: --check, nothing written.")
        return 0

    if unchanged(payload):
        print("emit_state: state unchanged since the last emission — leaving it as it is.")
        return 0

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        shown = OUT.relative_to(REPO)
    except ValueError:
        shown = OUT
    print(f"emit_state: wrote {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
