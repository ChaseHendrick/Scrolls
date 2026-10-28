// Snapped Labels, "Voxel exact" tab: per-scroll claim levels (Measured, Certified, Not shown), tolerance bars, abstain
// strata, residual histograms and controls, read from vx/summary.json (schema snapped-labels/voxel-exact@1, checked by
// python -m kit vxsummary check). ?vx=URL reads another summary; ?vx=fixture reads the synthetic fixture, always under a
// banner. The tab stays hidden until a summary loads and validates. Loaded after app.js and uses its helpers.
'use strict';

const VX = { doc: null, url: null, fixture: false, show: null, showIdx: 0, mode: 'signed', pick: {} };
const VX_SCHEMA = 'snapped-labels/voxel-exact@1';
const VX_CLAIMS = { measured: 'Measured', certified: 'Certified', not_shown: 'Not shown' };
const VX_ORDER = { measured: 0, certified: 1, not_shown: 2 };
const VX_TOLS = ['0.5', '1', '2'];
// a verdict is text plus a shape, never color alone
const VX_ICON = { PASS: '✓', FAIL: '✕', 'NOT SHOWN': '○', UNANSWERABLE: '?', VOID: '⊘' };
const VX_STRATUM_NAME = { C0: 'snapped (code 0)', C0L: 'snapped, placed in the label scan (code 0)', C2: 'filled (code 2)', C1: 'left in place (code 1)' };

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const p1 = (x) => (x == null || !Number.isFinite(x) ? 'n/a' : `${(100 * x).toFixed(1)}%`);
const sgn = (x) => (x > 0 ? `+${x.toFixed(2)}` : x.toFixed(2));
const VX_BASIS = { itt: 'every selected site', scorable: 'scorable sites', covered: 'covered sites' };

function vxURL() {
  const q = params.get('vx');
  if (q === 'fixture') return new URL('vx/fixture/summary.json', location.href).href;
  return new URL(q || 'vx/summary.json', location.href).href;
}

// The page's own check, a subset of kit/vxsummary.py: enough that a broken file never draws as numbers.
function vxValid(d) {
  const bad = [];
  if (!d || d.schema !== VX_SCHEMA) bad.push(`schema is not ${VX_SCHEMA}`);
  if (!d || !Array.isArray(d.scrolls) || !d.scrolls.length) bad.push('no scrolls');
  // every count drawn into the page must be an integer and every share a number in 0..1, so a file from ?vx=URL
  // cannot carry markup into the cards
  const cnt = (x) => Number.isInteger(x) && x >= 0;
  const frac = (x) => x == null || (typeof x === 'number' && x >= 0 && x <= 1);
  const slotOK = (w) => !w || (cnt(w.k) && cnt(w.n) && w.k <= w.n && frac(w.share) && frac(w.lower) && frac(w.upper) && w.basis in VX_BASIS);
  for (const s of (d && d.scrolls) || []) {
    if (!(s.claim in VX_CLAIMS)) bad.push(`${s.scroll}: claim ${s.claim}`);
    for (const st of s.strata || []) {
      if (!cnt(st.n_selected) || !cnt(st.n_scorable)) bad.push(`${s.scroll} ${st.id} counts`);
      const c = st.coverage;
      if (c && !(cnt(c.k) && cnt(c.n) && c.k <= c.n && frac(c.share) && frac(c.lower) && frac(c.upper) && frac(c.bar))) bad.push(`${s.scroll} ${st.id} coverage`);
      if (st.single_truth && !slotOK(st.single_truth.within_1)) bad.push(`${s.scroll} ${st.id} single_truth`);
      for (const t of VX_TOLS) if (!slotOK(st.within && st.within[t])) bad.push(`${s.scroll} ${st.id} within ${t} slot`);
      if (st.median_abs != null && typeof st.median_abs !== 'number') bad.push(`${s.scroll} ${st.id} median`);
    }
    for (const st of s.strata || []) for (const t of VX_TOLS) {
      const w = st.within && st.within[t];
      if (w && !(w.n >= w.k && w.k >= 0 && w.share >= 0 && w.share <= 1)) bad.push(`${s.scroll} ${st.id} within ${t}`);
      if (w && w.basis === 'covered' && !(st.coverage && st.coverage.k === w.n)) bad.push(`${s.scroll} ${st.id} covered ${t}`);
    }
    if ((s.strata || []).some((st) => st.coverage) && !s.scope) bad.push(`${s.scroll}: a two-scan test without its scope`);
  }
  if (d && typeof d.fixture !== 'boolean') bad.push('fixture flag missing');
  return bad;
}

// ---------------------------------------------------------------- small charts

function tolBars(st, rule) {
  const bar = rule && rule.bar != null ? rule.bar : 0.9;
  return `<div class="vx-tol" role="list">${VX_TOLS.map((t) => {
    const w = st.within[t];
    const label = `${t === '1' ? '1 voxel' : `${t} voxels`}`;
    if (!w) return `<div class="vx-tolrow" role="listitem"><span class="vx-toll">${label}</span><span class="vx-track na"><em>not measured</em></span><span class="vx-tolv">n/a</span></div>`;
    const lo = w.lower != null ? w.lower : null, hi = w.upper != null ? w.upper : null;
    const whisk = lo != null ? `<i class="vx-whisk" style="left:${100 * lo}%;width:${100 * ((hi != null ? hi : w.share) - lo)}%"></i>` : '';
    const line = t === '1' ? `<i class="vx-barline" style="left:${100 * bar}%" title="the bar, ${p1(bar)}"></i>` : '';
    return `<div class="vx-tolrow" role="listitem"><span class="vx-toll">${label}</span>
      <span class="vx-track" title="${esc(w.k)} of ${esc(w.n)} sites (${VX_BASIS[w.basis] || w.basis})${lo != null ? `; one-sided 95% interval ${p1(lo)} to ${p1(hi)}` : ''}">
        <i class="vx-fill" style="width:${100 * w.share}%"></i>${whisk}${line}</span>
      <span class="vx-tolv"><b>${p1(w.share)}</b> <small>${esc(w.k)} of ${esc(w.n)}, ${VX_BASIS[w.basis] || w.basis}</small></span></div>`;
  }).join('')}</div>`;
}

// a two-scan test: the share of drawn sites the two scans cover, with its interval and bar
function coverageBar(st) {
  const c = st.coverage;
  if (!c) return '';
  const whisk = c.lower != null ? `<i class="vx-whisk" style="left:${100 * c.lower}%;width:${100 * ((c.upper != null ? c.upper : c.share) - c.lower)}%"></i>` : '';
  return `<div class="vx-tol vx-cov" role="list"><div class="vx-tolrow" role="listitem"><span class="vx-toll">covered</span>
      <span class="vx-track" title="${esc(c.k)} of ${esc(c.n)} drawn sites; one-sided 95% interval ${p1(c.lower)} to ${p1(c.upper)}; bar ${p1(c.bar)}">
        <i class="vx-fill cov" style="width:${100 * c.share}%"></i>${whisk}<i class="vx-barline" style="left:${100 * c.bar}%" title="the coverage bar, ${p1(c.bar)}"></i></span>
      <span class="vx-tolv"><b>${p1(c.share)}</b> <small>${esc(c.k)} of ${esc(c.n)} drawn sites</small></span></div></div>
    <p class="hint">Covered: ${esc(c.what)}. ${esc(c.verdict)} (lower bound ${p1(c.lower)}, bar ${p1(c.bar)}). The shares below count covered sites only; a site that is not covered is neither a hit nor a miss.</p>`;
}

function singleTruth(st, s) {
  const o = st.single_truth;
  if (!o) return '';
  const w = o.within_1;
  return `<details class="vx-single"><summary>Against the ${esc(s.truth ? s.truth.voxel_um : '')} µm scan alone: <span aria-hidden="true">${VX_ICON[o.verdict] || ''}</span> ${esc(o.verdict)}${w ? `, ${p1(w.share)} within 1 voxel (${esc(w.k)} of ${esc(w.n)}, ${VX_BASIS[w.basis] || w.basis}; lower bound ${p1(w.lower)})` : ''}</summary>
    <p class="hint">${esc(o.why)}${o.instrument_limited ? ' (limited by the instrument)' : ''}.</p>
    <h4>Controls against the one scan</h4>${controls({ controls: o.controls })}</details>`;
}

function earlierTests(s) {
  if (!s.earlier || !s.earlier.length) return '';
  return `<details class="vx-earlier"><summary>Earlier frozen test${s.earlier.length > 1 ? 's' : ''} on this scroll (spent)</summary><ul>${s.earlier.map((e) => `<li><b>${esc(e.scope)}</b>: ${esc(e.summary)} <small>Preregistration ${esc(String(e.prereg.sha256).slice(0, 12))}, frozen ${esc(e.prereg.frozen)}.</small></li>`).join('')}</ul></details>`;
}

function hist(st, showPub) {
  const h = st.residual_hist, ph = st.published_hist;
  if (!h || !h.edges || h.edges.length < 2) return '<p class="hint">No residual distribution for this stratum.</p>';
  const W = 360, H = 130, L = 8, B = 22, T = 10;
  const e = h.edges, lo = e[0], hi = e[e.length - 1];
  const X = (v) => L + (W - 2 * L) * (v - lo) / (hi - lo);
  const all = [...h.counts, ...(showPub && ph && ph.counts ? ph.counts : [])];
  const max = Math.max(1, ...all);
  const Y = (c) => H - B - (H - B - T) * c / max;
  let bars = '';
  h.counts.forEach((c, i) => {
    if (!c) return;
    const x0 = X(e[i]) + 1, x1 = X(e[i + 1]) - 1;
    bars += `<rect class="vx-hbar" x="${x0.toFixed(1)}" y="${Y(c).toFixed(1)}" width="${Math.max(1, x1 - x0).toFixed(1)}" height="${(H - B - Y(c)).toFixed(1)}" rx="1.5"><title>${e[i]} to ${e[i + 1]} voxels: ${c} sites</title></rect>`;
  });
  let pub = '';
  if (showPub && ph && ph.counts && ph.edges && ph.edges.length === ph.counts.length + 1) {
    let d = `M${X(ph.edges[0]).toFixed(1)},${Y(0).toFixed(1)}`;
    ph.counts.forEach((c, i) => { d += `L${X(ph.edges[i]).toFixed(1)},${Y(c).toFixed(1)}L${X(ph.edges[i + 1]).toFixed(1)},${Y(c).toFixed(1)}`; });
    d += `L${X(ph.edges[ph.edges.length - 1]).toFixed(1)},${Y(0).toFixed(1)}`;
    pub = `<path class="vx-hpub" d="${d}"><title>published label</title></path>`;
  }
  const ticks = [-4, -2, -1, 0, 1, 2, 4].filter((v) => v >= lo && v <= hi)
    .map((v) => `<line class="vx-tick" x1="${X(v)}" x2="${X(v)}" y1="${H - B}" y2="${H - B + 4}"/><text class="vx-tickt" x="${X(v)}" y="${H - 6}" text-anchor="middle">${v > 0 ? '+' + v : v}</text>`).join('');
  const out = (h.under || h.over) ? `<text class="vx-tickt" x="${W - L}" y="${T + 2}" text-anchor="end">${h.under} below ${lo}, ${h.over} above +${hi}</text>` : '';
  return `<svg class="vx-hist" viewBox="0 0 ${W} ${H}" role="img" aria-label="Signed residual of the snapped vertices, in label voxels, ${h.counts.reduce((a, b) => a + b, 0)} sites${showPub ? ', with the published label' : ''}">
    <rect class="vx-band" x="${X(-1)}" y="${T}" width="${X(1) - X(-1)}" height="${H - B - T}"><title>within 1 voxel</title></rect>
    <line class="vx-base" x1="${L}" x2="${W - L}" y1="${H - B}" y2="${H - B}"/>
    ${bars}${pub}
    <line class="vx-zero" x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${H - B}"/>
    ${ticks}${out}</svg>`;
}

function meter(s) {
  const v = s.vertices, by = v.by_code, tot = Math.max(1, v.released + v.held_back);
  const part = (n, color) => (n ? `<i style="width:calc(${100 * n / tot}% - 2px);background:${color}"></i>` : '');
  return `<div class="meter vx-meter">${part(by['0'], 'var(--snap)')}${part(by['2'], 'var(--fill)')}${part(by['1'], 'var(--pub)')}${part(v.held_back, 'var(--held)')}</div>
    <div class="legend"><span><i style="background:var(--snap)"></i>snapped ${p1(by['0'] / tot)}</span><span><i style="background:var(--fill)"></i>filled ${p1(by['2'] / tot)}</span><span><i style="background:var(--pub)"></i>left in place ${p1(by['1'] / tot)}</span><span><i style="background:var(--held)"></i>held back ${p1(v.held_back / tot)}</span></div>`;
}

function chip(st, on, scroll) {
  const icon = VX_ICON[st.verdict] || '';
  return `<button class="vx-chip v-${st.verdict.replace(' ', '-').toLowerCase()}${st.id === 'C0L' ? ' sub' : ''}" data-scroll="${esc(scroll)}" data-stratum="${esc(st.id)}" aria-pressed="${on}" title="${esc(st.why)}">
    <b>${esc(st.id)}</b> ${esc(VX_STRATUM_NAME[st.id] || '')} <span class="vx-v"><span aria-hidden="true">${icon}</span> ${esc(st.verdict)}</span></button>`;
}

function controls(st) {
  if (!st.controls || !st.controls.length) return '';
  return `<ul class="vx-ctl">${st.controls.map((c) => {
    const state = c.holds == null ? 'not measured' : c.holds ? 'holds' : 'does not hold';
    return `<li class="${c.holds === false ? 'no' : c.holds ? 'yes' : ''}"><span aria-hidden="true">${c.holds == null ? '·' : c.holds ? '✓' : '✕'}</span> ${esc(c.name)}: ${p1(c.observed)} within 1 voxel, required ${esc(c.require)} ${p1(c.limit)}: <b>${state}</b></li>`;
  }).join('')}</ul>`;
}

function numbers(s) {
  const rows = [];
  for (const st of s.strata || []) {
    if (st.coverage) {
      const c = st.coverage;
      rows.push(`<tr><td>${esc(st.id)}</td><td>${esc(c.verdict)}</td><td>covered</td><td class="n">${esc(c.k)}</td><td class="n">${esc(c.n)}</td><td class="n">${p1(c.share)}</td><td class="n">${p1(c.lower)}</td><td class="n">${p1(c.upper)}</td><td>drawn sites</td></tr>`);
    }
    if (st.single_truth && st.single_truth.within_1) {
      const w = st.single_truth.within_1;
      rows.push(`<tr><td>${esc(st.id)}, one scan</td><td>${esc(st.single_truth.verdict)}</td><td>1</td><td class="n">${esc(w.k)}</td><td class="n">${esc(w.n)}</td><td class="n">${p1(w.share)}</td><td class="n">${w.lower != null ? p1(w.lower) : ''}</td><td class="n">${w.upper != null ? p1(w.upper) : ''}</td><td>${esc(w.basis)}</td></tr>`);
    }
    for (const t of VX_TOLS) {
      const w = st.within[t];
      rows.push(`<tr><td>${esc(st.id)}</td><td>${esc(st.verdict)}</td><td>${t}</td><td class="n">${w ? w.k : ''}</td><td class="n">${w ? w.n : ''}</td><td class="n">${w ? p1(w.share) : 'not measured'}</td><td class="n">${w && w.lower != null ? p1(w.lower) : ''}</td><td class="n">${w && w.upper != null ? p1(w.upper) : ''}</td><td>${w ? esc(w.basis) : ''}</td></tr>`);
    }
  }
  const v = s.vertices;
  return `<details class="vx-num"><summary>Show numbers</summary>
    <p class="hint">Vertices released ${fmt(v.released)} (code 0: ${fmt(v.by_code['0'])}, code 2: ${fmt(v.by_code['2'])}, code 1: ${fmt(v.by_code['1'])}), held back ${fmt(v.held_back)}. Label scan ${esc(s.label_scan.voxel_um)} µm${s.truth ? `; truth ${esc(s.truth.voxel_um)} µm scan` : ''}${s.second_truth ? `; second truth ${esc(s.second_truth.voxel_um)} µm scan` : ''}${s.oracle ? `; positive control ${esc(s.oracle.voxel_um)} µm scan` : ''}.${s.void && s.void.length ? ` Void: ${esc(s.void.join('; '))}.` : ''}</p>
    ${rows.length ? `<div class="vx-tw"><table><thead><tr><th>Stratum</th><th>Verdict</th><th>Voxels</th><th class="n">k</th><th class="n">n</th><th class="n">Share</th><th class="n">Lower</th><th class="n">Upper</th><th>Basis</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>` : ''}
    ${s.certificate ? `<p class="hint">Certificate: ${esc(s.certificate.method)}, lower bound ${p1(s.certificate.lower)} at ${p1(s.certificate.level)} over ${fmt(s.certificate.n)} vertices.</p>` : ''}</details>`;
}

// ---------------------------------------------------------------- cards

function stratumOrder(strata) {
  const rank = { C0: 0, C0L: 1, C2: 2, C1: 3 };
  return strata.slice().sort((a, b) => (rank[a.id] ?? 9) - (rank[b.id] ?? 9));
}

function strataBody(s, rule) {
  const strata = stratumOrder(s.strata || []);
  const prim = strata.find((x) => x.primary) || strata[0];
  const cur = strata.find((x) => x.id === VX.pick[s.scroll]) || prim;
  const one = prim && prim.within['1'];
  const pubc = prim && (prim.controls || []).find((c) => /^published/.test(c.name));
  const cov = prim && prim.coverage;
  const head2 = one ? `${cov ? `<p class="vx-headline">The two scans agree on the face at <b>${p1(cov.share)}</b> of drawn sites (${esc(cov.k)} of ${esc(cov.n)}). On those, <b>${p1(one.share)}</b> of snapped vertices lie within 1 voxel (${esc(prim.id)}, <span aria-hidden="true">${VX_ICON[prim.verdict] || ''}</span> ${esc(prim.verdict)}). One-sided 95% lower bounds ${p1(cov.lower)} (bar ${p1(cov.bar)}) and ${p1(one.lower)} (bar ${p1(rule.bar)}).</p>` : `<p class="vx-headline"><b>${p1(one.share)}</b> within 1 voxel (${esc(prim.id)}, <span aria-hidden="true">${VX_ICON[prim.verdict] || ''}</span> ${esc(prim.verdict)}). One-sided 95% lower bound ${p1(one.lower)} (bar ${p1(rule.bar)}).</p>`}
    ${s.scope ? `<p class="vx-scope">${esc(s.scope)}</p>` : ''}
    <p class="hint">${pubc ? `${esc(pubc.name.replace(/^published label/, 'Published label'))}: ${p1(pubc.observed)}.` : ''}${s.void && s.void.length ? ` The test is void: ${esc(s.void.join('; '))}.` : ''}</p>` : '';
  const pubOn = !!VX.pick[`${s.scroll}:pub`];
  return `${head2}
    ${meter(s)}
    <div class="vx-chips" role="group" aria-label="Strata">${strata.map((x) => chip(x, x.id === cur.id, s.scroll)).join('')}</div>
    <div class="vx-grid">
      <div><h4>${esc(cur.id)}: share within each tolerance</h4>${coverageBar(cur)}${tolBars(cur, rule)}
        <p class="hint">${esc(cur.verdict)}: ${esc(cur.why)}${cur.instrument_limited ? ' (limited by the instrument)' : ''}. ${esc(cur.n_selected)} sites selected${cur.coverage ? `, ${esc(cur.coverage.k)} covered` : `, ${esc(cur.n_scorable)} scorable`}. Whiskers: one-sided 95% interval. Dashed line: the bar.</p></div>
      <div><h4>${esc(cur.id)}: signed residual, voxels <label class="tog vx-pubtog"><input type="checkbox" data-pub="${esc(s.scroll)}"${pubOn ? ' checked' : ''}><i class="dot pub"></i>published label</label></h4>
        ${hist(cur, pubOn)}
        <p class="hint">${esc(cur.residual_hist && cur.residual_hist.sign ? cur.residual_hist.sign : '')}. Shaded: within 1 voxel.${cur.median_abs != null ? ` Median distance ${cur.median_abs.toFixed(2)} voxels.` : ''}</p></div>
    </div>
    <h4>Controls (each must be able to fail)</h4>${controls(cur)}
    ${singleTruth(cur, s)}
    <p class="hint vx-not">What this does not show: labels that follow the wrong wrap, sheets that touch with no gap, and any scroll, segment or region not scored here${cur.coverage ? ', and any site the two scans do not cover' : ''}.</p>
    ${earlierTests(s)}
    ${numbers(s)}`;
}

function scrollCard(s) {
  const rule = VX.doc.rule || {};
  const twoScan = (s.strata || []).some((x) => x.coverage);
  const badge = { measured: twoScan ? 'Model output, measured where two finer scans agree' : 'Model output, measured against an independent finer scan', certified: 'Model output, truth-free certificate', not_shown: (s.strata || []).length ? 'tested; no claim' : 'no claim' }[s.claim];
  const head = `<header class="vx-head"><div><h3>${esc(s.scroll)}</h3><small>label scan ${esc(s.label_scan.voxel_um)} µm voxels${s.truth ? `, truth from a ${esc(s.truth.voxel_um)} µm scan` : ''}${s.second_truth ? ` and a ${esc(s.second_truth.voxel_um)} µm scan` : ''}</small></div>
    <span class="vx-badge c-${s.claim}"><b>${VX_CLAIMS[s.claim]}</b> ${badge}</span></header>`;
  if (s.claim === 'not_shown') {
    const tested = (s.strata || []).length > 0;
    return `<article class="vx-card c-${s.claim}" data-scroll="${esc(s.scroll)}">${head}<p>Not shown: ${esc(s.why_not_shown)}.${tested ? ' The numbers below are what the test measured (model output); they make no claim.' : ''}</p>${tested ? strataBody(s, rule) : `${meter(s)}${numbers(s)}`}</article>`;
  }
  if (s.claim === 'certified') {
    const c = s.certificate;
    return `<article class="vx-card c-${s.claim}" data-scroll="${esc(s.scroll)}">${head}
      <p class="vx-headline">One-sided ${p1(c.level)} lower bound <b>${p1(c.lower)}</b> within 1 voxel (bar ${p1(rule.bar)}).</p>
      <p class="hint">No truth scan; lower bound from the certificate, over ${fmt(c.n)} vertices. It rests on these assumptions:</p>
      <ul class="vx-assume">${c.assumptions.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
      ${meter(s)}${numbers(s)}</article>`;
  }
  return `<article class="vx-card c-${s.claim}" data-scroll="${esc(s.scroll)}">${head}${strataBody(s, rule)}</article>`;
}

function renderCards() {
  const d = VX.doc;
  const sc = d.scrolls.slice().sort((a, b) => VX_ORDER[a.claim] - VX_ORDER[b.claim]);
  const count = (c) => d.scrolls.filter((s) => s.claim === c).length;
  $('vx-tiles').innerHTML = ['measured', 'certified', 'not_shown'].map((c) => `<div class="stat vx-t-${c}"><b>${count(c)}</b><span>scrolls ${VX_CLAIMS[c].toLowerCase()}</span></div>`).join('');
  $('vx-cards').innerHTML = sc.map(scrollCard).join('');
  $('vx-cards').querySelectorAll('.vx-chip').forEach((b) => { b.onclick = () => { VX.pick[b.dataset.scroll] = b.dataset.stratum; renderCards(); }; });
  $('vx-cards').querySelectorAll('input[data-pub]').forEach((c) => { c.onchange = () => { VX.pick[`${c.dataset.pub}:pub`] = c.checked; renderCards(); }; });
  const pre = d.prereg || {};
  $('vx-prereg').textContent = `${pre.sha256 || 'n/a'}, frozen ${pre.frozen || 'n/a'}`;
  const pr = d.prizes_read || {};
  $('vx-elig').innerHTML = d.fixture ? 'The fixture\'s scrolls are made up.' : `Sourced fact: none of these scrolls is on the prize lists at <a href="${esc(/^https:\/\//.test(String(pr.url)) ? pr.url : 'https://scrollprize.org/prizes')}" target="_blank" rel="noopener">scrollprize.org/prizes</a> (read ${esc(pr.date)}).`;
  $('vx-src').textContent = `${d.dataset.repo} ${d.dataset.release} at ${d.dataset.revision.slice(0, 12)}, summary ${d.generated}${d.fixture ? ', synthetic fixture' : ''}`;
}

// ---------------------------------------------------------------- showcase: residual heatmap and CT with the truth face

const RS = 12;   // floats per showcase line piece: published, snapped, truth (ax ay bx by each)

async function openShowcase(segment) {
  const list = (VX.doc && VX.doc.showcase) || [];
  const e = list.find((x) => x.segment === segment) || list[0];
  if (!e) throw new Error('no showcase segment');
  const base = new URL(e.file, VX.url).href;
  const meta = await getJSON(base);
  // the grids are plain number lists (null: no value)
  const res = Float32Array.from(meta.residual, (v) => (v == null ? NaN : v)), state = Uint8Array.from(meta.state);
  const xyz = Float32Array.from(meta.xyz), rows = Float32Array.from(meta.rows);
  VX.show = { meta, res, state, xyz, rows, plane: 0, cx: 0, cy: 0, win: Number($('vx-win').value) || 192, ct: null,
    mode: (document.querySelector('input[name="vx-mode"]:checked') || {}).value || 'signed' };
  $('vx-show-title').textContent = `${meta.scroll} · ${meta.segment}`;
  $('vx-truth-note').textContent = meta.truth_note;
  const mid = Math.floor(meta.planes.length / 2);
  pickPlane(mid);
  heat();
  await showDraw();
}

function pickPlane(i) {
  // center on a piece a quarter of the way along the plane's line
  const V = VX.show, p = V.meta.planes[i];
  V.plane = i;
  if (!p || !p.count) return;
  const q = RS * (p.first + Math.floor(p.count / 4));
  V.cx = V.rows[q + 4]; V.cy = V.rows[q + 5];
}

function divColor(v, css) {
  // diverging: blue (negative) to a neutral gray to orange (positive), clamped at +-2 voxels
  const t = Math.max(-1, Math.min(1, v / 2));
  const hex = (s) => { const m = s.trim().replace('#', ''); return [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16)); };
  const neg = hex(css.getPropertyValue('--neg') || '#2f7bf6'), pos = hex(css.getPropertyValue('--pos') || '#e0701a'), mid = hex(css.getPropertyValue('--neutral') || '#c9ccd6');
  const a = t < 0 ? neg : pos, k = Math.abs(t);
  return `rgb(${mid.map((m, i) => Math.round(m + (a[i] - m) * k)).join(',')})`;
}

function heat() {
  const V = VX.show; if (!V) return;
  const [h, w] = V.meta.shape, cv2 = $('vx-heat'), g = cv2.getContext('2d');
  const cw = Math.max(2, Math.floor(Math.min(900, cv2.parentNode.clientWidth || 600) / w));
  cv2.width = w * cw; cv2.height = h * cw;
  const css = getComputedStyle(document.documentElement);
  const surf = css.getPropertyValue('--panel').trim() || '#fff', line = css.getPropertyValue('--line').trim() || '#ccc';
  const tol = V.mode === 'signed' ? null : Number(V.mode);
  g.fillStyle = surf; g.fillRect(0, 0, cv2.width, cv2.height);
  for (let i = 0; i < h; i++) for (let j = 0; j < w; j++) {
    const k = i * w + j, s = V.state[k], x = j * cw, y = i * cw;
    if (s === 2) { g.fillStyle = css.getPropertyValue('--heldcell').trim() || '#ddd'; g.fillRect(x, y, cw, cw); continue; }   // held back: never drawn
    if (s === 1 || !Number.isFinite(V.res[k])) {                       // no value: hatched
      g.strokeStyle = line; g.lineWidth = 1; g.beginPath(); g.moveTo(x, y + cw); g.lineTo(x + cw, y); g.stroke(); continue;
    }
    const v = V.res[k];
    g.fillStyle = tol == null ? divColor(v, css) : (Math.abs(v) <= tol ? css.getPropertyValue('--snap').trim() : css.getPropertyValue('--pub').trim());
    g.fillRect(x, y, cw, cw);
  }
  const p = V.meta.planes[V.plane];
  if (p) { const i = V.meta.planes.indexOf(p); g.strokeStyle = css.getPropertyValue('--ink').trim(); g.lineWidth = 2; g.strokeRect(1, i * cw + 1, cv2.width - 2, cw - 2); }
  V.cw = cw;
  $('vx-heat-legend').innerHTML = tol == null
    ? `<span class="vx-grad" aria-hidden="true"></span><span>-2</span><span>0</span><span>+2 voxels (clamped)</span><span><i class="hatch"></i>no value</span><span><i style="background:var(--heldcell)"></i>held back for evaluation</span>`
    : `<span><i style="background:var(--snap)"></i>within ${tol} voxel${tol === 1 ? '' : 's'}</span><span><i style="background:var(--pub)"></i>not within</span><span><i class="hatch"></i>no value</span><span><i style="background:var(--heldcell)"></i>held back for evaluation</span>`;
}

async function showDraw() {
  const V = VX.show; if (!V) return;
  const cvs = $('vx-cv'), g = cvs.getContext('2d'), W = cvs.width, n = V.win, k = W / n;
  const p = V.meta.planes[V.plane], z = p ? p.z : 0;
  const x0 = Math.round(V.cx - n / 2), y0 = Math.round(V.cy - n / 2);
  $('vx-z').textContent = `z ${z}`;
  if (V.meta.volume) {
    const key = `${z}|${y0}|${x0}|${n}`;
    if (!V.ct || V.ct.key !== key) {
      const buf = await ctWindow(V.meta.volume, z, y0, x0, n);
      const img = new ImageData(n, n);
      for (let i = 0; i < n * n; i++) { img.data[4 * i] = img.data[4 * i + 1] = img.data[4 * i + 2] = buf[i]; img.data[4 * i + 3] = 255; }
      const off = document.createElement('canvas'); off.width = off.height = n; off.getContext('2d').putImageData(img, 0, 0);
      V.ct = { key, img: off };
    }
    g.imageSmoothingEnabled = false; g.drawImage(V.ct.img, 0, 0, W, W);
  } else {
    g.fillStyle = '#15171f'; g.fillRect(0, 0, W, W);
    g.fillStyle = 'rgba(255,255,255,.55)'; g.font = '14px system-ui, sans-serif'; g.fillText('Synthetic fixture: no CT', 14, 24);
  }
  const X = (x) => (x - x0 + 0.5) * k, Y = (y) => (y - y0 + 0.5) * k;
  const css = getComputedStyle(document.documentElement);
  const piece = (o, color, width, dash) => {
    g.strokeStyle = color; g.lineWidth = width; g.setLineDash(dash || []); g.lineCap = 'round'; g.beginPath();
    for (let q = p.first; q < p.first + p.count; q++) { const a = RS * q + o; g.moveTo(X(V.rows[a]), Y(V.rows[a + 1])); g.lineTo(X(V.rows[a + 2]), Y(V.rows[a + 3])); }
    g.stroke(); g.setLineDash([]);
  };
  if (p && p.count && !V.meta.volume) {
    // no CT in the fixture: a made-up sheet, drawn as a band along the made-up face
    piece(8, css.getPropertyValue('--band').trim() || '#d9c6a3', 7 * k);
  }
  if (p && p.count) {
    if ($('vx-l-pub').checked) piece(0, css.getPropertyValue('--pub').trim(), 2.5);
    if ($('vx-l-snap').checked) piece(4, css.getPropertyValue('--snap').trim(), 2.5);
    if ($('vx-l-truth').checked) { piece(8, '#11131c', 4.5, [7, 5]); piece(8, '#ffffff', 2, [7, 5]); }
  }
  g.fillStyle = '#fff'; g.fillRect(16, W - 22, 10 * k, 4);
  g.font = '13px system-ui, sans-serif'; g.fillText(V.meta.voxel_um ? `10 voxels (${Math.round(10 * V.meta.voxel_um)} µm)` : '10 voxels', 16, W - 30);
}

function heatCell(ev) {
  const V = VX.show; if (!V) return null;
  const b = $('vx-heat').getBoundingClientRect(), [h, w] = V.meta.shape;
  const j = Math.floor((ev.clientX - b.left) / b.width * w), i = Math.floor((ev.clientY - b.top) / b.height * h);
  if (i < 0 || j < 0 || i >= h || j >= w) return null;
  return { i, j, k: i * w + j };
}

// ---------------------------------------------------------------- wiring

function wireShowcase() {
  const heatCv = $('vx-heat'), tip = $('vx-tip');
  heatCv.addEventListener('mousemove', (ev) => {
    const c = heatCell(ev), V = VX.show; if (!c) { tip.hidden = true; return; }
    const s = V.state[c.k], v = V.res[c.k];
    tip.textContent = s === 2 ? 'held back for evaluation' : (s === 1 || !Number.isFinite(v)) ? 'no value here' : `${sgn(v)} voxels (row ${c.i}, column ${c.j})`;
    tip.hidden = false; tip.style.left = `${ev.offsetX + 14}px`; tip.style.top = `${ev.offsetY + 10}px`;
  });
  heatCv.addEventListener('mouseleave', () => { tip.hidden = true; });
  heatCv.addEventListener('click', (ev) => {
    const c = heatCell(ev), V = VX.show; if (!c || V.state[c.k] === 2) return;
    const x = V.xyz[3 * c.k], y = V.xyz[3 * c.k + 1], z = V.xyz[3 * c.k + 2];
    let best = Infinity, bi = 0;
    V.meta.planes.forEach((p, i) => { const d = Math.abs(p.z - z); if (d < best) { best = d; bi = i; } });
    V.plane = bi; V.cx = x; V.cy = y; heat(); showDraw();
  });
  document.querySelectorAll('input[name="vx-mode"]').forEach((r) => { r.onchange = () => { VX.show.mode = r.value; heat(); }; });
  ['vx-l-pub', 'vx-l-snap', 'vx-l-truth'].forEach((id) => { $(id).onchange = () => showDraw(); });
  $('vx-win').onchange = () => { VX.show.win = Number($('vx-win').value); showDraw(); };
  window.addEventListener('resize', () => heat());
}

async function vxInit() {
  VX.url = vxURL();
  let d;
  try {
    const r = await fetch(VX.url, { credentials: 'omit' });
    if (!r.ok) { if (params.get('vx')) throw new Error(`${r.status} ${VX.url}`); return; }   // no results yet: the tab stays hidden
    d = await r.json();
  } catch (e) {
    if (!params.get('vx')) return;
    $('vx-tabbtn').hidden = false; $('vx-error').hidden = false; $('vx-error').textContent = `Could not load the voxel-exact summary: ${e.message}`; return;
  }
  const bad = vxValid(d);
  if (bad.length) {
    if (!params.get('vx')) return;
    $('vx-tabbtn').hidden = false; $('vx-error').hidden = false; $('vx-error').textContent = `The voxel-exact summary does not validate: ${bad.slice(0, 3).join('; ')}`; return;
  }
  VX.doc = d; VX.fixture = d.fixture === true;
  $('vx-tabbtn').hidden = false;
  // a summary from ?vx=URL is someone else's file: say so, so a shared link cannot pass as this Space's results
  if (params.get('vx') && params.get('vx') !== 'fixture') { $('vx-error').hidden = false; $('vx-error').textContent = `Loaded from ${VX.url} (the vx parameter), not this Space's own results.`; }
  document.querySelectorAll('.vx-fixture').forEach((b) => { b.hidden = !VX.fixture; });
  document.body.classList.toggle('vx-fx', VX.fixture);
  renderCards();
  if (typeof table === 'function') table();
  const sc = d.showcase || [];
  $('vx-show-none').hidden = sc.length > 0; $('vx-show').hidden = !sc.length;
  if (sc.length) {
    $('vx-show-pick').innerHTML = sc.map((s) => `<option value="${esc(s.segment)}">${esc(s.scroll)} · ${esc(s.segment)}</option>`).join('');
    $('vx-show-pick').onchange = () => openShowcase($('vx-show-pick').value).catch((e) => { $('vx-show-title').textContent = e.message; });
    wireShowcase();
    await openShowcase(sc[0].segment).catch((e) => { $('vx-show-title').textContent = e.message; });
  }
  if (params.get('tab') === 'exact') tab('exact');
}

// the scroll's claim level for the All segments table (app.js)
window.vxClaim = (scroll) => {
  if (!VX.doc) return null;
  const s = VX.doc.scrolls.find((x) => x.scroll === scroll);
  return s ? VX_CLAIMS[s.claim] : 'Not scored';
};

Object.assign(window.snappedLabels, {
  voxelExact: () => (VX.doc ? JSON.parse(JSON.stringify(VX.doc)) : null),
  openShowcase: (segment) => openShowcase(segment),
});

window.vxReady = vxInit();
