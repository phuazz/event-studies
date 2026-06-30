// fetch_history.js — Pulls full price history (daily + monthly) for the ETF universe.
// Output: history/<TICKER>.json, one per ticker.
// Run: node fetch_history.js [--max-age-hours=168]   (default 168h = weekly cadence)
//
// Why a separate script: the daily snapshot (data.json) only carries
// short windows; the backtest needs full inception-to-now history with
// dividend-adjusted closes. Refresh weekly is plenty since we backtest
// on monthly bars.
//
// See BACKTEST_METHODOLOGY.md §3 for what we fetch and why.

const https = require('https');
const fs = require('fs');
const path = require('path');

// Universe is config-driven: read ../universes.json and fetch the UNION of all
// tickers across the declared universes. This keeps the fetch in lockstep with
// the catalogue as instruments are added — no hardcoded list.
const UNIVERSES = path.join(__dirname, '..', 'universes.json');
const UNI = (() => {
  const cfg = JSON.parse(fs.readFileSync(UNIVERSES, 'utf8'));
  const seen = new Set(), out = [];
  for (const u of Object.values(cfg.universes || {})) {
    for (const tk of (u.tickers || [])) {
      if (seen.has(tk.t)) continue;
      seen.add(tk.t);
      out.push({ t: tk.t, n: tk.n, c: tk.cls || tk.c || '' });
    }
  }
  return out;
})();

const ARG_MAX_AGE = (() => {
  const m = process.argv.find(a => a.startsWith('--max-age-hours='));
  return m ? parseFloat(m.split('=')[1]) : 168; // 1 week default
})();

const HISTORY_DIR = path.join(__dirname, '..', 'data');

// ---------- Yahoo fetch ----------

function yfFetch(tk, range, interval) {
  return new Promise((resolve, reject) => {
    // NOTE: We previously appended &events=div|split here, but Yahoo's v8
    // chart endpoint has been observed to return total-return-adjusted prices
    // in the `close` field (alongside `adjclose`) when that parameter is
    // present, which corrupts our return calculations. Stripping it returns
    // raw close prices in the standard convention.
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${tk}?range=${range}&interval=${interval}&includePrePost=false`;
    const options = {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' }
    };
    https.get(url, options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const j = JSON.parse(data);
          const result = j.chart && j.chart.result && j.chart.result[0];
          if (!result) reject(new Error('No data for ' + tk));
          else resolve(result);
        } catch (e) { reject(e); }
      });
      res.on('error', reject);
    }).on('error', reject);
  });
}

async function yfRetry(tk, range, interval, retries = 3) {
  let lastErr;
  for (let i = 0; i < retries; i++) {
    try { return await yfFetch(tk, range, interval); }
    catch (e) { lastErr = e; if (i < retries - 1) await sleep(1500 + i * 1200); }
  }
  throw lastErr;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- Bar extraction ----------
//
// Yahoo's chart payload has parallel arrays:
//   timestamp:                [t0, t1, ...]
//   indicators.quote[0]:      open/high/low/close/volume arrays
//   indicators.adjclose[0]:   { adjclose: [...] }  <-- split + dividend adjusted
//
// We pair them up and drop any bar where adjclose is null/0 (Yahoo's way
// of marking holidays/halts that crept into the array).

function extractBars(result) {
  const ts = result.timestamp || [];
  const q = (result.indicators.quote && result.indicators.quote[0]) || {};
  const adj = (result.indicators.adjclose && result.indicators.adjclose[0]
               && result.indicators.adjclose[0].adjclose) || q.close || [];
  const out = [];
  for (let i = 0; i < ts.length; i++) {
    const c = q.close ? q.close[i] : null;
    const ac = adj[i];
    if (c == null || ac == null || ac <= 0 || c <= 0) continue;
    out.push({
      // ISO date (UTC midnight is fine for a daily/monthly bar)
      d: new Date(ts[i] * 1000).toISOString().slice(0, 10),
      o: round4(q.open ? q.open[i] : null),
      h: round4(q.high ? q.high[i] : null),
      l: round4(q.low ? q.low[i] : null),
      c: round4(c),
      ac: round4(ac),
      v: q.volume ? q.volume[i] : null
    });
  }
  return out;
}

function round4(x) { return x == null ? null : +(+x).toFixed(4); }

// ---------- Sanity filter ----------
// Drop or flag pathological bars. See methodology §3.5.

function sanitize(bars, ticker) {
  const flagged = [];
  for (let i = 1; i < bars.length; i++) {
    const r = bars[i].ac / bars[i - 1].ac - 1;
    if (Math.abs(r) > 0.5) {
      flagged.push({ d: bars[i].d, ret: +r.toFixed(4) });
    }
  }
  if (flagged.length) {
    console.warn(`  ${ticker}: ${flagged.length} bars with |ret| > 50% (kept; verify if suspicious):`,
      flagged.slice(0, 3));
  }
  return bars;
}

// ---------- Per-ticker pipeline ----------

async function fetchOne(entry) {
  const dir = HISTORY_DIR;
  const file = path.join(dir, `${entry.t}.json`);

  // Skip if recently refreshed
  if (fs.existsSync(file)) {
    const ageHours = (Date.now() - fs.statSync(file).mtimeMs) / 3.6e6;
    if (ageHours < ARG_MAX_AGE) {
      return { ticker: entry.t, status: 'skipped', age: +ageHours.toFixed(1) };
    }
  }

  // Daily bars: Yahoo silently downsamples to monthly cadence when you ask
  // for range=max with interval=1d. Use range=10y instead — that's what the
  // 60-day rolling vol estimator needs anyway, and it gives true ~2500 bars
  // per ticker with full daily granularity.
  const dRes = await yfRetry(entry.t, '10y', '1d');
  const dailyBars = sanitize(extractBars(dRes), entry.t);
  await sleep(350);

  // Monthly bars (max history) — used by all monthly signals. range=max works
  // correctly for interval=1mo and gives true inception-to-now history.
  const mRes = await yfRetry(entry.t, 'max', '1mo');
  const monthlyBars = sanitize(extractBars(mRes), entry.t);

  // Daily-bar floor: 60 days minimum so the trailing-vol estimator works.
  // Newer ETFs may legitimately have fewer than the 10y cap of true daily bars.
  if (dailyBars.length < 60) throw new Error(`only ${dailyBars.length} daily bars`);
  // Still require at least 13 monthly bars (for 12-1 momentum + 1-month buffer).
  if (monthlyBars.length < 13) throw new Error(`only ${monthlyBars.length} monthly bars`);

  const meta = mRes.meta || dRes.meta || {};
  const out = {
    ticker: entry.t,
    name: entry.n,
    cls: entry.c,
    fetchedAt: new Date().toISOString(),
    // True inception comes from monthly bars (daily is now capped at 10y).
    inception: monthlyBars[0].d,
    dailyStart: dailyBars[0].d,
    lastDate: dailyBars[dailyBars.length - 1].d,
    nDaily: dailyBars.length,
    nMonthly: monthlyBars.length,
    currency: meta.currency || null,
    exchange: meta.exchangeName || null,
    daily: dailyBars,
    monthly: monthlyBars
  };

  fs.writeFileSync(file, JSON.stringify(out));
  return {
    ticker: entry.t, status: 'ok',
    inception: out.inception, nDaily: out.nDaily, nMonthly: out.nMonthly,
    sizeKB: +(fs.statSync(file).size / 1024).toFixed(1)
  };
}

// ---------- Main ----------

async function main() {
  if (!fs.existsSync(HISTORY_DIR)) fs.mkdirSync(HISTORY_DIR, { recursive: true });

  console.log(`[${new Date().toISOString()}] Fetching history for ${UNI.length} tickers (max-age ${ARG_MAX_AGE}h)...`);
  const results = [];
  const fails = [];

  for (let i = 0; i < UNI.length; i++) {
    const e = UNI[i];
    try {
      const r = await fetchOne(e);
      results.push(r);
      if (r.status === 'skipped') {
        console.log(`  [${i + 1}/${UNI.length}] ${e.t} skipped (age ${r.age}h)`);
      } else {
        console.log(`  [${i + 1}/${UNI.length}] ${e.t} OK — ${r.nDaily} daily, ${r.nMonthly} monthly, since ${r.inception} (${r.sizeKB} KB)`);
      }
    } catch (err) {
      fails.push({ ticker: e.t, error: err.message });
      console.warn(`  [${i + 1}/${UNI.length}] ${e.t} FAILED — ${err.message}`);
    }
    if (i < UNI.length - 1) await sleep(500);
  }

  // Manifest
  const manifest = {
    fetchedAt: new Date().toISOString(),
    total: UNI.length,
    ok: results.filter(r => r.status === 'ok').length,
    skipped: results.filter(r => r.status === 'skipped').length,
    failed: fails,
    tickers: results.map(r => ({ ticker: r.ticker, inception: r.inception, status: r.status }))
  };
  fs.writeFileSync(path.join(HISTORY_DIR, '_manifest.json'), JSON.stringify(manifest, null, 2));

  console.log(`\nDone. ok=${manifest.ok} skipped=${manifest.skipped} failed=${manifest.failed.length}`);
  if (fails.length > UNI.length * 0.5) { console.error('More than 50% failed — aborting.'); process.exit(1); }
}

if (require.main === module) main().catch(err => { console.error('Fatal:', err); process.exit(1); });

module.exports = { UNI, HISTORY_DIR, fetchOne, extractBars, sanitize };
