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
const COLORS = {ink: [235, 64, 52], surface: [64, 200, 96], clicks: [40, 220, 235], reference: [250, 180, 30]};
const MARKS = {pos: '#ffffff', neg: '#ff46c8'};
const LAYERS = [
  ['ink', 'Ink (3D ink model)', true, 'rgb(235,64,52)'],
  ['surface', 'Recto surface', false, 'rgb(64,200,96)'],
  ['clicks', 'Your clicks', true, 'rgb(40,220,235)'],
  ['reference', "Organizers' ink reference", true, 'rgb(250,180,30)'],
  ['pca', 'DINO colors', false, 'linear-gradient(90deg,#e33,#3c3,#36f)'],
  ['cross', 'Crosshair', true, '#fff'],
];
const MODES = [['move', 'Move only'], ['pos', 'More like this'], ['neg', 'Not this']];   // the first is the default
const CT_CACHE_MAX = 4;                        // scan cubes kept in memory, for going back and forth
const TOP_FLOOR = 0.35;                        // opacity of the least similar patch inside Top % (app.TOP_FLOOR)

const st = {
  meta: null, key: null, rev: -1, size: 0, n: 0,
  ct: null, ink: null, surface: null, pca: null, ref: null, clk: null,
  lo: 0, hi: 255, autoLo: 0, autoHi: 255, bright: 0, contrast: 0,
  slices: [0, 0, 0], on: {}, mode: 'move', opacity: 0.7, top: 8,
  refThr: 0, refTop: 1, clkThr: 0, clkTop: 1,
  marks: {pos: [], neg: []}, pending: [], inflight: null, clickSeq: 0, loading: 0, linkSlices: null,
};
const PAGE_ID = Math.random().toString(36).slice(2, 8);
const MODE_NAME = `slv-mode-${PAGE_ID}`;                 // one radio group for the three click modes
for (const [k, , on] of LAYERS) st.on[k] = on;
const ctCache = new Map();

// ---------------------------------------------------------------- the page

element.innerHTML = `
<div class="slv">
  <div class="slv-bar">
    <div class="slv-group slv-layers">${LAYERS.map(([k, label, on, color]) => `
      <label class="slv-chip"><input type="checkbox" data-layer="${k}" ${on ? 'checked' : ''}>
        <i style="background:${color}"></i>${label}</label>`).join('')}
    </div>
    <div class="slv-group">
      <span class="slv-label">A click does</span>${MODES.map(([k, label], i) => `
      <label class="slv-chip"><input type="radio" name="${MODE_NAME}"
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
      <button data-act="center" title="Put the crosshair back on the cube's point (C)">Center on point</button>
      <button data-act="reset" title="Undo zoom and pan in all views (0)">Reset zoom</button>
      <button data-act="auto" title="Brightness and contrast back to automatic">Auto contrast</button>
      <button data-act="undo" title="Forget your last click (Ctrl or Cmd + Z)">Undo click</button>
      <button data-act="clear" title="Forget every More like this and Not this click">Clear clicks</button>
      <button data-act="use" title="Copy the crosshair's scan position to Your own point">Use crosshair as point</button>
      <button data-act="link" title="Copy a link that opens this cube at this crosshair">Copy link</button>
      <button data-act="view3d" class="slv-3d-toggle" title="Turn the three views into one 3D space you can rotate">3D view</button>
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
  <div class="slv-3d" hidden>
    <div class="slv-group slv-3d-bar">
      <label class="slv-chip"><input type="checkbox" data-3d="slices" checked>Slices</label>
      <label class="slv-chip"><input type="checkbox" data-3d="points" checked>Layers as points in 3D</label>
      <label class="slv-chip"><input type="checkbox" data-3d="box" checked>Cube outline</label>
      <label class="slv-chip"><input type="checkbox" data-3d="spin">Spin</label>
      <span class="slv-buttons"><button data-act="camera" title="Look at the whole cube again">Reset camera</button></span>
    </div>
    <canvas class="slv-3d-canvas" aria-label="3D view of the cube"></canvas>
    <div class="slv-group slv-3d-sliders">${[0, 1, 2].map(a => `
      <label>${AXIS[a]} <input type="range" data-slice3="${a}" min="0" max="255" value="128"><b data-out="s3${a}"></b></label>`).join('')}
    </div>
  </div>
  <div class="slv-readout" data-out="readout">&nbsp;</div>
  <div class="slv-help">Drag in a view: move the crosshair. Wheel or arrow keys: next slice (Shift: 8 at a time).
    Ctrl or Cmd with the wheel, or pinch: zoom. Right-drag or Shift-drag: pan. Double-click: reset zoom.
    Click: More like this (white cross), Not this (magenta cross), or nothing, as chosen above.
    Amber marks the organizers' ink reference (their threshold, cosine 0.5, and the Top % shown).
    3D view: drag to rotate, wheel to zoom, right-drag to pan; click a slice to search or move the crosshair.</div>
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
  const composed = [...dirty];
  for (const a of dirty) compose(a);
  for (const a of new Set([...dirty, ...dirtyPaint])) paint(a);
  dirty.clear();
  dirtyPaint.clear();
  if (g3.on && g3.ready) update3D(composed);
}

function windowLevel() {
  const width = Math.max(1, (st.autoHi - st.autoLo) * Math.pow(2, -st.contrast / 50));
  const center = (st.autoLo + st.autoHi) / 2 - (st.bright / 100) * (st.autoHi - st.autoLo) / 2;
  st.lo = center - width / 2;
  st.hi = center + width / 2;
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
  const [ir, ig, ib] = COLORS.ink, [sr, sg, sb] = COLORS.surface;
  const [rr, rg, rb] = COLORS.reference, [cr, cg, cb] = COLORS.clicks;
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
    // the organizers' reference never lights a patch below their own threshold (tau, cosine 0.5)
    [st.refThr, st.refTop] = topThreshold(st.ref, st.top);
    const tau = st.meta && st.meta.tau != null ? st.meta.tau : 0.5;
    if (st.refThr < tau) st.refThr = tau;
    if (st.refTop < st.refThr) st.refThr = Infinity;
  }
  if (st.clk) [st.clkThr, st.clkTop] = topThreshold(st.clk, st.top);
  if (g3.on && g3.ready) buildPatchClouds();
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
    while (queue.length && token === st.loading) await one(queue.shift());
  }));
  if (token !== st.loading) return null;                 // another cube was picked: never cache a part-read scan
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
  // a link made with Copy link carries the crosshair as s=z,y,x (cube voxels), for the cube the link names: a gallery
  // cube (cube=ID) or the cube run at a point (v, z, y, x); it is applied when that cube opens, and to no other
  try {
    const q = new URLSearchParams(window.location.search);
    if (!q.get('s')) return null;
    const s = q.get('s').split(',').map(Number);
    if (s.length !== 3 || !s.every(Number.isFinite)) return null;
    if (q.get('cube')) return {s, cube: q.get('cube')};
    const point = ['z', 'y', 'x'].map(k => Number(q.get(k)));
    return q.get('v') && point.every(Number.isFinite) ? {s, v: q.get('v'), point} : null;
  } catch (e) { return null; }
}
st.linkSlices = linkSlicesOnce();

async function onValue(raw) {
  let m = null;
  try { m = raw ? JSON.parse(raw) : null; } catch (e) { m = null; }
  if (!m || !m.key) return;
  if (m.ack_only) {                                        // clicks the server could not use: stop resending them
    if (m.key === st.key) {
      const acked = new Set((m.clicks && m.clicks.acked) || []);
      st.pending = st.pending.filter(p => !acked.has(p.id));
      if (st.inflight) { clearTimeout(st.inflight); st.inflight = null; }
      st.flushTries = 0;
      redraw([0, 1, 2], true);
    }
    return;
  }
  if (m.key !== st.key || st.failed) {
    await newCube(m);
  } else if (m.rev > st.rev) {
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
  st.inflight = setTimeout(() => { st.inflight = null; flushClicks(); }, 15000);
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
  st.failed = false;
  st.pending = [];
  st.rev = -1;
  applyClicks(m);
  const local = m.point.map((p, i) => Math.min(S - 1, Math.max(0, p - m.origin[i])));
  const link = st.linkSlices;
  const forThisCube = link && (link.cube ? link.cube === m.cube_id
    : (link.v && link.v.toLowerCase() === String(m.volume).toLowerCase() && link.point.every((p, i) => p === m.point[i])));
  st.slices = forThisCube ? link.s.map(v => Math.min(S - 1, Math.max(0, v | 0))) : local;
  if (forThisCube) st.linkSlices = null;
  for (const v of V) {
    v.slider.max = S - 1;
    if (!same) { v.zoom = 1; }
    v.cx = S / 2; v.cy = S / 2;
  }
  resize();
  redraw();                                                // black views, not the previous cube, while this one loads
  setStatus(`Loading ${m.title || m.volume}...`, 0);
  try {
    const [ct, layers] = await Promise.all([loadCT(m, token), loadLayers(m)]);
    if (token !== st.loading || !ct) return;
    st.ct = ct;
    Object.assign(st, {ink: layers.ink || null, surface: layers.surface || null, pca: layers.pca || null,
                       ref: layers.ref || null});
    [st.autoLo, st.autoHi] = autoWindow(ct);
    windowLevel();
    updateThresholds();
    if (g3.on && g3.ready) build3D();
    const missing = ['ink', 'surface', 'dino'].filter(k => !(m.has || {})[k]);
    setStatus(`${m.title || m.volume}: cube of ${S}³ voxels at z ${m.origin[0]}, y ${m.origin[1]}, x ${m.origin[2]}`
              + (missing.length ? ` (not run: ${missing.join(', ')})` : ''), null);
    redraw();
  } catch (e) {
    if (token !== st.loading) return;
    st.failed = true;                                      // picking the same cube again retries the load
    setStatus(`Could not load this cube: ${e.message}. Pick it again in a minute to retry.`, null);
    console.error('scroll lens viewer', e);
  }
}

// ---------------------------------------------------------------- controls

element.querySelectorAll('input[data-layer]').forEach(box => box.addEventListener('change', () => {
  st.on[box.dataset.layer] = box.checked;
  redraw();
  if (g3.on && g3.ready) visibility3D();
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
  if (act === 'center' && m) {
    st.slices = m.point.map((p, i) => Math.min(st.size - 1, Math.max(0, p - m.origin[i])));
    redraw();
  } else if (act === 'reset') {
    for (const v of V) { v.zoom = 1; v.cx = st.size / 2; v.cy = st.size / 2; }
    redraw([0, 1, 2], true);
  } else if (act === 'auto') {
    setSlider('bright', 0); setSlider('contrast', 0); windowLevel(); redraw();
  } else if (act === 'undo') {
    if (st.pending.length) { st.pending.pop(); redraw([0, 1, 2], true); }
    else trigger('undo', {key: st.key});
  } else if (act === 'clear') {
    st.pending = [];
    trigger('clear', {key: st.key});
  } else if (act === 'use' && m) {
    trigger('apply', {volume: m.volume, point: st.slices.map((s, i) => s + m.origin[i])});
    flash(btn, 'Copied to Your own point');
  } else if (act === 'link' && m) {
    copyLink(btn);
  } else if (act === 'view3d') {
    toggle3D(btn);
  } else if (act === 'camera') {
    resetCamera();
  }
}));

function flash(btn, text) {
  if (btn.dataset.label === undefined) btn.dataset.label = btn.textContent;
  clearTimeout(btn._flash);
  btn.textContent = text;
  btn._flash = setTimeout(() => { btn.textContent = btn.dataset.label; }, 1500);
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
  if (!st.ct) {
    setStatus('This cube is still loading; click again in a moment.', null);
    return;
  }
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

const DOUBLE_CLICK_MS = 260;
let clickTimer = 0;

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
        clearTimeout(clickTimer);
        if (st.mode === 'move') moveCrosshair(a, vox);
        else clickTimer = setTimeout(() => sendClick(st.mode, vox), DOUBLE_CLICK_MS);
      }
    }
    gesture = null;
  };
  cv.addEventListener('pointerup', end);
  cv.addEventListener('pointercancel', ev => { pointers.delete(ev.pointerId); gesture = null; });
  cv.addEventListener('pointerleave', () => { if (!gesture) readout(null); });
  cv.addEventListener('dblclick', () => {
    clearTimeout(clickTimer);                             // the two clicks of a double-click search nothing
    v.zoom = 1; v.cx = st.size / 2; v.cy = st.size / 2;
    redraw([a], true);
  });

  let wheelAcc = 0;
  cv.addEventListener('wheel', ev => {
    if (!st.size) return;
    ev.preventDefault();
    if (ev.ctrlKey || ev.metaKey) {
      zoomAt(a, Math.exp(-(ev.deltaY || ev.deltaX) * 0.0025), ev.clientX, ev.clientY);
      return;
    }
    // a mouse wheel notch (deltaY of about 100 pixels, or a line) is one slice; a trackpad's small deltas add up
    const dy = ev.deltaY || (ev.shiftKey ? ev.deltaX : 0);   // Shift turns a wheel notch sideways on many systems
    let steps;
    if (ev.deltaMode !== 0 || Math.abs(dy) >= 50) {
      steps = Math.sign(dy);
      wheelAcc = 0;
    } else {
      wheelAcc += dy;
      steps = Math.trunc(wheelAcc / 30);
      wheelAcc -= steps * 30;
    }
    if (!steps) return;
    stepSlice(a, -steps * (ev.shiftKey ? 8 : 1));
  }, {passive: false});

  cv.addEventListener('keydown', ev => {
    if (!st.size) return;
    if ((ev.ctrlKey || ev.metaKey) && (ev.key === 'z' || ev.key === 'Z') && !ev.shiftKey && !ev.altKey) {
      element.querySelector('button[data-act="undo"]').click();
      ev.preventDefault();
      return;
    }
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;     // the browser's own shortcuts (zoom, copy, history)
    const big = ev.shiftKey ? 8 : 1;
    const keys = {ArrowUp: big, ArrowRight: big, PageUp: 8, ArrowDown: -big, ArrowLeft: -big, PageDown: -8};
    if (ev.key in keys) { stepSlice(a, keys[ev.key]); ev.preventDefault(); return; }
    if (ev.key === '+' || ev.key === '=') { const r = cv.getBoundingClientRect(); zoomAt(a, 1.25, r.left + r.width / 2, r.top + r.height / 2); }
    else if (ev.key === '-' || ev.key === '_') { const r = cv.getBoundingClientRect(); zoomAt(a, 0.8, r.left + r.width / 2, r.top + r.height / 2); }
    else if (ev.key === '0') { v.zoom = 1; v.cx = st.size / 2; v.cy = st.size / 2; redraw([a], true); }
    else if (ev.key === 'c' || ev.key === 'C') element.querySelector('button[data-act="center"]').click();
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


// ---------------------------------------------------------------- the 3D view
//
// One three.js scene (three 0.160, as Unroll uses) holding the cube: the three slices as planes textured with the
// same images the flat views draw, so they move and recolor live; the cube's outline; ink and recto surface voxels
// as points; and the patches like your concept or like the organizers' reference as larger glowing points. World
// axes: x to the right, the scan's z up (z grows downward in the scan, as in the front and side views), y toward you.

const THREE_URL = 'https://cdn.jsdelivr.net/npm/three@0.160.0/+esm';
const ORBIT_URL = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js/+esm';
const MAX_POINTS = 160000;               // voxels drawn per layer in 3D; denser layers are thinned evenly
const g3 = {on: false, ready: false, loading: null, T: null, renderer: null, scene: null, camera: null, controls: null,
            planes: [], textures: [], box: null, clouds: {}, raf: 0, size: 0, key: null,
            show: {slices: true, points: true, box: true}, down: null};
const panel3 = element.querySelector('.slv-3d');
const canvas3 = element.querySelector('.slv-3d-canvas');

function world(z, y, x) {
  const h = st.size / 2;
  return [x - h, h - z, y - h];
}

async function load3D() {
  if (g3.T) return;
  if (!g3.loading) {
    g3.loading = Promise.all([import(THREE_URL), import(ORBIT_URL)]).then(([T, O]) => {
      g3.T = T;
      g3.Orbit = O.OrbitControls;
    });
  }
  await g3.loading;
}

async function toggle3D(btn) {
  if (!g3.on) {
    btn.disabled = true;
    setStatus('Loading the 3D view...', null);
    try {
      await load3D();
    } catch (e) {
      btn.disabled = false;
      g3.loading = null;
      setStatus(`Could not load the 3D view (${e.message}); the flat views still work.`, null);
      return;
    }
    btn.disabled = false;
    g3.on = true;
    element.querySelector('.slv-views').hidden = true;
    panel3.hidden = false;
    btn.textContent = btn.dataset.label = 'Flat views';
    if (!g3.renderer) init3D();
    size3D();
    build3D();
    loop3D();
    setStatus('3D view: drag to rotate, wheel to zoom, right-drag to pan. Click a slice to search it.', null);
  } else {
    g3.on = false;
    cancelAnimationFrame(g3.raf);
    panel3.hidden = true;
    element.querySelector('.slv-views').hidden = false;
    btn.textContent = btn.dataset.label = '3D view';
    resize();
    redraw();
  }
}

function init3D() {
  const T = g3.T;
  g3.renderer = new T.WebGLRenderer({canvas: canvas3, antialias: true});
  g3.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  g3.renderer.setClearColor(0x0b0f14);
  g3.scene = new T.Scene();
  g3.camera = new T.PerspectiveCamera(40, 1, 1, 10000);
  g3.controls = new g3.Orbit(g3.camera, canvas3);
  g3.controls.enableDamping = true;
  g3.controls.dampingFactor = 0.07;
  g3.controls.autoRotateSpeed = 1.2;
  g3.ready = true;
  new ResizeObserver(() => { if (g3.on) size3D(); }).observe(panel3);
  canvas3.addEventListener('pointerdown', ev => { g3.down = {x: ev.clientX, y: ev.clientY, button: ev.button}; });
  canvas3.addEventListener('pointerup', ev => {
    const d = g3.down;
    g3.down = null;
    if (!d || d.button !== 0 || Math.hypot(ev.clientX - d.x, ev.clientY - d.y) > 4) return;
    const hit = pick3D(ev);
    if (!hit) return;
    if (st.mode === 'move') { st.slices = hit.voxel.slice(); redraw(); }
    else sendClick(st.mode, hit.voxel);
  });
  canvas3.addEventListener('pointermove', ev => {
    if (ev.buttons) return;
    const hit = pick3D(ev);
    readout(hit ? hit.voxel : null);
  });
  canvas3.addEventListener('pointerleave', () => readout(null));
  element.querySelectorAll('input[data-3d]').forEach(box => box.addEventListener('change', () => {
    const k = box.dataset['3d'];
    if (k === 'spin') g3.controls.autoRotate = box.checked;
    else { g3.show[k] = box.checked; visibility3D(); }
  }));
  element.querySelectorAll('input[data-slice3]').forEach(input => input.addEventListener('input', () => {
    st.slices[+input.dataset.slice3] = +input.value;
    redraw();
  }));
}

function size3D() {
  const w = Math.max(200, panel3.clientWidth);
  const h = Math.round(Math.min(window.innerHeight * 0.72, w * 0.7));
  canvas3.style.width = `${w}px`;
  canvas3.style.height = `${h}px`;
  g3.renderer.setSize(w, h, false);
  g3.camera.aspect = w / h;
  g3.camera.updateProjectionMatrix();
}

function resetCamera() {
  if (!g3.ready) return;
  const S = st.size || 256;
  g3.camera.position.set(S * 1.25, S * 0.85, S * 1.55);
  g3.camera.near = S / 100;
  g3.camera.far = S * 20;
  g3.camera.updateProjectionMatrix();
  g3.controls.target.set(0, 0, 0);
  g3.controls.minDistance = S * 0.2;
  g3.controls.maxDistance = S * 6;
  g3.controls.update();
}

function clear3D() {
  for (const obj of [...g3.planes, g3.box, ...Object.values(g3.clouds)]) {
    if (!obj) continue;
    g3.scene.remove(obj);
    obj.geometry.dispose();
    obj.material.dispose();
  }
  for (const t of g3.textures) t.dispose();
  g3.planes = []; g3.textures = []; g3.box = null; g3.clouds = {};
}

function build3D() {
  const T = g3.T, S = st.size;
  if (!S) return;
  const fresh = g3.key !== st.key;
  g3.size = S;
  clear3D();
  for (let a = 0; a < 3; a++) {
    compose(a);                                            // the textures read the flat views' images
    const tex = new T.CanvasTexture(V[a].off);
    tex.flipY = false;
    tex.magFilter = T.NearestFilter;
    tex.minFilter = T.LinearFilter;
    tex.generateMipmaps = false;
    tex.colorSpace = T.SRGBColorSpace;
    const geo = new T.BufferGeometry();
    geo.setAttribute('position', new T.BufferAttribute(new Float32Array(12), 3));
    geo.setAttribute('uv', new T.BufferAttribute(new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]), 2));
    geo.setIndex([0, 2, 1, 1, 2, 3]);
    const mesh = new T.Mesh(geo, new T.MeshBasicMaterial({map: tex, side: T.DoubleSide}));
    mesh.userData.axis = a;
    g3.scene.add(mesh);
    g3.planes.push(mesh);
    g3.textures.push(tex);
    placePlane(a);
  }
  g3.box = new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(S, S, S)),
                              new T.LineBasicMaterial({color: 0xc9d4de, transparent: true, opacity: 0.45}));
  g3.scene.add(g3.box);
  buildVoxelCloud('ink', st.ink, 0xeb4034, 0.5);
  buildVoxelCloud('surface', st.surface, 0x40c860, 0.25);
  buildPatchClouds();
  visibility3D();
  for (const input of element.querySelectorAll('input[data-slice3]')) input.max = S - 1;
  syncSliders3D();
  if (fresh) { g3.key = st.key; resetCamera(); }
}

function placePlane(a) {
  const S = st.size, [r, c] = OTHERS[a], s = st.slices[a] + 0.5;
  const pos = g3.planes[a].geometry.attributes.position;
  [[0, 0], [0, S], [S, 0], [S, S]].forEach(([row, col], i) => {
    const v = [0, 0, 0];
    v[a] = s; v[r] = row; v[c] = col;
    const [X, Y, Z] = world(v[0], v[1], v[2]);
    pos.setXYZ(i, X, Y, Z);
  });
  pos.needsUpdate = true;
  g3.planes[a].geometry.computeBoundingSphere();
  g3.planes[a].geometry.computeBoundingBox();
}

function buildVoxelCloud(name, vol, color, opacity) {
  if (!vol) return;
  const T = g3.T, S = st.size;
  let count = 0;
  for (let i = 0; i < vol.length; i++) if (vol[i] >= 128) count++;
  if (!count) return;
  const stride = Math.max(1, Math.ceil(count / MAX_POINTS));
  const pts = new Float32Array(Math.ceil(count / stride) * 3);
  let k = 0, seen = 0;
  for (let i = 0; i < vol.length; i++) {
    if (vol[i] < 128) continue;
    if (seen++ % stride) continue;
    const z = Math.floor(i / (S * S)), y = Math.floor(i / S) % S, x = i % S;
    const [X, Y, Z] = world(z + 0.5, y + 0.5, x + 0.5);
    pts[k++] = X; pts[k++] = Y; pts[k++] = Z;
  }
  const geo = new T.BufferGeometry();
  geo.setAttribute('position', new T.BufferAttribute(pts.subarray(0, k), 3));
  const mat = new T.PointsMaterial({color, size: Math.max(0.9, 1.1 * stride ** (1 / 3)), sizeAttenuation: true,
                                    transparent: true, opacity, depthWrite: false});
  g3.clouds[name] = new T.Points(geo, mat);
  g3.scene.add(g3.clouds[name]);
}

function patchCloud(name, sim, thr, color, opacity) {
  const T = g3.T, n = st.n;
  if (g3.clouds[name]) {
    g3.scene.remove(g3.clouds[name]);
    g3.clouds[name].geometry.dispose();
    g3.clouds[name].material.dispose();
    delete g3.clouds[name];
  }
  if (!sim || !Number.isFinite(thr)) return;
  const out = [];
  for (let i = 0; i < sim.length; i++) {
    if (sim[i] < thr) continue;
    const tz = Math.floor(i / (n * n)), ty = Math.floor(i / n) % n, tx = i % n;
    out.push(...world(tz * PATCH + PATCH / 2, ty * PATCH + PATCH / 2, tx * PATCH + PATCH / 2));
  }
  if (!out.length) return;
  const geo = new T.BufferGeometry();
  geo.setAttribute('position', new T.BufferAttribute(new Float32Array(out), 3));
  g3.clouds[name] = new T.Points(geo, new T.PointsMaterial({color, size: PATCH * 0.8, sizeAttenuation: true,
    transparent: true, opacity, depthWrite: false, blending: T.AdditiveBlending}));
  g3.scene.add(g3.clouds[name]);
}

function buildPatchClouds() {
  if (!g3.ready || !st.size) return;
  patchCloud('reference', st.ref, st.refThr, 0xfab41e, 0.55);
  patchCloud('clicks', st.clk, st.clkThr, 0x28dceb, 0.7);
  const marks = [];
  for (const kind of ['pos', 'neg']) for (const v of st.marks[kind]) marks.push({kind, v});
  if (g3.clouds.marks) {
    g3.scene.remove(g3.clouds.marks);
    g3.clouds.marks.geometry.dispose();
    g3.clouds.marks.material.dispose();
    delete g3.clouds.marks;
  }
  if (marks.length) {
    const T = g3.T, pos = [], col = [];
    for (const {kind, v} of marks) {
      pos.push(...world(v[0] + 0.5, v[1] + 0.5, v[2] + 0.5));
      col.push(...(kind === 'pos' ? [1, 1, 1] : [1, 0.27, 0.78]));
    }
    const geo = new T.BufferGeometry();
    geo.setAttribute('position', new T.BufferAttribute(new Float32Array(pos), 3));
    geo.setAttribute('color', new T.BufferAttribute(new Float32Array(col), 3));
    g3.clouds.marks = new T.Points(geo, new T.PointsMaterial({size: PATCH * 1.2, vertexColors: true,
                                                             sizeAttenuation: true, depthTest: false}));
    g3.scene.add(g3.clouds.marks);
  }
  visibility3D();
}

function visibility3D() {
  if (!g3.ready) return;
  for (const p of g3.planes) p.visible = g3.show.slices;
  if (g3.box) g3.box.visible = g3.show.box;
  const want = {ink: st.on.ink, surface: st.on.surface, reference: st.on.reference, clicks: st.on.clicks, marks: true};
  for (const [name, cloud] of Object.entries(g3.clouds)) cloud.visible = g3.show.points && !!want[name];
}

function syncSliders3D() {
  element.querySelectorAll('input[data-slice3]').forEach(input => {
    const a = +input.dataset.slice3;
    if (+input.value !== st.slices[a]) input.value = st.slices[a];
    out(`s3${a}`).textContent = st.slices[a];
  });
}

function update3D(composed) {
  if (!g3.planes.length) return;
  if (g3.size !== st.size) { build3D(); return; }        // a cube of another size: new planes and textures
  for (const a of composed) {
    if (!g3.planes[a]) continue;
    g3.textures[a].needsUpdate = true;
    placePlane(a);
  }
  syncSliders3D();
}

function pick3D(ev) {
  if (!g3.ready || !g3.show.slices || !st.size) return null;
  const T = g3.T, rect = canvas3.getBoundingClientRect();
  const ndc = new T.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
  const ray = new T.Raycaster();
  ray.setFromCamera(ndc, g3.camera);
  const hit = ray.intersectObjects(g3.planes, false)[0];
  if (!hit) return null;
  const h = st.size / 2, p = hit.point;
  const vox = [h - p.y, p.z + h, p.x + h].map(v => Math.min(st.size - 1, Math.max(0, Math.floor(v))));
  vox[hit.object.userData.axis] = st.slices[hit.object.userData.axis];
  return {voxel: vox};
}

function loop3D() {
  if (!g3.on) return;
  g3.controls.update();
  g3.renderer.render(g3.scene, g3.camera);
  g3.raf = requestAnimationFrame(loop3D);
}

// ---------------------------------------------------------------- start

watch('value', () => onValue(props.value));
if (props.value) onValue(props.value);
