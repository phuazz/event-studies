#!/usr/bin/env python
"""validate_leads.py — Stage 1.5: a DEPLOYABILITY stress-test on the discovery
leads, before they inform any sign-off.

The discovery scan already answered "is the edge real versus random entry?"
(OOS split, Benjamini-Hochberg FDR, block-bootstrap episode-level significance).
This adds the questions that decide DEPLOYABILITY, which significance does not:

  1. Sub-period stability — is the edge an all-eras effect, or carried by one
     window (e.g. 2020)? Block-weighted edge in disjoint calendar windows.
  2. Cross-sectional concentration — is the edge broad across size tiers and GICS
     sectors, or does it live in one slice? (Vault rule: narrow a marginal edge to
     where the mechanism is strongest before trusting OR discarding it.)
  3. Cost headroom — break-even round-trip cost, and net edge at 2x / 5x the base
     tiered cost.
  4. Stricter multiple-testing haircut — the within-config best-horizon selection
     penalty (x7) and a Bonferroni cross-check over the OOS cells, beside BH-q.

Verdict per lead: SIGN-OFF / WATCH / GRAVEYARD, with the binding reason. Output is
a short note + JSON under private/leads/ (gitignored). Nothing is promoted.

Run (needs the cached scan + NDU up):
    python scripts/validate_leads.py --asof 2026-07-02
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu          # noqa: E402
import discovery_scan as ds            # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LEADS_DIR = ROOT / "private" / "leads"
SECTOR_CACHE = ROOT / "data" / "cache" / "norgate" / "sectors.json"

HLABEL_TO_H = dict(zip(ds.HORIZON_LABELS, ds.HORIZONS))
CLUSTER = ds.CLUSTER_DAYS

# Disjoint calendar windows for the stability read; the last three are OOS (>=2015).
WINDOWS = [("<=2003", 0, 2003), ("2004-2009", 2004, 2009), ("2010-2014", 2010, 2014),
           ("2015-2018", 2015, 2018), ("2019-2022", 2019, 2022), ("2023-2026", 2023, 2026)]
OOS_YEAR = 2015
REALISTIC_RT_BPS = 30.0     # blended realistic round-trip for the cost read


def block_edge(net_fwd: np.ndarray, date_ords: np.ndarray, stat: str = "median"):
    """Block-weighted edge (one obs per independent market episode) + episode n.

    stat='median' — robust central tendency of the raw edge (context).
    stat='mean'   — the episode-weighted MEAN, used for the drift-adjusted alpha:
                    paired with subtracting each name's MEAN drift it is a proper
                    market-model-free CAR, centred at zero under random entry (a
                    median here would be skew-biased downward at long horizons)."""
    if net_fwd.size == 0:
        return float("nan"), 0
    ep = ds.cluster_market_episodes(date_ords, CLUSTER)
    order = np.argsort(ep, kind="mergesort")
    f = net_fwd[order]; e = ep[order]
    starts = np.concatenate(([0], np.flatnonzero(np.diff(e)) + 1))
    sizes = np.diff(np.concatenate((starts, [f.size]))).astype(float)
    ep_means = np.add.reduceat(f, starts) / sizes
    agg = np.mean(ep_means) if stat == "mean" else np.median(ep_means)
    return float(agg), int(starts.size)


def get_sector(n, sym: str, cache: dict) -> str:
    if sym in cache:
        return cache[sym]
    try:
        v = n.classification_at_level(sym, "GICS", "Name", 1)
    except Exception:  # noqa: BLE001
        v = None
    cache[sym] = v or "Unknown"
    return cache[sym]


def collect(n, uni, leads_ss, sym_index):
    """One pass over the cached universe: per single-stock lead, gather entries
    (date_ord, sym_id, tier, gross_fwd@h, net_fwd@h, mae@h)."""
    symbols = uni["symbols"]; mem_map = uni["membership_index_map"]
    cfg_by_id = {c["id"]: c for c in ds.SINGLE_STOCK_CONFIGS}
    coll = {L["config"]: {"date": [], "sym": [], "tier": [], "gross": [], "net": [],
                          "abn_gross": [], "abn": [], "mae": []} for L in leads_ss}
    lead_h = {L["config"]: HLABEL_TO_H[L["horizon_label"]] for L in leads_ss}
    need_h = set(lead_h.values())
    for k, s in enumerate(symbols, 1):
        try:
            df = nu.load_prices(s, n=n)
        except Exception:  # noqa: BLE001
            continue
        if len(df) < 260:
            continue
        close = df["Close"].to_numpy(dtype=float)
        prices = {"open": df["Open"].to_numpy(dtype=float), "high": df["High"].to_numpy(dtype=float),
                  "low": df["Low"].to_numpy(dtype=float), "close": close,
                  "vol": df["Volume"].to_numpy(dtype=float), "dates": list(df.index.date)}
        member_any = np.zeros(len(close), dtype=bool)
        for idx_name in mem_map.get(s, []):
            try:
                ms = nu.load_membership(s, idx_name, n=n)
            except Exception:  # noqa: BLE001
                continue
            if ms.size:
                member_any |= (ms.reindex(df.index).fillna(0).to_numpy(dtype=float) > 0.5)
        if not member_any.any():
            continue
        tier = ds.cost_tier(mem_map.get(s, []))
        cost = ds.COST_BPS[tier] / 1e4
        sid = sym_index[s]; nbar = len(close); dates = prices["dates"]
        # each name's OWN unconditional mean h-forward return = its drift benchmark,
        # so abnormal = actual - drift strips beta and lets us judge the SIGNAL, not
        # market/size/sector drift (consistent with the scan's per-name null).
        bf = ds.build_base_fwd(close)
        drift = {h: (float(bf[h].mean()) if bf[h].size else 0.0) for h in need_h}
        for L in leads_ss:
            cid = L["config"]; h = lead_h[cid]
            trig = cfg_by_id[cid]["detect"](prices) & member_any
            idxs = np.flatnonzero(trig)
            if idxs.size == 0:
                continue
            dh = drift[h]
            anchor = -10**9
            for i in idxs:
                if i - anchor <= CLUSTER:
                    continue
                anchor = i
                j = min(i + h, nbar - 1)
                if j <= i:
                    continue
                seg = close[i:j + 1] / close[i] - 1.0
                g = float(close[j] / close[i] - 1.0)
                C = coll[cid]
                C["date"].append(dates[i].toordinal()); C["sym"].append(sid); C["tier"].append(tier)
                C["gross"].append(g); C["net"].append(g - cost)
                C["abn_gross"].append(g - dh); C["abn"].append(g - dh - cost)
                C["mae"].append(float(seg.min()))
        if k % 500 == 0:
            print(f"  ... {k}/{len(symbols)} symbols", file=sys.stderr)
    return coll, lead_h


def analyse_lead(L, C, lead_h, cells_by, base_by_h, sectors):
    """Judge the lead on its DRIFT-ADJUSTED alpha (abn = forward return minus the
    name's own mean h-forward return), not the beta-laden absolute edge. The
    absolute edge is kept only for context."""
    cid = L["config"]; h = lead_h[cid]
    date = np.array(C["date"]); sym = np.array(C["sym"]); tier = np.array(C["tier"])
    net = np.array(C["net"]); abn = np.array(C["abn"]); abn_gross = np.array(C["abn_gross"])
    years = np.array([dt.date.fromordinal(int(d)).year for d in date]) if date.size else np.array([])
    is_oos = years >= OOS_YEAR

    alpha_edge, n_ind_all = block_edge(abn, date, "mean")               # drift-adjusted CAR
    alpha_edge_oos, n_ind_oos = block_edge(abn[is_oos], date[is_oos], "mean") if date.size else (float("nan"), 0)
    abs_net_edge, _ = block_edge(net, date)                             # median, with beta (context only)
    abs_net_edge_oos, _ = block_edge(net[is_oos], date[is_oos]) if date.size else (float("nan"), 0)
    base = base_by_h.get(str(h), base_by_h.get(h, {})).get("base_median", float("nan"))

    # --- sub-period stability of the ALPHA ---
    win = []
    for lab, y0, y1 in WINDOWS:
        m = (years >= y0) & (years <= y1)
        e, ni = block_edge(abn[m], date[m], "mean") if m.any() else (float("nan"), 0)
        win.append({"window": lab, "oos": y0 >= OOS_YEAR, "alpha": e, "n_ind": ni})
    valid_win = [w for w in win if w["n_ind"] >= 5]
    pos_win = sum(1 for w in valid_win if w["alpha"] > 0)
    oos_valid = [w for w in valid_win if w["oos"]]
    pos_oos = sum(1 for w in oos_valid if w["alpha"] > 0)
    # carried by one window? drop the window with the single best alpha, re-check sign
    carried = False
    if valid_win:
        best_w = max(valid_win, key=lambda w: (w["alpha"] if np.isfinite(w["alpha"]) else -9))
        mask_drop = np.ones(date.size, dtype=bool)
        for lab, y0, y1 in WINDOWS:
            if lab == best_w["window"]:
                mask_drop &= ~((years >= y0) & (years <= y1))
        e_drop, _ = block_edge(abn[mask_drop], date[mask_drop], "mean") if mask_drop.any() else (float("nan"), 0)
        carried = (alpha_edge > 0) and not (e_drop > 0)

    # --- size tier concentration of the ALPHA ---
    tiers = {}
    for t in ("large", "mid", "small"):
        m = tier == t
        e, ni = block_edge(abn[m], date[m], "mean") if m.any() else (float("nan"), 0)
        tiers[t] = {"alpha": e, "n_ind": ni, "n_trades": int(m.sum())}
    tier_pos = sum(1 for t in tiers.values() if t["n_ind"] >= 5 and t["alpha"] > 0)
    tier_valid = sum(1 for t in tiers.values() if t["n_ind"] >= 5)

    # --- GICS sector concentration of the ALPHA ---
    sec_labels = np.array([sectors.get(int(s), "Unknown") for s in sym]) if sym.size else np.array([])
    sec = {}
    for lab in sorted(set(sec_labels.tolist())):
        m = sec_labels == lab
        e, ni = block_edge(abn[m], date[m], "mean") if m.any() else (float("nan"), 0)
        if ni >= 5:
            sec[lab] = {"alpha": e, "n_ind": ni}
    sec_pos = sum(1 for v in sec.values() if v["alpha"] > 0)
    sec_total = len(sec)
    sec_disp = float(np.std([v["alpha"] for v in sec.values()])) if sec else float("nan")

    # --- cost headroom on the ALPHA (the tradeable excess, not the beta) ---
    break_even_bps = block_edge(abn_gross, date, "mean")[0] * 1e4
    def alpha_at(mult):
        extra = np.array([(mult - 1) * ds.COST_BPS[t] / 1e4 for t in tier])
        return block_edge(abn - extra, date, "mean")[0]
    alpha_2x = alpha_at(2.0); alpha_5x = alpha_at(5.0)

    # --- multiple-testing haircut (from the scan's OOS cell p) ---
    cell = cells_by.get((cid, h, "OOS"), {})
    p = cell.get("p_value", float("nan")); q = cell.get("q_value", float("nan"))
    fdr = bool(cell.get("fdr_reject", False))
    p_x7 = min(1.0, p * 7) if np.isfinite(p) else float("nan")          # best-of-7-horizons
    p_bonf = min(1.0, p * cells_by["_n_oos"]) if np.isfinite(p) else float("nan")

    # --- verdict, on the drift-adjusted alpha ---
    reasons = []
    if not fdr:
        verdict = "GRAVEYARD"; reasons.append("did not survive BH-FDR")
    elif not (alpha_edge_oos > 0):
        verdict = "GRAVEYARD"; reasons.append("drift-adjusted OOS alpha <= 0 (edge was beta, not signal)")
    elif np.isfinite(alpha_2x) and alpha_2x <= 0:
        verdict = "GRAVEYARD"; reasons.append("alpha negative at 2x cost")
    else:
        broad = (tier_pos >= max(2, tier_valid - 1)) and (sec_total == 0 or sec_pos / sec_total >= 0.6)
        stable = (len(valid_win) and pos_win / len(valid_win) >= 0.7) and (len(oos_valid) == 0 or pos_oos >= (len(oos_valid) + 1) // 2)
        strong_mt = np.isfinite(p_x7) and p_x7 < 0.05
        if broad and stable and strong_mt and not carried and not L.get("thin"):
            verdict = "SIGN-OFF"
            reasons.append("drift-adjusted alpha stable across eras, broad across tiers/sectors, clears x7 haircut")
        else:
            verdict = "WATCH"
            if L.get("thin"):
                reasons.append("thin (<20 episodes) — accrue more before trusting")
            if carried:
                reasons.append("alpha collapses without its best window")
            if not stable:
                reasons.append(f"alpha sign unstable across eras ({pos_win}/{len(valid_win)} windows +, OOS {pos_oos}/{len(oos_valid)})")
            if not broad:
                reasons.append(f"alpha concentrated (tiers {tier_pos}/{tier_valid}+, sectors {sec_pos}/{sec_total}+)")
            if not strong_mt:
                reasons.append("only marginal after x7 best-horizon selection haircut")

    return {
        "config": cid, "family": L["family"], "horizon": L["horizon_label"], "thin": L.get("thin"),
        "n_trades": int(net.size), "n_ind_all": n_ind_all, "n_ind_oos": n_ind_oos,
        "alpha_edge": alpha_edge, "alpha_edge_oos": alpha_edge_oos,
        "abs_net_edge": abs_net_edge, "abs_net_edge_oos": abs_net_edge_oos,
        "baseline": base, "reward_to_mae": cell.get("reward_to_mae"),
        "subperiods": win, "pos_windows": f"{pos_win}/{len(valid_win)}", "pos_oos_windows": f"{pos_oos}/{len(oos_valid)}",
        "carried_by_best_window": carried,
        "tiers": tiers, "sectors_pos": f"{sec_pos}/{sec_total}", "sector_dispersion": sec_disp,
        "tier_pos": tier_pos, "tier_valid": tier_valid,
        "top_sectors": sorted(sec.items(), key=lambda kv: -kv[1]["alpha"])[:3],
        "bottom_sectors": sorted(sec.items(), key=lambda kv: kv[1]["alpha"])[:3],
        "break_even_rt_bps": break_even_bps, "alpha_2x_cost": alpha_2x, "alpha_5x_cost": alpha_5x,
        "p_oos": p, "bh_q": q, "fdr": fdr, "p_x7_selection": p_x7, "p_bonferroni": p_bonf,
        "verdict": verdict, "reasons": reasons,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", required=True)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    rec = json.loads((LEADS_DIR / f"lead_sheet_{args.asof}.json").read_text(encoding="utf-8"))
    leads = rec["leads"]
    leads_ss = [L for L in leads if L["family"] != "breadth"]
    leads_breadth = [L for L in leads if L["family"] == "breadth"]
    base_by_h = rec["baseline"]
    cells_by = {(c["config"], c["horizon"], c["window"]): c for c in rec["cells"]}
    cells_by["_n_oos"] = sum(1 for c in rec["cells"] if c["window"] == "OOS")

    n = nu.connect(); nu.hard_check(n)
    uni = nu.resolve_universe(n)
    sym_index = {s: k for k, s in enumerate(uni["symbols"])}
    print(f"[validate] {len(leads_ss)} single-stock leads over {len(uni['symbols'])} names", file=sys.stderr)

    coll, lead_h = collect(n, uni, leads_ss, sym_index)

    # sectors for contributing names only
    contrib = sorted({sid for C in coll.values() for sid in C["sym"]})
    id_to_sym = {k: s for s, k in sym_index.items()}
    cache = json.loads(SECTOR_CACHE.read_text()) if SECTOR_CACHE.exists() else {}
    sectors = {}
    for j, sid in enumerate(contrib, 1):
        sectors[sid] = get_sector(n, id_to_sym[sid], cache)
        if j % 500 == 0:
            print(f"  ... sectors {j}/{len(contrib)}", file=sys.stderr)
    SECTOR_CACHE.write_text(json.dumps(cache), encoding="utf-8")

    out = [analyse_lead(L, coll[L["config"]], lead_h, cells_by, base_by_h, sectors) for L in leads_ss]
    order = {"SIGN-OFF": 0, "WATCH": 1, "GRAVEYARD": 2}
    out.sort(key=lambda r: (order[r["verdict"]], -(r["alpha_edge_oos"] if np.isfinite(r["alpha_edge_oos"]) else -9)))

    paths = write_validation(args.asof, out, leads_breadth, rec)
    print("\n=== validation complete ===")
    for r in out:
        print(f"  {r['verdict']:9s} {r['config']:22s} {r['horizon']:3s} "
              f"alpha_OOS={r['alpha_edge_oos']*100:+.2f}% (abs {r['abs_net_edge_oos']*100:+.2f}%) "
              f"a-breakeven={r['break_even_rt_bps']:.0f}bps windows(a)={r['pos_windows']} | "
              f"{r['reasons'][0] if r['reasons'] else ''}")
    for p in paths:
        print(f"  wrote {p}")
    return 0


def _pct(x, dp=2):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{100*x:+.{dp}f}%"


def write_validation(asof, out, leads_breadth, rec):
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    jp = LEADS_DIR / f"validation_{asof}.json"
    jp.write_text(json.dumps({"asof": asof, "leads": out, "breadth_thin": leads_breadth}, indent=1,
                             default=lambda o: float(o) if isinstance(o, np.floating) else str(o)),
                  encoding="utf-8")

    signoff = [r for r in out if r["verdict"] == "SIGN-OFF"]
    watch = [r for r in out if r["verdict"] == "WATCH"]
    grave = [r for r in out if r["verdict"] == "GRAVEYARD"]
    L = []
    L.append(f"# Lead validation — deployability stress-test — as of {asof}")
    L.append("")
    L.append("_Stage 1.5: what significance does not answer. The discovery scan established "
             "each lead's edge is real versus random entry (OOS + FDR + block bootstrap). This "
             "note asks whether it is STABLE across eras, BROAD across the cross-section, "
             "COST-robust, and not an artefact of best-horizon selection. Nothing here is promoted._")
    L.append("")
    L.append("**Key correction from the first pass:** leads are judged on DRIFT-ADJUSTED "
             "**alpha** — each entry's forward return minus that name's own mean forward return "
             "at the same horizon — not the absolute edge. At long horizons the absolute edge is "
             "dominated by market/size/sector drift (a 6-month hold of almost any stock is "
             "positive); stripping each name's own drift isolates the actual signal. Short-horizon "
             "leads (1-week gaps, baseline ≈ 0) are barely affected; long-horizon mean-reversion "
             "leads lose most of their apparent edge. (The drift benchmark is the name's full-sample "
             "mean — an attribution benchmark, not a tradeable estimate.)")
    L.append("")
    L.append(f"**Verdict tally:** {len(signoff)} SIGN-OFF · {len(watch)} WATCH · {len(grave)} GRAVEYARD "
             f"(of {len(out)} single-stock leads); {len(leads_breadth)} breadth leads are episode-thin "
             "(see foot).")
    L.append("")
    L.append("## How to read it")
    L.append("- **alpha (OOS)** is the drift-adjusted, cost-net, block-weighted edge (one obs per "
             "independent market episode). **abs edge** is the raw forward return incl. drift "
             "(context only — do not read it as signal). **α break-even** is the round-trip cost "
             "(bps) that zeroes the *alpha*. **windows +** = disjoint calendar windows with positive "
             "*alpha* (era stability). **p×7** = the OOS p after the within-config best-of-7-horizons "
             "selection penalty.")
    L.append("- **SIGN-OFF** = FDR + positive OOS alpha stable across eras + broad across "
             "tiers/sectors + clears the ×7 haircut + not carried by one window. **WATCH** = real "
             "but fails one. **GRAVEYARD** = fails FDR, or the edge was beta not alpha, or alpha is "
             "negative at 2× cost.")
    L.append("")

    hdr = ("| Verdict | Config | Fam | H | Alpha OOS | Abs edge OOS | Rew/MAE | α break-even | "
           "Windows + | OOS win + | Tiers + | Sectors + | p×7 | Binding reason |")
    sep = "|" + "---|" * 14
    L.append("## Leads, ranked by verdict then OOS alpha")
    L.append(""); L.append(hdr); L.append(sep)
    for r in out:
        L.append(f"| {r['verdict']} | {r['config']} | {r['family'][:4]} | {r['horizon']} | "
                 f"{_pct(r['alpha_edge_oos'])} | {_pct(r['abs_net_edge_oos'])} | "
                 f"{(r['reward_to_mae'] if r['reward_to_mae'] is not None else float('nan')):.2f} | "
                 f"{r['break_even_rt_bps']:.0f}bps | {r['pos_windows']} | {r['pos_oos_windows']} | "
                 f"{r['tier_pos']}/{r['tier_valid']} | {r['sectors_pos']} | "
                 f"{(r['p_x7_selection'] if r['p_x7_selection']==r['p_x7_selection'] else float('nan')):.3f} | "
                 f"{r['reasons'][0] if r['reasons'] else '—'} |")
    L.append("")

    # concentration detail for the top few (all alpha)
    L.append("## Alpha concentration & stability detail (top leads)")
    L.append("")
    for r in (signoff + watch)[:6]:
        L.append(f"### {r['config']} ({r['horizon']}) — {r['verdict']}")
        tl = " · ".join(f"{t}: {_pct(v['alpha'])} (n={v['n_ind']})" for t, v in r["tiers"].items())
        L.append(f"- **Alpha by size tier:** {tl}")
        if r["top_sectors"]:
            ts = " · ".join(f"{k}: {_pct(v['alpha'])}" for k, v in r["top_sectors"])
            bs = " · ".join(f"{k}: {_pct(v['alpha'])}" for k, v in r["bottom_sectors"])
            L.append(f"- **Best GICS sectors (alpha):** {ts}")
            L.append(f"- **Worst GICS sectors (alpha):** {bs}  (dispersion {_pct(r['sector_dispersion'])})")
        wl = " · ".join(f"{w['window']}{'*' if w['oos'] else ''}: {_pct(w['alpha']) if w['n_ind']>=5 else 'thin'}"
                        for w in r["subperiods"])
        L.append(f"- **Alpha by era (* = OOS):** {wl}")
        L.append(f"- **Cost:** alpha {_pct(r['alpha_edge'])} → {_pct(r['alpha_2x_cost'])} at 2× cost, "
                 f"{_pct(r['alpha_5x_cost'])} at 5× cost; alpha break-even {r['break_even_rt_bps']:.0f}bps "
                 f"round trip. (Absolute edge incl. drift: {_pct(r['abs_net_edge'])}.)")
        L.append(f"- **Multiple-testing:** OOS p={r['p_oos']:.4f}, BH-q={r['bh_q']:.3f}, "
                 f"p×7(selection)={r['p_x7_selection']:.3f}, Bonferroni p={r['p_bonferroni']:.3f}.")
        L.append(f"- **Verdict reasons:** {'; '.join(r['reasons'])}.")
        L.append("")

    if leads_breadth:
        L.append("## Breadth leads — episode-thin, not de-thinnable by slicing")
        L.append("")
        for b in leads_breadth:
            o = b["oos"]
            L.append(f"- **{b['config']}** ({b['horizon_label']}): OOS edge {_pct(o['cond_median'])} vs "
                     f"baseline {_pct(o['base_median'])}, but only {o['n_independent_episodes']} independent "
                     "episodes. Breadth thrusts are rare by nature; slicing cannot manufacture episodes. "
                     "Keep as a pre-registered watch item to accrue signals, do not size.")
        L.append("")

    L.append("## Recommendation")
    L.append("")
    if signoff:
        L.append("- **Take to Stage 2 now:** " + ", ".join(f"`{r['config']}`" for r in signoff) + ".")
    if watch:
        L.append("- **Watch / narrow, do not size yet:** " + ", ".join(f"`{r['config']}`" for r in watch) + ".")
    if grave:
        L.append("- **Graveyard:** " + ", ".join(f"`{r['config']}`" for r in grave) + ".")
    L.append("")
    mp = LEADS_DIR / f"validation_{asof}.md"
    mp.write_text("\n".join(L), encoding="utf-8")
    return [mp, jp]


if __name__ == "__main__":
    sys.exit(main())
