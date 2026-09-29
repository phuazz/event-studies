#!/usr/bin/env node
/* test_payload_trim.js — guards the compact price-series format (2026-09-29).
 *
 * WHY THIS EXISTS. events_results.json had grown to 2.65MB because every daily card
 * shipped its whole target history, back to 1949 on the GSPC cards. The engine now
 * ships only the bars index.html reads, as segments that keep their absolute positions
 * (engine/events.js, sparsifyPriceSeries; index.html, hydrate). The change is only
 * acceptable if no rendered number moves, and the way that fails is quiet: a missing
 * bar or a shifted index produces a plausible fan or mark, not an error.
 *
 * Every comparison below is EXACT. Values are serialised with NaN, -0, Infinity,
 * undefined and array holes kept distinct, and the strings must match byte for byte.
 *
 *   1. EQUALITY ON REAL DATA. The last results written in the full format (commit PIN)
 *      are rendered twice with the page's own code: once as shipped, once after the
 *      engine's sparsifyPriceSeries and the page's hydrate(). Per card: credibility(),
 *      liveStatus(), the all-episode fan, the prior-episode fan the live monitor is
 *      judged against, the fan chart SVG and its latest-instance path, the live panel
 *      and the whole card HTML. Then the Overview, status table and KPI row. Both runs
 *      read the same Monte Carlo draws, which is why this compares a pinned file
 *      rather than two engine runs.
 *   2. THE LIVE PAYLOAD. events_results.json as it stands is checked for shape, for
 *      each episode's idx landing on the bar dated as that episode, and for coverage.
 *      It is then rendered with every missing bar booby-trapped, so any read of a bar
 *      the payload does not ship throws instead of passing unseen.
 *   3. THE CARRY PATH. CI cannot see the Norgate inputs and carries those cards
 *      forward from the previous results. The engine is run for real against a staged
 *      data directory holding no local-only inputs, with the pinned full-format file as
 *      the previous results, and every carried card must come out compact and render
 *      exactly as the original did.
 *
 * Two negative controls prove the harness can fail: a single dropped bar must throw,
 * and a single value moved by 1e-9 must be caught by the equality check.
 *
 * Run: node tests/test_payload_trim.js [--dump DIR]
 *      --dump writes before.json and after.json (the per-card results compared in
 *      part 1) for inspection.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');
const ENGINE = path.join(ROOT, 'engine', 'events.js');
const {
  sparsifyPriceSeries, expandPriceSeries, compactCarriedCard,
  FAN_DAYS, CHG_BARS, LOCAL_ONLY_TICKERS, requiredTickers,
} = require(ENGINE);

// The last commit whose events_results.json carries the full series on every card.
const PIN = '7c96fdd';
// Rendering reads Date.now() for the staleness note; hold it still so two renders a
// millisecond apart cannot straddle a day boundary.
const FIXED_NOW = Date.parse('2026-09-29T12:00:00Z');

const argv = process.argv.slice(2);
const dumpDir = argv.includes('--dump') ? argv[argv.indexOf('--dump') + 1] : null;

const checks = [];
const add = (name, ok, detail) => checks.push({ name, ok: !!ok, detail: detail || '' });

// ---------- exact serialisation ----------
const canon = v => JSON.stringify(v, (k, x) => {
  if (typeof x === 'number') {
    if (Number.isNaN(x)) return '__NaN';
    if (Object.is(x, -0)) return '__-0';
    if (!Number.isFinite(x)) return x > 0 ? '__Inf' : '__-Inf';
  }
  return x === undefined ? '__undef' : x;
});
const clone = o => JSON.parse(JSON.stringify(o));
const isDaily = ev => ev.cadence !== 'monthly';

// ---------- the page's own code ----------
// The whole <script> block of index.html runs in a sandbox, minus the boot() call that
// would fetch and paint. Nothing is paraphrased, so the test cannot drift from the page.
function loadPage() {
  const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) throw new Error('could not find the script block in index.html');
  const src = m[1].replace(/\nboot\(\);\s*$/, '\n');
  if (src === m[1]) throw new Error('could not strip the boot() call from index.html');
  const ctx = vm.createContext({});
  vm.runInContext(src, ctx);
  vm.runInContext(`Date.now = () => ${FIXED_NOW};`, ctx);
  for (const fn of ['hydrate', 'credibility', 'liveStatus', 'buildFan', 'fanChart',
                    'livePanel', 'renderEvent', 'renderOverview', 'statusTable', 'summaryCards'])
    if (typeof ctx[fn] !== 'function') throw new Error(`index.html no longer defines ${fn}()`);
  return ctx;
}
const page = loadPage();
const setData = data => { page.__in = data; vm.runInContext('DATA = __in;', page); };

// Everything the page shows that depends on the price series, per card and page-wide.
function renderAll(data) {
  setData(data);
  const cards = {};
  for (const ev of data.events) {
    const fanHtml = page.fanChart(ev);
    cards[ev.id] = {
      credibility: canon(page.credibility(ev)),
      liveStatus: canon(page.liveStatus(ev)),
      fanAll: canon(ev.fan || page.buildFan(ev)),
      fanPrior: canon(ev.fanLatest ? ev.fanPrior : page.buildFan(ev, true)),
      fanChart: fanHtml,
      fanLatestPath: canon(vm.runInContext('FAN && FAN.latest', page)),
      livePanel: page.livePanel(ev),
      card: page.renderEvent(ev, data),
    };
  }
  return {
    cards,
    overview: page.renderOverview(data),
    statusTable: page.statusTable(data),
    summaryCards: page.summaryCards(),
  };
}

// Same payload, with every hole in every hydrated series booby-trapped: each unshipped
// bar becomes an object that throws on ANY property read, so `ps[i].ac`, `.d`, `.ind`
// or a field added later all fail loudly. Shipped bars stay plain objects, which keeps
// the render at native speed (a Proxy over the whole array made this test 100x slower).
function trap(data) {
  for (const ev of data.events) {
    const ps = ev.priceSeries;
    if (!Array.isArray(ps)) continue;
    for (let i = 0; i < ps.length; i++) {
      if (i in ps) continue;
      const msg = `${ev.id}: the page read bar ${i}, which the payload does not ship`;
      ps[i] = new Proxy({}, { get() { throw new Error(msg); } });
    }
  }
  return data;
}

// What the engine now writes for a card that used to carry the full series.
function compactLikeEngine(ev) {
  if (!isDaily(ev)) return ev;
  const { priceSeries, ...rest } = ev;
  return { ...rest, priceSeriesSparse: sparsifyPriceSeries(priceSeries, ev.episodes) };
}

// Count outputs that differ; `quiet` for the negative controls, which are meant to.
function compareRenders(label, a, b, quiet) {
  let diffs = 0;
  const note = what => { diffs++; if (!quiet) console.error(`  DIFF ${label} ${what}`); };
  for (const id of Object.keys(a.cards))
    for (const key of Object.keys(a.cards[id]))
      if (a.cards[id][key] !== b.cards[id][key]) note(`${id}.${key}`);
  for (const key of ['overview', 'statusTable', 'summaryCards'])
    if (a[key] !== b[key]) note(key);
  return diffs;
}

const kb = n => (n / 1024).toFixed(1) + 'KB';
const bytes = o => Buffer.byteLength(JSON.stringify(o));

// ============ 1. exact equality on the pinned full-format results ============
let pinned;
try {
  pinned = JSON.parse(execFileSync('git', ['show', `${PIN}:events_results.json`],
    { cwd: ROOT, maxBuffer: 64 * 1024 * 1024, encoding: 'utf8' }));
} catch (e) {
  console.error(`FATAL: cannot read events_results.json at ${PIN} — this test needs git history ` +
                `(a full clone), because the pinned file is its reference. ${e.message}`);
  process.exit(1);
}
const pinnedDaily = pinned.events.filter(isDaily);
add(`pinned ${PIN} carries a full priceSeries on every daily card`,
    pinnedDaily.length >= 8 && pinnedDaily.every(ev => Array.isArray(ev.priceSeries)),
    `${pinnedDaily.length} daily cards`);

const full = page.hydrate(clone(pinned));                   // a no-op: already full
const compact = { ...clone(pinned), events: clone(pinned).events.map(compactLikeEngine) };
const compactBytes = bytes(compact);
const compactHydrated = page.hydrate(clone(compact));

// The page's hydrate and the engine's expandPriceSeries must build the same array,
// holes in the same places.
let expandMismatch = 0;
for (const ev of compact.events.filter(isDaily)) {
  const node = expandPriceSeries(ev.priceSeriesSparse);
  const web = compactHydrated.events.find(e => e.id === ev.id).priceSeries;
  if (canon(node) !== canon(web) || Object.keys(node).join() !== Object.keys(web).join()) expandMismatch++;
}
add('index.html hydrate() and engine expandPriceSeries() build identical arrays', expandMismatch === 0);

// Every kept bar is the full series' bar at the same position, and positions agree
// with the episode dates.
let posMismatch = 0;
for (const ev of compactHydrated.events.filter(isDaily)) {
  const src = pinned.events.find(e => e.id === ev.id).priceSeries;
  if (ev.priceSeries.length !== src.length) posMismatch++;
  for (const i of Object.keys(ev.priceSeries)) if (canon(ev.priceSeries[i]) !== canon(src[i])) posMismatch++;
  for (const e of ev.episodes) if (e.idx != null && ev.priceSeries[e.idx].d !== e.date) posMismatch++;
}
add('every kept bar equals the full series at the same index, episodes land on their dates',
    posMismatch === 0, `${posMismatch} mismatches`);

const before = renderAll(full);
const after = renderAll(trap(compactHydrated));
const diffs = compareRenders('pinned', before, after);
add('every card and the Overview render identically from the full and the compact series',
    diffs === 0, `${diffs} differing outputs`);

// Non-vacuity: the comparison must have exercised the paths that read the series.
const liveCards = pinnedDaily.filter(ev => { const s = page.liveStatus(ev); return s && s.live; });
const dormantCards = pinnedDaily.filter(ev => { const s = page.liveStatus(ev); return s && !s.live; });
add('the pinned set includes a live daily card (liveStatus reads the tail)', liveCards.length >= 1,
    liveCards.map(e => e.id).join(', '));
add('the pinned set includes a dormant daily card (liveStatus reads a multi-year tail)',
    dormantCards.length >= 1, dormantCards.map(e => e.id).join(', '));

console.log(`\nPart 1 — ${PIN}: payload ${kb(bytes(pinned))} -> ${kb(compactBytes)}`);
for (const ev of pinned.events) {
  const c = compact.events.find(e => e.id === ev.id);
  const s = page.liveStatus(ev), cr = page.credibility(ev);
  const kept = c.priceSeriesSparse
    ? c.priceSeriesSparse.segments.reduce((a, g) => a + g.ac.length, 0) : ev.priceSeries.length;
  console.log(`  ${ev.id.padEnd(34)} ${kb(bytes(ev)).padStart(8)} -> ${kb(bytes(c)).padStart(8)}` +
              `  bars ${String(ev.priceSeries.length).padStart(5)} -> ${String(kept).padStart(5)}` +
              `  ${cr.action.toUpperCase()} ${cr.total}/10` +
              `  ${s ? (s.live ? `live k=${s.k} mtm=${(s.mtm * 100).toFixed(2)}%` : `dormant k=${s.k}`) : 'no live read'}`);
}

if (dumpDir) {
  fs.mkdirSync(dumpDir, { recursive: true });
  fs.writeFileSync(path.join(dumpDir, 'before.json'), JSON.stringify(before, null, 1));
  fs.writeFileSync(path.join(dumpDir, 'after.json'), JSON.stringify(after, null, 1));
  console.log(`  dumps written to ${dumpDir}`);
}

// ---------- negative controls: the harness has to be able to fail ----------
{
  const ev = compact.events.find(e => isDaily(e) && e.episodes.length >= 3);
  const broken = clone(compact);
  const bev = broken.events.find(e => e.id === ev.id);
  const seg = bev.priceSeriesSparse.segments[0];
  seg.d.pop(); seg.ac.pop(); seg.ind.pop();            // drop one bar the fan reads
  let threw = false;
  try { renderAll(trap(page.hydrate(broken))); } catch (e) { threw = /does not ship/.test(e.message); }
  add('negative control: a single dropped bar throws', threw, ev.id);

  // The final bar sets liveStatus's mark on every card that has an episode, so moving
  // it by 1e-9 must show up in that card's outputs.
  const nudged = clone(compact);
  const nsegs = nudged.events.find(e => e.id === ev.id).priceSeriesSparse.segments;
  const last = nsegs[nsegs.length - 1];
  last.ac[last.ac.length - 1] += 1e-9;
  const nd = compareRenders('control', before, renderAll(trap(page.hydrate(nudged))), true);
  add('negative control: a value moved by 1e-9 is detected', nd > 0, `${nd} outputs moved`);
}

// ============ 2. the live payload as committed ============
const live = JSON.parse(fs.readFileSync(path.join(ROOT, 'events_results.json'), 'utf8'));
const liveDaily = live.events.filter(isDaily);
add('no daily card in events_results.json ships the full series',
    liveDaily.every(ev => !Array.isArray(ev.priceSeries) && ev.priceSeriesSparse),
    liveDaily.filter(ev => Array.isArray(ev.priceSeries)).map(e => e.id).join(', '));

let shapeErrs = [];
for (const ev of liveDaily) {
  const sp = ev.priceSeriesSparse;
  if (!sp) continue;
  const n = sp.length;
  const kept = new Set();
  let prevEnd = -1;
  for (const s of sp.segments) {
    const m = s.ac.length;
    if (!(s.start > prevEnd)) shapeErrs.push(`${ev.id}: segment at ${s.start} overlaps or abuts its predecessor`);
    if (s.d.length !== m || s.ind.length !== m) shapeErrs.push(`${ev.id}: ragged columns at ${s.start}`);
    for (let j = 0; j < m; j++) kept.add(s.start + j);
    prevEnd = s.start + m;
  }
  if (prevEnd !== n) shapeErrs.push(`${ev.id}: last segment ends at ${prevEnd}, series length is ${n}`);
  const idxs = ev.episodes.map(e => e.idx).filter(i => i != null);
  const need = new Set();
  for (const i of idxs) for (let k = 0; k <= FAN_DAYS && i + k < n; k++) need.add(i + k);
  if (idxs.length) for (let i = idxs[idxs.length - 1]; i < n; i++) need.add(i);
  for (let i = Math.max(0, n - 1 - CHG_BARS); i < n; i++) need.add(i);
  const missing = [...need].filter(i => !kept.has(i));
  if (missing.length) shapeErrs.push(`${ev.id}: ${missing.length} required bars absent, first ${missing[0]}`);
  let ps;
  try { ps = expandPriceSeries(sp); } catch (e) { shapeErrs.push(`${ev.id}: ${e.message}`); continue; }
  for (const e of ev.episodes)
    if (e.idx != null && (!ps[e.idx] || ps[e.idx].d !== e.date))
      shapeErrs.push(`${ev.id}: episode ${e.date} idx ${e.idx} lands on ${ps[e.idx] ? ps[e.idx].d : 'a hole'}`);
}
for (const e of shapeErrs) console.error('  ' + e);
add('live payload: segments well formed, every required bar present, episodes on their dates',
    shapeErrs.length === 0, `${shapeErrs.length} problems`);

let liveRenderErr = null;
try { renderAll(trap(page.hydrate(clone(live)))); } catch (e) { liveRenderErr = e.message; }
add('live payload renders every card and the Overview without reading an unshipped bar',
    liveRenderErr === null, liveRenderErr || '');

// ============ 3. the CI carry path, run for real ============
{
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'es-carry-'));
  try {
    const dataDir = path.join(tmp, 'data');
    fs.mkdirSync(dataDir);
    // SPY is the one input every run needs (the regime map and the daily window). A
    // two-bar stand-in is enough: no card here is recomputed, so nothing reads it.
    fs.writeFileSync(path.join(dataDir, 'SPY.json'), JSON.stringify({
      dailyStart: '2026-09-25', lastDate: '2026-09-28',
      daily: [{ d: '2026-09-25', ac: 1 }, { d: '2026-09-28', ac: 1 }],
    }));
    // Stage exactly the cards CI must carry: those whose every input is local-only and
    // which have a pinned result to carry.
    const cat = JSON.parse(fs.readFileSync(path.join(ROOT, 'catalogue', 'catalogue.json'), 'utf8'));
    const pinnedIds = new Set(pinned.events.map(e => e.id));
    const carryCat = { ...cat, events: cat.events.filter(ev => ev.rationale && pinnedIds.has(ev.id) &&
      requiredTickers(ev).every(tk => LOCAL_ONLY_TICKERS.has(tk))) };
    const catFile = path.join(tmp, 'catalogue.json');
    fs.writeFileSync(catFile, JSON.stringify(carryCat));
    const outFile = path.join(tmp, 'events_results.json');
    fs.writeFileSync(outFile, JSON.stringify(pinned));   // the "previous results"
    const runEngine = () => execFileSync(process.execPath, [ENGINE], {
      cwd: ROOT, stdio: 'pipe', encoding: 'utf8',
      env: { ...process.env, EVENTS_DATA_DIR: dataDir, EVENTS_CATALOGUE: catFile, EVENTS_OUT: outFile },
    });

    runEngine();
    const carriedRun = JSON.parse(fs.readFileSync(outFile, 'utf8'));
    const carried = carriedRun.events;
    const carriedDaily = carried.filter(isDaily);
    add('carry run: every staged card was carried, none recomputed',
        carried.length === carryCat.events.length && carried.every(e => e.carriedForward === true),
        `${carried.length} of ${carryCat.events.length} carried`);
    add('carry run: carried daily cards come out compact',
        carriedDaily.length >= 1 && carriedDaily.every(e => !e.priceSeries && e.priceSeriesSparse),
        `${carriedDaily.length} daily cards carried`);
    add('carry run: carried monthly cards keep their full series untouched',
        carried.filter(e => !isDaily(e)).every(e => canon(e.priceSeries) ===
          canon(pinned.events.find(p => p.id === e.id).priceSeries)));

    // The original full-series cards with the same carry flags and the same run-level
    // fields, so the only difference left is the price-series format.
    const reference = { ...clone(carriedRun),
      events: carried.map(c => ({ ...clone(pinned.events.find(p => p.id === c.id)),
        carriedForward: c.carriedForward, carriedFrom: c.carriedFrom, carriedReason: c.carriedReason })) };
    const cd = compareRenders('carry', renderAll(page.hydrate(reference)),
                              renderAll(trap(page.hydrate(clone(carriedRun)))));
    add('carry run: carried cards render exactly as the originals did', cd === 0, `${cd} differing outputs`);

    // A second carry, from a file that is already compact, must change nothing.
    runEngine();
    const again = JSON.parse(fs.readFileSync(outFile, 'utf8'));
    const seriesOf = e => canon(e.priceSeriesSparse || e.priceSeries);
    const firstById = new Map(carried.map(c => [c.id, seriesOf(c)]));
    add('carry run: carrying an already-compact card leaves its series byte-identical',
        again.events.length === carried.length && again.events.every(e => firstById.get(e.id) === seriesOf(e)));
    add('compactCarriedCard returns a compact card unchanged',
        carriedDaily.every(e => compactCarriedCard(e) === e));
  } catch (e) {
    add('carry run: the engine completed', false, (e.stderr || e.message || '').toString().trim().slice(0, 400));
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

let failed = 0;
console.log('');
for (const c of checks) {
  if (!c.ok) failed++;
  console.log(`${c.ok ? 'PASS' : 'FAIL'}  ${c.name}${c.detail ? '  (' + c.detail + ')' : ''}`);
}
console.log(failed === 0 ? `\nALL GREEN — ${checks.length} checks` : `\n${failed} of ${checks.length} FAILED`);
process.exit(failed === 0 ? 0 : 1);
