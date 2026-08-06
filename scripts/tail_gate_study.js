// tail_gate_study.js — episode emitter for the tail-gate study (E1a successor).
//
// Spec: studies/2026-08-06_tail-gate_preregistration.md (FROZEN, countersigned).
// Role: reproduce the 2026-07-17 exit-rule sample EXACTLY from the pinned
// events_results.json (commit 8e9e775, the last change before the filed run),
// assert the filed E0/E1a aggregates as a reconciliation gate (STOP on miss),
// then emit per-episode detail (exit day, dates, returns, held-path DD,
// cluster ids) for the Python scorer. No scoring happens here.
//
// Episode assembly is copied VERBATIM from scripts/exit_rule_study.js (the
// frozen engine): pathFrom / wfBand / clusterIds / firstK / trailK, with the
// same MIN_PRECEDENTS and CLUSTER_DAYS. The only additions are date emission
// and the reconciliation asserts.
//
// Run: node scripts/tail_gate_study.js <pinned_events_results.json>

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const FILED = path.join(ROOT, 'private', 'studies', 'exit-rule-results.json');
const OUT = path.join(ROOT, 'private', 'studies', 'tail-gate-episodes.json');

const MIN_PRECEDENTS = 6;
const CLUSTER_DAYS = 21;
const TOL = 1e-12;

const q = (a, p) => {
  if (!a.length) return NaN;
  const s = a.slice().sort((x, y) => x - y);
  const pos = (s.length - 1) * p, lo = Math.floor(pos), hi = Math.ceil(pos);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (pos - lo);
};
const median = a => q(a, 0.5);
const mean = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN;

function firstK(r, H, pred) {
  for (let k = 1; k <= H; k++) if (pred(k)) return k;
  return H;
}
function trailK(r, H, drop) {
  let peak = 0;
  for (let k = 1; k <= H; k++) {
    if (r[k] > peak) peak = r[k];
    if ((1 + r[k]) / (1 + peak) - 1 <= -drop) return k;
  }
  return H;
}
const CELLS = [
  { id: 'E0',  fn: (r, H) => H },
  { id: 'E1a', fn: (r, H) => firstK(r, H, k => r[k] <= -0.05) },
  { id: 'E1b', fn: (r, H) => firstK(r, H, k => r[k] <= -0.10) },
  { id: 'E2a', fn: (r, H) => trailK(r, H, 0.05) },
  { id: 'E2b', fn: (r, H) => trailK(r, H, 0.10) },
];

function pathFrom(ac, idx, H) {
  const r = [];
  for (let k = 0; k <= H && idx + k < ac.length; k++) r.push(ac[idx + k] / ac[idx] - 1);
  return r.length === H + 1 ? r : null;
}
function wfBand(priorPaths, H) {
  if (priorPaths.length < MIN_PRECEDENTS) return null;
  const band = [null];
  for (let k = 1; k <= H; k++) {
    const vals = priorPaths.filter(p => p.length > k).map(p => p[k]);
    band.push(vals.length >= MIN_PRECEDENTS ? q(vals, 0.75) : null);
  }
  return band;
}
const toDate = s => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
function clusterIds(items) {
  const ids = []; let cid = 0, anchor = null;
  items.forEach(it => {
    const d = toDate(it.date);
    if (anchor === null || (d - anchor) / 86400000 > CLUSTER_DAYS) { cid++; anchor = d; }
    ids.push(cid);
  });
  return ids;
}

function perEpisode(episodes, H, dates) {
  // dates: per episode, array of calendar dates aligned to r[0..H]
  return episodes.map((ep, i) => {
    const cells = {};
    CELLS.forEach(m => {
      const k = m.fn(ep.r, H, undefined);
      let lo = 0; for (let j = 1; j <= k; j++) if (ep.r[j] < lo) lo = ep.r[j];
      cells[m.id] = {
        k, ret: ep.r[k], heldDD: lo,
        exitDate: dates[i][k], horizonDate: dates[i][H],
      };
    });
    return { ticker: ep.ticker, entryDate: ep.date, cluster: ep.cluster, cells,
             r: ep.r.map(v => Math.round(v * 1e10) / 1e10),
             dates: dates[i] };
  });
}

function agg(eps, id) {
  const rets = eps.map(e => e.cells[id].ret);
  const dds = eps.map(e => e.cells[id].heldDD);
  return { n: rets.length, medianGross: median(rets), meanGross: mean(rets),
           hit: rets.filter(x => x > 0).length / rets.length,
           maxDD: Math.min(...dds) };
}

function reconcile(name, eps, filedStratum, nClusters) {
  const fail = (m) => { console.error('RECONCILIATION MISS: ' + m); process.exit(2); };
  if (eps.length !== filedStratum.nEpisodes)
    fail(`${name} nEpisodes ${eps.length} vs filed ${filedStratum.nEpisodes}`);
  if (nClusters !== filedStratum.nClusters)
    fail(`${name} nClusters ${nClusters} vs filed ${filedStratum.nClusters}`);
  for (const id of ['E0', 'E1a', 'E1b', 'E2a', 'E2b']) {
    const got = agg(eps, id);
    const f = filedStratum.cells.find(c => c.id === id);
    for (const k of ['medianGross', 'meanGross', 'hit', 'maxDD']) {
      if (Math.abs(got[k] - f[k]) > TOL)
        fail(`${name} ${id}.${k}: ${got[k]} vs filed ${f[k]}`);
    }
  }
  console.log(`reconciliation PASS: ${name} (E0/E1a/E1b/E2a/E2b exact)`);
}

function main() {
  const pinPath = process.argv[2];
  if (!pinPath) { console.error('usage: node tail_gate_study.js <pinned_events_results.json>'); process.exit(1); }
  const D = JSON.parse(fs.readFileSync(pinPath, 'utf8').replace(/^﻿/, ''));
  const filed = JSON.parse(fs.readFileSync(FILED, 'utf8'));
  const ev = Object.fromEntries(D.events.map(e => [e.id, e]));

  // --- washout stratum (GLD+SLV, H=63) — assembly verbatim ---
  const H1 = 63;
  const wash = [];
  for (const [tk, id] of [['GLD', 'gld-oversold-reversion-downtrend'], ['SLV', 'slv-oversold-reversion-downtrend']]) {
    const e = ev[id], ps = e.priceSeries.map(b => b.ac);
    const pd = e.priceSeries.map(b => b.d);
    const eps = e.episodes.filter(x => x.idx != null);
    const paths = eps.map(x => pathFrom(ps, x.idx, H1));
    eps.forEach((x, i) => {
      if (!paths[i]) return;
      const priors = paths.slice(0, i).filter(Boolean);
      if (priors.length < MIN_PRECEDENTS) return;
      wash.push({ ticker: tk, date: x.date, r: paths[i],
                  dates: Array.from({ length: H1 + 1 }, (_, k) => pd[x.idx + k]) });
    });
  }
  wash.sort((a, b) => a.date < b.date ? -1 : 1);
  clusterIds(wash).forEach((c, i) => wash[i].cluster = c);
  const washDates = wash.map(e => e.dates);
  const washFiled = filed.strata.find(s => s.name === 'washout (GLD+SLV)');
  const washClusters = new Set(wash.map(e => e.cluster)).size;
  reconcile('washout', perEpisode(wash, H1, washDates), washFiled, washClusters);

  // --- SPX seasonal stratum (H=189) — assembly verbatim ---
  const H2 = 189;
  const g = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'GSPC.json'), 'utf8'));
  const dac = g.daily.map(b => b.ac);
  const gd = g.daily.map(b => b.d);
  const juneAnchor = {};
  g.daily.forEach((b, i) => { if (b.d.slice(5, 7) === '06') juneAnchor[+b.d.slice(0, 4)] = i; });
  const spxEv = ev['spx-strong-q2-9m-forward'];
  const sig = spxEv.episodes.map(x => ({ date: x.date, year: +x.date.slice(0, 4) }));
  const spx = [];
  const spxPaths = sig.map(s => juneAnchor[s.year] != null ? pathFrom(dac, juneAnchor[s.year], H2) : null);
  sig.forEach((s, i) => {
    if (!spxPaths[i]) return;
    const priors = spxPaths.slice(0, i).filter(Boolean);
    if (priors.length < MIN_PRECEDENTS) return;
    const a = juneAnchor[s.year];
    spx.push({ ticker: 'GSPC', date: s.date, r: spxPaths[i], cluster: i,
               dates: Array.from({ length: H2 + 1 }, (_, k) => gd[a + k]) });
  });
  const spxDates = spx.map(e => e.dates);
  const spxFiled = filed.strata.find(s => s.name === 'SPX seasonal');
  reconcile('SPX', perEpisode(spx, H2, spxDates), spxFiled, spx.length);

  const out = {
    generatedAt: new Date().toISOString(),
    spec: 'studies/2026-08-06_tail-gate_preregistration.md',
    pin: { eventsResults: path.basename(pinPath), commit: '8e9e775' },
    strata: [
      { name: 'washout (GLD+SLV)', horizon: H1,
        episodes: perEpisode(wash, H1, washDates) },
      { name: 'SPX seasonal', horizon: H2,
        episodes: perEpisode(spx, H2, spxDates) },
    ],
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
  const dr = out.strata.map(s => {
    const ds = s.episodes.map(e => e.entryDate);
    return `${s.name}: ${s.episodes.length} eps ${ds[0]} .. ${ds[ds.length - 1]}`;
  });
  console.log(dr.join('\n'));
  console.log('wrote ' + OUT);
}

main();
