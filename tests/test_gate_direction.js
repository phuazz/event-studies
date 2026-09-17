#!/usr/bin/env node
/* test_gate_direction.js — guards the direction-aware credibility gate.
 *
 * WHY THIS EXISTS. Until 2026-09-17 `credibility()` assumed every study predicted the
 * target RISING: it scanned only horizons with `edgeMedian > 0` for its best p-value,
 * and scored consistency as the share of horizons with a positive edge. A study whose
 * finding is that the target FALLS therefore scored zero on both components. The live
 * spx-first-policy-hike card would have rendered IGNORE 1/10 beside its own strongest
 * cell (1M, -4.63pp, p=0.023).
 *
 * The fix reads `ev.direction` ('up' | 'down') from the CATALOGUE. Two properties have
 * to hold together, and this file exists to keep both:
 *
 *   1. NO REGRESSION — every 'up' card scores exactly what it scored before.
 *   2. NO SIGN-FISHING — direction is declared, never inferred. If the gate ever
 *      started reading the sign off the results it would keep whichever direction
 *      scored better, silently doubling the multiple-testing surface of every card.
 *
 * Run: node tests/test_gate_direction.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const src = html.match(/function credibility\(ev\)\{[\s\S]*?\n\}/);
if (!src) { console.error('FATAL: could not extract credibility() from index.html'); process.exit(1); }
eval(src[0]);

/* The gate exactly as it stood before the 2026-09-17 direction fix. Kept verbatim so
 * the regression check compares against real prior behaviour, not a paraphrase. */
function gateBeforeFix(ev) {
  const bh = ev.byHorizon || [], at = l => bh.find(r => r.label === l) || {};
  const sample = ev.nEpisodes >= 12 ? 2 : ev.nEpisodes >= 6 ? 1 : 0;
  let bestP = 1;
  for (const r of bh) if (r.edgeMedian > 0 && r.pValue != null && !Number.isNaN(r.pValue) && r.pValue < bestP) bestP = r.pValue;
  const signif = bestP < 0.05 ? 2 : bestP < 0.10 ? 1 : 0;
  const m = at('3M'), mfe = m.mfeMedian, mae = m.maeMedian;
  const tail = (mfe != null && mae != null && mae < 0) ? (mfe > -mae * 1.3 ? 2 : mfe > -mae ? 1 : 0) : (mfe > 0 ? 1 : 0);
  const on = (ev.regimeSplit && ev.regimeSplit.on) || 0, off = (ev.regimeSplit && ev.regimeSplit.off) || 0;
  const regime = Math.min(on, off) >= 2 ? 2 : Math.min(on, off) >= 1 ? 1 : 0;
  const pos = bh.length ? bh.filter(r => r.edgeMedian > 0).length / bh.length : 0;
  const consistency = pos >= 0.7 ? 2 : pos >= 0.5 ? 1 : 0;
  let total = sample + signif + tail + regime + consistency;
  let action = total >= 7 ? 'act' : total >= 5 ? 'monitor' : 'ignore';
  if (signif === 0 && action === 'act') action = 'monitor';
  if (ev.nEpisodes < 4) action = 'ignore';
  if (ev.gateOverride) {
    const ORD = { act: 2, monitor: 1, ignore: 0 };
    if (ORD[ev.gateOverride] != null && ORD[ev.gateOverride] < ORD[action]) action = ev.gateOverride;
  }
  return { total, action };
}

const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'events_results.json'), 'utf8'));
const checks = [];
const add = (name, ok, detail) => checks.push({ name, ok, detail: detail || '' });

/* 1. Every 'up' card must be untouched by the fix. */
const ups = data.events.filter(e => e.direction !== 'down');
let drift = 0;
for (const ev of ups) {
  const a = gateBeforeFix(ev), b = credibility(ev);
  if (a.total !== b.total || a.action !== b.action) {
    drift++;
    console.error(`  DRIFT ${ev.id}: was ${a.action} ${a.total}/10, now ${b.action} ${b.total}/10`);
  }
}
add(`all ${ups.length} 'up' cards score exactly as before the fix`, drift === 0);
add(`the book still contains 'up' cards to regress against`, ups.length >= 5, `${ups.length} found`);

/* 2. The live 'down' card is scored on its declared direction, not on a positive edge. */
const downs = data.events.filter(e => e.direction === 'down');
for (const ev of downs) {
  const before = gateBeforeFix(ev), after = credibility(ev);
  const bestCell = (ev.byHorizon || []).filter(r => r.edgeMedian < 0 && r.pValue != null)
    .reduce((m, r) => (!m || r.pValue < m.pValue ? r : m), null);
  console.log(`  ${ev.id}: pre-fix ${before.action} ${before.total}/10 -> ${after.action} ${after.total}/10 ` +
              `(best negative cell ${bestCell ? bestCell.label + ' ' + bestCell.edgeMedian.toFixed(4) + ' p=' + bestCell.pValue.toFixed(3) : 'none'})`);
  add(`${ev.id}: significance scores off the declared direction`, after.breakdown.Significance > 0,
      `Significance ${after.breakdown.Significance}/2`);
  add(`${ev.id}: consistency scores off the declared direction`, after.breakdown.Consistency > 0,
      `Consistency ${after.breakdown.Consistency}/2`);
  add(`${ev.id}: bestP is the true lowest p among cells in its direction`,
      bestCell != null && Math.abs(after.bestP - bestCell.pValue) < 1e-9);
  add(`${ev.id}: the fix actually changed its standing`, after.total > before.total);
  add(`${ev.id}: credibility() exposes dir for the display layer`, after.dir === -1);
}
add('at least one down card is live (otherwise this file guards nothing)', downs.length >= 1);

/* 3. Direction must NEVER be inferred from the numbers. Feeding the same negative-edge
 *    card in with no declared direction has to reproduce the old, blind score. */
for (const ev of downs) {
  const undeclared = { ...ev };
  delete undeclared.direction;
  const a = gateBeforeFix(ev), b = credibility(undeclared);
  add(`${ev.id}: omitting direction reproduces the pre-fix score (no sign-fishing)`,
      b.total === a.total && b.action === a.action, `${b.action} ${b.total}/10 vs ${a.action} ${a.total}/10`);
}

/* 4. Tail asymmetry must swap MFE/MAE for a down study, not reuse the up-study pair. */
const synth = {
  nEpisodes: 6, regimeSplit: { on: 3, off: 3 },
  byHorizon: [{ label: '3M', n: 6, edgeMedian: -6.0, pValue: 0.04, mfeMedian: 3.0, maeMedian: -11.5 }],
};
add('tail asymmetry swaps MFE/MAE for a down study',
    credibility({ ...synth, direction: 'down' }).breakdown['Tail asym'] === 2 &&
    credibility(synth).breakdown['Tail asym'] === 0);

let failed = 0;
console.log('');
for (const c of checks) {
  if (!c.ok) failed++;
  console.log(`${c.ok ? 'PASS' : 'FAIL'}  ${c.name}${c.detail ? '  (' + c.detail + ')' : ''}`);
}
console.log(failed === 0 ? `\nALL GREEN — ${checks.length} checks` : `\n${failed} of ${checks.length} FAILED`);
process.exit(failed === 0 ? 0 : 1);
