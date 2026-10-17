// Scroll Lens viewer: draws the three slices of a cube in the visitor's browser.
//
// app.py loads this file as the js_on_load of a gr.HTML component. Gradio passes `element` (the component's root),
// `trigger(event, data)` (calls the Python listener for that event), `props` (props.value is the JSON view description
// that app.viewer_value() writes) and `watch('value', fn)`. The scan cube comes straight from the Vesuvius Challenge
// open-data bucket (it allows any origin) and the model layers from one compressed file the Space serves, so moving a
// slider, dragging, zooming and toggling a layer redraw at once, with no round trip to the server. Clicks for the
// search go to Python (trigger 'select'), which answers with the similarity map in a new view description.

const CHUNK = 128;
const PATCH = 8;
const OTHERS = [[1, 2], [0, 2], [0, 1]];      // per view: the axes of its rows and of its columns
const VIEW_NAMES = ['Top view (z)', 'Front view (y)', 'Side view (x)'];
const AXIS = ['z', 'y', 'x'];
const COLOURS = {ink: [235, 64, 52], surface: [64, 200, 96], clicks: [40, 220, 235], reference: [250, 180, 30]};
const MARKS = {pos: '#ffffff', neg: '#ff46c8'};
const LAYERS = [
  ['ink', 'Ink (3D ink model)', true, 'rgb(235,64,52)'],
  ['surface', 'Recto surface', false, 'rgb(64,200,96)'],
  ['clicks', 'Your clicks', true, 'rgb(40,220,235)'],
  ['reference', "Organisers' ink reference", true, 'rgb(250,180,30)'],
  ['pca', 'DINO colours', false, 'linear-gradient(90deg,#e33,#3c3,#36f)'],
  ['cross', 'Crosshair', true, '#fff'],
];
const MODES = [['pos', 'More like this'], ['neg', 'Not this'], ['move', 'Move only']];
const CT_CACHE_MAX = 4;                        // scan cubes kept in memory, for going back and forth
const TOP_FLOOR = 0.35;                        // opacity of the least similar patch inside Top % (app.TOP_FLOOR)

const st = {
  meta: null, key: null, rev: -1, size: 0, n: 0,
  ct: null, ink: null, surface: null, pca: null, ref: null, clk: null,
  lo: 0, hi: 255, autoLo: 0, autoHi: 255, bright: 0, contrast: 0,
  slices: [0, 0, 0], on: {}, mode: 'pos', opacity: 0.7, top: 8,
  refThr: 0, refTop: 1, clkThr: 0, clkTop: 1,
  marks: {pos: [], neg: []}, pending: [], inflight: null, clickSeq: 0, loading: 0, linkSlices: null,
};
const PAGE_ID = Math.random().toString(36).slice(2, 8);
for (const [k, , on] of LAYERS) st.on[k] = on;
const ctCache = new Map();

// ---------------------------------------------------------------- the page

element.innerHTML = `
<div class="slv">
  <div class="slv-bar">
    <div class="slv-group slv-layers">${LAYERS.map(([k, label, on, colour]) => `
      <label class="slv-chip"><input type="checkbox" data-layer="${k}" ${on ? 'checked' : ''}>
        <i style="background:${colour}"></i>${label}</label>`).join('')}
    </div>
    <div class="slv-group">
      <span class="slv-label">A click does</span>${MODES.map(([k, label], i) => `
      <label class="slv-chip"><input type="radio" name="slv-mode-${Math.random().toString(36).slice(2)}"
        data-mode="${k}" ${i === 0 ? 'checked' : ''}>${label}</label>`).join('')}
    </div>
    <details class="slv-more" open><summary>More controls</summary>
    <div class="slv-group slv-sliders">
      <label>Opacity <input type="range" data-set="opacity" min="0" max="1" step="0.05" value="0.7"></label>
      <label>Top % shown <input type="range" data-set="top" min="1" max="40" step="1" value="8"><b data-out="top">8</b></label>
      <label>Brightness <input type="range" data-set="bright" min="-100" max="100" step="1" value="0"></label>
      <label>Contrast <input type="range" data-set="contrast" min="-100" max="100" step="1" value="0"></label>
    </div>
    <div class="slv-group slv-buttons">
      <button data-act="centre" title="Put the crosshair back on the cube's point (C)">Centre on point</button>
      <button data-act="reset" title="Undo zoom and pan in all views (0)">Reset zoom</button>
      <button data-act="auto" title="Brightness and contrast back to automatic">Auto contrast</button>
      <button data-act="clear" title="Forget every More like this and Not this click">Clear clicks</button>
      <button data-act="use" title="Copy the crosshair's scan position to Your own point">Use crosshair as point</button>
      <button data-act="link" title="Copy a link that opens this cube at this crosshair">Copy link</button>
      <button data-act="3d" title="Ink and surface shells and similar patches in a rotatable 3D plot">Draw in 3D</button>
    </div>
    </details>
  </div>
  <div class="slv-status"><span data-out="status">Pick a cube from the gallery, or a point in a scan.</span>
    <progress data-out="progress" max="1" value="0" hidden></progress></div>
  <div class="slv-views">${[0, 1, 2].map(a => `
    <div class="slv-view">
      <div class="slv-title">${VIEW_NAMES[a]} <span data-out="idx${a}"></span></div>
      <canvas data-view="${a}" tabindex="0" aria-label="${VIEW_NAMES[a]}"></canvas>
      <input type="range" data-slice="${a}" min="0" max="255" value="128" aria-label="${AXIS[a]} slice">
    </div>`).join('')}
  </div>
  <div class="slv-readout" data-out="readout">&nbsp;</div>
  <div class="slv-help">Drag in a view: move the crosshair. Wheel or arrow keys: next slice (Shift: 8 at a time).
    Ctrl or Cmd with the wheel, or pinch: zoom. Right-drag or Shift-drag: pan. Double-click: reset zoom.
    Click: More like this (white cross), Not this (magenta cross), or nothing, as chosen above.
    Amber marks the organisers' ink reference (their threshold, cosine 0.5, and the Top % shown).</div>
</div>`;

const $ = sel => element.querySelector(sel);
if (window.matchMedia && window.matchMedia('(max-width: 600px)').matches) {
  element.querySelector('.slv-more').open = false;          // phones: the views come sooner
}
const out = name => element.querySelector(`[data-out="${name}"]`);
const V = [0, 1, 2].map(a => {
  const canvas = element.querySelector(`canvas[data-view="${a}"]`);
  const off = document.createElement('canvas');
  return {canvas, ctx: canvas.getContext('2d'), off, offctx: off.getContext('2d'), img: null,
          slider: element.querySelector(`input[data-slice="${a}"]`), zoom: 1, cx: 0, cy: 0, fit: 1};
});

function setStatus(text, progress) {
  out('status').textContent = text;
  const bar = out('progress');
  if (progress == null) { bar.hidden = true; } else { bar.hidden = false; bar.value = progress; }
}

// ---------------------------------------------------------------- drawing

const dirty = new Set();
const dirtyPaint = new Set();
let frame = 0;
function redraw(views = [0, 1, 2], paintOnly = false) {
  for (const a of views) (paintOnly ? dirtyPaint : dirty).add(a);
  if (!frame) frame = requestAnimationFrame(flush);
}
function flush() {
  frame = 0;
  for (const a of dirty) compose(a);
  for (const a of new Set([...dirty, ...dirtyPaint])) paint(a);
  dirty.clear();
  dirtyPaint.clear();
}

function windowLevel() {
  const width = Math.max(1, (st.autoHi - st.autoLo) * Math.pow(2, -st.contrast / 50));
  const centre = (st.autoLo + st.autoHi) / 2 - (st.bright / 100) * (st.autoHi - st.autoLo) / 2;
  st.lo = centre - width / 2;
  st.hi = centre + width / 2;
}

function compose(a) {
  const S = st.size;
  if (!S) return;
  const v = V[a];
  if (!v.img || v.img.width !== S) {
    v.off.width = S;
    v.off.height = S;
    v.img = v.offctx.createImageData(S, S);
  }
  const n = st.n, [r, c] = OTHERS[a];
  const strides = [S * S, S, 1], pst = [n * n, n, 1];
  const s = st.slices[a];
  const base = s * strides[a], pbase = (s >> 3) * pst[a];
  const rs = strides[r], cs = strides[c], prs = pst[r], pcs = pst[c];
  const img = v.img.data;
  const ct = st.ct, ink = st.on.ink ? st.ink : null, sf = st.on.surface ? st.surface : null;
  const pca = st.on.pca ? st.pca : null, ref = st.on.reference ? st.ref : null, clk = st.on.clicks ? st.clk : null;
  const op = st.opacity, lo = st.lo, k = 255 / Math.max(1e-6, st.hi - st.lo);
  const [ir, ig, ib] = COLOURS.ink, [sr, sg, sb] = COLOURS.surface;
  const [rr, rg, rb] = COLOURS.reference, [cr, cg, cb] = COLOURS.clicks;
  const refThr = st.refThr, refK = 1 / Math.max(1e-6, st.refTop - st.refThr);
  const clkThr = st.clkThr, clkK = 1 / Math.max(1e-6, st.clkTop - st.clkThr);
  const pw = 0.6 * op;
  let p = 0;
  for (let i = 0; i < S; i++) {
    const row = base + i * rs, prow = pbase + (i >> 3) * prs;
    for (let j = 0; j < S; j++) {
      const idx = row + j * cs;
      let g = ct ? (ct[idx] - lo) * k : 0;
      g = g < 0 ? 0 : (g > 255 ? 255 : g);
      let R = g, G = g, B = g;
      const pidx = prow + (j >> 3) * pcs;
      if (pca) {
        const q = pidx * 3;
        R = R * (1 - pw) + pca[q] * pw; G = G * (1 - pw) + pca[q + 1] * pw; B = B * (1 - pw) + pca[q + 2] * pw;
      }
      if (sf) {
        const al = sf[idx] * op / 255;
        if (al > 0) { R += (sr - R) * al; G += (sg - G) * al; B += (sb - B) * al; }
      }
      if (ink) {
        const al = ink[idx] * op / 255;
        if (al > 0) { R += (ir - R) * al; G += (ig - G) * al; B += (ib - B) * al; }
      }
      if (ref) {
        const sv = ref[pidx];
        if (sv >= refThr) {
          const al = (TOP_FLOOR + (1 - TOP_FLOOR) * Math.min(1, (sv - refThr) * refK)) * op;
          R += (rr - R) * al; G += (rg - G) * al; B += (rb - B) * al;
        }
      }
      if (clk) {
        const sv = clk[pidx];
        if (sv >= clkThr) {
          const al = (TOP_FLOOR + (1 - TOP_FLOOR) * Math.min(1, (sv - clkThr) * clkK)) * op;
          R += (cr - R) * al; G += (cg - G) * al; B += (cb - B) * al;
        }
      }
      img[p++] = R; img[p++] = G; img[p++] = B; img[p++] = 255;
    }
  }
  v.offctx.putImageData(v.img, 0, 0);
  out(`idx${a}`).textContent = `${AXIS[a]} ${s} of ${S - 1}`;
  if (+v.slider.value !== s) v.slider.value = s;
}

function transform(a) {
  const v = V[a], W = v.canvas.width, sc = v.fit * v.zoom;
  return {sc, ox: W / 2 - v.cx * sc, oy: v.canvas.height / 2 - v.cy * sc};
}

function paint(a) {
  const v = V[a], ctx = v.ctx, W = v.canvas.width, H = v.canvas.height;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = '#0b0f14';
  ctx.fillRect(0, 0, W, H);
  const S = st.size;
  if (!S || !v.img) return;
  const {sc, ox, oy} = transform(a);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(v.off, ox, oy, S * sc, S * sc);
  const [r, c] = OTHERS[a];
  const dpr = window.devicePixelRatio || 1;
  if (st.on.cross) {
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    ctx.lineWidth = Math.max(1, dpr);
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    const y = oy + (st.slices[r] + 0.5) * sc, x = ox + (st.slices[c] + 0.5) * sc;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    ctx.restore();
  }
  // the clicks made in this cube whose patch lies in this slice
  const tok = st.slices[a] >> 3;
  for (const kind of ['pos', 'neg']) {
    const list = st.marks[kind].concat(st.pending.filter(m => m.kind === kind).map(m => m.voxel));
    for (const vox of list) {
      if ((vox[a] >> 3) !== tok) continue;
      const x = ox + (vox[c] + 0.5) * sc, y = oy + (vox[r] + 0.5) * sc, h = 6 * dpr + 2;
      ctx.strokeStyle = 'rgba(0,0,0,0.7)';
      ctx.lineWidth = 4 * dpr;
      ctx.beginPath(); ctx.moveTo(x - h, y); ctx.lineTo(x + h, y); ctx.moveTo(x, y - h); ctx.lineTo(x, y + h); ctx.stroke();
      ctx.strokeStyle = MARKS[kind];
      ctx.lineWidth = 2 * dpr;
      ctx.beginPath(); ctx.moveTo(x - h, y); ctx.lineTo(x + h, y); ctx.moveTo(x, y - h); ctx.lineTo(x, y + h); ctx.stroke();
    }
  }
}

function resize() {
  const dpr = window.devicePixelRatio || 1;
  for (const v of V) {
    const w = Math.max(120, v.canvas.parentElement.clientWidth);
    v.canvas.style.width = `${w}px`;
    v.canvas.style.height = `${w}px`;
    const px = Math.round(w * dpr);
    if (v.canvas.width !== px) { v.canvas.width = px; v.canvas.height = px; }
    v.fit = st.size ? px / st.size : 1;
  }
  redraw([0, 1, 2], true);
}
new ResizeObserver(resize).observe(element.querySelector('.slv-views'));

// ---------------------------------------------------------------- similarity thresholds

function topThreshold(sim, pct) {
  const sorted = Float32Array.from(sim).sort();
  const best = sorted[sorted.length - 1];
  if (best - sorted[0] < 1e-6) return [Infinity, Infinity];   // a flat map (the concept cancels out): show nothing
  const k = Math.min(sorted.length - 1, Math.max(0, Math.floor(sorted.length * (1 - pct / 100))));
  return [sorted[k], best];
}
function updateThresholds() {
  if (st.ref) {
    // the organisers' reference never lights a patch below their own threshold (tau, cosine 0.5)
    [st.refThr, st.refTop] = topThreshold(st.ref, st.top);
    const tau = st.meta && st.meta.tau != null ? st.meta.tau : 0.5;
    if (st.refThr < tau) st.refThr = tau;
    if (st.refTop < st.refThr) st.refThr = Infinity;
  }
  if (st.clk) [st.clkThr, st.clkTop] = topThreshold(st.clk, st.top);
}

// ---------------------------------------------------------------- loading a cube

function chunkRange(o, size) {
  const out = [];
  for (let k = Math.floor(o / CHUNK); k <= Math.floor((o + size - 1) / CHUNK); k++) out.push(k);
  return out;
}

async function fetchRetry(url, tries = 3) {
  let last;
  for (let t = 0; t < tries; t++) {
    try {
      const resp = await fetch(url);
      if (resp.status === 404) return null;      // no chunk stored there: all outside the scroll (403 is a refusal)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.arrayBuffer();
    } catch (e) {
      last = e;
      await new Promise(res => setTimeout(res, 800 * (t + 1)));
    }
  }
  throw last;
}

async function loadCT(m, token) {
  const S = m.size, [oz, oy, ox] = m.origin;
  const ckey = `${m.volume}:${m.origin.join(',')}:${S}`;
  if (ctCache.has(ckey)) { const ct = ctCache.get(ckey); ctCache.delete(ckey); ctCache.set(ckey, ct); return ct; }
  const ct = new Uint8Array(S * S * S);
  const keys = [];
  for (const cz of chunkRange(oz, S)) for (const cy of chunkRange(oy, S)) for (const cx of chunkRange(ox, S)) keys.push([cz, cy, cx]);
  let done = 0;
  const one = async key => {
    const buf = await fetchRetry(`${m.ct.base}/${key.join('/')}`);
    if (token !== st.loading) return;
    done += 1;
    setStatus(`Reading the scan from the open-data bucket: ${done} of ${keys.length} chunks`, done / keys.length);
    if (!buf) return;
    if (buf.byteLength !== CHUNK ** 3) throw new Error(`chunk ${key} has ${buf.byteLength} bytes`);
    const src = new Uint8Array(buf);
    const z0 = Math.max(oz, key[0] * CHUNK), z1 = Math.min(oz + S, (key[0] + 1) * CHUNK);
    const y0 = Math.max(oy, key[1] * CHUNK), y1 = Math.min(oy + S, (key[1] + 1) * CHUNK);
    const x0 = Math.max(ox, key[2] * CHUNK), x1 = Math.min(ox + S, (key[2] + 1) * CHUNK);
    for (let z = z0; z < z1; z++) {
      for (let y = y0; y < y1; y++) {
        const sOff = ((z - key[0] * CHUNK) * CHUNK + (y - key[1] * CHUNK)) * CHUNK + (x0 - key[2] * CHUNK);
        const dOff = ((z - oz) * S + (y - oy)) * S + (x0 - ox);
        ct.set(src.subarray(sOff, sOff + (x1 - x0)), dOff);
      }
    }
  };
  const queue = keys.slice();
  await Promise.all(Array.from({length: Math.min(8, keys.length)}, async () => {
    while (queue.length) await one(queue.shift());
  }));
  ctCache.set(ckey, ct);
  while (ctCache.size > CT_CACHE_MAX) ctCache.delete(ctCache.keys().next().value);
  return ct;
}

function autoWindow(ct) {
  // the 0.5th and 99.5th percentiles of the papyrus (non-zero) voxels, as the server did
  const hist = new Uint32Array(256);
  for (let i = 0; i < ct.length; i++) hist[ct[i]]++;
  const total = ct.length - hist[0];
  if (!total) return [0, 255];
  let acc = 0, lo = 1, hi = 255;
  for (let v = 1; v < 256; v++) { acc += hist[v]; if (acc >= total * 0.005) { lo = v; break; } }
  acc = 0;
  for (let v = 1; v < 256; v++) { acc += hist[v]; if (acc >= total * 0.995) { hi = v; break; } }
  return [lo, Math.max(hi, lo + 1)];
}

async function loadLayers(m) {
  if (!m.data) return {};
  const resp = await fetch(m.data);
  if (!resp.ok) throw new Error(`model layers: HTTP ${resp.status}`);
  let buf = await resp.arrayBuffer();
  const head = new Uint8Array(buf, 0, 2);
  if (head[0] === 0x1f && head[1] === 0x8b) {
    buf = await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  }
  const hlen = new DataView(buf).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
  const dataStart = (4 + hlen + 3) & ~3;                     // arrays start 4-byte aligned after the header
  const out = {};
  for (const a of header.arrays) {
    const start = dataStart + a.offset;
    if (a.dtype === 'uint8') out[a.name] = new Uint8Array(buf, start, a.nbytes);
    else if (a.dtype === 'float32') out[a.name] = new Float32Array(buf, start, a.nbytes / 4);
  }
  return out;
}

function decodeSim(b64) {
  if (!b64) return null;
  const bin = atob(b64), n = bin.length / 2, outArr = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
    if (v & 0x8000) v -= 0x10000;
    outArr[i] = v / 8192;
  }
  return outArr;
}

function linkSlicesOnce() {
  // a link made with Copy link carries the crosshair as s=z,y,x (cube voxels); use it for the first cube only
  try {
    const q = new URLSearchParams(window.location.search);
    if (!q.get('s')) return null;
    const s = q.get('s').split(',').map(Number);
    return s.length === 3 && s.every(Number.isFinite) ? s : null;
  } catch (e) { return null; }
}
st.linkSlices = linkSlicesOnce();

async function onValue(raw) {
  let m = null;
  try { m = raw ? JSON.parse(raw) : null; } catch (e) { m = null; }
  if (!m || !m.key) return;
  if (m.key !== st.key) {
    await newCube(m);
  } else if (m.rev !== st.rev) {
    applyClicks(m);
    redraw();
  }
}

function applyClicks(m) {
  st.meta = m;
  st.rev = m.rev;
  st.clk = decodeSim(m.clicks && m.clicks.sim);
  st.marks = {pos: (m.clicks && m.clicks.pos) || [], neg: (m.clicks && m.clicks.neg) || []};
  const acked = new Set((m.clicks && m.clicks.acked) || []);
  st.pending = st.pending.filter(p => !acked.has(p.id));
  st.flushTries = 0;
  if (st.inflight) { clearTimeout(st.inflight); st.inflight = null; }
  updateThresholds();
  flushClicks();
}

// Clicks go to Python one request at a time, each carrying every click not yet acknowledged, so a click made while
// another is being handled is sent next instead of being dropped; the ids stop a resent click counting twice.
function flushClicks() {
  if (st.inflight || !st.pending.length || !st.key) return;
  if ((st.flushTries = (st.flushTries || 0) + 1) > 3) {
    st.pending = [];
    st.flushTries = 0;
    setStatus('The Space did not answer these clicks; try again in a moment.', null);
    redraw([0, 1, 2], true);
    return;
  }
  st.inflight = setTimeout(() => { st.inflight = null; flushClicks(); }, 8000);
  trigger('select', {key: st.key, clicks: st.pending.map(p => ({id: p.id, index: p.voxel, value: p.kind}))});
}

async function newCube(m) {
  const token = ++st.loading;
  const S = m.size;
  const same = st.size === S;
  st.key = m.key;
  st.size = S;
  st.n = S / PATCH;
  st.ct = st.ink = st.surface = st.pca = st.ref = null;
  st.pending = [];
  applyClicks(m);
  const local = m.point.map((p, i) => Math.min(S - 1, Math.max(0, p - m.origin[i])));
  st.slices = st.linkSlices ? st.linkSlices.map(v => Math.min(S - 1, Math.max(0, v | 0))) : local;
  st.linkSlices = null;
  for (const v of V) {
    v.slider.max = S - 1;
    if (!same) { v.zoom = 1; }
    v.cx = S / 2; v.cy = S / 2;
  }
  resize();
  setStatus(`Loading ${m.title || m.volume}...`, 0);
  try {
    const [ct, layers] = await Promise.all([loadCT(m, token), loadLayers(m)]);
    if (token !== st.loading) return;
    st.ct = ct;
    Object.assign(st, {ink: layers.ink || null, surface: layers.surface || null, pca: layers.pca || null,
                       ref: layers.ref || null});
    [st.autoLo, st.autoHi] = autoWindow(ct);
    windowLevel();
    updateThresholds();
    const missing = ['ink', 'surface', 'dino'].filter(k => !(m.has || {})[k]);
    setStatus(`${m.title || m.volume}: cube of ${S}³ voxels at z ${m.origin[0]}, y ${m.origin[1]}, x ${m.origin[2]}`
              + (missing.length ? ` (not run: ${missing.join(', ')})` : ''), null);
    redraw();
  } catch (e) {
    if (token !== st.loading) return;
    setStatus(`Could not load this cube: ${e.message}. Try again in a minute.`, null);
    console.error('scroll lens viewer', e);
  }
}

// ---------------------------------------------------------------- controls

element.querySelectorAll('input[data-layer]').forEach(box => box.addEventListener('change', () => {
  st.on[box.dataset.layer] = box.checked;
  redraw();
}));
element.querySelectorAll('input[data-mode]').forEach(radio => radio.addEventListener('change', () => {
  if (radio.checked) st.mode = radio.dataset.mode;
}));
element.querySelectorAll('input[data-set]').forEach(input => input.addEventListener('input', () => {
  const k = input.dataset.set, val = +input.value;
  st[k] = val;
  if (k === 'top') { out('top').textContent = val; updateThresholds(); }
  if (k === 'bright' || k === 'contrast') windowLevel();
  redraw();
}));
V.forEach((v, a) => v.slider.addEventListener('input', () => {
  st.slices[a] = +v.slider.value;
  redraw();
}));

function setSlider(name, value) {
  const input = element.querySelector(`input[data-set="${name}"]`);
  input.value = value;
  st[name] = value;
}

element.querySelectorAll('button[data-act]').forEach(btn => btn.addEventListener('click', () => {
  const act = btn.dataset.act, m = st.meta;
  if (act === 'centre' && m) {
    st.slices = m.point.map((p, i) => Math.min(st.size - 1, Math.max(0, p - m.origin[i])));
    redraw();
  } else if (act === 'reset') {
    for (const v of V) { v.zoom = 1; v.cx = st.size / 2; v.cy = st.size / 2; }
    redraw([0, 1, 2], true);
  } else if (act === 'auto') {
    setSlider('bright', 0); setSlider('contrast', 0); windowLevel(); redraw();
  } else if (act === 'clear') {
    st.pending = [];
    trigger('clear', {key: st.key});
  } else if (act === 'use' && m) {
    trigger('apply', {volume: m.volume, point: st.slices.map((s, i) => s + m.origin[i])});
    flash(btn, 'Copied to Your own point');
  } else if (act === 'link' && m) {
    copyLink(btn);
  } else if (act === '3d') {
    trigger('submit', {key: st.key, top: st.top,
                       layers: Object.keys(st.on).filter(k => st.on[k])});
    flash(btn, 'Drawing below...');
  }
}));

function flash(btn, text) {
  const old = btn.textContent;
  btn.textContent = text;
  setTimeout(() => { btn.textContent = old; }, 1500);
}

function copyLink(btn) {
  const m = st.meta, q = new URLSearchParams();
  if (m.cube_id) q.set('cube', m.cube_id);
  else {
    q.set('v', m.volume);
    m.point.forEach((p, i) => q.set(AXIS[i], p));
    q.set('size', m.request_size || m.size);
  }
  q.set('s', st.slices.join(','));
  const url = `${window.location.origin}${window.location.pathname}?${q}`;
  const show = () => setStatus(`Link: ${url}`, null);
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(() => flash(btn, 'Link copied'), show);
  } else {
    show();
  }
}

// ---------------------------------------------------------------- mouse, touch and keys in the views

function toVoxel(a, ev) {
  const v = V[a], rect = v.canvas.getBoundingClientRect();
  const dpr = v.canvas.width / rect.width;
  const {sc, ox, oy} = transform(a);
  const col = Math.floor(((ev.clientX - rect.left) * dpr - ox) / sc);
  const row = Math.floor(((ev.clientY - rect.top) * dpr - oy) / sc);
  const S = st.size;
  if (row < 0 || col < 0 || row >= S || col >= S) return null;
  const [r, c] = OTHERS[a], vox = [0, 0, 0];
  vox[a] = st.slices[a];
  vox[r] = row;
  vox[c] = col;
  return vox;
}

function readout(vox) {
  const m = st.meta;
  if (!vox || !m) { out('readout').innerHTML = '&nbsp;'; return; }
  const S = st.size, n = st.n;
  const idx = (vox[0] * S + vox[1]) * S + vox[2];
  const pidx = ((vox[0] >> 3) * n + (vox[1] >> 3)) * n + (vox[2] >> 3);
  const parts = [`cube z ${vox[0]}, y ${vox[1]}, x ${vox[2]}`,
                 `scan z ${vox[0] + m.origin[0]}, y ${vox[1] + m.origin[1]}, x ${vox[2] + m.origin[2]}`];
  if (st.ct) parts.push(`CT ${st.ct[idx]}`);
  if (st.ink) parts.push(`ink ${Math.round(st.ink[idx] / 2.55)}%`);
  if (st.surface) parts.push(`surface ${Math.round(st.surface[idx] / 2.55)}%`);
  if (st.ref) parts.push(`reference cos ${st.ref[pidx].toFixed(2)}`);
  if (st.clk) parts.push(`your concept ${st.clk[pidx].toFixed(2)}`);
  out('readout').textContent = parts.join(' · ');
}

function zoomAt(a, factor, clientX, clientY) {
  const v = V[a], rect = v.canvas.getBoundingClientRect();
  const dpr = v.canvas.width / rect.width;
  const {sc, ox, oy} = transform(a);
  const sx = (clientX - rect.left) * dpr, sy = (clientY - rect.top) * dpr;
  const ix = (sx - ox) / sc, iy = (sy - oy) / sc;            // image point under the cursor stays put
  v.zoom = Math.min(32, Math.max(1, v.zoom * factor));
  const nsc = v.fit * v.zoom;
  v.cx = ix - (sx - v.canvas.width / 2) / nsc;
  v.cy = iy - (sy - v.canvas.height / 2) / nsc;
  if (v.zoom === 1) { v.cx = st.size / 2; v.cy = st.size / 2; }
  redraw([a], true);
}

function moveCrosshair(a, vox) {
  const [r, c] = OTHERS[a];
  if (st.slices[r] === vox[r] && st.slices[c] === vox[c]) return;
  st.slices[r] = vox[r];
  st.slices[c] = vox[c];
  redraw([r, c]);
  redraw([a], true);
}

function sendClick(kind, vox) {
  if (!st.meta || !st.meta.has || !st.meta.has.dino) {
    setStatus('This cube has no 3D DINO embeddings, so it cannot be searched. Run it with the 3D DINO model.', null);
    return;
  }
  st.pending.push({id: `${PAGE_ID}-${++st.clickSeq}`, kind, voxel: vox});
  if (kind === 'pos' && !st.on.clicks) {
    st.on.clicks = true;
    element.querySelector('input[data-layer="clicks"]').checked = true;
  }
  redraw([0, 1, 2], true);
  flushClicks();
}

V.forEach((v, a) => {
  const cv = v.canvas;
  const pointers = new Map();
  let gesture = null;

  cv.addEventListener('contextmenu', ev => ev.preventDefault());
  cv.addEventListener('pointerdown', ev => {
    if (!st.size) return;
    cv.focus({preventScroll: true});
    try { cv.setPointerCapture(ev.pointerId); } catch (e) { /* a synthetic pointer: dragging still works */ }
    pointers.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    if (pointers.size === 2) {                                   // two fingers: pinch to zoom, move to pan
      const [p, q] = [...pointers.values()];
      gesture = {type: 'pinch', d: Math.hypot(p.x - q.x, p.y - q.y), mx: (p.x + q.x) / 2, my: (p.y + q.y) / 2};
      return;
    }
    const pan = ev.button === 2 || ev.button === 1 || ev.shiftKey;
    gesture = {type: pan ? 'pan' : 'pending', x: ev.clientX, y: ev.clientY, lx: ev.clientX, ly: ev.clientY};
    ev.preventDefault();
  });
  cv.addEventListener('pointermove', ev => {
    if (!st.size) return;
    if (pointers.has(ev.pointerId)) pointers.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    const vox = toVoxel(a, ev);
    readout(vox);
    if (!gesture) return;
    if (gesture.type === 'pinch' && pointers.size === 2) {
      const [p, q] = [...pointers.values()];
      const d = Math.hypot(p.x - q.x, p.y - q.y), mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
      zoomAt(a, d / Math.max(1, gesture.d), mx, my);
      const sc = v.fit * v.zoom, dpr = cv.width / cv.getBoundingClientRect().width;
      v.cx -= (mx - gesture.mx) * dpr / sc;
      v.cy -= (my - gesture.my) * dpr / sc;
      Object.assign(gesture, {d, mx, my});
      redraw([a], true);
      return;
    }
    if (gesture.type === 'pan') {
      const sc = v.fit * v.zoom, dpr = cv.width / cv.getBoundingClientRect().width;
      v.cx -= (ev.clientX - gesture.lx) * dpr / sc;
      v.cy -= (ev.clientY - gesture.ly) * dpr / sc;
      gesture.lx = ev.clientX;
      gesture.ly = ev.clientY;
      redraw([a], true);
      return;
    }
    if (gesture.type === 'pending' && Math.hypot(ev.clientX - gesture.x, ev.clientY - gesture.y) > 4) {
      gesture.type = 'drag';
    }
    if (gesture.type === 'drag' && vox) moveCrosshair(a, vox);
  });
  const end = ev => {
    pointers.delete(ev.pointerId);
    if (!gesture) return;
    if (gesture.type === 'pinch') { if (pointers.size === 0) gesture = null; return; }
    if (gesture.type === 'pending') {
      const vox = toVoxel(a, ev);
      if (vox) {
        if (st.mode === 'move') moveCrosshair(a, vox);
        else sendClick(st.mode, vox);
      }
    }
    gesture = null;
  };
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', ev => { pointers.delete(ev.pointerId); gesture = null; });
  cv.addEventListener('pointerleave', () => { if (!gesture) readout(null); });
  cv.addEventListener('dblclick', () => {
    v.zoom = 1; v.cx = st.size / 2; v.cy = st.size / 2;
    redraw([a], true);
  });

  let wheelAcc = 0;
  cv.addEventListener('wheel', ev => {
    if (!st.size) return;
    ev.preventDefault();
    if (ev.ctrlKey || ev.metaKey) {
      zoomAt(a, Math.exp(-ev.deltaY * 0.0025), ev.clientX, ev.clientY);
      return;
    }
    // a mouse wheel notch (deltaY of about 100 pixels, or a line) is one slice; a trackpad's small deltas add up
    let steps;
    if (ev.deltaMode !== 0 || Math.abs(ev.deltaY) >= 50) {
      steps = Math.sign(ev.deltaY);
      wheelAcc = 0;
    } else {
      wheelAcc += ev.deltaY;
      steps = Math.trunc(wheelAcc / 30);
      wheelAcc -= steps * 30;
    }
    if (!steps) return;
    stepSlice(a, -steps * (ev.shiftKey ? 8 : 1));
  }, {passive: false});

  cv.addEventListener('keydown', ev => {
    if (!st.size) return;
    const big = ev.shiftKey ? 8 : 1;
    const keys = {ArrowUp: big, ArrowRight: big, PageUp: 8, ArrowDown: -big, ArrowLeft: -big, PageDown: -8};
    if (ev.key in keys) { stepSlice(a, keys[ev.key]); ev.preventDefault(); return; }
    if (ev.key === '+' || ev.key === '=') { const r = cv.getBoundingClientRect(); zoomAt(a, 1.25, r.left + r.width / 2, r.top + r.height / 2); }
    else if (ev.key === '-' || ev.key === '_') { const r = cv.getBoundingClientRect(); zoomAt(a, 0.8, r.left + r.width / 2, r.top + r.height / 2); }
    else if (ev.key === '0') { v.zoom = 1; v.cx = st.size / 2; v.cy = st.size / 2; redraw([a], true); }
    else if (ev.key === 'c' || ev.key === 'C') element.querySelector('button[data-act="centre"]').click();
    else return;
    ev.preventDefault();
  });
});

function stepSlice(a, delta) {
  const s = Math.min(st.size - 1, Math.max(0, st.slices[a] + delta));
  if (s === st.slices[a]) return;
  st.slices[a] = s;
  redraw();
}

// ---------------------------------------------------------------- start

watch('value', () => onValue(props.value));
if (props.value) onValue(props.value);
