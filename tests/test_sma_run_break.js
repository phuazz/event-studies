#!/usr/bin/env node
/* test_sma_run_break.js — guards detectFirstCloseBelowSmaAfterRun and the matched
 * (uptrend-only) baseline that analyseEvent runs when a detector supplies one.
 *
 * Synthetic data only: the real target (GSPC) is Norgate-sourced and never in CI.
 *
 * Run: node tests/test_sma_run_break.js
 */
const assert = require('assert');
const { detectFirstCloseBelowSmaAfterRun, analyseEvent, sma } = require('../engine/events.js');

function series(closes) {
  const d0 = Date.UTC(2000, 0, 3);
  return { daily: closes.map((ac, i) => ({ d: new Date(d0 + i * 864e5).toISOString().slice(0, 10), ac })) };
}

// 1. Long climb, then a sharp drop: exactly one trigger, on the first close not above.
{
  const c = [];
  for (let i = 0; i < 600; i++) c.push(100 * Math.pow(1.001, i));
  for (let i = 0; i < 30; i++) c.push(c[c.length - 1] * 0.97);
  const ev = { smaPeriod: 200, minRunDays: 150 };
  const r = detectFirstCloseBelowSmaAfterRun(series(c), ev);
  const s = sma(c, 200);
  const first = c.findIndex((v, i) => i >= 600 && s[i] != null && v <= s[i]);
  assert.deepStrictEqual(r.triggers, [first], 'one trigger, at the first close at/below the SMA');
  assert.ok(r.runLength[first - 1] >= 150, 'prior run met the threshold');
  assert.ok(r.matchedBaselineIdx.every(j => r.runLength[j] >= 150), 'matched baseline = mature-run days');
  assert.ok(!r.matchedBaselineIdx.includes(first), 'the trigger day is not in its own baseline');
}

// 2. Run too short: no trigger.
{
  const c = [];
  for (let i = 0; i < 200; i++) c.push(100);            // flat: SMA defined, close == SMA, no run
  for (let i = 0; i < 100; i++) c.push(100 + i * 0.5);  // 100-day run
  for (let i = 0; i < 20; i++) c.push(50);
  const r = detectFirstCloseBelowSmaAfterRun(series(c), { minRunDays: 150 });
  assert.deepStrictEqual(r.triggers, [], 'a 100-day run must not fire a 150-day rule');
  const r2 = detectFirstCloseBelowSmaAfterRun(series(c), { minRunDays: 90 });
  assert.strictEqual(r2.triggers.length, 1, 'the same run fires a 90-day rule');
}

// 3. Causal: triggers found on a truncated history equal those on the full history.
{
  const c = [];
  let v = 100, seed = 42;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;  // seeded LCG
  for (let i = 0; i < 6000; i++) { v *= 1 + 0.0004 + 0.02 * (rnd() - 0.5); c.push(v); }
  const full = detectFirstCloseBelowSmaAfterRun(series(c), { minRunDays: 60 }).triggers;
  assert.ok(full.length >= 2, `need triggers to test causality (got ${full.length})`);
  for (const cut of [1500, 3000, 4500]) {
    const part = detectFirstCloseBelowSmaAfterRun(series(c.slice(0, cut)), { minRunDays: 60 }).triggers;
    assert.deepStrictEqual(part, full.filter(t => t < cut), `no look-ahead at cut ${cut}`);
  }

  // 4. analyseEvent emits matched-baseline fields only when the detector supplies them.
  const ser = detectFirstCloseBelowSmaAfterRun(series(c), { minRunDays: 60 });
  const withM = analyseEvent(ser, { clusterDays: 63 }, {});
  const h63 = withM.byHorizon.find(b => b.h === 63);
  for (const k of ['matchedBaseHit', 'matchedBaseMedian', 'matchedPValue', 'matchedPValueHit', 'matchedEdgeHit'])
    assert.ok(Number.isFinite(h63[k]), `${k} present`);
  const { matchedBaselineIdx, ...plain } = ser;
  const without = analyseEvent(plain, { clusterDays: 63 }, {});
  assert.ok(!('matchedBaseHit' in without.byHorizon[0]), 'other cards unchanged');
}

console.log('test_sma_run_break: all assertions passed');
