// Snapped Labels: the snapped-label dataset on live X-ray CT. Everything is read in the browser: the dataset's index
// and per-segment cross sections from Hugging Face, the CT slice from the Vesuvius Challenge open-data bucket by HTTP
// range reads (uint8, 128^3 chunks, no compressor). ?data=URL reads another copy of the dataset; ?seg=ID&z=Z opens a
// segment at a plane.
'use strict';

const params = new URLSearchParams(location.search);
const DATA = (params.get('data') || 'https://huggingface.co/datasets/SharpMeow/vesuvius-snapped-labels/resolve/main').replace(/\/+$/, '');
const $ = (id) => document.getElementById(id);
const fmt = (n) => (n == null ? 'n/a' : Number(n).toLocaleString('en-US'));
const pct = (a, b) => (b ? `${(100 * a / b).toFixed(1)}%` : 'n/a');

const S = { index: [], seg: null, view: null, rows: null, plane: 0, cx: 0, cy: 0, win: 192, order: [], at: 0, abort: null };

async function getJSON(url) { const r = await fetch(url, { credentials: 'omit' }); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }

// ---------------------------------------------------------------- CT slices

const zarrays = new Map();
function zarray(vol, L) { const k = `${vol}/${L}`; if (!zarrays.has(k)) zarrays.set(k, getJSON(`${k}/.zarray`)); return zarrays.get(k); }

async function rangeGet(url, off, len, signal) {
  const r = await fetch(url, { headers: { Range: `bytes=${off}-${off + len - 1}` }, signal, credentials: 'omit' });
  if (r.status === 404 || r.status === 403) return null;          // a chunk the masked scan leaves out
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return new Uint8Array(await r.arrayBuffer());
}

// A level-0 window [y0, y0+n) x [x0, x0+n) of plane z, as a Uint8Array of n*n (0 outside the scan).
async function ctWindow(vol, z, y0, x0, n, signal) {
  const m = await zarray(vol, 0);
  const [Z, Y, X] = m.shape, [cz, cy, cx] = m.chunks;
  if (m.compressor) throw new Error('compressed scan: the viewer reads uncompressed chunks only');
  const out = new Uint8Array(n * n);
  if (z < 0 || z >= Z) return out;
  const jobs = [];
  for (let by = Math.floor(Math.max(0, y0) / cy); by * cy < Math.min(Y, y0 + n); by++) {
    for (let bx = Math.floor(Math.max(0, x0) / cx); bx * cx < Math.min(X, x0 + n); bx++) {
      const url = `${vol}/0/${Math.floor(z / cz)}/${by}/${bx}`;
      jobs.push(rangeGet(url, (z % cz) * cy * cx, cy * cx, signal).then((b) => {
        if (!b) return;
        for (let j = 0; j < cy; j++) {
          const yy = by * cy + j - y0; if (yy < 0 || yy >= n) continue;
          for (let i = 0; i < cx; i++) { const xx = bx * cx + i - x0; if (xx >= 0 && xx < n) out[yy * n + xx] = b[j * cx + i]; }
        }
      }));
    }
  }
  await Promise.all(jobs);
  return out;
}

// ---------------------------------------------------------------- drawing

// A plane's rows are line pieces, float32: published ax ay bx by, then snapped ax ay bx by.
const R = 8;
const cv = $('cv'), cx2d = cv.getContext('2d');
let ctImage = null;   // {key, img}

function planeRows() {
  const p = S.view.planes[S.plane];
  return p ? S.rows.subarray(p.first * R, (p.first + p.count) * R) : new Float32Array(0);
}

function ringOrder() {
  // the plane's line pieces in order around their centroid: Next and Previous walk along the label
  const r = planeRows(), n = r.length / R;
  if (!n) { S.order = []; return; }
  let mx = 0, my = 0;
  for (let i = 0; i < n; i++) { mx += r[R * i]; my += r[R * i + 1]; }
  mx /= n; my /= n;
  const idx = Array.from({ length: n }, (_, i) => i);
  idx.sort((a, b) => Math.atan2(r[R * a + 1] - my, r[R * a] - mx) - Math.atan2(r[R * b + 1] - my, r[R * b] - mx));
  S.order = idx;
}

function centreOn(k) {
  const r = planeRows();
  if (!S.order.length) return;
  S.at = ((k % S.order.length) + S.order.length) % S.order.length;
  const i = S.order[S.at];
  S.cx = r[R * i]; S.cy = r[R * i + 1];
}

function middle() {
  // the position in S.order of the piece nearest the plane's centroid: a start on the label, away from its ends
  const r = planeRows(), n = r.length / R;
  if (!n) return 0;
  let mx = 0, my = 0;
  for (let i = 0; i < n; i++) { mx += r[R * i]; my += r[R * i + 1]; }
  mx /= n; my /= n;
  let best = Infinity, bi = 0;
  for (let i = 0; i < n; i++) { const d = (r[R * i] - mx) ** 2 + (r[R * i + 1] - my) ** 2; if (d < best) { best = d; bi = i; } }
  return S.order.indexOf(bi);
}

async function draw() {
  if (!S.view) return;
  const p = S.view.planes[S.plane];
  $('z-out').textContent = p ? p.z : '';
  const n = S.win, x0 = Math.round(S.cx - n / 2), y0 = Math.round(S.cy - n / 2), z = p ? p.z : 0;
  const key = `${S.view.volume}|${z}|${y0}|${x0}|${n}`;
  const W = cv.width, k = W / n;
  if (!ctImage || ctImage.key !== key) {
    if (S.abort) S.abort.abort();
    S.abort = new AbortController();
    msg('Reading CT…');
    let buf;
    try { buf = await ctWindow(S.view.volume, z, y0, x0, n, S.abort.signal); } catch (e) { if (e.name === 'AbortError') return; msg(`CT read failed: ${e.message}`); return; }
    // contrast: 1st to 99.5th percentile of the window's nonzero voxels
    const h = new Uint32Array(256); let c = 0;
    for (const v of buf) if (v) { h[v]++; c++; }
    let lo = 0, hi = 255, acc = 0;
    for (let v = 0; v < 256; v++) { acc += h[v]; if (acc >= 0.01 * c) { lo = v; break; } }
    acc = 0;
    for (let v = 0; v < 256; v++) { acc += h[v]; if (acc >= 0.995 * c) { hi = v; break; } }
    const img = new ImageData(n, n), s = 255 / Math.max(1, hi - lo);
    for (let i = 0; i < n * n; i++) { const g = Math.max(0, Math.min(255, (buf[i] - lo) * s)); img.data[4 * i] = img.data[4 * i + 1] = img.data[4 * i + 2] = g; img.data[4 * i + 3] = 255; }
    const off = document.createElement('canvas'); off.width = n; off.height = n; off.getContext('2d').putImageData(img, 0, 0);
    ctImage = { key, img: off };
    msg('');
  }
  cx2d.imageSmoothingEnabled = false;
  cx2d.drawImage(ctImage.img, 0, 0, W, W);
  const r = planeRows(), m = r.length / R;
  const X = (x) => (x - x0 + 0.5) * k, Y = (y) => (y - y0 + 0.5) * k;
  const css = getComputedStyle(document.documentElement);
  const lw = Math.max(1.5, Math.min(3, k * 0.4));
  if ($('l-move').checked) {
    // grey strokes from the published line to the snapped one, at each piece's midpoint
    cx2d.strokeStyle = css.getPropertyValue('--move').trim() || 'rgba(200,200,200,.6)';
    cx2d.lineWidth = Math.max(1, lw * 0.45); cx2d.beginPath();
    for (let i = 0; i < m; i++) {
      const a = R * i, px = (r[a] + r[a + 2]) / 2, py = (r[a + 1] + r[a + 3]) / 2, qx = (r[a + 4] + r[a + 6]) / 2, qy = (r[a + 5] + r[a + 7]) / 2;
      if (Math.abs(px - qx) + Math.abs(py - qy) < 0.05) continue;
      cx2d.moveTo(X(px), Y(py)); cx2d.lineTo(X(qx), Y(qy));
    }
    cx2d.stroke();
  }
  const line = (o, colour) => {
    cx2d.strokeStyle = colour; cx2d.lineWidth = lw; cx2d.lineCap = 'round'; cx2d.beginPath();
    for (let i = 0; i < m; i++) { const a = R * i + o; cx2d.moveTo(X(r[a]), Y(r[a + 1])); cx2d.lineTo(X(r[a + 2]), Y(r[a + 3])); }
    cx2d.stroke();
  };
  if ($('l-pub').checked) line(0, css.getPropertyValue('--pub').trim() || '#f08a24');
  if ($('l-snap').checked) line(4, css.getPropertyValue('--snap').trim() || '#2f7bf6');
  // scale bar: 10 voxels
  const um = S.view.voxel_um || null;
  cx2d.fillStyle = '#fff'; cx2d.fillRect(16, W - 22, 10 * k, 4);
  cx2d.font = '13px system-ui, sans-serif'; cx2d.fillText(um ? `10 voxels (${Math.round(10 * um)} µm)` : '10 voxels', 16, W - 30);
  history.replaceState(null, '', `?${new URLSearchParams({ ...(params.get('data') ? { data: params.get('data') } : {}), seg: S.seg.segment, z: String(z) })}`);
}

function msg(t) { const e = $('cv-msg'); e.textContent = t; e.hidden = !t; }

// ---------------------------------------------------------------- segments

function card(seg) {
  const v = seg.vertices_released, sn = seg.snapped, ab = seg.abstained, held = seg.vertices_held_back;
  const fl = seg.filled != null ? seg.filled : 0, lip = seg.left_in_place != null ? seg.left_in_place : ab - fl;
  const pb = seg.placed_by;
  const mv = seg.move_voxels || {};
  const fine = pb ? `<div><b>${pct(pb.finer_scan, v)}</b><span>placed in the 2.4 µm scan</span></div>` : '';
  const base = `${DATA}/${seg.path}`;
  $('seg-card').innerHTML = `
    <div class="row">
      <div><b>${fmt(v)}</b><span>released vertices</span></div>
      <div><b>${pct(sn, v)}</b><span>snapped onto a face</span></div>
      <div><b>${pct(fl, v)}</b><span>filled from measured neighbours</span></div>
      ${fine}
      <div><b>${mv.median != null ? mv.median.toFixed(2) : 'n/a'} vx</b><span>median move (90th pct ${mv.p90 != null ? mv.p90.toFixed(1) : 'n/a'})</span></div>
      <div><b>${fmt(held)}</b><span>held back for evaluation</span></div>
    </div>
    <div class="meter"><i style="width:${100 * sn / Math.max(1, v + held)}%;background:var(--snap)"></i><i style="width:${100 * fl / Math.max(1, v + held)}%;background:var(--fill)"></i><i style="width:${100 * lip / Math.max(1, v + held)}%;background:var(--pub)"></i><i style="width:${100 * held / Math.max(1, v + held)}%;background:var(--held)"></i></div>
    <div class="legend"><span><i style="background:var(--snap)"></i>snapped</span><span><i style="background:var(--fill)"></i>filled (drawn at the published position)</span><span><i style="background:var(--pub)"></i>left in place</span><span><i style="background:var(--held)"></i>held back</span></div>
    <pre class="cmd"><code>hf download SharpMeow/vesuvius-snapped-labels --repo-type dataset --include "${seg.path}/*" --local-dir snapped-labels</code></pre>
    <p class="hint">Mesh: <a href="${base}/snapped.tifxyz/meta.json" target="_blank" rel="noopener">${seg.path}/snapped.tifxyz</a> · record: <a href="${base}/release.json" target="_blank" rel="noopener">release.json</a> · CT: <a href="${S.view ? S.view.volume : '#'}/.zattrs" target="_blank" rel="noopener">${S.view ? S.view.volume.split('/').pop() : ''}</a></p>`;
}

async function openSeg(seg, z) {
  S.seg = seg;
  document.querySelectorAll('#seg-list li').forEach((li) => li.classList.toggle('on', li.dataset.id === seg.segment));
  $('v-title').textContent = `${seg.scroll} · ${seg.segment} · ${seg.method}`;
  msg('Loading cross sections…');
  const base = `${DATA}/viewer/${seg.scroll}/${seg.segment}`;
  const [view, bin] = await Promise.all([getJSON(`${base}.json`), fetch(`${base}.bin`, { credentials: 'omit' }).then((r) => { if (!r.ok) throw new Error(`${r.status}`); return r.arrayBuffer(); })]);
  S.view = view; S.rows = new Float32Array(bin);
  const zr = $('z-range'); zr.max = String(Math.max(0, view.planes.length - 1));
  let pi = Math.floor(view.planes.length / 2);
  if (z != null) { let best = Infinity; view.planes.forEach((p, i) => { const d = Math.abs(p.z - z); if (d < best) { best = d; pi = i; } }); }
  // start on the busiest plane near the middle, so the first view shows the label
  if (z == null) { let best = -1; for (let i = Math.floor(pi * 0.6); i <= Math.min(view.planes.length - 1, Math.ceil(pi * 1.4)); i++) if (view.planes[i].count > best) { best = view.planes[i].count; pi = i; } }
  S.plane = pi; zr.value = String(pi);
  ringOrder(); centreOn(middle());
  card(seg);
  ctImage = null;
  await draw();
}

function listSegs() {
  const sc = $('f-scroll').value, q = $('f-find').value.trim().toLowerCase();
  const ul = $('seg-list'); ul.innerHTML = '';
  for (const s of S.index) {
    if (sc && s.scroll !== sc) continue;
    if (q && !s.segment.toLowerCase().includes(q)) continue;
    const li = document.createElement('li'); li.dataset.id = s.segment;
    const nm = s.segment.replace(/^\d{14}-/, '');
    li.innerHTML = `<span>${nm}</span><small>${pct(s.snapped, s.vertices_released)}</small>`;
    li.title = s.segment;
    li.onclick = () => openSeg(s).catch((e) => msg(e.message));
    if (S.seg && S.seg.segment === s.segment) li.classList.add('on');
    ul.appendChild(li);
  }
}

function table() {
  const tb = document.querySelector('#tbl tbody'); tb.innerHTML = '';
  for (const s of S.index) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${s.scroll}</td><td>${s.segment}</td><td>${s.method}</td><td class="n">${fmt(s.vertices_released)}</td><td class="n">${pct(s.snapped, s.vertices_released)}</td><td class="n">${s.move_voxels && s.move_voxels.median != null ? s.move_voxels.median.toFixed(2) : 'n/a'}</td><td class="n">${fmt(s.vertices_held_back)}</td>`;
    tr.onclick = () => { tab('view'); openSeg(s).catch((e) => msg(e.message)); };
    tb.appendChild(tr);
  }
}

function tab(name) {
  document.querySelectorAll('.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  document.querySelectorAll('[data-pane]').forEach((p) => { p.hidden = p.dataset.pane !== name; });
}

// ---------------------------------------------------------------- wiring

document.querySelectorAll('.tabs button').forEach((b) => { b.onclick = () => tab(b.dataset.tab); });
$('f-scroll').onchange = listSegs;
$('f-find').oninput = listSegs;
['l-pub', 'l-snap', 'l-move'].forEach((id) => { $(id).onchange = () => draw(); });
$('z-range').oninput = () => { S.plane = Number($('z-range').value); ringOrder(); const r = planeRows(); if (r.length) { let best = Infinity, bi = 0; for (let i = 0; i < r.length / R; i++) { const d = (r[R * i] - S.cx) ** 2 + (r[R * i + 1] - S.cy) ** 2; if (d < best) { best = d; bi = i; } } S.at = Math.max(0, S.order.indexOf(bi)); } draw(); };
$('win').onchange = () => { S.win = Number($('win').value); draw(); };
$('b-next').onclick = () => { centreOn(S.at + Math.max(1, Math.round(S.order.length / 24))); draw(); };
$('b-prev').onclick = () => { centreOn(S.at - Math.max(1, Math.round(S.order.length / 24))); draw(); };
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.key === 'ArrowRight') $('b-next').click();
  if (e.key === 'ArrowLeft') $('b-prev').click();
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); const zr = $('z-range'); zr.value = String(Number(zr.value) + (e.key === 'ArrowUp' ? 1 : -1)); zr.oninput(); }
});
cv.addEventListener('click', (e) => {
  const b = cv.getBoundingClientRect(), n = S.win;
  S.cx += ((e.clientX - b.left) / b.width - 0.5) * n; S.cy += ((e.clientY - b.top) / b.height - 0.5) * n; draw();
});

// window.snappedLabels: the same data for scripts and headless browsers
window.snappedLabels = {
  data: DATA,
  segments: () => S.index.slice(),
  open: (segment, z) => { const s = S.index.find((x) => x.segment === segment); if (!s) throw new Error(`no segment ${segment}`); return openSeg(s, z); },
  view: () => (S.view ? { ...S.view, plane: S.view.planes[S.plane], centre: [S.cx, S.cy] } : null),
};

(async function init() {
  try {
    const idx = await getJSON(`${DATA}/index.json`);
    S.index = idx.segments;
    $('st-count').textContent = String(S.index.length);
    const scrolls = [...new Set(S.index.map((s) => s.scroll))];
    $('f-scroll').innerHTML = `<option value="">All scrolls</option>` + scrolls.map((s) => `<option>${s}</option>`).join('');
    table();
    const want = params.get('seg');
    const big = (sc) => S.index.filter((s) => s.scroll === sc).sort((a, b) => b.vertices_released - a.vertices_released)[0];
    const first = S.index.find((s) => s.segment === want) || big('PHerc0139') || S.index[0];   // default: the largest PHerc0139 segment
    $('f-scroll').value = first.scroll;
    listSegs();
    await openSeg(first, params.get('z') != null ? Number(params.get('z')) : null);
  } catch (e) {
    $('v-title').textContent = 'Could not load the dataset';
    msg(`${e.message}. The dataset is ${DATA}`);
  }
})();
