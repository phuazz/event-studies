#!/usr/bin/env python
"""promote_lead.py — Stage 2 of the funnel: turn a ticked discovery lead into a
pre-registration draft for the EXISTING catalogue, WITHOUT admitting anything.

It writes two files under private/leads/promoted/ (gitignored):
  <config>__candidate.json      — a candidate wrapper in the private SCHEMA.md
                                  style (OUR discovery numbers, engineStatus,
                                  discoveryGap, rationaleDraft PLACEHOLDER,
                                  signOff.approved=false);
  <config>__catalogue_card.json — a card in the existing catalogue schema
                                  (id/kind/target/params/clusterDays/rationale/
                                  definition), ready to paste after you write the
                                  rationale and sign off.

Human-in-the-loop is absolute: this NEVER edits catalogue/catalogue.json, never
touches docs/ or the dashboard, and never sets signOff.approved. The confirmation
engine (engine/events.js) is single-target on Yahoo data; a cross-sectional
stock-level archetype therefore maps to `requires-new-detector` unless an existing
single-target detector already implements the same rule — stated honestly per lead.

Usage:
  python scripts/promote_lead.py --asof 2026-07-02 --lead mo_escape252low_5d15
  python scripts/promote_lead.py --asof 2026-07-02 --lead br_zweig_thrust --target SPY
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEADS_DIR = ROOT / "private" / "leads"
PROMOTED_DIR = LEADS_DIR / "promoted"

# Mapping from a discovery archetype-config to a catalogue card. `kind` is an
# existing engine kind only where a single-target detector already implements the
# same rule; otherwise a descriptive kind + engineStatus 'requires-new-detector'.
NEW = "requires-new-detector (cross-sectional stock-level; engine/events.js is single-target on Yahoo ETF data)"
EXIST = "existing-detector (single-target in engine/events.js)"

PROMOTE = {
    # --- mean reversion (all new single-target detectors) ---
    "mr_rsi14_below20": ("mean_reversion_rsi_oversold", NEW, {"rsiPeriod": 14, "oversoldLevel": 20},
        "Trigger when RSI(14) crosses below 20. Forward returns from the trigger close."),
    "mr_rsi14_below30": ("mean_reversion_rsi_oversold", NEW, {"rsiPeriod": 14, "oversoldLevel": 30},
        "Trigger when RSI(14) crosses below 30. Forward returns from the trigger close."),
    "mr_decline5_10pct": ("mean_reversion_ndecline", NEW, {"declineDays": 5, "declinePct": 10},
        "Trigger on the first session the close is <=10% below its close 5 sessions earlier."),
    "mr_decline5_15pct": ("mean_reversion_ndecline", NEW, {"declineDays": 5, "declinePct": 15},
        "Trigger on the first session the close is <=15% below its close 5 sessions earlier."),
    "mr_decline10_15pct": ("mean_reversion_ndecline", NEW, {"declineDays": 10, "declinePct": 15},
        "Trigger on the first session the close is <=15% below its close 10 sessions earlier."),
    "mr_decline10_20pct": ("mean_reversion_ndecline", NEW, {"declineDays": 10, "declinePct": 20},
        "Trigger on the first session the close is <=20% below its close 10 sessions earlier."),
    "mr_ddown252_20": ("mean_reversion_drawdown", NEW, {"drawdownPct": 20, "highLookback": 252},
        "Trigger on the first session the drawdown from the trailing 252d high reaches -20%."),
    "mr_ddown252_30": ("mean_reversion_drawdown", NEW, {"drawdownPct": 30, "highLookback": 252},
        "Trigger on the first session the drawdown from the trailing 252d high reaches -30%."),
    "mr_ddown252_40": ("mean_reversion_drawdown", NEW, {"drawdownPct": 40, "highLookback": 252},
        "Trigger on the first session the drawdown from the trailing 252d high reaches -40%."),
    "mr_below200_10": ("mean_reversion_below_sma", NEW, {"smaPeriod": 200, "distancePct": 10},
        "Trigger on the first session the close is >=10% below its 200d SMA."),
    "mr_below200_20": ("mean_reversion_below_sma", NEW, {"smaPeriod": 200, "distancePct": 20},
        "Trigger on the first session the close is >=20% below its 200d SMA."),
    "mr_gapdown5": ("mean_reversion_gap_down", NEW, {"gapPct": 5},
        "Trigger when the open is <=5% below the prior close."),
    "mr_gapdown10": ("mean_reversion_gap_down", NEW, {"gapPct": 10},
        "Trigger when the open is <=10% below the prior close."),
    # --- momentum (escape-from-low matches the existing coffee detector) ---
    "mo_escape252low_5d15": ("momentum_thrust_from_252d_low", EXIST,
        {"rocWindow": 5, "thrustPct": 15, "lowLookback": 252, "lowWithin": 21},
        "Trigger when 5d ROC first exceeds +15% while a 252d low printed within the trailing 21 sessions."),
    "mo_escape252low_10d25": ("momentum_thrust_from_252d_low", EXIST,
        {"rocWindow": 10, "thrustPct": 25, "lowLookback": 252, "lowWithin": 21},
        "Trigger when 10d ROC first exceeds +25% while a 252d low printed within the trailing 21 sessions."),
    "mo_roc5_3sig": ("momentum_roc_sigma", NEW, {"rocWindow": 5, "sigma": 3},
        "Trigger when the 5d ROC first reaches >=3x its trailing 252d standard deviation."),
    "mo_roc21_2sig": ("momentum_roc_sigma", NEW, {"rocWindow": 21, "sigma": 2},
        "Trigger when the 21d ROC first reaches >=2x its trailing 252d standard deviation."),
    "mo_roc21_3sig": ("momentum_roc_sigma", NEW, {"rocWindow": 21, "sigma": 3},
        "Trigger when the 21d ROC first reaches >=3x its trailing 252d standard deviation."),
    "mo_breakaway_gap5": ("momentum_breakaway_gap", NEW, {"gapPct": 5, "unfilledDays": 10},
        "Trigger on a >=5% up-gap whose floor (prior close) is not revisited within 10 sessions."),
    "mo_breakaway_gap10": ("momentum_breakaway_gap", NEW, {"gapPct": 10, "unfilledDays": 10},
        "Trigger on a >=10% up-gap whose floor (prior close) is not revisited within 10 sessions."),
    # --- volatility / dislocation ---
    "vol_nsig_down3": ("dislocation_nsigma", NEW, {"direction": "down", "sigma": 3, "window": 63},
        "Trigger when a single-day return <= -3x its trailing 63d standard deviation."),
    "vol_nsig_down4": ("dislocation_nsigma", NEW, {"direction": "down", "sigma": 4, "window": 63},
        "Trigger when a single-day return <= -4x its trailing 63d standard deviation."),
    "vol_nsig_up3": ("dislocation_nsigma", NEW, {"direction": "up", "sigma": 3, "window": 63},
        "Trigger when a single-day return >= +3x its trailing 63d standard deviation."),
    "vol_nsig_up4": ("dislocation_nsigma", NEW, {"direction": "up", "sigma": 4, "window": 63},
        "Trigger when a single-day return >= +4x its trailing 63d standard deviation."),
    "vol_range_exp2": ("dislocation_range_expansion", NEW, {"mult": 2, "atrPeriod": 20},
        "Trigger on the first session the true range >= 2x its 20d ATR."),
    "vol_range_exp3": ("dislocation_range_expansion", NEW, {"mult": 3, "atrPeriod": 20},
        "Trigger on the first session the true range >= 3x its 20d ATR."),
    "vol_downstreak5": ("dislocation_streak", NEW, {"direction": "down", "length": 5},
        "Trigger when the close prints a 5th consecutive down session."),
    "vol_downstreak7": ("dislocation_streak", NEW, {"direction": "down", "length": 7},
        "Trigger when the close prints a 7th consecutive down session."),
    "vol_upstreak5": ("dislocation_streak", NEW, {"direction": "up", "length": 5},
        "Trigger when the close prints a 5th consecutive up session."),
    "vol_upstreak7": ("dislocation_streak", NEW, {"direction": "up", "length": 7},
        "Trigger when the close prints a 7th consecutive up session."),
    # --- breadth (index-level; target SPY) ---
    "br_pct200_up15": ("breadth_cross_up", NEW, {"level": 15, "breadthUniverse": "sp500_pit"},
        "Trigger when the % of S&P 500 members above their own 200d SMA crosses UP through 15%."),
    "br_pct200_up20": ("breadth_cross_up", NEW, {"level": 20, "breadthUniverse": "sp500_pit"},
        "Trigger when the % of S&P 500 members above their own 200d SMA crosses UP through 20%."),
    "br_zweig_thrust": ("breadth_zweig_thrust", NEW, {"breadthUniverse": "sp500_pit"},
        "Zweig thrust: 10d EMA of adv/(adv+dec) rises from <0.40 to >0.615 within 10 sessions."),
    "br_nhnl_high10": ("breadth_net_new_highs", NEW, {"level": 10, "breadthUniverse": "sp500_pit"},
        "Trigger when net (new highs - new lows)/members crosses above +10%."),
    "br_nhnl_low20": ("breadth_net_new_lows", NEW, {"level": -20, "breadthUniverse": "sp500_pit"},
        "Trigger when net (new highs - new lows)/members crosses below -20% (washout)."),
    "br_upvol_cluster": ("breadth_upvolume_cluster", NEW, {"breadthUniverse": "sp500_pit"},
        "Trigger when >=2 of the trailing 5 sessions are 90%-up-volume days across members."),
}


def _find_lead(record, cfg):
    for L in record.get("leads", []):
        if L["config"] == cfg:
            return L
    return None


def _cells_for(record, cfg):
    return [c for c in record.get("cells", []) if c["config"] == cfg]


def _our_numbers(cells):
    """OUR computed discovery numbers, per horizon x window — never anyone else's."""
    out = {}
    for c in cells:
        out.setdefault(c["horizon_label"], {})[c["window"]] = {
            "edge_median": c["cond_median"], "baseline_median": c["base_median"],
            "lift_median": c["lift_median"], "hit_rate": c["hit_rate"],
            "reward_to_mae": c["reward_to_mae"], "sortino": c["sortino"],
            "n_independent_episodes": c["n_independent_episodes"], "n_trades": c["n_trades"],
            "n_names": c["n_names"], "p_value": c["p_value"],
            "q_value": c.get("q_value"), "fdr_reject": c.get("fdr_reject"),
        }
    return out


def promote(asof, cfg, target_override=None):
    src = LEADS_DIR / f"lead_sheet_{asof}.json"
    if not src.exists():
        raise SystemExit(f"lead sheet not found: {src} (run discovery_scan first)")
    record = json.loads(src.read_text(encoding="utf-8"))
    if cfg not in PROMOTE:
        raise SystemExit(f"unknown config {cfg!r}. Known: {', '.join(sorted(PROMOTE))}")
    kind, engine_status, params, definition = PROMOTE[cfg]
    lead = _find_lead(record, cfg)
    cells = _cells_for(record, cfg)
    if not cells:
        raise SystemExit(f"{cfg} was not tested in {src.name} — nothing to promote")

    is_breadth = kind.startswith("breadth")
    target = target_override or ("SPY" if is_breadth else "<PM: choose a target instrument, or run cross-sectional confirmation>")
    best_h = lead["horizon_label"] if lead else None

    card_id = f"{cfg.replace('_', '-')}-discovery"
    catalogue_card = {
        "id": card_id,
        "kind": kind,
        "target": target,
        **params,
        "clusterDays": 21,
        "rationale": ("PLACEHOLDER — write the economic mechanism before admission. "
                      f"Discovery mechanism hypothesis (edit): {lead['mechanism'] if lead else PROMOTE[cfg][3]} "
                      "Judged on OUR discovery numbers + the catalogue Monte Carlo, not on any external claim."),
        "definition": definition + " (Discovery measured this cross-sectionally on the "
                      "Norgate point-in-time S&P Composite 1500; confirmation target/vehicle is the PM's choice.)",
    }

    candidate = {
        "id": card_id,
        "status": "discovery-lead-unverified",
        "sourceLeadId": f"lead_sheet_{asof}:{cfg}",
        "discoveredAtISO": dt.date.today().isoformat(),
        "proposedKind": kind,
        "engineStatus": engine_status,
        "target": target,
        "definitionMechanical": definition,
        "discoveryGap": (
            "Discovery is a CROSS-SECTIONAL, survivorship-free, point-in-time scan over the "
            "S&P Composite 1500 (delisted members included). Confirmation via engine/events.js "
            "is SINGLE-TARGET on ~10y Yahoo ETF data. The two are not the same test: a "
            "single-instrument confirmation is underpowered relative to the pooled cross-section, "
            "and cannot see delisted names. Treat the discovery numbers as the powered estimate "
            "and the catalogue card as a pre-registration for ongoing, out-of-sample accrual."),
        "ourDiscoveryNumbers": {
            "headlineHorizon": best_h,
            "isThin": lead["thin"] if lead else None,
            "fdrSurvivor": lead["fdr_reject"] if lead else None,
            "byHorizonWindow": _our_numbers(cells),
            "note": "OUR computed numbers only. Net of liquidity-tiered round-trip cost. "
                    "Edge is block-weighted (one obs per independent market episode).",
        },
        "rationaleDraft": "PLACEHOLDER — Zhenghao to write the economic mechanism.",
        "catalogueCardFile": f"{cfg}__catalogue_card.json",
        "signOff": {"approved": False, "by": None, "dateISO": None},
    }

    PROMOTED_DIR.mkdir(parents=True, exist_ok=True)
    card_path = PROMOTED_DIR / f"{cfg}__catalogue_card.json"
    cand_path = PROMOTED_DIR / f"{cfg}__candidate.json"
    card_path.write_text(json.dumps(catalogue_card, indent=2), encoding="utf-8")
    cand_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
    return card_path, cand_path, kind, engine_status, target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", required=True, help="lead-sheet date, e.g. 2026-07-02")
    ap.add_argument("--lead", required=True, help="config id from the lead sheet")
    ap.add_argument("--target", default=None, help="override the confirmation target ticker")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    card_path, cand_path, kind, engine_status, target = promote(args.asof, args.lead, args.target)
    print(f"Promoted {args.lead} -> DRAFT (nothing admitted, catalogue.json untouched)")
    print(f"  kind         : {kind}")
    print(f"  engineStatus : {engine_status}")
    print(f"  target       : {target}")
    print(f"  card         : {card_path.relative_to(ROOT)}")
    print(f"  candidate    : {cand_path.relative_to(ROOT)}")
    print("\nNext: write the rationale, verify the target ticker against two sources, "
          "then paste the card into catalogue/catalogue.json and set signOff.approved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
