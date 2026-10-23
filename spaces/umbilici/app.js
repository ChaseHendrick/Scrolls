// Umbilici: the center lines of the prize-eligible Herculaneum scans, over live X-ray CT.
// Apache 2.0, Chase Hendrick. CT is read in the visitor's browser from the Vesuvius Challenge open-data bucket.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const VERSION = '1.3.0';
const DATASET = 'https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines';
const LASAGNA_SCROLL = 'PHerc0175A';
const ICE = new THREE.Color('#89f0ff');
const AMBER = new THREE.Color('#ffb347');
const COARSE = matchMedia('(pointer: coarse)').matches;
const $ = (id) => document.getElementById(id);

// ---------- state ----------
const S = {
  data: null, las: null, mode: 'array', sel: null, hot: null, ex: 3, z: null,
  ct: true, render: 'xray', gain: 44, sheets: true, needles: true, ct2: false, ori: false, blend: 70,
  dirty: true, status: '',
};

// ---------- renderer ----------
const canvas = $('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
const DPR = Math.min(devicePixelRatio || 1, 2);
renderer.setPixelRatio(DPR);
renderer.setSize(innerWidth, innerHeight);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#02060a');
const camera = new THREE.PerspectiveCamera(32, innerWidth / innerHeight, 1, 20000);
camera.position.set(-620, 330, 2350).multiplyScalar(Math.max(1, 1.25 / camera.aspect));
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(0, 90, 0);
controls.autoRotate = false;
controls.autoRotateSpeed = 0.35;
controls.addEventListener('change', () => { S.dirty = true; });
// While the camera moves, the X-ray takes fewer ray steps instead of dropping resolution: changing the pixel ratio
// mid-drag resized the bloom buffers and made the glow pop and flicker.
let moving = false, settleT = 0;
controls.addEventListener('start', () => { moving = true; clearTimeout(settleT); controls.autoRotate = false; applyVolUniforms(); });
controls.addEventListener('end', () => { clearTimeout(settleT); settleT = setTimeout(() => { moving = false; applyVolUniforms(); S.dirty = true; }, 150); });

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
// ---------- settings (glow, quality, film), kept per viewer ----------
const SET_DEFAULT = { glow: 0.8, radius: 0.5, quality: 'auto', film: true, spin: true };
const SET = { ...SET_DEFAULT };
try { Object.assign(SET, JSON.parse(localStorage.getItem('umbilici.settings') || '{}')); } catch { /* storage blocked */ }
{ const q = new URLSearchParams(location.search); if (q.has('glow')) SET.glow = Math.max(0, Math.min(3, +q.get('glow') || 0)); }
function saveSet() { try { localStorage.setItem('umbilici.settings', JSON.stringify(SET)); } catch { /* storage blocked */ } }
// auto quality starts at 1.5 pixels per CSS pixel (1.25 on touch screens) and steps down, at most twice, when frames
// run slow; 'high' is the screen's full density and 'low' is 0.75
let autoLevel = 0;
function autoSteps() { const d = Math.min(devicePixelRatio || 1, 2); return [Math.min(d, COARSE ? 1.25 : 1.5), Math.min(d, 1), 0.75]; }
function pixelRatio() { const d = Math.min(devicePixelRatio || 1, 2); return SET.quality === 'low' ? 0.75 : SET.quality === 'high' ? d : autoSteps()[autoLevel]; }
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), SET.glow, SET.radius, 0.55);
composer.addPass(bloom);
composer.addPass(new OutputPass());

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight); S.dirty = true;
});

// ---------- helpers ----------
const mm = (s, v) => v * s.voxel_um / 1000;
const fmt = (v, d = 1) => Number(v).toFixed(d);
async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${r.status} ${url}`); return r.json(); }
function linePts(l) { const p = l.points, out = []; for (let i = 0; i < p.length; i += 3) out.push([p[i], p[i + 1], p[i + 2]]); return out; }
function lineAt(l, z) {
  const p = linePts(l);
  if (z < p[0][2] || z > p[p.length - 1][2]) return null;
  for (let i = 1; i < p.length; i++) {
    if (p[i][2] >= z) { const a = p[i - 1], b = p[i], t = b[2] === a[2] ? 0 : (z - a[2]) / (b[2] - a[2]); return [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]; }
  }
  return null;
}
function lineMean(l) { const p = linePts(l); let x = 0, y = 0; for (const q of p) { x += q[0]; y += q[1]; } return [x / p.length, y / p.length]; }
function drift(s, l) { const [mx, my] = lineMean(l); let d = 0; for (const q of linePts(l)) d = Math.max(d, Math.hypot(q[0] - mx, q[1] - my)); return mm(s, d); }
const isFinder = (l) => l.source === 'finder';
const hasFinder = (s) => s.lines.some(isFinder);
function gradeOf(s) { const f = s.lines.find(isFinder); return f ? f.grade : null; }
function usable(note) { const m = /usable ends: ([a-z, ]+)/.exec(note || ''); return m ? m[1] : null; }
const GRADE_TEXT = {
  PASS: 'both ends passed the automatic end check',
  FLAG: 'the end check found a problem at an end (a lean, or a line that stops short of the papyrus)',
  VOID: 'the tilt test failed its own control on this scan, so the check says nothing either way: the line bends in its middle as much as the planted test tilt, so a real lean at an end cannot be told from a bend (5 of the 13 lines made by people fail the same control)',
};

// ---------- statistics (definitions: Guide, For researchers) ----------
const RAW = (l) => `${DATASET}/resolve/main/${l.file}`;
const median = (a) => { if (!a.length) return null; const b = [...a].sort((u, v) => u - v); const k = b.length >> 1; return b.length % 2 ? b[k] : (b[k - 1] + b[k]) / 2; };
function lineStats(s, l) {
  const p = linePts(l), n = p.length;
  const dz = []; for (let i = 1; i < n; i++) dz.push(p[i][2] - p[i - 1][2]);
  const [mx, my] = lineMean(l);
  // least-squares x(z), y(z)
  let sz = 0, szz = 0, sx = 0, sy = 0, sxz = 0, syz = 0;
  for (const [x, y, z] of p) { sz += z; szz += z * z; sx += x; sy += y; sxz += x * z; syz += y * z; }
  const den = n * szz - sz * sz || 1;
  const bx = (n * sxz - sz * sx) / den, by = (n * syz - sz * sy) / den, ax = (sx - bx * sz) / n, ay = (sy - by * sz) / n;
  let r2 = 0, path = 0;
  for (let i = 0; i < n; i++) { const [x, y, z] = p[i]; r2 += (x - ax - bx * z) ** 2 + (y - ay - by * z) ** 2; if (i) path += Math.hypot(x - p[i - 1][0], y - p[i - 1][1], z - p[i - 1][2]); }
  const st = l.stamp || {};
  const stamped = st.volume_width === s.shape[2] && st.volume_height === s.shape[1] && st.volume_slices === s.shape[0];
  const z0 = p[0][2], z1 = p[n - 1][2];
  return {
    points: n, z_start: z0, z_end: z1, height_mm: mm(s, z1 - z0), coverage: (z1 - z0) / s.shape[0],
    median_step_vox: median(dz), max_step_vox: dz.length ? Math.max(...dz) : null,
    mean_x: mx, mean_y: my, off_center_mm: mm(s, Math.hypot(mx - s.shape[2] / 2, my - s.shape[1] / 2)),
    stray_mm: drift(s, l), tilt_deg: Math.atan(Math.hypot(bx, by)) * 180 / Math.PI, wiggle_mm: mm(s, Math.sqrt(r2 / n)),
    path_mm: mm(s, path), path_over_height: path / Math.max(1, z1 - z0), stamped,
  };
}
function pairStats(s, a, b) {
  const lo = Math.max(a.z[0], b.z[0]), hi = Math.min(a.z[1], b.z[1]); const g = [];
  for (let z = lo; z <= hi; z += 64) { const p = lineAt(a, z), q = lineAt(b, z); if (p && q) g.push(Math.hypot(p[0] - q[0], p[1] - q[1])); }
  if (!g.length) return null;
  return { a: a.source, b: b.source, overlap_mm: mm(s, hi - lo), samples: g.length, median_mm: mm(s, median(g)), min_mm: mm(s, Math.min(...g)), max_mm: mm(s, Math.max(...g)) };
}
function pairsOf(s) { const out = []; for (let i = 0; i < s.lines.length; i++) for (let j = i + 1; j < s.lines.length; j++) { const q = pairStats(s, s.lines[i], s.lines[j]); if (q) out.push(q); } return out; }
const STAT_CACHE = new Map();
function statsOf(s, l) { const k = s.scroll + '|' + l.file; if (!STAT_CACHE.has(k)) STAT_CACHE.set(k, lineStats(s, l)); return STAT_CACHE.get(k); }
function lineRows() {
  return S.data.scrolls.flatMap((s) => s.lines.map((l) => {
    const t = statsOf(s, l);
    return {
      scroll: s.scroll, scan: s.scan, volume: s.volume, voxel_um: s.voxel_um, source: l.source, maker: S.data.sources[l.source].label,
      kind: l.kind, grade: l.grade || '', usable_ends: isFinder(l) ? (usable(l.note) || '') : '', withdrawn: l.note.includes('withdrawn'),
      ...t, licence: l.licence, sha256: l.sha256, file: RAW(l), upstream: l.upstream, note: l.note,
    };
  }));
}
function scanRows() {
  return S.data.scrolls.map((s) => {
    const pr = pairsOf(s)[0];
    return {
      scroll: s.scroll, scan: s.scan, volume: s.volume, voxel_um: s.voxel_um, slices: s.shape[0], height_px: s.shape[1], width_px: s.shape[2],
      height_mm: mm(s, s.shape[0]), width_mm: mm(s, s.shape[2]), levels: s.levels, first_letters: s.first_letters, grand_prize: s.grand_prize,
      lines: s.lines.length, sources: s.lines.map((l) => l.source).join(' '), grade: gradeOf(s) || '',
      pair_median_mm: pr ? pr.median_mm : null, pair_max_mm: pr ? pr.max_mm : null, zarr: s.zarr,
    };
  });
}
function toCSV(rows) {
  if (!rows.length) return '';
  const cols = Object.keys(rows[0]);
  const cell = (v) => { if (v == null) return ''; if (typeof v === 'number') v = Number.isInteger(v) ? v : +v.toFixed(4); v = String(v); return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
  return [cols.join(','), ...rows.map((r) => cols.map((c) => cell(r[c])).join(','))].join('\n') + '\n';
}
function pointRows(only) {
  return S.data.scrolls.filter((s) => !only || s === only).flatMap((s) => s.lines.flatMap((l) => linePts(l).map(([x, y, z]) => ({ scroll: s.scroll, scan: s.scan, source: l.source, x, y, z }))));
}
function scanJSON(s) {
  return {
    scroll: s.scroll, scan: s.scan, volume: s.volume, zarr: s.zarr, voxel_um: s.voxel_um, shape_zyx: s.shape, pyramid: s.pyramid,
    first_letters: s.first_letters, grand_prize: s.grand_prize, frame: S.data.frame, release: S.data.made,
    lines: s.lines.map((l) => ({ ...l, url: RAW(l), maker: S.data.sources[l.source].label, stats: statsOf(s, l), points: linePts(l) })),
    pairs: pairsOf(s),
  };
}
function download(name, text, type = 'text/csv') {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
let toastT = 0;
function toast(msg) { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 1600); }
async function copy(text, what = 'copied') {
  try { await navigator.clipboard.writeText(text); }
  catch { const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); } catch { /* nothing */ } ta.remove(); }
  toast(what);
}

// ---------- lines as glowing tubes ----------
function tube(points3, color, radius, opacity = 1) {
  const curve = new THREE.CatmullRomCurve3(points3.map((p) => new THREE.Vector3(...p)), false, 'centripetal');
  const g = new THREE.TubeGeometry(curve, Math.min(900, points3.length * 4), radius, 8, false);
  const m = new THREE.MeshBasicMaterial({ color: color.clone().multiplyScalar(1.35), transparent: true, opacity, depthWrite: true, toneMapped: false });
  const mesh = new THREE.Mesh(g, m); mesh.renderOrder = 3; mesh.userData.base = opacity; return mesh;
}
function ring(r, y, color, opacity, seg = 96) {
  const pts = []; for (let i = 0; i <= seg; i++) { const a = i / seg * Math.PI * 2; pts.push(new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r)); }
  const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color, transparent: true, opacity, toneMapped: false }));
  l.renderOrder = 2; return l;
}

// ---------- ARRAY view ----------
const arrayGroup = new THREE.Group(); scene.add(arrayGroup);
const hitMeshes = [];
const labels = [];
function buildArray() {
  arrayGroup.clear(); hitMeshes.length = 0; $('labels').innerHTML = ''; labels.length = 0;
  const people = S.data.scrolls.filter((s) => !hasFinder(s));
  const finder = S.data.scrolls.filter(hasFinder);
  const rows = [[people, -150], [finder, 170]];
  for (const [list, rz] of rows) {
    const step = 112, x0 = -(list.length - 1) * step / 2;
    list.forEach((s, i) => {
      const g = new THREE.Group(); g.position.set(x0 + i * step, 0, rz); g.userData.scroll = s.scroll;
      const H = mm(s, s.shape[0]);
      const [cx, cy] = lineMean(s.lines[0]);
      for (const l of s.lines) {
        const pts = linePts(l).map(([x, y, z]) => [mm(s, x - cx) * S.ex, mm(s, z), mm(s, y - cy) * S.ex]);
        g.add(tube(pts, isFinder(l) ? AMBER : ICE, 0.9, l.note.includes('withdrawn') ? 0.45 : 1));
      }
      const tint = hasFinder(s) ? AMBER : ICE;
      g.add(ring(26, 0, tint, 0.28)); g.add(ring(26, H, tint, 0.12));
      for (let k = 0; k < 4; k++) {
        const a = k / 4 * Math.PI * 2 + Math.PI / 4;
        const v = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(Math.cos(a) * 26, 0, Math.sin(a) * 26), new THREE.Vector3(Math.cos(a) * 26, H, Math.sin(a) * 26)]),
          new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity: 0.06 }));
        g.add(v);
      }
      const hit = new THREE.Mesh(new THREE.CylinderGeometry(40, 40, H, 12), new THREE.MeshBasicMaterial({ visible: false }));
      hit.position.y = H / 2; hit.userData.scroll = s.scroll; g.add(hit); hitMeshes.push(hit);
      arrayGroup.add(g);
      const el = document.createElement('div'); el.className = 'lbl' + (hasFinder(s) ? ' cf' : '');
      el.innerHTML = `<b>${s.scroll.replace('PHerc', '')}</b>${fmt(H, 0)} mm`;
      $('labels').appendChild(el); labels.push({ el, g, s });
    });
  }
  // floor grid, faint
  const grid = new THREE.GridHelper(2400, 48, 0x0f3440, 0x0a1f28); grid.material.transparent = true; grid.material.opacity = 0.35; grid.position.y = -0.5;
  arrayGroup.add(grid);
  S.dirty = true;
}
function placeLabels() {
  const show = S.mode === 'array';
  const w = innerWidth, h = innerHeight, v = new THREE.Vector3();
  for (const L of labels) {
    if (!show) { L.el.style.display = 'none'; continue; }
    v.set(0, -14, 0).applyMatrix4(L.g.matrixWorld).project(camera);
    if (v.z > 1) { L.el.style.display = 'none'; continue; }
    L.el.style.display = '';
    L.el.style.left = `${(v.x * 0.5 + 0.5) * w}px`; L.el.style.top = `${(-v.y * 0.5 + 0.5) * h}px`;
    L.el.classList.toggle('hot', S.hot === L.s.scroll); L.el.classList.toggle('sel', S.sel && S.sel.scroll === L.s.scroll);
  }
}

// ---------- CT streaming from the open-data bucket ----------
const zarrMeta = new Map();
async function zmeta(s, L) {
  const k = `${s.zarr}/${L}`; if (!zarrMeta.has(k)) zarrMeta.set(k, getJSON(`${k}/.zarray`)); return zarrMeta.get(k);
}
let inflight = 0; const waiters = [];
const MAXQ = 10;
async function slot() { if (inflight < MAXQ) { inflight++; return; } await new Promise((r) => waiters.push(r)); inflight++; }
function free() { inflight--; const w = waiters.shift(); if (w) w(); }
async function rangeGet(url, off, len, signal) {
  await slot();
  try {
    const r = await fetch(url, { headers: { Range: `bytes=${off}-${off + len - 1}` }, signal });
    if (!r.ok) return null;
    return new Uint8Array(await r.arrayBuffer());
  } catch (e) { if (e.name === 'AbortError') throw e; return null; } finally { free(); }
}
// one axial slice of level L at level-0 height z0, as a Uint8Array (Y by X)
async function ctSlice(s, L, z0, signal) {
  const m = await zmeta(s, L); const [Z, Y, X] = m.shape; const [cz, cy, cx] = m.chunks;
  const z = Math.min(Z - 1, Math.max(0, Math.floor(z0 / 2 ** L)));
  const out = new Uint8Array(X * Y); const jobs = [];
  for (let by = 0; by * cy < Y; by++) for (let bx = 0; bx * cx < X; bx++) {
    jobs.push(rangeGet(`${s.zarr}/${L}/${Math.floor(z / cz)}/${by}/${bx}`, (z % cz) * cy * cx, cy * cx, signal).then((b) => {
      if (!b) return; const h = Math.min(cy, Y - by * cy), w = Math.min(cx, X - bx * cx);
      for (let r = 0; r < h; r++) out.set(b.subarray(r * cx, r * cx + w), (by * cy + r) * X + bx * cx);
    }));
  }
  await Promise.all(jobs);
  return { data: out, X, Y };
}

// ---------- volume (radiograph / MIP) ----------
const VOL_VS = `varying vec3 vPos; void main(){ vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const VOL_FS = `
precision highp float; precision highp sampler3D;
uniform sampler3D uVol; uniform vec3 uCam; uniform float uGain; uniform int uMode; uniform float uFill; uniform int uN;
varying vec3 vPos;
vec2 box(vec3 o, vec3 d){ vec3 iv = 1.0 / d; vec3 a = (vec3(-0.5) - o) * iv, b = (vec3(0.5) - o) * iv;
  vec3 lo = min(a, b), hi = max(a, b); return vec2(max(max(lo.x, lo.y), lo.z), min(min(hi.x, hi.y), hi.z)); }
void main(){
  vec3 o = uCam, d = normalize(vPos - uCam);
  vec2 t = box(o, d); t.x = max(t.x, 0.0); if (t.x >= t.y) discard;
  const int N = 220;
  float dt = (t.y - t.x) / float(uN);
  float j = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
  float acc = 0.0, mx = 0.0;
  for (int i = 0; i < N; i++) {
    if (i >= uN) break;
    vec3 p = o + d * (t.x + (float(i) + j) * dt) + 0.5;
    float v = texture(uVol, vec3(p.x, p.z, p.y)).r;
    acc += v * dt; mx = max(mx, v);
    if (uMode == 0 ? acc * uGain > 7.0 : mx > 0.995) break;   // the pixel is already white
  }
  float I;
  if (uMode == 0) I = 1.0 - exp(-max(acc - 0.015, 0.0) * uGain);
  else I = smoothstep(0.18, 0.18 + 1.6 / (uGain * 0.12 + 1.0), mx);
  I = clamp(I, 0.0, 1.0);
  vec3 film = mix(vec3(0.02, 0.10, 0.16), vec3(0.62, 0.86, 0.95), I);
  gl_FragColor = vec4(film * pow(I, 1.25) * 0.82 * uFill, 1.0);
}`;
let vol = null; // { s, mesh, tex, abort }
function disposeVol() {
  if (!vol) return; vol.abort.abort(); vol.mesh.geometry.dispose(); vol.mesh.material.dispose(); vol.tex.dispose(); vol.mesh.parent?.remove(vol.mesh); vol = null;
}
async function loadVolume(s, parent) {
  disposeVol();
  const L = 5; const m = await zmeta(s, L); const [Z, Y, X] = m.shape; const [cz, cy, cx] = m.chunks;
  const stride = Math.max(1, Math.ceil(Z / (COARSE ? 72 : 120)));
  const zs = []; for (let z = 0; z < Z; z += stride) zs.push(z);
  const D = zs.length; const data = new Uint8Array(X * Y * D);
  const tex = new THREE.Data3DTexture(data, X, Y, D);
  tex.format = THREE.RedFormat; tex.type = THREE.UnsignedByteType; tex.minFilter = tex.magFilter = THREE.LinearFilter; tex.unpackAlignment = 1; tex.needsUpdate = true;
  const mat = new THREE.ShaderMaterial({
    vertexShader: VOL_VS, fragmentShader: VOL_FS, side: THREE.BackSide, transparent: true, depthWrite: false, depthTest: false,
    blending: THREE.AdditiveBlending, uniforms: { uVol: { value: tex }, uCam: { value: new THREE.Vector3() }, uGain: { value: S.gain }, uMode: { value: 0 }, uFill: { value: 1 }, uN: { value: COARSE ? 140 : 220 } },
  });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat);
  mesh.scale.set(mm(s, X * 32), mm(s, zs[D - 1] * 32 + stride * 32), mm(s, Y * 32));
  mesh.position.set(0, mesh.scale.y / 2, 0); mesh.renderOrder = 1;
  mesh.onBeforeRender = (r, sc, cam) => { mat.uniforms.uCam.value.copy(cam.position).applyMatrix4(new THREE.Matrix4().copy(mesh.matrixWorld).invert()); };
  parent.add(mesh);
  const abort = new AbortController();
  vol = { s, mesh, tex, abort, loaded: 0, total: D };
  applyVolUniforms();
  // coarse to fine: every 4th slice first (copied into its gap), then the rest
  const order = []; for (let i = 0; i < D; i += 4) order.push(i); for (let i = 0; i < D; i++) if (i % 4) order.push(i);
  const done = new Uint8Array(D); let lastUp = 0;
  const one = async (i) => {
    const z = zs[i]; const plane = X * Y; const tasks = [];
    for (let by = 0; by * cy < Y; by++) for (let bx = 0; bx * cx < X; bx++) {
      tasks.push(rangeGet(`${s.zarr}/${L}/${Math.floor(z / cz)}/${by}/${bx}`, (z % cz) * cy * cx, cy * cx, abort.signal).then((b) => {
        if (!b) return; const h = Math.min(cy, Y - by * cy), w = Math.min(cx, X - bx * cx);
        for (let r = 0; r < h; r++) data.set(b.subarray(r * cx, r * cx + w), i * plane + (by * cy + r) * X + bx * cx);
      }));
    }
    await Promise.all(tasks);
    done[i] = 1;
    if (i % 4 === 0) for (let k = i + 1; k < Math.min(D, i + 4); k++) if (!done[k]) data.copyWithin(k * plane, i * plane, (i + 1) * plane);
    vol && vol.tex === tex && (vol.loaded++);
    const now = performance.now(); if (now - lastUp > 400 || vol?.loaded === D) { lastUp = now; tex.needsUpdate = true; S.dirty = true; setStatus(); }
  };
  try {
    let k = 0; const lanes = Array.from({ length: 3 }, async () => { while (k < order.length) { await one(order[k++]); } });
    await Promise.all(lanes);
  } catch (e) { if (e.name !== 'AbortError') console.warn(e); }
}
function applyVolUniforms() {
  if (!vol) return; const u = vol.mesh.material.uniforms; u.uGain.value = S.render === 'mip' ? S.gain / 10 + 0.5 : 0.5 + S.gain * S.gain / 700; u.uMode.value = S.render === 'mip' ? 1 : 0;
  vol.mesh.visible = S.mode === 'scan' ? S.ct : S.ct2; u.uFill.value = S.mode === 'lasagna' ? 0.55 : 1;
  const full = SET.quality === 'low' ? 140 : COARSE && SET.quality !== 'high' ? 140 : 220;
  u.uN.value = moving ? Math.round(full / 2) : full; S.dirty = true;
}
function setStatus() {
  const el = $('ct-status'); if (!el) return;
  el.textContent = vol ? (vol.loaded < vol.total ? `streaming CT ${Math.round(100 * vol.loaded / vol.total)}%` : `CT level 5 (${fmt(vol.s.voxel_um * 32, 0)} µm voxels), ${vol.total} heights`) : '';
}

// ---------- SCAN view ----------
const scanGroup = new THREE.Group(); scene.add(scanGroup);
let slicePlane = null, sliceTex = null;
let lasGroup = null;
function scanOrigin(s) { return [s.shape[2] / 2, s.shape[1] / 2]; }
function toWorld(s, x, y, z) { const [ox, oy] = scanOrigin(s); return [mm(s, x - ox), mm(s, z), mm(s, y - oy)]; }
function buildScan(s) {
  disposeVol(); scanGroup.clear(); lasGroup = null;
  for (const l of s.lines) scanGroup.add(tube(linePts(l).map(([x, y, z]) => toWorld(s, x, y, z)), isFinder(l) ? AMBER : ICE, 0.55, l.note.includes('withdrawn') ? 0.5 : 1));
  const W = mm(s, s.shape[2]), D = mm(s, s.shape[1]), H = mm(s, s.shape[0]);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(W, H, D)), new THREE.LineBasicMaterial({ color: ICE, transparent: true, opacity: 0.12 }));
  frame.position.y = H / 2; scanGroup.add(frame);
  // slice plane, textured from the inset canvas
  sliceTex = new THREE.CanvasTexture($('slice')); sliceTex.colorSpace = THREE.SRGBColorSpace;
  slicePlane = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshBasicMaterial({ map: sliceTex, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }));
  slicePlane.rotation.x = -Math.PI / 2; slicePlane.renderOrder = 2; scanGroup.add(slicePlane);
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(W, D)), new THREE.LineBasicMaterial({ color: ICE, transparent: true, opacity: 0.5, toneMapped: false }));
  slicePlane.add(edge);
  if (s.scroll === LASAGNA_SCROLL && S.las) buildLasagna(s);
  loadVolume(s, scanGroup);
}

// ---------- LASAGNA layers (PHerc0175A) ----------
const SHEET_FS = `uniform sampler2D map; uniform float uA; uniform vec3 uTint; varying vec2 vUv;
void main(){ float c = texture2D(map, vUv).r; float a = smoothstep(0.42, 0.9, c) * uA; gl_FragColor = vec4(uTint * a, 1.0); }`;
const SHEET_VS = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const texLoader = new THREE.TextureLoader();
function buildLasagna(s) {
  lasGroup = new THREE.Group(); scanGroup.add(lasGroup);
  const W = mm(s, s.shape[2]), D = mm(s, s.shape[1]);
  const sheets = new THREE.Group(); sheets.name = 'sheets'; lasGroup.add(sheets);
  S.las.slice_z.forEach((z, i) => {
    const t = texLoader.load(`data/lasagna/cos_${z}.webp`, () => { S.dirty = true; });
    const mat = new THREE.ShaderMaterial({ vertexShader: SHEET_VS, fragmentShader: SHEET_FS, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      uniforms: { map: { value: t }, uA: { value: 0.5 }, uTint: { value: new THREE.Color().lerpColors(ICE, AMBER, i / (S.las.slice_z.length - 1)).multiplyScalar(0.9) } } });
    const p = new THREE.Mesh(new THREE.PlaneGeometry(W, D), mat); p.rotation.x = -Math.PI / 2; p.position.y = mm(s, z); p.renderOrder = 1; sheets.add(p);
  });
  fetch('data/lasagna/needles.bin').then((r) => r.arrayBuffer()).then((buf) => {
    const n = S.las.needles.count; const pos = new Uint16Array(buf, 0, n * 3); const nr = new Int8Array(buf, n * 6, n * 3); const gm = new Uint8Array(buf, n * 9, n);
    const keep = COARSE ? 6 : 3; const m = Math.ceil(n / keep);
    const P = new Float32Array(m * 6), C = new Float32Array(m * 6); const half = 26; const col = new THREE.Color();
    let k = 0;
    for (let i = 0; i < n; i += keep, k++) {
      const a = nr[i * 3] / 127, b = nr[i * 3 + 1] / 127, c = nr[i * 3 + 2] / 127;
      const [x, y, z] = [pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]];
      const p0 = toWorld(s, x - a * half, y - b * half, z - c * half), p1 = toWorld(s, x + a * half, y + b * half, z + c * half);
      P.set(p0, k * 6); P.set(p1, k * 6 + 3);
      const hue = ((Math.atan2(b, a) * 2) / (Math.PI * 2) + 1) % 1; const sat = Math.min(1, Math.hypot(a, b));
      col.setHSL(hue, 0.35 + 0.65 * sat, 0.1 + 0.26 * (gm[i] / 255));
      C.set([col.r, col.g, col.b], k * 6); C.set([col.r, col.g, col.b], k * 6 + 3);
    }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(P, 3)); g.setAttribute('color', new THREE.BufferAttribute(C, 3));
    const ls = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
    ls.name = 'needles'; ls.renderOrder = 2; lasGroup.add(ls); applyLasVis();
  });
  applyLasVis();
}
function applyLasVis() {
  if (!lasGroup) return; const on = S.mode === 'lasagna';
  lasGroup.visible = on;
  const sh = lasGroup.getObjectByName('sheets'); if (sh) sh.visible = S.sheets;
  const gl = lasGroup.getObjectByName('needles'); if (gl) gl.visible = S.needles;
  if (slicePlane) slicePlane.visible = !on;
  S.dirty = true;
}

// ---------- slice inset ----------
const sc = $('slice'), sx = sc.getContext('2d');
let sliceJob = 0, sliceAbort = null;
const sheetImgs = new Map();
function sheetImg(path) { if (!sheetImgs.has(path)) { const im = new Image(); im.src = path; sheetImgs.set(path, new Promise((r) => { im.onload = () => r(im); im.onerror = () => r(null); })); } return sheetImgs.get(path); }
function lut(v) { // x-ray film: black to ice to white
  const t = v / 255; return [Math.min(255, 255 * Math.pow(t, 1.35) * 0.85), Math.min(255, 255 * Math.pow(t, 1.05) * 0.97), Math.min(255, 255 * Math.pow(t, 0.8))];
}
const LUT = Array.from({ length: 256 }, (_, i) => lut(i));
function drawCT(sl, alpha = 1) {
  // percentile window over non-empty pixels
  const h = new Uint32Array(256); let n = 0; for (let i = 0; i < sl.data.length; i += 7) { const v = sl.data[i]; if (v > 2) { h[v]++; n++; } }
  let lo = 0, hi = 255, c = 0; for (let v = 0; v < 256; v++) { c += h[v]; if (c < n * 0.01) lo = v; if (c < n * 0.995) hi = v; }
  const span = Math.max(8, hi - lo);
  const im = new ImageData(sl.X, sl.Y); const d = im.data;
  for (let i = 0; i < sl.data.length; i++) { const v = sl.data[i]; const t = v <= 2 ? 0 : Math.max(0, Math.min(255, (v - lo) * 255 / span)); const q = LUT[t | 0]; d[i * 4] = q[0]; d[i * 4 + 1] = q[1]; d[i * 4 + 2] = q[2]; d[i * 4 + 3] = 255; }
  const tmp = new OffscreenCanvas(sl.X, sl.Y); tmp.getContext('2d').putImageData(im, 0, 0);
  sx.globalAlpha = alpha; sx.drawImage(tmp, 0, 0, sc.width, sc.height); sx.globalAlpha = 1;
}
function drawMarks(s, z) {
  const k = sc.width / s.shape[2];
  for (const l of s.lines) {
    const p = lineAt(l, z); if (!p) continue;
    const x = p[0] * k, y = p[1] * k; const col = isFinder(l) ? '#ffb347' : '#89f0ff';
    sx.strokeStyle = col; sx.lineWidth = 1.6; sx.shadowColor = col; sx.shadowBlur = 10;
    sx.beginPath(); sx.arc(x, y, 9, 0, Math.PI * 2); sx.stroke();
    sx.beginPath(); sx.moveTo(x - 22, y); sx.lineTo(x - 12, y); sx.moveTo(x + 12, y); sx.lineTo(x + 22, y); sx.moveTo(x, y - 22); sx.lineTo(x, y - 12); sx.moveTo(x, y + 12); sx.lineTo(x, y + 22); sx.stroke();
    sx.fillStyle = col; sx.beginPath(); sx.arc(x, y, 1.6, 0, Math.PI * 2); sx.fill();
    sx.shadowBlur = 0; sx.font = '500 12px JetBrains Mono, monospace'; sx.fillText(S.data.sources[l.source].short, x + 14, y - 13);
  }
}
async function drawSlice() {
  const s = S.sel; if (!s) return;
  const job = ++sliceJob; sliceAbort?.abort(); sliceAbort = new AbortController(); const sig = sliceAbort.signal;
  const z = S.z; const las = S.mode === 'lasagna' && s.scroll === LASAGNA_SCROLL && S.las;
  $('i-z').textContent = `z ${Math.round(z)} · ${fmt(mm(s, z), 1)} mm`;
  $('i-title').textContent = las ? 'LASAGNA SHEETS' : 'AXIAL CT SLICE';
  if (slicePlane) { slicePlane.position.y = mm(s, z); }
  try {
    if (las) {
      const im = await sheetImg(`data/lasagna/${S.ori ? 'ori' : 'cos'}_${z}.webp`); if (job !== sliceJob) return;
      sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height);
      const ctOn = S.blend < 100;
      if (ctOn) { $('i-status').textContent = 'streaming CT…'; const sl = await ctSlice(s, 3, z, sig); if (job !== sliceJob) return; drawCT(sl, 1); }
      if (im) { sx.globalCompositeOperation = ctOn ? 'screen' : 'source-over'; sx.globalAlpha = S.blend / 100; if (!S.ori) sx.filter = 'sepia(1) saturate(2.2) hue-rotate(-12deg) brightness(1.05)'; sx.drawImage(im, 0, 0, sc.width, sc.height); sx.filter = 'none'; sx.globalAlpha = 1; sx.globalCompositeOperation = 'source-over'; }
      drawMarks(s, z); $('i-status').textContent = 'model output · villa lasagna';
    } else {
      $('i-status').textContent = 'streaming…';
      const quick = await ctSlice(s, 4, z, sig); if (job !== sliceJob) return;
      sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); drawCT(quick); drawMarks(s, z); if (sliceTex) sliceTex.needsUpdate = true; S.dirty = true;
      await new Promise((r) => setTimeout(r, 220)); if (job !== sliceJob) return;
      const fine = await ctSlice(s, 3, z, sig); if (job !== sliceJob) return;
      sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); drawCT(fine); drawMarks(s, z);
      $('i-status').textContent = `CT level 3 · ${fmt(s.voxel_um * 8, 0)} µm px`;
    }
    if (sliceTex) sliceTex.needsUpdate = true; S.dirty = true;
  } catch (e) { if (e.name !== 'AbortError') { $('i-status').textContent = 'CT unavailable'; console.warn(e); } }
}
let zTimer = 0;
function setZ(z, now = false) {
  const s = S.sel; if (!s) return;
  if (S.mode === 'lasagna' && S.las && s.scroll === LASAGNA_SCROLL) { const zs = S.las.slice_z; z = zs.reduce((a, b) => Math.abs(b - z) < Math.abs(a - z) ? b : a, zs[0]); }
  S.z = Math.max(0, Math.min(s.shape[0] - 1, z));
  $('z').value = Math.round(1000 * S.z / s.shape[0]);
  clearTimeout(zTimer); if (now) drawSlice(); else zTimer = setTimeout(drawSlice, 90);
  if (slicePlane) slicePlane.position.y = mm(s, S.z); S.dirty = true; drawHere(); syncURL();
}
$('z').addEventListener('input', (e) => { if (S.sel) setZ(e.target.value / 1000 * S.sel.shape[0]); });
sc.addEventListener('wheel', (e) => { if (!S.sel) return; e.preventDefault(); const step = S.mode === 'lasagna' ? 1280 * Math.sign(e.deltaY) : S.sel.shape[0] / 200 * Math.sign(e.deltaY); setZ(S.z - step); }, { passive: false });

// ---------- UI ----------
function railRow(s) {
  const li = document.createElement('li'); li.dataset.scroll = s.scroll;
  const srcs = s.lines.map((l) => `<span class="src ${isFinder(l) ? 'cf' : ''}" title="${S.data.sources[l.source].label}">${S.data.sources[l.source].short}</span>`).join('');
  const g = gradeOf(s);
  const prize = s.grand_prize ? 'GP' : 'FL';
  li.innerHTML = `<span class="nm">${s.scroll}<small>${prize}</small></span><span class="srcs">${srcs}</span><span class="grade ${g || ''}">${g || '·'}</span>`;
  li.addEventListener('click', () => select(s.scroll, S.mode === 'array' ? 'scan' : S.mode));
  li.addEventListener('mouseenter', () => { S.hot = s.scroll; S.dirty = true; });
  li.addEventListener('mouseleave', () => { S.hot = null; S.dirty = true; });
  return li;
}
function buildRail() {
  const ol = $('rail-list'); ol.innerHTML = '';
  for (const s of S.data.scrolls) ol.appendChild(railRow(s));
}
function buildCard(s) {
  $('c-kick').textContent = `SCAN ${s.scan} · ${s.voxel_um} µm · ${s.grand_prize ? 'GRAND PRIZE · ' : ''}FIRST LETTERS`;
  $('c-title').textContent = s.scroll;
  $('c-lines').innerHTML = s.lines.map((l, i) => {
    const src = S.data.sources[l.source]; const f = isFinder(l); const t = statsOf(s, l);
    const up = /^https?:/.test(l.upstream) ? `<a href="${l.upstream}" target="_blank" rel="noopener">upstream</a>` : '';
    const grade = l.grade ? `<span class="grade ${l.grade}" title="${GRADE_TEXT[l.grade]}">END CHECK ${l.grade}</span>` : `<span class="dim">${l.kind === 'person' ? 'made by a person' : ''}</span>`;
    const note = f ? `<div class="note">${GRADE_TEXT[l.grade] || ''}. Usable ends: ${usable(l.note) || 'see note'}. Model output; no end checked on CT by a person.</div>`
      : (l.note ? `<div class="note">${l.note}.</div>` : '');
    const row = (k, v) => `<tr><th>${k}</th><td>${v}</td></tr>`;
    return `<div class="ln"><div class="who"><b class="${f ? 'cf' : 'p'}">${src.label}</b>${grade}</div>
      <div class="meta">${t.points} points · z ${t.z_start} to ${t.z_end} (${fmt(t.height_mm, 0)} mm, ${fmt(t.coverage * 100, 0)}% of the scan) · strays up to ${fmt(t.stray_mm, 1)} mm from its mean · ${l.licence}</div>${note}
      <div class="links"><a href="${RAW(l)}" download>download</a><button class="lk" data-copy="${RAW(l)}" data-what="file URL copied">copy URL</button><a href="${DATASET}/blob/main/${l.file}" target="_blank" rel="noopener">view</a>${up}</div>
      <details class="full"><summary>every number</summary><table class="kv">
        ${row('credit', l.credit)}${row('kind', l.kind)}${row('points', t.points)}
        ${row('z range', `${t.z_start} to ${t.z_end} voxels, ${fmt(mm(s, t.z_start), 2)} to ${fmt(mm(s, t.z_end), 2)} mm`)}
        ${row('coverage', `${fmt(t.coverage * 100, 1)}% of ${s.shape[0]} slices`)}
        ${row('step', `median ${fmt(t.median_step_vox, 0)}, max ${fmt(t.max_step_vox, 0)} voxels (${fmt(mm(s, t.max_step_vox), 1)} mm)`)}
        ${row('mean x, y', `${fmt(t.mean_x, 0)}, ${fmt(t.mean_y, 0)} voxels, ${fmt(t.off_center_mm, 2)} mm off grid center`)}
        ${row('stray', `${fmt(t.stray_mm, 2)} mm`)}${row('tilt', `${fmt(t.tilt_deg, 2)}°`)}${row('wiggle', `${fmt(t.wiggle_mm, 3)} mm RMS`)}
        ${row('path', `${fmt(t.path_mm, 1)} mm, ${fmt(t.path_over_height, 4)} times its height`)}
        ${row('stamped', t.stamped ? `yes: ${l.stamp.voxelsize_um} µm, ${l.stamp.volume_width} x ${l.stamp.volume_height} x ${l.stamp.volume_slices}` : 'no: bare points')}
        ${row('licence', l.licence)}
        ${row('sha256', `<button class="lk mono" data-copy="${l.sha256}" data-what="sha256 copied" title="copy">${l.sha256.slice(0, 16)}…</button>`)}
        ${row('file', `<code>${l.file}</code>`)}
        ${l.note ? row('note', l.note) : ''}
      </table></details></div>`;
  }).join('');
  $('c-pair').innerHTML = pairsOf(s).map((q) => `<div class="ln meta">${S.data.sources[q.a].short} and ${S.data.sources[q.b].short} sit a median <b>${fmt(q.median_mm, 2)} mm</b> apart (min ${fmt(q.min_mm, 2)}, max ${fmt(q.max_mm, 2)}) over the ${fmt(q.overlap_mm, 0)} mm where both exist.</div>`).join('');
  $('c-pyr').innerHTML = `<table class="kv"><tr><th>level</th><td>shape z, y, x</td><td>voxel</td></tr>${s.pyramid.map((p, i) => `<tr><th>${p.path}</th><td>${p.shape.join(' x ')}</td><td>${fmt(s.voxel_um * 2 ** i, i ? 1 : 3)} µm</td></tr>`).join('')}</table>
    <div class="dim">every level ${s.pyramid[0].dtype === '|u1' ? 'uint8' : s.pyramid[0].dtype}, chunks ${s.pyramid[0].chunks.join(' x ')}, ${s.pyramid[0].compressor || 'no compressor'}</div>`;
  $('c-vol').innerHTML = `CT <a href="${s.zarr}/.zattrs" target="_blank" rel="noopener">${s.volume}</a> · Vesuvius Challenge open data, CC BY-NC 4.0`;
}
function hereRows(s, z) { return s.lines.map((l) => { const p = lineAt(l, z); return p ? { source: l.source, x: p[0], y: p[1], z } : null; }).filter(Boolean); }
function drawHere() {
  const s = S.sel; if (!s || S.z == null) return;
  const z = Math.round(S.z); const rows = hereRows(s, z);
  $('c-here').innerHTML = `<div class="mono small dim">AT z ${z} (${fmt(mm(s, z), 2)} mm), LEVEL-0 VOXELS</div>` + (rows.length
    ? rows.map((r) => `<div class="hr"><span class="${r.source === 'finder' ? 'amber' : 'ice'}">${S.data.sources[r.source].short}</span> <code>${fmt(r.x, 1)}, ${fmt(r.y, 1)}, ${z}</code><button class="lk" data-copy="${fmt(r.x, 1)}, ${fmt(r.y, 1)}, ${z}" data-what="x, y, z copied">copy</button></div>`).join('')
    : '<div class="dim small">no line reaches this height</div>');
}
function setMode(m) {
  if (m === 'lasagna' && !S.las) m = 'scan';
  if ((m === 'scan' || m === 'lasagna') && !S.sel) { select(m === 'lasagna' ? LASAGNA_SCROLL : S.data.scrolls[0].scroll, m); return; }
  if (m === 'lasagna' && S.sel.scroll !== LASAGNA_SCROLL) { select(LASAGNA_SCROLL, 'lasagna'); return; }
  const prev = S.mode; S.mode = m; document.body.classList.toggle('focus', m !== 'array');
  document.querySelectorAll('.chip').forEach((c) => c.classList.toggle('on', c.dataset.mode === m));
  arrayGroup.visible = m === 'array'; scanGroup.visible = m !== 'array';
  $('card').hidden = m === 'array'; $('inset').hidden = m === 'array';
  $('ctl-array').hidden = m !== 'array'; $('ctl-scan').hidden = m !== 'scan'; $('ctl-las').hidden = m !== 'lasagna';
  $('blend-wrap').hidden = m !== 'lasagna'; $('t-ori').parentElement.hidden = m !== 'lasagna';
  document.querySelectorAll('#rail li').forEach((li) => li.classList.toggle('sel', !!S.sel && li.dataset.scroll === S.sel.scroll && m !== 'array'));
  if (m === 'array') { controls.target.set(0, 90, 0); if (prev !== 'array') { const k = Math.max(1, 1.25 / camera.aspect); camera.position.set(-620 * k, 330 * k, 2350 * k); camera.far = 20000; camera.updateProjectionMatrix(); } controls.autoRotate = false; }
  applyVolUniforms(); applyLasVis();
  if (m !== 'array' && S.sel) setZ(S.z ?? defaultZ(S.sel), true);
  syncURL(); S.dirty = true;
}
function defaultZ(s) { const l = s.lines[0]; return (l.z[0] + l.z[1]) / 2; }
function frameScan(s) {
  const H = mm(s, s.shape[0]), W = mm(s, Math.max(s.shape[1], s.shape[2]));
  controls.target.set(0, H * 0.5, 0);
  const d = Math.max(H, W * 1.4) * 2.3 * Math.max(1, 1.1 / camera.aspect); camera.position.set(d * 0.5, H * 1.05, d * 0.86); camera.near = 1; camera.far = d * 10; camera.updateProjectionMatrix();
}
function select(name, mode = 'scan') {
  const s = S.data.scrolls.find((q) => q.scroll === name); if (!s) return;
  const changed = S.sel !== s; S.sel = s;
  if (changed) { S.z = null; buildScan(s); buildCard(s); frameScan(s); }
  S.z = S.z ?? (mode === 'lasagna' && S.las ? S.las.slice_z[4] : defaultZ(s));
  setMode(mode);
}
document.querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => setMode(c.dataset.mode)));
$('c-close').addEventListener('click', () => setMode('array'));
$('b-about').addEventListener('click', () => { markSeen(); openGuide(); });
$('ex').addEventListener('input', (e) => { S.ex = +e.target.value; $('ex-v').textContent = S.ex; buildArray(); syncURL(); });
$('t-ct').addEventListener('change', (e) => { S.ct = e.target.checked; applyVolUniforms(); });
$('t-ct2').addEventListener('change', (e) => { S.ct2 = e.target.checked; applyVolUniforms(); });
$('render').addEventListener('change', (e) => { S.render = e.target.value; applyVolUniforms(); });
$('gain').addEventListener('input', (e) => { S.gain = +e.target.value; applyVolUniforms(); });
$('t-sheets').addEventListener('change', (e) => { S.sheets = e.target.checked; applyLasVis(); });
$('t-needle').addEventListener('change', (e) => { S.needles = e.target.checked; applyLasVis(); });
$('t-ori').addEventListener('change', (e) => { S.ori = e.target.checked; drawSlice(); });
$('blend').addEventListener('input', (e) => { S.blend = +e.target.value; clearTimeout(zTimer); zTimer = setTimeout(drawSlice, 120); });
addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.mode !== 'array' && !document.querySelector('dialog[open]')) setMode('array'); });
// copy buttons anywhere, card actions
document.addEventListener('click', (e) => { const b = e.target.closest('[data-copy]'); if (b) { e.preventDefault(); copy(b.dataset.copy, b.dataset.what); } });
$('c-acts').addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]'); const s = S.sel; if (!b || !s) return;
  const act = b.dataset.act;
  if (act === 'view') copy(location.href, 'view link copied');
  else if (act === 'zarr') copy(s.zarr, 'OME-Zarr URL copied');
  else if (act === 'csv') download(`${s.scroll}_center_lines.csv`, toCSV(pointRows(s)));
  else if (act === 'json') download(`${s.scroll}_umbilici.json`, JSON.stringify(scanJSON(s), null, 1), 'application/json');
  else if (act === 'use') openGuide('vc3d');
});
$('i-copy').addEventListener('click', () => { const s = S.sel; if (!s) return; const rows = hereRows(s, Math.round(S.z)); copy(rows.map((r) => `${s.scroll} ${r.source} ${fmt(r.x, 1)}, ${fmt(r.y, 1)}, ${r.z}`).join('\n') || 'none', 'x, y, z copied'); });

// guide
function tabs(dlg, name) {
  dlg.querySelectorAll('.tabs [data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  dlg.querySelectorAll('[data-pane]').forEach((p) => { p.hidden = p.dataset.pane !== name; });
}
function snippets() {
  const s = S.sel || S.data.scrolls.find((q) => q.scroll === 'PHerc0846A') || S.data.scrolls[0]; const l = s.lines[0];
  const z = Math.round(S.sel && S.z != null ? S.z : (l.z[0] + l.z[1]) / 2);
  $('g-py1').textContent = `import json, urllib.request
import numpy as np

URL = "${RAW(l)}"
pts = sorted(json.load(urllib.request.urlopen(URL))["control_points"], key=lambda p: p["z"])
z = np.array([p["z"] for p in pts], float)
x = np.array([p["x"] for p in pts], float)
y = np.array([p["y"] for p in pts], float)

Z = ${z}                      # a height in level-0 voxels
print(np.interp(Z, z, x), np.interp(Z, z, y))   # holds the end values outside the line, like VC3D`;
  $('g-py2').textContent = `VOL = "${s.zarr}"
L = 3                         # pyramid level: voxels are 2**L times level 0
meta = json.load(urllib.request.urlopen(f"{VOL}/{L}/.zarray"))   # uint8, 128^3 chunks, no compressor
cz, cy, cx = meta["chunks"]
X, Y = np.interp(Z, z, x), np.interp(Z, z, y)
zl, yl, xl = int(Z) >> L, int(Y) >> L, int(X) >> L
off = (zl % cz) * cy * cx                                # one axial plane of the chunk
req = urllib.request.Request(f"{VOL}/{L}/{zl // cz}/{yl // cy}/{xl // cx}",
                             headers={"Range": f"bytes={off}-{off + cy * cx - 1}"})
plane = np.frombuffer(urllib.request.urlopen(req).read(), np.uint8).reshape(cy, cx)
print(plane[yl % cy, xl % cx])`;
}
function openGuide(tab = 'basics') { snippets(); tabs($('about'), tab); if (!$('about').open) $('about').showModal(); }
$('about').querySelector('.tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) { if (b.dataset.tab === 'vc3d') snippets(); tabs($('about'), b.dataset.tab); } });

// data sheet
const COLS = {
  lines: [['scroll', 'scroll'], ['maker', 'maker'], ['grade', 'grade'], ['points', 'pts'], ['z_start', 'z start'], ['z_end', 'z end'], ['height_mm', 'height mm'],
    ['coverage', 'cover'], ['median_step_vox', 'step'], ['max_step_vox', 'max step'], ['off_center_mm', 'off ctr mm'], ['stray_mm', 'stray mm'], ['tilt_deg', 'tilt °'],
    ['wiggle_mm', 'wiggle mm'], ['path_over_height', 'path/ht'], ['stamped', 'stamp'], ['usable_ends', 'usable ends'], ['licence', 'licence'], ['sha256', 'sha256']],
  scans: [['scroll', 'scroll'], ['scan', 'scan'], ['voxel_um', 'µm'], ['slices', 'z'], ['height_px', 'y'], ['width_px', 'x'], ['height_mm', 'height mm'], ['width_mm', 'width mm'],
    ['levels', 'levels'], ['grand_prize', 'GP'], ['lines', 'lines'], ['sources', 'sources'], ['grade', 'grade'], ['pair_median_mm', 'pair gap mm'], ['pair_max_mm', 'pair max mm']],
};
const DEC = { height_mm: 1, coverage: 2, median_step_vox: 0, max_step_vox: 0, off_center_mm: 2, stray_mm: 2, tilt_deg: 2, wiggle_mm: 3, path_over_height: 4, width_mm: 1, voxel_um: 3, pair_median_mm: 2, pair_max_mm: 2 };
const SHEET = { tab: 'lines', key: null, dir: 1 };
function cellHTML(k, v) {
  if (v == null || v === '') return '<span class="dim">·</span>';
  if (k === 'grade') return `<span class="grade ${v}">${v}</span>`;
  if (k === 'sha256') return `<button class="lk mono" data-copy="${v}" data-what="sha256 copied">${v.slice(0, 10)}…</button>`;
  if (typeof v === 'boolean') return v ? 'yes' : '<span class="dim">no</span>';
  if (k === 'coverage') return `${fmt(v * 100, 0)}%`;
  if (typeof v === 'number' && k in DEC) return fmt(v, DEC[k]);
  return String(v);
}
function renderSheet() {
  const rows = SHEET.tab === 'lines' ? lineRows() : scanRows(); const cols = COLS[SHEET.tab];
  if (SHEET.key) rows.sort((a, b) => { const u = a[SHEET.key], v = b[SHEET.key]; return (u > v ? 1 : u < v ? -1 : 0) * SHEET.dir; });
  $('tbl').innerHTML = `<thead><tr>${cols.map(([k, h]) => `<th data-k="${k}" class="${SHEET.key === k ? (SHEET.dir > 0 ? 'up' : 'dn') : ''}">${h}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr data-scroll="${r.scroll}" class="${r.source === 'finder' ? 'cf' : ''}${r.withdrawn ? ' wd' : ''}">${cols.map(([k]) => `<td>${cellHTML(k, r[k])}</td>`).join('')}</tr>`).join('')}</tbody>`;
  $('sheet-note').textContent = `${rows.length} ${SHEET.tab}. Click a column to sort, a row to open its scan. Definitions: Guide, For researchers. Downloads hold every column and the full notes.`;
}
function openSheet(tab = 'lines') { SHEET.tab = tab; tabs($('sheet'), tab); renderSheet(); if (!$('sheet').open) $('sheet').showModal(); }
$('sheet').querySelector('.tabs').addEventListener('click', (e) => {
  const t = e.target.closest('[data-tab]'); if (t) { SHEET.tab = t.dataset.tab; SHEET.key = null; tabs($('sheet'), SHEET.tab); renderSheet(); return; }
  const d = e.target.closest('[data-dl]'); if (!d) return;
  if (d.dataset.dl === 'lines') download('umbilici_lines.csv', toCSV(lineRows()));
  else if (d.dataset.dl === 'scans') download('umbilici_scans.csv', toCSV(scanRows()));
  else if (d.dataset.dl === 'points') download('umbilici_points.csv', toCSV(pointRows()));
  else download('umbilici.json', JSON.stringify({ release: S.data.made, frame: S.data.frame, sources: S.data.sources, scans: S.data.scrolls.map(scanJSON) }, null, 1), 'application/json');
});
$('tbl').addEventListener('click', (e) => {
  if (e.target.closest('[data-copy]')) return;
  const th = e.target.closest('th[data-k]'); if (th) { const k = th.dataset.k; SHEET.dir = SHEET.key === k ? -SHEET.dir : 1; SHEET.key = k; renderSheet(); return; }
  const tr = e.target.closest('tr[data-scroll]'); if (tr) { $('sheet').close(); select(tr.dataset.scroll, S.mode === 'lasagna' && tr.dataset.scroll === LASAGNA_SCROLL ? 'lasagna' : 'scan'); }
});
$('b-sheet').addEventListener('click', () => openSheet(SHEET.tab));

// settings
function applySettings(save = true) {
  bloom.strength = SET.glow; bloom.radius = SET.radius;
  const pr = pixelRatio(); if (Math.abs(renderer.getPixelRatio() - pr) > 1e-3) { renderer.setPixelRatio(pr); composer.setPixelRatio(pr); }
  document.body.classList.toggle('nofilm', !SET.film);
  $('s-glow').value = Math.round(SET.glow * 100); $('s-glow-v').textContent = SET.glow.toFixed(2);
  $('s-radius').value = Math.round(SET.radius * 100); $('s-radius-v').textContent = SET.radius.toFixed(2);
  $('s-quality').value = SET.quality; $('s-film').checked = SET.film; $('s-spin').checked = SET.spin;
  if (!SET.spin) controls.autoRotate = false;
  applyVolUniforms(); S.dirty = true; if (save) saveSet();
}
$('b-set').addEventListener('click', (e) => { e.stopPropagation(); $('settings').hidden = !$('settings').hidden; });
document.addEventListener('pointerdown', (e) => { if (!$('settings').hidden && !e.target.closest('#settings, #b-set')) $('settings').hidden = true; });
$('s-glow').addEventListener('input', (e) => { SET.glow = e.target.value / 100; applySettings(); });
$('s-radius').addEventListener('input', (e) => { SET.radius = e.target.value / 100; applySettings(); });
$('s-quality').addEventListener('change', (e) => { SET.quality = e.target.value; applySettings(); });
$('s-film').addEventListener('change', (e) => { SET.film = e.target.checked; applySettings(); });
$('s-spin').addEventListener('change', (e) => { SET.spin = e.target.checked; applySettings(); });
$('s-reset').addEventListener('click', () => { Object.assign(SET, SET_DEFAULT); applySettings(); });

// first visit
function seen() { try { return localStorage.getItem('umbilici.seen') === '1'; } catch { return true; } }
function markSeen() { try { localStorage.setItem('umbilici.seen', '1'); } catch { /* private window */ } $('hint').hidden = true; }
$('hint-go').addEventListener('click', () => { markSeen(); openGuide('basics'); });
$('hint-x').addEventListener('click', markSeen);


// hover and pick in the array
const ray = new THREE.Raycaster(); const ndc = new THREE.Vector2(); let downAt = null;
canvas.addEventListener('pointermove', (e) => {
  if (S.mode !== 'array') return;
  if (e.buttons || moving) { if (S.hot) { S.hot = null; S.dirty = true; } $('tip').hidden = true; return; }
  ndc.set(e.clientX / innerWidth * 2 - 1, -e.clientY / innerHeight * 2 + 1); ray.setFromCamera(ndc, camera);
  const h = ray.intersectObjects(hitMeshes, false)[0]; const name = h ? h.object.userData.scroll : null;
  if (name !== S.hot) { S.hot = name; S.dirty = true; document.querySelectorAll('#rail li').forEach((li) => li.classList.toggle('hot', li.dataset.scroll === name)); }
  const tip = $('tip');
  if (name) {
    const s = S.data.scrolls.find((q) => q.scroll === name); const g = gradeOf(s);
    tip.innerHTML = `<b>${name}</b><br>${s.lines.map((l) => S.data.sources[l.source].label).join(', ')}${g ? `<br>end check <span class="grade ${g}">${g}</span>` : ''}<br><span class="dim">click to open in X-ray</span>`;
    tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 14}px`; tip.hidden = false; canvas.style.cursor = 'pointer';
  } else { tip.hidden = true; canvas.style.cursor = ''; }
});
canvas.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  if (S.mode === 'array' && S.hot) { $('tip').hidden = true; select(S.hot, 'scan'); }
});

// highlight the hovered scan
// Hover dims the other scans, easing over a few frames; it never jumps, and it waits while the camera is dragged,
// since a drag sweeping the pointer across scans used to halve and restore the whole glow many times a second.
function applyHot() {
  let busy = false;
  for (const g of arrayGroup.children) {
    if (!g.userData.scroll) continue; const on = !S.hot || g.userData.scroll === S.hot;
    g.traverse((o) => {
      if (!o.isMesh || !o.material || o.material.visible === false || o.material.opacity === undefined) return;
      const base = o.userData.base ?? 1, goal = on ? base : base * 0.4, cur = o.material.opacity;
      if (Math.abs(goal - cur) > 0.004) { o.material.opacity = cur + (goal - cur) * 0.18; busy = true; } else o.material.opacity = goal;
    });
  }
  if (busy) S.dirty = true;
}

// ---------- URL and agent API ----------
function syncURL() {
  const q = new URLSearchParams();
  if (S.mode !== 'array') { q.set('mode', S.mode); q.set('scan', S.sel.scroll); q.set('z', Math.round(S.z)); }
  if (S.ex !== 3) q.set('ex', S.ex);
  history.replaceState(null, '', q.toString() ? `?${q}` : location.pathname);
}
window.umbilici = {
  version: () => VERSION,
  scans: () => S.data.scrolls.map((s) => ({ scroll: s.scroll, scan: s.scan, volume: s.volume, voxel_um: s.voxel_um, shape_zyx: s.shape, grand_prize: s.grand_prize, first_letters: s.first_letters, sources: s.lines.map((l) => l.source), grade: gradeOf(s) })),
  lines: (name) => { const s = S.data.scrolls.find((q) => q.scroll === name); return s ? s.lines.map((l) => ({ ...l, points: linePts(l) })) : null; },
  at: (name, z) => { const s = S.data.scrolls.find((q) => q.scroll === name); return s ? s.lines.map((l) => ({ source: l.source, xy: lineAt(l, z) })) : null; },
  select: (name, mode = 'scan') => select(name, mode),
  mode: (m) => setMode(m),
  setZ: (z) => setZ(z, true),
  state: () => ({ mode: S.mode, scan: S.sel?.scroll ?? null, z: S.z, ex: S.ex, ct: { loaded: vol?.loaded ?? 0, total: vol?.total ?? 0 }, render: S.render, pixel_ratio: renderer.getPixelRatio(), auto_level: autoLevel }),
  image: () => { composer.render(); return renderer.domElement.toDataURL('image/png'); },
  slice: () => sc.toDataURL('image/png'),
  stats: (name) => { const s = S.data.scrolls.find((q) => q.scroll === name); return s ? { lines: s.lines.map((l) => ({ source: l.source, file: RAW(l), ...statsOf(s, l) })), pairs: pairsOf(s) } : null; },
  table: (which = 'lines') => (which === 'scans' ? scanRows() : lineRows()),
  csv: (which = 'lines') => toCSV(which === 'scans' ? scanRows() : which === 'points' ? pointRows() : lineRows()),
  guide: (tab) => openGuide(tab),
  bench: (n = 20) => { const t0 = performance.now(); const gl = renderer.getContext(), px = new Uint8Array(4); for (let i = 0; i < n; i++) { composer.render(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); } return { ms_per_frame: +((performance.now() - t0) / n).toFixed(1), pixel_ratio: renderer.getPixelRatio(), size: [innerWidth, innerHeight] }; },
  settings: (s) => { if (s) { Object.assign(SET, s); applySettings(); } return { ...SET }; },
  data: (tab) => openSheet(tab),
};

// ---------- loop ----------
const frames = []; let lastFrame = 0, stepPending = false;
function tick() {
  requestAnimationFrame(tick);
  controls.update();
  if (S.mode === 'array') applyHot();
  if (S.dirty || controls.autoRotate) {
    composer.render(); placeLabels(); S.dirty = false;
    const now = performance.now();
    if (now - lastFrame < 250) frames.push(now - lastFrame);
    lastFrame = now;
    if (frames.length >= 24) {
      const m = median(frames); frames.length = 0;
      if (SET.quality === 'auto' && m > 25 && autoLevel < 2) stepPending = true;
    }
    if (stepPending && !moving) { stepPending = false; const s = autoSteps(); let k = autoLevel + 1; while (k < 2 && s[k] >= s[autoLevel]) k++; if (s[k] < s[autoLevel]) { autoLevel = k; applySettings(false); } }
  }
}

// ---------- boot ----------
(async () => {
  S.data = await getJSON('data/lines.json');
  try { S.las = await getJSON('data/lasagna/meta.json'); } catch { S.las = null; document.querySelector('.chip.las').disabled = true; }
  $('k-count').textContent = S.data.scrolls.length;
  $('a-sources').innerHTML = Object.entries(S.data.sources).map(([k, v]) => {
    const l = S.data.scrolls.flatMap((s) => s.lines).find((q) => q.source === k); const n = S.data.scrolls.filter((s) => s.lines.some((q) => q.source === k)).length;
    const names = S.data.scrolls.filter((s) => s.lines.some((q) => q.source === k)).map((s) => s.scroll).join(', ');
    return `<li><b class="${k === 'finder' ? 'amber' : 'ice'}">${v.label}</b> (${v.short}): ${n} scan${n === 1 ? '' : 's'}, ${l ? l.licence : ''}. <span class="dim">Credit as given: ${l ? l.credit : ''}. ${names}.</span></li>`;
  }).join('');
  const all = S.data.scrolls.flatMap((s) => s.lines.map((l) => [s, l]));
  const bare = all.filter(([s, l]) => !statsOf(s, l).stamped);
  $('g-nscan').textContent = S.data.scrolls.length; $('g-nline').textContent = all.length; $('g-nsrc').textContent = Object.keys(S.data.sources).length;
  $('g-stamped').textContent = all.length - bare.length;
  const bareBy = {}; for (const [, l] of bare) bareBy[S.data.sources[l.source].label] = (bareBy[S.data.sources[l.source].label] || 0) + 1;
  $('g-unstamped').textContent = bare.length ? `the ${bare.length} without it (${Object.entries(bareBy).map(([k, n]) => `${k}: ${n}`).join('; ')})` : 'none';
  $('g-made').textContent = S.data.made; $('g-frame').textContent = S.data.frame;
  $('g-nlev').textContent = S.data.scrolls.reduce((n, s) => n + s.pyramid.length, 0);
  $('g-las').textContent = S.las ? `cos at ${S.las.slice_z.length} heights (z ${S.las.slice_z.join(', ')}) as ${S.las.slice_px} px WebP; an orientation picture per height at ${S.las.ori_px} px (hue from the doubled in-plane angle, so a normal and its opposite match); ${S.las.needles.count.toLocaleString('en-US')} normals on a ${S.las.needles.grid_voxels.join(' x ')} voxel grid where cos > 40 and grad_mag > 20, with nz rebuilt as the square root of 1 - nx² - ny². Frame: ${S.las.frame}.` : 'not loaded.';
  // the lasagna dataset may still be on its way to the Hub: say so instead of linking a 404
  fetch('https://huggingface.co/api/datasets/SharpMeow/pherc0175a-lasagna', { credentials: 'omit' }).then((r) => {
    if (r.ok) return;
    document.querySelectorAll('a[href*="pherc0175a-lasagna"]').forEach((a) => { a.removeAttribute('href'); a.classList.add('soon'); a.title = 'being published to the Hub; check back soon'; a.textContent += ' (soon)'; });
  }).catch(() => {});
  const q = new URLSearchParams(location.search);
  if (q.get('ex')) { S.ex = Math.max(1, Math.min(30, +q.get('ex'))); $('ex').value = S.ex; $('ex-v').textContent = S.ex; }
  applySettings(false); buildRail(); buildArray();
  $('boot').remove();
  tick();
  if (q.get('scan')) { const m = q.get('mode') || 'scan'; select(q.get('scan'), m); if (q.get('z')) setZ(+q.get('z'), true); }
  else { setMode('array'); controls.autoRotate = SET.spin && !matchMedia('(prefers-reduced-motion: reduce)').matches; }
  if (q.get('guide')) openGuide(q.get('guide'));
  else if (q.get('data')) openSheet(q.get('data') === 'scans' ? 'scans' : 'lines');
  else if (!seen() && !navigator.webdriver) $('hint').hidden = false;
})().catch((e) => { $('boot').textContent = `could not load: ${e.message}`; console.error(e); });
