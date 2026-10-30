/* Vesuvius Radar page: asks the API for one window and view, draws the charts, lists the items, follows the
   collector, and keeps the viewer's own stars, hides and last visit in this browser. No libraries. */
(function () {
  "use strict";

  const SRC = ["arxiv", "github", "hf", "pypi", "zenodo", "journals", "blog"];
  const SRC_LABEL = { arxiv: "arXiv", github: "GitHub", hf: "Hugging Face", pypi: "PyPI", zenodo: "Zenodo", journals: "Journals", blog: "News and blogs" };
  const SHORT = { arxiv: "arXiv", github: "GitHub", hf: "HF", pypi: "PyPI", zenodo: "Zenodo", journals: "Journals", blog: "News" };
  const BANDS = ["high", "medium", "low"];
  const BAND_LABEL = { high: "High", medium: "Medium", low: "Low" };
  // An issue's or pull request's author is who opened it; a later comment or review has its own author.
  const OPENED = { issue: "opened by", pr: "opened by", thread: "started by" };
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 2) + "..." : s);
  // who with its first name replaced by the person's name (who_name), co-authors and other posters kept
  const byline = (i) => (i.who_name ? [i.who_name].concat(i.who.split(",").slice(1).map((s) => s.trim())).join(", ") : i.who);
  const KIND = { paper: "paper", repo: "repository", pr: "pull request", issue: "issue", release: "release", model: "model",
    dataset: "dataset", space: "Space", "daily-paper": "daily paper", package: "package version", post: "blog post", news: "news story" };
  const LOOKBACKS = [["1m", "1 min"], ["5m", "5 min"], ["15m", "15 min"], ["30m", "30 min"], ["1h", "1 hour"], ["3h", "3 hours"],
    ["6h", "6 hours"], ["12h", "12 hours"], ["1d", "1 day"], ["2d", "2 days"], ["3d", "3 days"], ["7d", "7 days"], ["14d", "14 days"], ["30d", "30 days"]];
  const VIEW_ICON = {
    all: '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="10" cy="10" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
    research: '<svg viewBox="0 0 20 20"><path d="M5 3.5h7l3 3v10H5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M7.5 9.5h5M7.5 12.5h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    team: '<svg viewBox="0 0 20 20"><circle cx="7" cy="7.5" r="2.6" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="13.5" cy="8.5" r="2.1" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M2.8 16c.6-2.6 2.2-3.8 4.2-3.8s3.6 1.2 4.2 3.8M11.6 12.6c1.9-.4 3.9.5 4.6 3.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    builders: '<svg viewBox="0 0 20 20"><path d="m7 6-4 4 4 4M13 6l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };
  const VIEW_SHORT = { all: "Everything, from every source", research: "Papers and methods", team: "Community activity about the scrolls", builders: "Tools, models, data, releases" };
  const PER = [10, 20, 50, 100];  // items per page: the list is paged, so the page never grows without end
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safe = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "#");
  const fmtN = (n) => (n == null ? "" : Number(n).toLocaleString("en-US"));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("vradar." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("vradar." + k, JSON.stringify(v)); } catch (e) { /* private window */ } },
  };

  /* ------------------------------------------------------------ state */
  const defaults = () => ({ view: "all", since: "1d", by: "date", q: "", meaning: false, sort: "date", min: 20, sources: [], bands: [], topics: [],
    code: false, starred: false, showHidden: false, newOnly: false });
  // Saved filters from before version 2 kept "Most relevant" as the sort; the default is now Newest, so drop the old sort.
  const saved = store.get("filters", {});
  if (saved.v !== 2) delete saved.sort;
  delete saved.v;
  const perSaved = +store.get("per", 10);
  const S = Object.assign({ f: Object.assign(defaults(), saved), per: PER.includes(perSaved) ? perSaved : 10, page: 0, items: [], matched: 0,
    stars: new Set(store.get("stars", [])), hide: new Set(store.get("hidden", [])), ov: null, base: null, counts: null, cfg: null,
    open: new Set(), like: new Set() });
  // The last visit: items first seen after it get a "new" mark. Updated a little after the page opens.
  S.lastVisit = store.get("lastVisit", null);
  setTimeout(() => store.set("lastVisit", new Date().toISOString().slice(0, 19) + "Z"), 15000);
  readUrl();

  function readUrl() {
    const p = new URLSearchParams(location.search);
    // Hugging Face opens the Space with parameters of its own (__theme, and __sign on a private Space). Only a link that
    // names a filter replaces the saved filters, and a link without "min" keeps the saved minimum score.
    if (!["view", "since", "by", "q", "meaning", "sort", "min", "sources", "bands", "topics", "code", "per"].some((k) => p.has(k))) return;
    const f = Object.assign(defaults(), { min: S.f.min });
    if (p.get("view")) f.view = p.get("view");
    if (p.get("since")) f.since = p.get("since");
    if (p.get("by")) f.by = p.get("by");
    if (p.get("q")) f.q = p.get("q");
    if (p.get("meaning") === "1") f.meaning = true;
    if (p.get("sort")) f.sort = p.get("sort");
    if (p.get("min")) f.min = Math.max(0, Math.min(90, +p.get("min") || 0));
    ["sources", "bands", "topics"].forEach((k) => { if (p.get(k)) f[k] = p.get(k).split(",").filter(Boolean); });
    if (p.get("code") === "1") f.code = true;
    if (PER.includes(+p.get("per"))) S.per = +p.get("per");
    S.f = f;
  }
  function viewParams(extra) {
    const f = S.f, p = new URLSearchParams();
    p.set("since", f.since); p.set("view", f.view);
    if (f.by !== "date") p.set("by", f.by);
    if (f.q.trim()) { p.set("q", f.q.trim()); if (f.meaning) p.set("by_meaning", "true"); }
    if (f.min) p.set("min_score", f.min);
    if (f.sources.length) p.set("sources", f.sources.join(","));
    if (f.bands.length) p.set("bands", f.bands.join(","));
    if (f.topics.length) p.set("topics", f.topics.join(","));
    if (f.code) p.set("has_code", "true");
    if (f.starred) p.set("ids", Array.from(S.stars).join(",") || "none");
    for (const k in extra || {}) { if (extra[k] == null) p.delete(k); else p.set(k, extra[k]); }
    return p;
  }
  function pageUrl() {
    const f = S.f, p = new URLSearchParams();
    const d = defaults();
    ["view", "since", "by", "q", "sort"].forEach((k) => { if (f[k] && f[k] !== d[k]) p.set(k, f[k]); });
    if (f.meaning) p.set("meaning", "1");
    p.set("min", f.min);  // always, so a shared link shows its own minimum rather than the reader's saved one
    ["sources", "bands", "topics"].forEach((k) => { if (f[k].length) p.set(k, f[k].join(",")); });
    if (f.code) p.set("code", "1");
    if (S.per !== 10) p.set("per", S.per);
    const qs = p.toString();
    return location.origin + location.pathname + (qs ? "?" + qs : "");
  }

  /* ------------------------------------------------------------ time */
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const D = (iso) => new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  const hm = (d) => pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes());
  const dm = (d) => d.getUTCDate() + " " + MON[d.getUTCMonth()];
  const stamp = (iso) => { const d = D(iso); return dm(d) + " " + hm(d) + " UTC"; };
  function ago(iso) {
    const s = (Date.now() - D(iso).getTime()) / 1000;
    if (s < 0) return "in " + until(iso);
    if (s < 50) return "just now";
    if (s < 3600) return Math.max(1, Math.round(s / 60)) + " min ago";
    if (s < 86400 * 1.5) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " days ago";
  }
  function until(iso) {
    const s = (D(iso).getTime() - Date.now()) / 1000;
    if (s < 60) return "under a minute";
    if (s < 3600) return Math.round(s / 60) + " min";
    return Math.round(s / 3600) + " h";
  }
  const lbLabel = (v) => (LOOKBACKS.find((x) => x[0] === v) || [v, v])[1];

  /* ------------------------------------------------------------ svg helpers */
  const NS = "http://www.w3.org/2000/svg";
  function el(tag, attrs, text) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    return e;
  }
  // A bar with only its data end rounded, anchored square on the baseline.
  function barPath(x, y, w, h, r, horizontal) {
    if (w <= 0 || h <= 0) return "";
    r = Math.max(0, Math.min(r, horizontal ? h / 2 : w / 2, horizontal ? w : h));
    if (horizontal) return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  const niceMax = (v) => { if (v <= 4) return 4; const p = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p; return 10 * p; };
  function ticks(max, n) { const step = niceMax(max / n); const out = []; for (let v = 0; v <= max + 1e-9; v += step) out.push(v); return out; }
  const width = (host, min, max) => Math.max(min, Math.min(max, Math.round(host.clientWidth || max)));

  /* ------------------------------------------------------------ tooltip */
  const tip = $("#tip");
  function showTip(html, x, y) {
    tip.innerHTML = html; tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > innerHeight - 8) top = y - r.height - 14;
    tip.style.left = Math.max(8, left) + "px"; tip.style.top = Math.max(8, top) + "px";
  }
  document.addEventListener("pointermove", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (t) showTip(t.getAttribute("data-tip"), e.clientX, e.clientY); else tip.hidden = true;
  });
  document.addEventListener("scroll", () => { tip.hidden = true; }, true);
  const row = (color, label, val) => `<div class="r"><span>${color ? `<i style="background:${color}"></i>` : ""}${esc(label)}</span><b>${esc(val)}</b></div>`;
  const hint = (t) => `<div class="r"><span>${esc(t)}</span></div>`;

  /* ------------------------------------------------------------ data */
  async function getJSON(url, opt) {
    const r = await fetch(url, Object.assign({ cache: "no-store" }, opt || {}));
    const body = await r.json().catch(() => ({}));
    if (!r.ok && r.status !== 409 && r.status !== 429) throw new Error(body.detail || ("HTTP " + r.status));
    return { status: r.status, body };
  }
  let seq = 0;
  async function load() {
    const my = ++seq;
    store.set("filters", Object.assign({}, S.f, { starred: false, showHidden: false, newOnly: false, v: 2 }));
    store.set("per", S.per);
    try { history.replaceState(null, "", pageUrl().replace(location.origin, "") + location.hash); } catch (e) { /* sandboxed */ }
    const base = viewParams({ sources: null, bands: null, topics: null });
    const sort = S.f.meaning && S.f.q.trim() ? "score" : S.f.sort;
    const [ov, bs, items, counts] = await Promise.all([
      getJSON("api/overview?" + viewParams()), getJSON("api/overview?" + base),
      getJSON("api/items?" + viewParams({ sort, limit: S.per, offset: 0 })),
      getJSON("api/counts?" + viewParams({ since: "30d", by_meaning: null })),
    ]);
    if (my !== seq) return;
    S.ov = ov.body; S.base = bs.body; S.counts = counts.body.lookbacks; S.matched = items.body.matched;
    S.items = items.body.items; S.page = 0; S.byMeaning = items.body.by_meaning;
    renderAll();
    if (!$("[data-panel=briefing]").hidden) loadBriefing();
    renderLinks();
  }
  async function goPage(n) {
    const pages = Math.max(1, Math.ceil(S.matched / S.per));
    n = Math.max(0, Math.min(pages - 1, n));
    const sort = S.f.meaning && S.f.q.trim() ? "score" : S.f.sort;
    const { body } = await getJSON("api/items?" + viewParams({ sort, limit: S.per, offset: n * S.per }));
    S.items = body.items; S.page = n; S.matched = body.matched; renderList();
    const top = $("#listTop");
    if (top.getBoundingClientRect().top < 0) top.scrollIntoView({ block: "start" });
  }
  function pagerHTML() {
    const pages = Math.ceil(S.matched / S.per), p = S.page;
    if (pages <= 1) return "";
    const nums = [...new Set([0, p - 2, p - 1, p, p + 1, p + 2, pages - 1].filter((k) => k >= 0 && k < pages))].sort((a, b) => a - b);
    let out = "", prev = -1;
    nums.forEach((k) => {
      if (k > prev + 1) out += '<span class="gap" aria-hidden="true">...</span>';
      out += `<button type="button" data-page="${k}" ${k === p ? 'aria-current="page"' : ""} aria-label="Page ${k + 1}">${k + 1}</button>`;
      prev = k;
    });
    const from = p * S.per + 1, to = Math.min(S.matched, (p + 1) * S.per);
    return `<span class="pinfo">${fmtN(from)} to ${fmtN(to)} of ${fmtN(S.matched)}</span>
      <button type="button" data-page="${p - 1}" ${p === 0 ? "disabled" : ""} aria-label="Previous page">Previous</button>${out}
      <button type="button" data-page="${p + 1}" ${p >= pages - 1 ? "disabled" : ""} aria-label="Next page">Next</button>`;
  }
  let loadTimer;
  const reload = (ms) => { clearTimeout(loadTimer); loadTimer = setTimeout(() => load().catch(fail), ms || 0); };
  function fail(e) { notice("Could not load the radar: " + esc(e.message) + ". It may be waking up; try again in a minute.", "bad"); }

  /* ------------------------------------------------------------ controls */
  function renderViews() {
    const V = S.views || {};
    $("#views").innerHTML = ["all", "research", "team", "builders"].map((k) => `<button type="button" class="vbtn" role="radio" aria-checked="${S.f.view === k}" data-view="${k}">
        <b>${VIEW_ICON[k]}${esc((V[k] && V[k].label) || k)}</b><span>${esc(VIEW_SHORT[k])}</span></button>`).join("");
    $("#viewAbout").textContent = (V[S.f.view] && V[S.f.view].about) || "";
  }
  $("#views").addEventListener("click", (e) => { const b = e.target.closest("[data-view]"); if (!b) return; S.f.view = b.dataset.view; renderViews(); reload(); });
  function renderLookback() {
    const opts = LOOKBACKS.some(([v]) => v === S.f.since) ? LOOKBACKS : LOOKBACKS.concat([[S.f.since, S.f.since]]);
    const n = (v) => (S.counts && S.counts[v] != null ? ` (${fmtN(S.counts[v])} ${S.counts[v] === 1 ? "item" : "items"})` : "");
    $("#lookback").innerHTML = opts.map(([v, l]) => `<option value="${esc(v)}" ${S.f.since === v ? "selected" : ""}>Past ${esc(l)}${n(v)}</option>`).join("");
    $$("#byPick button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.by === S.f.by)));
  }
  $("#lookback").addEventListener("change", (e) => { S.f.since = e.target.value; renderLookback(); reload(); });
  $("#byPick").addEventListener("click", (e) => { const b = e.target.closest("[data-by]"); if (!b) return; S.f.by = b.dataset.by; renderLookback(); reload(); });

  /* ------------------------------------------------------------ collector */
  const notice = (msg, kind) => { const n = $("#notice"); n.className = "notice" + (kind ? " " + kind : ""); n.innerHTML = msg; n.hidden = !msg; };
  let colTimer, wasRunning = false, lastSaved = null;
  async function pollSources() {
    clearTimeout(colTimer);
    let running = false;
    try {
      const { body } = await getJSON("api/sources");
      S.src = body;
      running = !!body.check_requested || Object.values(body.sources).some((s) => s.state === "running");
      renderCollector(body, running);
      if (!HERO.done) { HERO.done = true; heroStats(); }
      if (!$("[data-panel=sources]").hidden) renderSources();
      if (body.store.saved && lastSaved && body.store.saved !== lastSaved && !running) reload(300);
      lastSaved = body.store.saved;
      if (wasRunning && !running) {
        const n = Object.values(body.sources).reduce((a, s) => a + (s.new || 0), 0);
        notice(`Check finished: <b>${fmtN(n)}</b> items new to the radar. Showing the updated window.`, "");
        reload(); heroStats();
      }
      wasRunning = running;
    } catch (e) { $("#colText").textContent = "The Space is waking up or busy; retrying..."; }
    colTimer = setTimeout(pollSources, running ? 2000 : 20000);
  }
  function renderCollector(b, running) {
    const src = b.sources, list = Object.values(src);
    const done = list.filter((s) => s.last_check);
    const newest = done.map((s) => s.last_check).sort().pop();
    const next = list.map((s) => s.next_check).sort()[0];
    const bad = list.filter((s) => s.state === "error" || s.state === "partial");
    const p = $("#pulse");
    p.className = "pulse" + (running ? " busy" : bad.length ? " warn" : "");
    $("#colText").innerHTML = running
      ? `<b>Checking sources now.</b> ${list.filter((s) => s.state !== "running").length} of ${list.length} done.`
      : (newest ? `Collecting around the clock. Last check <b>${esc(ago(newest))}</b>; next in <b>${esc(until(next))}</b>. ` : "Waiting for the first check. ") +
        `${list.length - bad.length} of ${list.length} sources healthy · ${fmtN(b.store.items)} items from the last 30 days`;
    const btn = $("#checkBtn");
    btn.disabled = running; btn.classList.toggle("busy", running);
    btn.querySelector("span").textContent = running ? "Checking..." : "Check now";
    document.body.classList.toggle("scanning", running);
    $("#progress").hidden = !running;
    if (running) {
      $("#progRows").innerHTML = SRC.filter((k) => src[k]).map((k) => {
        const v = src[k], fresh = b.check_requested && v.last_check && v.last_check >= b.check_requested;
        const st = v.state === "running" ? "running" : fresh ? v.state : "queued";
        const icon = st === "running" ? '<span class="spinner"></span>' : st === "queued" ? "○"
          : st === "ok" ? '<span style="color:var(--good-ink)">✓</span>' : st === "partial" ? '<span style="color:var(--warn-ink)">!</span>' : '<span style="color:var(--bad-ink)">✕</span>';
        return `<div class="prow"><span class="st">${icon}</span><span class="nm"><i class="dot s-${k}"></i>${esc(v.label)}</span><span class="num">${fresh ? fmtN(v.new) + " new" : ""}</span><span class="step">${esc(v.step || (fresh ? (v.notes[0] || v.state) : st))}</span></div>`;
      }).join("");
    }
    $("#build").textContent = `Store: ${fmtN(b.store.items)} items, saved ${b.store.saved ? ago(b.store.saved) : "not yet"} · model ${b.semantic.model} ${b.semantic.ready ? "ready" : "not loaded"} · up since ${stamp(b.store.booted)}`;
  }
  $("#checkBtn").addEventListener("click", async () => {
    notice("");
    try {
      const { status, body } = await getJSON("api/check", { method: "POST" });
      if (status === 429) { notice(esc(body.reason) + ". The collector also runs on its own schedule (Sources tab).", "warn"); return; }
      if (status === 409) notice("A check is already running; following it.");
      wasRunning = true; pollSources();
    } catch (err) { notice("Could not start a check: " + esc(err.message), "bad"); }
  });

  /* ------------------------------------------------------------ KPIs */
  function renderKpis() {
    const o = S.ov, items = o.items;
    const spark = SRC.filter((k) => o.by_source[k]).map((k) => `<i style="flex:${o.by_source[k]};background:var(--s-${k})" data-tip="${esc(row(`var(--s-${k})`, SRC_LABEL[k], fmtN(o.by_source[k])))}"></i>`).join("");
    const bspark = BANDS.filter((b) => o.by_band[b]).map((b) => `<i style="flex:${o.by_band[b]};background:var(--b-${b})" data-tip="${esc(row(`var(--b-${b})`, BAND_LABEL[b], fmtN(o.by_band[b])))}"></i>`).join("");
    const nNew = S.lastVisit ? S.items.filter((i) => (i.first_seen || "") > S.lastVisit).length : null;
    const win = `in the last ${lbLabel(S.f.since)}`;
    $("#kpis").innerHTML = [
      `<div class="card kpi"><span class="l">Items</span><span class="v">${fmtN(items)}</span><span class="d">${esc(win)}</span><div class="spark">${spark}</div></div>`,
      `<div class="card kpi"><span class="l">High relevance</span><span class="v">${fmtN(o.high)}</span><span class="d">score 60 or more; ${fmtN(o.medium)} medium</span><div class="spark">${bspark}</div></div>`,
      `<div class="card kpi"><span class="l">With code or data</span><span class="v">${fmtN(o.with_code + o.new_repos)}</span><span class="d">${fmtN(o.with_code)} link code, ${fmtN(o.new_repos)} new repositories</span></div>`,
      o.learned && o.learned.ready
        ? `<div class="card kpi"><span class="l">Learned scores</span><span class="v">${fmtN(o.learned.items)}</span><span class="d">scored by a model fitted to blind ratings of ${fmtN(o.learned.trained_on)} items</span></div>`
        : `<div class="card kpi"><span class="l">Found by meaning</span><span class="v">${o.semantic.ready ? fmtN(o.lifted_by_meaning) : "off"}</span><span class="d">${o.semantic.ready ? "scored higher by the model than by keywords" : "the model is loading"}</span></div>`,
      `<div class="card kpi"><span class="l">New since your visit</span><span class="v">${nNew == null ? "first" : fmtN(nNew)}</span><span class="d">${S.lastVisit ? "among the top items, since " + esc(stamp(S.lastVisit)) : "visit; marks start next time"}</span></div>`,
    ].join("");
  }

  /* ------------------------------------------------------------ charts */
  function binLabel(iso, step) {
    const d = D(iso);
    if (step < 3600) return hm(d);
    if (step < 86400) return d.getUTCHours() === 0 || step >= 6 * 3600 ? dm(d) + " " + hm(d) : hm(d);
    return dm(d);
  }
  function chartTime() {
    const host = $("#chTime"); host.innerHTML = "";
    const tl = S.ov.timeline, bins = tl.bins, step = tl.bin_seconds;
    const unit = step < 3600 ? (step / 60) + "-minute" : step < 86400 ? (step / 3600) + "-hour" : "day";
    $("#tlCaption").textContent = `Items per ${unit} bin (UTC), by ${S.f.by === "found" ? "when the radar found them" : "publish or update time"}, stacked by source.`;
    const W = width(host, 320, 1140), H = W < 600 ? 210 : 230, L = 38, R = 10, T = 16, B = 28;
    const tot = (b) => SRC.reduce((a, k) => a + (b.n[k] || 0), 0);
    const max = niceMax(Math.max(1, ...bins.map(tot)));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Items per time bin, stacked by source" });
    const y = (v) => T + (H - T - B) * (1 - v / max);
    ticks(max, 4).forEach((v) => { svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: v === 0 ? "base" : "gl" })); svg.appendChild(el("text", { x: L - 7, y: y(v) + 3.5, "text-anchor": "end", class: "tick" }, fmtN(v))); });
    const bw = (W - L - R) / bins.length, w = Math.max(1.5, Math.min(40, bw * 0.7));
    const every = Math.ceil(bins.length / Math.max(3, Math.floor((W - L) / 84)));
    bins.forEach((b, n) => {
      const cx = L + bw * n + bw / 2, t = tot(b);
      const present = SRC.filter((k) => b.n[k]);
      let acc = 0;
      present.forEach((k, j) => {
        const y0 = y(acc), y1 = y(acc + b.n[k]); acc += b.n[k];
        const top = j === present.length - 1, gap = top || w < 4 ? 0 : 1.5;
        const h = Math.max(0, y0 - y1 - gap);
        svg.appendChild(el("path", { d: top ? barPath(cx - w / 2, y1, w, h, Math.min(3, w / 2)) : `M${cx - w / 2},${y1 + gap}h${w}v${h}h${-w}Z`, style: `fill:var(--s-${k})`, class: "mark" }));
      });
      if (t && bins.length <= 40) svg.appendChild(el("text", { x: cx, y: y(t) - 5, "text-anchor": "middle", class: "tick", style: "fill:var(--fg2)" }, fmtN(t)));
      if (n % every === 0) svg.appendChild(el("text", { x: cx, y: H - 9, "text-anchor": "middle", class: "tick" }, binLabel(b.t, step)));
      const end = new Date(D(b.t).getTime() + step * 1000).toISOString();
      svg.appendChild(el("rect", { x: L + bw * n, y: T, width: bw, height: H - T - B, class: "hit", "data-tip": `<b>${esc(stamp(b.t))} to ${esc(hm(D(end)))}</b>` + (t ? SRC.filter((k) => b.n[k]).map((k) => row(`var(--s-${k})`, SRC_LABEL[k], b.n[k])).join("") : hint("Nothing in this bin")) + (t ? row("", "Total", t) : "") }));
    });
    if (!S.ov.items) svg.appendChild(el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, "Nothing in this window yet"));
    host.appendChild(svg);
    $("#legTime").innerHTML = SRC.filter((k) => S.ov.by_source[k]).map((k) => `<span><i style="background:var(--s-${k})"></i>${SRC_LABEL[k]}</span>`).join("");
  }

  function chartTopics() {
    const host = $("#chTopics"); host.innerHTML = "";
    const rows = Object.entries(S.ov.by_topic).slice(0, 10);
    const W = width(host, 300, 520), rowH = 30, L = 156, R = 40, H = Math.max(70, rows.length * rowH + 8);
    const max = Math.max(1, ...rows.map((r) => r[1]));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Items per topic" });
    host.classList.toggle("dim", S.f.topics.length > 0);
    rows.forEach(([t, n], k) => {
      const y = 4 + k * rowH, w = (W - L - R) * n / max, on = S.f.topics.includes(t);
      svg.appendChild(el("text", { x: L - 10, y: y + rowH / 2 + 4, "text-anchor": "end", "font-size": 12.5, style: on ? "fill:var(--fg);font-weight:650" : "" }, t));
      svg.appendChild(el("path", { d: barPath(L, y + 7, Math.max(3, w), rowH - 14, 4, true), class: "mark" + (on ? " on" : ""), style: "fill:var(--accent)" }));
      svg.appendChild(el("text", { x: L + w + 7, y: y + rowH / 2 + 4, class: "tick", style: "fill:var(--fg2)" }, fmtN(n)));
      const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit", "data-tip": `<b>${esc(t)}</b>` + row("", "Items", fmtN(n)) + hint(on ? "Click to remove this filter" : "Click to filter by this topic") });
      hit.addEventListener("click", () => toggle("topics", t));
      svg.appendChild(hit);
    });
    if (!rows.length) svg.appendChild(el("text", { x: W / 2, y: 38, "text-anchor": "middle", class: "empty" }, "No topics in view"));
    host.appendChild(svg);
  }

  function chartScores() {
    const host = $("#chScores"); host.innerHTML = "";
    const bins = S.base.score_hist;
    const W = width(host, 300, 520), H = 240, L = 34, R = 8, T = 14, B = 28;
    const max = niceMax(Math.max(1, ...bins));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Histogram of relevance scores" });
    const y = (v) => T + (H - T - B) * (1 - v / max), x = (s) => L + (W - L - R) * s / 100;
    ticks(max, 3).forEach((v) => { svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: v === 0 ? "base" : "gl" })); svg.appendChild(el("text", { x: L - 6, y: y(v) + 3.5, "text-anchor": "end", class: "tick" }, fmtN(v))); });
    const band = (a) => (a >= 60 ? "high" : a >= 35 ? "medium" : "low");
    bins.forEach((n, k) => {
      const a = k * 5, x0 = x(a) + 1, w = x(a + 5) - x(a) - 2;
      if (n) svg.appendChild(el("path", { d: barPath(x0, y(n), w, y(0) - y(n), 3), style: `fill:var(--b-${band(a)})`, opacity: a + 5 <= S.f.min ? 0.3 : 1 }));
      const hit = el("rect", { x: x0, y: T, width: w, height: H - T - B, class: "hit", "data-tip": `<b>Score ${a} to ${a + 4}</b>` + row(`var(--b-${band(a)})`, BAND_LABEL[band(a)] + " band", fmtN(n) + " items") + hint("Click to set the minimum score here") });
      hit.addEventListener("click", () => { S.f.min = Math.min(90, a); reload(); });
      svg.appendChild(hit);
    });
    [0, 20, 35, 60, 80, 100].forEach((v) => svg.appendChild(el("text", { x: x(v), y: H - 9, "text-anchor": "middle", class: "tick" }, v)));
    const mx = x(S.f.min);
    svg.appendChild(el("line", { x1: mx, x2: mx, y1: T - 4, y2: y(0), style: "stroke:var(--fg);stroke-width:1.5", "stroke-dasharray": "4 3" }));
    svg.appendChild(el("text", { x: mx + 5, y: T + 7, "font-size": 11, style: "fill:var(--fg)" }, "min " + S.f.min));
    host.appendChild(svg);
  }

  function chartSources() {
    const host = $("#chSources"); host.innerHTML = "";
    const by = S.base.by_source, rows = SRC.map((k) => [k, by[k] || 0]);
    const W = width(host, 300, 520), rowH = 30, L = 120, R = 44, H = rows.length * rowH + 6;
    const max = Math.max(1, ...rows.map((r) => r[1]));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Items per source" });
    host.classList.toggle("dim", S.f.sources.length > 0);
    rows.forEach(([k, n], j) => {
      const y = 3 + j * rowH, w = (W - L - R) * n / max, on = S.f.sources.includes(k);
      svg.appendChild(el("circle", { cx: 8, cy: y + rowH / 2, r: 5, style: `fill:var(--s-${k})` }));
      svg.appendChild(el("text", { x: 20, y: y + rowH / 2 + 4, "font-size": 13, style: on ? "fill:var(--fg);font-weight:650" : "fill:var(--fg)" }, SRC_LABEL[k]));
      svg.appendChild(el("rect", { x: L, y: y + 8, width: W - L - R, height: rowH - 16, rx: 4, style: "fill:var(--chip)" }));
      if (n) svg.appendChild(el("path", { d: barPath(L, y + 8, Math.max(3, w), rowH - 16, 4, true), class: "mark" + (on ? " on" : ""), style: `fill:var(--s-${k})` }));
      svg.appendChild(el("text", { x: W - R + 8, y: y + rowH / 2 + 4, class: "tick", style: "fill:var(--fg2)" }, fmtN(n)));
      const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit", "data-tip": `<b>${SRC_LABEL[k]}</b>` + row(`var(--s-${k})`, "Items in view", fmtN(n)) + hint(on ? "Click to remove this filter" : "Click to show only this source") });
      hit.addEventListener("click", () => toggle("sources", k));
      svg.appendChild(hit);
    });
    host.appendChild(svg);
  }

  function mix(t) {  // a share of the heat ramp, as a CSS color-mix
    return `color-mix(in oklab, var(--heat-1) ${Math.round(12 + 88 * t)}%, var(--heat-0))`;
  }
  function chartMatrix() {
    const host = $("#chMatrix"); host.innerHTML = "";
    const m = S.ov.topic_source, topics = Object.keys(S.ov.by_topic).slice(0, 9), srcs = SRC.filter((k) => S.ov.by_source[k]);
    if (!topics.length) { host.innerHTML = '<p class="note">No items in view.</p>'; return; }
    const W = width(host, 320, 560), L = 150, T = 26, cw = (W - L - 4) / Math.max(1, srcs.length), ch = 26, H = T + topics.length * ch + 4;
    const max = Math.max(1, ...topics.flatMap((t) => srcs.map((k) => (m[t] || {})[k] || 0)));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Items per topic and source" });
    srcs.forEach((k, j) => svg.appendChild(el("text", { x: L + cw * j + cw / 2, y: 14, "text-anchor": "middle", "font-size": 11.5 }, (cw < 60 ? SHORT : SRC_LABEL)[k])));
    topics.forEach((t, i) => {
      const y = T + i * ch;
      svg.appendChild(el("text", { x: L - 10, y: y + ch / 2 + 4, "text-anchor": "end", "font-size": 12.5 }, t));
      srcs.forEach((k, j) => {
        const n = (m[t] || {})[k] || 0, x = L + cw * j;
        svg.appendChild(el("rect", { x: x + 1, y: y + 1, width: cw - 2, height: ch - 2, rx: 4, style: `fill:${n ? mix(Math.sqrt(n / max)) : "var(--sunk)"}`, "data-tip": `<b>${esc(t)}</b>` + row(`var(--s-${k})`, SRC_LABEL[k], fmtN(n) + " items") }));
        if (n && cw > 30) svg.appendChild(el("text", { x: x + cw / 2, y: y + ch / 2 + 4, "text-anchor": "middle", class: "tick", style: n / max > 0.45 ? "fill:var(--surface);pointer-events:none" : "fill:var(--fg);pointer-events:none" }, fmtN(n)));
      });
    });
    host.appendChild(svg);
  }

  function chartPeople() {
    const host = $("#chPeople"); host.innerHTML = "";
    const rows = (S.ov.people || Object.entries(S.ov.top_people).map(([name, value]) => ({ name, value, works: null, items: null }))).slice(0, 8);
    if (!rows.length) { host.innerHTML = '<p class="note">No authors in view.</p>'; return; }
    const W = width(host, 320, 560), rowH = 30, L = Math.min(210, W * 0.42), R = 96, H = rows.length * rowH + 6;
    const max = Math.max(1, ...rows.map((r) => r.value));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Top contributors by pieces of work" });
    rows.forEach((r, k) => {
      const y = 3 + k * rowH, w = (W - L - R) * r.value / max, p = r.name;
      const name = p.length > 28 ? p.slice(0, 26) + "..." : p;
      const works = r.works == null ? "" : `${r.works} ${r.works === 1 ? "piece" : "pieces"}`;
      svg.appendChild(el("text", { x: L - 10, y: y + rowH / 2 + 4, "text-anchor": "end", "font-size": 12.5 }, name));
      svg.appendChild(el("path", { d: barPath(L, y + 8, Math.max(3, w), rowH - 16, 4, true), style: "fill:var(--b-medium)" }));
      svg.appendChild(el("text", { x: L + w + 7, y: y + rowH / 2 + 4, class: "tick", style: "fill:var(--fg2)" }, works || fmtN(r.value)));
      const tipHtml = `<b>${esc(p)}</b>` + (r.works != null ? row("", "Pieces of work", fmtN(r.works)) + row("", "Items", fmtN(r.items)) : "") +
        row("", "Weight (best score per piece, summed)", fmtN(r.value)) + hint("Click to search for this name");
      const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit", "data-tip": tipHtml });
      hit.addEventListener("click", () => { S.f.q = p; S.f.meaning = false; reload(); });
      svg.appendChild(hit);
    });
    host.appendChild(svg);
  }

  /* ------------------------------------------------------------ filters */
  // Sources, topics, relevance and the browser-only toggles sit in four small dropdowns; what is switched on shows as
  // removable pills under them, so the panel stays one row however many filters exist.
  function opt(group, value, label, n, extra, title) {
    const on = group === "toggle" ? S.f[value] : S.f[group].includes(value);
    return `<button type="button" class="fchip opt" role="checkbox" aria-checked="${on}" aria-pressed="${on}" data-g="${group}" data-v="${esc(value)}"${title ? ` title="${esc(title)}"` : ""}><i class="box" aria-hidden="true"></i>${extra || ""}<span class="ol">${esc(label)}</span>${n != null ? `<span class="n">${fmtN(n)}</span>` : ""}</button>`;
  }
  const TOGGLES = { code: "Links code", starred: "Starred", showHidden: "Show hidden", newOnly: "New since your visit" };
  function summary(sel, all, label) {
    if (!sel.length) return "";
    return sel.length === 1 ? label(sel[0]) : `${sel.length} of ${all}`;
  }
  function renderFilters() {
    const b = S.base;
    // Only what this window holds, plus anything already picked, so the lists carry no rows of zeros.
    const srcs = SRC.filter((k) => b.by_source[k] || S.f.sources.includes(k));
    $("#fSources").innerHTML = srcs.map((k) => opt("sources", k, SRC_LABEL[k], b.by_source[k] || 0, `<i class="dot s-${k}"></i>`)).join("") ||
      '<p class="note">Nothing in this window.</p>';
    const topics = Object.keys(b.by_topic);
    S.f.topics.forEach((t) => { if (!topics.includes(t)) topics.push(t); });
    $("#fTopics").innerHTML = topics.map((t) => opt("topics", t, t, b.by_topic[t] || 0)).join("") || '<p class="note">Nothing in this window.</p>';
    $("#fBands").innerHTML = BANDS.map((x) => opt("bands", x, BAND_LABEL[x] + (x === "high" ? " (60+)" : x === "medium" ? " (35 to 59)" : " (under 35)"), b.by_band[x] || 0, `<i class="dot" style="background:var(--b-${x})"></i>`)).join("");
    $("#fToggles").innerHTML = opt("toggle", "code", TOGGLES.code, null, "", "Only items that link code, models or data") +
      opt("toggle", "starred", TOGGLES.starred, S.stars.size, "", "Stars live in this browser") +
      opt("toggle", "showHidden", TOGGLES.showHidden, S.hide.size, "", "Hidden items live in this browser") +
      (S.lastVisit ? opt("toggle", "newOnly", TOGGLES.newOnly, null, "", "First seen by the radar after " + stamp(S.lastVisit)) : "");
    $("#vSources").textContent = summary(S.f.sources, srcs.length, (k) => SRC_LABEL[k]);
    $("#vTopics").textContent = summary(S.f.topics, topics.length, (t) => t);
    $("#vRel").textContent = [S.f.bands.length ? S.f.bands.map((x) => BAND_LABEL[x]).join(", ") : "", S.f.min ? S.f.min + "+" : ""].filter(Boolean).join(" · ");
    const tg = Object.keys(TOGGLES).filter((k) => S.f[k]);
    $("#vMore").textContent = summary(tg, Object.keys(TOGGLES).length, (k) => TOGGLES[k]);
    $$("#fbar .dd").forEach((d) => d.classList.toggle("active", !!d.querySelector(".ddv") && !!d.querySelector(".ddv").textContent));
    $("#q").value = S.f.q; $("#meaning").checked = S.f.meaning; $("#meaning").disabled = !S.f.q.trim(); $("#sort").value = S.f.sort; $("#min").value = S.f.min; $("#minOut").textContent = S.f.min;
    $("#per").value = String(S.per);
    $("#sort").disabled = S.f.meaning && !!S.f.q.trim();
    renderPills();
  }
  function renderPills() {
    const d = defaults(), pills = [];
    const pill = (g, v, label, dot) => pills.push(`<button type="button" class="pill" data-pg="${g}" data-pv="${esc(v)}" title="Remove this filter">${dot || ""}${esc(label)}<span aria-hidden="true">×</span></button>`);
    if (S.f.q.trim()) pill("q", "", (S.f.meaning ? "Meaning: " : "Search: ") + S.f.q.trim());
    S.f.sources.forEach((k) => pill("sources", k, SRC_LABEL[k], `<i class="dot s-${k}"></i>`));
    S.f.topics.forEach((t) => pill("topics", t, t));
    S.f.bands.forEach((x) => pill("bands", x, BAND_LABEL[x], `<i class="dot" style="background:var(--b-${x})"></i>`));
    if (S.f.min !== d.min) pill("min", "", "Score " + S.f.min + "+");
    Object.keys(TOGGLES).forEach((k) => { if (S.f[k]) pill("toggle", k, TOGGLES[k]); });
    $("#pills").innerHTML = pills.join("") + (pills.length > 1 ? '<button type="button" class="pill clear" data-pg="all">Clear all</button>' : "");
    $("#pills").hidden = !pills.length;
    $("#reset").hidden = !pills.length;
  }
  $("#pills").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pg]");
    if (!b) return;
    const g = b.dataset.pg, v = b.dataset.pv;
    if (g === "all") return resetFilters();
    if (g === "q") { S.f.q = ""; S.f.meaning = false; }
    else if (g === "min") S.f.min = defaults().min;
    else if (g === "toggle") S.f[v] = false;
    else S.f[g] = S.f[g].filter((x) => x !== v);
    if (g === "toggle" && v !== "code" && v !== "starred") { renderFilters(); renderList(); } else reload();
  });
  function toggle(group, v) {
    const a = S.f[group], k = a.indexOf(v);
    if (k >= 0) a.splice(k, 1); else a.push(v);
    reload();
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".fchip");
    if (!b) return;
    const g = b.dataset.g, v = b.dataset.v;
    if (g === "toggle") {
      S.f[v] = !S.f[v];
      if (v === "starred" || v === "code") reload(); else { renderFilters(); renderList(); }
    } else toggle(g, v);
  });
  // Dropdowns: one open at a time, closed by a click elsewhere or Escape, and kept inside the screen on a phone.
  $$(".filters .dd").forEach((d) => d.addEventListener("toggle", () => {
    if (!d.open) return;
    $$(".filters .dd[open]").forEach((o) => { if (o !== d) o.open = false; });
    const pnl = d.querySelector(".ddpanel");
    pnl.style.transform = "";
    const r = pnl.getBoundingClientRect(), edge = document.documentElement.clientWidth - 12;
    if (r.right > edge) pnl.style.transform = `translateX(${Math.round(edge - r.right)}px)`;
    else if (r.left < 12) pnl.style.transform = `translateX(${Math.round(12 - r.left)}px)`;
  }));
  document.addEventListener("click", (e) => { $$(".filters .dd[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; }); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const d = $(".filters .dd[open]");
    if (d) { d.open = false; d.querySelector("summary").focus(); }
  });
  $("#q").addEventListener("input", (e) => { S.f.q = e.target.value; $("#meaning").disabled = !S.f.q.trim(); reload(S.f.meaning ? 450 : 220); egg.typed(S.f.q); });
  $("#meaning").addEventListener("change", (e) => { S.f.meaning = e.target.checked; reload(); });
  $("#sort").addEventListener("change", (e) => { S.f.sort = e.target.value; reload(); });
  $("#per").addEventListener("change", (e) => { S.per = PER.includes(+e.target.value) ? +e.target.value : 10; reload(); });
  $("#min").addEventListener("input", (e) => { S.f.min = +e.target.value; $("#minOut").textContent = S.f.min; reload(250); });
  function resetFilters() { const keep = { view: S.f.view, since: S.f.since, sort: S.f.sort }; S.f = Object.assign(defaults(), keep); renderViews(); renderLookback(); reload(); }
  $("#reset").addEventListener("click", resetFilters);
  $("#shareBtn").addEventListener("click", (e) => copy(pageUrl(), e.currentTarget, "Copy link to this view"));
  function copy(text, btn, label) {
    const done = () => { btn.textContent = "Copied"; setTimeout(() => (btn.textContent = label), 1300); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(() => prompt("Copy this link", text));
    else prompt("Copy this link", text);
  }

  /* ------------------------------------------------------------ list */
  const ICON = {
    star: '<svg viewBox="0 0 20 20"><path d="m10 2.8 2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5L2.8 8.1l5-.7Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    starOn: '<svg viewBox="0 0 20 20"><path d="m10 2.8 2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5L2.8 8.1l5-.7Z" fill="currentColor"/></svg>',
    hide: '<svg viewBox="0 0 20 20"><path d="M3 10s2.6-5 7-5 7 5 7 5-2.6 5-7 5-7-5-7-5Z" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="2.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M4 16 16 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    show: '<svg viewBox="0 0 20 20"><path d="M3 10s2.6-5 7-5 7 5 7 5-2.6 5-7 5-7-5-7-5Z" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="10" cy="10" r="2.2" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>',
    copy: '<svg viewBox="0 0 20 20"><rect x="7" y="7" width="9" height="9" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M13 4.5H6A1.5 1.5 0 0 0 4.5 6v7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    ok: '<svg viewBox="0 0 20 20"><path d="m4.5 10.5 3.5 3.5 7.5-8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };
  function ring(i) {
    const r = 20, c = 2 * Math.PI * r, f = c * i.score / 100;
    const t = `<b>Score ${i.score}</b>` + row(`var(--b-${i.band})`, BAND_LABEL[i.band] + " band", "") + (i.learned ? row("", "Learned model", i.score) : "") + row("", "Keywords", i.keyword) + (i.semantic != null ? row("", "Meaning", i.semantic) : "") + (i.match != null ? row("", "Match to your search", i.match) : "");
    return `<div class="ring" data-tip="${esc(t)}"><svg viewBox="0 0 50 50"><circle class="bg" cx="25" cy="25" r="${r}"/><circle class="fg" cx="25" cy="25" r="${r}" style="stroke:var(--b-${i.band})" stroke-dasharray="${f} ${c}"/></svg><b>${i.score}</b></div>`;
  }
  function itemHTML(i) {
    const isNew = S.lastVisit && (i.first_seen || "") > S.lastVisit;
    const meta = [
      `<span class="src"><i class="dot s-${i.source}"></i>${esc(SRC_LABEL[i.source] || i.source)}</span>`,
      `<span>${esc(KIND[i.kind] || i.kind)}${i.state ? " · " + esc(i.state) : ""}${i.category ? " · " + esc(i.category) : ""}</span>`,
      `<span title="${esc(stamp(i.date))}${i.created && i.created !== i.date ? "; opened " + esc(stamp(i.created)) : ""}${i.first_seen ? "; found " + esc(stamp(i.first_seen)) : ""}">${esc(dm(D(i.date)))} (${esc(ago(i.date))})</span>`,
      i.who ? `<span${i.who_name ? ` title="${esc(i.who)}"` : ""}>${OPENED[i.kind] ? OPENED[i.kind] + " " : ""}${esc(clip(byline(i), 80))}</span>` : "",
      i.stars != null ? `<span>${fmtN(i.stars)} stars</span>` : "",
      i.likes ? `<span>${fmtN(i.likes)} likes</span>` : "",
      i.downloads ? `<span>${fmtN(i.downloads)} downloads</span>` : "",
      i.upvotes ? `<span>${fmtN(i.upvotes)} upvotes</span>` : "",
      i.comments ? `<span>${fmtN(i.comments)} comments</span>` : "",
      i.language ? `<span>${esc(i.language)}</span>` : "",
      i.license ? `<span>${esc(i.license)}</span>` : "",
      isNew ? `<span class="badge new">new</span>` : "",
      i.code ? `<span class="badge code">code</span>` : "",
      i.new_repo ? `<span class="badge soft">created in window</span>` : "",
      i.updated ? `<span class="badge soft">updated</span>` : "",
      i.prerelease ? `<span class="badge soft">pre-release</span>` : "",
      !i.learned && i.semantic != null && i.score > i.keyword ? `<span class="badge mean" title="The meaning model scored it higher than the keywords did">by meaning</span>` : "",
    ].filter(Boolean).join("");
    const byMeaning = new Set(i.topics_by_meaning || []);
    const links = [
      `<a href="${esc(safe(i.url))}" target="_blank" rel="noopener">Open</a>`,
      i.pdf ? `<a href="${esc(safe(i.pdf))}" target="_blank" rel="noopener">PDF</a>` : "",
      i.hf_url ? `<a href="${esc(safe(i.hf_url))}" target="_blank" rel="noopener">Hugging Face papers</a>` : "",
      i.doi_url ? `<a href="${esc(safe(i.doi_url))}" target="_blank" rel="noopener">DOI</a>` : "",
      i.discussion_url ? `<a href="${esc(safe(i.discussion_url))}" target="_blank" rel="noopener">Discussion</a>` : "",
      ...(i.code || []).map((u) => `<a href="${esc(safe(u))}" target="_blank" rel="noopener">Code: ${esc(u.replace(/^https?:\/\/(www\.)?/, "").slice(0, 48))}</a>`),
    ].filter(Boolean).join("");
    const starred = S.stars.has(i.id), hidden = S.hide.has(i.id), open = S.open.has(i.id), like = S.like.has(i.id);
    return `<article class="card item${hidden ? " hidden-item" : ""}" data-id="${esc(i.id)}">
      ${ring(i)}
      <div class="t"><h3><a href="${esc(safe(i.url))}" target="_blank" rel="noopener">${esc(i.title)}</a></h3></div>
      <div class="acts">
        <button class="icon${starred ? " on" : ""}" data-act="star" title="${starred ? "Unstar" : "Star (kept in this browser)"}" aria-label="${starred ? "Unstar" : "Star"}">${starred ? ICON.starOn : ICON.star}</button>
        <button class="icon" data-act="hide" title="${hidden ? "Unhide" : "Hide (kept in this browser)"}" aria-label="${hidden ? "Unhide" : "Hide"}">${hidden ? ICON.show : ICON.hide}</button>
        <button class="icon" data-act="copy" title="Copy link" aria-label="Copy link">${ICON.copy}</button>
      </div>
      <div class="meta">${meta}</div>
      <div class="body">
        ${updateHTML(i)}
        ${i.summary ? `<p class="summary" title="Click to expand">${i.activity && i.activity.who ? `<span class="slab">${esc(cap(OPENED[i.kind] || "posted by"))} ${esc(i.who_name || i.who || "")}:</span> ` : ""}${esc(i.summary)}</p>` : ""}
        <div class="tags">${i.topics.map((t) => `<button class="tag${byMeaning.has(t) ? " meaning" : ""}" data-topic="${esc(t)}"${byMeaning.has(t) ? ' title="Added by the meaning model"' : ""}>${esc(t)}</button>`).join("")}</div>
        <div class="links-row">
          <div class="links">${links}</div>
          <div class="more-row">
            <button class="btn ghost" data-act="why" type="button" aria-expanded="${open}" title="How the score was made: keywords, meaning and the learned model">Why this score</button>
            <button class="btn ghost" data-act="like" type="button" aria-expanded="${like}" title="The items closest to this one in meaning">More like this</button>
          </div>
        </div>
        <div class="detail" data-detail ${open ? "" : "hidden"}>${open ? whyHTML(i) : ""}</div>
        <div class="detail" data-similar ${like ? "" : "hidden"}></div>
      </div>
    </article>`;
  }
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const SEE = { comment: "the comment", review: "the review", commit: "the commit" };
  function updateHTML(i) {
    const a = i.activity;
    if (!a || !a.who) return "";
    const what = cap(a.what);
    const kind = /comment/.test(a.what) ? "comment" : /review|approved|changes requested/.test(a.what) ? "review" : a.what === "new commits" ? "commit" : "";
    const also = (a.also || []).length ? ` · <span class="also">also: ${esc(a.also.join(", "))}</span>` : "";
    const link = a.url ? ` · <a class="ulink" href="${esc(safe(a.url))}" target="_blank" rel="noopener">See ${SEE[kind] || "it"}</a>` : "";
    return `<div class="update-row"><span class="ulab">Latest update</span><span class="uwho"><b>${esc(what)}</b> by <b${a.who_name ? ` title="${esc(a.who)}"` : ""}>${esc(a.who_name || a.who)}</b> · <span title="${esc(stamp(a.date))}">${esc(ago(a.date))}</span>${also}${link}</span>` +
      (a.text ? `<p class="usaid" title="Click to expand">${esc(a.text)}</p>` : "") + `</div>`;
  }
  function whyHTML(i) {
    const parts = i.parts || [];
    const max = Math.max(20, ...parts.map((p) => Math.abs(p[1])));
    const rows = parts.map(([l, p]) => `<div class="why-row"><span class="lab">${esc(l)}</span><span class="bar"><i class="${p < 0 ? "neg" : ""}" style="width:${Math.round(100 * Math.abs(p) / max)}%"></i></span><span class="pts">${p > 0 ? "+" : ""}${p}</span></div>`).join("");
    const mean = i.semantic != null ? `<span>Meaning <b>${i.semantic}</b> (cosine ${i.sim} to "${esc(i.near || "")}")</span>` : `<span>Meaning: not scored${i.source === "pypi" ? " (package versions are scored by the package)" : ""}</span>`;
    return `<h4>Why this score</h4><div class="why">${rows || '<p class="note">No term matched; the score comes from meaning alone.</p>'}</div>
      <div class="why-total"><span>Keywords <b>${i.keyword}</b></span>${mean}<span>Final <b>${i.score}</b> (${esc(BAND_LABEL[i.band])})</span></div>${i.learned ? `<p class="note">The final score comes from the learned model, fitted to blind ratings of what items are worth to scroll work; it reads the ${i.learned === "full" ? "text's meaning, " : ""}keyword score, source, kind and popularity. The keyword points above explain the match; they no longer set the score.</p>` : ""}${i.capped ? `<p class="note">Capped at ${i.score}: ${esc(i.capped)}.</p>` : ""}`;
  }
  function visible() {
    let items = S.items.filter((i) => S.f.showHidden || !S.hide.has(i.id));
    if (S.f.newOnly && S.lastVisit) items = items.filter((i) => (i.first_seen || "") > S.lastVisit);
    return items;
  }
  function renderList() {
    const items = visible();
    const hiddenHere = S.items.length - S.items.filter((i) => !S.hide.has(i.id)).length;
    $("#count").innerHTML = `<b>${fmtN(S.matched)}</b> items match` + (S.byMeaning ? ", closest in meaning to your words first" : "") + (hiddenHere && !S.f.showHidden ? ` · ${fmtN(hiddenHere)} hidden` : "");
    if (!items.length) {
      const short = /^(1|5|15|30)m$/.test(S.f.since);
      $("#list").innerHTML = `<div class="card emptybox"><b>Nothing here yet.</b><span>${short ? "Short windows are often empty: papers arrive once a day and the collector checks GitHub and Hugging Face every 20 minutes. Try " : "Lower the minimum score, widen the lookback or "}</span><div class="more-row">
        <button class="btn" type="button" data-quick="1d">Show the last day</button><button class="btn ghost" type="button" data-quick="reset">Reset filters</button><button class="btn ghost" type="button" data-quick="found">Use "Found by the radar"</button></div></div>`;
      $("#pager").innerHTML = "";
      return;
    }
    $("#list").innerHTML = items.map(itemHTML).join("");
    $("#pager").innerHTML = pagerHTML();
    $$("[data-similar]:not([hidden])").forEach((d) => loadSims(d.closest(".item").dataset.id, d));
  }
  $("#pager").addEventListener("click", (e) => { const b = e.target.closest("[data-page]"); if (b && !b.disabled) goPage(+b.dataset.page).catch(fail); });
  $("#list").addEventListener("click", (e) => {
    const q = e.target.closest("[data-quick]");
    if (q) {
      if (q.dataset.quick === "1d") { S.f.since = "1d"; renderLookback(); } else if (q.dataset.quick === "found") { S.f.by = "found"; renderLookback(); } else { const keep = { view: S.f.view, since: S.f.since }; S.f = Object.assign(defaults(), keep); }
      reload(); return;
    }
    const card = e.target.closest(".item");
    if (!card) return;
    const id = card.dataset.id, item = S.items.find((x) => x.id === id);
    const t = e.target.closest("[data-topic]");
    if (t) { if (!S.f.topics.includes(t.dataset.topic)) toggle("topics", t.dataset.topic); return; }
    if (e.target.closest(".summary, .usaid")) { e.target.closest(".summary, .usaid").classList.toggle("open"); return; }
    const a = e.target.closest("[data-act]");
    if (!a || !item) return;
    const act = a.dataset.act;
    if (act === "star") { S.stars.has(id) ? S.stars.delete(id) : S.stars.add(id); store.set("stars", Array.from(S.stars)); renderFilters(); renderList(); }
    if (act === "hide") { S.hide.has(id) ? S.hide.delete(id) : S.hide.add(id); store.set("hidden", Array.from(S.hide)); renderFilters(); renderList(); }
    if (act === "copy") { (navigator.clipboard ? navigator.clipboard.writeText(item.url) : Promise.reject()).then(() => { a.innerHTML = ICON.ok; setTimeout(() => (a.innerHTML = ICON.copy), 1200); }).catch(() => {}); }
    // Each button opens and closes its own panel: the score's breakdown, or the nearest items in meaning.
    if (act === "why") {
      const d = card.querySelector("[data-detail]");
      if (d.hidden) { S.open.add(id); d.innerHTML = whyHTML(item); d.hidden = false; } else { S.open.delete(id); d.hidden = true; }
      a.setAttribute("aria-expanded", String(!d.hidden));
    }
    if (act === "like") {
      const d = card.querySelector("[data-similar]");
      if (d.hidden) { S.like.add(id); d.hidden = false; loadSims(id, d, true); } else { S.like.delete(id); d.hidden = true; }
      a.setAttribute("aria-expanded", String(!d.hidden));
    }
  });
  const simCache = {};
  async function loadSims(id, box, scroll) {
    box.innerHTML = '<h4>More like this</h4><p class="note">Finding the closest items in meaning...</p>';
    try {
      const it = simCache[id] || (simCache[id] = (await getJSON("api/item?id=" + encodeURIComponent(id))).body);
      const sims = it.similar || [];
      box.innerHTML = `<h4>More like this</h4>` + (sims.length ? `<ul class="sim-list">${sims.map((s) => `<li><i class="dot s-${esc(s.source)}" title="${esc(SRC_LABEL[s.source] || s.source)}"></i><a href="${esc(safe(s.url))}" target="_blank" rel="noopener">${esc(s.title)}</a><span class="s" title="Cosine similarity">${s.similarity.toFixed(2)}</span></li>`).join("")}</ul>` : '<p class="note">The meaning model is not loaded yet, so there are no neighbors to show.</p>');
      if (scroll) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (e) { box.innerHTML = '<p class="note">Could not load similar items: ' + esc(e.message) + "</p>"; }
  }

  let rz;
  addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (S.ov) { chartTime(); chartTopics(); chartScores(); chartSources(); chartMatrix(); chartPeople(); } }, 150); });
  function renderAll() {
    renderViews(); renderLookback(); renderKpis(); renderFilters();
    chartTime(); chartTopics(); chartScores(); chartSources(); chartMatrix(); chartPeople(); renderList();
  }

  /* ------------------------------------------------------------ briefing */
  async function loadBriefing() {
    const p = viewParams({ min_score: Math.max(35, S.f.min), per_topic: 3 });
    const { body: b } = await getJSON("api/briefing?" + p);
    $("#briefWhen").textContent = `Last ${lbLabel(S.f.since)} · ${stamp(b.since)} to now`;
    $("#briefTitle").textContent = `Briefing for ${b.label}`;
    $("#briefAbout").textContent = b.about;
    const ov = S.ov || { items: 0, high: 0, with_code: 0, new_repos: 0 };
    $("#briefStats").innerHTML = [[b.items, "items score 35+"], [ov.high, "high relevance"], [ov.with_code + ov.new_repos, "with code or new repos"]].map(([n, l]) => `<div><b>${fmtN(n)}</b><span>${l}</span></div>`).join("");
    const topics = Object.entries(b.topics);
    $("#briefGrid").innerHTML = topics.length ? topics.map(([t, items]) => `<section class="card brief-topic"><h3>${esc(t)}<span>${fmtN((S.ov && S.ov.by_topic[t]) || items.length)} in view</span></h3>${items.map((i) => `
      <div class="bitem"><span class="sc ${i.band === "high" ? "high" : ""}">${i.score}</span><a href="${esc(safe(i.url))}" target="_blank" rel="noopener">${esc(i.title)}</a>
      <span class="m"><i class="dot s-${esc(i.source)}"></i>${esc(SRC_LABEL[i.source] || i.source)} · ${esc(KIND[i.kind] || i.kind)} · ${esc(ago(i.date))}${i.activity && i.activity.who ? " · " + esc(i.activity.what) + " by " + esc(i.activity.who_name || i.activity.who) : i.who ? " · " + esc(i.who_name || i.who.split(",")[0]) : ""}${i.code ? ' · <span class="badge code">code</span>' : ""}</span></div>`).join("")}</section>`).join("")
      : `<div class="card emptybox"><b>Nothing scores 35 or more in this window.</b><span>Widen the lookback above, or switch to Everyone.</span></div>`;
  }

  /* ------------------------------------------------------------ sources tab */
  const SRC_ABOUT = {
    arxiv: (c) => [`Today's announcement for ${c.rss.join(", ")}, with abstracts`, `Past-week lists of ${c.pastweek.join(", ")} once a day, to catch up after sleep`, "A search of every category for scroll terms"],
    github: (c) => [`Repository searches: ${c.queries.join("; ")}`, `Pull requests, issues and releases of ${c.watch_repos.join(", ")}`, "Logged out; unchanged listings answered from cache"],
    hf: (c) => [`Models, datasets and Spaces matching ${c.search.join(", ")}`, `Everything by ${c.authors.join(", ")}`, "Daily papers, merged with their arXiv rows"],
    pypi: (c) => [`New versions of ${Object.keys(c.packages).length} packages: ${Object.keys(c.packages).join(", ")}`, "Pre-releases score 10 lower"],
    zenodo: (c) => [`Records matching ${c.queries.join("; ")}`, "Datasets, software, preprints and articles"],
    journals: (c) => [`Crossref works created in the window matching ${c.queries.join("; ")}`, "Journal articles, chapters, proceedings and posted content"],
    blog: (c) => [`The feeds of ${[...new Set(c.feeds.map((f) => f.name || f[0]))].join(", ")}`, "News searches go through the scorer like any listing, and a story found twice is kept once"],
  };
  function renderSources() {
    const b = S.src;
    if (!b) return;
    $("#srcTable tbody").innerHTML = SRC.map((k) => {
      const v = b.sources[k];
      return `<tr><td class="first" data-l="Source"><span class="nm"><i class="dot s-${k}"></i>${esc(v.label)}</span></td><td data-l="Every">${v.every_min < 60 ? v.every_min + " min" : v.every_min / 60 + " h"}</td>
        <td data-l="Last check">${v.last_check ? esc(ago(v.last_check)) : "not yet"}</td><td data-l="Next">${v.state === "running" ? "now" : esc(until(v.next_check))}</td>
        <td data-l="State"><span class="state ${esc(v.state)}">${esc(v.state)}</span></td><td class="num" data-l="Read">${fmtN(v.read)}</td><td class="num" data-l="Kept">${fmtN(v.kept)}</td>
        <td class="num" data-l="New">${fmtN(v.new)}</td><td class="num" data-l="Stored">${fmtN(v.items_stored)}</td><td class="num" data-l="Time">${v.seconds} s</td></tr>`;
    }).join("");
    $("#runTable tbody").innerHTML = (b.runs || []).slice(0, 40).map((r) => `<tr><td class="first" data-l="Finished">${esc(stamp(r.finished))}</td><td data-l="Source"><span class="nm"><i class="dot s-${esc(r.source)}"></i>${esc(SRC_LABEL[r.source] || r.source)}</span></td>
      <td data-l="State"><span class="state ${esc(r.state)}">${esc(r.state)}</span></td><td class="num" data-l="Read">${fmtN(r.read)}</td><td class="num" data-l="Kept">${fmtN(r.kept)}</td><td class="num" data-l="New">${fmtN(r.new)}</td>
      <td class="num" data-l="Time">${(r.ms / 1000).toFixed(1)} s</td><td class="notes" data-l="Notes">${esc((r.notes || []).join("; "))}</td></tr>`).join("") || `<tr><td colspan="8">No checks yet since the Space started.</td></tr>`;
    if (S.cfg && !$("#srcCards").children.length) {
      $("#srcCards").innerHTML = SRC.map((k) => `<div class="card src-card"><h3><i class="dot s-${k}"></i>${esc(SRC_LABEL[k])}</h3><ul>${SRC_ABOUT[k](S.cfg.sources[k]).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("");
    }
  }

  /* ------------------------------------------------------------ connect + how */
  function renderLinks() {
    const base = location.origin + location.pathname.replace(/[^/]*$/, "");
    $("#lnkJson").textContent = base + "api/items?" + viewParams({ ids: null, limit: 100 });
    $("#lnkCsv").textContent = base + "api/export.csv?" + viewParams({ ids: null });
    $("#lnkRss").textContent = base + "feed.xml?" + viewParams({ ids: null, by_meaning: null, q: null, min_score: Math.max(S.f.min, 35) });
    $("#lnkPage").textContent = pageUrl();
    $("#dlCsv").href = "api/export.csv?" + viewParams();
    $("#dlJson").href = "api/items?" + viewParams({ limit: 100 });
    $("#dlRss").href = "feed.xml?" + viewParams({ ids: null, by_meaning: null, q: null, min_score: Math.max(S.f.min, 35) });
  }
  document.addEventListener("click", (e) => { const b = e.target.closest("[data-copy]"); if (b) copy($("#" + b.dataset.copy).textContent, b, "Copy"); });
  async function loadConfig() {
    const [{ body: c }, { body: v }] = await Promise.all([getJSON("api/config"), getJSON("api/views")]);
    S.cfg = c; S.views = v; renderViews();
    $("#howModel").textContent = c.semantic.model;
    $("#howTopics").innerHTML = `<div class="t"><h3><span>Scroll terms</span><span class="w">+${c.core.weight}</span></h3><p>${c.core.terms.map(esc).join(", ")}</p></div>` +
      Object.entries(c.topics).map(([n, t]) => `<div class="t"><h3><span>${esc(n)}</span><span class="w">+${t.weight} strong, +${Math.floor(t.weight / 2)} weak</span></h3><p><b>strong:</b> ${t.strong.map(esc).join(", ")}<br><b>weak:</b> ${t.weak.map(esc).join(", ")}</p></div>`).join("") +
      `<div class="t"><h3><span>Context terms</span><span class="w">+${c.context_bonus}</span></h3><p>${c.context.map(esc).join(", ")}</p></div>` +
      `<div class="t"><h3><span>Off-topic terms</span><span class="w">-15 each, up to 2</span></h3><p>${c.negative.map(esc).join(", ")}</p></div>` +
      (c.learned && c.learned.ready ? `<div class="t"><h3><span>Learned model</span><span class="w">rank agreement ${c.learned.evaluation.full.spearman} on held-out items</span></h3><p>Ridge regression on the embedding plus ${esc(c.learned.meta_features.join(", "))}, source and kind; fitted ${esc(c.learned.trained)} to blind ratings of ${fmtN(c.learned.items)} items, ${esc(c.learned.calibration)} calibration to 0 to 100. The keyword and meaning scores alone agreed ${c.learned.evaluation.rule_score} with the same ratings.</p></div>` : "") +
      `<div class="t"><h3><span>Meaning anchors</span><span class="w">cosine ${c.semantic.sim_floor} to ${c.semantic.sim_ceiling} maps to 0 to 100</span></h3><p>${Object.values(c.semantic.anchors).flat().map(esc).join("<br>")}</p></div>`;
    $("#howSources").innerHTML = SRC.map((k) => `<li><b><i class="dot s-${k}"></i> ${esc(SRC_LABEL[k])}</b> (every ${c.sources[k].every_min < 60 ? c.sources[k].every_min + " minutes" : c.sources[k].every_min / 60 + " hours"}): ${esc(SRC_ABOUT[k](c.sources[k]).join("; "))}.</li>`).join("");
    renderSources();
  }

  /* ------------------------------------------------------------ tabs, theme */
  function selectTab(name) {
    $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    $$(".panel").forEach((p) => (p.hidden = p.dataset.panel !== name));
    if (name === "briefing") loadBriefing().catch(fail);
    if (name === "sources") renderSources();
    if (name === "connect") renderLinks();
    try { history.replaceState(null, "", location.pathname + location.search + "#" + name); } catch (e) { /* sandboxed */ }
  }
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  function setTheme(t) {
    if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
    try { localStorage.setItem("vradar.theme", t === "auto" ? "" : t); } catch (e) { /* ignore */ }
    $$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === t)));
    drawScene();
  }
  $$("[data-theme-set]").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeSet)));
  $$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === (document.documentElement.dataset.theme || "auto"))));

  /* ------------------------------------------------------------ hero: Vesuvius over the bay, with a radar sweep */
  // A drawn scene, not a photo: the Bay of Naples, Vesuvius (Monte Somma and the Gran Cono), Pliny's pine-shaped
  // plume, Herculaneum's colonnades and stone pines on the shore, and radar rings from the crater. Each blip is a
  // source that brought items in the last day, in that source's color. Deterministic, so it never jumps on reload.
  const HERO = { blips: [] };
  const sceneTheme = () => {
    const t = document.documentElement.dataset.theme;
    return t === "light" || t === "dark" || t === "vesuvius" ? t : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  };
  const PAL = {
    light: { sky: ["#cfe0f3", "#eef0f0", "#f8e3c8"], sun: "#fff3d6", sunO: .95, ring: "#2a78d6", ringO: .22, sweep: "#2a78d6", sweepO: .16,
      far: "#b9c6d6", shade: "#8d8f9e", lit: "#b4b3b9", gully: "#6d6e7d", smoke: "#9b9aa6", smokeO: .34, crater: null,
      sea: ["#9cc0de", "#7ea9cf"], shim: "#ffffff", land: "#7f9a6a", land2: "#5f7d4f", wall: "#efe4d1", roof: "#c9714a", col: "#d8cbb3", pine: "#3f5a35", trunk: "#5b4636" },
    dark: { sky: ["#0a1220", "#152036", "#2a2b3d"], sun: "#c9d6ff", sunO: .35, ring: "#86b6ef", ringO: .22, sweep: "#3987e5", sweepO: .22,
      far: "#1e2738", shade: "#141a26", lit: "#232b3b", gully: "#0d121b", smoke: "#6b7385", smokeO: .22, crater: "#ff8a4c",
      sea: ["#13233a", "#0d1a2c"], shim: "#9fc3ff", land: "#1a2419", land2: "#121a12", wall: "#3a3f4c", roof: "#5a3a33", col: "#4a4f5c", pine: "#0f1a12", trunk: "#1b1712" },
    vesuvius: { sky: ["#120b0a", "#2a120b", "#6a250d"], sun: "#ff9a4a", sunO: .45, ring: "#ffa070", ringO: .2, sweep: "#ff6a2b", sweepO: .28,
      far: "#2c1712", shade: "#1c110e", lit: "#2f1d17", gully: "#120a08", smoke: "#4a3a34", smokeO: .55, crater: "#ff6a2b",
      sea: ["#2a1410", "#1a0d0a"], shim: "#ff9a5a", land: "#20140f", land2: "#160d0a", wall: "#3a2a22", roof: "#6e2e14", col: "#4b3529", pine: "#120a07", trunk: "#1a100b" },
  };
  function drawScene() {
    const svg = $("#scene");
    if (!svg) return;
    const P = PAL[sceneTheme()], W = 1600, cx = 1162, cy = 292;
    let seed = 7;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const f = (v) => v.toFixed(1);
    const o = [];
    o.push(`<defs>
      <linearGradient id="vsky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${P.sky[0]}"/><stop offset=".55" stop-color="${P.sky[1]}"/><stop offset="1" stop-color="${P.sky[2]}"/></linearGradient>
      <radialGradient id="vsun"><stop offset="0" stop-color="${P.sun}"/><stop offset="1" stop-color="${P.sun}" stop-opacity="0"/></radialGradient>
      <radialGradient id="vglow"><stop offset="0" stop-color="${P.crater || P.sun}"/><stop offset="1" stop-color="${P.crater || P.sun}" stop-opacity="0"/></radialGradient>
      <linearGradient id="vsea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${P.sea[0]}"/><stop offset="1" stop-color="${P.sea[1]}"/></linearGradient>
      <linearGradient id="vcone" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${P.shade}"/><stop offset="1" stop-color="${P.lit}"/></linearGradient>
      <filter id="vblur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="9"/></filter>
      <filter id="vsoft"><feGaussianBlur stdDeviation="2.2"/></filter>
    </defs>`);
    o.push(`<rect width="${W}" height="760" fill="url(#vsky)"/><circle cx="1440" cy="250" r="210" fill="url(#vsun)" opacity="${P.sunO}"/>`);
    o.push(`<rect y="600" width="${W}" height="160" fill="url(#vsea)"/>`);
    o.push('<g transform="translate(240 150) scale(.85)">');
    // radar rings and cross hairs from the crater, behind the mountain
    const R = [110, 210, 310, 410, 510];
    R.forEach((r, i) => o.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${P.ring}" stroke-opacity="${f(P.ringO * (1 - i * .12))}" stroke-width="1.3" ${i % 2 ? 'stroke-dasharray="3 7"' : ""}/>`));
    o.push(`<path d="M${cx - 520} ${cy}H${cx + 520}M${cx} ${cy - 330}V${cy + 40}" stroke="${P.ring}" stroke-opacity="${f(P.ringO * .6)}" stroke-width="1"/>`);
    // the sweep: thin wedges that fade behind the leading edge
    let sw = "";
    for (let k = 0; k < 14; k++) {
      const a0 = (-90 - k * 4) * Math.PI / 180, a1 = (-90 - (k + 1) * 4) * Math.PI / 180, r = 520;
      sw += `<path d="M${cx} ${cy}L${f(cx + r * Math.cos(a0))} ${f(cy + r * Math.sin(a0))}A${r} ${r} 0 0 0 ${f(cx + r * Math.cos(a1))} ${f(cy + r * Math.sin(a1))}Z" fill="${P.sweep}" fill-opacity="${f(P.sweepO * (1 - k / 14))}"/>`;
    }
    sw += `<line x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy - 520}" stroke="${P.sweep}" stroke-opacity="${f(Math.min(1, P.sweepO * 3))}" stroke-width="2"/>`;
    o.push(`<g class="sweep" style="transform-origin:${cx}px ${cy}px">${sw}</g>`);
    // blips: one per source with items in the last day (two for the busiest), placed in the sky inside the rings
    HERO.blips.forEach((b, i) => {
      let x, y, tries = 0;
      do { const a = (-165 + rnd() * 150) * Math.PI / 180, r = 130 + rnd() * 300; x = cx + r * Math.cos(a); y = cy + r * Math.sin(a); tries++; } while ((y > 250 || y < 20 || x < 830 || Math.abs(x - cx - 30) < 90 && y < cy - 120) && tries < 60);
      const d = f((i * 0.63) % 4.5);
      o.push(`<circle class="ping" cx="${f(x)}" cy="${f(y)}" r="9" fill="none" stroke="var(--s-${b})" stroke-width="2" style="animation-delay:${d}s"/>`);
      o.push(`<circle class="blip" cx="${f(x)}" cy="${f(y)}" r="5.5" fill="var(--s-${b})" stroke="${P.sky[1]}" stroke-width="2" style="animation-delay:${d}s"/>`);
    });
    // Pliny's plume: a column that spreads like a stone pine
    let pl = `<path d="M${cx - 16} ${cy + 4}C${cx - 10} ${cy - 60} ${cx + 4} ${cy - 110} ${cx + 10} ${cy - 150}L${cx + 34} ${cy - 150}C${cx + 30} ${cy - 110} ${cx + 22} ${cy - 60} ${cx + 18} ${cy + 4}Z" fill="${P.smoke}"/>`;
    for (let k = 0; k < 16; k++) {
      const u = k / 15, px = cx + 22 + (u - .5) * 280 + (rnd() - .5) * 30 + u * 40, py = cy - 170 - Math.sin(u * Math.PI) * 40 + (rnd() - .5) * 16;
      pl += `<circle cx="${f(px)}" cy="${f(py)}" r="${f(26 + rnd() * 26 + Math.sin(u * Math.PI) * 18)}" fill="${P.smoke}"/>`;
    }
    o.push(`<g class="plume" opacity="${P.smokeO}" filter="url(#vblur)">${pl}</g>`);
    // the far Apennines
    o.push(`<path d="M-300 640 C100 628 420 612 600 600 C760 560 860 575 960 548 C1060 522 1120 556 1240 540 C1360 524 1460 548 1600 520 L1600 760 L-300 760Z" fill="${P.far}"/>`);
    // Vesuvius: Monte Somma's broken rim on the left, the Gran Cono in the middle, one light from the right
    const mtn = `M560 700 C700 650 800 560 880 480 C920 440 950 420 985 404 L1004 416 L1026 392 L1046 404 L1068 372 L1090 362 L1104 338 L1124 304 L1140 294 L1186 290 L1204 300 C1240 340 1300 400 1380 460 C1460 520 1540 560 1600 584 L1600 760 L560 760Z`;
    o.push(`<path d="${mtn}" fill="${P.shade}"/>`);
    o.push(`<path d="M1170 292 L1186 290 L1204 300 C1240 340 1300 400 1380 460 C1460 520 1540 560 1600 584 L1600 760 L1260 760 C1230 600 1200 420 1170 292Z" fill="url(#vcone)" opacity=".95"/>`);
    // gullies down the cone
    for (let k = 0; k < 16; k++) {
      const t = rnd(), sy = 320 + rnd() * 110, half = (sy - 290) * (1.05 + t * .35), sx = cx + 10 + (t - .5) * 2 * half;
      const len = 60 + rnd() * 150, dx = (sx - cx - 10) * len / Math.max(60, sy - 280) * .9;
      o.push(`<path d="M${f(sx)} ${f(sy)} q${f(dx * .4)} ${f(len * .5)} ${f(dx)} ${f(len)}" fill="none" stroke="${P.gully}" stroke-opacity="${f(.12 + rnd() * .16)}" stroke-width="${f(1.2 + rnd() * 2)}" stroke-linecap="round"/>`);
    }
    // haze across the lower slopes gives the mountain distance
    o.push(`<ellipse cx="1180" cy="560" rx="520" ry="34" fill="${P.sky[2]}" opacity=".45" filter="url(#vblur)"/>`);
    if (P.crater) {
      o.push(`<ellipse class="glow" cx="${cx}" cy="${cy}" rx="46" ry="12" fill="url(#vglow)"/>`);
      if (sceneTheme() === "vesuvius") for (let k = 0; k < 3; k++) {
        const sx = cx - 8 + k * 14;
        o.push(`<path class="glow" d="M${sx} ${cy + 2} q${f(-6 + k * 6)} 50 ${f(-14 + k * 22)} 110 t${f(-10 + k * 16)} 90" fill="none" stroke="${P.crater}" stroke-width="2.2" stroke-linecap="round" opacity=".8" filter="url(#vsoft)" style="animation-delay:${k * .7}s"/>`);
      }
    }
    // eruption layer (filled on a click in the Vesuvius theme) and the click target over the mountain
    o.push(`<g id="erupt"></g><path class="vhit" d="${mtn}" fill="transparent"><title>Vesuvius</title></path>`);
    // the bay
    o.push(`<path d="M-300 648 C300 640 560 652 820 646 C1000 642 1180 652 1600 646 L1600 760 L-300 760Z" fill="url(#vsea)"/>`);
    for (let k = 0; k < 26; k++) {
      const x = 640 + rnd() * 900, y = 664 + rnd() * 84, w = 16 + rnd() * 44;
      o.push(`<path class="shimmer" d="M${f(x)} ${f(y)}h${f(w)}" stroke="${P.shim}" stroke-width="1.4" stroke-linecap="round" style="animation-delay:${f(rnd() * 6)}s"/>`);
    }
    // the shore at Herculaneum: a terrace, houses with tiled roofs, a colonnade
    o.push(`<path d="M780 652 C900 630 1040 626 1180 632 C1290 636 1400 640 1600 628 L1600 676 C1400 684 1200 680 980 676 C900 674 840 670 780 668Z" fill="${P.land}"/>`);
    const houses = [[880, 618, 54, 26], [940, 610, 38, 34], [986, 622, 60, 22], [1300, 614, 46, 30], [1352, 620, 58, 24]];
    houses.forEach(([x, y, w, h]) => o.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${P.wall}"/><path d="M${x - 4} ${y}L${x + w / 2} ${y - 12}L${x + w + 4} ${y}Z" fill="${P.roof}"/>`));
    o.push(`<rect x="1062" y="612" width="196" height="8" fill="${P.wall}"/><rect x="1062" y="638" width="196" height="6" fill="${P.wall}"/>`);
    for (let k = 0; k < 12; k++) o.push(`<rect x="${1068 + k * 16}" y="620" width="5" height="18" fill="${P.col}"/>`);
    o.push(`<path d="M1056 612L1160 594L1264 612Z" fill="${P.roof}"/>`);
    // stone pines in front
    const pine = (x, y, s) => {
      let g = `<path d="M${x} ${y}C${x - 2 * s} ${y - 40 * s} ${x + 4 * s} ${y - 70 * s} ${x + 2 * s} ${y - 96 * s}" stroke="${P.trunk}" stroke-width="${f(5 * s)}" fill="none" stroke-linecap="round"/>`;
      for (let k = 0; k < 7; k++) g += `<ellipse cx="${f(x + 2 * s + (k - 3) * 15 * s)}" cy="${f(y - 104 * s - Math.sin(k / 6 * Math.PI) * 10 * s)}" rx="${f(26 * s)}" ry="${f(12 * s)}" fill="${P.pine}"/>`;
      return g;
    };
    o.push(`<path d="M1340 760 C1400 700 1480 676 1600 668 L1600 760Z" fill="${P.land2}"/>`);
    o.push(pine(1470, 700, 1.15) + pine(1560, 690, .95) + pine(845, 668, .62) + pine(1215, 652, .5));
    o.push("</g>");
    svg.innerHTML = o.join("");
  }
  async function heroStats() {
    try {
      const [d1, d7] = await Promise.all([getJSON("api/overview?since=1d"), getJSON("api/overview?since=7d")]);
      const by = d1.body.by_source || {};
      const ranked = SRC.filter((k) => by[k]).sort((a, b) => by[b] - by[a]);
      HERO.blips = ranked.concat(ranked.slice(0, 3)).concat(ranked.slice(0, 1));
      drawScene();
      const c = d7.body.community || {};
      const stats = [[fmtN(d1.body.items), "new in the last day"], [fmtN(d7.body.high), "high scores this week"],
        [fmtN(c.new_scroll_repos || 0), "new scroll repositories this week"], [fmtN(c.villa_merged || 0), "villa pull requests merged this week"]];
      $("#heroStats").innerHTML = stats.map(([b, l]) => `<div class="hstat"><b>${b}</b><span>${l}</span></div>`).join("");
    } catch (e) { /* the hero keeps its drawing; the stats wait for the next try */ }
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawScene);
  $$("[data-go]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const tab = a.dataset.go;
    if (tab === "radar" && S.f.since !== "1d") { S.f.since = "1d"; renderLookback(); reload(0); }
    selectTab(tab);
    $(".tabs").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }));

  /* ------------------------------------------------------------ easter eggs */
  // 1. In the Vesuvius theme, click the volcano: it erupts (lava fountain, ash column, flows, volcanic lightning).
  // 2. The Konami code (up up down down left right left right B A): every source's color goes up as fireworks.
  // 3. Type "pliny" in the search box: Pliny the Younger's line on the pine-shaped cloud, and the plume swells.
  const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  let toastTimer;
  function toast(html, ms) {
    const t = $("#toast");
    t.innerHTML = html; t.hidden = false; t.classList.remove("out");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.classList.add("out"); setTimeout(() => { t.hidden = true; }, 600); }, ms || 6500);
  }
  const egg = {
    busy: false,
    erupt() {
      if (egg.busy || sceneTheme() !== "vesuvius") return;
      const g = $("#erupt");
      if (!g) return;
      egg.busy = true;
      const cx = 1162, cy = 292, o = [];
      let seed = 79;
      const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
      const LAVA = ["#ffd27a", "#ffb347", "#ff8a3d", "#ff6a2b", "#ff3b2f", "#ffe9a8"];
      o.push(`<ellipse class="e-flash" cx="${cx}" cy="${cy}" rx="140" ry="60" fill="url(#vglow)"/>`);
      // the ash column: puffs that rise, spread and drift with the wind
      for (let k = 0; k < 26; k++) {
        const r = 30 + rnd() * 40, d = (k * 0.16).toFixed(2), dx = Math.round(-60 + rnd() * 160 + k * 4), dy = Math.round(-200 - rnd() * 260);
        o.push(`<circle class="e-ash" cx="${cx + 10}" cy="${cy - 10}" r="${r.toFixed(0)}" fill="${k % 3 ? "#4a3a34" : "#6b5a52"}" style="--dx:${dx}px;--dy:${dy}px;animation-delay:${d}s"/>`);
      }
      // volcanic lightning inside the column
      [[cx - 40, cy - 250, "#c9b6ff"], [cx + 70, cy - 320, "#9fd0ff"], [cx + 10, cy - 200, "#ffd1f0"]].forEach(([x, y, col], k) => {
        let d = `M${x} ${y}`;
        for (let j = 0; j < 5; j++) d += ` l${Math.round(-18 + rnd() * 36)} ${Math.round(14 + rnd() * 16)}`;
        o.push(`<path class="e-bolt" d="${d}" stroke="${col}" stroke-width="3" fill="none" stroke-linecap="round" style="animation-delay:${(2.2 + k * 1.3).toFixed(1)}s"/>`);
      });
      // the lava fountain: glowing bombs thrown in arcs
      for (let k = 0; k < 46; k++) {
        const ang = (-90 + (rnd() - 0.5) * 70) * Math.PI / 180, v = 120 + rnd() * 230;
        const dx = Math.round(Math.cos(ang) * v * 1.4), up = Math.round(Math.sin(ang) * v), down = Math.round(160 + rnd() * 120);
        o.push(`<circle class="e-bomb" cx="${cx}" cy="${cy}" r="${(2.5 + rnd() * 4).toFixed(1)}" fill="${LAVA[k % LAVA.length]}" style="--dx:${dx}px;--up:${up}px;--down:${down}px;animation-delay:${(0.4 + rnd() * 4.5).toFixed(2)}s"/>`);
      }
      // lava flows down the cone
      [[-10, 260, 0.6], [18, 300, 1.1], [44, 240, 1.7], [-34, 220, 2.3]].forEach(([off, len, d]) => {
        o.push(`<path class="e-flow" d="M${cx + off} ${cy + 4} q${off * 1.6} ${len * 0.45} ${off * 3.2 + 20} ${len}" stroke="${off > 20 ? "#ff3b2f" : "#ff8a3d"}" stroke-width="6" fill="none" stroke-linecap="round" pathLength="100" style="animation-delay:${d}s"/>`);
      });
      g.innerHTML = o.join("");
      $(".hero").classList.add("erupting");
      toast("<b>Vesuvius erupts.</b> Herculaneum's library lay under the ash for about 1,700 years; the radar is here to help read it.", 7000);
      setTimeout(() => { g.innerHTML = ""; $(".hero").classList.remove("erupting"); egg.busy = false; }, reduce() ? 2500 : 11000);
    },
    fireworks() {
      const svg = $("#scene");
      if (!svg) return;
      const box = svg.viewBox.baseVal, o = [];
      let seed = 4;
      const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
      SRC.concat(SRC).forEach((k, n) => {
        const x = box.width * (0.45 + rnd() * 0.5), y = 60 + rnd() * 260, d = (n * 0.45).toFixed(2);
        for (let j = 0; j < 12; j++) {
          const a = j / 12 * 2 * Math.PI, r = 50 + rnd() * 30;
          o.push(`<circle class="e-spark" cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="3.2" fill="var(--s-${k})" style="--dx:${(Math.cos(a) * r).toFixed(0)}px;--dy:${(Math.sin(a) * r).toFixed(0)}px;animation-delay:${d}s"/>`);
        }
      });
      const g = el("g", { class: "e-fire" });
      g.innerHTML = o.join("");
      svg.appendChild(g);
      document.body.classList.add("party");
      toast("<b>ΧΑΙΡΕ!</b> (Greek for hello.) Seven sources, seven colors.", 6500);
      setTimeout(() => { g.remove(); document.body.classList.remove("party"); }, reduce() ? 2000 : 9000);
    },
    typed(q) {
      if (q.trim().toLowerCase() !== "pliny") return;
      $(".hero").classList.add("plinian");
      setTimeout(() => $(".hero").classList.remove("plinian"), 9000);
      toast('<i>"Nubes... oriebatur, cuius similitudinem et formam non alia magis arbor quam pinus expresserit."</i> No tree shows the shape of the cloud over Vesuvius better than a pine: Pliny the Younger, Letters 6.16.', 9000);
    },
  };
  $("#scene").addEventListener("click", (e) => { if (e.target.closest(".vhit")) egg.erupt(); });
  const KONAMI = ["ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a"];
  let kpos = 0;
  document.addEventListener("keydown", (e) => {
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    kpos = k === KONAMI[kpos] ? kpos + 1 : (k === KONAMI[0] ? 1 : 0);
    if (kpos === KONAMI.length) { kpos = 0; egg.fireworks(); }
  });

  /* ------------------------------------------------------------ start */
  const startTab = (location.hash || "#radar").slice(1);
  renderViews(); renderLookback();
  selectTab(["radar", "briefing", "sources", "connect", "how"].includes(startTab) ? startTab : "radar");
  loadConfig().catch(() => { /* the page still works without it */ });
  drawScene();
  load().catch(fail);
  pollSources();
  // A public helper for people driving the page from the console or a test.
  window.vesuviusRadar = { state: () => JSON.parse(JSON.stringify(S.f)), set: (f) => { Object.assign(S.f, f); renderViews(); renderLookback(); return load(); },
    erupt: () => egg.erupt(), fireworks: () => egg.fireworks() };
})();
