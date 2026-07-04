#!/usr/bin/env python
"""lead_sheet.py — turn discovery_scan cells into the ranked LEAD SHEET.

Selection (a config becomes a lead only if it SURVIVES OOS):
  - OOS: block-weighted edge > 0 AND lift over baseline > 0 AND random-entry
    p-value < 0.10;
  - IN-SAMPLE sign-consistent: IS edge > 0 AND IS lift > 0 (discovered pre-2015,
    not an OOS-only fluke);
  - among a config's qualifying horizons, keep the one with the best risk-reward
    (reward-to-MAE, tie-broken by lift).

Ranking is downside-aware, not headline-mean: FDR survivors first, then
non-thin, then by reward-to-MAE, then lift. A lead with < 20 independent OOS
episodes is flagged THIN and shown in a separate section — never headlined. Every
conditional number is shown beside its unconditional baseline.

Outputs (all under private/leads/, gitignored):
  lead_sheet_<asof>.md    — the human deliverable
  lead_sheet_<asof>.json  — full machine record (proof, universe, baseline, cells)
  cells_tested_<asof>.csv — EVERY cell tested (the declared testing budget)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)

ROOT = Path(__file__).resolve().parents[1]
LEADS_DIR = ROOT / "private" / "leads"

HORIZONS = [5, 10, 21, 42, 63, 126, 252]
THIN_EPISODES = 20
FDR_Q = 0.10


def _pct(x, dp=2):
    if x is None or (isinstance(x, float) and (x != x)):
        return "n/a"
    return f"{100 * x:+.{dp}f}%"


def _cap(x, hi=99.0):
    if x is None or (isinstance(x, float) and (x != x)):
        return float("nan")
    return min(x, hi)


def select_leads(cells):
    """A config becomes a lead only if its DRIFT-ADJUSTED alpha (signal, not beta)
    is positive OOS, sign-consistent in-sample, and significant. The pooled lift is
    reported for context but does NOT gate — at long horizons it can be pure beta."""
    by = {(c["config"], c["horizon"], c["window"]): c for c in cells}
    configs = sorted({c["config"] for c in cells})
    leads = []
    for cfg in configs:
        best, best_key = None, None
        for h in HORIZONS:
            oos = by.get((cfg, h, "OOS"))
            isc = by.get((cfg, h, "IS"))
            if not oos or not isc:
                continue
            a_oos = oos.get("alpha_driftadj", float("nan"))
            a_is = isc.get("alpha_driftadj", float("nan"))
            if not (a_oos > 0 and oos["p_value"] < 0.10):        # positive SIGNAL, significant
                continue
            if not (a_is > 0):                                    # sign-consistent discovery
                continue
            key = (a_oos, _cap(oos["reward_to_mae"]))
            if best is None or key > best_key:
                allc = by.get((cfg, h, "ALL"))
                best = {"config": cfg, "family": oos["family"], "horizon": h,
                        "horizon_label": oos["horizon_label"], "mechanism": oos["mechanism"],
                        "oos": oos, "is": isc, "all": allc}
                best_key = key
        if best:
            best["thin"] = best["oos"]["n_independent_episodes"] < THIN_EPISODES
            best["fdr_reject"] = bool(best["oos"].get("fdr_reject", False))
            best["q_value"] = best["oos"].get("q_value", float("nan"))
            leads.append(best)

    leads.sort(key=lambda L: (
        not L["fdr_reject"], L["thin"],
        -L["oos"].get("alpha_driftadj", 0.0), -_cap(L["oos"]["reward_to_mae"])))
    return leads


def _budget(cells):
    oos = [c for c in cells if c["window"] == "OOS"]
    n_oos = len(oos)
    survivors = [c for c in oos if c.get("fdr_reject")]
    return {
        "cells_total": len(cells),
        "cells_oos": n_oos,
        "expected_false_positives_at_p05": round(0.05 * n_oos, 1),
        "fdr_survivors_q10": len(survivors),
    }


def write_lead_sheet(out):
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    asof = out["proof"]["expected_last_session"]
    cells = out["cells"]
    leads = select_leads(cells)
    budget = _budget(cells)

    # ---- JSON (full machine record) ----
    json_path = LEADS_DIR / f"lead_sheet_{asof}.json"
    json_path.write_text(json.dumps({
        "asof_last_nyse_session": asof,
        "generated_from": "scripts/discovery_scan.py",
        "proof_artefacts": out["proof"],
        "universe": out["universe"],
        "baseline": out["baseline"],
        "budget": budget,
        "n_leads": len(leads),
        "leads": leads,
        "cells": cells,
        "run": {k: out.get(k) for k in ("loaded", "skipped", "seconds", "n_configs",
                                        "n_single_stock_configs", "n_breadth_configs")},
    }, indent=1, default=_json_default), encoding="utf-8")

    # ---- cells CSV (the full testing budget) ----
    csv_path = LEADS_DIR / f"cells_tested_{asof}.csv"
    fields = ["config", "family", "horizon", "horizon_label", "window", "n_trades",
              "n_independent_episodes", "n_names", "frac_names_positive",
              "alpha_driftadj", "cond_median", "base_median", "lift_median", "hit_rate", "base_hit",
              "median_mae", "reward_to_mae", "sortino", "p05", "p95",
              "ci_lo", "ci_hi", "p_value", "null_percentile", "q_value", "fdr_reject"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for c in sorted(cells, key=lambda x: (x["config"], x["window"], x["horizon"])):
            w.writerow({k: c.get(k, "") for k in fields})

    # ---- Markdown (the deliverable) ----
    md_path = LEADS_DIR / f"lead_sheet_{asof}.md"
    md_path.write_text(_render_md(out, leads, budget, asof), encoding="utf-8")
    return [md_path, json_path, csv_path]


def _lead_row(L):
    o, i = L["oos"], L["is"]
    thin = " ⚠️THIN" if L["thin"] else ""
    fdr = "✓" if L["fdr_reject"] else "·"
    rr = _cap(o["reward_to_mae"])
    return (f"| {L['config']} | {L['family']} | {L['horizon_label']} | "
            f"**{_pct(o.get('alpha_driftadj'))}** | {_pct(o['cond_median'])} | {_pct(o['lift_median'])} | "
            f"{o['hit_rate']*100:.0f}% | {rr:.2f} | {o['sortino']:.2f} | "
            f"{o['n_independent_episodes']}{thin} | {o['n_names']} | "
            f"{o['p_value']:.3f} | {fdr} | {_pct(i.get('alpha_driftadj'))} |")


def _render_md(out, leads, budget, asof):
    p = out["proof"]; u = out["universe"]
    headline = [L for L in leads if not L["thin"]]
    thinleads = [L for L in leads if L["thin"]]

    L = []
    L.append(f"# Discovery lead sheet — Norgate US universe — as of {asof}")
    L.append("")
    L.append("_Stage 1 of the event-studies funnel. A ranked list of extreme/event "
             "setups with measured forward-return edge and risk-reward — NOT a finished "
             "strategy. Each lead is a candidate for your sign-off; promotion into the "
             "pre-registered catalogue + Monte Carlo is Stage 2 "
             "(`scripts/promote_lead.py`). Nothing here auto-promotes; the public "
             "dashboard is untouched._")
    L.append("")
    L.append("## Proof the feed is survivorship-free and point-in-time")
    L.append("")
    L.append(f"- **As-of (last NYSE session):** {asof}; benchmark last dates "
             f"{p['benchmark_last_dates']}.")
    L.append(f"- **Delisted database:** {p['delisted_symbol_count']:,} symbols "
             f"({p['delisted_suffixed_count']:,} carry a delisting suffix, e.g. "
             f"{', '.join(p['delisted_examples'][:3])}). A reversion edge measured only "
             "on survivors is a trap; delisted members are in the pool.")
    L.append(f"- **Point-in-time membership (spot-check):** {p['membership_probe']['symbol']} "
             f"was a {p['membership_probe']['index']} member on "
             f"{p['membership_probe']['member_days']:,} days over "
             f"{p['membership_probe']['window']} — the universe at trigger date t is what "
             "was investable at t.")
    L.append(f"- **Universe:** {u['counts']['total']:,} names "
             f"({u['counts']['live']:,} live, {u['counts']['delisted_suffixed']:,} delisted) "
             f"across {', '.join(u['index_names'])}. Method: {u['method']}.")
    L.append(f"- **NDU last update (US Equities):** {p['ndu_last_update_us_equities']}; "
             f"norgatedata v{p['norgatedata_version']}.")
    L.append("")
    n_ss = out.get("n_single_stock_configs", out["n_configs"])
    n_br = out.get("n_breadth_configs", 0)
    nominal = out["n_configs"] * len(HORIZONS) * 3
    L.append("## Multiple-testing budget (the whole search space, declared up front)")
    L.append("")
    L.append(f"- **Declared search space:** {out['n_configs']} fixed archetype-configs "
             f"({n_ss} single-stock + {n_br} breadth) × {len(HORIZONS)} horizons × 3 windows "
             f"(IS / OOS / ALL) = {nominal:,} nominal cells. The grammar is fixed and discrete "
             "— no free search, no continuous optimisation, no archetype added mid-scan.")
    L.append(f"- **{budget['cells_total']:,} cells had ≥{ '6' } independent episodes to "
             f"evaluate**, of which **{budget['cells_oos']:,} are in the OOS window**. At "
             f"p<0.05, ~**{budget['expected_false_positives_at_p05']} OOS false positives are "
             "expected by chance alone** — which is why a lead must clear OOS significance AND "
             "Benjamini-Hochberg FDR, not a raw p.")
    L.append(f"- **{budget['fdr_survivors_q10']} OOS cell(s) survive BH-FDR at q≤{FDR_Q:.2f}.**")
    L.append("")
    L.append("## How to read the numbers")
    L.append("")
    L.append("- **Drift-adj α (OOS)** is the headline and the GATE: each entry's forward "
             "return minus that name's OWN mean forward return, episode-weighted (mean CAR). "
             "It strips market/size/sector beta and the fact that some archetypes select "
             "high-drift names, so it measures the SIGNAL, not buy-and-hold. A config is a "
             "lead ONLY if this is positive OOS, sign-consistent in-sample, and significant. "
             "**Raw edge** and **Lift vs base** are the block-weighted conditional median and "
             "its excess over the pooled baseline — shown for context, but at long horizons "
             "they are largely beta, so do not read them as signal.")
    L.append("- **Reward/MAE, Sortino, hit-rate** are *entry-weighted* per-trade, net of "
             "liquidity-tiered cost. **p** is vs a per-name random-entry null; **FDR ✓** = "
             "survives Benjamini-Hochberg q≤0.10. **Episodes** = independent OOS market "
             "episodes (<20 ⇒ ⚠️THIN, never a headline). **IS α** is the pre-2015 "
             "drift-adjusted alpha, shown for sign-consistency.")
    L.append("")

    hdr = ("| Config | Family | Horizon | Drift-adj α (OOS) | Raw edge | Lift vs base | Hit | "
           "Reward/MAE | Sortino | Episodes | Names | p | FDR | IS α |")
    sep = "|" + "---|" * 14

    L.append(f"## Headline leads ({len(headline)}) — survived OOS, ≥20 independent episodes")
    L.append("")
    if headline:
        L.append(hdr); L.append(sep)
        for ld in headline:
            L.append(_lead_row(ld))
    else:
        L.append("_None. No archetype-config cleared OOS edge + significance with ≥20 "
                 "independent episodes at this run. That is a legitimate result, not a "
                 "bug: the guards are doing their job._")
    L.append("")

    if thinleads:
        L.append(f"## Thin / underpowered leads ({len(thinleads)}) — survived OOS but <20 episodes")
        L.append("")
        L.append("_Directionally interesting, statistically thin. Accrue more episodes "
                 "before trusting. Not for sizing._")
        L.append("")
        L.append(hdr); L.append(sep)
        for ld in thinleads:
            L.append(_lead_row(ld))
        L.append("")

    if headline or thinleads:
        L.append("## Mechanism hypotheses (edit before promotion)")
        L.append("")
        for ld in (headline + thinleads):
            L.append(f"- **{ld['config']}** ({ld['horizon_label']}): {ld['mechanism']}")
        L.append("")

    L.append("## Assumptions made in this scan (correct me)")
    L.append("")
    for a in out.get("assumptions", DEFAULT_ASSUMPTIONS):
        L.append(f"- {a}")
    L.append("")
    L.append("## Next step")
    L.append("")
    L.append("Tick the leads you want to take forward. For each, run "
             "`python scripts/promote_lead.py --asof " + asof + " --lead <config>` to "
             "generate a catalogue card (existing schema) with a rationale stub for you "
             "to edit. Nothing is admitted to `catalogue/catalogue.json` without your "
             "sign-off.")
    L.append("")
    return "\n".join(L)


DEFAULT_ASSUMPTIONS = [
    "Leads are GATED and ranked on drift-adjusted alpha (each entry's forward return "
    "minus that name's own mean forward return, episode-weighted mean CAR), NOT the raw "
    "edge or the lift over the pooled baseline. At long horizons the raw edge is largely "
    "market/size/sector beta, and archetypes that select high-drift names show a fake lift "
    "against a pooled baseline; the drift adjustment measures the actual signal. The drift "
    "benchmark is each name's full-sample mean — an attribution benchmark, not a tradeable "
    "estimate.",
    "Universe scoped to point-in-time members of the S&P 500 / MidCap 400 / SmallCap "
    "600 (the investable S&P Composite 1500), delisted members included. A whole-market "
    "OTC/micro-cap scan is deliberately excluded as un-investable and lacking clean "
    "point-in-time membership. Broadening is a one-line config change in norgate_universe.py.",
    "Prices are TOTALRETURN-adjusted; the Close is used for every indicator and for "
    "forward returns. Total-return adjustment removes mechanical ex-dividend gap-downs "
    "(a feature: they are not mis-flagged as event gaps).",
    "Forward returns are delisting-aware: a position is carried to the last available "
    "bar, so delisting losses are realised; the same clamp is applied to the baseline.",
    "Costs: liquidity-tiered round-trip charged once to each held forward return "
    "(large 10bps / mid 20bps / small 40bps); a name pays its cheapest tier. The grammar "
    "is long-natured, so short-borrow is noted, not charged.",
    "OOS split at 2015-01-01. Significance null preserves episode sizes and per-name "
    "overlap but draws within-episode entries independently, so it does not fully "
    "reproduce same-day cross-sectional correlation — the p-value is a mild lower bound "
    "on conservativeness; the episode-level statistic, block-bootstrap CI, OOS "
    "requirement and FDR are the primary guards.",
]


if __name__ == "__main__":
    import sys
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if src and src.exists():
        data = json.loads(src.read_text(encoding="utf-8"))
        # allow re-rendering from a saved JSON record
        data.setdefault("proof", data.get("proof_artefacts"))
        data.setdefault("n_configs", data.get("run", {}).get("n_configs", 0))
        for k in ("loaded", "skipped", "seconds"):
            data.setdefault(k, data.get("run", {}).get(k))
        print(write_lead_sheet(data))
    else:
        print("usage: python lead_sheet.py <lead_sheet_*.json>")
