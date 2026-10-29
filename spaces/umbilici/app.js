// Umbilici: the center lines of the prize-eligible Herculaneum scans and the other public scans, over live X-ray CT.
// Apache 2.0, Chase Hendrick. CT is read in the visitor's browser from the Vesuvius Challenge open-data bucket.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const VERSION = '1.12.0';
const DATASET = 'https://huggingface.co/datasets/SharpMeow/vesuvius-center-lines';
const LASAGNA_SCROLL = 'PHerc0175A';
const ICE = new THREE.Color('#89f0ff');
const AMBER = new THREE.Color('#ffb347');
// one color per maker, so two people's lines on one scan never share a color (Chase, 24 Oct 2026)
const SRC_HEX = { bucket: '#89f0ff', drobkov: '#ff7eb6', tauil: '#b69cff', dopico: '#f2f5f7', finder: '#ffb347', 'finder-polished': '#c6f36b', 'finder-v2': '#ff7a59' };
const SRC_OTHER = '#d8d0c0'; // a maker the dataset added after this page was built
const SRC_COL = Object.fromEntries(Object.entries(SRC_HEX).map(([k, v]) => [k, new THREE.Color(v)]));
const colOf = (l) => SRC_COL[l.source] || ICE;
const hexOf = (l) => SRC_HEX[l.source] || '#89f0ff';
const COARSE = matchMedia('(pointer: coarse)').matches;
// the Array view's opening camera: high enough that its three rows (people, Center Finder, not on the prize page) stand apart
const ARRAY_CAM = [-620, 760, 2300];
const $ = (id) => document.getElementById(id);

// ---------- state ----------
const S = {
  data: null, las: null, mode: 'array', sel: null, hot: null, ex: 3, z: null,
  ct: true, render: 'xray', gain: 44, sheets: true, needles: true, ct2: false, ori: false, blend: 70,
  dirty: true, status: '',
};

// ---------- renderer ----------
const canvas = $('gl');
// No canvas antialias or preserved buffer: the composer draws into its own targets, so both only cost memory and a
// copy per frame; image() reads the canvas in the same task as its render.
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: false, powerPreference: 'high-performance' });
const DPR = Math.min(devicePixelRatio || 1, 2);
renderer.setPixelRatio(DPR);
renderer.setSize(innerWidth, innerHeight);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#02060a');
const camera = new THREE.PerspectiveCamera(32, innerWidth / innerHeight, 1, 20000);
camera.position.set(...ARRAY_CAM).multiplyScalar(Math.max(1, 1.25 / camera.aspect));
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
let userMoved = false;
controls.addEventListener('start', () => { moving = true; userMoved = true; clearTimeout(settleT); controls.autoRotate = false; applyVolUniforms(); });
controls.addEventListener('end', () => { clearTimeout(settleT); settleT = setTimeout(() => { moving = false; applyVolUniforms(); S.dirty = true; }, 150); });

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
// ---------- settings (glow, quality, film), kept per viewer ----------
const SET_DEFAULT = { glow: 0.25, radius: 0.5, quality: 'auto', film: true, spin: true, inset: true, turn: false };
const SET = { ...SET_DEFAULT };
// a saved glow of 0.8 is the old default (1.11 and earlier saved every setting on any change), so it gives way to the new one
try { const saved = JSON.parse(localStorage.getItem('umbilici.settings') || '{}'); if (saved.glow === 0.8) delete saved.glow; Object.assign(SET, saved); } catch { /* storage blocked */ }
{ const q = new URLSearchParams(location.search); if (q.has('glow')) SET.glow = Math.max(0, Math.min(3, +q.get('glow') || 0)); }
// only the settings a viewer changed are kept, so a later default reaches everyone else
function saveSet() { try { localStorage.setItem('umbilici.settings', JSON.stringify(Object.fromEntries(Object.entries(SET).filter(([k, v]) => v !== SET_DEFAULT[k])))); } catch { /* storage blocked */ } }
// auto quality starts at 1.25 pixels per CSS pixel (1 on touch screens) and steps down, at most twice, when frames
// run slow; 'high' is the screen's full density and 'low' is 0.75
let autoLevel = 0;
function autoSteps() { const d = Math.min(devicePixelRatio || 1, 2); return [Math.min(d, COARSE ? 1 : 1.25), Math.min(d, 1), 0.75]; }
function pixelRatio() { const d = Math.min(devicePixelRatio || 1, 2); return SET.quality === 'low' ? 0.75 : SET.quality === 'high' ? d : autoSteps()[autoLevel]; }
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), SET.glow, SET.radius, 0.55);
composer.addPass(bloom);
composer.addPass(new OutputPass());

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
  // the Hub sizes the Space's frame after the page loads; keep the opening view framed until the visitor moves it
  if (S.mode === 'array' && !userMoved) fitArray();
  S.dirty = true;
});
function fitArray() { const k = Math.max(1, 1.25 / camera.aspect); const a = controls.getAzimuthalAngle(); const r = Math.hypot(ARRAY_CAM[0], ARRAY_CAM[2]) * k;
  camera.position.set(Math.sin(a) * r, ARRAY_CAM[1] * k, Math.cos(a) * r); camera.far = 20000; camera.updateProjectionMatrix(); }

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
// an older version (superseded_by names the newer line's file) or a withdrawn line is drawn faded
const isOld = (l) => !!l.superseded_by || l.note.includes('withdrawn');
const isNewest = (s, l) => s.lines.some((o) => o.superseded_by === l.file);
// lines the visitor switched off: a whole maker (legend) or one line (scan card); kept in the URL as off=
const OFF = { src: new Set(), line: new Set() };
const lineKey = (s, l) => `${s.scroll}:${l.source}`;
const shown = (s, l) => !OFF.src.has(l.source) && !OFF.line.has(lineKey(s, l));
const hasFinder = (s) => s.lines.some(isFinder);
function gradeOf(s) { const f = s.lines.find(isFinder); return f ? f.grade : null; }
// traffic light for a Center Finder line: red when an end is flagged, yellow (caution) when the check could not judge
// an end, the scan is one the check was never tuned for, or a pass rests on a CT recap; green when both ends passed
function lightOf(l) {
  if (!l || !l.grade) return null;
  if (l.grade === 'FLAG') return 'bad';
  const recap = l.ends && Object.values(l.ends).some((e) => e.recapped);
  return l.grade === 'VOID' || l.untested || recap ? 'caution' : 'good';
}
const LIGHT_WORD = { good: 'both ends passed the CT end check', caution: 'caution: a CT recap, an end the check could not judge, or a scan the check was not tuned for', bad: 'an end was flagged by the CT end check' };
const onPrize = (s) => s.first_letters || s.grand_prize;
function numberWords(n) {
  const ones = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
  const tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
  return n < 20 ? ones[n] : n < 100 ? tens[Math.floor(n / 10)] + (n % 10 ? '-' + ones[n % 10] : '') : String(n);
}
// the prize page's word for a scan: GP, FL, both in the card kicker, or none for a scan not on the page
const prizeTag = (s) => s.grand_prize ? 'GP' : s.first_letters ? 'FL' : '';
const prizeWords = (s) => !onPrize(s) ? 'NOT ON THE PRIZE PAGE' : [s.grand_prize && 'GRAND PRIZE', s.first_letters && 'FIRST LETTERS'].filter(Boolean).join(' · ');
// the pyramid level of scan s that stands in for level L of a 1.2 m (about 9 µm) scan: a 2.4 µm scan reads two levels
// coarser where its pyramid has them; every pyramid here stops at level 5, so its slices are read at level 5
function lv(s, L) { return Math.min(s.pyramid.length - 1, L + Math.max(0, Math.round(Math.log2(8.64 / s.voxel_um)))); }
function usable(l) {
  if (Array.isArray(l.usable)) return l.usable.length ? l.usable.join(', ') : 'none';
  const m = /usable ends: ([a-z, ]+)/.exec(l.note || ''); return m ? m[1] : null;
}
// one end's grade as the dataset words it, e.g. "low PASS (CT recap)"
function endText(l, k) { const e = l.ends && l.ends[k]; return e ? `${k} ${e.grade}${e.recapped ? ' (CT recap)' : ''}` : ''; }
// the same, as colored HTML
function endHTML(l, k) { const e = l.ends && l.ends[k]; return e ? `<span class="end">${k} <span class="grade ${e.grade}">${e.grade}</span>${e.recapped ? '<span class="rc">CT recap</span>' : ''}</span>` : ''; }
function endsHTML(l) { return `<span class="ends">${['low', 'high'].map((k) => endHTML(l, k)).filter(Boolean).join('')}</span>`; }
function endsText(l) { return l.ends && Object.keys(l.ends).length ? ['low', 'high'].map((k) => endText(l, k)).filter(Boolean).join(', ') : ''; }
const GRADE_TEXT = {
  PASS: 'both ends passed the automatic CT end check',
  FLAG: 'the automatic CT end check flagged an end: there the line sits more than 4 mm from the center the CT shows',
  VOID: 'the end check could not judge this line',
};
const UNTESTED = 'the CT end check was tuned on 1.2 m (about 9 µm) scans only; on this scan its grades are untested, so no end is marked usable';

// ---------- statistics (definitions: Guide, For researchers) ----------
const RAW = (l) => `${DATASET}/resolve/main/${l.file}`;
// a line's license, under the key the dataset publishes (index.json, and data/lines.json built from it); kept as
// published so every reader of those files keeps working. The page's own tables and labels say license.
const lic = (l) => l.licence;
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
      kind: l.kind, grade: l.grade || '', ct_untested: !!l.untested, ct_end_low: endText(l, 'low'), ct_end_high: endText(l, 'high'), usable_ends: isFinder(l) ? (usable(l) || '') : '', withdrawn: l.note.includes('withdrawn'), superseded: !!l.superseded_by,
      ...t, license: lic(l), sha256: l.sha256, file: RAW(l), upstream: l.upstream, note: l.note,
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
  const prize = S.data.scrolls.filter(onPrize);
  const people = prize.filter((s) => !hasFinder(s));
  const finder = prize.filter(hasFinder);
  const other = S.data.scrolls.filter((s) => !onPrize(s));   // not on the prize page: a row behind the two prize rows
  const rows = [[people, -150], [finder, 170], [other, -560]];
  for (const [list, rz] of rows) {
    const step = 112, x0 = -(list.length - 1) * step / 2;
    list.forEach((s, i) => {
      const g = new THREE.Group(); g.position.set(x0 + i * step, 0, rz); g.userData.scroll = s.scroll;
      const H = mm(s, s.shape[0]);
      const [cx, cy] = lineMean(s.lines[0]);
      for (const l of s.lines) {
        if (!shown(s, l)) continue;
        const pts = linePts(l).map(([x, y, z]) => [mm(s, x - cx) * S.ex, mm(s, z), mm(s, y - cy) * S.ex]);
        g.add(tube(pts, colOf(l), 0.9, isOld(l) ? 0.45 : 1));
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
      const lt = lightOf(s.lines.find(isFinder));
      const el = document.createElement('div'); el.className = 'lbl' + (hasFinder(s) ? ' cf' : '') + (lt ? ` ${lt}` : '') + (onPrize(s) ? '' : ' np');
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
// The page reads one axial plane of a chunk per request, which only works on uncompressed chunks. A scan stored with a
// compressor (PHerc0172's 7.91 µm scan, Blosc zstd, from center lines v2.6) keeps its lines but gets no CT here.
const streamable = (s) => !s.pyramid.some((p) => p.compressor);
const NO_CT = (s) => `no CT here: this scan's chunks are ${s.pyramid.find((p) => p.compressor)?.compressor || 'compressed'}-compressed and the page reads only uncompressed ones`;
async function zmeta(s, L) {
  const k = `${s.zarr}/${L}`; if (!zarrMeta.has(k)) zarrMeta.set(k, getJSON(`${k}/.zarray`)); return zarrMeta.get(k);
}
let inflight = 0; const waiters = [];
const MAXQ = 10;
const MAX_PX = 640, READS = 2400; // the X-ray volume: widest plane kept, range reads per scan (see loadVolume)
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
const sliceCache = new Map(); // `${zarr}/${L}/${z}` -> slice, last 48 kept
async function ctSlice(s, L, z0, signal) {
  const m = await zmeta(s, L); const [Z, Y, X] = m.shape; const [cz, cy, cx] = m.chunks;
  const z = Math.min(Z - 1, Math.max(0, Math.floor(z0 / 2 ** L)));
  const key = `${s.zarr}/${L}/${z}`; const hit = sliceCache.get(key);
  if (hit) { sliceCache.delete(key); sliceCache.set(key, hit); return hit; }
  const res = await ctSliceFetch(s, L, z, m, signal);
  if (!signal?.aborted) { sliceCache.set(key, res); if (sliceCache.size > 48) sliceCache.delete(sliceCache.keys().next().value); }
  return res;
}
async function ctSliceFetch(s, L, z, m, signal) {
  const [, Y, X] = m.shape; const [cz, cy, cx] = m.chunks;
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
  const L = 5; const m = await zmeta(s, L); const [Z, Y0, X0] = m.shape; const [cz, cy, cx] = m.chunks;
  // A 2.4 µm scan's level-5 plane is up to 1,326 px across (a 1.2 m scan's about 250): it is read whole, kept every
  // f-th pixel, and fewer heights are read (at least 24), so one scan costs at most about READS range reads.
  const f = Math.max(1, Math.ceil(Math.max(X0, Y0) / MAX_PX)); const X = Math.ceil(X0 / f), Y = Math.ceil(Y0 / f);
  const per = Math.ceil(Y0 / cy) * Math.ceil(X0 / cx);
  const stride = Math.max(1, Math.ceil(Z / Math.max(24, Math.min(COARSE ? 72 : 120, Math.floor(READS / per)))));
  const zs = []; for (let z = 0; z < Z; z += stride) zs.push(z);
  const D = zs.length; const data = new Uint8Array(X * Y * D);
  const tex = new THREE.Data3DTexture(data, X, Y, D);
  tex.format = THREE.RedFormat; tex.type = THREE.UnsignedByteType; tex.minFilter = tex.magFilter = THREE.LinearFilter; tex.unpackAlignment = 1; tex.needsUpdate = true;
  const mat = new THREE.ShaderMaterial({
    vertexShader: VOL_VS, fragmentShader: VOL_FS, side: THREE.BackSide, transparent: true, depthWrite: false, depthTest: false,
    blending: THREE.AdditiveBlending, uniforms: { uVol: { value: tex }, uCam: { value: new THREE.Vector3() }, uGain: { value: S.gain }, uMode: { value: 0 }, uFill: { value: 1 }, uN: { value: COARSE ? 140 : 220 } },
  });
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat);
  mesh.scale.set(mm(s, X * f * 32), mm(s, zs[D - 1] * 32 + stride * 32), mm(s, Y * f * 32));
  mesh.position.set(0, mesh.scale.y / 2, 0); mesh.renderOrder = 1;
  mesh.onBeforeRender = (r, sc, cam) => { mat.uniforms.uCam.value.copy(cam.position).applyMatrix4(new THREE.Matrix4().copy(mesh.matrixWorld).invert()); };
  parent.add(mesh);
  const abort = new AbortController();
  vol = { s, mesh, tex, abort, loaded: 0, total: D, data, zs, X, Y, f, stride, done: null };
  applyVolUniforms();
  // coarse to fine: every 4th slice first (copied into its gap), then the rest
  const order = []; for (let i = 0; i < D; i += 4) order.push(i); for (let i = 0; i < D; i++) if (i % 4) order.push(i);
  const done = new Uint8Array(D); vol.done = done; let lastUp = 0;
  const one = async (i) => {
    const z = zs[i]; const plane = X * Y; const tasks = [];
    for (let by = 0; by * cy < Y0; by++) for (let bx = 0; bx * cx < X0; bx++) {
      tasks.push(rangeGet(`${s.zarr}/${L}/${Math.floor(z / cz)}/${by}/${bx}`, (z % cz) * cy * cx, cy * cx, abort.signal).then((b) => {
        if (!b) return; const h = Math.min(cy, Y0 - by * cy), w = Math.min(cx, X0 - bx * cx);
        if (f === 1) { for (let r = 0; r < h; r++) data.set(b.subarray(r * cx, r * cx + w), i * plane + (by * cy + r) * X + bx * cx); return; }
        // keep the pixels whose level-5 row and column are multiples of f
        for (let r = (f - (by * cy) % f) % f; r < h; r += f) {
          const row = i * plane + ((by * cy + r) / f) * X;
          for (let q = (f - (bx * cx) % f) % f; q < w; q += f) data[row + (bx * cx + q) / f] = b[r * cx + q];
        }
      }));
    }
    await Promise.all(tasks);
    done[i] = 1;
    if (i % 4 === 0) for (let k = i + 1; k < Math.min(D, i + 4); k++) if (!done[k]) data.copyWithin(k * plane, i * plane, (i + 1) * plane);
    vol && vol.tex === tex && (vol.loaded++);
    const now = performance.now(); if (now - lastUp > 1200 || vol?.loaded === D) { lastUp = now; tex.needsUpdate = true; S.dirty = true; setStatus(); }
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
  el.textContent = vol ? (vol.loaded < vol.total ? `streaming CT ${Math.round(100 * vol.loaded / vol.total)}%` : `CT level 5${vol.f > 1 ? `, every ${vol.f === 2 ? 'second' : vol.f === 3 ? 'third' : `${vol.f}th`} pixel` : ''} (${fmt(vol.s.voxel_um * 32 * vol.f, 0)} µm voxels), ${vol.total} heights`) : S.sel && !streamable(S.sel) ? NO_CT(S.sel) : '';
}

// ---------- SCAN view ----------
const scanGroup = new THREE.Group(); scene.add(scanGroup);
let slicePlane = null, sliceTex = null;
let lasGroup = null;
function scanOrigin(s) { return [s.shape[2] / 2, s.shape[1] / 2]; }
function toWorld(s, x, y, z) { const [ox, oy] = scanOrigin(s); return [mm(s, x - ox), mm(s, z), mm(s, y - oy)]; }
const scanLines = new THREE.Group();
function buildScanLines(s) {
  scanLines.clear();
  for (const l of s.lines) if (shown(s, l)) scanLines.add(tube(linePts(l).map(([x, y, z]) => toWorld(s, x, y, z)), colOf(l), 0.55, isOld(l) ? 0.5 : 1));
  S.dirty = true;
}
function buildScan(s) {
  disposeVol(); scanGroup.clear(); lasGroup = null;
  scanGroup.add(scanLines); buildScanLines(s);
  const W = mm(s, s.shape[2]), D = mm(s, s.shape[1]), H = mm(s, s.shape[0]);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(W, H, D)), new THREE.LineBasicMaterial({ color: ICE, transparent: true, opacity: 0.12 }));
  frame.position.y = H / 2; scanGroup.add(frame);
  // slice plane, textured from the inset canvas
  sliceTex = new THREE.CanvasTexture(tc); sliceTex.colorSpace = THREE.SRGBColorSpace;
  slicePlane = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshBasicMaterial({ map: sliceTex, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }));
  slicePlane.rotation.x = -Math.PI / 2; slicePlane.renderOrder = 2; scanGroup.add(slicePlane);
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(W, D)), new THREE.LineBasicMaterial({ color: ICE, transparent: true, opacity: 0.5, toneMapped: false }));
  slicePlane.add(edge);
  if (s.scroll === LASAGNA_SCROLL && S.las) buildLasagna(s);
  if (streamable(s)) loadVolume(s, scanGroup);
  setStatus();
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
// The slice is composed off screen (CT and lasagna only) and shown in one step by present(), so the inset never shows
// a cleared black frame while CT is still streaming. present() also turns it with the 3D view when asked and draws
// the line marks last, upright.
const sc = $('slice'), vx = sc.getContext('2d');
const buf = document.createElement('canvas'); buf.width = sc.width; buf.height = sc.height; const sx = buf.getContext('2d');
let shownAngle = null;
function viewAngle() { return SET.turn && S.mode !== 'array' ? controls.getAzimuthalAngle() : 0; }
// the 3D slice plane keeps its own unturned copy, since it already sits in the scene's frame
const tc = document.createElement('canvas'); tc.width = sc.width; tc.height = sc.height; const tx = tc.getContext('2d');
function present(turnOnly = false) {
  const s = S.sel; if (!s) return;
  const a = viewAngle(); shownAngle = a; const W = sc.width, c = W / 2;
  vx.setTransform(1, 0, 0, 1, 0, 0); vx.fillStyle = '#000'; vx.fillRect(0, 0, W, W);
  vx.translate(c, c); vx.rotate(a); vx.translate(-c, -c); vx.drawImage(buf, 0, 0); vx.setTransform(1, 0, 0, 1, 0, 0);
  drawMarks(vx, s, S.z, a);
  if (turnOnly) return;
  tx.drawImage(buf, 0, 0); drawMarks(tx, s, S.z, 0);
  if (sliceTex) sliceTex.needsUpdate = true; S.dirty = true;
}
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
  const im = new ImageData(sl.X, sl.Y); const d32 = new Uint32Array(im.data.buffer); const map = new Uint32Array(256);
  for (let v = 0; v < 256; v++) { const t = v <= 2 ? 0 : Math.max(0, Math.min(255, (v - lo) * 255 / span)); const q = LUT[t | 0]; map[v] = (255 << 24 | (q[2] & 255) << 16 | (q[1] & 255) << 8 | (q[0] & 255)) >>> 0; }
  for (let i = 0, n = sl.data.length; i < n; i++) d32[i] = map[sl.data[i]];
  const tmp = new OffscreenCanvas(sl.X, sl.Y); tmp.getContext('2d').putImageData(im, 0, 0);
  sx.globalAlpha = alpha; sx.drawImage(tmp, 0, 0, sc.width, sc.height); sx.globalAlpha = 1;
}
function drawMarks(sx, s, z, a = 0) {
  // the slice fills the square inset whatever the scan's x and y extent, so x and y scale apart (PHerc0172 is not square)
  const kx = sc.width / s.shape[2], ky = sc.height / s.shape[1], c = sc.width / 2, ca = Math.cos(a), sa = Math.sin(a);
  for (const l of s.lines) {
    if (!shown(s, l)) continue;
    const p = lineAt(l, z); if (!p) continue;
    const u = p[0] * kx - c, v = p[1] * ky - c; const x = c + u * ca - v * sa, y = c + u * sa + v * ca; const col = hexOf(l);
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
      present(); $('i-status').textContent = 'model output · villa lasagna';
    } else if (!streamable(s)) {
      sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); present();
      $('i-status').textContent = `no CT: ${s.pyramid.find((p) => p.compressor).compressor}-compressed scan`;
    } else {
      $('i-status').textContent = 'streaming…';
      const Lq = lv(s, 4), Lf = lv(s, 3);
      const quick = await ctSlice(s, Lq, z, sig); if (job !== sliceJob) return;
      sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); drawCT(quick); present();
      if (Lf !== Lq) {
        await new Promise((r) => setTimeout(r, 220)); if (job !== sliceJob) return;
        const fine = await ctSlice(s, Lf, z, sig); if (job !== sliceJob) return;
        sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); drawCT(fine); present();
      }
      $('i-status').textContent = `CT level ${Lf} · ${fmt(s.voxel_um * 2 ** Lf, 0)} µm px`;
    }
  } catch (e) { if (e.name !== 'AbortError') { $('i-status').textContent = 'CT unavailable'; console.warn(e); } }
}
let zTimer = 0;
function setZ(z, now = false) {
  const s = S.sel; if (!s) return;
  if (S.mode === 'lasagna' && S.las && s.scroll === LASAGNA_SCROLL) { const zs = S.las.slice_z; z = zs.reduce((a, b) => Math.abs(b - z) < Math.abs(a - z) ? b : a, zs[0]); }
  S.z = Math.max(0, Math.min(s.shape[0] - 1, z));
  $('z').value = Math.round(1000 * S.z / s.shape[0]);
  clearTimeout(zTimer); if (now) drawSlice(); else { livePreview(s); zTimer = setTimeout(drawSlice, 90); }
  if (slicePlane) slicePlane.position.y = mm(s, S.z); S.dirty = true; drawHere(); syncURLSoon();
}
// While the height slider moves, the inset follows at once from the level-5 CT already in memory for the 3D view
// (or from a cached finer slice), and the finer levels replace it when the slider rests.
function livePreview(s) {
  if (S.mode === 'lasagna') return;
  const z = S.z; $('i-z').textContent = `z ${Math.round(z)} · ${fmt(mm(s, z), 1)} mm`;
  for (const L of new Set([lv(s, 3), lv(s, 4)])) { const hit = sliceCache.get(`${s.zarr}/${L}/${Math.floor(z / 2 ** L)}`); if (hit) { sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); drawCT(hit); present(); return; } }
  const v = vol && vol.s === s && vol.done ? vol : null; if (!v) return;
  const i = Math.max(0, Math.min(v.zs.length - 1, Math.round(z / 32 / v.stride))); if (!v.done[i] && !v.done[i - (i % 4)]) return;
  const plane = v.X * v.Y; const sl = { data: v.data.subarray(i * plane, (i + 1) * plane), X: v.X, Y: v.Y };
  sx.fillStyle = '#000'; sx.fillRect(0, 0, sc.width, sc.height); drawCT(sl); present();
}
$('z').addEventListener('input', (e) => { if (S.sel) setZ(e.target.value / 1000 * S.sel.shape[0]); });
sc.addEventListener('wheel', (e) => { if (!S.sel) return; e.preventDefault(); const step = S.mode === 'lasagna' ? 1280 * Math.sign(e.deltaY) : S.sel.shape[0] / 200 * Math.sign(e.deltaY); setZ(S.z - step); }, { passive: false });

// ---------- showing and hiding lines ----------
function buildLegend() {
  const used = Object.keys(S.data.sources).filter((k) => S.data.scrolls.some((s) => s.lines.some((l) => l.source === k)));
  $('legend').innerHTML = used.map((k) => `<button class="lg${OFF.src.has(k) ? ' off' : ''}" data-src="${k}" aria-pressed="${!OFF.src.has(k)}" title="show or hide every line by ${S.data.sources[k].label}"><i class="sw" style="background:${SRC_HEX[k]};box-shadow:0 0 6px ${SRC_HEX[k]}"></i>${k === 'finder' ? 'Center Finder (model output)' : k === 'finder-polished' ? 'Center Finder, polished (model output)' : k === 'finder-v2' ? 'Center Finder v2 (model output)' : S.data.sources[k].label}</button>`).join('');
}
function linesChanged() {
  buildLegend(); buildArray(); if (S.sel) { buildScanLines(S.sel); buildCard(S.sel); drawSlice(); }
  syncURLSoon();
}
// show(kind, name, on): kind 'source' (a maker, such as drobkov) or 'line' (SCROLL:SOURCE); on omitted toggles
function showLines(kind, name, on) {
  const set = kind === 'source' ? OFF.src : OFF.line;
  const now = on === undefined ? set.has(name) : !!on;
  if (now) set.delete(name); else set.add(name);
  linesChanged();
  return { off: [...OFF.src, ...OFF.line] };
}
document.addEventListener('click', (e) => { const b = e.target.closest('#legend [data-src]'); if (b) showLines('source', b.dataset.src); });
document.addEventListener('change', (e) => { const c = e.target.closest('input[data-line]'); if (c) showLines('line', c.dataset.line, c.checked); });

// ---------- UI ----------
// The header text and the view buttons wrap at different widths (on a phone the buttons take two rows), so the panels
// under them are placed from what is measured here, not from fixed offsets: --nav-w (the buttons' width, which the
// header's kicker keeps clear of on wide screens), --head-b (where the header text ends) and --nav-b (where the
// buttons end; the scan card, the first-visit hint and the settings sit under it on phones), and --bl-h (the height
// of the controls at bottom left, which the slice panel sits above in X-ray and Lasagna on phones). style.css has
// fallbacks.
const NAV = document.querySelector('nav.tr');
const BL = document.querySelector('.hud.bl');
function placeHud() {
  const css = document.documentElement.style;
  css.setProperty('--nav-w', `${Math.ceil(NAV.getBoundingClientRect().width)}px`);
  const head = Math.max(0, ...[...document.querySelectorAll('.tl .kicker, .tl h1')].map((e) => e.getBoundingClientRect().bottom));
  css.setProperty('--head-b', `${Math.ceil(head)}px`);
  css.setProperty('--nav-b', `${Math.ceil(NAV.getBoundingClientRect().bottom)}px`);
  css.setProperty('--bl-h', `${Math.ceil(BL.getBoundingClientRect().height)}px`);
}
let hudQueued = false;
const placeHudSoon = () => { if (!hudQueued) { hudQueued = true; requestAnimationFrame(() => { hudQueued = false; placeHud(); }); } };
if (window.ResizeObserver) { const ro = new ResizeObserver(placeHudSoon); ro.observe(document.querySelector('.tl')); ro.observe(NAV); ro.observe(BL); }
addEventListener('resize', placeHudSoon);
placeHud();
function railRow(s) {
  const li = document.createElement('li'); li.dataset.scroll = s.scroll;
  const srcs = s.lines.map((l) => `<span class="src s-${l.source}" title="${S.data.sources[l.source].label}">${S.data.sources[l.source].short}</span>`).join('');
  const g = gradeOf(s);
  const f = s.lines.find(isFinder); const ut = !!(f && f.untested); const lt = lightOf(f);
  li.innerHTML = `<span class="nm">${s.scroll}<small>${prizeTag(s)}</small></span><span class="srcs">${srcs}</span><span class="grade ${g || ''} ${lt ? 'lt-' + lt : ''}${ut ? ' ut' : ''}" title="${f ? endsText(f) + (ut ? `; ${UNTESTED}` : '') + (lt ? `; ${LIGHT_WORD[lt]}` : '') : ''}">${g || '·'}</span>`;
  li.addEventListener('click', () => select(s.scroll, S.mode === 'array' ? 'scan' : S.mode));
  li.addEventListener('mouseenter', () => { S.hot = s.scroll; S.dirty = true; });
  li.addEventListener('mouseleave', () => { S.hot = null; S.dirty = true; });
  return li;
}
function buildRail() {
  const ol = $('rail-list'); ol.innerHTML = '';
  let sep = false;
  for (const s of S.data.scrolls) {
    if (!onPrize(s) && !sep) { sep = true; const li = document.createElement('li'); li.className = 'sep mono'; li.textContent = 'NOT ON THE PRIZE PAGE'; ol.appendChild(li); }
    ol.appendChild(railRow(s));
  }
}
// the scan menu on the card: in X-ray and Lasagna the list is hidden, so the page keeps one scrolling panel (the card)
function buildPick() {
  const opt = (s) => `<option value="${s.scroll}">${s.scroll}${prizeTag(s) ? ' ' + prizeTag(s) : ''}</option>`;
  const on = S.data.scrolls.filter(onPrize), off = S.data.scrolls.filter((s) => !onPrize(s));
  $('c-pick').innerHTML = `<optgroup label="Prize page">${on.map(opt).join('')}</optgroup>` + (off.length ? `<optgroup label="Not on the prize page">${off.map(opt).join('')}</optgroup>` : '');
}
$('c-pick').addEventListener('change', (e) => { const name = e.target.value; select(name, S.mode === 'lasagna' && name !== LASAGNA_SCROLL ? 'scan' : S.mode === 'array' ? 'scan' : S.mode); e.target.blur(); });
function buildCard(s) {
  $('c-pick').value = s.scroll;
  $('c-kick').textContent = `SCAN ${s.scan} · ${s.voxel_um} µm · ${prizeWords(s)}`;
  $('c-title').textContent = s.scroll;
  $('c-lines').innerHTML = s.lines.map((l, i) => {
    const src = S.data.sources[l.source]; const f = isFinder(l); const t = statsOf(s, l);
    const up = /^https?:/.test(l.upstream) ? `<a href="${l.upstream}" target="_blank" rel="noopener">upstream</a>` : '';
    const grade = l.grade ? `<span class="grade ${l.grade} lt-${lightOf(l)}" title="${GRADE_TEXT[l.grade]}; ${LIGHT_WORD[lightOf(l)]}">END CHECK ${l.grade}${lightOf(l) === 'caution' ? ' · CAUTION' : ''}</span>` : `<span class="dim">${l.kind === 'person' ? 'made by a person' : ''}</span>`;
    const ends = endsText(l);
    const ver = l.superseded_by ? '<span class="ver old" title="a newer version of this line exists; it is kept for comparison">SUPERSEDED</span>' : (isNewest(s, l) ? '<span class="ver new" title="the newest version of this line; kit takes it by default">NEWEST</span>' : '');
    const was = l.superseded_by ? '<div class="note">Superseded: the newer version of this line is on this card, marked NEWEST. This one is kept for comparison and drawn faded.</div>' : '';
    const note = f ? `<div class="note">${ends ? `CT end check: ${endsHTML(l)}` : `${GRADE_TEXT[l.grade] || 'No CT end check'}.`}</div><div class="note">${l.untested ? `Untested: ${UNTESTED}. ` : ''}Usable ends: ${usable(l) || 'see note'}. Model output: no end has been checked on CT by a person.</div>`
      : (l.note ? `<div class="note">${l.note}${/[.!?]$/.test(l.note.trim()) ? '' : '.'}</div>` : '');
    const row = (k, v) => `<tr><th>${k}</th><td>${v}</td></tr>`;
    const k = lineKey(s, l);
    return `<div class="ln${shown(s, l) ? '' : ' off'}"><div class="who"><span class="name"><label class="show" title="show or hide this line"><input type="checkbox" data-line="${k}"${OFF.line.has(k) ? '' : ' checked'}${OFF.src.has(l.source) ? ' disabled' : ''}></label><b style="color:${hexOf(l)}">${src.label}</b></span><span class="tags">${ver}${grade}</span></div>
      <div class="meta">${t.points} points · z ${t.z_start} to ${t.z_end} (${fmt(t.height_mm, 0)} mm, ${fmt(t.coverage * 100, 0)}% of the scan) · strays up to ${fmt(t.stray_mm, 1)} mm from its mean · ${lic(l)}</div>${was}${note}
      <div class="links"><a href="${RAW(l)}" download>download</a><button class="lk" data-copy="${RAW(l)}" data-what="file URL copied">copy URL</button><button class="lk" data-copy="python -m kit centerline get ${s.scroll} --source ${l.source} --into YOUR_PROJECT_FOLDER" data-what="kit command copied: it writes YOUR_PROJECT_FOLDER/umbilicus.json" title="A command for the Scrolls kit that downloads this line, checks its sha256 and writes it as umbilicus.json where VC3D looks">copy kit command</button><a href="${DATASET}/blob/main/${l.file}" target="_blank" rel="noopener">view</a>${up}</div>
      <details class="full"><summary>every number</summary><table class="kv">
        ${row('credit', l.credit)}${row('kind', l.kind)}${row('points', t.points)}
        ${row('z range', `${t.z_start} to ${t.z_end} voxels, ${fmt(mm(s, t.z_start), 2)} to ${fmt(mm(s, t.z_end), 2)} mm`)}
        ${row('coverage', `${fmt(t.coverage * 100, 1)}% of ${s.shape[0]} slices`)}
        ${row('step', `median ${fmt(t.median_step_vox, 0)}, max ${fmt(t.max_step_vox, 0)} voxels (${fmt(mm(s, t.max_step_vox), 1)} mm)`)}
        ${row('mean x, y', `${fmt(t.mean_x, 0)}, ${fmt(t.mean_y, 0)} voxels, ${fmt(t.off_center_mm, 2)} mm off grid center`)}
        ${row('stray', `${fmt(t.stray_mm, 2)} mm`)}${row('tilt', `${fmt(t.tilt_deg, 2)}°`)}${row('wiggle', `${fmt(t.wiggle_mm, 3)} mm RMS`)}
        ${row('path', `${fmt(t.path_mm, 1)} mm, ${fmt(t.path_over_height, 4)} times its height`)}
        ${row('stamped', t.stamped ? `yes: ${l.stamp.voxelsize_um} µm, ${l.stamp.volume_width} x ${l.stamp.volume_height} x ${l.stamp.volume_slices}` : 'no: bare points')}
        ${row('license', lic(l))}
        ${row('sha256', `<button class="lk mono" data-copy="${l.sha256}" data-what="sha256 copied" title="copy">${l.sha256.slice(0, 16)}…</button>`)}
        ${row('file', `<code>${l.file}</code>`)}
        ${l.ends && Object.keys(l.ends).length ? row('CT end check', ['low', 'high'].filter((k) => l.ends[k]).map((k) => `${endHTML(l, k)} ${fmt(l.ends[k].D_mm, 2)} mm from the CT center`).join('<br>')) : ''}
        ${l.note ? row('note', l.note) : ''}
      </table></details></div>`;
  }).join('');
  $('c-pair').innerHTML = pairsOf(s).map((q) => `<div class="ln meta">${S.data.sources[q.a].short} and ${S.data.sources[q.b].short} sit a median <b>${fmt(q.median_mm, 2)} mm</b> apart (min ${fmt(q.min_mm, 2)}, max ${fmt(q.max_mm, 2)}) over the ${fmt(q.overlap_mm, 0)} mm where both exist.</div>`).join('');
  $('c-pyr').innerHTML = `<table class="kv"><tr><th>level</th><td>shape z, y, x</td><td>voxel</td></tr>${s.pyramid.map((p, i) => `<tr><th>${p.path}</th><td>${p.shape.join(' x ')}</td><td>${fmt(s.voxel_um * 2 ** i, i ? 1 : 3)} µm</td></tr>`).join('')}</table>
    <div class="dim">every level ${s.pyramid[0].dtype === '|u1' ? 'uint8' : s.pyramid[0].dtype}, chunks ${s.pyramid[0].chunks.join(' x ')}, ${s.pyramid[0].compressor || 'no compressor'}</div>${streamable(s) ? '' : `<div class="note">This page reads one plane of an uncompressed chunk at a time, so it shows no CT for this scan; its line is drawn in the scan's frame. zarr, VC3D and the neuroglancer link read the compressed chunks.</div>`}`;
  $('c-vol').innerHTML = `CT <a href="${s.zarr}/.zattrs" target="_blank" rel="noopener">${s.volume}</a> · Vesuvius Challenge open data, CC BY-NC 4.0`;
}
function hereRows(s, z) { return s.lines.map((l) => { const p = lineAt(l, z); return p ? { source: l.source, x: p[0], y: p[1], z } : null; }).filter(Boolean); }
function drawHere() {
  const s = S.sel; if (!s || S.z == null) return;
  const z = Math.round(S.z); const rows = hereRows(s, z);
  $('c-here').innerHTML = `<div class="mono small dim">AT z ${z} (${fmt(mm(s, z), 2)} mm), LEVEL-0 VOXELS</div>` + (rows.length
    ? rows.map((r) => `<div class="hr"><span class="${r.source.startsWith('finder') ? 'amber' : 'ice'}">${S.data.sources[r.source].short}</span> <code>${fmt(r.x, 1)}, ${fmt(r.y, 1)}, ${z}</code><button class="lk" data-copy="${fmt(r.x, 1)}, ${fmt(r.y, 1)}, ${z}" data-what="x, y, z copied">copy</button></div>`).join('')
    : '<div class="dim small">no line reaches this height</div>');
}
function setMode(m) {
  if (m === 'lasagna' && !S.las) m = 'scan';
  if ((m === 'scan' || m === 'lasagna') && !S.sel) { select(m === 'lasagna' ? LASAGNA_SCROLL : S.data.scrolls[0].scroll, m); return; }
  if (m === 'lasagna' && S.sel.scroll !== LASAGNA_SCROLL) { select(LASAGNA_SCROLL, 'lasagna'); return; }
  const prev = S.mode; S.mode = m; document.body.classList.toggle('focus', m !== 'array'); placeHud();
  document.querySelectorAll('.chip').forEach((c) => c.classList.toggle('on', c.dataset.mode === m));
  arrayGroup.visible = m === 'array'; scanGroup.visible = m !== 'array';
  $('card').hidden = m === 'array'; showInset();
  $('ctl-array').hidden = m !== 'array'; $('ctl-scan').hidden = m !== 'scan'; $('ctl-las').hidden = m !== 'lasagna';
  $('blend-wrap').hidden = m !== 'lasagna'; $('t-ori').parentElement.hidden = m !== 'lasagna';
  document.querySelectorAll('#rail li').forEach((li) => li.classList.toggle('sel', !!S.sel && li.dataset.scroll === S.sel.scroll && m !== 'array'));
  if (m === 'array') { controls.target.set(0, 90, 0); if (prev !== 'array') { const k = Math.max(1, 1.25 / camera.aspect); camera.position.set(ARRAY_CAM[0] * k, ARRAY_CAM[1] * k, ARRAY_CAM[2] * k); camera.far = 20000; camera.updateProjectionMatrix(); } controls.autoRotate = false; }
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
$('b-connect').addEventListener('click', () => { markSeen(); openGuide('connect'); });
let exQueued = false;
$('ex').addEventListener('input', (e) => { S.ex = +e.target.value; $('ex-v').textContent = S.ex; if (!exQueued) { exQueued = true; requestAnimationFrame(() => { exQueued = false; buildArray(); }); } syncURLSoon(); });
$('t-ct').addEventListener('change', (e) => { S.ct = e.target.checked; applyVolUniforms(); });
$('t-ct2').addEventListener('change', (e) => { S.ct2 = e.target.checked; applyVolUniforms(); });
$('render').addEventListener('change', (e) => { S.render = e.target.value; applyVolUniforms(); });
$('gain').addEventListener('input', (e) => { S.gain = +e.target.value; applyVolUniforms(); });
$('t-sheets').addEventListener('change', (e) => { S.sheets = e.target.checked; applyLasVis(); });
$('t-needle').addEventListener('change', (e) => { S.needles = e.target.checked; applyLasVis(); });
$('t-ori').addEventListener('change', (e) => { S.ori = e.target.checked; drawSlice(); });
$('blend').addEventListener('input', (e) => { S.blend = +e.target.value; clearTimeout(zTimer); zTimer = setTimeout(drawSlice, 120); });
addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.mode !== 'array' && !document.querySelector('dialog[open]')) setMode('array'); });
// neuroglancer link for an OME-Zarr URL, as kit/spaceconnect.py makes them
const ngLink = (url, name) => 'https://neuroglancer-demo.appspot.com/#!' + encodeURIComponent(JSON.stringify({ layers: [{ type: 'image', source: `zarr://${url.replace(/\/+$/, '')}/`, name }], layout: '4panel' }));
// copy buttons anywhere, card actions
document.addEventListener('click', (e) => { const b = e.target.closest('[data-copy]'); if (b) { e.preventDefault(); copy(b.dataset.copy, b.dataset.what); } });
$('c-acts').addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]'); const s = S.sel; if (!b || !s) return;
  const act = b.dataset.act;
  if (act === 'view') copy(location.href, 'view link copied');
  else if (act === 'zarr') copy(s.zarr, 'OME-Zarr URL copied');
  else if (act === 'ng') open(ngLink(s.zarr, `${s.scroll} CT`), '_blank', 'noopener');
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
  $('g-py2').textContent = !streamable(s) ? `# pip install numcodecs
from numcodecs import Blosc

VOL = "${s.zarr}"
L = 3                         # pyramid level: voxels are 2**L times level 0
meta = json.load(urllib.request.urlopen(f"{VOL}/{L}/.zarray"))   # uint8, 128^3 chunks, Blosc: read whole chunks
cz, cy, cx = meta["chunks"]
X, Y = np.interp(Z, z, x), np.interp(Z, z, y)
zl, yl, xl = int(Z) >> L, int(Y) >> L, int(X) >> L
raw = urllib.request.urlopen(f"{VOL}/{L}/{zl // cz}/{yl // cy}/{xl // cx}").read()
chunk = np.frombuffer(Blosc().decode(raw), np.uint8).reshape(cz, cy, cx)
print(chunk[zl % cz, yl % cy, xl % cx])` : `VOL = "${s.zarr}"
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
// while a dialog is open it is the one scrolling panel: the list and the card behind it stop scrolling (style.css body.modal)
function modalState() { document.body.classList.toggle('modal', !!document.querySelector('dialog[open]')); }
document.querySelectorAll('dialog').forEach((d) => d.addEventListener('close', modalState));
function openGuide(tab = 'basics') { snippets(); tabs($('about'), tab); if (!$('about').open) $('about').showModal(); modalState(); }
$('about').querySelector('.tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) { if (b.dataset.tab === 'vc3d') snippets(); tabs($('about'), b.dataset.tab); } });

// data sheet
const COLS = {
  lines: [['scroll', 'scroll'], ['maker', 'maker'], ['grade', 'grade'], ['ct_end_low', 'low end'], ['ct_end_high', 'high end'], ['points', 'pts'], ['z_start', 'z start'], ['z_end', 'z end'], ['height_mm', 'height mm'],
    ['coverage', 'cover'], ['median_step_vox', 'step'], ['max_step_vox', 'max step'], ['off_center_mm', 'off ctr mm'], ['stray_mm', 'stray mm'], ['tilt_deg', 'tilt °'],
    ['wiggle_mm', 'wiggle mm'], ['path_over_height', 'path/ht'], ['stamped', 'stamp'], ['usable_ends', 'usable ends'], ['superseded', 'superseded'], ['license', 'license'], ['sha256', 'sha256']],
  scans: [['scroll', 'scroll'], ['scan', 'scan'], ['voxel_um', 'µm'], ['slices', 'z'], ['height_px', 'y'], ['width_px', 'x'], ['height_mm', 'height mm'], ['width_mm', 'width mm'],
    ['levels', 'levels'], ['grand_prize', 'GP'], ['first_letters', 'FL'], ['lines', 'lines'], ['sources', 'sources'], ['grade', 'grade'], ['pair_median_mm', 'pair gap mm'], ['pair_max_mm', 'pair max mm']],
};
const DEC = { height_mm: 1, coverage: 2, median_step_vox: 0, max_step_vox: 0, off_center_mm: 2, stray_mm: 2, tilt_deg: 2, wiggle_mm: 3, path_over_height: 4, width_mm: 1, voxel_um: 3, pair_median_mm: 2, pair_max_mm: 2 };
const SHEET = { tab: 'lines', key: null, dir: 1 };
function cellHTML(k, v) {
  if (v == null || v === '') return '<span class="dim">·</span>';
  if (k === 'grade') return `<span class="grade ${v}">${v}</span>`;
  if (k === 'ct_end_low' || k === 'ct_end_high') { const m = /^(\w+) (PASS|FLAG)( \(CT recap\))?$/.exec(v); if (m) return `<span class="end"><span class="grade ${m[2]}">${m[2]}</span>${m[3] ? '<span class="rc">CT recap</span>' : ''}</span>`; }
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
    <tbody>${rows.map((r) => `<tr data-scroll="${r.scroll}" class="${r.source?.startsWith('finder') ? 'cf' : ''}${r.withdrawn || r.superseded ? ' wd' : ''}">${cols.map(([k]) => `<td>${cellHTML(k, r[k])}</td>`).join('')}</tr>`).join('')}</tbody>`;
  $('sheet-note').textContent = `${rows.length} ${SHEET.tab}. Click a column to sort, a row to open its scan. Definitions: Guide, For researchers. Downloads hold every column and the full notes.`;
}
function openSheet(tab = 'lines') { SHEET.tab = tab; tabs($('sheet'), tab); renderSheet(); if (!$('sheet').open) $('sheet').showModal(); modalState(); }
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
  $('s-inset').checked = SET.inset; $('s-turn').checked = SET.turn; $('t-turn').checked = SET.turn;
  if (!SET.spin) controls.autoRotate = false;
  showInset(); if (S.sel && S.mode !== 'array') present(true);
  applyVolUniforms(); S.dirty = true; if (save) saveSet();
}
function showInset() { const off = S.mode === 'array'; $('inset').hidden = off || !SET.inset; $('i-show').hidden = off || SET.inset; }
$('b-set').addEventListener('click', (e) => { e.stopPropagation(); $('settings').hidden = !$('settings').hidden; });
document.addEventListener('pointerdown', (e) => { if (!$('settings').hidden && !e.target.closest('#settings, #b-set')) $('settings').hidden = true; });
$('s-glow').addEventListener('input', (e) => { SET.glow = e.target.value / 100; applySettings(); });
$('s-radius').addEventListener('input', (e) => { SET.radius = e.target.value / 100; applySettings(); });
$('s-quality').addEventListener('change', (e) => { SET.quality = e.target.value; applySettings(); });
$('s-film').addEventListener('change', (e) => { SET.film = e.target.checked; applySettings(); });
$('s-spin').addEventListener('change', (e) => { SET.spin = e.target.checked; applySettings(); });
$('s-inset').addEventListener('change', (e) => { SET.inset = e.target.checked; applySettings(); });
$('s-turn').addEventListener('change', (e) => { SET.turn = e.target.checked; applySettings(); });
$('t-turn').addEventListener('change', (e) => { SET.turn = e.target.checked; applySettings(); });
$('i-hide').addEventListener('click', () => { SET.inset = false; applySettings(); });
$('i-show').addEventListener('click', () => { SET.inset = true; applySettings(); });
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
    tip.innerHTML = `<b>${name}</b><br>${s.lines.map((l) => S.data.sources[l.source].label).join(', ')}${g ? `<br>end check ${(() => { const f = s.lines.find(isFinder); return f && f.ends && Object.keys(f.ends).length ? endsHTML(f) : `<span class="grade ${g}">${g}</span>`; })()}` : ''}<br><span class="dim">click to open in X-ray</span>`;
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
let urlT = 0;
function syncURLSoon() { clearTimeout(urlT); urlT = setTimeout(syncURL, 300); }
function syncURL() {
  const q = new URLSearchParams();
  if (S.mode !== 'array') { q.set('mode', S.mode); q.set('scan', S.sel.scroll); q.set('z', Math.round(S.z)); }
  if (S.ex !== 3) q.set('ex', S.ex);
  const off = [...OFF.src, ...OFF.line]; if (off.length) q.set('off', off.join(','));
  history.replaceState(null, '', q.toString() ? `?${q}` : location.pathname);
}
window.umbilici = {
  version: () => VERSION,
  show: (kind, name, on) => showLines(kind, name, on),
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
// Frames are capped at 60 a second, and at 30 while the array only spins by itself: a 120 Hz screen (MacBook Pro)
// otherwise draws the full X-ray and glow twice as often for no visible gain. The spin is timed, not per frame.
const frames = []; let lastFrame = 0, lastTick = 0, stepPending = false;
function tick(now = performance.now()) {
  requestAnimationFrame(tick);
  const idleSpin = controls.autoRotate && !S.dirty && !moving;
  const gap = idleSpin ? 1000 / 30 : 1000 / 60;
  if (now - lastTick < gap - 2) return;
  const dt = lastTick ? Math.min(0.1, (now - lastTick) / 1000) : 1 / 60; lastTick = now;
  controls.update(dt);
  if (S.mode === 'array') applyHot();
  else if (SET.turn && S.sel && !$('inset').hidden && shownAngle !== null && Math.abs(controls.getAzimuthalAngle() - shownAngle) > 0.003) present(true);
  if (S.dirty || controls.autoRotate) {
    composer.render(); placeLabels(); S.dirty = false;
    // slow means frames arriving well after the cap allows, not the cap itself
    if (now - lastFrame < 250) frames.push(now - lastFrame - gap);
    lastFrame = now;
    if (frames.length >= 24) {
      const m = median(frames); frames.length = 0;
      if (SET.quality === 'auto' && m > 9 && autoLevel < 2) stepPending = true;
    }
    if (stepPending && !moving) { stepPending = false; const s = autoSteps(); let k = autoLevel + 1; while (k < 2 && s[k] >= s[autoLevel]) k++; if (s[k] < s[autoLevel]) { autoLevel = k; applySettings(false); } }
  }
}

// ---------- live lines ----------
// The page reads the dataset's newest revision when it opens, so a new release of SharpMeow/vesuvius-center-lines
// shows here without a redeploy. data/lines.json, built at deploy, is the fallback and supplies what a line file
// does not change: the points and frame stamp of a file it already holds (dataset files never change in place; a
// new version is a new file) and each scan's pyramid. A file or scan it lacks is read from the dataset and the bucket.
const LINE_KEYS = ['source', 'kind', 'credit', 'licence', 'upstream', 'file', 'sha256', 'z', 'note'];
const STAMP_KEYS = ['voxelsize_um', 'volume', 'volume_width', 'volume_height', 'volume_slices'];
async function liveData(bundle) {
  try {
    const api = await fetch(`${DATASET.replace('/datasets/', '/api/datasets/')}`, { credentials: 'omit' }).then((r) => (r.ok ? r.json() : null));
    const rev = api?.sha || 'main', at = (f) => `${DATASET}/resolve/${rev}/${f}`;
    const ix = await getJSON(at('index.json'));
    const held = new Map(bundle.scrolls.flatMap((s) => s.lines.map((l) => [`${l.file}:${l.sha256}`, l])));
    const scanOf = new Map(bundle.scrolls.map((s) => [s.scroll, s]));
    const sources = { ...bundle.sources };
    for (const f of ix.files) sources[f.source] ||= { label: f.credit, short: f.source.slice(0, 2).toUpperCase() };
    const order = Object.keys(sources);
    const scrolls = await Promise.all(Object.entries(ix.scrolls)
      .sort(([a, x], [b, y]) => (!(x.first_letters || x.grand_prize)) - (!(y.first_letters || y.grand_prize)) || (a < b ? -1 : a > b ? 1 : 0))
      .map(async ([name, sc]) => {
        const rows = ix.files.filter((f) => f.scroll === name);
        const vol = rows.find((f) => f.scan === sc.scan && f.volume)?.volume;
        let s = scanOf.get(name);
        if (!s || s.scan !== sc.scan || s.volume !== vol) s = await newScan(name, sc, vol);
        const lines = await Promise.all(rows.map((f) => liveLine(f, held.get(`${f.file}:${f.sha256}`), at)));
        lines.sort((a, b) => order.indexOf(a.source) - order.indexOf(b.source));
        return { ...s, first_letters: sc.first_letters, grand_prize: sc.grand_prize, lines };
      }));
    return { ...bundle, made: ix.made, frame: ix.frame, sources, scrolls, revision: rev, live: true };
  } catch (e) {
    console.warn('center lines: using the copy built with this page', e);
    return { ...bundle, live: false };
  }
}
async function newScan(name, sc, vol) {
  const zarr = `https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com/${name}/volumes/${vol}`;
  const levels = (await getJSON(`${zarr}/.zattrs`)).multiscales[0].datasets.map((d) => d.path);
  const pyramid = await Promise.all(levels.map(async (path) => {
    const za = await getJSON(`${zarr}/${path}/.zarray`);
    return { path, shape: za.shape, chunks: za.chunks, dtype: za.dtype, compressor: za.compressor ? za.compressor.id : null };
  }));
  return { scroll: name, scan: sc.scan, volume: vol, zarr, voxel_um: parseFloat(vol.match(/-([0-9.]+)um-/)[1]),
    shape: pyramid[0].shape, levels: levels.length, pyramid };
}
// one line as data/lines.json holds it (tools/build_lines.py makes the same fields)
async function liveLine(f, had, at) {
  const ends = {};
  for (const [k, e] of Object.entries(f.ct_ends || {})) { ends[k] = {}; for (const q of ['grade', 'recapped', 'D_mm']) if (q in e) ends[k][q] = e[q]; }
  let grade = null;
  if (Object.keys(ends).length) grade = Object.values(ends).some((e) => e.grade !== 'PASS') ? 'FLAG' : 'PASS';
  else { const m = (f.note || '').match(/end check (PASS|FLAG|VOID)/); if (m) grade = m[1]; }
  let points = had?.points, stamp = had?.stamp, usable = had ? had.usable : null;
  if (!had) {
    const doc = await getJSON(at(f.file)), md = doc.metadata || {};
    points = [...doc.control_points].sort((a, b) => a.z - b.z).flatMap((p) => [Math.round(p.x), Math.round(p.y), Math.round(p.z)]);
    stamp = Object.fromEntries(STAMP_KEYS.filter((k) => k in md).map((k) => [k, md[k]]));
    const use = md.usable_ends;
    usable = use && typeof use === 'object' ? ['low', 'high'].filter((k) => use[k]) : null;
  }
  const l = Object.fromEntries(LINE_KEYS.map((k) => [k, f[k] ?? (k === 'note' ? '' : f[k])]));
  return { ...l, grade, ends, untested: !!f.ct_untested_scan, usable, stamp, points, superseded_by: f.superseded_by ?? null };
}

// ---------- boot ----------
(async () => {
  S.data = await liveData(await getJSON('data/lines.json'));
  for (const k of Object.keys(S.data.sources)) SRC_HEX[k] ||= SRC_OTHER;
  try { S.las = await getJSON('data/lasagna/meta.json'); } catch { S.las = null; document.querySelector('.chip.las').disabled = true; }
  const nPrize = S.data.scrolls.filter(onPrize).length, nOther = S.data.scrolls.length - nPrize;
  $('k-count').textContent = nPrize; $('k-other').innerHTML = nOther ? `<span class="sep">/</span>${nOther} OTHER PUBLIC SCANS` : '';
  $('h-count').textContent = numberWords(S.data.scrolls.length);
  $('a-sources').innerHTML = Object.entries(S.data.sources).map(([k, v]) => {
    const l = S.data.scrolls.flatMap((s) => s.lines).find((q) => q.source === k); const n = S.data.scrolls.filter((s) => s.lines.some((q) => q.source === k)).length;
    const names = S.data.scrolls.filter((s) => s.lines.some((q) => q.source === k)).map((s) => s.scroll).join(', ');
    return `<li><b class="${k.startsWith('finder') ? 'amber' : 'ice'}">${v.label}</b> (${v.short}): ${n} scan${n === 1 ? '' : 's'}, ${l ? lic(l) : ''}. <span class="dim">Credit as given: ${l ? l.credit : ''}. ${names}.</span></li>`;
  }).join('');
  const all = S.data.scrolls.flatMap((s) => s.lines.map((l) => [s, l]));
  const bare = all.filter(([s, l]) => !statsOf(s, l).stamped);
  $('g-nscan').textContent = S.data.scrolls.length; $('g-nline').textContent = all.length; $('g-nsrc').textContent = Object.keys(S.data.sources).length;
  $('g-stamped').textContent = all.length - bare.length;
  const bareBy = {}; for (const [, l] of bare) bareBy[S.data.sources[l.source].label] = (bareBy[S.data.sources[l.source].label] || 0) + 1;
  $('g-unstamped').textContent = bare.length ? `the ${bare.length} without it (${Object.entries(bareBy).map(([k, n]) => `${k}: ${n}`).join('; ')})` : 'none';
  $('g-made').textContent = S.data.made + (S.data.live ? `, read live at revision ${S.data.revision.slice(0, 8)}` : ', the copy built with this page'); $('g-frame').textContent = S.data.frame;
  $('g-nlev').textContent = S.data.scrolls.reduce((n, s) => n + s.pyramid.length, 0);
  $('g-las').textContent = S.las ? `cos at ${S.las.slice_z.length} heights (z ${S.las.slice_z.join(', ')}) as ${S.las.slice_px} px WebP; an orientation picture per height at ${S.las.ori_px} px (hue from the doubled in-plane angle, so a normal and its opposite match); ${S.las.needles.count.toLocaleString('en-US')} normals on a ${S.las.needles.grid_voxels.join(' x ')} voxel grid where cos > 40 and grad_mag > 20, with nz rebuilt as the square root of 1 - nx² - ny². Frame: ${S.las.frame}.` : 'not loaded.';
  // the lasagna dataset may still be on its way to the Hub: say so instead of linking a 404
  fetch('https://huggingface.co/api/datasets/SharpMeow/pherc0175a-lasagna', { credentials: 'omit' }).then((r) => {
    if (r.ok) return;
    document.querySelectorAll('a[href*="pherc0175a-lasagna"]').forEach((a) => { a.removeAttribute('href'); a.classList.add('soon'); a.title = 'being published to the Hub; check back soon'; a.textContent += ' (soon)'; });
  }).catch(() => {});
  const q = new URLSearchParams(location.search);
  if (q.get('ex')) { S.ex = Math.max(1, Math.min(30, +q.get('ex'))); $('ex').value = S.ex; $('ex-v').textContent = S.ex; }
  for (const k of (q.get('off') || '').split(',').filter(Boolean)) (k.includes(':') ? OFF.line : OFF.src).add(k);
  buildLegend();
  applySettings(false); buildRail(); buildPick(); buildArray();
  $('boot').remove();
  tick();
  if (q.get('scan')) { const m = q.get('mode') || 'scan'; select(q.get('scan'), m); if (q.get('z')) setZ(+q.get('z'), true); }
  else { setMode('array'); controls.autoRotate = SET.spin && !matchMedia('(prefers-reduced-motion: reduce)').matches; }
  if (q.get('guide')) openGuide(q.get('guide'));
  else if (q.get('data')) openSheet(q.get('data') === 'scans' ? 'scans' : 'lines');
  else if (!seen() && !navigator.webdriver) $('hint').hidden = false;
})().catch((e) => { $('boot').textContent = `could not load: ${e.message}`; console.error(e); });
