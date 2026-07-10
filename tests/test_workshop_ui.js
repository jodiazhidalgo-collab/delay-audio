const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const projectRoot = path.resolve(__dirname, "..");
const source = fs.readFileSync(
  path.join(projectRoot, "app", "web", "static", "js", "delay_audio.js"),
  "utf8"
);

function element() {
  const classList = {
    add() {},
    remove() {},
    toggle() {},
    contains() { return false; }
  };
  return {
    classList,
    addEventListener() {},
    setAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return { classList }; },
    textContent: "",
    innerHTML: "",
    disabled: false
  };
}

function createHarness() {
  const values = new Map([
    ["delay-audio-active-tab", "taller"]
  ]);
  const localStorage = {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); }
  };
  const elements = {
    folders: element(),
    statusText: element(),
    refreshButton: element(),
    headerWorkshopCluster: element()
  };
  const document = {
    hidden: false,
    activeElement: null,
    body: { appendChild() {} },
    getElementById(id) { return elements[id] || null; },
    createElement() { return element(); },
    addEventListener() {}
  };
  const never = new Promise(() => {});
  const context = {
    console,
    document,
    localStorage,
    URLSearchParams,
    CSS: { escape: (value) => String(value) },
    fetch: () => never,
    setInterval: () => ({ timer: true }),
    clearInterval() {},
    setTimeout: () => ({ timer: true }),
    clearTimeout() {},
    window: {
      DelayAudioConfig: {},
      setInterval: () => ({ timer: true }),
      clearInterval() {},
      setTimeout: () => ({ timer: true }),
      clearTimeout() {}
    }
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "delay_audio.js" });
  return {
    context,
    elements,
    getState() {
      return JSON.parse(localStorage.getItem("delay-audio-workshop-state") || "{}");
    },
    setState(state) {
      localStorage.setItem("delay-audio-workshop-state", JSON.stringify(state));
    },
    evaluate(code) {
      return vm.runInContext(code, context);
    }
  };
}

function response(data, ok = true) {
  return { ok, status: ok ? 200 : 500, async json() { return data; } };
}

async function main() {
  const harness = createHarness();

  harness.setState({
    status: "done",
    requested_mode: "medir",
    result: {
      ok: true,
      delay_ms: 96540,
      confidence: "MEDIA",
      zones_count: 1,
      avg_score: 0.4883274785,
      profile: "pelicula"
    },
    rows: [{
      zona: "6",
      inicio: "00:12:00",
      delay: "96540",
      confianza: "MEDIA",
      pista_video: "0:1",
      pista_espanol: "0:2"
    }]
  });
  const legacyHtml = harness.evaluate("renderWorkshopResult(readWorkshopState())");
  assert.match(legacyHtml, /96540 ms/);
  assert.match(legacyHtml, /MEDIA/);
  assert.match(legacyHtml, /00:12:00/);
  assert.doesNotMatch(legacyHtml, /Resultado híbrido/);

  harness.setState({
    status: "running",
    job: "job-overlap",
    rows: [],
    result: null
  });
  harness.evaluate("workshopPollGeneration = 10; workshopPollInFlight = 0; workshopTimer = null");
  let overlapCalls = 0;
  let releaseOverlap;
  const overlapResponse = new Promise((resolve) => { releaseOverlap = resolve; });
  harness.context.fetch = () => {
    overlapCalls += 1;
    return overlapResponse;
  };
  const firstPoll = harness.evaluate('pollWorkshopJob(10, "job-overlap")');
  await harness.evaluate('pollWorkshopJob(10, "job-overlap")');
  assert.equal(overlapCalls, 1);
  releaseOverlap(response({
    ok: true,
    job: "job-overlap",
    status: "running",
    rows: [],
    result: null,
    progress: { phase: "measure", percent: 10 }
  }));
  await firstPoll;

  harness.setState({ status: "running", job: "job-old", rows: [], result: null });
  harness.evaluate("workshopPollGeneration = 20; workshopPollInFlight = 0; workshopTimer = null");
  let releaseOld;
  const oldResponse = new Promise((resolve) => { releaseOld = resolve; });
  harness.context.fetch = () => oldResponse;
  const oldPoll = harness.evaluate('pollWorkshopJob(20, "job-old")');
  harness.setState({ status: "running", job: "job-new", rows: [], result: null });
  harness.evaluate("workshopPollGeneration = 21");
  releaseOld(response({
    ok: true,
    job: "job-old",
    status: "done",
    result: { ok: true, delay_ms: 9999, confidence: "ALTA" }
  }));
  await oldPoll;
  assert.equal(harness.getState().job, "job-new");
  assert.equal(harness.getState().status, "running");

  harness.setState({ status: "running", job: "job-missing", rows: [], result: null });
  harness.evaluate("workshopPollGeneration = 30; workshopPollInFlight = 0; workshopTimer = null");
  harness.context.fetch = async () => response({ ok: false, error: "No encuentro ese trabajo." });
  await harness.evaluate('pollWorkshopJob(30, "job-missing")');
  assert.equal(harness.getState().status, "error");
  assert.match(harness.getState().result.error, /ya no está disponible/);

  const requests = [];
  harness.setState({
    status: "done",
    job: "job-terminado",
    result: { ok: true, delay_ms: 1234, confidence: "MEDIA" },
    rows: [{ zona: "1" }],
    ref: { path: "ref.mkv", audio: 1, metadata: {} },
    esp: { path: "esp.mkv", audio: 2, metadata: {} },
    settings: { modo: "medir", perfil: "pelicula", carpeta_salida: "/out" }
  });
  harness.evaluate("workshopPollGeneration = 40; workshopPollInFlight = 0; workshopTimer = null");
  harness.context.fetch = async (url) => {
    requests.push(String(url));
    if (String(url).includes("delay_audio_save_settings")) {
      return response({ ok: true, settings: { modo: "medir", perfil: "pelicula", carpeta_salida: "/out" } });
    }
    if (String(url).includes("delay_audio_start")) {
      return response({ ok: true, job: "job-relanzado", status: "running", requested_mode: "medir" });
    }
    return response({
      ok: true,
      job: "job-relanzado",
      status: "running",
      rows: [],
      result: null,
      progress: { phase: "measure", percent: 0 }
    });
  };
  await harness.evaluate("runWorkshop()");
  await Promise.resolve();
  assert.equal(harness.getState().job, "job-relanzado");
  assert.equal(harness.getState().status, "running");
  assert.equal(harness.getState().result, null);
  assert.equal(requests.filter((url) => url.includes("delay_audio_start")).length, 1);
  assert.equal(requests.some((url) => url.includes("job=job-terminado")), false);

  const baseSlot = { path: "ref.mkv", name: "Ref", audio: 0, duration: "01:40:00", fps: "24.000" };
  harness.setState({
    status: "done",
    ref: baseSlot,
    esp: { ...baseSlot, path: "esp.mkv", duration: "01:42:00" },
    delayHintMs: 16000,
    settings: { modo: "medir", perfil: "pelicula" },
    result: { state: "OK_VERIFICADO", export_allowed: true, delay_ms: 16000 }
  });
  const verifiedHtml = harness.evaluate("renderWorkshopSlot('ref', readWorkshopState().ref, workshopMetaAlerts(readWorkshopState()))");
  assert.match(verifiedHtml, /is-duration-warning/);
  assert.doesNotMatch(verifiedHtml, /is-duration-help-red|is-help-red/);
  assert.doesNotMatch(verifiedHtml, /Ayuda recomendada|Ayuda muy recomendable/);
  assert.match(verifiedHtml, /<span>Editar<\/span><\/button>/);

  harness.setState({
    status: "done",
    ref: baseSlot,
    esp: { ...baseSlot, path: "esp.mkv", duration: "01:42:00" },
    delayHintMs: 0,
    settings: { modo: "medir", perfil: "pelicula" },
    result: {
      state: "NO_FIABLE",
      export_allowed: false,
      decision: { reason: "descubrimiento_sin_evidencia_suficiente" }
    }
  });
  const helpableFailureHtml = harness.evaluate("renderWorkshopSlot('ref', readWorkshopState().ref, workshopMetaAlerts(readWorkshopState()))");
  assert.match(helpableFailureHtml, /workshop-edit is-help-red/);
  assert.match(helpableFailureHtml, /is-duration-help-red/);
  assert.doesNotMatch(helpableFailureHtml, /Ayuda recomendada|Ayuda muy recomendable|<small>/);
  assert.match(helpableFailureHtml, /<span>Editar<\/span><\/button>/);

  harness.setState({
    status: "done",
    ref: baseSlot,
    esp: { ...baseSlot, path: "esp.mkv", duration: "01:42:00" },
    delayHintMs: 16000,
    settings: { modo: "medir", perfil: "pelicula" },
    result: {
      state: "MONTAJE_DISTINTO",
      export_allowed: false,
      decision: { reason: "ningun_delay_fijo_explica_las_zonas" }
    }
  });
  const montageHtml = harness.evaluate("renderWorkshopSlot('ref', readWorkshopState().ref, workshopMetaAlerts(readWorkshopState()))");
  assert.match(montageHtml, /is-duration-warning/);
  assert.doesNotMatch(montageHtml, /is-duration-help-red|is-help-red/);

  harness.setState({
    status: "running",
    ref: baseSlot,
    esp: { ...baseSlot, path: "esp.mkv", duration: "01:42:00" },
    settings: { modo: "medir", perfil: "pelicula" },
    result: {
      state: "NO_FIABLE",
      export_allowed: false,
      decision: { reason: "descubrimiento_sin_evidencia_suficiente" }
    }
  });
  const runningHtml = harness.evaluate("renderWorkshopSlot('ref', readWorkshopState().ref, workshopMetaAlerts(readWorkshopState()))");
  assert.match(runningHtml, /is-duration-warning/);
  assert.doesNotMatch(runningHtml, /is-duration-help-red|is-help-red/);
  assert.doesNotMatch(source, /Ayuda visual aplicada|Ayuda visual limpia|Ayuda recomendada|Ayuda muy recomendable/);

  const hybridEvidenceHtml = harness.evaluate(`renderWorkshopHybridEvidence(
    { requested_mode: "medir" },
    {
      state: "OK_VERIFICADO",
      delay_ms: 800,
      export_allowed: true,
      visual: { verified: true, zones_valid: 3 },
      audio: { supporting_zones: 3 },
      fps_correction: { planned: true, confirmed: true, applied: true },
      measurement_core: { start_sec: 120, end_sec: 5280, span_sec: 5160 },
      edit_hint: { hint_used: true, hint_helped_fast_path: true },
      decision: { reason: "ok", contradictions: [] }
    },
    hybridWorkshopResultInfo({ state: "OK_VERIFICADO" })
  )`);
  assert.match(hybridEvidenceHtml, /Zona útil/);
  assert.match(hybridEvidenceHtml, /Aceleró fast path/);

  let previewRequest = "";
  harness.setState({
    ref: { ...baseSlot, path: "ref.mkv" },
    esp: { ...baseSlot, path: "esp.mkv" },
    delayHintMs: 2000,
    settings: { modo: "medir", perfil: "trailer" }
  });
  harness.context.fetch = async (url) => {
    previewRequest = String(url);
    return response({
      ok: true,
      ref_url: "/preview/x/ref.mp4",
      esp_url: "/preview/x/esp.mp4",
      profile: "trailer",
      delay_hint_ms: 2000,
      window_sec: 4,
      relative_max_offset_ms: 8000,
      max_offset_ms: 60000
    });
  };
  await harness.evaluate("openWorkshopPreview()");
  assert.match(previewRequest, /profile=trailer/);
  assert.match(previewRequest, /delay_hint_ms=2000/);
  const mappedPreviewTimes = JSON.parse(harness.evaluate(`JSON.stringify((() => {
    workshopPreviewHintMs = 5000;
    return workshopPreviewTargetTimes(0);
  })())`));
  assert.deepEqual(mappedPreviewTimes, { ref: 3, esp: 0 });

  console.log("workshop_ui: 10 casos OK");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
