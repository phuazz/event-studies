#!/usr/bin/env python
"""build_dashboard.py — tabbed research dashboard for the US equity basket work.

Styled on the canonical vault system (C:\\dev\\design.md tokens, verbatim) and
carrying the interaction patterns from the breadth-thrust-etf dashboard:
  - charts expand to a full-screen overlay (click, or keyboard; Esc closes)
  - range selectors on long series
  - hover crosshair with a value readout
  - sortable table headers
  - expandable table rows revealing a detail panel
  - collapsible details/summary accordions for method + caveats
  - a live filter on the holdings table
  - a data-freshness / health strip

Single-theme light by vault default; background and every colour painted from
tokens so the page holds on any host ground.
Run: python private/studies/build_dashboard.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
PRIV = os.path.join(HERE, "..", "private", "studies")
D = json.load(open(os.path.join(PRIV, "basket_curves.json")))
X = json.load(open(os.path.join(PRIV, "dashboard_data.json")))
OUT = os.path.join(PRIV, "basket_dashboard.html")
U = X["universe"]

PAYLOAD = json.dumps({
    "dates": D["bench"]["dates"],
    "eq": {k: D[k]["eq"] for k in ("bench", "trend", "buffered")},
    "dd": {k: D[k]["dd"] for k in ("bench", "trend", "buffered")},
    "breadth": X["breadthHistory"],
    "coverage": X["coverage"],
    "basket": X["basket"],
    "subs": X["subIndustries"],
}, separators=(",", ":"))

SER = [("bench", "Broad basket", "--b"), ("trend", "Trend-gated", "--c"), ("buffered", "Buffered top-50", "--p")]
opt = ""
for k, lbl, tok in reversed(SER):
    d = D[k]; rec = k == "bench"
    opt += f"""<article class="card{' rec' if rec else ''}">
      <div class="ct"><span class="dot" style="background:var({tok})"></span><h3>{lbl}</h3>
      {'<span class="pill pg">default</span>' if rec else ''}</div>
      <div class="mrow"><span>Return p.a.</span><b class="mono">{d['cagr']*100:.2f}%</b></div>
      <div class="mrow"><span>Sharpe</span><b class="mono">{d['sharpe']:.2f}</b></div>
      <div class="mrow"><span>Worst fall</span><b class="mono neg">{d['mdd']*100:.1f}%</b></div>
      <div class="mrow"><span>Turnover p.a.</span><b class="mono">{d['turn']*100:.0f}%</b></div></article>"""

ERA = [("Rank top-50, quarterly", "0.68", "0.57", 1, "0.78", "0.80", 0),
       ("Buffered top-50, semi-annual", "0.71", "0.61", 1, "0.90", "0.80", 1),
       ("Trend-gated broad, semi-annual", "0.63", "0.61", 1, "0.83", "0.80", 1)]
erows = "".join(
    f'<tr><td>{n}</td><td class="mono r">{a}</td><td class="mono r sub">{b}</td>'
    f'<td><span class="pill {"pg" if c else "pr"}">{"PASS" if c else "FAIL"}</span></td>'
    f'<td class="mono r">{d}</td><td class="mono r sub">{e}</td>'
    f'<td><span class="pill {"pg" if f else "pr"}">{"PASS" if f else "FAIL"}</span></td></tr>'
    for n, a, b, c, d, e, f in ERA)
COST = [(0, 17.11, 13.32), (10, 16.61, 13.24), (25, 15.86, 13.12),
        (40, 15.11, 13.00), (50, 14.61, 12.92), (75, 13.37, 12.72)]
crows = "".join(
    f'<tr><td class="mono r">{c}</td><td class="mono r">{a:.2f}%</td><td class="mono r sub">{b:.2f}%</td>'
    f'<td class="mono r {"pos" if a-b>1 else "neg" if a-b<0.8 else ""}">{a-b:+.2f}pp</td></tr>'
    for c, a, b in COST)

html = f"""<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Basket Research Desk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>
:root{{
  --bg:#fafaf8; --bg2:#ffffff; --bg3:#f5f5f0; --bg4:#eeeee8; --bg-hover:#f0f0ea;
  --bd:#e2e0d8; --bd2:#d5d3ca; --bd-strong:#c0beb5;
  --t1:#1a1a18; --t2:#5c5c56; --t3:#8a8a82; --t4:#b0b0a8;
  --g:#1a8754; --g2:#22a366; --g-bg:rgba(26,135,84,0.07); --g-bg2:rgba(26,135,84,0.14);
  --r:#c0392b; --r2:#e74c3c; --r-bg:rgba(192,57,43,0.07); --r-bg2:rgba(192,57,43,0.14);
  --b:#2563eb; --b2:#3b82f6; --b-bg:rgba(37,99,235,0.06); --b-bg2:rgba(37,99,235,0.12);
  --a:#b45309; --a-bg:rgba(180,83,9,0.07);
  --p:#7c3aed; --p-bg:rgba(124,58,237,0.06);
  --c:#0891b2; --c-bg:rgba(8,145,178,0.06);
  --pk:#be185d; --pk-bg:rgba(190,24,93,0.06);
  --g-text:#146c43; --r-text:#a93226; --b-text:#1d4ed8; --a-text:#92400e;
}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--t1);-webkit-text-size-adjust:100%;text-size-adjust:100%;
  font-family:"DM Sans",system-ui,-apple-system,sans-serif;line-height:1.55;margin:0;
  padding:clamp(16px,3vw,30px) clamp(13px,3vw,30px)}}
.wrap{{max-width:1120px;margin:0 auto}}
h1{{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:clamp(28px,4.4vw,40px);
  margin:0;line-height:1.15}}
h2{{font-family:"Instrument Serif",Georgia,serif;font-weight:400;font-size:clamp(19px,2.5vw,24px);
  margin:0;line-height:1.2}}
h3{{font-size:14.5px;font-weight:600;margin:0}}
p{{margin:0;max-width:70ch;color:var(--t2);font-size:14px}}
.lede{{font-size:15px;max-width:66ch}}
.mono{{font-family:"JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}}
header{{border-bottom:1px solid var(--bd);padding-bottom:14px}}
.hrow{{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:baseline;justify-content:space-between}}
.stamp{{font-family:"JetBrains Mono",monospace;font-size:11.5px;color:var(--t3);line-height:1.7}}
.health{{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}}
.hchip{{display:inline-flex;align-items:center;gap:6px;background:var(--bg2);border:1px solid var(--bd);
  border-radius:20px;padding:3px 11px;font-size:11.5px;color:var(--t2);
  font-family:"JetBrains Mono",monospace}}
.hchip i{{width:6px;height:6px;border-radius:50%;background:var(--g);display:block}}
nav{{display:flex;gap:2px;overflow-x:auto;border-bottom:1px solid var(--bd);margin:14px 0 22px}}
.tab{{appearance:none;background:none;border:0;border-bottom:2px solid transparent;font-family:inherit;
  font-size:13.5px;font-weight:500;color:var(--t3);padding:9px 13px;cursor:pointer;white-space:nowrap;min-height:44px}}
.tab:hover{{color:var(--t1);background:var(--bg-hover)}}
.tab.on{{color:var(--t1);border-bottom-color:var(--t1)}}
.pane{{display:none;flex-direction:column;gap:26px}} .pane.on{{display:flex}}
section{{display:flex;flex-direction:column;gap:11px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(208px,1fr));gap:12px}}
.card{{background:var(--bg2);border:1px solid var(--bd);border-radius:4px;padding:14px 15px;
  display:flex;flex-direction:column;gap:8px}}
.card.rec{{border-color:var(--b);box-shadow:inset 3px 0 0 var(--b)}}
.ct{{display:flex;align-items:center;gap:8px}}
.dot{{width:9px;height:9px;border-radius:50%;flex:0 0 auto}}
.mrow{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;font-size:13px;
  color:var(--t2);border-bottom:1px dotted var(--bd);padding-bottom:5px}}
.mrow:last-child{{border-bottom:0;padding-bottom:0}} .mrow b{{font-size:14.5px;color:var(--t1);font-weight:600}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.kpi{{background:var(--bg2);border:1px solid var(--bd);border-radius:4px;padding:13px 14px}}
.kpi .l{{font-size:11.5px;color:var(--t3);text-transform:uppercase;letter-spacing:.06em;font-weight:600}}
.kpi .v{{font-family:"JetBrains Mono",monospace;font-size:24px;font-weight:600;line-height:1.25;margin-top:3px}}
.kpi .s{{font-size:12px;color:var(--t3)}}
/* charts */
.chead{{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;justify-content:space-between}}
.ctrl{{display:flex;gap:4px;align-items:center}}
.rb{{appearance:none;background:var(--bg2);border:1px solid var(--bd);color:var(--t2);font-family:inherit;
  font-size:11.5px;font-weight:500;padding:4px 9px;border-radius:3px;cursor:pointer;min-height:30px}}
.rb:hover{{background:var(--bg-hover);color:var(--t1)}}
.rb.on{{background:var(--t1);border-color:var(--t1);color:var(--bg2)}}
.exp{{appearance:none;background:var(--bg2);border:1px solid var(--bd);color:var(--t2);font-family:inherit;
  font-size:11.5px;font-weight:500;padding:4px 10px;border-radius:3px;cursor:pointer;min-height:30px}}
.exp:hover{{background:var(--bg-hover);color:var(--t1);border-color:var(--bd2)}}
.cw{{position:relative;background:var(--bg2);border:1px solid var(--bd);border-radius:4px;padding:8px 4px 2px}}
.cw svg{{width:100%;height:auto;display:block;touch-action:pan-y}}
.gl{{stroke:var(--bd);stroke-width:1}}
.ax{{fill:var(--t3);font-family:"JetBrains Mono",monospace;font-size:11px}}
.ln{{fill:none;stroke-width:1.8;stroke-linejoin:round;stroke-linecap:round}}
.ar{{opacity:.10}}
.cross{{stroke:var(--bd-strong);stroke-width:1;stroke-dasharray:3 3}}
.rdo{{position:absolute;top:8px;right:10px;background:var(--bg2);border:1px solid var(--bd);border-radius:3px;
  padding:6px 9px;font-family:"JetBrains Mono",monospace;font-size:11.5px;color:var(--t1);
  pointer-events:none;opacity:0;transition:opacity .12s;line-height:1.6;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.rdo.on{{opacity:1}} .rdo b{{font-weight:600}} .rdo i{{display:inline-block;width:9px;height:3px;border-radius:2px;margin-right:5px;vertical-align:middle;font-style:normal}}
.leg{{display:flex;flex-wrap:wrap;gap:7px 18px;font-size:12.5px;color:var(--t2)}}
.leg i{{display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}}
/* overlay */
.ov{{position:fixed;inset:0;background:rgba(26,26,24,.62);z-index:50;display:none;
  align-items:center;justify-content:center;padding:clamp(10px,3vw,36px)}}
.ov.on{{display:flex}}
.ovbox{{background:var(--bg2);border-radius:5px;width:100%;max-width:1200px;max-height:92vh;overflow:auto;
  padding:16px clamp(12px,2vw,20px)}}
.ovhead{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}}
.ovclose{{appearance:none;background:var(--bg3);border:1px solid var(--bd);border-radius:3px;
  font-family:inherit;font-size:12.5px;padding:6px 12px;cursor:pointer;color:var(--t1);min-height:36px}}
.ovclose:hover{{background:var(--bg-hover)}}
/* tables */
.tw{{overflow-x:auto;background:var(--bg2);border:1px solid var(--bd);border-radius:4px}}
.tw.tall{{max-height:470px;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px;min-width:440px}}
th{{position:sticky;top:0;background:var(--bg3);text-align:left;padding:8px 11px;font-size:11px;
  text-transform:uppercase;letter-spacing:.06em;color:var(--t3);font-weight:600;border-bottom:1px solid var(--bd);z-index:1}}
th.s{{cursor:pointer;user-select:none}} th.s:hover{{color:var(--t1);background:var(--bg4)}}
th.s::after{{content:'\\2195';opacity:.32;margin-left:5px;font-size:11px}}
th.s.asc::after{{content:'\\25B2';opacity:.9}} th.s.desc::after{{content:'\\25BC';opacity:.9}}
td{{padding:7px 11px;border-bottom:1px solid var(--bd)}}
tr:last-child td{{border-bottom:0}}
tbody tr.rw{{cursor:pointer}} tbody tr.rw:hover{{background:var(--bg-hover)}}
tbody tr.rw.op{{background:var(--b-bg)}}
td.r,th.r{{text-align:right}} td.sub{{color:var(--t2)}}
.pos{{color:var(--g-text)}} .neg{{color:var(--r-text)}}
.pill{{font-family:"JetBrains Mono",monospace;font-size:11px;font-weight:600;padding:2px 7px;border-radius:3px}}
.pg{{background:var(--g-bg2);color:var(--g-text)}} .pr{{background:var(--r-bg2);color:var(--r-text)}}
td.bar{{width:110px;min-width:90px}}
td.bar span{{display:block;height:7px;background:var(--g);border-radius:2px;min-width:2px}}
.det td{{background:var(--bg3);padding:13px 14px}}
.dgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:11px}}
.dbox .dl{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--t3);font-weight:600}}
.dbox .dv{{font-family:"JetBrains Mono",monospace;font-size:15px;font-weight:600;margin:2px 0 5px}}
.track{{height:6px;background:var(--bg4);border-radius:3px;overflow:hidden}}
.track span{{display:block;height:100%;border-radius:3px}}
.fbar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.fin{{appearance:none;font-family:inherit;font-size:13px;padding:7px 11px;border:1px solid var(--bd);
  border-radius:3px;background:var(--bg2);color:var(--t1);min-width:190px;min-height:38px}}
.fin:focus{{border-color:var(--b);outline:none}}
.cnt{{font-size:12.5px;color:var(--t3);font-family:"JetBrains Mono",monospace}}
/* accordion */
details{{background:var(--bg2);border:1px solid var(--bd);border-radius:4px}}
details+details{{margin-top:9px}}
summary{{cursor:pointer;list-style:none;padding:12px 15px;font-weight:600;font-size:14px;
  display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:44px}}
summary::-webkit-details-marker{{display:none}}
summary::after{{content:'Show \\25BC';font-family:"JetBrains Mono",monospace;font-size:11px;
  font-weight:500;color:var(--t3);white-space:nowrap}}
details[open]>summary::after{{content:'Hide \\25B2'}}
details[open]>summary{{border-bottom:1px solid var(--bd)}}
summary:hover{{background:var(--bg-hover)}}
.dbody{{padding:13px 15px 15px;display:flex;flex-direction:column;gap:9px}}
.note{{background:var(--b-bg);border:1px solid var(--bd);border-left:3px solid var(--b);border-radius:4px;
  padding:13px 16px;display:flex;flex-direction:column;gap:7px}}
.warn{{background:var(--a-bg);border-left-color:var(--a)}}
ul{{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;max-width:70ch;font-size:14px;color:var(--t2)}}
li::marker{{color:var(--t4)}}
.fine{{font-size:12.5px;color:var(--t3);max-width:74ch}}
footer{{border-top:1px solid var(--bd);margin-top:30px;padding-top:14px;font-size:12px;color:var(--t3)}}
:focus-visible{{outline:2px solid var(--b);outline-offset:2px}}
@media (max-width:640px){{.kpi .v{{font-size:21px}} td{{padding:7px 9px}}
  /* 44px tap floor on phones (vault MOBILE_CHECK) */
  .rb,.exp{{min-height:44px;padding:6px 12px}} .fin{{min-width:0;flex:1;min-height:44px}}
  th{{padding:12px 9px}} th.s{{padding-top:13px;padding-bottom:13px}}
  summary{{min-height:48px}}}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
</style>

<div class="wrap">
<header>
  <div class="hrow">
    <div>
      <h1>Basket Research Desk</h1>
      <p class="lede">Holding US stocks directly instead of buying an ETF &mdash; the rules, the evidence,
      and what they select today.</p>
    </div>
    <div class="stamp">AS AT {U['end']}<br>{U['index']} &middot; point-in-time<br>Net of 25bps per side</div>
  </div>
  <div class="health">
    <span class="hchip"><i></i>Panel {U['start']} &rarr; {U['end']}</span>
    <span class="hchip"><i></i>{U['months']} months</span>
    <span class="hchip"><i></i>{U['symbolsUsed']:,} symbols</span>
    <span class="hchip"><i></i>{U['records']:,} records</span>
    <span class="hchip"><i></i>{U['membersLatest']:,}/{U['liveToday']:,} members resolved</span>
    <span class="hchip" title="Names Norgate marks as removed or delisted during the latest month. They stay in the backtest — that is what point-in-time data is for — but cannot be held today."><i style="background:var(--a)"></i>{U['delistedExcluded']} delisted excluded from live view</span>
  </div>
</header>

<nav role="tablist">
  <button class="tab on" data-p="monitor">Monitor</button>
  <button class="tab" data-p="strategies">Strategies</button>
  <button class="tab" data-p="evidence">Evidence</button>
  <button class="tab" data-p="universe">Universe</button>
  <button class="tab" data-p="method">Method</button>
</nav>

<div class="pane on" id="monitor">
  <section>
    <h2>Where the market stands</h2>
    <div class="kpis">
      <div class="kpi"><div class="l">Above 200-day</div><div class="v">{U['trendPct']*100:.0f}%</div>
        <div class="s">{U['trendLatest']} of {U['liquidLatest']} liquid names</div></div>
      <div class="kpi"><div class="l">Index members</div><div class="v mono">{U['membersLatest']:,}</div>
        <div class="s">passing liquidity: {U['liquidLatest']}</div></div>
      <div class="kpi"><div class="l">Basket size</div><div class="v mono">{len(X['basket'])}</div>
        <div class="s">equal-weight, semi-annual</div></div>
      <div class="kpi"><div class="l">Sub-industries</div><div class="v mono">{len(X['subIndustries'])}</div>
        <div class="s">with 5+ liquid names</div></div>
    </div>
    <div class="chead"><h2>Market participation</h2>
      <div class="ctrl"><span class="rg" data-t="breadth"></span>
      <button class="exp" data-x="breadth">Expand &#8599;</button></div></div>
    <div class="cw" id="c-breadth"><div class="rdo"></div></div>
    <p>Participation is the most useful single read here. At {U['trendPct']*100:.0f}% above the 200-day, the
    trend filter is admitting most of the universe rather than a narrow slice. Hover the chart for any month.</p>
  </section>

  <section>
    <div class="chead"><h2>What the rules select today</h2>
      <span class="cnt" id="bcount"></span></div>
    <p>The 50 names the buffered rule holds as at {U['end']}. Click any row for the score breakdown; click a
    column heading to sort. Shown for research inspection, not as a recommendation to buy.</p>
    <p class="fine">{U['delistedExcluded']} name(s) Norgate marks as removed or delisted during {U['end']} are
    excluded here because they no longer trade. They remain in the backtest, which is precisely what
    point-in-time data is for &mdash; dropping them there would reintroduce survivorship bias.</p>
    <div class="fbar"><input class="fin" id="bfilter" type="search" placeholder="Filter ticker or sub-industry&hellip;"
      aria-label="Filter holdings"></div>
    <div class="tw tall"><table id="tbasket">
      <thead><tr>
        <th class="s" data-k="sym" data-ty="s">Ticker</th>
        <th class="s" data-k="sub" data-ty="s">Sub-industry</th>
        <th class="s r" data-k="score" data-ty="n" title="Average of the momentum and inverted-volatility percentiles">Score</th>
        <th class="s r" data-k="mom" data-ty="n" title="Return from 13 months ago to 1 month ago">12-1 mom</th>
        <th class="s r" data-k="vol" data-ty="n" title="60-day realised volatility, annualised">Vol</th>
        <th class="s r" data-k="dv" data-ty="n" title="60-day median daily dollar volume">Daily $vol</th>
      </tr></thead><tbody></tbody></table></div>
  </section>

  <section>
    <div class="chead"><h2>Strongest sub-industries now</h2><span class="cnt" id="scount"></span></div>
    <p>Internal participation by GICS sub-industry &mdash; the share of each group's liquid names above their
    own 200-day average.</p>
    <div class="tw tall"><table id="tsubs">
      <thead><tr>
        <th class="s" data-k="sub" data-ty="s">Sub-industry</th>
        <th class="s r" data-k="n" data-ty="n">Names</th>
        <th class="s r" data-k="breadth" data-ty="n">Above 200d</th>
        <th></th>
      </tr></thead><tbody></tbody></table></div>
  </section>
</div>

<div class="pane" id="strategies">
  <section>
    <h2>Three ways to hold the universe</h2>
    <p>All three measured against the same investable universe, after costs. The broad basket is the default
    because it wins on return with a quarter of the trading.</p>
    <div class="grid">{opt}</div>
  </section>
  <section>
    <div class="chead"><h2>Growth of $1 &middot; log scale</h2>
      <div class="ctrl"><span class="rg" data-t="eq"></span>
      <button class="exp" data-x="eq">Expand &#8599;</button></div></div>
    <div class="cw" id="c-eq"><div class="rdo"></div></div>
    <div class="leg"><span><i style="background:var(--b)"></i>Broad basket</span>
      <span><i style="background:var(--c)"></i>Trend-gated</span>
      <span><i style="background:var(--p)"></i>Buffered top-50</span></div>
    <p>Selecting on price and volume signals ended <em>behind</em> selecting nothing &mdash; about 1.4 points a
    year, most of it paid away in trading.</p>
  </section>
  <section>
    <div class="chead"><h2>Drawdown from prior peak</h2>
      <div class="ctrl"><span class="rg" data-t="dd"></span>
      <button class="exp" data-x="dd">Expand &#8599;</button></div></div>
    <div class="cw" id="c-dd"><div class="rdo"></div></div>
    <p>Where selection earns its keep: a worst fall of <b>{D['buffered']['mdd']*100:.1f}%</b> against the broad
    basket's <b>{D['bench']['mdd']*100:.1f}%</b>, and shallower through both the dot-com unwind and 2008.</p>
  </section>
</div>

<div class="pane" id="evidence">
  <section>
    <h2>Does it still work in the modern era?</h2>
    <p>The rule and the pass mark were fixed in writing before any of this was run: beat the broad basket on
    Sharpe in <em>both</em> halves. Two studies this month looked strong overall and died on this test.</p>
    <div class="tw"><table>
      <thead><tr><th>Approach</th><th class="r">1994&ndash;2010</th><th class="r">base</th><th></th>
      <th class="r">2010&ndash;2026</th><th class="r">base</th><th></th></tr></thead>
      <tbody>{erows}</tbody></table></div>
    <p class="fine">Sharpe ratios at 25bps per side. The first row is what most screens would produce, and it
    fails in the half that matters most.</p>
  </section>
  <section>
    <h2>Where the edge dies</h2>
    <div class="tw"><table>
      <thead><tr><th class="r">bps/side</th><th class="r">Selected</th><th class="r">Broad</th><th class="r">Edge</th></tr></thead>
      <tbody>{crows}</tbody></table></div>
    <p class="fine">Sub-industry variant, quarterly, full sample. The advantage decays steadily and is gone by
    roughly 75bps &mdash; and the S&amp;P 1500 includes SmallCap 600 names where spreads run well above 10bps.</p>
  </section>
  <section>
    <h2>Four signals, one answer</h2>
    <div class="note">
      <p>Four separate price and volume signals were tested this month &mdash; a Bitcoin volatility thrust,
      sub-industry breadth, the plain ranked basket, and the buffered basket. Every one reduced drawdown.
      <b>None reliably added return.</b> The 200-day filter cut the worst fall in six of six five-year windows.</p>
    </div>
    <p>Treat these as risk control, not alpha. If the goal is the largest pile of money, own the broad basket
    and trade it rarely.</p>
  </section>
</div>

<div class="pane" id="universe">
  <section>
    <h2>Survivorship, and why it matters</h2>
    <div class="kpis">
      <div class="kpi"><div class="l">Symbols in universe</div><div class="v mono">{U['watchlistSymbols']:,}</div>
        <div class="s">vs {U['liveToday']:,} live today</div></div>
      <div class="kpi"><div class="l">Symbols with history</div><div class="v mono">{U['symbolsUsed']:,}</div>
        <div class="s">incl. removed &amp; delisted</div></div>
      <div class="kpi"><div class="l">Month records</div><div class="v mono">{U['records']:,}</div>
        <div class="s">{U['months']} months</div></div>
      <div class="kpi"><div class="l">Sub-industries</div><div class="v mono">{U['subIndustries']}</div>
        <div class="s">GICS level 4</div></div>
    </div>
    <div class="note warn">
      <p>The index carries <b>{U['watchlistSymbols']:,}</b> names across its history against
      <b>{U['liveToday']:,}</b> alive today. A screen built on today's constituents silently discards roughly
      two-thirds of the record &mdash; every company that failed, was acquired, or was dropped. Membership here
      is point-in-time: a name counts in a month only if it was actually in the index that month.</p>
    </div>
  </section>
  <section>
    <div class="chead"><h2>Members through time</h2>
      <button class="exp" data-x="cov">Expand &#8599;</button></div>
    <div class="cw" id="c-cov"><div class="rdo"></div></div>
    <p class="fine">The panel resolves {U['membersLatest']:,} members in the latest month against an index of
    {U['liveToday']:,} &mdash; the coverage check that says the point-in-time join is working.</p>
  </section>
</div>

<div class="pane" id="method">
  <section>
    <h2>Method and limits</h2>
    <p>Everything below was fixed in writing before any test was run, so the result could not be
    reverse-engineered from whatever happened to work.</p>
    <details open><summary>The rule, as pre-registered</summary><div class="dbody">
      <ul>
        <li><b>Universe</b> &mdash; in the index that month, point-in-time.</li>
        <li><b>Liquidity</b> &mdash; 60-day median dollar volume above the 40th percentile of that month's
        universe. A percentile, not a fixed dollar figure, which would mean different things in 1996 and 2026.</li>
        <li><b>Price floor</b> &mdash; unadjusted close of $5 or more.</li>
        <li><b>Trend gate</b> &mdash; close above the 200-day average. Must pass.</li>
        <li><b>Rank</b> &mdash; average of the 12-1 momentum percentile and the inverted 60-day volatility
        percentile. Hold the top 50, equal-weight.</li>
        <li><b>Buffer</b> &mdash; a held name is replaced only once it falls below rank 100, which cut turnover
        from 284% to 139% a year.</li>
        <li><b>Benchmark</b> &mdash; equal-weight every name passing the same liquidity filters, so the
        comparison isolates selection rather than the equal-weight premium.</li>
      </ul></div></details>
    <details><summary>What this does not prove</summary><div class="dbody">
      <ul>
        <li>The Sharpe advantage is about 0.08 &mdash; suggestive, not statistically established, and not
        significance-tested.</li>
        <li>Costs are a flat assumption. Real spreads vary by name and size.</li>
        <li>US-listed, long-only, no leverage. Sector labels use current classification, so a company
        reclassified mid-life is mislabelled in its early years.</li>
        <li>A name leaving the index is sold at its last recorded price, so a collapse after removal is not
        captured. Those cases sit mostly in the broad basket, which flatters it &mdash; the comparison is
        conservative rather than generous.</li>
        <li>One market, one sample. Nothing here has been traded forward.</li>
      </ul></div></details>
    <details><summary>Why a deviation was logged and refused</summary><div class="dbody">
      <p>Holding 100 names instead of 50 produced a Sharpe of 0.84 against the pre-named headline's 0.77 &mdash;
      visibly better, and exactly the cell that would have been promoted had the headline not been fixed in
      advance. It is recorded as a refused deviation rather than used, because it was a best-of-nine choice made
      after seeing results. It may be real; it would need its own pre-registered test on fresh data to count.</p>
    </div></details>
  </section>
</div>

<footer>Own calculations on Norgate data, {U['start']} to {U['end']}. Research on a rules framework, not a
recommendation to buy any security. Historical and net of assumed costs; not a forecast.</footer>
</div>

<div class="ov" id="ov" role="dialog" aria-modal="true" aria-label="Expanded chart">
  <div class="ovbox"><div class="ovhead"><h2 id="ovt"></h2>
    <button class="ovclose" id="ovc">Close &#10005;</button></div>
    <div class="cw" id="c-ov" style="border:0;padding:0"><div class="rdo"></div></div>
    <div class="leg" id="ovl"></div></div>
</div>

<script>
var DATA={PAYLOAD};
var CSS=getComputedStyle(document.documentElement);
function tok(n){{return CSS.getPropertyValue(n).trim()||'#888';}}

/* ---------- chart engine ---------- */
var SPECS={{
  eq:{{title:'Growth of $1',log:true,fmt:function(v){{return v.toFixed(2)+'x';}},axf:function(v){{return v+'x';}},
      ticks:[1,3,10,30],series:[['bench','Broad basket','--b'],['trend','Trend-gated','--c'],['buffered','Buffered top-50','--p']],
      get:function(k){{return DATA.eq[k];}},labels:DATA.dates}},
  dd:{{title:'Drawdown from prior peak',fmt:function(v){{return (v*100).toFixed(1)+'%';}},axf:function(v){{return (v*100).toFixed(0)+'%';}},
      ticks:[0,-0.1,-0.25,-0.4,-0.5],series:[['bench','Broad basket','--b'],['trend','Trend-gated','--c'],['buffered','Buffered top-50','--p']],
      get:function(k){{return DATA.dd[k];}},labels:DATA.dates}},
  breadth:{{title:'Share of liquid names above their 200-day average',area:true,
      fmt:function(v){{return (v*100).toFixed(0)+'%';}},axf:function(v){{return (v*100).toFixed(0)+'%';}},
      ticks:[0,0.25,0.5,0.75,1],fixed:[0,1],series:[['b','Above 200-day','--g']],
      get:function(){{return DATA.breadth.map(function(r){{return r.b;}});}},
      labels:DATA.breadth.map(function(r){{return r.t;}})}},
  cov:{{title:'Index members carried in the panel',area:true,
      fmt:function(v){{return Math.round(v)+' members';}},axf:function(v){{return String(v);}},
      ticks:[0,500,1000,1500],fixed:[0,1650],series:[['members','Members','--a']],
      get:function(){{return DATA.coverage.map(function(r){{return r.members;}});}},
      labels:DATA.coverage.map(function(r){{return String(r.y);}})}}
}};
var RANGES={{eq:[['20Y',240],['10Y',120],['All',0]],dd:[['20Y',240],['10Y',120],['All',0]],
  breadth:[['5Y',60],['10Y',120],['All',0]]}};
var STATE={{}};

function draw(host,key,months,big){{
  var sp=SPECS[key], W=big?1160:940, H=big?460:280;
  var PL=big?64:54,PR=14,PT=12,PB=26,iw=W-PL-PR,ih=H-PT-PB;
  var labels=sp.labels, all=sp.series.map(function(s){{return sp.get(s[0]);}});
  var n=labels.length, from=(months&&months<n)?n-months:0;
  var lab=labels.slice(from), ser=all.map(function(a){{return a.slice(from);}}), m=lab.length;
  var lo,hi;
  if(sp.fixed){{lo=sp.fixed[0];hi=sp.fixed[1];}}
  else{{lo=Infinity;hi=-Infinity;ser.forEach(function(a){{a.forEach(function(v){{if(v<lo)lo=v;if(v>hi)hi=v;}});}});
    if(sp.log){{lo=Math.max(lo*0.92,0.5);hi=hi*1.06;}}else{{var pad=(hi-lo)*0.07||0.01;lo-=pad;hi+=pad;}}}}
  function X(i){{return PL+iw*(m<2?0.5:i/(m-1));}}
  function Y(v){{ if(sp.log){{var L=Math.log(Math.max(v,0.01)),a=Math.log(lo),b=Math.log(hi);
      return PT+ih*(1-(L-a)/(b-a));}} return PT+ih*(1-(v-lo)/(hi-lo)); }}
  var ticks=sp.ticks.filter(function(v){{return v>=lo-1e-9&&v<=hi+1e-9;}});
  if(!ticks.length) ticks=[lo,(lo+hi)/2,hi];
  var s='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet" role="img" aria-label="'+sp.title+'">';
  ticks.forEach(function(v){{var y=Y(v);
    s+='<line class="gl" x1="'+PL+'" x2="'+(W-PR)+'" y1="'+y.toFixed(1)+'" y2="'+y.toFixed(1)+'"/>';
    s+='<text class="ax" x="'+(PL-7)+'" y="'+(y+3.6).toFixed(1)+'" text-anchor="end">'+sp.axf(v)+'</text>';}});
  var step=Math.max(1,Math.ceil(m/(big?12:7)));
  for(var i=0;i<m;i+=step){{var t=lab[i]; t=(t.length>4)?t.slice(0,4):t;
    s+='<text class="ax" x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle">'+t+'</text>';}}
  ser.forEach(function(a,si){{
    var col=tok(sp.series[si][2]);
    var pts=a.map(function(v,i){{return X(i).toFixed(1)+','+Y(v).toFixed(1);}}).join(' ');
    if(sp.area) s+='<polygon class="ar" style="fill:'+col+'" points="'+PL+','+Y(sp.fixed?sp.fixed[0]:lo)+' '+pts+' '+(W-PR)+','+Y(sp.fixed?sp.fixed[0]:lo)+'"/>';
    s+='<polyline class="ln" style="stroke:'+col+'" points="'+pts+'"/>';}});
  s+='<line class="cross" id="cx" x1="0" x2="0" y1="'+PT+'" y2="'+(PT+ih)+'" style="opacity:0"/>';
  s+='<rect x="'+PL+'" y="'+PT+'" width="'+iw+'" height="'+ih+'" fill="transparent" id="hit"/></svg>';
  host.querySelectorAll('svg').forEach(function(e){{e.remove();}});
  host.insertAdjacentHTML('afterbegin',s);
  var svg=host.querySelector('svg'), rdo=host.querySelector('.rdo'), cx=svg.querySelector('#cx');
  function move(ev){{
    var r=svg.getBoundingClientRect(), px=('touches' in ev?ev.touches[0].clientX:ev.clientX)-r.left;
    var vx=px/r.width*W, i=Math.round((vx-PL)/iw*(m-1));
    if(i<0)i=0; if(i>m-1)i=m-1;
    cx.setAttribute('x1',X(i).toFixed(1)); cx.setAttribute('x2',X(i).toFixed(1)); cx.style.opacity=1;
    var h='<b>'+lab[i]+'</b>';
    ser.forEach(function(a,si){{h+='<br><i style="background:'+tok(sp.series[si][2])+'"></i>'+sp.series[si][1]+' '+sp.fmt(a[i]);}});
    rdo.innerHTML=h; rdo.classList.add('on');
  }}
  svg.addEventListener('mousemove',move); svg.addEventListener('touchmove',move,{{passive:true}});
  svg.addEventListener('mouseleave',function(){{rdo.classList.remove('on');cx.style.opacity=0;}});
}}

['eq','dd','breadth','cov'].forEach(function(k){{
  var host=document.getElementById('c-'+k); if(!host) return;
  STATE[k]=RANGES[k]?RANGES[k][RANGES[k].length-1][1]:0;
  var rg=document.querySelector('.rg[data-t="'+k+'"]');
  if(rg&&RANGES[k]){{
    RANGES[k].forEach(function(r,idx){{
      var b=document.createElement('button'); b.className='rb'+(idx===RANGES[k].length-1?' on':'');
      b.textContent=r[0]; b.setAttribute('aria-label',sp_label(k,r[0]));
      b.addEventListener('click',function(){{
        rg.querySelectorAll('.rb').forEach(function(x){{x.classList.remove('on');}});
        b.classList.add('on'); STATE[k]=r[1]; draw(host,k,r[1],false);}});
      rg.appendChild(b);}});
  }}
  draw(host,k,STATE[k],false);
}});
function sp_label(k,r){{return 'Show '+r+' of '+SPECS[k].title;}}

/* ---------- expand overlay ---------- */
var ov=document.getElementById('ov'), ovt=document.getElementById('ovt'), ovl=document.getElementById('ovl');
var ovHost=document.getElementById('c-ov'), lastFocus=null;
function openOv(k){{
  lastFocus=document.activeElement;
  ovt.textContent=SPECS[k].title; ov.classList.add('on');
  ovl.innerHTML=SPECS[k].series.map(function(s){{return '<span><i style="background:'+tok(s[2])+'"></i>'+s[1]+'</span>';}}).join('');
  draw(ovHost,k,STATE[k]||0,true);
  document.getElementById('ovc').focus();
}}
function closeOv(){{ov.classList.remove('on'); if(lastFocus)lastFocus.focus();}}
document.querySelectorAll('.exp').forEach(function(b){{
  b.addEventListener('click',function(){{openOv(b.dataset.x);}});}});
document.getElementById('ovc').addEventListener('click',closeOv);
ov.addEventListener('click',function(e){{if(e.target===ov)closeOv();}});
document.addEventListener('keydown',function(e){{if(e.key==='Escape'&&ov.classList.contains('on'))closeOv();}});

/* ---------- tables: sort, filter, expand ---------- */
function fmtRow(b){{
  return '<td class="mono">'+b.sym+'</td><td class="sub">'+b.sub+'</td>'+
    '<td class="mono r">'+b.score.toFixed(2)+'</td>'+
    '<td class="mono r '+(b.mom>0?'pos':'neg')+'">'+(b.mom>0?'+':'')+(b.mom*100).toFixed(0)+'%</td>'+
    '<td class="mono r">'+(b.vol*100).toFixed(0)+'%</td>'+
    '<td class="mono r">$'+Math.round(b.dv).toLocaleString()+'m</td>';
}}
function detail(b){{
  function bar(lbl,val,pctv,col){{
    return '<div class="dbox"><div class="dl">'+lbl+'</div><div class="dv">'+val+'</div>'+
      '<div class="track"><span style="width:'+Math.max(2,Math.min(100,pctv))+'%;background:'+col+'"></span></div></div>';
  }}
  var momPct=Math.min(100,Math.max(0,(b.mom+0.5)/1.5*100));
  var volPct=Math.min(100,b.vol/0.8*100);
  return '<td colspan="6"><div class="dgrid">'+
    bar('Composite score',b.score.toFixed(2),b.score*100,tok('--p'))+
    bar('12-1 momentum',(b.mom>0?'+':'')+(b.mom*100).toFixed(1)+'%',momPct,tok(b.mom>0?'--g':'--r'))+
    bar('Realised volatility',(b.vol*100).toFixed(1)+'%',volPct,tok('--a'))+
    bar('Daily dollar volume','$'+Math.round(b.dv).toLocaleString()+'m',Math.min(100,b.dv/500*100),tok('--b'))+
    '</div><p class="fine" style="margin-top:9px">Selected because it cleared the liquidity floor and the '+
    '200-day trend gate, then ranked in the top 50 on the combined score. It stays held until it falls '+
    'below rank 100.</p></td>';
}}
function mkTable(id,rows,render,det,defKey,defDir,countEl){{
  var t=document.getElementById(id), tb=t.querySelector('tbody');
  var st={{k:defKey,d:defDir,q:''}};
  function paint(){{
    var r=rows.slice();
    if(st.q){{var q=st.q.toLowerCase();
      r=r.filter(function(x){{return (x.sym||'').toLowerCase().indexOf(q)>=0||(x.sub||'').toLowerCase().indexOf(q)>=0;}});}}
    var th=t.querySelector('th[data-k="'+st.k+'"]'), ty=th?th.dataset.ty:'n';
    r.sort(function(a,b){{var av=a[st.k],bv=b[st.k];
      var c=(ty==='s')?String(av).localeCompare(String(bv)):(av-bv); return st.d==='asc'?c:-c;}});
    tb.innerHTML=r.map(function(x,i){{return '<tr class="'+(det?'rw':'')+'" data-i="'+rows.indexOf(x)+'">'+render(x)+'</tr>';}}).join('');
    t.querySelectorAll('th[data-k]').forEach(function(h){{h.classList.remove('asc','desc');
      if(h.dataset.k===st.k)h.classList.add(st.d);}});
    if(countEl)document.getElementById(countEl).textContent=r.length+' of '+rows.length;
  }}
  t.querySelectorAll('th[data-k]').forEach(function(h){{
    h.classList.add('s'); h.setAttribute('tabindex','0'); h.setAttribute('role','button');
    function go(){{ if(st.k===h.dataset.k) st.d=(st.d==='asc'?'desc':'asc');
      else {{st.k=h.dataset.k; st.d=(h.dataset.ty==='s')?'asc':'desc';}} paint(); }}
    h.addEventListener('click',go);
    h.addEventListener('keydown',function(e){{if(e.key==='Enter'||e.key===' '){{e.preventDefault();go();}}}});
  }});
  if(det){{
    tb.addEventListener('click',function(e){{
      var tr=e.target.closest('tr.rw'); if(!tr)return;
      var nx=tr.nextElementSibling;
      if(nx&&nx.classList.contains('det')){{nx.remove();tr.classList.remove('op');return;}}
      tb.querySelectorAll('tr.det').forEach(function(x){{x.remove();}});
      tb.querySelectorAll('tr.op').forEach(function(x){{x.classList.remove('op');}});
      var row=document.createElement('tr'); row.className='det'; row.innerHTML=det(rows[+tr.dataset.i]);
      tr.after(row); tr.classList.add('op');
    }});
  }}
  return {{paint:paint,setQ:function(v){{st.q=v;paint();}}}};
}}
var bt=mkTable('tbasket',DATA.basket,fmtRow,detail,'score','desc','bcount'); bt.paint();
document.getElementById('bfilter').addEventListener('input',function(e){{bt.setQ(e.target.value);}});
var st=mkTable('tsubs',DATA.subs,function(s){{
  return '<td>'+s.sub+'</td><td class="mono r">'+s.n+'</td>'+
    '<td class="mono r">'+(s.breadth*100).toFixed(0)+'%</td>'+
    '<td class="bar"><span style="width:'+(s.breadth*100).toFixed(0)+'%"></span></td>';
}},null,'breadth','desc','scount'); st.paint();

/* ---------- tabs ---------- */
document.querySelectorAll('.tab').forEach(function(t){{
  t.addEventListener('click',function(){{
    document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('on');}});
    document.querySelectorAll('.pane').forEach(function(x){{x.classList.remove('on');}});
    t.classList.add('on'); document.getElementById(t.dataset.p).classList.add('on');
    ['eq','dd','breadth','cov'].forEach(function(k){{
      var h=document.getElementById('c-'+k);
      if(h&&h.offsetParent!==null) draw(h,k,STATE[k]||0,false);}});
    window.scrollTo({{top:0,behavior:'instant'}});
  }});
}});
</script>
"""
open(OUT, "w", encoding="utf-8").write(html)
print(f"wrote {OUT} ({len(html):,} bytes)")
