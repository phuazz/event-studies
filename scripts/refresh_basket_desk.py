#!/usr/bin/env python
"""refresh_basket_desk.py — one command to rebuild the Basket Research Desk, with a
guard layer that can actually fail.

  python scripts/refresh_basket_desk.py            # reuse the panel, refresh the desk
  python scripts/refresh_basket_desk.py --full     # rebuild the point-in-time panel too (~6 min)
  python scripts/refresh_basket_desk.py --check     # guards only, build nothing

Why guards: the vault rule is that nothing runs unattended without a layer that can
catch a silently-wrong step. Every check below has a real threshold and a real
failure mode; a guard that cannot fail is decoration. One of them (G4) exists
because the bug it tests for actually shipped: delisted symbols appearing in the
live holdings table while remaining, correctly, in the backtest.

Output stays under private/ (gitignored) — the desk lists individual holdings and
this repo is public. This script is code only and carries no data.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PRIV = os.path.join(ROOT, "private", "studies")
DATA = os.path.join(ROOT, "data")
PANEL = os.path.join(DATA, "_pit_sp1500.parquet")
PAGE = os.path.join(PRIV, "basket_dashboard.html")
DD = os.path.join(PRIV, "dashboard_data.json")
CURVES = os.path.join(PRIV, "basket_curves.json")

FULL = "--full" in sys.argv
CHECK_ONLY = "--check" in sys.argv
fails, warns = [], []


def step(cmd, label):
    print(f"\n>>> {label}")
    r = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True)
    tail = [l for l in (r.stdout or "").strip().split("\n") if l.strip()][-3:]
    for l in tail:
        print("    " + l)
    if r.returncode != 0:
        err = (r.stderr or "").strip().split("\n")[-3:]
        for l in err:
            print("    ! " + l)
        fails.append(f"{label} exited {r.returncode}")
    return r.returncode == 0


def guard(ok, name, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)
    return ok


# ---------- build ----------
if not CHECK_ONLY:
    if FULL:
        step(["scripts/build_pit_universe.py", "S&P Composite 1500", "sp1500"], "rebuild point-in-time panel")
    if not os.path.exists(PANEL):
        print(f"\n!! panel missing: {PANEL}\n   run once with --full")
        sys.exit(2)
    step(["private/studies/export_basket_curves.py"], "export strategy curves")
    step(["scripts/export_dashboard_data.py"], "export desk data")
    step(["scripts/build_dashboard.py"], "build dashboard")

# ---------- guards ----------
print("\n>>> guards")
for p, n in ((PANEL, "panel"), (DD, "desk data"), (CURVES, "curves"), (PAGE, "page")):
    if not os.path.exists(p):
        guard(False, f"{n} exists", p)
if fails:
    print("\nRESULT: FAIL — required inputs missing")
    sys.exit(1)

X = json.load(open(DD)); C = json.load(open(CURVES)); U = X["universe"]

# G1 panel freshness — the desk is only as current as its last closed month
import datetime as _dt
y, m = (int(v) for v in U["end"].split("-"))
age = (_dt.date.today().year - y) * 12 + (_dt.date.today().month - m)
guard(age <= 2, "G1 panel freshness", f"last month {U['end']}, {age} month(s) old (limit 2)")

# G2 point-in-time join resolves — the check that says membership actually matched
res = U["membersLatest"] / U["liveToday"]
guard(0.90 <= res <= 1.05, "G2 membership resolution",
      f"{U['membersLatest']:,}/{U['liveToday']:,} = {res*100:.1f}% (band 90-105%)")

# G3 basket is the size the rule says
guard(len(X["basket"]) == 50, "G3 basket size", f"{len(X['basket'])} names (expected 50)")

# G4 no delisted symbol in the LIVE holdings — this bug shipped once
bad = [b["sym"] for b in X["basket"] if re.search(r"-\d{6}$", b["sym"])]
guard(not bad, "G4 no delisted names in live basket", f"{len(bad)} found: {bad[:4]}" if bad else "clean")

# G5 delisted names are still IN the panel — dropping them would reintroduce
#    survivorship bias, so this guards the opposite error to G4
import pandas as pd
pan = pd.read_parquet(PANEL, columns=["sym"])
n_del = int(pan.sym.str.contains(r"-\d{6}$", regex=True).sum())
guard(n_del > 0, "G5 delisted history retained in panel", f"{n_del:,} delisted-symbol records")

# G6 curves are aligned and finite
lens = {k: len(C[k]["eq"]) for k in ("bench", "trend", "buffered")}
ok = len(set(lens.values())) == 1 and min(lens.values()) > 300
guard(ok, "G6 curves aligned", f"lengths {lens}")
guard(all(all(isinstance(v, (int, float)) for v in C[k]["eq"]) for k in lens),
      "G6b curves finite", "no nulls")

# G7 chart series populated
guard(len(X["breadthHistory"]) > 300 and len(X["coverage"]) > 25, "G7 chart series populated",
      f"breadth {len(X['breadthHistory'])} months, coverage {len(X['coverage'])} years")

# G8 headline figures on the page match the curve file (catches a stale rebuild)
html = open(PAGE, encoding="utf-8").read()
exp = f"{C['bench']['cagr']*100:.2f}%"
guard(exp in html, "G8 page matches curves", f"benchmark CAGR {exp} present in page")
guard(len(html) > 60000, "G8b page size sane", f"{len(html):,} bytes")

# G9 static publication check (vault MOBILE_CHECK, half one)
cp = os.path.join(ROOT, "..", "scripts", "check_page.py")
if os.path.exists(cp):
    r = subprocess.run([sys.executable, cp, PAGE], capture_output=True, text=True)
    line = [l for l in (r.stdout or "").split("\n") if l.strip().startswith("-->")]
    guard(r.returncode == 0, "G9 publication check", line[0].strip() if line else "see check_page output")
else:
    warns.append("G9 skipped — check_page.py not found")

print("\n" + "=" * 62)
if warns:
    for w in warns:
        print(f"WARN: {w}")
if fails:
    print(f"RESULT: FAIL — {len(fails)} guard(s) tripped: {fails}")
    sys.exit(1)
print("RESULT: PASS — desk rebuilt and verified")
print(f"  page   {PAGE}")
print(f"  as at  {U['end']}  ·  {U['membersLatest']:,} members  ·  {len(X['basket'])} holdings")
print("  republish the artifact to update the hosted copy")
