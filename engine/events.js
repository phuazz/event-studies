// events.js — SentimentTrader-style event scenario engine.
//
// Reads history/<ticker>.json (produced by fetch_history.js) and, for each
// pre-registered event in events/catalogue.json, finds every historical
// trigger date, measures the forward-return distribution at fixed horizons,
// and compares it to the unconditional baseline. Writes events_results.json,
// which the "Event Studies" tab of index.html renders.
//
// Run: node events.js
//
// ----------------------------------------------------------------------------
// The three ways this study is silently wrong, stated before the code (per the
// vault prompting convention), and the countermeasure for each:
//
//   1. Pseudo-replication from overlapping forward windows. "47 triggers" with
//      a 3-month forward window, when triggers cluster in a few volatile
//      episodes, is really a handful of independent observations. Countermeasure:
//      triggers within `clusterDays` collapse to one EPISODE; we headline the
//      episode count, and the significance test is a random-entry Monte Carlo
//      that resamples real overlapping windows of the same sample size, so the
//      null carries the same overlap structure as the conditional sample.
//
//   2. Look-ahead in the indicator. RSI/SMA/breadth at date t must use only
//      data through t. We compute every indicator causally and enter at the
//      close of the trigger day (the close that defines the signal) — the
//      conventional event-study timing. This is mildly optimistic versus the
//      backtest's firstDayT1 fill; it is documented on the card, not hidden.
//
//   3. Multiple testing. Scanning many event x horizon cells and surfacing the
//      green ones manufactures false positives. We record how many cells were
//      screened in the output so the dashboard can show the multiple-testing
//      context; a catalogue event without a written rationale is not admitted.
// ----------------------------------------------------------------------------

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const CATALOGUE = process.env.EVENTS_CATALOGUE || path.join(__dirname, '..', 'catalogue', 'catalogue.json');
const UNIVERSES = path.join(__dirname, '..', 'universes.json');
const OUT = process.env.EVENTS_OUT || path.join(__dirname, '..', 'events_results.json');

// Forward-return horizons in TRADING days (not calendar days — we index into
// the bar array, which sidesteps all weekday/holiday date arithmetic).
const HORIZONS = [5, 10, 21, 42, 63, 126, 252];
const HORIZON_LABELS = ['1W', '2W', '1M', '2M', '3M', '6M', '1Y'];

const BOOT_ITERS = 2000;

// ---------- small stats helpers ----------

function mean(a) { return a.length ? a.reduce((s, x) => s + x, 0) / a.length : NaN; }

function quantile(arr, q) {
  if (!arr.length) return NaN;
  const a = arr.slice().sort((x, y) => x - y);
  const pos = (a.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  if (lo === hi) return a[lo];
  return a[lo] + (a[hi] - a[lo]) * (pos - lo);
}

function median(a) { return quantile(a, 0.5); }

function hitRate(a) { return a.length ? a.filter(x => x > 0).length / a.length : NaN; }

function randInt(n) { return Math.floor(Math.random() * n); }

// ---------- indicators (all causal) ----------

// Wilder's RSI over `period` bars on a value series. Returns an array aligned
// to `vals`, with the first `period` entries null (not yet defined).
function rsiWilder(vals, period) {
  const out = new Array(vals.length).fill(null);
  if (vals.length <= period) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = vals[i] - vals[i - 1];
    if (d >= 0) gain += d; else loss -= d;
  }
  let avgGain = gain / period, avgLoss = loss / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < vals.length; i++) {
    const d = vals[i] - vals[i - 1];
    const g = d > 0 ? d : 0, l = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

// Trailing simple moving average; out[i] uses vals[i-period+1 .. i] inclusive.
function sma(vals, period) {
  const out = new Array(vals.length).fill(null);
  let run = 0;
  for (let i = 0; i < vals.length; i++) {
    run += vals[i];
    if (i >= period) run -= vals[i - period];
    if (i >= period - 1) out[i] = run / period;
  }
  return out;
}

// Trailing rolling maximum over `win` bars inclusive; out[i] uses vals[i-win+1..i].
// Entries before the window is full (or with nulls in range) are null.
function rollingMax(vals, win) {
  const out = new Array(vals.length).fill(null);
  for (let i = win - 1; i < vals.length; i++) {
    let m = -Infinity, ok = true;
    for (let k = i - win + 1; k <= i; k++) {
      if (vals[k] == null) { ok = false; break; }
      if (vals[k] > m) m = vals[k];
    }
    out[i] = ok ? m : null;
  }
  return out;
}

// Trailing rolling minimum over `win` bars inclusive; out[i] uses vals[i-win+1..i].
function rollingMin(vals, win) {
  const out = new Array(vals.length).fill(null);
  for (let i = win - 1; i < vals.length; i++) {
    let m = Infinity, ok = true;
    for (let k = i - win + 1; k <= i; k++) {
      if (vals[k] == null) { ok = false; break; }
      if (vals[k] < m) m = vals[k];
    }
    out[i] = ok ? m : null;
  }
  return out;
}

// ---------- data loading ----------

function loadTicker(tk) {
  const f = path.join(DATA_DIR, `${tk}.json`);
  if (!fs.existsSync(f)) throw new Error(`data/${tk}.json not found — run scripts/fetch_history.js`);
  return JSON.parse(fs.readFileSync(f, 'utf8'));
}

// Global risk regime indicator (methodology §7.4): SPY above its 200-day SMA.
// Returned as a map from ISO date -> true/false for every SPY daily bar where
// the 200-day SMA is defined.
function buildRegime(spy) {
  const ac = spy.daily.map(b => b.ac);
  const s200 = sma(ac, 200);
  const map = {};
  for (let i = 0; i < spy.daily.length; i++) {
    if (s200[i] != null) map[spy.daily[i].d] = ac[i] > s200[i];
  }
  return map;
}

// ---------- trigger detection ----------
//
// Each event produces a boolean trigger on an "indicator series" that shares a
// date axis with the "target series" whose forward returns we measure. For a
// single-asset event the two are the same ticker; for a breadth event the
// indicator is the breadth series and the target is SPY.

// SPY RSI goes from overbought (>70) to below 50 within `window` trading days.
// Trigger fires on the day RSI crosses below 50, provided RSI exceeded 70
// within the preceding `window` bars.
function detectRsiOverboughtToMid(target, ev) {
  const ac = target.daily.map(b => b.ac);
  const dates = target.daily.map(b => b.d);
  const rsi = rsiWilder(ac, ev.rsiPeriod || 14);
  const win = ev.window || 3;
  const triggers = [];
  for (let i = 1; i < rsi.length; i++) {
    if (rsi[i] == null || rsi[i - 1] == null) continue;
    // moment of crossing below 50
    if (!(rsi[i] < 50 && rsi[i - 1] >= 50)) continue;
    // was overbought within the preceding `win` bars?
    let wasOB = false;
    for (let k = 1; k <= win; k++) {
      if (i - k >= 0 && rsi[i - k] != null && rsi[i - k] > 70) { wasOB = true; break; }
    }
    if (wasOB) triggers.push(i);
  }
  return { dates, ac, triggers, indicator: rsi, indicatorName: `RSI(${ev.rsiPeriod || 14})` };
}

// Cross-asset breadth: share of the universe trading above its own 200-day SMA,
// computed on SPY's date axis. Trigger fires when breadth crosses below `level`.
function detectBreadthCross(spy, ev, universe) {
  const level = ev.level != null ? ev.level : 0.5;
  const minNames = ev.minNames || 20;

  // Per-ticker map: date -> (ac > its trailing 200d SMA), only where defined.
  const aboveByTk = {};
  for (const tk of universe) {
    let h;
    try { h = loadTicker(tk); } catch (e) { continue; }
    const ac = h.daily.map(b => b.ac);
    const s200 = sma(ac, 200);
    const m = {};
    for (let i = 0; i < h.daily.length; i++) {
      if (s200[i] != null) m[h.daily[i].d] = ac[i] > s200[i];
    }
    aboveByTk[tk] = m;
  }

  // Breadth on SPY's axis.
  const dates = spy.daily.map(b => b.d);
  const ac = spy.daily.map(b => b.ac);
  const breadth = new Array(dates.length).fill(null);
  for (let i = 0; i < dates.length; i++) {
    const d = dates[i];
    let above = 0, total = 0;
    for (const tk of universe) {
      const m = aboveByTk[tk];
      if (m && d in m) { total++; if (m[d]) above++; }
    }
    if (total >= minNames) breadth[i] = above / total;
  }

  const triggers = [];
  for (let i = 1; i < breadth.length; i++) {
    if (breadth[i] == null || breadth[i - 1] == null) continue;
    if (breadth[i] < level && breadth[i - 1] >= level) triggers.push(i);
  }
  // Express breadth as a 0-100 series for display, consistent with RSI scale.
  return { dates, ac, triggers, indicator: breadth.map(b => b == null ? null : +(b * 100).toFixed(1)), indicatorName: '% > 200d SMA' };
}

// New-highs-into-thinning-breadth divergence. The target makes repeated 1-year
// highs while cross-asset participation (% of the universe above its own 200-day
// SMA) has rolled over from its own trailing-1-year peak. The trigger fires on
// the ONSET of the combined condition; forward returns are measured on the
// target. This is our OWN cross-asset construct — it deliberately substitutes
// cross-asset breadth for any single-market internal breadth, and imports no
// external study's numbers. Significance comes from analyseEvent's Monte Carlo.
function detectNewHighBreadthDivergence(target, ev, universe) {
  const dates = target.daily.map(b => b.d);
  const ac = target.daily.map(b => b.ac);

  const nhLookback = ev.newHighLookback || 252;
  const nhWindow = ev.newHighWindow || 30;
  const nhMinCount = ev.newHighMinCount || 9;
  const brPeakLookback = ev.breadthPeakLookback || 252;
  const brDrop = (ev.breadthDropPP != null ? ev.breadthDropPP : 15) / 100;
  const minNames = ev.minNames || 30;

  // 1-year-high flag: target close at/above its trailing nhLookback max.
  const trailMax = rollingMax(ac, nhLookback);
  const is1yrHigh = ac.map((v, i) => trailMax[i] == null ? null : (v >= trailMax[i] - 1e-9));

  // Count of 1-year-high days within the trailing nhWindow sessions.
  const nhCount = new Array(ac.length).fill(null);
  for (let i = nhWindow - 1; i < ac.length; i++) {
    let c = 0, ok = true;
    for (let k = i - nhWindow + 1; k <= i; k++) {
      if (is1yrHigh[k] == null) { ok = false; break; }
      if (is1yrHigh[k]) c++;
    }
    if (ok) nhCount[i] = c;
  }

  // Cross-asset breadth on the TARGET's date axis: % of universe above own 200d.
  const aboveByTk = {};
  for (const tk of universe) {
    let h; try { h = loadTicker(tk); } catch (e) { continue; }
    const a = h.daily.map(b => b.ac);
    const s2 = sma(a, 200);
    const m = {};
    for (let i = 0; i < h.daily.length; i++) if (s2[i] != null) m[h.daily[i].d] = a[i] > s2[i];
    aboveByTk[tk] = m;
  }
  const breadth = new Array(dates.length).fill(null);
  for (let i = 0; i < dates.length; i++) {
    const d = dates[i];
    let above = 0, total = 0;
    for (const tk of universe) { const m = aboveByTk[tk]; if (m && d in m) { total++; if (m[d]) above++; } }
    if (total >= minNames) breadth[i] = above / total;
  }

  // Breadth divergence: breadth sits brDrop below its own trailing-1-year peak.
  const brPeak = rollingMax(breadth, brPeakLookback);
  const diverging = breadth.map((b, i) => (b == null || brPeak[i] == null) ? null : (b <= brPeak[i] - brDrop));

  // Combined condition, fired on onset (true today, not true yesterday).
  const cond = dates.map((_, i) =>
    nhCount[i] != null && nhCount[i] >= nhMinCount && diverging[i] === true);
  const triggers = [];
  for (let i = 1; i < dates.length; i++) if (cond[i] && !cond[i - 1]) triggers.push(i);

  return {
    dates, ac, triggers,
    indicator: breadth.map(b => b == null ? null : +(b * 100).toFixed(1)),
    indicatorName: '% > 200d SMA (cross-asset)'
  };
}

// Oversold washout inside a downtrend: the target's RSI crosses below
// `oversoldLevel` while it trades below its `smaPeriod`-day SMA. A mean-reversion
// ("buy the washout") trigger — deliberately COUNTER-trend, outside this
// scanner's trend-following spine. Forward returns measured on the target.
function detectOversoldReversionInDowntrend(target, ev) {
  const ac = target.daily.map(b => b.ac);
  const dates = target.daily.map(b => b.d);
  const rsi = rsiWilder(ac, ev.rsiPeriod || 14);
  const s = sma(ac, ev.smaPeriod || 200);
  const lvl = ev.oversoldLevel != null ? ev.oversoldLevel : 30;
  const triggers = [];
  for (let i = 1; i < ac.length; i++) {
    if (rsi[i] == null || rsi[i - 1] == null || s[i] == null) continue;
    // RSI crosses below the oversold level, with the close already below the SMA.
    if (rsi[i] < lvl && rsi[i - 1] >= lvl && ac[i] < s[i]) triggers.push(i);
  }
  return { dates, ac, triggers, indicator: rsi, indicatorName: `RSI(${ev.rsiPeriod || 14})` };
}

// Momentum thrust out of a multi-month low (the SentimenTrader coffee study,
// now testable on a single-commodity instrument): a `rocWindow`-day rate of
// change above `thrustPct` while the instrument also printed a `lowLookback`-day
// low within the trailing `lowWithin` sessions. Their thesis is a bull trap, so
// the interesting forward returns are the 2-6 month negatives — our Monte Carlo
// judges it, not their printed numbers.
function detectMomentumThrustFrom252dLow(target, ev) {
  const ac = target.daily.map(b => b.ac);
  const dates = target.daily.map(b => b.d);
  const rocWin = ev.rocWindow || 5;
  const thr = (ev.thrustPct != null ? ev.thrustPct : 13) / 100;
  const lowLook = ev.lowLookback || 252;
  const lowWithin = ev.lowWithin || 21;

  const roc = ac.map((v, i) => i >= rocWin ? (v / ac[i - rocWin] - 1) : null);
  const trailMin = rollingMin(ac, lowLook);
  const is252Low = ac.map((v, i) => trailMin[i] == null ? null : (v <= trailMin[i] + 1e-9));
  const lowRecent = new Array(ac.length).fill(false);
  for (let i = 0; i < ac.length; i++) {
    for (let k = Math.max(0, i - lowWithin + 1); k <= i; k++) {
      if (is252Low[k]) { lowRecent[i] = true; break; }
    }
  }
  const triggers = [];
  for (let i = 1; i < ac.length; i++) {
    if (roc[i] == null || roc[i - 1] == null) continue;
    if (roc[i] > thr && roc[i - 1] <= thr && lowRecent[i]) triggers.push(i);
  }
  return { dates, ac, triggers, indicator: roc.map(r => r == null ? null : +(r * 100).toFixed(1)), indicatorName: `${rocWin}d RoC %` };
}

// Collapse triggers whose forward windows overlap into one episode. We keep the
// FIRST trigger of each cluster; any later trigger within `clusterDays` bars of
// the cluster's anchor is absorbed.
function clusterEpisodes(triggers, clusterDays) {
  const eps = [];
  let anchor = -Infinity;
  for (const t of triggers) {
    if (t - anchor > clusterDays) { eps.push(t); anchor = t; }
  }
  return eps;
}

// ---------- forward-return analysis ----------

function analyseEvent(series, ev, regimeMap) {
  const { dates, ac, triggers } = series;
  const clusterDays = ev.clusterDays != null ? ev.clusterDays : 10;
  const episodes = clusterEpisodes(triggers, clusterDays);

  // Baseline: unconditional overlapping forward returns per horizon.
  const baseFwd = {};
  for (const h of HORIZONS) {
    const arr = [];
    for (let i = 0; i + h < ac.length; i++) arr.push(ac[i + h] / ac[i] - 1);
    baseFwd[h] = arr;
  }

  // Per-horizon conditional stats + significance.
  const byHorizon = HORIZONS.map((h, hi) => {
    const fwd = [], mfe = [], mae = [];
    for (const idx of episodes) {
      if (idx + h >= ac.length) continue;
      fwd.push(ac[idx + h] / ac[idx] - 1);
      let hi2 = -Infinity, lo2 = Infinity;
      for (let k = 1; k <= h; k++) {
        const r = ac[idx + k] / ac[idx] - 1;
        if (r > hi2) hi2 = r;
        if (r < lo2) lo2 = r;
      }
      mfe.push(hi2); mae.push(lo2);
    }
    const n = fwd.length;
    const base = baseFwd[h];
    const condMedian = median(fwd);

    // Random-entry Monte Carlo: draw n start indices uniformly from the valid
    // range, take the median forward return, repeat. The null inherits the same
    // overlap structure and sample size as the conditional set, so the p-value
    // is not inflated by pseudo-replication.
    let ge = 0;
    const nullMedians = [];
    const maxStart = ac.length - h;
    if (n > 0 && maxStart > 0) {
      for (let b = 0; b < BOOT_ITERS; b++) {
        const draws = [];
        for (let j = 0; j < n; j++) draws.push(base[randInt(maxStart)]);
        const m = median(draws);
        nullMedians.push(m);
        if (m >= condMedian) ge++;
      }
    }
    const pTwoSided = n > 0 ? 2 * Math.min(ge, BOOT_ITERS - ge) / BOOT_ITERS : NaN;
    const percentile = n > 0 ? 1 - ge / BOOT_ITERS : NaN; // where the conditional median sits in the null

    // CI on the conditional median by resampling episodes with replacement.
    let ciLo = NaN, ciHi = NaN;
    if (n > 1) {
      const meds = [];
      for (let b = 0; b < BOOT_ITERS; b++) {
        const s = [];
        for (let j = 0; j < n; j++) s.push(fwd[randInt(n)]);
        meds.push(median(s));
      }
      ciLo = quantile(meds, 0.05); ciHi = quantile(meds, 0.95);
    }

    return {
      h, label: HORIZON_LABELS[hi], n,
      mean: mean(fwd), median: condMedian, hit: hitRate(fwd),
      mfeMedian: median(mfe), maeMedian: median(mae),
      baseMean: mean(base), baseMedian: median(base), baseHit: hitRate(base),
      edgeMedian: condMedian - median(base),
      ciLo, ciHi, pValue: pTwoSided, percentile
    };
  });

  // Episode list with per-horizon forward returns + regime tag, for the table
  // and the signal map.
  const episodeRows = episodes.map(idx => {
    const fwd = {};
    for (const h of HORIZONS) fwd[h] = idx + h < ac.length ? +( (ac[idx + h] / ac[idx] - 1) * 100).toFixed(2) : null;
    const d = dates[idx];
    return { date: d, idx, regime: d in regimeMap ? (regimeMap[d] ? 'on' : 'off') : null, fwd };
  });

  const onCount = episodeRows.filter(e => e.regime === 'on').length;
  const offCount = episodeRows.filter(e => e.regime === 'off').length;

  // Downsample target + indicator series for the signal map (keep every bar —
  // ~2,500 points is fine, but round to keep the JSON compact).
  const priceSeries = dates.map((d, i) => ({ d, ac: +ac[i].toFixed(2), ind: series.indicator[i] == null ? null : +series.indicator[i].toFixed(1) }));

  return {
    nTriggers: triggers.length,
    nEpisodes: episodes.length,
    clusterDays,
    firstDate: episodes.length ? dates[episodes[0]] : null,
    lastDate: episodes.length ? dates[episodes[episodes.length - 1]] : null,
    regimeSplit: { on: onCount, off: offCount, untagged: episodeRows.length - onCount - offCount },
    indicatorName: series.indicatorName,
    byHorizon,
    episodes: episodeRows,
    priceSeries
  };
}

// ---------- monthly seasonal analysis ----------
//
// A different signal CLASS from the daily kinds above: an ANNUAL seasonal signal
// measured on a month-end price series. It emits the SAME standard event shape
// (byHorizon / episodes / priceSeries) so the existing renderer works, but on
// MONTHLY horizons (3/6/9/12 months) rather than trading-day horizons. Each
// year's June signal is 12 months apart while the forward window is <= 12 months
// and consecutive years do not overlap on the 9-month headline, so every signal
// is its own episode (clusterDays 0).

// JS Date months are 0-INDEXED (January === 0). `month1` here is 1-indexed (the
// human convention, matching the ISO month substring '06' === June). Returns a
// 1-indexed {year, month1}. Using day-of-month 1 avoids month-length overflow.
function addMonths(year, month1, n) {
  const d = new Date(Date.UTC(year, (month1 - 1) + n, 1)); // (month1-1) converts to 0-indexed for Date
  return { year: d.getUTCFullYear(), month1: d.getUTCMonth() + 1 };
}

// Edge-case asserts for the forward-month mapping the seasonal study relies on
// (vault date-handling rule: assert a month boundary and a year boundary).
function assertSeasonalDateLogic() {
  const yb = addMonths(2020, 6, 9);   // June 2020 + 9m -> March 2021 (YEAR boundary)
  if (!(yb.year === 2021 && yb.month1 === 3)) throw new Error('date logic: June+9m != next March');
  const iy = addMonths(2020, 6, 3);   // June 2020 + 3m -> September 2020 (intra-year)
  if (!(iy.year === 2020 && iy.month1 === 9)) throw new Error('date logic: June+3m != September');
  const mb = addMonths(2020, 10, 3);  // October 2020 + 3m -> January 2021 (month + year boundary)
  if (!(mb.year === 2021 && mb.month1 === 1)) throw new Error('date logic: Oct+3m != next January');
}

// Strong 2nd quarter (April-June) -> forward return on the price index. A June
// month-end signal fires when the S&P 500 either rose in each of April, May and
// June (three consecutive up months) and/or gained >= q2GainThreshold from the
// end of March to the end of June. Forward returns are measured on the monthly
// price index from the June close; 9M (June -> the following March) is the
// headline. Baseline = all overlapping monthly h-month returns; significance
// from the same random-entry Monte Carlo as the daily kinds, on monthly bars.
function analyseSeasonalStrongQuarter(target, ev) {
  assertSeasonalDateLogic();
  if (!target.monthly || !target.monthly.length)
    throw new Error(`${ev.target}: no monthly series (seasonal signal needs month-end closes)`);

  const bars = target.monthly;
  const dates = bars.map(b => b.d);
  const ac = bars.map(b => b.ac);
  const N = ac.length;

  const forwardMonths = ev.forwardMonths || [3, 6, 9, 12];
  const labels = forwardMonths.map(h => `${h}M`);
  const q2Thr = ev.q2GainThreshold != null ? ev.q2GainThreshold : 0.10;
  const smaMonths = ev.regimeSmaMonths || 10;

  // Month-index map keyed by 'YYYY-MM' (the ISO month substring is 1-indexed).
  const idxByYm = {};
  for (let i = 0; i < N; i++) idxByYm[dates[i].slice(0, 7)] = i;

  // Regime tag from the GSPC monthly series ITSELF (a 10-month SMA), not SPY daily.
  const smaMonthly = sma(ac, smaMonths);

  // One candidate per year with Mar/Apr/May/Jun month-end closes present.
  const years = [...new Set(dates.map(d => +d.slice(0, 4)))].sort((a, b) => a - b);
  const signals = []; // { idx: June bar index, year, q2, up3 }
  for (const Y of years) {
    const iM = idxByYm[`${Y}-03`], iA = idxByYm[`${Y}-04`], iMy = idxByYm[`${Y}-05`], iJ = idxByYm[`${Y}-06`];
    if (iM == null || iA == null || iMy == null || iJ == null) continue;
    const cM = ac[iM], cA = ac[iA], cMy = ac[iMy], cJ = ac[iJ];
    const up3 = cA > cM && cMy > cA && cJ > cMy;
    const q2 = cJ / cM - 1;
    if (up3 || q2 >= q2Thr) signals.push({ idx: iJ, year: Y, q2, up3 });
  }
  const episodes = signals.map(s => s.idx); // each signal is its own episode

  // Runtime tie-out on the FIRST completed signal: a June + 9-month forward bar
  // must be dated to the following March (ties the abstract date math to data).
  if (forwardMonths.includes(9)) {
    for (const s of signals) {
      if (s.idx + 9 < N) {
        const fd = dates[s.idx + 9], exp = addMonths(s.year, 6, 9);
        if (+fd.slice(0, 4) !== exp.year || +fd.slice(5, 7) !== exp.month1)
          throw new Error(`seasonal forward tie-out: ${dates[s.idx]} +9m -> ${fd}, expected ${exp.year}-${String(exp.month1).padStart(2, '0')}`);
        break;
      }
    }
  }

  // Baseline: all overlapping monthly h-month returns.
  const baseFwd = {};
  for (const h of forwardMonths) {
    const arr = [];
    for (let i = 0; i + h < N; i++) arr.push(ac[i + h] / ac[i] - 1);
    baseFwd[h] = arr;
  }

  const byHorizon = forwardMonths.map((h, hi) => {
    const fwd = [], mfe = [], mae = [];
    for (const idx of episodes) {
      if (idx + h >= N) continue;
      fwd.push(ac[idx + h] / ac[idx] - 1);
      let hiR = -Infinity, loR = Infinity;
      for (let k = 1; k <= h; k++) {
        const r = ac[idx + k] / ac[idx] - 1;
        if (r > hiR) hiR = r;
        if (r < loR) loR = r;
      }
      mfe.push(hiR); mae.push(loR);
    }
    const n = fwd.length;
    const base = baseFwd[h];
    const condMedian = median(fwd);

    // Random-entry Monte Carlo, monthly overlapping windows, same n.
    let ge = 0;
    const maxStart = N - h;
    if (n > 0 && maxStart > 0) {
      for (let b = 0; b < BOOT_ITERS; b++) {
        const draws = [];
        for (let j = 0; j < n; j++) draws.push(base[randInt(maxStart)]);
        if (median(draws) >= condMedian) ge++;
      }
    }
    const pTwoSided = n > 0 ? 2 * Math.min(ge, BOOT_ITERS - ge) / BOOT_ITERS : NaN;
    const percentile = n > 0 ? 1 - ge / BOOT_ITERS : NaN;

    // CI on the conditional median by resampling episodes with replacement.
    let ciLo = NaN, ciHi = NaN;
    if (n > 1) {
      const meds = [];
      for (let b = 0; b < BOOT_ITERS; b++) {
        const s = [];
        for (let j = 0; j < n; j++) s.push(fwd[randInt(n)]);
        meds.push(median(s));
      }
      ciLo = quantile(meds, 0.05); ciHi = quantile(meds, 0.95);
    }

    return {
      h, label: labels[hi], n,
      mean: mean(fwd), median: condMedian, hit: hitRate(fwd),
      mfeMedian: median(mfe), maeMedian: median(mae),
      baseMean: mean(base), baseMedian: median(base), baseHit: hitRate(base),
      edgeMedian: condMedian - median(base),
      ciLo, ciHi, pValue: pTwoSided, percentile
    };
  });

  // Episode rows with per-horizon forward returns (%) + regime tag.
  const episodeRows = signals.map(s => {
    const idx = s.idx;
    const fwd = {};
    for (const h of forwardMonths) fwd[h] = idx + h < N ? +((ac[idx + h] / ac[idx] - 1) * 100).toFixed(2) : null;
    const regime = smaMonthly[idx] == null ? null : (ac[idx] > smaMonthly[idx] ? 'on' : 'off');
    return { date: dates[idx], idx, regime, fwd };
  });
  const onCount = episodeRows.filter(e => e.regime === 'on').length;
  const offCount = episodeRows.filter(e => e.regime === 'off').length;

  // priceSeries: monthly bars; `ind` = the trailing Q2 return % at every June
  // bar (signal or not), else null — the indicator behind the signal.
  const q2AtJune = {};
  for (const Y of years) {
    const iM = idxByYm[`${Y}-03`], iJ = idxByYm[`${Y}-06`];
    if (iM != null && iJ != null) q2AtJune[iJ] = +((ac[iJ] / ac[iM] - 1) * 100).toFixed(1);
  }
  const priceSeries = bars.map((b, i) => ({ d: b.d, ac: +ac[i].toFixed(2), ind: i in q2AtJune ? q2AtJune[i] : null }));

  // ---- Range-of-outcomes fan on DAILY bars ----
  // The monthly series is too coarse for a drawdown envelope, so the fan is
  // built on daily bars: anchor each June signal at its LAST daily bar in June,
  // then aggregate cumulative-return percentiles + running-min drawdown across
  // episodes over 252 trading days. This is the exact logic of index.html's
  // buildFan, precomputed here (so the payload stays lean and the chart matches
  // the daily tabs). 9M (~189 trading days) sits inside the 1Y window.
  let fan = null, fanLatest = null;
  const daily = target.daily || [];
  if (daily.length > 60) {
    const dac = daily.map(b => b.ac);
    const juneAnchor = {}; // year -> last daily-bar index in that June
    for (let i = 0; i < daily.length; i++) {
      const ym = daily[i].d.slice(0, 7);
      if (ym.slice(5, 7) === '06') juneAnchor[+ym.slice(0, 4)] = i; // sorted -> keeps the last June bar
    }
    const anchors = signals.map(s => juneAnchor[s.year]).filter(a => a != null);
    const rnd4 = x => +x.toFixed(4);
    fan = [{ k: 0, n: anchors.length, p10: 0, p25: 0, p50: 0, p75: 0, p90: 0, mn: 0, mx: 0, ddMed: 0, ddBad: 0 }];
    for (let k = 1; k <= 252; k++) {
      const rets = [], dds = [];
      for (const a of anchors) {
        if (a + k >= dac.length) continue;
        const b0 = dac[a];
        rets.push(dac[a + k] / b0 - 1);
        let lo = 0;
        for (let j = 1; j <= k; j++) { const r = dac[a + j] / b0 - 1; if (r < lo) lo = r; }
        dds.push(lo);
      }
      if (rets.length < 3) break;
      fan.push({
        k, n: rets.length,
        p10: rnd4(quantile(rets, 0.1)), p25: rnd4(quantile(rets, 0.25)), p50: rnd4(quantile(rets, 0.5)),
        p75: rnd4(quantile(rets, 0.75)), p90: rnd4(quantile(rets, 0.9)),
        mn: rnd4(Math.min(...rets)), mx: rnd4(Math.max(...rets)),
        ddMed: rnd4(quantile(dds, 0.5)), ddBad: rnd4(quantile(dds, 0.1))
      });
    }
    const lastSig = signals[signals.length - 1];
    const aL = lastSig ? juneAnchor[lastSig.year] : null;
    if (aL != null) {
      const path = [];
      for (let k = 0; aL + k < dac.length && k <= 252; k++) path.push({ k, v: rnd4(dac[aL + k] / dac[aL] - 1) });
      fanLatest = { date: dates[lastSig.idx], path };
    }
  }

  return {
    nTriggers: signals.length,
    nEpisodes: episodes.length,
    clusterDays: 0,
    firstDate: episodes.length ? dates[episodes[0]] : null,
    lastDate: episodes.length ? dates[episodes[episodes.length - 1]] : null,
    regimeSplit: { on: onCount, off: offCount, untagged: episodeRows.length - onCount - offCount },
    indicatorName: 'Q2 return %',
    byHorizon,
    episodes: episodeRows,
    priceSeries,
    fan, fanLatest
  };
}

// ---------- main ----------

function main() {
  if (!fs.existsSync(CATALOGUE)) throw new Error(`catalogue not found at ${CATALOGUE}`);
  const cat = JSON.parse(fs.readFileSync(CATALOGUE, 'utf8'));
  const spy = loadTicker('SPY');
  const regimeMap = buildRegime(spy);

  // Multi-universe: resolve the catalogue's default universe from universes.json.
  // Breadth events may name their own `breadthUniverse`; single-target events
  // (RSI, oversold) do not use the universe at all.
  const universesCfg = fs.existsSync(UNIVERSES) ? JSON.parse(fs.readFileSync(UNIVERSES, 'utf8')) : { universes: {} };
  const resolveUniverse = (name) => {
    const u = universesCfg.universes && universesCfg.universes[name];
    return u && u.tickers ? u.tickers.map(x => x.t) : [];
  };
  const universe = resolveUniverse(cat.defaultUniverse || 'core');

  const out = {
    generatedAt: new Date().toISOString(),
    dailyWindow: { start: spy.dailyStart, end: spy.lastDate },
    horizons: HORIZONS,
    horizonLabels: HORIZON_LABELS,
    nEventsScreened: cat.events.length,
    nHorizonsScreened: HORIZONS.length,
    multipleTestingNote:
      `${cat.events.length} pre-registered event(s) x ${HORIZONS.length} horizons = ` +
      `${cat.events.length * HORIZONS.length} cells screened. P-values are NOT corrected for ` +
      `multiple testing; treat a single green cell among many as weak evidence.`,
    events: []
  };

  for (const ev of cat.events) {
    if (!ev.rationale) { console.warn(`SKIP ${ev.id}: no rationale (not admitted to the catalogue).`); continue; }
    console.log(`Analysing ${ev.id} (${ev.kind})...`);

    // Monthly seasonal kind: emits the standard shape on monthly horizons, then
    // skips the daily analyseEvent path entirely (its own dispatch + push).
    if (ev.kind === 'seasonal_strong_quarter') {
      const target = loadTicker(ev.target);
      const res = analyseSeasonalStrongQuarter(target, ev);
      out.events.push({
        id: ev.id, name: ev.name, kind: ev.kind,
        target: ev.target, cadence: 'monthly',
        // The horizon the THESIS is stated over (9 months here) — the denominator
        // the live monitor measures progress against. Distinct from the 1Y fan span.
        thesisHorizonDays: ev.thesisHorizonDays || null,
        rationale: ev.rationale, definition: ev.definition,
        entryNote: 'Forward return measured on the monthly price index from the June month-end close (event-study convention).',
        ...res
      });
      console.log(`  ${res.nTriggers} triggers -> ${res.nEpisodes} episodes (regime on/off: ${res.regimeSplit.on}/${res.regimeSplit.off})`);
      continue;
    }

    let series;
    if (ev.kind === 'rsi_ob_to_mid') {
      series = detectRsiOverboughtToMid(loadTicker(ev.target), ev);
    } else if (ev.kind === 'breadth_cross') {
      series = detectBreadthCross(spy, ev, universe);
    } else if (ev.kind === 'newhigh_breadth_divergence') {
      series = detectNewHighBreadthDivergence(loadTicker(ev.target), ev, universe);
    } else if (ev.kind === 'oversold_reversion_in_downtrend') {
      series = detectOversoldReversionInDowntrend(loadTicker(ev.target), ev);
    } else if (ev.kind === 'momentum_thrust_from_252d_low') {
      series = detectMomentumThrustFrom252dLow(loadTicker(ev.target), ev);
    } else {
      console.warn(`SKIP ${ev.id}: unknown kind ${ev.kind}`); continue;
    }
    const res = analyseEvent(series, ev, regimeMap);
    out.events.push({
      id: ev.id, name: ev.name, kind: ev.kind,
      target: ev.target || 'SPY', rationale: ev.rationale, definition: ev.definition,
      // The horizon the THESIS is stated over (e.g. a multi-week snap-back for a
      // washout) — the denominator the live monitor measures progress against,
      // NOT the 1Y fan span.
      thesisHorizonDays: ev.thesisHorizonDays || null,
      entryNote: 'Forward return measured from the close of the trigger day (event-study convention).',
      ...res
    });
    console.log(`  ${res.nTriggers} triggers -> ${res.nEpisodes} independent episodes (regime on/off: ${res.regimeSplit.on}/${res.regimeSplit.off})`);
  }

  fs.writeFileSync(OUT, JSON.stringify(out));
  console.log(`\nWrote ${OUT} (${(fs.statSync(OUT).size / 1024).toFixed(1)} KB) — ${out.events.length} event(s).`);
}

if (require.main === module) {
  try { main(); } catch (e) { console.error('Fatal:', e.message); process.exit(1); }
}

module.exports = { rsiWilder, sma, clusterEpisodes, HORIZONS, HORIZON_LABELS };
