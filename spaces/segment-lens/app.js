// Segment Lens: published tifxyz segments as 3D surfaces with kit tifxyz check's flags, beside the Segment Atlas
// numbers. Reads atlas.jsonl and lens/*.slg.gz from the Hugging Face dataset SharpMeow/vesuvius-segment-atlas at
// run time (format: docs/tools/atlas.md in ChaseHendrick/Scrolls, "Lens files").
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const VERSION = '1.0.0';
// ?data=URL/ reads another copy of the atlas (a local build, for testing); the default is the published dataset
const DATA = new URLSearchParams(location.search).get('data') || 'https://huggingface.co/datasets/SharpMeow/vesuvius-segment-atlas/resolve/main/';
const S3 = 'https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/';
const COLORS = { base: [0.80, 0.84, 0.86], hole: [0.35, 0.65, 1.0], fold: [1.0, 0.36, 0.36], str: [1.0, 0.65, 0.2] };
const $ = (id) => document.getElementById(id);

let rows = [];
let current = null;
let mesh = null;
let wire = null;
let lens = null;
let sortKey = 'area_cm2';
let sortDir = -1;

// ---------------------------------------------------------------- 3D

const canvas = $('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x05080b);
const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
camera.position.set(0, 0, 3.2);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xe8f4ff, 0x1a2228, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(2, 3, 4);
scene.add(sun);
const back = new THREE.DirectionalLight(0x9fe3ff, 0.5);
back.position.set(-3, -2, -4);
scene.add(back);

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();
(function loop() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(loop);
})();

async function gunzip(buf) {
  const ds = new DecompressionStream('gzip');
  const stream = new Blob([buf]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function parseLens(raw) {
  const magic = String.fromCharCode(...raw.slice(0, 4));
  if (magic !== 'SLG1') throw new Error('not a Segment Lens grid');
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const h = dv.getUint16(4, true), w = dv.getUint16(6, true), k = dv.getUint16(8, true);
  const lo = [0, 1, 2].map((i) => dv.getFloat32(10 + 4 * i, true));
  const hi = [0, 1, 2].map((i) => dv.getFloat32(22 + 4 * i, true));
  const n = h * w;
  const q = [0, 1, 2].map((i) => new Uint16Array(raw.slice(34 + 2 * n * i, 34 + 2 * n * (i + 1)).buffer));
  const flags = raw.slice(34 + 6 * n, 34 + 7 * n);
  return { h, w, k, lo, hi, q, flags };
}

function buildMesh(g) {
  const { h, w, lo, hi, q } = g;
  const n = h * w;
  const span = [0, 1, 2].map((i) => (hi[i] - lo[i]) || 1);
  const size = Math.max(...span);
  const pos = new Float32Array(3 * n);
  const ok = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    if (q[0][i] === 65535) continue;
    ok[i] = 1;
    for (let a = 0; a < 3; a++) {
      const v = lo[a] + (q[a][i] / 65534) * span[a];
      pos[3 * i + a] = (v - (lo[a] + hi[a]) / 2) / size * 2;
    }
  }
  const idx = [];
  for (let r = 0; r < h - 1; r++) {
    for (let c = 0; c < w - 1; c++) {
      const a = r * w + c, b = a + 1, d = a + w, e = d + 1;
      if (ok[a] && ok[b] && ok[d] && ok[e]) idx.push(a, b, e, a, e, d);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(3 * n), 3));
  geo.setIndex(idx);
  geo.computeVertexNormals();
  // z (scan height) points up on screen: the scan's slices are stacked along z
  geo.rotateX(-Math.PI / 2);
  return { geo, cells: idx.length / 6 };
}

function paint() {
  if (!mesh || !lens) return;
  const col = mesh.geometry.getAttribute('color');
  const show = { 1: $('t-hole').checked, 2: $('t-fold').checked, 4: $('t-str').checked };
  const f = lens.flags;
  for (let i = 0; i < f.length; i++) {
    let c = COLORS.base;
    if (show[1] && (f[i] & 1)) c = COLORS.hole;
    if (show[4] && (f[i] & 4)) c = COLORS.str;
    if (show[2] && (f[i] & 2)) c = COLORS.fold;
    col.setXYZ(i, c[0], c[1], c[2]);
  }
  col.needsUpdate = true;
  if (wire) wire.visible = $('t-wire').checked;
}

async function show(row) {
  current = row;
  setCard(row);
  document.querySelectorAll('#list li').forEach((li) => li.classList.toggle('on', li.dataset.id === row.id));
  if (!row.lens) {
    clearMesh();
    $('c-note').textContent = row.prize_lists && row.prize_lists.length
      ? 'This scroll is on a prize list, so it has numbers here but no 3D preview (public media rule).'
      : 'No preview for this mesh (it was not measured, or has no filled nodes).';
    return;
  }
  $('c-note').textContent = 'Loading the preview…';
  try {
    const res = await fetch(DATA + 'lens/' + row.lens);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const g = parseLens(await gunzip(await res.arrayBuffer()));
    if (current !== row) return;
    clearMesh();
    lens = g;
    const { geo, cells } = buildMesh(g);
    mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      vertexColors: true, side: THREE.DoubleSide, roughness: 0.75, metalness: 0.0 }));
    scene.add(mesh);
    wire = new THREE.LineSegments(new THREE.WireframeGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0x9fe3ff, transparent: true, opacity: 0.12 }));
    scene.add(wire);
    paint();
    controls.reset();
    $('c-note').textContent = `Preview: 1 in ${g.k} grid nodes along each side (${g.w} x ${g.h}, ${cells.toLocaleString()} cells); flags pooled over each ${g.k} x ${g.k} block. Drag to turn, scroll to zoom. Up on screen is the scan's z.`;
  } catch (err) {
    $('c-note').textContent = 'The preview could not be loaded: ' + err.message;
  }
}

function clearMesh() {
  for (const o of [mesh, wire]) {
    if (!o) continue;
    scene.remove(o);
    o.geometry.dispose();
    o.material.dispose();
  }
  mesh = wire = lens = null;
}

// ---------------------------------------------------------------- panels

const fmt = (v, n = 2) => (v === null || v === undefined || Number.isNaN(v) ? '-' : Number(v).toFixed(n));
const pct = (v) => (v === null || v === undefined ? '-' : (100 * v).toFixed(1) + '%');

function kitCommand(row) {
  return `python -m kit tifxyz check ${row.url.replace(S3, 's3://vesuvius-challenge-open-data/')} --png check.png`;
}

function setCard(r) {
  $('c-kicker').textContent = `${r.scroll}${r.volume ? ' · VOLUME ' + r.volume : ''}${r.voxel_um ? ' · ' + r.voxel_um + ' µm' : ''}`;
  $('c-title').textContent = r.segment + (r.kind !== 'mesh' ? ' (' + r.mesh + ')' : '');
  const items = r.error ? [['not measured', r.error]] : [
    ['area', r.area_cm2 == null ? '-' : fmt(r.area_cm2) + ' cm²'],
    ['grid', `${r.grid_w} x ${r.grid_h}`],
    ['filled', pct(r.filled_share)],
    ['edges within 10% of the step', pct(r.within_10pct)],
    ['median edge / step', fmt(r.edge_p50, 3)],
    ['grid angle (median)', fmt(r.angle_p50, 1) + '°'],
    ['holes', `${fmt(r.holes_mm2)} mm² (${(r.holes_nodes || 0).toLocaleString()} nodes)`],
    ['folds', `${fmt(r.folds_mm2)} mm² (${(r.folds_nodes || 0).toLocaleString()} nodes)`],
    ['stretched', `${fmt(r.stretched_mm2)} mm² (${(r.stretched_nodes || 0).toLocaleString()} nodes)`],
    ['area vs meta.json', r.meta_area_ratio == null ? '-' : fmt(r.meta_area_ratio, 4)],
  ];
  $('c-nums').innerHTML = items.map(([k, v]) => `<dt>${k}</dt><dd>${esc(String(v))}</dd>`).join('');
  $('a-bucket').href = r.url + '/meta.json';
  $('a-bucket').textContent = 'meta.json on the bucket';
}

function esc(s) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.hidden = true; }, 2600);
}

function scrollsWithLens() {
  const s = new Map();
  for (const r of rows) {
    const e = s.get(r.scroll) || { n: 0, lens: 0 };
    e.n++;
    if (r.lens) e.lens++;
    s.set(r.scroll, e);
  }
  return [...s.entries()].sort((a, b) => (b[1].lens > 0) - (a[1].lens > 0) || a[0].localeCompare(b[0]));
}

function fillScrolls() {
  const sel = $('sel-scroll');
  sel.innerHTML = scrollsWithLens().map(([s, e]) =>
    `<option value="${esc(s)}">${esc(s)} · ${e.n} meshes${e.lens ? '' : ' · numbers only'}</option>`).join('');
  const want = new URLSearchParams(location.hash.slice(1)).get('scroll');
  if (want && [...sel.options].some((o) => o.value === want)) sel.value = want;
  else if ([...sel.options].some((o) => o.value === 'PHerc0139')) sel.value = 'PHerc0139';
}

function fillList() {
  const scroll = $('sel-scroll').value;
  const top = $('only-top').checked;
  const f = $('filter').value.trim().toLowerCase();
  const list = rows.filter((r) => r.scroll === scroll && (!top || r.kind === 'mesh')
    && (!f || r.id.toLowerCase().includes(f)))
    .sort((a, b) => (b.area_cm2 || 0) - (a.area_cm2 || 0));
  $('list').innerHTML = list.map((r) => `<li tabindex="0" data-id="${esc(r.id)}">
      <span class="nm" title="${esc(r.id)}">${esc(r.segment)}${r.kind !== 'mesh' ? ' · ' + esc(r.mesh) : ''}</span>
      <span class="ar">${r.area_cm2 == null ? '' : fmt(r.area_cm2, 1) + ' cm²'}</span>
      <span class="fl">${r.voxel_um ? r.voxel_um + ' µm · ' : ''}${r.error ? 'not measured' :
        `<b class="c-hole">${fmt(r.holes_mm2, 1)}</b> / <b class="c-fold">${fmt(r.folds_mm2, 1)}</b> / <b class="c-str">${fmt(r.stretched_mm2, 1)}</b> mm²`}${r.lens ? '' : ' · numbers only'}</span>
    </li>`).join('');
  return list;
}

$('list').addEventListener('click', (e) => {
  const li = e.target.closest('li');
  if (!li) return;
  const r = rows.find((x) => x.id === li.dataset.id);
  if (r) { location.hash = 'scroll=' + encodeURIComponent(r.scroll) + '&id=' + encodeURIComponent(r.id); show(r); }
});
$('list').addEventListener('keydown', (e) => { if (e.key === 'Enter') e.target.click(); });
$('sel-scroll').addEventListener('change', () => { const l = fillList(); if (l.length) show(l[0]); });
$('only-top').addEventListener('change', fillList);
$('filter').addEventListener('input', fillList);
for (const id of ['t-hole', 't-fold', 't-str', 't-wire']) $(id).addEventListener('change', paint);
$('b-copy').addEventListener('click', async () => {
  if (!current) return;
  try { await navigator.clipboard.writeText(kitCommand(current)); toast('kit command copied'); }
  catch { toast(kitCommand(current)); }
});
$('b-about').addEventListener('click', () => $('about').showModal());

// ---------------------------------------------------------------- table

function fillTable() {
  const f = $('t-filter').value.trim().toLowerCase();
  const list = rows.filter((r) => r.kind === 'mesh' && (!f || r.id.toLowerCase().includes(f)));
  list.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sortDir;
  });
  document.querySelectorAll('#tbl th').forEach((th) => th.classList.toggle('sorted', th.dataset.k === sortKey));
  $('tbl').querySelector('tbody').innerHTML = list.map((r) => `<tr class="${r.lens ? 'go' : ''}" data-id="${esc(r.id)}">
    <td>${esc(r.scroll)}</td><td title="${esc(r.mesh)}">${esc(r.segment)}</td><td class="n">${r.voxel_um ?? '-'}</td>
    <td class="n">${fmt(r.area_cm2)}</td><td class="n">${pct(r.filled_share)}</td><td class="n">${pct(r.within_10pct)}</td>
    <td class="n">${fmt(r.holes_mm2)}</td><td class="n">${fmt(r.folds_mm2)}</td><td class="n">${fmt(r.stretched_mm2)}</td>
    <td>${r.lens ? 'view' : (r.error ? 'error' : '-')}</td></tr>`).join('');
}

document.querySelectorAll('#tbl th').forEach((th) => th.addEventListener('click', () => {
  if (sortKey === th.dataset.k) sortDir = -sortDir; else { sortKey = th.dataset.k; sortDir = th.classList.contains('n') ? -1 : 1; }
  fillTable();
}));
$('t-filter').addEventListener('input', fillTable);
$('tbl').addEventListener('click', (e) => {
  const tr = e.target.closest('tr.go');
  if (!tr) return;
  const r = rows.find((x) => x.id === tr.dataset.id);
  setMode('lens');
  $('sel-scroll').value = r.scroll;
  fillList();
  show(r);
});

function setMode(m) {
  document.querySelectorAll('.chip[data-mode]').forEach((b) => b.classList.toggle('on', b.dataset.mode === m));
  $('table-view').hidden = m !== 'table';
  if (m === 'table') fillTable();
}
document.querySelectorAll('.chip[data-mode]').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));

// ---------------------------------------------------------------- start

async function start() {
  try {
    const txt = await fetch(DATA + 'atlas.jsonl').then((r) => {
      if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); });
    rows = txt.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
  } catch (err) {
    $('c-title').textContent = 'The atlas could not be loaded';
    $('c-note').textContent = String(err.message || err);
    return;
  }
  $('k-count').textContent = rows.length.toLocaleString();
  const sum = await fetch(DATA + 'summary.json').then((r) => (r.ok ? r.json() : null)).catch(() => null);
  $('t-meta').textContent = `${rows.filter((r) => r.kind === 'mesh').length} top-level meshes` +
    (sum ? ` · built ${sum.built} from kit ${sum.kit_commit}` : '') + ` · Segment Lens ${VERSION}`;
  fillScrolls();
  const list = fillList();
  const want = new URLSearchParams(location.hash.slice(1)).get('id');
  const pick = rows.find((r) => r.id === want) || list.find((r) => r.lens) || list[0];
  if (pick) show(pick);
}
// For agents and tests (headless Chromium): the loaded rows, the selected mesh and its preview's flag counts.
window.segmentLens = {
  version: VERSION,
  state: () => ({ rows: rows.length, selected: current ? current.id : null, loaded: !!lens,
    grid: lens ? [lens.w, lens.h, lens.k] : null }),
  rows: (scroll) => rows.filter((r) => !scroll || r.scroll === scroll),
  select: (id) => { const r = rows.find((x) => x.id === id); if (r) { $('sel-scroll').value = r.scroll; fillList(); show(r); } return !!r; },
  flags: () => {
    if (!lens) return null;
    const out = { hole: 0, fold: 0, stretched: 0, nodes: lens.flags.length };
    for (const f of lens.flags) { if (f & 1) out.hole++; if (f & 2) out.fold++; if (f & 4) out.stretched++; }
    return out;
  },
  command: () => (current ? kitCommand(current) : null),
};

start();
