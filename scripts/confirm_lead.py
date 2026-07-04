#!/usr/bin/env python
"""confirm_lead.py — Stage 2 confirmation: re-test ONE pre-registered cross-sectional
lead on the Norgate point-in-time universe, rigorously, as a single hypothesis.

This closes the seam the single-target Yahoo engine (engine/events.js) cannot: a
discovery lead is a CROSS-SECTIONAL stock signal, so confirming it on one ETF is
underpowered and blind to delisted names. Here we re-run the archetype over the
full survivorship-free cross-section, but with confirmation discipline that the
discovery scan (which mines 36x7x3 cells) cannot have:

  - PRE-REGISTRATION GATE: the card must carry a written rationale (the antidote to
    fishing, mirroring events.js). One hypothesis is tested, so the p-value needs
    NO multiple-testing correction — a plain p<0.05 is the bar, not FDR.
  - The effect size is DRIFT-ADJUSTED alpha (excess over each name's own drift,
    episode-weighted mean CAR) — signal, not beta.
  - Significance is a drift-aware random-entry Monte Carlo that preserves the
    episode block structure (the cross-sectional analogue of the events.js
    random-entry test): does entering ON the signal beat entering RANDOMLY in the
    same names, in excess of drift?
  - Reports the full horizon decay curve, the SPY>200d regime split, the IS/OOS
    split, and independent-episode accounting; and the count of episodes accrued
    SINCE registration (genuinely out-of-sample), which grows each re-run.

Verdict: CONFIRMED / CONFIRMED-THIN / NOT-CONFIRMED. It NEVER edits
catalogue/catalogue.json, docs/, or the dashboard — admission remains the PM's,
after sign-off. Writes private/leads/confirmations/<config>_<asof>.{json,md}.

Run (needs NDU up + the cached scan):
    python scripts/confirm_lead.py --card mo_breakaway_gap5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import norgate_universe as nu   # noqa: E402
import discovery_scan as ds     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROMOTED_DIR = ROOT / "private" / "leads" / "promoted"
CONF_DIR = ROOT / "private" / "leads" / "confirmations"

PLACEHOLDER_MARKERS = ("PLACEHOLDER",)


def load_card(config: str) -> dict:
    cand_f = PROMOTED_DIR / f"{config}__candidate.json"
    card_f = PROMOTED_DIR / f"{config}__catalogue_card.json"
    if not cand_f.exists():
        raise SystemExit(f"no promoted candidate for {config!r} at {cand_f} — run promote_lead first")
    cand = json.loads(cand_f.read_text(encoding="utf-8"))
    card = json.loads(card_f.read_text(encoding="utf-8")) if card_f.exists() else {}
    rationale = card.get("rationale") or cand.get("rationaleDraft") or ""
    # PRE-REGISTRATION GATE: refuse a card with no written rationale.
    if not rationale.strip():
        raise SystemExit(f"pre-registration gate: {config} has no rationale — write one before confirming")
    if any(rationale.strip().startswith(m) for m in PLACEHOLDER_MARKERS):
        print(f"[warn] {config} rationale is still a bare PLACEHOLDER — confirming anyway, but the "
              "card is not admission-ready until you write the mechanism.", file=sys.stderr)
    horizon = cand.get("ourDiscoveryNumbers", {}).get("headlineHorizon") or "1M"
    return {"config": config, "kind": cand.get("proposedKind"),
            "registered_iso": cand.get("discoveredAtISO"), "horizon_label": horizon,
            "sign_off": cand.get("signOff", {}), "rationale": rationale,
            "engine_status": cand.get("engineStatus"), "target": cand.get("target")}


def build_regime(n) -> dict:
    """SPY above its 200-day SMA, as {date_ordinal: bool} (methodology regime gate)."""
    spy = nu.load_prices("SPY", n=n)
    close = spy["Close"].to_numpy(dtype=float)
    s200 = ds.sma(close, 200)
    dates = list(spy.index.date)
    return {dates[i].toordinal(): bool(close[i] > s200[i])
            for i in range(len(close)) if np.isfinite(s200[i])}


def collect_one(n, uni, config, sym_index):
    """Gather every trigger of ONE config across the cross-section, per horizon:
    (date_ord, sym_id, tier, net fwd, drift-adjusted abnormal, MAE). Also returns
    the per-name unconditional forward distributions of contributing names (for the
    drift-aware null)."""
    cfg = {c["id"]: c for c in ds.SINGLE_STOCK_CONFIGS}.get(config)
    if cfg is None:
        raise SystemExit(f"{config} is not a single-stock archetype (breadth confirmation is index-level; "
                         "use breadth_scan). confirm_lead handles single-stock leads.")
    symbols = uni["symbols"]; mem_map = uni["membership_index_map"]
    # `fwd`/`abn` are GROSS (signal detection is on gross returns; the drift-aware
    # null is gross, so both sides match). Per-entry `cost` is kept so the report
    # can show the net, deployable alpha separately.
    per_h = {h: {"date": [], "sym": [], "tier": [], "fwd": [], "abn": [], "cost": [], "mae": []}
             for h in ds.HORIZONS}
    base_fwd_by_sym = {}
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
        trig = cfg["detect"](prices) & member_any
        idxs = np.flatnonzero(trig)
        if idxs.size == 0:
            continue
        keep, anchor = [], -10**9
        for i in idxs:
            if i - anchor > ds.CLUSTER_DAYS:
                keep.append(int(i)); anchor = int(i)
        if not keep:
            continue
        sid = sym_index[s]; nbar = len(close)
        bf = ds.build_base_fwd(close)
        base_fwd_by_sym[sid] = bf
        drift = {h: (float(bf[h].mean()) if bf[h].size else 0.0) for h in ds.HORIZONS}
        tier = ds.cost_tier(mem_map.get(s, [])); cost = ds.COST_BPS[tier] / 1e4
        dates = prices["dates"]
        for i in keep:
            do = dates[i].toordinal()
            for h in ds.HORIZONS:
                j = min(i + h, nbar - 1)
                if j <= i:
                    continue
                seg = close[i:j + 1] / close[i] - 1.0
                fwd_gross = float(close[j] / close[i] - 1.0)
                P = per_h[h]
                P["date"].append(do); P["sym"].append(sid); P["tier"].append(tier)
                P["fwd"].append(fwd_gross); P["abn"].append(fwd_gross - drift[h])
                P["cost"].append(cost); P["mae"].append(float(seg.min()))
        if k % 500 == 0:
            print(f"  ... {k}/{len(symbols)} symbols", file=sys.stderr)
    return per_h, base_fwd_by_sym


def mean_car(abn: np.ndarray, date: np.ndarray):
    """Episode-weighted mean CAR (drift-adjusted alpha) + independent-episode count."""
    if abn.size == 0:
        return float("nan"), 0
    ep = ds.cluster_market_episodes(date, ds.CLUSTER_DAYS)
    order = np.argsort(ep, kind="mergesort")
    a = abn[order]; e = ep[order]
    starts = np.concatenate(([0], np.flatnonzero(np.diff(e)) + 1))
    sizes = np.diff(np.concatenate((starts, [a.size]))).astype(float)
    return float(np.mean(np.add.reduceat(a, starts) / sizes)), int(starts.size)


def confirm_horizon(P, base_fwd_by_sym, horizon, regime, rng):
    date = np.array(P["date"]); sym = np.array(P["sym"])
    fwd = np.array(P["fwd"]); abn = np.array(P["abn"]); mae = np.array(P["mae"])
    cost = np.array(P["cost"])
    n_trades = fwd.size
    if n_trades == 0:
        return None
    alpha, n_ind = mean_car(abn, date)                 # GROSS drift-adjusted alpha (signal)
    alpha_net, _ = mean_car(abn - cost, date)          # net of liquidity-tiered cost (deployable)

    # sort into episode blocks for the vectorised null / CI
    ep = ds.cluster_market_episodes(date, ds.CLUSTER_DAYS)
    order = np.argsort(ep, kind="mergesort")
    a = abn[order]; s = sym[order]; e = ep[order]
    starts = np.concatenate(([0], np.flatnonzero(np.diff(e)) + 1))
    sizes = np.diff(np.concatenate((starts, [n_trades]))).astype(float)
    ep_abn = np.add.reduceat(a, starts) / sizes

    # bootstrap CI on the alpha (resample episodes)
    pick = rng.integers(0, n_ind, size=(ds.BOOT_ITERS, n_ind))
    boot = np.mean(ep_abn[pick], axis=1)
    ci_lo, ci_hi = float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95))

    # drift-aware random-entry null (single pre-registered test)
    b_eff = int(min(ds.BOOT_ITERS, max(300, 15_000_000 // max(n_trades, 1))))
    vals = np.empty((b_eff, n_trades), dtype=np.float64)
    drift_col = np.empty(n_trades)
    for su in np.unique(s):
        cols = np.flatnonzero(s == su)
        arr = base_fwd_by_sym[su][horizon]
        drift_col[cols] = arr.mean() if arr.size else 0.0
        vals[:, cols] = arr[rng.integers(0, arr.size, size=(b_eff, cols.size))] if arr.size else np.nan
    abn_null = vals - drift_col
    ep_mean_null = np.add.reduceat(abn_null, starts, axis=1) / sizes
    null_alpha = np.nanmean(ep_mean_null, axis=1)
    ge = int(np.sum(null_alpha >= alpha))
    p_two = 2.0 * min(ge, b_eff - ge) / b_eff

    # regime split (SPY > 200d at entry), IS/OOS split
    reg = np.array([regime.get(int(d), None) for d in date])
    a_on, n_on = mean_car(abn[reg == True], date[reg == True])   # noqa: E712
    a_off, n_off = mean_car(abn[reg == False], date[reg == False])  # noqa: E712
    is_oos = date >= dt.date(2015, 1, 1).toordinal()
    a_is, n_is = mean_car(abn[~is_oos], date[~is_oos])
    a_oos, n_oos = mean_car(abn[is_oos], date[is_oos])

    hit = float((fwd > 0).mean())
    med_mae = float(np.median(mae))
    reward_to_mae = float(alpha / abs(med_mae)) if med_mae < 0 else float("inf")
    return {
        "horizon": horizon, "horizon_label": ds.HORIZON_LABELS[ds.HORIZONS.index(horizon)],
        "alpha": alpha, "alpha_net": alpha_net, "ci_lo": ci_lo, "ci_hi": ci_hi, "p_value": p_two,
        "n_trades": int(n_trades), "n_independent_episodes": int(n_ind),
        "hit_rate": hit, "reward_to_mae": reward_to_mae,
        "regime_on": {"alpha": a_on, "n_ind": n_on}, "regime_off": {"alpha": a_off, "n_ind": n_off},
        "in_sample": {"alpha": a_is, "n_ind": n_is}, "out_of_sample": {"alpha": a_oos, "n_ind": n_oos},
    }


def verdict(hz: dict) -> tuple:
    if hz is None:
        return "NO-DATA", ["no triggers"]
    reasons = []
    ok_alpha = hz["alpha"] > 0
    ok_p = hz["p_value"] < 0.05
    ok_oos = hz["out_of_sample"]["alpha"] > 0
    thin = hz["n_independent_episodes"] < 20
    if not ok_alpha:
        return "NOT-CONFIRMED", ["drift-adjusted alpha <= 0"]
    if not ok_p:
        return "NOT-CONFIRMED", [f"not significant (p={hz['p_value']:.3f} >= 0.05)"]
    if not ok_oos:
        return "NOT-CONFIRMED", ["OOS drift-adjusted alpha <= 0 (not sign-consistent)"]
    if thin:
        return "CONFIRMED-THIN", [f"significant + sign-consistent, but only {hz['n_independent_episodes']} episodes"]
    return "CONFIRMED", ["positive drift-adjusted alpha, significant as a single pre-registered test, "
                         "sign-consistent out-of-sample, >=20 independent episodes"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--card", required=True, help="promoted config id, e.g. mo_breakaway_gap5")
    ap.add_argument("--seed", type=int, default=20260704)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rng = np.random.default_rng(args.seed)

    card = load_card(args.card)
    n = nu.connect(); proof = nu.hard_check(n)
    asof = proof["expected_last_session"]
    uni = nu.resolve_universe(n)
    sym_index = {s: k for k, s in enumerate(uni["symbols"])}
    print(f"[confirm] {card['config']} (registered {card['registered_iso']}, horizon {card['horizon_label']}) "
          f"over {len(uni['symbols'])} names", file=sys.stderr)

    regime = build_regime(n)
    per_h, base_fwd_by_sym = collect_one(n, uni, card["config"], sym_index)
    curve = [confirm_horizon(per_h[h], base_fwd_by_sym, h, regime, rng) for h in ds.HORIZONS]
    curve = [c for c in curve if c is not None]

    hz_label = card["horizon_label"]
    headline = next((c for c in curve if c["horizon_label"] == hz_label), curve[0] if curve else None)
    vd, reasons = verdict(headline)

    # episodes accrued SINCE registration (genuinely out-of-sample forward test)
    reg_ord = dt.date.fromisoformat(card["registered_iso"]).toordinal() if card.get("registered_iso") else None
    since = None
    if headline and reg_ord:
        d = np.array(per_h[headline["horizon"]]["date"])
        since = int(np.sum(d >= reg_ord))

    out = {"config": card["config"], "asof": asof, "registered_iso": card["registered_iso"],
           "kind": card["kind"], "engine_status": card["engine_status"], "target": card["target"],
           "sign_off": card["sign_off"], "headline_horizon": hz_label,
           "verdict": vd, "reasons": reasons, "headline": headline, "curve": curve,
           "episodes_since_registration": since,
           "single_hypothesis_note": "One pre-registered hypothesis — p<0.05 is the bar; NO multiple-testing "
                                      "correction applies (unlike the discovery scan).",
           "proof": proof, "universe_counts": uni["counts"], "rationale": card["rationale"]}
    paths = write_confirmation(out)
    print(f"\n=== confirmation: {card['config']} -> {vd} ===")
    if headline:
        print(f"  {hz_label}: alpha {headline['alpha']*100:+.2f}% [CI {headline['ci_lo']*100:+.2f}, "
              f"{headline['ci_hi']*100:+.2f}] p={headline['p_value']:.3f} "
              f"episodes={headline['n_independent_episodes']} "
              f"(regime on {headline['regime_on']['alpha']*100:+.2f}% / off {headline['regime_off']['alpha']*100:+.2f}%)")
    print("  reasons: " + "; ".join(reasons))
    for p in paths:
        print(f"  wrote {p}")
    return 0


def _pct(x, dp=2):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{100*x:+.{dp}f}%"


def write_confirmation(out):
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    jp = CONF_DIR / f"{out['config']}_{out['asof']}.json"
    jp.write_text(json.dumps(out, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else str(o)),
                  encoding="utf-8")
    h = out["headline"]; L = []
    L.append(f"# Confirmation — {out['config']} — {out['verdict']} — as of {out['asof']}")
    L.append("")
    L.append(f"_Stage 2 cross-sectional confirmation of a PRE-REGISTERED lead (registered "
             f"{out['registered_iso']}) on the Norgate point-in-time universe "
             f"({out['universe_counts']['total']:,} names, {out['universe_counts']['delisted_suffixed']:,} "
             "delisted). A single hypothesis — p<0.05 is the bar, no multiple-testing correction. Nothing is "
             "admitted to the catalogue or dashboard; sign-off remains yours._")
    L.append("")
    L.append(f"**Verdict: {out['verdict']}** — {'; '.join(out['reasons'])}.")
    L.append("")
    if h:
        L.append(f"## Headline horizon ({out['headline_horizon']})")
        L.append("")
        L.append(f"- **Drift-adjusted alpha (gross):** {_pct(h['alpha'])} "
                 f"(90% CI {_pct(h['ci_lo'])} … {_pct(h['ci_hi'])}), **p = {h['p_value']:.4f}** "
                 "(drift-aware random-entry Monte Carlo, single pre-registered test). "
                 f"Net of liquidity-tiered cost: {_pct(h['alpha_net'])}.")
        L.append(f"- **Independent episodes:** {h['n_independent_episodes']} "
                 f"({h['n_trades']:,} name-entries); hit-rate {h['hit_rate']*100:.0f}%, "
                 f"reward/MAE {h['reward_to_mae']:.2f}.")
        L.append(f"- **Regime split (SPY vs 200d):** on-trend {_pct(h['regime_on']['alpha'])} "
                 f"(n={h['regime_on']['n_ind']}) · off-trend {_pct(h['regime_off']['alpha'])} "
                 f"(n={h['regime_off']['n_ind']}).")
        L.append(f"- **In-sample vs out-of-sample:** IS {_pct(h['in_sample']['alpha'])} "
                 f"(n={h['in_sample']['n_ind']}) · OOS {_pct(h['out_of_sample']['alpha'])} "
                 f"(n={h['out_of_sample']['n_ind']}).")
        if out.get("episodes_since_registration") is not None:
            L.append(f"- **Episodes since registration:** {out['episodes_since_registration']} "
                     "(grows each re-run — the genuinely forward, post-registration test).")
        L.append("")
    L.append("## Horizon decay curve (drift-adjusted alpha)")
    L.append("")
    L.append("| Horizon | Alpha | 90% CI | p | Episodes |")
    L.append("|---|---|---|---|---|")
    for c in out["curve"]:
        L.append(f"| {c['horizon_label']} | {_pct(c['alpha'])} | {_pct(c['ci_lo'])} … {_pct(c['ci_hi'])} | "
                 f"{c['p_value']:.3f} | {c['n_independent_episodes']} |")
    L.append("")
    L.append("## Pre-registered rationale (as filed)")
    L.append("")
    L.append("> " + out["rationale"].replace("\n", "\n> "))
    L.append("")
    L.append("## Next step")
    L.append("")
    approved = out["sign_off"].get("approved")
    L.append(f"Sign-off status: **approved = {approved}**. " + (
        "This confirmation is evidence for your admission decision; it does not admit anything. "
        "If you approve, paste the card into `catalogue/catalogue.json`, set `signOff.approved = true`, "
        "and the ongoing re-runs will accrue post-registration episodes as a live forward test."))
    L.append("")
    mp = CONF_DIR / f"{out['config']}_{out['asof']}.md"
    mp.write_text("\n".join(L), encoding="utf-8")
    return [mp, jp]


if __name__ == "__main__":
    sys.exit(main())
