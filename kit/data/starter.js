/* Scrolls Starter. Everything here runs locally, with no network or command execution. */
(function () {
  "use strict";
  function positive(value, label) {
    const n = Number(value);
    if (!String(value).trim() || !Number.isFinite(n) || n <= 0) throw Error(label + " must be a positive number.");
    return n;
  }
  function pathValue(value, label) {
    const text = String(value || "").trim();
    if (!text || /[\x00-\x1f\x7f]/.test(text)) throw Error("Enter " + label + " without line breaks or control characters.");
    return text.startsWith("-") ? "./" + text : text;
  }
  function shellCommand(argv, shell) {
    if (shell === "powershell") return "& " + argv.map(v => "'" + String(v).replace(/'/g, "''") + "'").join(" ");
    return argv.map(v => "'" + String(v).replace(/'/g, "'\"'\"'") + "'").join(" ");
  }
  function pythonFor(report, shell) {
    return report.portable ? (shell === "powershell" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python") : report.executable;
  }
  function pathKey(value, windows) {
    const path = windows ? value.replace(/\\/g, "/").toLowerCase() : value;
    const parts = [];
    path.split("/").forEach(part => {
      if (part === "." || part === "") return;
      if (part === ".." && parts.length && parts[parts.length - 1] !== "..") parts.pop();
      else parts.push(part);
    });
    return (path.startsWith("/") ? "/" : "") + parts.join("/");
  }
  function readerCommand(form, report) {
    const input = pathValue(form.image, "the full image path");
    const output = pathValue(form.output, "a new output prefix");
    const backend = form.backend;
    if (!["linenet", "tesseract"].includes(backend)) throw Error("Choose a supported reader.");
    const language = backend === "linenet" ? "grc" : pathValue(form.language, "an installed language code");
    if (!/^[A-Za-z][A-Za-z0-9_]*(\+[A-Za-z][A-Za-z0-9_]*)*$/.test(language) || language.split("+").includes("osd")) {
      throw Error("Use recognition language codes such as eng, lat or grc, joined with + if needed.");
    }
    if (new Set(language.split("+")).size !== language.split("+").length) throw Error("Language codes must not repeat.");
    const python = pythonFor(report, form.shell);
    const argv = [python, "-m", "kit", "letterread", input.startsWith("-") ? "./" + input : input, "--backend", backend, "--language", language];
    if (backend === "linenet") {
      if (!["letters-v2-ccby", "letters-v2-real", "local"].includes(form.weights)) throw Error("Choose reader weights.");
      const weights = form.weights === "local" ? pathValue(form.localWeights, "the weights file path") : form.weights;
      if (form.weights === "local" && !weights.toLowerCase().endsWith(".npz")) throw Error("Local weights must name a .npz checkpoint file, not a released model name.");
      argv.push("--weights", weights);
      if (form.scale === "mm") {
        const mm = positive(form.mm, "Letter height"), um = positive(form.um, "Pixel size");
        if (!Number.isFinite(mm * 1000 / um) || mm * 1000 / um < 4) throw Error("That scale must give a finite letter height of at least 4 pixels. Check the image resolution and units.");
        argv.push("--letter-mm", String(mm), "--um-per-px", String(um));
      } else {
        const px = positive(form.px, "Letter height");
        if (px < 4) throw Error("Letter height must be at least 4 image pixels.");
        argv.push("--letter-px", String(px));
      }
      if (form.lines.trim()) {
        const lines = form.lines.trim().split(/[\s,]+/).map(Number);
        if (lines.some(n => !Number.isFinite(n) || n < 0)) throw Error("Line centers must be nonnegative row numbers.");
        argv.push("--lines", ...lines.map(String));
      }
    }
    if (!["bright", "dark", "auto"].includes(form.polarity)) throw Error("Choose the ink polarity.");
    argv.push("--polarity", form.polarity);
    if (form.control.trim()) argv.push("--control", pathValue(form.control, "the control image path"));
    const outputs = [output + ".json"];
    argv.push("--out", outputs[0]);
    if (backend === "linenet" && form.overlay) { outputs.push(output + "-overlay.png"); argv.push("--overlay", outputs[outputs.length - 1]); }
    if (backend === "linenet" && form.csv) { outputs.push(output + ".csv"); argv.push("--csv", outputs[outputs.length - 1]); }
    const windows = form.shell === "powershell";
    const protectedInputs = [input, form.control.trim()];
    if (backend === "linenet" && form.weights === "local") protectedInputs.push(pathValue(form.localWeights, "the weights file path"));
    if (outputs.some(out => protectedInputs.some(src => pathKey(out, windows) === pathKey(src, windows)))) throw Error("An output would replace an input. Choose a different output prefix.");
    return {argv, outputs, command: shellCommand(argv, form.shell)};
  }
  const glyphs = ["11111/00100/00100/00100/00100/00100/11111", "10001/11001/11001/10101/10011/10011/10001", "10001/10010/10100/11000/10100/10010/10001"];
  function practice(noise, threshold, contaminated) {
    let seed = 1701;
    function random() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; }
    const width = 23, height = 11, truth = Array(width * height).fill(false);
    glyphs.forEach((g, k) => g.split("/").forEach((row, y) => Array.from(row).forEach((v, x) => {
      truth[(y + 2) * width + x + 2 + k * 7] = v === "1";
    })));
    const signal = truth.map(t => t ? 1 - random() * noise : random() * noise);
    const control = truth.map(t => contaminated && t ? 1 - random() * noise : random() * noise);
    const mask = signal.map(v => v >= threshold), nullMask = control.map(v => v >= threshold);
    const total = truth.filter(Boolean).length, kept = mask.filter(Boolean).length;
    const tp = mask.filter((v, i) => v && truth[i]).length, fp = kept - tp;
    const nullKept = nullMask.filter(Boolean).length;
    const precision = kept ? tp / kept : 0, recall = tp / total;
    return {width, height, truth, signal, control, mask, nullMask, tp, fp, total, kept, nullKept, precision, recall,
      pass: precision >= 0.9 && recall >= 0.8 && nullKept <= total * 0.1};
  }
  const api = {readerCommand, shellCommand, practice};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;
  window.ScrollsStarter = api;
  const report = JSON.parse(document.getElementById("setup-data").textContent);
  const $ = id => document.getElementById(id);
  const text = (id, value) => { $(id).textContent = value; };
  text("checked-at", report.portable ? "Portable edition: setup has not been checked. Install Scrolls Starter, then run scrolls-start --check or open it normally for a real snapshot." : "Checked " + report.checked_at + ". Reopen Scrolls Starter after installing anything.");
  text("python-info", report.portable ? "No Python needed for this page. Reader commands require the separate installation in Start Here." : "Python " + report.python + " on " + report.system + "; Scrolls " + report.version);
  text("python-path", report.portable ? "Not checked. Commands use .venv in the current folder, matching Start Here's scrolls-learning folder." : report.executable);
  const rows = $("packages");
  report.packages.forEach(p => {
    const li = document.createElement("li");
    li.textContent = p.name + ": " + (p.available ? "import passed (" + p.version + ")" : "needs attention: " + p.detail);
    rows.append(li);
  });
  text("environment-note", report.virtual_environment ? "A virtual environment is active." : "Use a separate virtual environment before adding reader packages; see Start Here. This practice page already works.");
  text("tools-info", report.portable ? "Local packages, weights, language packs and official tool requirements have not been checked." : Object.entries(report.tools).map(([k, v]) => k + ": " + (v ? "on PATH" : "not on PATH")).join("; ") + ". These are optional for this introduction; presence is not a complete official workflow check.");
  const defaultShell = report.system === "Windows" ? "powershell" : "posix";
  $("shell").value = defaultShell;
  const installPython = report.virtual_environment ? report.executable : (defaultShell === "powershell" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python");
  text("install-command", shellCommand([installPython, "-m", "pip", "install", "numpy", "pillow", "tifffile", "imagecodecs"], defaultShell));
  text("weights-info", report.weights.map(w => w.name + ": " + w.state + " (" + w.license + ")").join("; "));
  const tess = report.tesseract;
  text("tesseract-info", tess.available ? tess.version + ". Installed languages: " + (tess.languages.map(l => l.code).join(", ") || "none") : "Tesseract unavailable: " + tess.reason);
  function draw(id, values, mask, truth) {
    const canvas = $(id), ctx = canvas.getContext("2d"), size = 16;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    values.forEach((v, i) => {
      const x = (i % 23) * size, y = Math.floor(i / 23) * size, c = Math.round(v * 255);
      ctx.fillStyle = "rgb(" + c + "," + c + "," + c + ")";
      ctx.fillRect(x, y, size, size);
      if (mask[i]) { ctx.fillStyle = "rgba(12,180,156,.65)"; ctx.fillRect(x, y, size, size); }
      if ($("truth").checked && truth[i]) { ctx.strokeStyle = "#ffcc5c"; ctx.lineWidth = 2; ctx.strokeRect(x + 1, y + 1, size - 2, size - 2); }
    });
  }
  function updatePractice() {
    const noise = Number($("noise").value) / 100, threshold = Number($("threshold").value) / 100;
    const p = practice(noise, threshold, $("contaminated").checked);
    text("noise-value", $("noise").value + "%"); text("threshold-value", $("threshold").value + "%");
    draw("signal", p.signal, p.mask, p.truth); draw("control-canvas", p.control, p.nullMask, Array(p.truth.length).fill(false));
    text("practice-result", (p.pass ? "PRACTICE PASS" : "PRACTICE FAIL") + ": " + p.tp + "/" + p.total + " drawn ink pixels kept, " + p.fp + " extra pixels, " + p.nullKept + " pixels kept in the control.");
    $("practice-result").className = "result " + (p.pass ? "pass" : "fail");
    text("practice-reason", p.pass ? "The drawn shape survives and the control stays quiet. You have demonstrated this fixed toy rule, not a learned reader or scroll result." : "The fixed rule failed. Compare the drawn shape and the control; changing a threshold after seeing a real evaluation would require a new test.");
  }
  ["noise", "threshold", "truth", "contaminated"].forEach(id => $(id).addEventListener("input", updatePractice));
  $("reset-practice").addEventListener("click", () => { $("noise").value = 35; $("threshold").value = 55; $("truth").checked = false; $("contaminated").checked = false; updatePractice(); });
  function fields() {
    const f = {};
    ["image", "output", "backend", "language", "weights", "localWeights", "scale", "mm", "um", "px", "lines", "polarity", "control", "shell"].forEach(k => { f[k] = $(k).value; });
    ["overlay", "csv"].forEach(k => { f[k] = $(k).checked; });
    return f;
  }
  function updateWizard() {
    const f = fields(), greek = f.backend === "linenet";
    const installPython = report.virtual_environment ? report.executable : pythonFor({portable: true}, f.shell);
    text("install-command", shellCommand([installPython, "-m", "pip", "install", "numpy", "pillow", "tifffile", "imagecodecs"], f.shell));
    text("demo-command", shellCommand([pythonFor(report, f.shell), "-m", "kit", "letterdemo", "--weights", "letters-v2-ccby"], f.shell));
    $("greek-fields").hidden = !greek; $("language-fields").hidden = greek;
    $("greek-exports").hidden = !greek;
    $("physical-fields").hidden = f.scale !== "mm"; $("pixel-fields").hidden = f.scale === "mm";
    $("local-weights-field").hidden = f.weights !== "local";
    let needs = report.packages.filter(p => !p.available).map(p => p.name);
    if (!greek && !tess.available) needs.push("Tesseract and its language packs");
    if (!greek && tess.available) {
      const installed = tess.languages.map(l => l.code);
      f.language.split("+").filter(c => !installed.includes(c)).forEach(c => needs.push("language pack " + c));
    }
    text("reader-needs", report.portable ? "Setup not checked. Install the reader's image packages first; Tesseract also needs its engine and selected language packs. No model is included in this portable page." : needs.length ? "Setup needs attention: " + needs.join(", ") + ". You can prepare the command, then complete setup before running it." : "Package imports passed. The reader will validate your files and model when you run the command.");
    text("download-note", greek ? (f.weights === "local" ? "Local weights: no weight download. Use a trusted compatible checkpoint." : "Running this command may download about 6 MB of weights once and verify their SHA-256. " + (f.weights === "letters-v2-real" ? "These weights are CC BY-NC 4.0 (noncommercial)." : "These weights are CC BY 4.0.")) : "Tesseract uses installed language packs and does not download them. Its word confidence is not a probability or measured scroll accuracy.");
    try {
      const result = readerCommand(f, report);
      text("reader-command", result.command);
      text("command-status", "Ready to copy. This page has not checked whether your image or output paths exist. Use a new output prefix: the reader can overwrite existing outputs.");
      text("expected-files", "Expected files: " + result.outputs.join(", ") + ". These contain model hypotheses and control results, not a verified transcription.");
      $("copy-command").disabled = false;
    } catch (err) {
      text("reader-command", "Complete the fields above to prepare your command."); text("command-status", err.message); text("expected-files", ""); $("copy-command").disabled = true;
    }
  }
  $("reader-form").addEventListener("input", updateWizard);
  $("reader-form").addEventListener("submit", e => e.preventDefault());
  $("copy-command").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("reader-command").textContent); text("copy-status", "Command copied. Paste it into the selected terminal when ready."); }
    catch (_) { const range = document.createRange(); range.selectNodeContents($("reader-command")); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); text("copy-status", "Command selected. Press Ctrl+C or Command+C to copy."); }
  });
  updatePractice(); updateWizard();
  document.documentElement.dataset.starterReady = "true";
}());
