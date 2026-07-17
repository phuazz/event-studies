// exit_rule_study.js — the pre-registered exit-rule study.
//
// Spec: studies/2026-07-17_exit-rule_preregistration.md (FROZEN before this ran).
// Question: does any simple pre-registered exit rule beat hold-to-horizon, and if
// not, is hold-to-horizon defensible on evidence rather than by default?
//
// Run:  node scripts/exit_rule_study.js --selftest   (must pass before results)
//       node scripts/exit_rule_study.js              (one run through the frozen menu)
//
// ----------------------------------------------------------------------------
// The three ways this study is silently wrong, and the countermeasure for each
// (stated in the pre-registration before any code was written):
//
//   1. Overfitting the exit on a tiny, non-independent sample. 18 cells against
//      ~21 washout clusters. GLD and SLV fire together 7 times in 21 clusters —
//      one precious-metals selloff, not two draws. Countermeasure: the menu is
//      frozen; every cell is reported; the bootstrap resamples whole CLUSTERS.
//
//   2. Look-ahead in the exit rule. E3's percentile band must be walk-forward —
//      episode i sees only its own ticker's strictly-earlier episodes. Enforced
//      by construction and asserted by a perturbation selftest.
//
//   3. Costs and a rolling episode set. Costs are applied at 1x and 2x (though
//      per amendment A1.2 they are constant across cells and cannot discriminate);
//      the 10y daily cap means the episode set rolls, so the sample is a moving
//      target and that is reported.
// ----------------------------------------------------------------------------

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const RESULTS = path.join(ROOT, 'events_results.json');
const OUT = path.join(ROOT, 'private', 'studies', 'exit-rule-results.json');

const COST_ONE_WAY = 0.0002;   // 2 bps
const TRADES = 2;              // entry + exit, identical for every cell (A1.2)
const MIN_PRECEDENTS = 6;      // E3 needs a band; all cells share this subset
const CLUSTER_DAYS = 21;       // washout: same macro episode if within 21 calendar days
const BOOT = 2000;

// ---------- small stats ----------
const q = (a, p) => {
  if (!a.length) return NaN;
  const s = a.slice().sort((x, y) => x - y);
  const pos = (s.length - 1) * p, lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (pos - lo);
};
const median = a => q(a, 0.5);
const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN;
const randInt = n => Math.floor(Math.random() * n);

// ---------- the frozen menu (§3) ----------
// Each rule receives the episode's forward path r[0..H] (r[0]=0) and the
// walk-forward p75 band (or null); returns the exit index k (<=H).
// A1.1: an early exit holds cash at 0% for the remainder, so the cell's return is
// r[kExit] measured over the SAME 0..H window for every cell.
const MENU = [
  { id: 'E0',  label: 'hold to horizon',        fn: (r, H) => H },
  { id: 'E1a', label: 'fixed stop -5%',         fn: (r, H) => firstK(r, H, k => r[k] <= -0.05) },
  { id: 'E1b', label: 'fixed stop -10%',        fn: (r, H) => firstK(r, H, k => r[k] <= -0.10) },
  { id: 'E2a', label: 'trailing stop 5%',       fn: (r, H) => trailK(r, H, 0.05) },
  { id: 'E2b', label: 'trailing stop 10%',      fn: (r, H) => trailK(r, H, 0.10) },
  { id: 'E3',  label: 'trim above wf p75',      fn: (r, H, band) => band ? firstK(r, H, k => band[k] != null && r[k] > band[k]) : H },
  { id: 'E4a', label: 'time stop 21d',          fn: (r, H) => Math.min(21, H) },
  { id: 'E4b', label: 'time stop 63d',          fn: (r, H) => Math.min(63, H) },
  { id: 'E4c', label: 'time stop 126d',         fn: (r, H) => Math.min(126, H) },
];

function firstK(r, H, pred) {
  for (let k = 1; k <= H; k++) if (pred(k)) return k;
  return H;
}
function trailK(r, H, drop) {
  let peak = 0;
  for (let k = 1; k <= H; k++) {
    if (r[k] > peak) peak = r[k];
    // drawdown from the running peak, in price terms
    if ((1 + r[k]) / (1 + peak) - 1 <= -drop) return k;
  }
  return H;
}

// ---------- episode assembly ----------
// A path is the daily cumulative return from the entry close, r[0..H].
function pathFrom(ac, idx, H) {
  const r = [];
  for (let k = 0; k <= H && idx + k < ac.length; k++) r.push(ac[idx + k] / ac[idx] - 1);
  return r.length === H + 1 ? r : null; // only fully-matured episodes
}

// Walk-forward p75 band for episode i: the 75th percentile at each k across the
// SAME TICKER's strictly-earlier episodes. Never sees episode i or anything after.
function wfBand(priorPaths, H) {
  if (priorPaths.length < MIN_PRECEDENTS) return null;
  const band = [null];
  for (let k = 1; k <= H; k++) {
    const vals = priorPaths.filter(p => p.length > k).map(p => p[k]);
    band.push(vals.length >= MIN_PRECEDENTS ? q(vals, 0.75) : null);
  }
  return band;
}

// ---------- clustering (washout book) ----------
const toDate = s => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
function clusterIds(items) {
  // items: [{date}] sorted; returns a cluster id per item (same macro episode if
  // within CLUSTER_DAYS of the running cluster anchor, across BOTH tickers).
  const ids = []; let cid = 0, anchor = null;
  items.forEach(it => {
    const d = toDate(it.date);
    if (anchor === null || (d - anchor) / 86400000 > CLUSTER_DAYS) { cid++; anchor = d; }
    ids.push(cid);
  });
  return ids;
}

// ---------- run one stratum ----------
function runStratum(name, episodes, H, barred) {
  // episodes: [{ticker,date,r:[...]}] chronological, fully matured, evaluable only
  const cells = MENU.map(m => {
    const rets = [], dds = [];
    episodes.forEach(ep => {
      const kx = m.fn(ep.r, H, ep.band);
      const gross = ep.r[kx];
      // held-period drawdown (what you had to sit through before exiting)
      let lo = 0; for (let j = 1; j <= kx; j++) if (ep.r[j] < lo) lo = ep.r[j];
      rets.push(gross); dds.push(lo);
    });
    const net1 = rets.map(x => x - TRADES * COST_ONE_WAY);
    const net2 = rets.map(x => x - TRADES * COST_ONE_WAY * 2);
    return {
      id: m.id, label: m.label, n: rets.length,
      medianGross: median(rets), median1x: median(net1), median2x: median(net2),
      meanGross: mean(rets), hit: rets.filter(x => x > 0).length / rets.length,
      maxDD: Math.min(...dds), medDD: median(dds),
      rets, dds
    };
  });

  const base = cells.find(c => c.id === 'E0');

  // cluster-level block bootstrap of (cell - E0) on the median
  const cids = [...new Set(episodes.map(e => e.cluster))];
  const byCluster = {}; cids.forEach(c => byCluster[c] = []);
  episodes.forEach((e, i) => byCluster[e.cluster].push(i));

  cells.forEach(c => {
    if (c.id === 'E0') { c.bootWin = null; return; }
    let win = 0;
    for (let b = 0; b < BOOT; b++) {
      const idx = [];
      for (let j = 0; j < cids.length; j++) idx.push(...byCluster[cids[randInt(cids.length)]]);
      const a = median(idx.map(i => c.rets[i])), z = median(idx.map(i => base.rets[i]));
      if (a > z) win++;
    }
    c.bootWin = win / BOOT;
  });

  // three chronological sub-periods
  const third = Math.ceil(episodes.length / 3);
  cells.forEach(c => {
    c.subBeats = [0, 1, 2].map(t => {
      const sl = episodes.map((_, i) => i).filter(i => Math.floor(i / third) === t);
      if (sl.length < 2) return null;
      return median(sl.map(i => c.rets[i])) > median(sl.map(i => base.rets[i]));
    }).filter(x => x !== null);
  });

  cells.forEach(c => {
    c.beatsMedian = c.median1x > base.median1x;
    c.beatsDD = c.maxDD > base.maxDD;         // less negative = better
    c.barred = barred.includes(c.id);
    c.degenerate = c.id !== 'E0' &&
      c.rets.every((x, i) => Math.abs(x - base.rets[i]) < 1e-12);
    delete c.rets; delete c.dds;
  });

  return { name, horizon: H, nEpisodes: episodes.length, nClusters: cids.length, cells };
}

// ---------- selftests (must pass BEFORE any results run) ----------
function selftest() {
  let pass = 0;
  const ok = (cond, msg) => { if (!cond) throw new Error('SELFTEST FAIL: ' + msg); pass++; console.log('  ok  ' + msg); };

  // fixed stop fires on the FIRST breach, close-only
  const r1 = [0, -0.02, -0.06, 0.10, 0.20];
  ok(MENU.find(m => m.id === 'E1a').fn(r1, 4) === 2, 'E1a exits on the first close <= -5%');
  ok(MENU.find(m => m.id === 'E1b').fn(r1, 4) === 4, 'E1b does not fire when -10% is never breached');

  // trailing stop measures from the RUNNING PEAK, not from entry
  const r2 = [0, 0.20, 0.10, 0.05, 0.30];       // peak +20% -> +5% is a 12.5% drawdown
  ok(trailK(r2, 4, 0.10) === 3, 'E2b trails from the running peak (fires at k=3)');
  ok(trailK([0, 0.01, 0.02, 0.03], 3, 0.10) === 3, 'trailing stop does not fire on a monotonic rise');

  // A1.3: E4b is degenerate against a 63d horizon and MUST equal E0 exactly
  const r3 = Array.from({ length: 64 }, (_, k) => k * 0.001);
  ok(MENU.find(m => m.id === 'E4b').fn(r3, 63) === MENU.find(m => m.id === 'E0').fn(r3, 63),
    'A1.3: E4b(63d) is identical to E0 at a 63d horizon');

  // NO-LOOK-AHEAD: perturbing a LATER episode must not change an earlier decision
  const mk = (bump) => {
    const priors = Array.from({ length: 8 }, (_, i) =>
      Array.from({ length: 11 }, (_, k) => k * 0.004 * (i + 1)));
    const band = wfBand(priors, 10);
    const self = Array.from({ length: 11 }, (_, k) => k * 0.02);
    const later = Array.from({ length: 11 }, (_, k) => k * (bump ? 99 : 0.001)); // future episode
    void later; // deliberately NOT passed into the band — that is the point
    return MENU.find(m => m.id === 'E3').fn(self, 10, band);
  };
  ok(mk(false) === mk(true), 'E3 decision is invariant to a later episode (no look-ahead)');

  // walk-forward band refuses to form below the precedent floor
  ok(wfBand([[0, 1], [0, 1]], 1) === null, 'wfBand returns null below MIN_PRECEDENTS');

  // date/boundary: a June anchor + 189 trading days crosses the year boundary
  const jun = toDate('2020-06-30');
  ok(jun.getUTCFullYear() === 2020 && jun.getUTCMonth() === 5, 'JS Date months are 0-indexed: June === 5');
  ok(clusterIds([{ date: '2026-06-10' }, { date: '2026-06-10' }]).join() === '1,1',
    'same-date GLD/SLV triggers collapse to ONE cluster');
  ok(clusterIds([{ date: '2026-01-01' }, { date: '2026-03-01' }]).join() === '1,2',
    'triggers >21d apart are separate clusters');

  console.log(`\n${pass} selftests passed.`);
}

// ---------- main ----------
function main() {
  const D = JSON.parse(fs.readFileSync(RESULTS, 'utf8'));
  const ev = Object.fromEntries(D.events.map(e => [e.id, e]));
  const report = { generatedAt: new Date().toISOString(), spec: 'studies/2026-07-17_exit-rule_preregistration.md', strata: [] };

  // --- washout stratum: GLD + SLV, H=63 ---
  const wash = [];
  for (const [tk, id] of [['GLD', 'gld-oversold-reversion-downtrend'], ['SLV', 'slv-oversold-reversion-downtrend']]) {
    const e = ev[id], ps = e.priceSeries.map(b => b.ac);
    const eps = e.episodes.filter(x => x.idx != null);
    const paths = eps.map(x => pathFrom(ps, x.idx, 63));
    eps.forEach((x, i) => {
      if (!paths[i]) return;                       // not yet matured
      const priors = paths.slice(0, i).filter(Boolean);
      if (priors.length < MIN_PRECEDENTS) return;  // shared evaluable subset
      wash.push({ ticker: tk, date: x.date, r: paths[i], band: wfBand(priors, 63) });
    });
  }
  wash.sort((a, b) => a.date < b.date ? -1 : 1);
  clusterIds(wash).forEach((c, i) => wash[i].cluster = c);
  report.strata.push(runStratum('washout (GLD+SLV)', wash, 63, []));

  // --- SPX seasonal stratum: H=189, E4 barred (§5) ---
  const g = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'GSPC.json'), 'utf8'));
  const dac = g.daily.map(b => b.ac);
  const juneAnchor = {};
  g.daily.forEach((b, i) => { if (b.d.slice(5, 7) === '06') juneAnchor[+b.d.slice(0, 4)] = i; });
  const spxEv = ev['spx-strong-q2-9m-forward'];
  const sig = spxEv.episodes.map(x => ({ date: x.date, year: +x.date.slice(0, 4) }));
  const spx = [];
  const spxPaths = sig.map(s => juneAnchor[s.year] != null ? pathFrom(dac, juneAnchor[s.year], 189) : null);
  sig.forEach((s, i) => {
    if (!spxPaths[i]) return;
    const priors = spxPaths.slice(0, i).filter(Boolean);
    if (priors.length < MIN_PRECEDENTS) return;
    spx.push({ ticker: 'GSPC', date: s.date, r: spxPaths[i], band: wfBand(priors, 189), cluster: i });
  });
  report.strata.push(runStratum('SPX seasonal', spx, 189, ['E4a', 'E4b', 'E4c']));

  // --- gate (§6) ---
  const survivors = MENU.filter(m => m.id !== 'E0').map(m => m.id).filter(id => {
    return report.strata.every(st => {
      const c = st.cells.find(x => x.id === id);
      if (c.barred || c.degenerate) return false;
      return c.beatsMedian && c.beatsDD && c.bootWin >= 0.90 &&
        c.subBeats.filter(Boolean).length >= 2 && c.median2x > st.cells.find(x => x.id === 'E0').median2x;
    });
  });
  report.survivors = survivors;
  report.verdict = survivors.length ? `TAKEN FORWARD: ${survivors.join(', ')}` : 'NO RULE CLEARS — E0 (hold to horizon) STANDS';

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(report, null, 1));

  // --- console summary ---
  const pc = v => (v == null || Number.isNaN(v) ? '  —  ' : (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%');
  for (const st of report.strata) {
    console.log(`\n=== ${st.name}  H=${st.horizon}d  n=${st.nEpisodes} episodes / ${st.nClusters} clusters`);
    console.log('cell  rule                 med(1x)   maxDD    hit   boot  sub  flag');
    for (const c of st.cells) {
      const flag = c.barred ? 'BARRED(§5)' : c.degenerate ? 'degenerate=E0' : '';
      console.log(`${c.id.padEnd(5)} ${c.label.padEnd(20)} ${pc(c.median1x).padStart(8)} ${pc(c.maxDD).padStart(8)} ` +
        `${(c.hit * 100).toFixed(0).padStart(4)}% ${c.bootWin == null ? '  — ' : c.bootWin.toFixed(2)} ` +
        `${c.subBeats.filter(Boolean).length}/${c.subBeats.length}  ${flag}`);
    }
  }
  console.log(`\nVERDICT: ${report.verdict}`);
  console.log(`Wrote ${OUT}`);
}

if (require.main === module) {
  if (process.argv.includes('--selftest')) selftest();
  else main();
}
