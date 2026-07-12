const tabsEl = document.getElementById("tabs");
const foldersEl = document.getElementById("folders");
const statusText = document.getElementById("statusText");
const refreshButton = document.getElementById("refreshButton");
const headerWorkshopCluster = document.getElementById("headerWorkshopCluster");
const renameModeButton = document.getElementById("renameModeButton");

const kindLabels = {
  folder: "📁",
  video: "🎬",
  image: "🖼️",
  subtitle: "📄",
  torrent: "🧲",
  json: "📄",
  file: "📄"
};

const activeTabStorageKey = "delay-audio-active-tab";
const qbitDefaultVisible = 8;
const qbitShowAllPrefix = "delay-audio-qbit-show-all";
const watchCardPrefix = "delay-audio-watch-card";
const freshCardSeconds = 3600;
let activeTab = readSavedActiveTab() || "movies";
let lastData = null;
let qbitDeleteInProgress = false;
const openFolderDetails = new Set();
const openTextDetails = new Set();
const folderChildrenCache = new Map();
const loadingFolderDetails = new Set();
const selectedQbitHashes = new Set();
const watchCardActivity = new Map();
const autoOpenedWatchCards = new Map();
const manuallyClosedWatchCards = new Set();
const autoOpenNewFolderCardIds = new Set(["complete_movies", "movies_automatizacion", "complete_tv"]);
const searchableFolderIds = new Set(["media_movies", "media_tv"]);
const mediaSearchState = new Map();
const moveHintItems = ["&#128193;", "&#128196;", "&#127916;"];
const titleHintItems = [
  "&#128193; Abrir Carpeta",
  "&#127916;&#127925; Delay Audio",
  "&#127916;&#127925; Editar Idioma ES",
  "&#127916;&#127925; Convertir AC-3 5.1",
  "&#127916;&#128221; Borrar Subtitulo",
  "&#128196; TXT Ver texto"
];
let cardHintIndex = 0;
let cardHintTimer = null;
let openFolderRefreshInProgress = false;
let statusLoadInProgress = false;
let arrWorkersBusy = false;
let actionModalItem = null;
let itemActionBusy = false;
let itemActionError = "";
let deleteConfirmMode = false;
let customMoveState = {
  open: false,
  loading: false,
  error: "",
  parts: [],
  items: [],
  path: ""
};
let renameModeActive = false;
let renameModalItem = null;
let renameBusy = false;
let renameError = "";
let renameInputValue = "";
let trailerModalItem = null;
let trailerModalInfo = null;
let trailerModalLoading = false;
let trailerActionBusy = false;
let trailerModalError = "";
let trailerModalStatus = "";
let trailerVideoSelection = "";
let trailerSubtitleSelection = new Set();
let trailerAudioSelection = "";
let trailerBusyMode = "";
const workshopStorageKey = "delay-audio-workshop-state";
const trailerJobStorageKey = "delay-audio-trailer-job-state";
const delayAudioConfig = window.DelayAudioConfig || {};
const mediaRootPath = delayAudioConfig.mediaRootPath || "/media";
const queueMoviesPath = delayAudioConfig.queueMoviesPath || "/data/downloads/torrents/queue/movies";
const completeMoviesPath = delayAudioConfig.completeMoviesPath || "/data/downloads/torrents/complete/movies";
const hospitalPath = delayAudioConfig.hospitalPath || `${mediaRootPath}/Hospital`;
let workshopBusy = false;
let workshopTimer = null;
let workshopPollGeneration = 0;
let workshopPollRequestId = 0;
let workshopPollInFlight = 0;
let trailerJobTimer = null;
let workshopOutputModalOpen = false;
let workshopSettingsLoaded = false;
let workshopSettingsLoading = false;
let workshopSaveStatus = "";
let workshopSaveTimer = null;
let workshopSaveDebounce = null;
let workshopSavePromise = null;
let workshopPreviewModalOpen = false;
let workshopPreviewLoading = false;
let workshopPreviewError = "";
let workshopPreviewData = null;
let workshopPreviewHintMs = 0;
let workshopPreviewPlaying = false;
let workshopPreviewTimer = null;

function prepareFinishSound() {
  if (window.DelayAudioSounds && typeof window.DelayAudioSounds.prepare === "function") {
    window.DelayAudioSounds.prepare();
  }
}

function playFinishSound(jobId) {
  if (window.DelayAudioSounds && typeof window.DelayAudioSounds.done === "function") {
    window.DelayAudioSounds.done(jobId);
  }
}

function finishSoundJob(prefix, detail = "") {
  return `${prefix}:${Date.now()}:${detail}`;
}

const workshopDefaultSettings = {
  modo: "exportar",
  perfil: "pelicula",
  confianza_minima: "MEDIA",
  carpeta_salida: completeMoviesPath,
  sub_video_bueno: "INGLES",
  sub_fuente_espanol: "ESPAÑOL delay audio"
};

const workshopOutputPresets = [
  {
    key: "complete_movies",
    label: "Complete Movies",
    path: completeMoviesPath
  },
  {
    key: "hospital",
    label: "Hospital",
    path: hospitalPath
  }
];

function readSavedActiveTab() {
  try {
    return localStorage.getItem(activeTabStorageKey) || "";
  } catch (error) {
    return "";
  }
}

function saveActiveTab(tabId) {
  try {
    localStorage.setItem(activeTabStorageKey, tabId);
  } catch (error) {}
}

function qbitShowAllKey(category) {
  return `${qbitShowAllPrefix}:${category}`;
}

function isQbitShowingAll(category) {
  try {
    return localStorage.getItem(qbitShowAllKey(category)) === "1";
  } catch (error) {
    return false;
  }
}

function setQbitShowingAll(category, showAll) {
  try {
    localStorage.setItem(qbitShowAllKey(category), showAll ? "1" : "0");
  } catch (error) {}
}

function watchCardKey(cardId) {
  return `${watchCardPrefix}:${cardId}`;
}

function isWatchCardCollapsed(cardId) {
  if (autoOpenedWatchCards.has(cardId) && !manuallyClosedWatchCards.has(cardId)) return false;
  try {
    return localStorage.getItem(watchCardKey(cardId)) === "closed";
  } catch (error) {
    return false;
  }
}

function setWatchCardCollapsed(cardId, collapsed) {
  try {
    localStorage.setItem(watchCardKey(cardId), collapsed ? "closed" : "open");
  } catch (error) {}
}

function isFreshCardTimestamp(timestamp) {
  const value = Number(timestamp || 0);
  if (!value) return false;
  return Math.max(0, Date.now() / 1000 - value) < freshCardSeconds;
}

function watchCardHasFreshActivity(cardId) {
  return Boolean(watchCardActivity.get(cardId)?.fresh);
}

function folderActivityDescriptor(folder, sectionId) {
  const cardId = `folder-${sectionId}-${folder.id}`;
  const items = Array.isArray(folder.items) ? folder.items : [];
  const extraSections = Array.isArray(folder.extra_sections) ? folder.extra_sections : [];
  const extraItems = extraSections.flatMap((section) => {
    return (Array.isArray(section.items) ? section.items : []).map((item) => ({
      ...item,
      activityKey: `${section.id || section.label || "extra"}:${item.name || ""}`
    }));
  });
  const rootItems = items.map((item) => ({ ...item, activityKey: `root:${item.name || ""}` }));
  const trackedItems = [...rootItems, ...extraItems];
  const isAutomationCard = folder.id === "movies_automatizacion";
  const count = Number(folder.count || 0) + (isAutomationCard ? extraItems.length : 0);
  return {
    id: cardId,
    folderId: folder.id,
    count,
    keys: new Set(trackedItems.map((item) => item.activityKey)),
    items: trackedItems,
    fresh: trackedItems.some((item) => isFreshCardTimestamp(item.mtime))
  };
}

function autoOpenFolderParts(item) {
  if (Array.isArray(item.parts) && item.parts.length) return item.parts;
  return item.name ? [item.name] : [];
}

function autoOpenNewFolderItems(descriptor, addedKeys) {
  if (!autoOpenNewFolderCardIds.has(descriptor.folderId) || !addedKeys.length) return;
  const added = new Set(addedKeys);
  (Array.isArray(descriptor.items) ? descriptor.items : []).forEach((item) => {
    if (!added.has(item.activityKey)) return;
    if (item.kind !== "folder" || !item.can_expand) return;
    const sourceId = item.children_source || descriptor.folderId;
    const parts = autoOpenFolderParts(item);
    if (!sourceId || !parts.length) return;
    openFolderDetails.add(`${sourceId}::${parts.join("/")}`);
  });
}

function collectWatchCardActivity(data, sectionId) {
  const descriptors = [];
  if (["movies", "tv"].includes(sectionId)) {
    const arrItems = Array.isArray(data.arr_status?.items) ? data.arr_status.items : [];
    descriptors.push({
      id: `realdebrid-${sectionId}`,
      count: Number(data.arr_status?.monitoring || 0),
      keys: new Set(arrItems.map((item) => String(item.id || item.title || ""))),
      fresh: arrItems.some((item) => isFreshCardTimestamp(item.last_progress_ts))
    });

    const qbitItems = Array.isArray(data.qbit_status?.items) ? data.qbit_status.items : [];
    descriptors.push({
      id: `qbit-${sectionId}`,
      count: Number(data.qbit_status?.total || 0),
      keys: new Set(qbitItems.map((item) => String(item.hash || item.name || ""))),
      fresh: qbitItems.some((item) => isFreshCardTimestamp(item.added_on))
    });
  }

  const section = getSections(data).find((item) => item.id === sectionId);
  (section?.folders || []).forEach((folder) => {
    descriptors.push(folderActivityDescriptor(folder, sectionId));
  });
  return descriptors;
}

function updateWatchCardActivity(data, sectionId) {
  collectWatchCardActivity(data, sectionId).forEach((current) => {
    const previous = watchCardActivity.get(current.id);
    const trigger = autoOpenedWatchCards.get(current.id);

    if (trigger) {
      const triggerStillPresent = trigger.keys.size
        ? [...trigger.keys].some((key) => current.keys.has(key))
        : current.count >= trigger.count;
      if (!triggerStillPresent) {
        autoOpenedWatchCards.delete(current.id);
        manuallyClosedWatchCards.delete(current.id);
        setWatchCardCollapsed(current.id, true);
      }
    }

    if (previous) {
      const addedKeys = [...current.keys].filter((key) => !previous.keys.has(key));
      const countIncreased = current.count > previous.count;
      if ((addedKeys.length || countIncreased) && !manuallyClosedWatchCards.has(current.id)) {
        autoOpenedWatchCards.set(current.id, {
          keys: new Set(addedKeys),
          count: current.count
        });
        autoOpenNewFolderItems(current, addedKeys);
      }
    }

    if (!current.fresh) manuallyClosedWatchCards.delete(current.id);
    watchCardActivity.set(current.id, current);
  });
}

function bindWatchCardToggles() {
  foldersEl.querySelectorAll("[data-watch-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const cardId = button.dataset.watchToggle;
      const card = button.closest("[data-watch-card]");
      if (!cardId || !card) return;
      const collapsed = !card.classList.contains("is-collapsed");
      autoOpenedWatchCards.delete(cardId);
      if (collapsed) {
        manuallyClosedWatchCards.add(cardId);
      } else {
        manuallyClosedWatchCards.delete(cardId);
      }
      card.classList.toggle("is-collapsed", collapsed);
      card.querySelectorAll(`[data-watch-toggle="${CSS.escape(cardId)}"]`).forEach((toggle) => {
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      });
      setWatchCardCollapsed(cardId, collapsed);
    });
  });
}

function bindQbitActions() {
  foldersEl.querySelectorAll("[data-qbit-select]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const hash = checkbox.dataset.qbitSelect;
      if (!hash) return;
      if (checkbox.checked) {
        selectedQbitHashes.add(hash);
      } else {
        selectedQbitHashes.delete(hash);
      }
      render(lastData);
    });
  });

  foldersEl.querySelectorAll("[data-qbit-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteSelectedQbit(button.dataset.qbitDelete));
  });

  foldersEl.querySelectorAll("[data-qbit-show-all]").forEach((button) => {
    button.addEventListener("click", () => {
      const category = button.dataset.qbitShowAll;
      if (!category) return;
      setQbitShowingAll(category, !isQbitShowingAll(category));
      selectedQbitHashes.clear();
      render(lastData);
    });
  });
}

function getMediaSearch(folderId) {
  if (!mediaSearchState.has(folderId)) {
    mediaSearchState.set(folderId, {
      open: false,
      query: "",
      items: [],
      count: 0,
      loading: false,
      error: "",
      timer: null
    });
  }
  return mediaSearchState.get(folderId);
}

function clearMediaSearch(folderId, options = {}) {
  if (!searchableFolderIds.has(folderId)) return;
  const state = getMediaSearch(folderId);
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
  state.query = "";
  state.items = [];
  state.count = 0;
  state.loading = false;
  state.error = "";
  if (options.close) state.open = false;
}

function clearSearchForSource(sourceId) {
  if (!sourceId) return;
  clearMediaSearch(sourceId, { close: true });
}

function hasActiveSearch(sourceId) {
  if (!searchableFolderIds.has(sourceId)) return false;
  const state = getMediaSearch(sourceId);
  return Boolean(state.open || state.query);
}

function anyMediaSearchOpen() {
  return [...searchableFolderIds].some((folderId) => {
    const state = getMediaSearch(folderId);
    return Boolean(state.open || state.query);
  }) || Boolean(document.activeElement?.matches?.("[data-media-search-input]"));
}

function plural(count) {
  return count === 1 ? "1 elemento" : `${count} elementos`;
}

function ago(timestamp) {
  if (!timestamp) return "Sin cambios";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
  if (seconds < 60) return `hace ${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  const days = Math.round(hours / 24);
  return `hace ${days} d`;
}

function compactAge(timestamp) {
  if (!timestamp) return "";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const restSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${restSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  if (hours < 24) return `${hours}h ${restMinutes}m`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `${days}d ${restHours}h` : `${days}d`;
}

function latestTimestamp(items, key) {
  if (!Array.isArray(items)) return 0;
  return items.reduce((latest, item) => {
    const value = Number(item?.[key] || 0);
    return value > latest ? value : latest;
  }, 0);
}

function realDebridCompactText(items) {
  const latest = latestTimestamp(items, "last_progress_ts");
  return latest ? `Ultima actividad: hace ${compactAge(latest)}` : "Sin actividad reciente";
}

function qbitCompactText(items) {
  const dayAgo = Date.now() / 1000 - 86400;
  const latest = latestTimestamp(
    Array.isArray(items) ? items.filter((item) => Number(item?.added_on || 0) >= dayAgo) : [],
    "added_on"
  );
  return latest ? `Ultima entrada 24h: hace ${compactAge(latest)}` : "Sin entradas en 24h";
}

function pct(value) {
  const number = Number(value || 0);
  return `${Math.max(0, Math.min(100, Math.round(number)))}%`;
}

function qbitPct(value) {
  const number = Math.max(0, Math.min(100, Number(value || 0)));
  if (!Number.isFinite(number)) return "0%";
  let rounded = Math.round(number * 10) / 10;
  if (rounded >= 100 && number < 100) rounded = 99.9;
  return Number.isInteger(rounded) ? `${rounded}%` : `${rounded.toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function makeActionTarget(sourceId, parts, kind = "file") {
  const cleanParts = Array.isArray(parts) ? parts.filter((part) => String(part || "").trim()) : [];
  if (!sourceId || !cleanParts.length) return null;
  return {
    source: String(sourceId),
    parts: cleanParts.map((part) => String(part)),
    kind
  };
}

function freshnessClass(timestamp) {
  if (!timestamp) return "";
  const seconds = Math.max(0, Date.now() / 1000 - Number(timestamp || 0));
  if (seconds < 3600) return " item-name-fresh-new";
  if (seconds < 86400) return " item-name-fresh-day";
  return "";
}

function renderItemName(name, target, timestamp = 0) {
  const freshClass = freshnessClass(timestamp);
  if (!target?.source || !Array.isArray(target.parts) || !target.parts.length) {
    return `<span class="item-name${freshClass}" title="${escapeHtml(name)}">${escapeHtml(name)}</span>`;
  }

  return `
    <button
      class="item-name item-name-action${freshClass}"
      type="button"
      title="${escapeHtml(name)}"
      data-item-action
      data-item-source="${escapeHtml(target.source)}"
      data-item-parts="${escapeHtml(JSON.stringify(target.parts))}"
      data-item-name="${escapeHtml(name)}"
      data-item-kind="${escapeHtml(target.kind || "file")}"
      data-item-mode="full"
    >${escapeHtml(name)}</button>
  `;
}

function renderStaticItemName(name, timestamp = 0) {
  return `<span class="item-name${freshnessClass(timestamp)}" title="${escapeHtml(name)}">${escapeHtml(name)}</span>`;
}

function renderItemActionIcon(name, target, kind = "file") {
  const label = kindLabels[kind] || kindLabels.file;
  if (!target?.source || !Array.isArray(target.parts) || !target.parts.length) {
    return `<span class="item-chip ${kind}-icon" aria-hidden="true">${label}</span>`;
  }
  if (renameModeActive) {
    return `
      <button
        class="item-chip icon-toggle rename-icon"
        type="button"
        data-item-rename
        data-item-source="${escapeHtml(target.source)}"
        data-item-parts="${escapeHtml(JSON.stringify(target.parts))}"
        data-item-name="${escapeHtml(name)}"
        data-item-kind="${escapeHtml(target.kind || kind)}"
        aria-label="Renombrar"
      >&#9998;</button>
    `;
  }
  return `
    <button
      class="item-chip icon-toggle ${kind}-icon"
      type="button"
      data-item-action
      data-item-source="${escapeHtml(target.source)}"
      data-item-parts="${escapeHtml(JSON.stringify(target.parts))}"
      data-item-name="${escapeHtml(name)}"
      data-item-kind="${escapeHtml(target.kind || kind)}"
      data-item-mode="move"
      aria-label="Acciones"
    >${label}</button>
  `;
}

function renderFolderToggleName(name, detailId, sourceId, parts, isOpen, timestamp = 0) {
  return `
    <button
      class="item-name item-name-action${freshnessClass(timestamp)}"
      type="button"
      title="${escapeHtml(name)}"
      data-folder-toggle="${escapeHtml(detailId)}"
      data-folder-source="${escapeHtml(sourceId)}"
      data-folder-name="${escapeHtml(parts[parts.length - 1] || name)}"
      data-folder-parts="${escapeHtml(JSON.stringify(parts))}"
      aria-expanded="${isOpen ? "true" : "false"}"
    >${escapeHtml(name)}</button>
  `;
}

function renderTextToggleName(name, detailId, isOpen, sourceId = "", timestamp = 0) {
  return `
    <button
      class="item-name item-name-action${freshnessClass(timestamp)}"
      type="button"
      title="${escapeHtml(name)}"
      data-txt-toggle="${escapeHtml(detailId)}"
      data-txt-source="${escapeHtml(sourceId)}"
      aria-expanded="${isOpen ? "true" : "false"}"
    >${escapeHtml(name)}</button>
  `;
}

function renderItemMeta(item) {
  const parts = [];
  if (["video", "temp"].includes(item.kind || "file") && item.size) {
    parts.push(`<span class="item-size">${escapeHtml(item.size)}</span>`);
  }
  parts.push(`<span class="item-age">${compactAge(item.mtime)}</span>`);
  return `<span class="item-meta">${parts.join(" ")}</span>`;
}

function readWorkshopState() {
  try {
    const state = JSON.parse(localStorage.getItem(workshopStorageKey) || "{}") || {};
    if (state?.settings?.carpeta_salida === queueMoviesPath) {
      state.settings.carpeta_salida = completeMoviesPath;
    }
    return state;
  } catch (error) {
    return {};
  }
}

function saveWorkshopState(state) {
  try {
    localStorage.setItem(workshopStorageKey, JSON.stringify(state || {}));
  } catch (error) {}
}

function readTrailerJobState() {
  try {
    return JSON.parse(localStorage.getItem(trailerJobStorageKey) || "{}") || {};
  } catch (error) {
    return {};
  }
}

function saveTrailerJobState(state) {
  try {
    localStorage.setItem(trailerJobStorageKey, JSON.stringify(state || {}));
  } catch (error) {}
}

function clearTrailerJobState() {
  try {
    localStorage.removeItem(trailerJobStorageKey);
  } catch (error) {}
}

function workshopSettings(state = readWorkshopState()) {
  return {
    ...workshopDefaultSettings,
    ...(state.settings || {}),
    confianza_minima: "MEDIA"
  };
}

function normalizeWorkshopDelayHintMs(value, max = 60000) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  const limit = Math.max(0, Number(max) || 60000);
  return Math.max(-limit, Math.min(limit, Math.round(number)));
}

function workshopDelayHintMs(state = readWorkshopState()) {
  return normalizeWorkshopDelayHintMs(state.delayHintMs || 0);
}

function workshopJobRunning(state = readWorkshopState()) {
  return state?.status === "running" || workshopBusy;
}

function blockWorkshopMutationWhileRunning(state = readWorkshopState()) {
  if (!workshopJobRunning(state)) return false;
  statusText.textContent = "Espera a que termine Taller";
  return true;
}

function formatWorkshopDelayHint(ms) {
  const value = normalizeWorkshopDelayHintMs(ms);
  const sign = value > 0 ? "+" : "";
  return `${sign}${value} ms`;
}

function clearWorkshopResultFields(state) {
  state.status = "";
  state.result = null;
  state.rows = [];
  state.progress = null;
  state.error = "";
  delete state.job;
  delete state.requested_mode;
  delete state.soundJob;
  state.soundDone = false;
}

function outputPresetLabel(path) {
  const preset = workshopOutputPresets.find((item) => item.path === path);
  if (preset) return preset.label;
  return path ? "Personalizada" : "Sin salida";
}

function renderWorkshopOnly() {
  renderHeaderWorkshop();
  if (activeTab === "taller" && lastData) {
    foldersEl.innerHTML = renderWorkshop();
    bindWorkshop();
  }
  resumeWorkshopIfNeeded();
}

function setWorkshopSaveStatus(status) {
  workshopSaveStatus = status || "";
  if (workshopSaveTimer) {
    clearTimeout(workshopSaveTimer);
    workshopSaveTimer = null;
  }
  if (lastData) renderTabs(lastData);
  if (!document.activeElement?.classList?.contains("workshop-input")) {
    renderWorkshopOnly();
  }
  if (status === "saved") {
    workshopSaveTimer = setTimeout(() => {
      workshopSaveStatus = "";
      if (lastData) renderTabs(lastData);
      if (!document.activeElement?.classList?.contains("workshop-input")) {
        renderWorkshopOnly();
      }
    }, 1400);
  }
}

function workshopSaveText() {
  if (workshopSaveStatus === "saving") return "Guardando";
  if (workshopSaveStatus === "saved") return "Guardado";
  if (workshopSaveStatus === "error") return "Error";
  return "Taller";
}

function updateWorkshopSettings(values, saveNow = false, renderUi = true) {
  const state = readWorkshopState();
  if (blockWorkshopMutationWhileRunning(state)) return;
  state.settings = {
    ...workshopSettings(state),
    ...values,
    confianza_minima: "MEDIA"
  };
  saveWorkshopState(state);
  if (renderUi) renderWorkshopOnly();
  queueWorkshopSettingsSave(saveNow ? 0 : 450);
}

function queueWorkshopSettingsSave(delay = 450) {
  if (workshopSaveDebounce) clearTimeout(workshopSaveDebounce);
  setWorkshopSaveStatus("saving");
  workshopSaveDebounce = setTimeout(() => {
    workshopSaveDebounce = null;
    saveWorkshopSettingsNow();
  }, delay);
}

async function saveWorkshopSettingsNow() {
  const settings = workshopSettings();
  const params = new URLSearchParams({
    v: "delay_audio_save_settings",
    da: "save_settings",
    modo: settings.modo || "exportar",
    perfil: settings.perfil || "pelicula",
    confianza_minima: "MEDIA",
    carpeta_salida: settings.carpeta_salida || workshopDefaultSettings.carpeta_salida,
    sub_video_bueno: settings.sub_video_bueno || workshopDefaultSettings.sub_video_bueno,
    sub_fuente_espanol: settings.sub_fuente_espanol || workshopDefaultSettings.sub_fuente_espanol,
    t: String(Date.now())
  });

  workshopSavePromise = fetch(`/api?${params.toString()}`, { cache: "no-store" })
    .then((response) => response.json().then((data) => ({ response, data })))
    .then(({ response, data }) => {
      if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
      const state = readWorkshopState();
      state.settings = {
        ...workshopDefaultSettings,
        ...(data.settings || settings),
        confianza_minima: "MEDIA"
      };
      saveWorkshopState(state);
      setWorkshopSaveStatus("saved");
      return state.settings;
    })
    .catch((error) => {
      setWorkshopSaveStatus("error");
      throw error;
    })
    .finally(() => {
      workshopSavePromise = null;
    });
  return workshopSavePromise;
}

async function flushWorkshopSettingsSave() {
  if (workshopSaveDebounce) {
    clearTimeout(workshopSaveDebounce);
    workshopSaveDebounce = null;
  }
  if (workshopSavePromise) {
    try {
      await workshopSavePromise;
      return;
    } catch (error) {}
  }
  await saveWorkshopSettingsNow();
}

async function ensureWorkshopSettings() {
  if (workshopSettingsLoaded || workshopSettingsLoading) return;
  workshopSettingsLoading = true;
  try {
    const response = await fetch(`/api?v=delay_audio_settings&da=settings&t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    const state = readWorkshopState();
    state.settings = {
      ...workshopDefaultSettings,
      ...(data.settings || {}),
      confianza_minima: "MEDIA"
    };
    saveWorkshopState(state);
    workshopSettingsLoaded = true;
    renderWorkshopOnly();
  } catch (error) {
    const state = readWorkshopState();
    state.settings = workshopSettings(state);
    saveWorkshopState(state);
  } finally {
    workshopSettingsLoading = false;
  }
}

function workshopSlotLabel(kind) {
  return kind === "esp" ? "Audio Español" : "Video Bueno";
}

function workshopSlotKey(kind) {
  return kind === "esp" ? "esp" : "ref";
}

function workshopTrackLabel(track) {
  const parts = [`0:${track.index}`];
  if (track.language) parts.push(String(track.language).toUpperCase());
  if (track.codec) parts.push(String(track.codec).toUpperCase());
  if (track.channels) parts.push(`${track.channels}ch`);
  if (track.title) parts.push(track.title);
  return parts.join(" - ");
}

function defaultWorkshopTrack(kind, streams) {
  if (!Array.isArray(streams) || !streams.length) return "";
  if (kind === "esp") {
    const spanish = streams.find((track) => track.spanish);
    if (spanish) return String(spanish.index);
  }
  return String(streams[0].index);
}

function workshopReady(state) {
  return Boolean(
    state?.ref?.path
    && state?.esp?.path
    && state?.ref?.audio !== undefined
    && state?.ref?.audio !== ""
    && state?.esp?.audio !== undefined
    && state?.esp?.audio !== ""
  );
}

function renderWorkshopTracks(kind, slot) {
  if (!slot?.path) return "";
  if (slot.loading) return `<div class="workshop-muted">Leyendo pistas...</div>`;
  const streams = Array.isArray(slot.streams) ? slot.streams : [];
  if (slot.error) {
    return `
      <div class="workshop-error">${escapeHtml(slot.error)}</div>
      <button class="workshop-mini workshop-reload" type="button" data-workshop-reload-tracks="${escapeHtml(kind)}">Reintentar pistas</button>
    `;
  }
  if (!streams.length) {
    return `
      <div class="workshop-muted">Sin pistas de audio</div>
      <button class="workshop-mini workshop-reload" type="button" data-workshop-reload-tracks="${escapeHtml(kind)}">Leer pistas</button>
    `;
  }

  return `
    <div class="workshop-tracks">
      ${streams.map((track) => {
        const active = String(slot.audio) === String(track.index);
        return `
          <button class="workshop-track ${active ? "is-active" : ""}" type="button" data-workshop-track="${escapeHtml(kind)}" data-workshop-track-value="${escapeHtml(track.index)}">
            <span>${escapeHtml(workshopTrackLabel(track))}</span>
            ${track.spanish ? `<em>ES</em>` : ""}
          </button>
        `;
      }).join("")}
    </div>
  `;
}

function parseWorkshopDurationSeconds(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const parts = text.split(":").map((part) => Number(part));
  if (parts.length === 3 && parts.every(Number.isFinite)) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  if (parts.length === 2 && parts.every(Number.isFinite)) {
    return parts[0] * 60 + parts[1];
  }
  const numeric = Number(text);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeWorkshopFps(value) {
  const match = String(value || "").replace(",", ".").match(/\d+(?:\.\d+)?/);
  if (!match) return "";
  const fps = Number(match[0]);
  return Number.isFinite(fps) && fps > 0 ? fps.toFixed(3) : "";
}

function workshopEditCanHelp(state) {
  if (workshopJobRunning(state)) return false;
  const result = state?.result || {};
  return result.state === "NO_FIABLE"
    && result.export_allowed === false
    && String(result?.decision?.reason || "") === "descubrimiento_sin_evidencia_suficiente";
}

function workshopMetaAlerts(state) {
  const refFps = normalizeWorkshopFps(state?.ref?.fps);
  const espFps = normalizeWorkshopFps(state?.esp?.fps);
  const refDuration = parseWorkshopDurationSeconds(state?.ref?.duration);
  const espDuration = parseWorkshopDurationSeconds(state?.esp?.duration);
  return {
    fpsMismatch: Boolean(refFps && espFps && refFps !== espFps),
    durationWarning: refDuration !== null && espDuration !== null && Math.abs(refDuration - espDuration) > 10,
    editCanHelp: workshopEditCanHelp(state)
  };
}

function workshopMetaClass(type, alerts) {
  if (type === "duration" && alerts?.durationWarning) {
    return alerts?.editCanHelp ? " is-duration-help-red" : " is-duration-warning";
  }
  if (type === "fps" && alerts?.fpsMismatch) return " is-fps-mismatch";
  return "";
}

function renderWorkshopMetaPill(value, type, alerts) {
  if (!value) return "";
  const className = workshopMetaClass(type, alerts).trim();
  return `<span${className ? ` class="${className}"` : ""}>${escapeHtml(value)}</span>`;
}

function renderWorkshopSlot(kind, slot, alerts = {}) {
  const selected = Boolean(slot?.path);
  const label = workshopSlotLabel(kind);
  const editWarningClass = alerts?.editCanHelp ? " is-help-red" : "";
  return `
    <section class="workshop-slot ${selected ? "has-video" : ""}">
      <div class="workshop-slot-head">
        <div>
          <div class="workshop-kicker">${escapeHtml(label)}</div>
          <h2>${selected ? escapeHtml(slot.name || "Video seleccionado") : "Sin seleccionar"}</h2>
        </div>
        ${selected && kind === "esp" ? `<button class="workshop-mini workshop-edit${editWarningClass}" type="button" data-workshop-preview-open><span>Editar</span></button>` : ""}
      </div>
      ${selected ? `
        <div class="workshop-meta">
          ${slot.size ? `<span>${escapeHtml(slot.size)}</span>` : ""}
          ${renderWorkshopMetaPill(slot.duration, "duration", alerts)}
          ${renderWorkshopMetaPill(slot.fps, "fps", alerts)}
        </div>
        ${renderWorkshopTracks(kind, slot)}
      ` : `<div class="workshop-empty">Elige un video desde una tarjeta.</div>`}
    </section>
  `;
}

function renderWorkshopDelayHint(state) {
  const delayHintMs = workshopDelayHintMs(state);
  if (!delayHintMs) return "";
  return `
    <div class="workshop-delay-hint">
      <span>Ayuda visual</span>
      <strong>${escapeHtml(formatWorkshopDelayHint(delayHintMs))}</strong>
      <button type="button" data-workshop-preview-reset-main ${workshopJobRunning(state) ? "disabled" : ""}>0</button>
    </div>
  `;
}

function renderWorkshopSettings(settings, locked = false) {
  const modo = settings.modo === "medir" ? "medir" : "exportar";
  const perfil = settings.perfil === "trailer" ? "trailer" : "pelicula";
  return `
    <section class="workshop-panel">
      <div class="workshop-panel-head">
        <div class="workshop-kicker">Ajustes</div>
        <div class="workshop-save-pill ${workshopSaveStatus ? `is-${escapeHtml(workshopSaveStatus)}` : ""}">
          <span></span>${escapeHtml(workshopSaveText())}
        </div>
      </div>
      <div class="workshop-control-grid">
        <div class="workshop-setting">
          <label>Modo</label>
          <div class="workshop-segment">
            <button class="${modo === "exportar" ? "is-active" : ""}" type="button" data-workshop-setting="modo" data-workshop-value="exportar" ${locked ? "disabled" : ""}>Medir y exportar</button>
            <button class="${modo === "medir" ? "is-active" : ""}" type="button" data-workshop-setting="modo" data-workshop-value="medir" ${locked ? "disabled" : ""}>Solo medir</button>
          </div>
        </div>
        <div class="workshop-setting">
          <label>Tipo</label>
          <div class="workshop-segment">
            <button class="${perfil === "pelicula" ? "is-active" : ""}" type="button" data-workshop-setting="perfil" data-workshop-value="pelicula" ${locked ? "disabled" : ""}>Película</button>
            <button class="${perfil === "trailer" ? "is-active" : ""}" type="button" data-workshop-setting="perfil" data-workshop-value="trailer" ${locked ? "disabled" : ""}>Tráiler</button>
          </div>
        </div>
        <div class="workshop-setting">
          <label>Sub Video Bueno</label>
          <input class="workshop-input" type="text" value="${escapeHtml(settings.sub_video_bueno || "")}" data-workshop-input="sub_video_bueno" autocomplete="off" ${locked ? "disabled" : ""}>
        </div>
        <div class="workshop-setting">
          <label>Sub Audio Español</label>
          <input class="workshop-input" type="text" value="${escapeHtml(settings.sub_fuente_espanol || "")}" data-workshop-input="sub_fuente_espanol" autocomplete="off" ${locked ? "disabled" : ""}>
        </div>
      </div>
      <button class="workshop-output" type="button" data-workshop-output-open ${locked ? "disabled" : ""}>
        <span>Carpeta salida</span>
        <strong>${escapeHtml(outputPresetLabel(settings.carpeta_salida))}</strong>
      </button>
    </section>
  `;
}

function renderWorkshopPreviewModal(state) {
  if (!workshopPreviewModalOpen) return "";
  const ready = Boolean(state.ref?.path && state.esp?.path);
  const canAccept = ready && !workshopJobRunning(state) && !workshopPreviewLoading && !workshopPreviewError && workshopPreviewData?.ref_url && workshopPreviewData?.esp_url;
  const valueText = formatWorkshopDelayHint(workshopPreviewHintMs);
  return `
    <div class="workshop-preview-modal is-open">
      <div class="workshop-preview-sheet" role="dialog" aria-modal="true" aria-labelledby="workshopPreviewTitle">
        <div class="sheet-grip" aria-hidden="true"></div>
        <div class="item-action-head">
          <div class="item-action-title-wrap">
            <div class="item-action-kicker">Ajuste visual</div>
            <h2 id="workshopPreviewTitle">Coincidir imagenes</h2>
          </div>
          <button class="sheet-close" type="button" data-workshop-preview-close aria-label="Cerrar">x</button>
        </div>

        ${!ready ? `<div class="workshop-preview-status is-error">Faltan Video Bueno y Audio Español.</div>` : ""}
        ${workshopPreviewLoading ? `<div class="workshop-preview-status is-working">Preparando preview...</div>` : ""}
        ${workshopPreviewError ? `<div class="workshop-preview-status is-error">${escapeHtml(workshopPreviewError)}</div>` : ""}

        ${workshopPreviewData?.ref_url && workshopPreviewData?.esp_url ? `
          <div class="workshop-preview-videos">
            <div class="workshop-preview-video">
              <span>Video Bueno</span>
              <video muted playsinline preload="auto" data-workshop-preview-video="ref" src="${escapeHtml(workshopPreviewData.ref_url)}"></video>
            </div>
            <div class="workshop-preview-video">
              <span>Audio Español</span>
              <video muted playsinline preload="auto" data-workshop-preview-video="esp" src="${escapeHtml(workshopPreviewData.esp_url)}"></video>
            </div>
          </div>
          <div class="workshop-preview-ruler" data-workshop-preview-ruler>
            <div class="workshop-preview-lane is-esp" aria-label="Desplazamiento del vídeo español"><i></i></div>
          </div>
        ` : ""}

        <div class="workshop-preview-value" data-workshop-preview-value>${escapeHtml(valueText)}</div>
        <div class="workshop-preview-controls">
          <button type="button" data-workshop-preview-play ${canAccept ? "" : "disabled"}>Play</button>
          <button type="button" data-workshop-preview-step="-1000" ${canAccept ? "" : "disabled"}>-</button>
          <button type="button" data-workshop-preview-step="1000" ${canAccept ? "" : "disabled"}>+</button>
        </div>
        <div class="workshop-preview-actions">
          <button class="workshop-preview-accept" type="button" data-workshop-preview-accept ${canAccept ? "" : "disabled"}>Aceptar</button>
        </div>
      </div>
    </div>
  `;
}

function renderWorkshopOutputModal(settings) {
  if (!workshopOutputModalOpen) return "";
  return `
    <div class="workshop-output-modal is-open">
      <div class="workshop-output-sheet" role="dialog" aria-modal="true" aria-labelledby="workshopOutputTitle">
        <div class="sheet-grip" aria-hidden="true"></div>
        <div class="item-action-head">
          <div class="item-action-title-wrap">
            <div class="item-action-kicker">Salida</div>
            <h2 id="workshopOutputTitle">Carpeta destino</h2>
          </div>
          <button class="sheet-close" type="button" data-workshop-output-close aria-label="Cerrar">x</button>
        </div>
        <div class="item-action-buttons">
          ${workshopOutputPresets.map((preset) => `
            <button class="item-action-button output-destination ${settings.carpeta_salida === preset.path ? "is-active" : ""}" type="button" data-workshop-output-path="${escapeHtml(preset.path)}">
              ${escapeHtml(preset.label)}
            </button>
          `).join("")}
        </div>
      </div>
    </div>
  `;
}

function renderWorkshopRows(rows) {
  if (!Array.isArray(rows) || !rows.length) return "";
  return `
    <div class="workshop-table">
      <div class="workshop-row is-head"><span>Zona</span><span>Inicio</span><span>Delay</span><span>Conf.</span><span>Pistas</span></div>
      ${rows.slice(-8).map((row) => `
        <div class="workshop-row">
          <span>${escapeHtml(row.zona)}</span>
          <span>${escapeHtml(row.inicio)}</span>
          <span>${escapeHtml(row.delay)} ms</span>
          <span>${escapeHtml(row.confianza)}</span>
          <span>${escapeHtml(`${row.pista_video || ""} / ${row.pista_espanol || ""}`)}</span>
        </div>
      `).join("")}
    </div>
  `;
}

function cleanWorkshopConfidence(value) {
  const text = String(value || "").trim();
  if (!text) return "--";
  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
}

function cleanWorkshopDelay(value) {
  if (value === undefined || value === null || value === "") return "--";
  const text = String(value).replace(/\s*ms$/i, "").trim();
  return `${text || "0"} ms`;
}

function hybridWorkshopResultInfo(result) {
  const state = String(result?.state || "").trim();
  if (!state) return null;
  const states = {
    OK_VERIFICADO: {
      title: "Verificado",
      message: "Audio e imagen coinciden con evidencia suficiente.",
      verified: true,
      technical: false
    },
    NO_FIABLE: {
      title: "No fiable",
      message: "La medición no reúne evidencia suficiente.",
      verified: false,
      technical: false
    },
    MONTAJE_DISTINTO: {
      title: "Montaje distinto",
      message: "Los vídeos parecen corresponder a montajes diferentes.",
      verified: false,
      technical: false
    },
    FPS_NO_CONFIRMADOS: {
      title: "FPS no confirmados",
      message: "No se ha confirmado una corrección de velocidad segura.",
      verified: false,
      technical: false
    },
    SIN_ZONAS_VALIDAS: {
      title: "Sin zonas válidas",
      message: "No hay zonas útiles suficientes para verificar el delay.",
      verified: false,
      technical: false
    },
    AUDIO_VIDEO_ORIGEN_DUDOSO: {
      title: "Origen dudoso",
      message: "Audio e imagen no aportan una referencia común segura.",
      verified: false,
      technical: false
    },
    ERROR_TECNICO: {
      title: "Error técnico",
      message: "La medición no pudo completarse correctamente.",
      verified: false,
      technical: true
    }
  };
  return states[state] || {
    title: "Resultado no reconocido",
    message: "El resultado no cumple el contrato del motor.",
    verified: false,
    technical: true
  };
}

function workshopHybridReason(result, fallback = "") {
  const reason = String(result?.decision?.reason || "").trim();
  const labels = {
    fast_path_visual_y_audio_coinciden: "Imagen y audio confirman el mismo delay.",
    descubrimiento_audio_y_visual_coinciden: "El descubrimiento de audio y la imagen confirman el mismo delay.",
    ningun_delay_fijo_explica_las_zonas: "Ningún delay fijo explica todas las zonas analizadas.",
    imagen_alinea_pero_audio_no_sostiene_el_mismo_origen: "La imagen alinea, pero el audio no confirma el mismo origen.",
    sin_zonas_utiles_en_audio_o_imagen: "No hay zonas útiles suficientes en audio o imagen.",
    descubrimiento_sin_evidencia_suficiente: "El descubrimiento no reúne evidencia suficiente.",
    fps_no_confirmados: "No se ha podido confirmar una corrección FPS segura.",
    vfr_no_confirmado: "El vídeo usa una cadencia variable que no se ha podido confirmar.",
    duracion_no_confirma_tempo: "La duración no confirma el cambio de velocidad previsto.",
    imagen_no_confirma_tempo: "La imagen no confirma el cambio de velocidad previsto.",
    duration_ratio_and_visual_match: "Duración e imagen confirman la corrección FPS.",
    evidencia_insuficiente_para_autorizar: "La evidencia no permite autorizar el resultado.",
    resultado_legacy_sin_verificacion_hibrida: "El resultado anterior no tiene verificación híbrida.",
    estado_hibrido_desconocido: "El motor devolvió un estado no reconocido.",
    contrato_resultado_invalido: "El resultado del motor está incompleto o no cumple el contrato.",
    motor_medicion_fallido: "El motor de medición no pudo completar el análisis.",
    error_tecnico_job: "El trabajo terminó por un error técnico.",
    cleanup_failed: "No se pudieron limpiar todos los temporales del trabajo.",
    fps_no_detectado: "No se pudieron detectar FPS válidos en ambos vídeos.",
    tempo_no_valido: "La relación de velocidad entre ambos vídeos no es válida.",
    fps_no_confirmado: "La diferencia FPS no quedó confirmada con seguridad."
  };
  if (labels[reason]) return labels[reason];
  if (!reason) return fallback || "El motor no ha indicado un motivo adicional.";
  const readable = reason.replace(/_/g, " ").trim();
  return readable ? `${readable.charAt(0).toUpperCase()}${readable.slice(1)}.` : fallback;
}

function workshopHybridFpsInfo(result) {
  const fps = result?.fps_correction || {};
  const reason = String(fps.reason || "");
  const refFps = normalizeWorkshopFps(fps.ref_fps).replace(/\.0+$/, "");
  const espFps = normalizeWorkshopFps(fps.esp_fps).replace(/\.0+$/, "");
  const pair = fps.planned === true && refFps && espFps ? ` · ${espFps} → ${refFps}` : "";

  if (fps.planned !== true) {
    if (reason && reason !== "fps_iguales") {
      return { text: "Rechazada", className: "is-error" };
    }
    return { text: "No necesaria", className: "is-neutral" };
  }
  if (fps.confirmed !== true) return { text: `Rechazada${pair}`, className: "is-error" };
  if (fps.applied === true) return { text: `Aplicada${pair}`, className: "is-ok" };
  return { text: `Confirmada${pair}`, className: "is-ok" };
}

function workshopHybridRequestedMode(state, result) {
  const values = [result?.requested_mode, state?.requested_mode];
  return values.find((value) => value === "medir" || value === "exportar") || "";
}

function workshopHybridExportInfo(state, result) {
  const exportData = result?.export || {};
  const status = String(exportData.status || "");
  const requestedMode = workshopHybridRequestedMode(state, result);
  if (status === "done") return { text: "Realizada", className: "is-ok", path: exportData.path || "" };
  if (status === "running") return { text: "En curso", className: "is-neutral", path: exportData.path || "" };
  if (status === "error") return { text: "Error", className: "is-error", path: exportData.path || "" };
  if (requestedMode === "medir") return { text: "No solicitada", className: "is-neutral", path: "" };
  if (state?.status === "running" && result?.state === "OK_VERIFICADO" && result?.export_allowed === true) {
    return { text: "En curso", className: "is-neutral", path: "" };
  }
  return { text: "Bloqueada", className: "is-warn", path: "" };
}

function workshopHybridZoneText(value, singular, plural) {
  const count = Math.max(0, Number(value) || 0);
  return `${count} ${count === 1 ? singular : plural}`;
}

function renderWorkshopHybridEvidence(state, result, hybridInfo) {
  const visual = result?.visual || {};
  const audio = result?.audio || {};
  const visualVerified = visual.verified === true;
  const visualZones = visual.zones_valid ?? 0;
  const audioZones = audio.supporting_zones ?? result?.zones_count ?? 0;
  const fpsInfo = workshopHybridFpsInfo(result);
  const exportInfo = workshopHybridExportInfo(state, result);
  const stateClass = hybridInfo.verified ? "is-ok" : hybridInfo.technical ? "is-error" : "is-warn";
  const reason = workshopHybridReason(result, hybridInfo.message);
  const delayUnavailable = String(result?.state || "") !== "OK_VERIFICADO";
  const finalDelay = delayUnavailable ? "--" : cleanWorkshopDelay(result?.delay_ms);
  const core = result?.measurement_core || {};
  const coreText = Number(core.span_sec) > 0
    ? `${Math.round(Number(core.start_sec || 0) / 60)}–${Math.round(Number(core.end_sec || 0) / 60)} min`
    : "No disponible";
  const editHint = result?.edit_hint || {};
  const editText = editHint.hint_helped_fast_path === true
    ? "Aceleró fast path"
    : editHint.hint_rejected === true
      ? "Descartada"
      : editHint.hint_used === true
        ? "Usada como semilla"
        : "No usada";

  return `
    <div class="workshop-evidence">
      <div class="workshop-evidence-item ${hybridInfo.verified ? "is-ok" : "is-warn"}">
        <span>Delay final</span>
        <strong>${escapeHtml(finalDelay)}</strong>
      </div>
      <div class="workshop-evidence-item ${stateClass}">
        <span>Estado</span>
        <strong>${escapeHtml(hybridInfo.title)}</strong>
      </div>
      <div class="workshop-evidence-item ${visualVerified ? "is-ok" : "is-warn"}">
        <span>Imagen</span>
        <strong>${escapeHtml(visualVerified ? "Verificada" : "No verificada")}</strong>
        <small>${escapeHtml(workshopHybridZoneText(visualZones, "zona válida", "zonas válidas"))}</small>
      </div>
      <div class="workshop-evidence-item ${hybridInfo.verified ? "is-ok" : "is-warn"}">
        <span>Audio</span>
        <strong>${escapeHtml(workshopHybridZoneText(audioZones, "zona coherente", "zonas coherentes"))}</strong>
      </div>
      <div class="workshop-evidence-item ${fpsInfo.className}">
        <span>FPS</span>
        <strong>${escapeHtml(fpsInfo.text)}</strong>
      </div>
      <div class="workshop-evidence-item ${Number(core.span_sec) > 0 ? "is-neutral" : "is-warn"}">
        <span>Zona útil</span>
        <strong>${escapeHtml(coreText)}</strong>
      </div>
      <div class="workshop-evidence-item ${editHint.hint_helped_fast_path === true ? "is-ok" : "is-neutral"}">
        <span>Editar</span>
        <strong>${escapeHtml(editText)}</strong>
      </div>
      <div class="workshop-evidence-item ${exportInfo.className}">
        <span>Exportación</span>
        <strong>${escapeHtml(exportInfo.text)}</strong>
      </div>
      <div class="workshop-evidence-item workshop-evidence-reason ${stateClass}">
        <span>Motivo</span>
        <strong>${escapeHtml(reason)}</strong>
      </div>
    </div>
    ${exportInfo.path && exportInfo.text === "Realizada" ? `<p class="workshop-ok">Exportado: ${escapeHtml(exportInfo.path)}</p>` : ""}
  `;
}

function workshopProgressInfo(state) {
  const progress = state.progress || null;
  const result = state.result || null;
  const hybridInfo = hybridWorkshopResultInfo(result);
  const rows = Array.isArray(state.rows) ? state.rows : [];
  let phase = String(progress?.phase || "").toLowerCase();
  if (!phase && state.status === "running" && result?.export?.status === "running") phase = "export";
  let percent = Number(progress?.percent);

  if (!Number.isFinite(percent)) {
    if (state.status === "running") {
      phase = phase || "measure";
      percent = Math.min(95, rows.length * 10);
    } else if (hybridInfo) {
      phase = hybridInfo.technical ? "error" : "done";
      percent = 100;
    } else if (result?.ok) {
      phase = "done";
      percent = 100;
    } else if (result && !result.ok) {
      phase = "error";
      percent = 100;
    } else {
      return null;
    }
  }

  percent = Math.max(0, Math.min(100, Math.round(percent)));
  const labels = {
    starting: "Inicio",
    fps: "FPS",
    measure: "Midiendo",
    export: "Exportando",
    done: "Listo",
    error: "Aviso"
  };

  return {
    phase: phase || "measure",
    label: progress?.label || labels[phase] || "Midiendo",
    percent
  };
}

function trailerJobProgressInfo(state = readTrailerJobState()) {
  if (!state.job || state.status !== "running") return null;
  const progress = state.progress || {};
  let percent = Number(progress.percent);
  if (!Number.isFinite(percent)) percent = 0;
  percent = Math.max(0, Math.min(100, Math.round(percent)));
  return {
    phase: progress.phase || state.phase || "trailer",
    label: progress.label || state.label || "Procesando",
    percent
  };
}

function renderTrailerJobProgressMarker() {
  const info = trailerJobProgressInfo();
  if (!info) return "";
  return `
    <div class="workshop-progress trailer-job-progress is-${escapeHtml(info.phase)}" aria-live="polite">
      <div class="workshop-progress-label"><span></span>${escapeHtml(info.label)}</div>
      <strong>${escapeHtml(info.percent)}%</strong>
    </div>
  `;
}

function renderHeaderWorkshop() {
  if (!headerWorkshopCluster) return;
  const state = readWorkshopState();
  const processHtml = `${renderTrailerJobProgressMarker()}${renderWorkshopProgressMarker(state)}${renderWorkshopLiveMarker(state)}`.trim();
  const html = processHtml || renderHeaderHints();
  headerWorkshopCluster.innerHTML = html;
  headerWorkshopCluster.classList.toggle("is-visible", Boolean(html));
  headerWorkshopCluster.classList.toggle("is-idle", !processHtml);
  headerWorkshopCluster.closest(".top")?.classList.toggle("has-idle-hints", !processHtml);
  if (!processHtml) ensureCardHintRotation();
}

function renderWorkshopProgressMarker(state) {
  const info = workshopProgressInfo(state);
  if (!info || state.status !== "running" || !["fps", "export"].includes(info.phase)) return "";
  return `
    <div class="workshop-progress is-${escapeHtml(info.phase)}" aria-live="polite">
      <div class="workshop-progress-label"><span></span>${escapeHtml(info.label)}</div>
      <strong>${escapeHtml(info.percent)}%</strong>
    </div>
  `;
}

function renderWorkshopLiveMarker(state) {
  if (state.status !== "running") return "";
  const progressPhase = String(state.progress?.phase || "").toLowerCase();
  if (progressPhase === "fps") return "";
  const rows = Array.isArray(state.rows) ? state.rows : [];
  const lastRow = rows.length ? rows[rows.length - 1] : null;
  const result = state.result || null;
  const hybridInfo = hybridWorkshopResultInfo(result);
  let phase = "running";
  let status = lastRow ? "Midiendo" : "Arrancando";
  let zone = "--";
  let delay = "--";
  let confidence = "--";
  let valuesClass = "";
  let valuesHtml = "";

  if (hybridInfo) {
    phase = hybridInfo.technical ? "error" : "done";
    status = hybridInfo.title;
  } else if (result?.ok) {
    phase = "done";
    status = "Resultado";
    delay = cleanWorkshopDelay(result.delay_ms);
    confidence = cleanWorkshopConfidence(result.confidence);
    valuesClass = " is-final";
    valuesHtml = `
        <strong>${escapeHtml(delay)}</strong>
        <strong>${escapeHtml(confidence)}</strong>
    `;
  } else {
    zone = lastRow ? String(lastRow.zona || rows.length) : "...";
    delay = lastRow ? cleanWorkshopDelay(lastRow.delay) : "--";
    confidence = lastRow ? cleanWorkshopConfidence(lastRow.confianza) : "--";
    valuesHtml = `
        <strong>${escapeHtml(zone)}</strong>
        <strong>${escapeHtml(delay)}</strong>
        <strong>${escapeHtml(confidence)}</strong>
    `;
  }

  return `
    <div class="workshop-live is-${phase}" aria-live="polite">
      <div class="workshop-live-status"><span></span>${escapeHtml(status)}</div>
      <div class="workshop-live-values${valuesClass}">
        ${valuesHtml}
      </div>
    </div>
  `;
}

function renderWorkshopResult(state) {
  const result = state.result || null;
  const hybridInfo = hybridWorkshopResultInfo(result);
  const rows = Array.isArray(state.rows) ? state.rows : [];
  if (state.status === "running" && !hybridInfo) {
    return `
      <section class="workshop-result is-running">
        <div class="workshop-kicker">Resultado</div>
        <h2>Midiendo...</h2>
        <p>Zonas analizadas: ${rows.length}</p>
        ${renderWorkshopRows(rows)}
      </section>
    `;
  }
  if (hybridInfo) {
    return `
      <section class="workshop-result">
        <div class="workshop-kicker">Resultado</div>
        <h2>Resultado híbrido</h2>
        ${renderWorkshopHybridEvidence(state, result, hybridInfo)}
        ${renderWorkshopRows(rows)}
      </section>
    `;
  }
  if (result?.ok) {
    const exportData = result.export || null;
    return `
      <section class="workshop-result">
        <div class="workshop-kicker">Resultado</div>
        <div class="workshop-final">
          <strong>${escapeHtml(result.delay_ms)} ms</strong>
          <span>${escapeHtml(result.confidence || "")}</span>
        </div>
        <p>${escapeHtml(result.zones_count || 0)} zonas · score ${Number(result.avg_score || 0).toFixed(3)}</p>
        ${exportData?.status === "done" ? `<p class="workshop-ok">Exportado: ${escapeHtml(exportData.path || "")}</p>` : ""}
        ${exportData?.status === "running" ? `<p>Exportando video final...</p>` : ""}
        ${exportData?.status === "skipped" ? `<p>No exportado: confianza inferior a MEDIA.</p>` : ""}
        ${exportData?.status === "error" ? `<p class="workshop-error">Exportacion fallida.</p>` : ""}
        ${renderWorkshopRows(rows)}
      </section>
    `;
  }
  if (result && !result.ok) {
    return `
      <section class="workshop-result">
        <div class="workshop-kicker">Resultado</div>
        <h2>Error</h2>
        <p class="workshop-error">${escapeHtml(result.error || "La medicion fallo.")}</p>
        ${renderWorkshopRows(rows)}
      </section>
    `;
  }
  return `
    <section class="workshop-result">
      <div class="workshop-kicker">Resultado</div>
      <h2>Preparado</h2>
      <p>Selecciona Video Bueno y Audio Español.</p>
    </section>
  `;
}

function workshopActionInfo(settings, alerts, state) {
  if (workshopBusy || state.status === "running") {
    return { text: "Trabajando", className: "" };
  }
  const exporting = settings.modo !== "medir";
  if (alerts?.fpsMismatch) {
    return {
      text: exporting ? "Corregir FPS, medir y exportar" : "Corregir FPS y medir",
      className: " is-fps-action"
    };
  }
  return {
    text: exporting ? "Medir y exportar" : "Solo medir",
    className: ""
  };
}

function renderWorkshop() {
  const state = readWorkshopState();
  const settings = workshopSettings(state);
  const alerts = workshopMetaAlerts(state);
  const action = workshopActionInfo(settings, alerts, state);
  return `
    <div class="workshop">
      ${renderWorkshopSlot("ref", state.ref, alerts)}
      ${renderWorkshopSlot("esp", state.esp, alerts)}
      ${renderWorkshopDelayHint(state)}
      <div class="workshop-actions">
        <button class="workshop-run${escapeHtml(action.className)}" type="button" data-workshop-run ${!workshopReady(state) || workshopJobRunning(state) ? "disabled" : ""}>${escapeHtml(action.text)}</button>
      </div>
      ${renderWorkshopSettings(settings, workshopJobRunning(state))}
      ${renderWorkshopResult(state)}
      ${renderWorkshopPreviewModal(state)}
      ${renderWorkshopOutputModal(settings)}
    </div>
  `;
}


function getSections(data) {
  return Array.isArray(data?.sections) ? data.sections : [];
}

function getActiveSection(data) {
  const sections = getSections(data);
  return sections.find((section) => section.id === activeTab) || sections[0] || null;
}

function setActiveTab(tabId) {
  activeTab = tabId || "movies";
  selectedQbitHashes.clear();
  saveActiveTab(activeTab);
  render(lastData);
  if (activeTab === "taller") {
    statusText.textContent = "Taller listo";
    return;
  }
  loadStatus();
}

function renderTabs(data) {
  const sections = getSections(data);
  tabsEl.innerHTML = sections.map((section) => `
    <button
      class="tab ${section.id === activeTab ? "is-active" : ""}"
      type="button"
      data-tab="${escapeHtml(section.id)}"
    >${escapeHtml(section.label)}${section.id === "taller" && workshopSaveStatus ? `<span class="tab-save-badge is-${escapeHtml(workshopSaveStatus)}"><i></i>${escapeHtml(workshopSaveText())}</span>` : ""}</button>
  `).join("");

  tabsEl.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });
}

function bindTextDetailToggles(root = foldersEl) {
  root.querySelectorAll("[data-txt-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const detailId = button.dataset.txtToggle;
      if (!detailId) return;
      const open = button.getAttribute("aria-expanded") !== "true";
      if (open) {
        openTextDetails.add(detailId);
      } else {
        openTextDetails.delete(detailId);
      }

      const wrapper = button.closest(".txt-child");
      const detail = foldersEl.querySelector(`[data-txt-detail="${CSS.escape(detailId)}"]`);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      wrapper?.classList.toggle("is-open", open);
      detail?.classList.toggle("is-open", open);
    });
  });
}

function bindFolderDetailToggles(root = foldersEl) {
  root.querySelectorAll("[data-folder-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const detailId = button.dataset.folderToggle;
      const sourceId = button.dataset.folderSource;
      const itemName = button.dataset.folderName;
      let itemParts = [];
      try {
        itemParts = JSON.parse(button.dataset.folderParts || "[]");
      } catch (error) {
        itemParts = [];
      }
      if (!Array.isArray(itemParts) || !itemParts.length) itemParts = itemName ? [itemName] : [];
      if (!detailId) return;
      const open = button.getAttribute("aria-expanded") !== "true";
      if (open) {
        openFolderDetails.add(detailId);
      } else {
        openFolderDetails.delete(detailId);
      }

      const wrapper = button.closest(".folder-child");
      const detail = foldersEl.querySelector(`[data-folder-detail="${CSS.escape(detailId)}"]`);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      wrapper?.classList.toggle("is-open", open);
      detail?.classList.toggle("is-open", open);
      if (open && sourceId && itemParts.length && !folderChildrenCache.has(detailId) && !loadingFolderDetails.has(detailId)) {
        loadFolderChildren(detailId, sourceId, itemParts);
      }
    });
  });
}

function renderChildren(children, context = {}) {
  if (!Array.isArray(children) || !children.length) return "";
  const sourceId = context.sourceId || "";
  const baseParts = Array.isArray(context.parts) ? context.parts : [];
  const detailPrefix = context.detailPrefix || baseParts.join("::");
  return `
    <div class="children">
      ${children.map((child) => {
        const kind = child.kind || "file";
        const hasText = Object.prototype.hasOwnProperty.call(child, "text");
        const detailId = detailPrefix ? `${detailPrefix}::${child.name}` : child.name;
        const parts = [...baseParts, child.name];
        const target = makeActionTarget(sourceId, parts, kind);
        const isOpen = openTextDetails.has(detailId);
        const folderOpen = openFolderDetails.has(detailId);
        const canExpand = kind === "folder" && Boolean(child.can_expand);
        if (hasText) {
          return `
            <div class="txt-child ${isOpen ? "is-open" : ""}">
              <div class="child txt-child-head">
                ${renderItemActionIcon(child.name, target, kind)}
                ${renderTextToggleName(child.name, detailId, isOpen, sourceId, child.mtime)}
                ${renderItemMeta(child)}
                <span class="txt-chevron" aria-hidden="true">v</span>
              </div>
              <pre class="txt-detail ${isOpen ? "is-open" : ""}" data-txt-detail="${escapeHtml(detailId)}">${escapeHtml(child.text)}</pre>
            </div>
          `;
        }
        if (canExpand) {
          return `
            <div class="folder-child ${folderOpen ? "is-open" : ""}">
              <div class="child folder-toggle-head">
                ${renderItemActionIcon(child.name, target, kind)}
                ${renderFolderToggleName(child.name, detailId, sourceId, parts, folderOpen, child.mtime)}
                ${renderItemMeta(child)}
                <span class="folder-chevron" aria-hidden="true">v</span>
              </div>
              <div class="folder-children ${folderOpen ? "is-open" : ""}" data-folder-detail="${escapeHtml(detailId)}">
                ${renderFolderChildrenContent(detailId)}
              </div>
            </div>
          `;
        }
        return `
          <div class="child">
            ${renderItemActionIcon(child.name, target, kind)}
            ${kind === "video" ? renderItemName(child.name, target, child.mtime) : renderStaticItemName(child.name, child.mtime)}
            ${renderItemMeta(child)}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderFolderChildrenContent(detailId) {
  if (loadingFolderDetails.has(detailId)) {
    return `<div class="children"><div class="empty">Cargando...</div></div>`;
  }

  const cached = folderChildrenCache.get(detailId);
  if (!cached) {
    return `<div class="children"><div class="empty">Pulsa para cargar</div></div>`;
  }
  if (cached.error) {
    return `<div class="error">${escapeHtml(cached.error)}</div>`;
  }

  return renderChildren(cached.items, {
    sourceId: cached.sourceId,
    parts: cached.parts || [],
    detailPrefix: detailId
  }) || `<div class="children"><div class="empty">Vacia</div></div>`;
}

async function loadFolderChildren(detailId, sourceId, itemParts, options = {}) {
  if (loadingFolderDetails.has(detailId)) return false;
  const silent = Boolean(options.silent);
  const renderAfter = options.renderAfter !== false;
  const parts = Array.isArray(itemParts)
    ? itemParts.map((part) => String(part || "").trim()).filter(Boolean)
    : [String(itemParts || "").trim()].filter(Boolean);
  loadingFolderDetails.add(detailId);
  if (!silent) render(lastData);
  let changed = false;
  try {
    const params = new URLSearchParams({
      v: "seguimiento_children",
      source: sourceId,
      name: parts[parts.length - 1] || "",
      t: String(Date.now())
    });
    parts.forEach((part) => params.append("part", part));
    const url = `/api?${params.toString()}`;
    const response = await fetch(url, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    folderChildrenCache.set(detailId, {
      items: Array.isArray(data.items) ? data.items : [],
      sourceId,
      parts,
      error: ""
    });
    changed = true;
  } catch (error) {
    folderChildrenCache.set(detailId, {
      items: [],
      sourceId,
      parts,
      error: "No se pudo cargar"
    });
    changed = true;
  } finally {
    loadingFolderDetails.delete(detailId);
    if (renderAfter) render(lastData);
  }
  return changed;
}

function visibleOpenFolderRequests() {
  const seen = new Set();
  return [...foldersEl.querySelectorAll('[data-folder-toggle][aria-expanded="true"]')]
    .map((button) => {
      let parts = [];
      try {
        parts = JSON.parse(button.dataset.folderParts || "[]");
      } catch (error) {
        parts = [];
      }
      if (!Array.isArray(parts) || !parts.length) parts = button.dataset.folderName ? [button.dataset.folderName] : [];
      return {
        detailId: button.dataset.folderToggle,
        sourceId: button.dataset.folderSource,
        itemName: button.dataset.folderName,
        parts
      };
    })
    .filter((request) => {
      if (!request.detailId || !request.sourceId || !request.parts.length || seen.has(request.detailId)) return false;
      seen.add(request.detailId);
      return true;
    });
}

async function refreshOpenFolderChildren() {
  if (openFolderRefreshInProgress) return;
  const requests = visibleOpenFolderRequests();
  if (!requests.length) return;

  openFolderRefreshInProgress = true;
  try {
    const results = await Promise.all(requests.map((request) => loadFolderChildren(
      request.detailId,
      request.sourceId,
      request.parts,
      { silent: true, renderAfter: false }
    )));
    if (results.some(Boolean)) render(lastData);
  } finally {
    openFolderRefreshInProgress = false;
  }
}

function renderExpandableItem(item, sourceId) {
  const kind = item.kind || "file";
  const canExpand = kind === "folder" && Boolean(item.can_expand);
  const itemParts = Array.isArray(item.parts) && item.parts.length ? item.parts : [item.name];
  const detailId = `${sourceId}::${itemParts.join("/")}`;
  const target = makeActionTarget(sourceId, itemParts, kind);
  const isOpen = openFolderDetails.has(detailId);
  const hasText = Object.prototype.hasOwnProperty.call(item, "text");

  if (hasText) {
    const textOpen = openTextDetails.has(detailId);
    return `
      <div class="txt-child ${textOpen ? "is-open" : ""}">
        <div class="item txt-child-head">
          ${renderItemActionIcon(item.name, target, kind)}
          ${renderTextToggleName(item.name, detailId, textOpen, sourceId, item.mtime)}
          ${renderItemMeta(item)}
          <span class="txt-chevron" aria-hidden="true">v</span>
        </div>
        <pre class="txt-detail ${textOpen ? "is-open" : ""}" data-txt-detail="${escapeHtml(detailId)}">${escapeHtml(item.text)}</pre>
      </div>
    `;
  }

  if (canExpand) {
    const parts = itemParts;
    return `
      <div class="folder-child ${isOpen ? "is-open" : ""}">
        <div class="item folder-toggle-head">
          ${renderItemActionIcon(item.name, target, kind)}
          ${renderFolderToggleName(item.name, detailId, sourceId, parts, isOpen, item.mtime)}
          ${renderItemMeta(item)}
          <span class="folder-chevron" aria-hidden="true">v</span>
        </div>
        <div class="folder-children ${isOpen ? "is-open" : ""}" data-folder-detail="${escapeHtml(detailId)}">
          ${renderFolderChildrenContent(detailId)}
        </div>
      </div>
    `;
  }

  return `
    <div class="item">
      ${renderItemActionIcon(item.name, target, kind)}
      ${kind === "video" ? renderItemName(item.name, target, item.mtime) : renderStaticItemName(item.name, item.mtime)}
      ${renderItemMeta(item)}
    </div>
    ${renderChildren(item.children, {
      sourceId,
      parts: itemParts,
      detailPrefix: item.name
    })}
  `;
}

function renderExtraSections(sections) {
  if (!Array.isArray(sections) || !sections.length) return "";
  return sections.map((section) => {
    const items = Array.isArray(section.items) ? section.items : [];
    const body = section.error
      ? `<div class="error">${escapeHtml(section.error)}</div>`
      : items.length
        ? items.map((item) => renderExpandableItem(item, section.id || item.children_source || "")).join("")
        : "";

    return `
      <div class="extra-section ${body ? "" : "is-empty"}">
        <div class="extra-title">${escapeHtml(section.label)}</div>
        <div class="extra-items">${body}</div>
      </div>
    `;
  }).join("");
}

function renderArrStatusCard(status) {
  if (!["movies", "tv"].includes(activeTab)) return "";
  const cardId = `realdebrid-${activeTab}`;
  const safeStatus = status || {
    stale: true,
    monitoring: 0,
    counts: {},
    items: [],
    updated_at: null,
    error: ""
  };
  const items = Array.isArray(safeStatus.items) ? safeStatus.items : [];
  const compactWatchCard = ["movies", "tv"].includes(activeTab);
  const hasActivity = Number(safeStatus.monitoring || 0) > 0 || items.length > 0;
  const canToggle = !compactWatchCard || hasActivity;
  const collapsed = compactWatchCard && !hasActivity ? true : isWatchCardCollapsed(cardId);
  const compactText = realDebridCompactText(items);
  const rows = items.length
    ? items.map((item) => `
      <div class="arr-row">
        <div class="arr-row-main">
          <span class="arr-name${freshnessClass(item.last_progress_ts)}" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</span>
        </div>
        <div class="arr-progress">
          <span style="width:${Math.max(0, Math.min(100, Number(item.progress || 0)))}%"></span>
        </div>
        <div class="arr-row-sub">
          <span>${pct(item.progress)}</span>
          <span>${escapeHtml(item.category || "manual")}</span>
          <span>${item.last_progress_ts ? `cambio ${compactAge(item.last_progress_ts)}` : ""}</span>
        </div>
      </div>
    `).join("")
    : `<div class="empty">Sin elementos vigilados</div>`;

  const headTag = canToggle ? "button" : "div";
  const headAttributes = canToggle
    ? `type="button" data-watch-toggle="${cardId}" aria-expanded="${collapsed ? "false" : "true"}"`
    : "";
  const body = compactWatchCard && !hasActivity ? "" : `
      ${compactWatchCard ? "" : `<div class="watch-closed">${escapeHtml(compactText)}</div>`}
      <div class="watch-body">
        <div class="items">
          ${safeStatus.error ? `<div class="error">${escapeHtml(safeStatus.error)}</div>` : ""}
          ${rows}
        </div>
        <div class="arr-updated">${safeStatus.updated_at ? `Actualizado ${ago(safeStatus.updated_at)}` : "Sin actualizar"}${safeStatus.stale ? " · cache" : ""}</div>
      </div>`;

  return `
    <article class="card watch-card arr-card ${compactWatchCard ? "is-compact-trial" : ""} ${compactWatchCard && !hasActivity ? "is-empty-compact" : ""} ${watchCardHasFreshActivity(cardId) ? "has-fresh-activity" : ""} ${collapsed ? "is-collapsed" : ""}" data-watch-card="${cardId}">
      <${headTag} class="watch-head ${canToggle ? "" : "is-static"}" ${headAttributes}>
        <span class="watch-title-wrap">
          <span class="title">Real-Debrid</span>
        </span>
        <span class="watch-side">
          <span class="badge">${safeStatus.monitoring || 0} vigilados</span>
          ${canToggle ? `<span class="watch-chevron" aria-hidden="true">v</span>` : ""}
        </span>
      </${headTag}>
      ${body}
    </article>
  `;
}

async function deleteSelectedQbit(category) {
  const hashes = [...selectedQbitHashes];
  if (!hashes.length || qbitDeleteInProgress) return;
  const label = category === "tv" ? "TV" : "Movies";
  const ok = confirm(`Borrar ${hashes.length} torrent(s) de ${label} y sus archivos descargados?`);
  if (!ok) return;

  const soundJob = finishSoundJob("qbit-delete", `${category}:${hashes.length}`);
  prepareFinishSound();
  qbitDeleteInProgress = true;
  render(lastData);
  try {
    const response = await fetch("/api", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ v: "seguimiento_qbit_delete", category, hashes })
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    selectedQbitHashes.clear();
    statusText.textContent = `${data.deleted || hashes.length} torrent(s) borrado(s)`;
    await loadStatus({ skipEntrySound: true });
    playFinishSound(soundJob);
  } catch (error) {
    statusText.textContent = "No se pudo borrar qBittorrent";
  } finally {
    qbitDeleteInProgress = false;
    render(lastData);
  }
}

function renderQbitStatusCard(status) {
  if (!["movies", "tv"].includes(activeTab)) return "";
  const label = activeTab === "tv" ? "TV" : "Movies";
  const cardId = `qbit-${activeTab}`;
  const safeStatus = status || {
    stale: true,
    total: 0,
    shown: 0,
    counts: {},
    items: [],
    updated_at: null,
    error: ""
  };
  const items = Array.isArray(safeStatus.items) ? safeStatus.items : [];
  const compactWatchCard = ["movies", "tv"].includes(activeTab);
  const hasActivity = Number(safeStatus.total || 0) > 0 || items.length > 0;
  const canToggle = !compactWatchCard || hasActivity;
  const collapsed = compactWatchCard && !hasActivity ? true : isWatchCardCollapsed(cardId);
  const visibleHashes = new Set(items.map((item) => item.hash).filter(Boolean));
  selectedQbitHashes.forEach((hash) => {
    if (!visibleHashes.has(hash)) selectedQbitHashes.delete(hash);
  });
  const selectedCount = [...selectedQbitHashes].filter((hash) => visibleHashes.has(hash)).length;
  const compactText = qbitCompactText(items);
  const showAll = isQbitShowingAll(activeTab);
  const visibleItems = showAll ? items : items.slice(0, qbitDefaultVisible);
  const hasMoreItems = items.length > qbitDefaultVisible;
  const qbitModeButton = hasMoreItems
    ? `<button class="qbit-mode-button" type="button" data-qbit-show-all="${escapeHtml(activeTab)}">${showAll ? "Solo 8" : "Todos"}</button>`
    : "";
  const rows = visibleItems.length
    ? visibleItems.map((item) => `
      <div class="arr-row qbit-row ${selectedQbitHashes.has(item.hash) ? "is-selected" : ""}">
        <div class="arr-row-main qbit-row-main">
          <label class="qbit-check" title="Seleccionar">
            <input type="checkbox" data-qbit-select="${escapeHtml(item.hash)}" ${selectedQbitHashes.has(item.hash) ? "checked" : ""} ${item.hash ? "" : "disabled"}>
            <span aria-hidden="true"></span>
          </label>
          <span class="arr-name${freshnessClass(item.added_on)}" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
        </div>
        <div class="arr-progress">
          <span style="width:${Math.max(0, Math.min(100, Number(item.progress || 0)))}%"></span>
        </div>
        <div class="arr-row-sub">
          <span>${qbitPct(item.progress)}</span>
          <span>${escapeHtml(item.size || "")}</span>
          <span>${escapeHtml(item.dlspeed || "0 B/s")}</span>
          <span>${item.added_on ? `agregado ${compactAge(item.added_on)}` : ""}</span>
        </div>
      </div>
    `).join("")
    : `<div class="empty">Sin torrents en ${escapeHtml(label)}</div>`;

  const titleTag = canToggle ? "button" : "span";
  const titleAttributes = canToggle
    ? `type="button" data-watch-toggle="${cardId}" aria-expanded="${collapsed ? "false" : "true"}"`
    : "";
  const body = compactWatchCard && !hasActivity ? "" : `
      ${compactWatchCard ? "" : `<div class="watch-closed">${escapeHtml(compactText)}</div>`}
      <div class="watch-body">
        <div class="items">
          ${safeStatus.error ? `<div class="error">${escapeHtml(safeStatus.error)}</div>` : ""}
          ${rows}
        </div>
        <div class="arr-updated">${safeStatus.updated_at ? `Actualizado ${ago(safeStatus.updated_at)}` : "Sin actualizar"}${safeStatus.shown && safeStatus.total > safeStatus.shown ? ` · mostrando ${safeStatus.shown}` : ""}</div>
        ${selectedCount ? `<div class="qbit-actions">
          <span>${selectedCount} seleccionado(s)</span>
          <button class="qbit-delete" type="button" data-qbit-delete="${escapeHtml(activeTab)}" ${selectedCount && !qbitDeleteInProgress ? "" : "disabled"}>${qbitDeleteInProgress ? "Borrando..." : "Borrar"}</button>
        </div>` : ""}
      </div>`;

  return `
    <article class="card watch-card qbit-card ${compactWatchCard ? "is-compact-trial" : ""} ${compactWatchCard && !hasActivity ? "is-empty-compact" : ""} ${watchCardHasFreshActivity(cardId) ? "has-fresh-activity" : ""} ${collapsed ? "is-collapsed" : ""}" data-watch-card="${cardId}">
      <div class="watch-head qbit-head">
        <${titleTag} class="watch-title-button ${canToggle ? "" : "is-static"}" ${titleAttributes}>
          <span class="watch-title-wrap">
            <span class="title">qBittorrent ${escapeHtml(label)}</span>
          </span>
        </${titleTag}>
        <span class="watch-side">
          ${qbitModeButton}
          <span class="badge">${safeStatus.total || 0} torrents</span>
          ${canToggle ? `<button class="watch-chevron" type="button" data-watch-toggle="${cardId}" aria-expanded="${collapsed ? "false" : "true"}" aria-label="Plegar">v</button>` : ""}
        </span>
      </div>
      ${body}
    </article>
  `;
}

function arrWorkersEnabled() {
  return lastData?.arr_workers?.enabled === true;
}

function renderArrWorkersButton(folder) {
  if (folder.id !== "complete_movies") return "";
  const enabled = arrWorkersEnabled();
  const stateClass = enabled ? "is-on" : "is-off";
  const label = enabled ? "ON" : "OFF";
  return `
    <button
      class="arr-power ${stateClass} ${arrWorkersBusy ? "is-busy" : ""}"
      type="button"
      data-arr-power
      aria-pressed="${enabled ? "true" : "false"}"
      ${arrWorkersBusy ? "disabled" : ""}
    >
      <span>${label}</span>
    </button>
  `;
}

function renderMediaSearchButton(folder) {
  if (!searchableFolderIds.has(folder.id)) return "";
  const state = getMediaSearch(folder.id);
  const active = state.open || Boolean(state.query);
  return `
    <button
      class="media-search-toggle ${active ? "is-active" : ""}"
      type="button"
      data-media-search-toggle="${escapeHtml(folder.id)}"
      aria-label="Buscar"
      aria-pressed="${active ? "true" : "false"}"
    >&#128269;</button>
  `;
}

function renderMoveHint() {
  return `
    <div class="move-hint" aria-label="Icono Mover">
      <span class="move-hint-label">Icono</span>
      <span class="move-hint-value" aria-hidden="true">
        <span class="move-hint-icon">
          <span class="move-hint-icon-main">${moveHintItems[cardHintIndex % moveHintItems.length]}</span>
        </span>
        <span class="move-hint-action">Mover</span>
      </span>
    </div>
  `;
}

function renderTitleHint() {
  return `
    <div class="title-hint" aria-label="Titulo">
      <span class="title-hint-fixed">Titulo</span>
      <span class="title-hint-rotator" aria-hidden="true"><span class="title-hint-text">${titleHintItems[cardHintIndex % titleHintItems.length]}</span></span>
    </div>
  `;
}

function renderHeaderHints() {
  return `
    <div class="header-idle-hints">
      ${renderMoveHint()}
      ${renderTitleHint()}
    </div>
  `;
}

function setCardHintContent(entering = false) {
  const moveText = moveHintItems[cardHintIndex % moveHintItems.length];
  const titleText = titleHintItems[cardHintIndex % titleHintItems.length];
  headerWorkshopCluster?.querySelectorAll(".move-hint-icon-main").forEach((item) => {
    item.classList.remove("is-fading-out");
    if (entering) item.classList.add("is-fading-in");
    item.innerHTML = moveText;
    if (entering) {
      void item.offsetWidth;
      window.setTimeout(() => item.classList.remove("is-fading-in"), 30);
    }
  });
  headerWorkshopCluster?.querySelectorAll(".title-hint-text").forEach((item) => {
    item.classList.remove("is-fading-out");
    if (entering) item.classList.add("is-fading-in");
    item.innerHTML = titleText;
    if (entering) {
      void item.offsetWidth;
      window.setTimeout(() => item.classList.remove("is-fading-in"), 30);
    }
  });
}

function animateCardHintsStep() {
  const items = [...(headerWorkshopCluster?.querySelectorAll(".move-hint-icon-main, .title-hint-text") || [])];
  if (!items.length) return;
  items.forEach((item) => {
    item.classList.remove("is-fading-in");
    item.classList.add("is-fading-out");
  });
  window.setTimeout(() => {
    cardHintIndex = (cardHintIndex + 1) % titleHintItems.length;
    setCardHintContent(true);
  }, 320);
}

function ensureCardHintRotation() {
  setCardHintContent(false);
  if (cardHintTimer) return;
  cardHintTimer = window.setInterval(animateCardHintsStep, 2800);
}

function mediaSearchStatusText(state) {
  if (state.loading) return "Buscando...";
  if (state.error) return state.error;
  if (state.query) return state.count === 1 ? "1 resultado" : `${state.count} resultados`;
  return "";
}

function renderMediaSearchPanel(folder) {
  if (!searchableFolderIds.has(folder.id)) return "";
  const state = getMediaSearch(folder.id);
  if (!state.open) return "";
  const query = state.query || "";
  const status = mediaSearchStatusText(state);

  return `
    <div class="media-search-panel" data-media-search-panel="${escapeHtml(folder.id)}">
      <div class="media-search-row">
        <input
          class="media-search-input"
          type="search"
          value="${escapeHtml(query)}"
          placeholder="Buscar..."
          data-media-search-input="${escapeHtml(folder.id)}"
          autocomplete="off"
          spellcheck="false"
        >
        <button class="media-search-clear" type="button" data-media-search-clear="${escapeHtml(folder.id)}" aria-label="Limpiar">x</button>
      </div>
      <div class="media-search-status ${state.error ? "is-error" : ""}" data-media-search-status="${escapeHtml(folder.id)}">${escapeHtml(status)}</div>
    </div>
  `;
}

function renderMediaSearchResults(folderId) {
  const state = getMediaSearch(folderId);
  const renderedItems = (Array.isArray(state.items) ? state.items : [])
    .map((item) => renderExpandableItem(item, item.children_source || folderId))
    .join("");
  const empty = state.query && !state.loading && !state.error ? `<div class="empty">Sin resultados</div>` : "";
  return `
    <div class="media-search-results" data-media-search-results="${escapeHtml(folderId)}">
      ${renderedItems || empty}
    </div>
  `;
}

function findRenderedFolder(folderId) {
  const sections = getSections(lastData || {});
  for (const section of sections) {
    const folder = (section.folders || []).find((item) => item.id === folderId);
    if (folder) return folder;
  }
  return null;
}

function renderFolderDefaultBody(folder) {
  const items = (Array.isArray(folder.items) ? folder.items : []).map((item) => {
    return renderExpandableItem(item, item.children_source || folder.id);
  }).join("");
  return `${items}${renderExtraSections(folder.extra_sections)}`;
}

function refreshMediaSearchDom(folderId) {
  const state = getMediaSearch(folderId);
  const statusEl = foldersEl.querySelector(`[data-media-search-status="${CSS.escape(folderId)}"]`);
  if (statusEl) {
    statusEl.textContent = mediaSearchStatusText(state);
    statusEl.classList.toggle("is-error", Boolean(state.error));
  }
  const liveEl = foldersEl.querySelector(`[data-media-search-live="${CSS.escape(folderId)}"]`);
  if (liveEl) {
    const folder = findRenderedFolder(folderId);
    liveEl.innerHTML = state.query ? renderMediaSearchResults(folderId) : (folder ? renderFolderDefaultBody(folder) : "");
    bindFolderDetailToggles(liveEl);
    bindTextDetailToggles(liveEl);
    bindItemRenameButtons(liveEl);
    bindItemActionNames(liveEl);
    return;
  }
  render(lastData);
}

function renderFolder(folder) {
  const isAlertCard = ["repetidas_error"].includes(folder.id);
  const isHospitalCard = folder.id === "hospital";
  const isTallerCompleteCard = folder.id === "complete_taller";
  const isGoodCard = activeTab === "movies" && folder.id === "media_movies"
    || activeTab === "tv" && folder.id === "media_tv"
    || activeTab === "trailers" && folder.id === "media_movies_trailer";
  const isStandardCard = !isAlertCard && !isGoodCard && !isHospitalCard && !isTallerCompleteCard;
  const extraSections = Array.isArray(folder.extra_sections) ? folder.extra_sections : [];
  const extraCount = extraSections.reduce((total, section) => {
    return total + (Array.isArray(section.items) ? section.items.length : 0);
  }, 0);
  const isAutomationCard = folder.id === "movies_automatizacion";
  const displayCount = Number(folder.count || 0) + (isAutomationCard ? extraCount : 0);
  const hasError = Boolean(folder.error || extraSections.some((section) => section.error));
  const hasActivity = displayCount > 0 || hasError;
  const cardId = `folder-${activeTab}-${folder.id}`;
  const collapsed = hasActivity ? isWatchCardCollapsed(cardId) : true;

  const searchState = searchableFolderIds.has(folder.id) ? getMediaSearch(folder.id) : null;
  const searchActive = Boolean(searchState?.query);
  const searchableBody = searchableFolderIds.has(folder.id)
    ? `${renderMediaSearchPanel(folder)}<div class="media-search-live" data-media-search-live="${escapeHtml(folder.id)}">${searchActive ? renderMediaSearchResults(folder.id) : renderFolderDefaultBody(folder)}</div>`
    : renderFolderDefaultBody(folder);
  const body = folder.error
    ? `<div class="error">${escapeHtml(folder.error)}</div>`
    : searchableBody;

  return `
    <article class="card watch-card folder-watch-card ${isStandardCard ? "card-standard" : ""} ${isAlertCard ? "card-alert" : ""} ${isGoodCard ? "card-good" : ""} ${isHospitalCard ? "card-hospital" : ""} ${isTallerCompleteCard ? "card-taller-complete" : ""} ${hasActivity ? "" : "is-empty-compact"} ${watchCardHasFreshActivity(cardId) ? "has-fresh-activity" : ""} ${collapsed ? "is-collapsed" : ""}" data-watch-card="${cardId}">
      <div class="card-head">
        <div>
          ${hasActivity
            ? `<button class="watch-title-button folder-watch-title-button" type="button" data-watch-toggle="${cardId}" aria-expanded="${collapsed ? "false" : "true"}"><span class="title">${escapeHtml(folder.name)}</span></button>`
            : `<div class="title">${escapeHtml(folder.name)}</div>`}
        </div>
        <div class="card-actions">
          ${renderArrWorkersButton(folder)}
          ${renderMediaSearchButton(folder)}
          <div class="badge">${plural(displayCount)}</div>
          ${hasActivity ? `<button class="watch-chevron folder-watch-chevron" type="button" data-watch-toggle="${cardId}" aria-expanded="${collapsed ? "false" : "true"}" aria-label="Plegar">v</button>` : ""}
        </div>
      </div>
      ${hasActivity ? `<div class="watch-body folder-watch-body"><div class="items">${body}</div></div>` : ""}
    </article>
  `;
}

function bindArrWorkersButton() {
  foldersEl.querySelectorAll("[data-arr-power]").forEach((button) => {
    button.addEventListener("click", toggleArrWorkers);
  });
}

function bindMediaSearchControls() {
  foldersEl.querySelectorAll("[data-media-search-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const folderId = button.dataset.mediaSearchToggle;
      const state = getMediaSearch(folderId);
      state.open = !state.open;
      const cardId = button.closest("[data-watch-card]")?.dataset.watchCard;
      if (state.open && cardId) setWatchCardCollapsed(cardId, false);
      if (!state.open) clearMediaSearch(folderId);
      render(lastData);
      if (state.open) {
        requestAnimationFrame(() => {
          foldersEl.querySelector(`[data-media-search-input="${CSS.escape(folderId)}"]`)?.focus();
        });
      }
    });
  });

  foldersEl.querySelectorAll("[data-media-search-clear]").forEach((button) => {
    button.addEventListener("click", () => {
      const folderId = button.dataset.mediaSearchClear;
      clearMediaSearch(folderId, { close: true });
      render(lastData);
    });
  });

  foldersEl.querySelectorAll("[data-media-search-input]").forEach((input) => {
    input.addEventListener("input", () => {
      const folderId = input.dataset.mediaSearchInput;
      const state = getMediaSearch(folderId);
      state.query = input.value;
      state.open = true;
      state.error = "";
      state.loading = Boolean(state.query.trim());
      state.items = state.query.trim() ? state.items : [];
      state.count = state.query.trim() ? state.count : 0;
      if (state.timer) clearTimeout(state.timer);
      state.timer = setTimeout(() => runMediaSearch(folderId), 180);
      refreshMediaSearchDom(folderId);
    });
  });
}

async function runMediaSearch(folderId) {
  const state = getMediaSearch(folderId);
  const query = state.query.trim();
  if (!query) {
    state.loading = false;
    state.items = [];
    state.count = 0;
    state.error = "";
    refreshMediaSearchDom(folderId);
    return;
  }

  try {
    const params = new URLSearchParams({
      v: "seguimiento_media_search",
      source: folderId,
      query,
      t: String(Date.now())
    });
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    if (getMediaSearch(folderId).query.trim() !== query) return;
    state.items = Array.isArray(data.items) ? data.items : [];
    state.count = Number(data.count || state.items.length || 0);
    state.error = "";
  } catch (error) {
    state.items = [];
    state.count = 0;
    state.error = "No se pudo buscar";
  } finally {
    state.loading = false;
    refreshMediaSearchDom(folderId);
  }
}

function ensureActionModal() {
  let modal = document.getElementById("itemActionModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "itemActionModal";
    modal.className = "item-action-modal";
    document.body.appendChild(modal);
  }
  return modal;
}

function closeItemActionModal() {
  if (itemActionBusy) return;
  actionModalItem = null;
  itemActionError = "";
  deleteConfirmMode = false;
  resetCustomMoveState();
  renderActionModal();
}

function resetCustomMoveState() {
  customMoveState = {
    open: false,
    loading: false,
    error: "",
    parts: [],
    items: [],
    path: ""
  };
}

function customMovePartsValue(parts) {
  return escapeHtml(JSON.stringify(Array.isArray(parts) ? parts : []));
}

function readCustomMoveParts(button) {
  try {
    const parsed = JSON.parse(button.dataset.customMoveParts || "[]");
    return Array.isArray(parsed) ? parsed.map((part) => String(part)) : [];
  } catch (error) {
    return [];
  }
}

function renderCustomMovePanel() {
  const parts = Array.isArray(customMoveState.parts) ? customMoveState.parts : [];
  const items = Array.isArray(customMoveState.items) ? customMoveState.items : [];
  const disabled = itemActionBusy ? "disabled" : "";
  const breadcrumbs = [
    `<button class="custom-move-crumb" type="button" data-custom-move-dir data-custom-move-parts="[]" ${disabled}>Media</button>`,
    ...parts.map((part, index) => {
      const crumbParts = parts.slice(0, index + 1);
      return `<button class="custom-move-crumb" type="button" data-custom-move-dir data-custom-move-parts="${customMovePartsValue(crumbParts)}" ${disabled}>${escapeHtml(part)}</button>`;
    })
  ].join("");
  const parentParts = parts.slice(0, -1);
  const upButton = parts.length
    ? `<button class="custom-move-up" type="button" data-custom-move-dir data-custom-move-parts="${customMovePartsValue(parentParts)}" ${disabled}>Subir</button>`
    : "";
  const list = customMoveState.loading
    ? `<div class="custom-move-empty">Cargando...</div>`
    : customMoveState.error
      ? `<div class="custom-move-empty is-error">${escapeHtml(customMoveState.error)}</div>`
      : items.length
        ? items.map((item) => {
          const nextParts = [...parts, item.name];
          return `
            <button class="custom-move-row" type="button" data-custom-move-dir data-custom-move-parts="${customMovePartsValue(nextParts)}" ${disabled}>
              <span class="custom-move-folder" aria-hidden="true">&#128193;</span>
              <span class="custom-move-name">${escapeHtml(item.name)}</span>
              <span class="custom-move-arrow" aria-hidden="true">›</span>
            </button>
          `;
        }).join("")
        : `<div class="custom-move-empty">Sin carpetas</div>`;

  return `
    <div class="custom-move-panel">
      <div class="custom-move-tools">
        <div class="custom-move-breadcrumbs">${breadcrumbs}</div>
        ${upButton}
      </div>
      <div class="custom-move-current" title="${escapeHtml(customMoveState.path || mediaRootPath)}">${escapeHtml(customMoveState.path || mediaRootPath)}</div>
      <div class="custom-move-list">${list}</div>
      <div class="custom-move-footer">
        <button class="item-action-button soft" type="button" data-custom-move-back ${disabled}>Volver</button>
        <button class="item-action-button output-destination" type="button" data-custom-move-run ${disabled}>Mover aqui</button>
      </div>
    </div>
  `;
}

function closeCustomMoveSelector() {
  if (itemActionBusy) return;
  resetCustomMoveState();
  itemActionError = "";
  renderActionModal();
}

function openCustomMoveSelector() {
  if (!actionModalItem || itemActionBusy) return;
  deleteConfirmMode = false;
  itemActionError = "";
  customMoveState = {
    open: true,
    loading: true,
    error: "",
    parts: [],
    items: [],
    path: mediaRootPath
  };
  renderActionModal();
  loadCustomMoveFolder([]);
}

async function loadCustomMoveFolder(parts = []) {
  if (!customMoveState.open || itemActionBusy) return;
  const cleanParts = Array.isArray(parts) ? parts.map((part) => String(part)) : [];
  customMoveState = {
    ...customMoveState,
    loading: true,
    error: "",
    parts: cleanParts
  };
  renderActionModal();

  try {
    const params = new URLSearchParams({
      v: "seguimiento_move_browse",
      t: String(Date.now())
    });
    cleanParts.forEach((part) => params.append("part", part));
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    customMoveState = {
      open: true,
      loading: false,
      error: "",
      parts: Array.isArray(data.parts) ? data.parts : cleanParts,
      items: Array.isArray(data.items) ? data.items : [],
      path: data.path || mediaRootPath
    };
  } catch (error) {
    customMoveState = {
      ...customMoveState,
      loading: false,
      error: error.message || "No se pudo abrir"
    };
  }
  renderActionModal();
}

function updateRenameModeButton() {
  if (!renameModeButton) return;
  renameModeButton.classList.toggle("is-active", renameModeActive);
  renameModeButton.setAttribute("aria-pressed", renameModeActive ? "true" : "false");
}

function toggleRenameMode() {
  if (renameBusy) return;
  renameModeActive = !renameModeActive;
  if (!renameModeActive) {
    renameModalItem = null;
    renameError = "";
  }
  updateRenameModeButton();
  renderRenameModal();
  render(lastData);
}

function ensureRenameModal() {
  let modal = document.getElementById("itemRenameModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "itemRenameModal";
    modal.className = "item-action-modal rename-modal";
    document.body.appendChild(modal);
  }
  return modal;
}

function closeRenameModal() {
  if (renameBusy) return;
  renameModalItem = null;
  renameError = "";
  renameInputValue = "";
  renderRenameModal();
}

function renameSelectionEnd(name, kind) {
  if (kind === "folder") return String(name || "").length;
  const text = String(name || "");
  const dot = text.lastIndexOf(".");
  return dot > 0 ? dot : text.length;
}

function renderRenameModal() {
  const modal = ensureRenameModal();
  if (!renameModalItem) {
    modal.className = "item-action-modal rename-modal";
    modal.innerHTML = "";
    modal.onclick = null;
    return;
  }

  const name = renameModalItem.name || renameModalItem.parts[renameModalItem.parts.length - 1] || "";
  modal.className = "item-action-modal rename-modal is-open";
  modal.innerHTML = `
    <form class="item-action-sheet rename-sheet" role="dialog" aria-modal="true" aria-labelledby="renameTitle" data-rename-form>
      <div class="sheet-grip" aria-hidden="true"></div>
      <div class="item-action-head">
        <div class="item-action-title-wrap">
          <div class="item-action-kicker">Renombrar</div>
          <h2 id="renameTitle">${escapeHtml(name)}</h2>
        </div>
        <button class="sheet-close" type="button" data-rename-close aria-label="Cerrar">x</button>
      </div>
      ${renameError ? `<div class="item-action-error">${escapeHtml(renameError)}</div>` : ""}
      <label class="rename-field">
        <span>Nuevo nombre</span>
        <input class="rename-input" name="renameName" value="${escapeHtml(renameInputValue || name)}" autocomplete="off" spellcheck="false" ${renameBusy ? "disabled" : ""}>
      </label>
      <div class="item-action-buttons">
        <button class="item-action-button soft" type="button" data-rename-close ${renameBusy ? "disabled" : ""}>Cancelar</button>
        <button class="item-action-button rename-submit" type="submit" ${renameBusy ? "disabled" : ""}>${renameBusy ? "Renombrando..." : "Renombrar"}</button>
      </div>
    </form>
  `;

  modal.onclick = (event) => {
    if (event.target === modal) closeRenameModal();
  };
  modal.querySelectorAll("[data-rename-close]").forEach((button) => {
    button.addEventListener("click", closeRenameModal);
  });
  modal.querySelector("[data-rename-form]")?.addEventListener("submit", runRenameItem);
}

function focusRenameInput() {
  const input = document.querySelector("#itemRenameModal .rename-input");
  if (!input) return;
  input.focus();
  const end = renameSelectionEnd(input.value, renameModalItem?.kind || "file");
  try {
    input.setSelectionRange(0, end);
  } catch (error) {}
}

function openRenameModal(button) {
  if (renameBusy) return;
  let parts = [];
  try {
    parts = JSON.parse(button.dataset.itemParts || "[]");
  } catch (error) {
    parts = [];
  }
  const target = makeActionTarget(button.dataset.itemSource, parts, button.dataset.itemKind || "file");
  if (!target) return;

  renameModalItem = {
    ...target,
    name: button.dataset.itemName || target.parts[target.parts.length - 1] || ""
  };
  renameInputValue = renameModalItem.name;
  renameError = "";
  renderRenameModal();
  requestAnimationFrame(focusRenameInput);
}

function bindItemRenameButtons(root = foldersEl) {
  root.querySelectorAll("[data-item-rename]").forEach((button) => {
    button.addEventListener("click", () => openRenameModal(button));
  });
}

async function runRenameItem(event) {
  event?.preventDefault();
  if (!renameModalItem || renameBusy) return;
  const input = document.querySelector("#itemRenameModal .rename-input");
  const newName = String(input?.value || "").trim();
  if (!newName) {
    renameError = "Escribe un nombre";
    renderRenameModal();
    requestAnimationFrame(focusRenameInput);
    return;
  }

  const soundJob = finishSoundJob("item-rename", `${renameModalItem.source}:${renameModalItem.parts.join("/")}`);
  prepareFinishSound();
  renameBusy = true;
  renameInputValue = newName;
  renameError = "";
  renderRenameModal();

  try {
    const params = new URLSearchParams({
      v: "seguimiento_item_rename",
      source: renameModalItem.source,
      name: newName,
      t: String(Date.now())
    });
    renameModalItem.parts.forEach((part) => params.append("part", part));
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    openFolderDetails.clear();
    openTextDetails.clear();
    folderChildrenCache.clear();
    clearSearchForSource(renameModalItem.source);
    renameModeActive = false;
    renameModalItem = null;
    renameInputValue = "";
    updateRenameModeButton();
    renderRenameModal();
    statusText.textContent = data.message || "Renombrado";
    await loadStatus({ skipEntrySound: true });
    playFinishSound(soundJob);
  } catch (error) {
    renameError = error.message || "No se pudo renombrar";
  } finally {
    renameBusy = false;
    renderRenameModal();
    render(lastData);
  }
}

function renderActionModal() {
  const modal = ensureActionModal();
  if (!actionModalItem) {
    modal.className = "item-action-modal";
    modal.innerHTML = "";
    modal.onclick = null;
    return;
  }

  const name = actionModalItem.name || actionModalItem.parts[actionModalItem.parts.length - 1] || "";
  const canSendToWorkshop = actionModalItem.kind === "video" && actionModalItem.mode !== "move";
  const showMoveActions = actionModalItem.mode === "move" || !canSendToWorkshop;
  const showCustomMove = showMoveActions && customMoveState.open;
  modal.className = "item-action-modal is-open";
  modal.innerHTML = `
    <div class="item-action-sheet ${showCustomMove ? "has-custom-move" : ""}" role="dialog" aria-modal="true" aria-labelledby="itemActionTitle">
      <div class="sheet-grip" aria-hidden="true"></div>
      <div class="item-action-head">
        <div class="item-action-title-wrap">
          <div class="item-action-kicker">Acciones</div>
          <h2 id="itemActionTitle">${escapeHtml(name)}</h2>
        </div>
        <button class="sheet-close" type="button" data-action-close aria-label="Cerrar">x</button>
      </div>
      ${itemActionError ? `<div class="item-action-error">${escapeHtml(itemActionError)}</div>` : ""}
      ${showCustomMove ? renderCustomMovePanel() : deleteConfirmMode ? `
        <div class="delete-confirm">Confirmar eliminacion</div>
        <div class="item-action-buttons">
          <button class="item-action-button soft" type="button" data-action-cancel-delete ${itemActionBusy ? "disabled" : ""}>Cancelar</button>
          <button class="item-action-button danger" type="button" data-action-run="delete" ${itemActionBusy ? "disabled" : ""}>Eliminar</button>
        </div>
      ` : `
        <div class="item-action-buttons">
          ${showMoveActions ? `
          <button class="item-action-button move" type="button" data-action-run="move_movies" ${itemActionBusy ? "disabled" : ""}>Mover a Movies 🎬</button>
          <button class="item-action-button move" type="button" data-action-run="move_tv" ${itemActionBusy ? "disabled" : ""}>Mover a TV 🎬</button>
          <button class="item-action-button move" type="button" data-action-run="move_infantiles" ${itemActionBusy ? "disabled" : ""}>Mover a Infantiles 🎬</button>
          <button class="item-action-button move" type="button" data-action-run="move_movies_automatizacion" ${itemActionBusy ? "disabled" : ""}>Mover a Movies Automatizacion</button>
          <button class="item-action-button move" type="button" data-action-run="move_complete" ${itemActionBusy ? "disabled" : ""}>Mover a Complete</button>
          <button class="item-action-button move" type="button" data-action-run="move_queue" ${itemActionBusy ? "disabled" : ""}>Mover a Queue</button>
          <button class="item-action-button move" type="button" data-action-run="move_repetidas_error" ${itemActionBusy ? "disabled" : ""}>Mover a Repetidas / Error</button>
          <button class="item-action-button move" type="button" data-action-run="move_hospital" ${itemActionBusy ? "disabled" : ""}>Mover a Hospital</button>
          <button class="item-action-button output-destination custom-move-trigger" type="button" data-custom-move-open ${itemActionBusy ? "disabled" : ""}>Mover a...</button>
          ` : ""}
          ${canSendToWorkshop ? `
            <button class="item-action-button marker" type="button" data-workshop-select="ref" ${itemActionBusy ? "disabled" : ""}>Video Bueno</button>
            <button class="item-action-button marker" type="button" data-workshop-select="esp" ${itemActionBusy ? "disabled" : ""}>Audio Español</button>
            <button class="item-action-button trailer-clean" type="button" data-trailer-open ${itemActionBusy ? "disabled" : ""}>Editar Video</button>
          ` : ""}
          ${showMoveActions ? `<button class="item-action-button danger delete-separated" type="button" data-action-delete-start ${itemActionBusy ? "disabled" : ""}>Eliminar</button>` : ""}
        </div>
      `}
    </div>
  `;

  modal.onclick = (event) => {
    if (event.target === modal) closeItemActionModal();
  };
  modal.querySelector("[data-action-close]")?.addEventListener("click", closeItemActionModal);
  modal.querySelector("[data-action-delete-start]")?.addEventListener("click", () => {
    deleteConfirmMode = true;
    itemActionError = "";
    renderActionModal();
  });
  modal.querySelector("[data-action-cancel-delete]")?.addEventListener("click", () => {
    deleteConfirmMode = false;
    itemActionError = "";
    renderActionModal();
  });
  modal.querySelectorAll("[data-action-run]").forEach((button) => {
    button.addEventListener("click", () => runItemAction(button.dataset.actionRun));
  });
  modal.querySelector("[data-custom-move-open]")?.addEventListener("click", openCustomMoveSelector);
  modal.querySelectorAll("[data-custom-move-back]").forEach((button) => {
    button.addEventListener("click", closeCustomMoveSelector);
  });
  modal.querySelectorAll("[data-custom-move-dir]").forEach((button) => {
    button.addEventListener("click", () => loadCustomMoveFolder(readCustomMoveParts(button)));
  });
  modal.querySelector("[data-custom-move-run]")?.addEventListener("click", runCustomMoveAction);
  modal.querySelectorAll("[data-workshop-select]").forEach((button) => {
    button.addEventListener("click", () => selectWorkshopVideo(button.dataset.workshopSelect));
  });
  modal.querySelector("[data-trailer-open]")?.addEventListener("click", openTrailerTrackModal);
}

function openItemActionModal(button) {
  if (itemActionBusy) return;
  const hadSearch = hasActiveSearch(button.dataset.itemSource);
  clearSearchForSource(button.dataset.itemSource);
  let parts = [];
  try {
    parts = JSON.parse(button.dataset.itemParts || "[]");
  } catch (error) {
    parts = [];
  }
  const target = makeActionTarget(button.dataset.itemSource, parts, button.dataset.itemKind || "file");
  if (!target) return;

  actionModalItem = {
    ...target,
    name: button.dataset.itemName || target.parts[target.parts.length - 1] || "",
    mode: button.dataset.itemMode || "full"
  };
  itemActionError = "";
  deleteConfirmMode = false;
  resetCustomMoveState();
  renderActionModal();
  if (hadSearch) render(lastData);
}

function bindItemActionNames(root = foldersEl) {
  root.querySelectorAll("[data-item-action]").forEach((button) => {
    button.addEventListener("click", () => openItemActionModal(button));
  });
}

function ensureTrailerModal() {
  let modal = document.getElementById("trailerTrackModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "trailerTrackModal";
    modal.className = "trailer-track-modal";
    document.body.appendChild(modal);
  }
  return modal;
}

function closeTrailerModal() {
  if (trailerActionBusy) return;
  trailerModalItem = null;
  trailerModalInfo = null;
  trailerModalLoading = false;
  trailerModalError = "";
  trailerModalStatus = "";
  trailerVideoSelection = "";
  trailerSubtitleSelection = new Set();
  trailerAudioSelection = "";
  trailerBusyMode = "";
  renderTrailerModal();
}

function trailerItemParams(version) {
  const params = new URLSearchParams({
    v: version,
    source: trailerModalItem.source,
    t: String(Date.now())
  });
  trailerModalItem.parts.forEach((part) => params.append("part", part));
  return params;
}

function trackLabelText(item) {
  if (typeof item === "string") return item;
  return String(item?.label || "");
}

function trackCountText(item) {
  const raw = item?.count;
  if (raw === null || raw === undefined || raw === "") return "";
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return "";
  return String(Math.round(value));
}

function renderTrailerRows(title, rows, mode = "") {
  const arr = Array.isArray(rows) ? rows : [];
  if (!arr.length) {
    return `
      <div class="trailer-track-row is-muted">
        <b>${escapeHtml(title)}</b>
        <span>No detectado</span>
      </div>
    `;
  }

  return arr.map((item, index) => {
    const id = String(item?.id || "");
    const isVideo = mode === "video";
    const isAudio = mode === "audio";
    const isSubtitle = mode === "subtitle";
    const canSelect = Boolean(
      (isVideo && item?.selectable && id)
      || (isAudio && item?.convertible && id)
      || (isSubtitle && item?.removable && id)
    );
    const selected = canSelect && (
      isVideo ? trailerVideoSelection === id
      : isAudio ? trailerAudioSelection === id
      : trailerSubtitleSelection.has(id)
    );
    const countText = isSubtitle ? trackCountText(item) : "";
    return `
      <button
        class="trailer-track-row ${isVideo ? "is-video" : ""} ${isAudio ? "is-audio" : ""} ${isSubtitle ? "is-subtitle" : ""} ${canSelect ? "is-selectable" : ""} ${selected ? "is-selected" : ""}"
        type="button"
        ${canSelect && isVideo ? `data-trailer-video="${escapeHtml(id)}"` : ""}
        ${canSelect && isAudio ? `data-trailer-audio="${escapeHtml(id)}"` : ""}
        ${canSelect && isSubtitle ? `data-trailer-subtitle="${escapeHtml(id)}"` : ""}
        ${canSelect ? "" : "disabled"}
      >
        <b>${escapeHtml(`${title} ${index + 1}`)}</b>
        <span class="trailer-track-label">${escapeHtml(trackLabelText(item) || "No detectado")}</span>
        ${countText ? `<span class="trailer-track-count">${escapeHtml(countText)}</span>` : ""}
      </button>
    `;
  }).join("");
}

function renderTrailerModal() {
  const modal = ensureTrailerModal();
  if (!trailerModalItem) {
    modal.className = "trailer-track-modal";
    modal.innerHTML = "";
    modal.onclick = null;
    return;
  }

  const name = trailerModalItem.name || trailerModalItem.parts[trailerModalItem.parts.length - 1] || "";
  const info = trailerModalInfo || {};
  const selectedCount = trailerSubtitleSelection.size;
  const hasSelectedVideo = Boolean(trailerVideoSelection);
  const hasSelectedAudio = Boolean(trailerAudioSelection);
  const hasSelectedTracks = hasSelectedVideo || hasSelectedAudio || selectedCount > 0;
  modal.className = "trailer-track-modal is-open";
  modal.innerHTML = `
    <div class="trailer-track-sheet" role="dialog" aria-modal="true" aria-labelledby="trailerTrackTitle">
      <div class="item-action-head">
        <div class="item-action-title-wrap">
          <div class="item-action-kicker">Editar Video</div>
          <h2 id="trailerTrackTitle">${escapeHtml(name)}</h2>
        </div>
        <button class="sheet-close" type="button" data-trailer-close aria-label="Cerrar">x</button>
      </div>
      ${trailerModalError ? `<div class="item-action-error">${escapeHtml(trailerModalError)}</div>` : ""}
      ${trailerModalStatus ? `<div class="trailer-track-status ${trailerActionBusy ? "is-working" : ""}">${escapeHtml(trailerModalStatus)}</div>` : ""}
      ${trailerModalLoading ? `
        <div class="trailer-track-loading">Leyendo pistas...</div>
      ` : `
        <div class="trailer-track-list">
          ${renderTrailerRows("Video", info.video, "video")}
          ${renderTrailerRows("Audio", info.audio, "audio")}
          ${renderTrailerRows("Subtitulos", info.subtitles, "subtitle")}
        </div>
        <button class="trailer-chapters-10m ${hasSelectedVideo ? "" : "is-hidden"}" type="button" data-trailer-chapters ${trailerActionBusy ? "disabled" : ""}>
          ${trailerActionBusy && trailerBusyMode === "chapters" ? "Aplicando..." : "Capitulos cada 10 min"}
        </button>
        <button class="trailer-audio-convert ${hasSelectedAudio ? "" : "is-hidden"}" type="button" data-trailer-audio-convert ${trailerActionBusy ? "disabled" : ""}>
          ${trailerActionBusy && trailerBusyMode === "audio" ? "Convirtiendo..." : "Convertir a AC-3 5.1"}
        </button>
        <button class="trailer-delete-selected ${selectedCount ? "" : "is-hidden"}" type="button" data-trailer-delete ${trailerActionBusy ? "disabled" : ""}>
          ${trailerActionBusy && trailerBusyMode === "subtitle" ? "Eliminando..." : `Eliminar ${selectedCount}`}
        </button>
        <button class="trailer-rename-language ${hasSelectedTracks ? "" : "is-hidden"}" type="button" data-trailer-language ${trailerActionBusy ? "disabled" : ""}>
          ${trailerActionBusy && trailerBusyMode === "language" ? "Renombrando..." : "Renombrar idioma a ES"}
        </button>
      `}
    </div>
  `;

  modal.onclick = (event) => {
    if (event.target === modal) closeTrailerModal();
  };
  modal.querySelector("[data-trailer-close]")?.addEventListener("click", closeTrailerModal);
  modal.querySelectorAll("[data-trailer-video]").forEach((button) => {
    button.addEventListener("click", () => {
      if (trailerActionBusy) return;
      const id = String(button.dataset.trailerVideo || "");
      if (!id) return;
      trailerVideoSelection = trailerVideoSelection === id ? "" : id;
      trailerModalError = "";
      renderTrailerModal();
    });
  });
  modal.querySelectorAll("[data-trailer-audio]").forEach((button) => {
    button.addEventListener("click", () => {
      if (trailerActionBusy) return;
      const id = String(button.dataset.trailerAudio || "");
      if (!id) return;
      trailerAudioSelection = trailerAudioSelection === id ? "" : id;
      trailerModalError = "";
      renderTrailerModal();
    });
  });
  modal.querySelectorAll("[data-trailer-subtitle]").forEach((button) => {
    button.addEventListener("click", () => {
      if (trailerActionBusy) return;
      const id = String(button.dataset.trailerSubtitle || "");
      if (!id) return;
      if (trailerSubtitleSelection.has(id)) {
        trailerSubtitleSelection.delete(id);
      } else {
        trailerSubtitleSelection.add(id);
      }
      trailerModalError = "";
      renderTrailerModal();
    });
  });
  modal.querySelector("[data-trailer-chapters]")?.addEventListener("click", applyTrailerChapters);
  modal.querySelector("[data-trailer-audio-convert]")?.addEventListener("click", convertTrailerAudio);
  modal.querySelector("[data-trailer-delete]")?.addEventListener("click", deleteTrailerSubtitles);
  modal.querySelector("[data-trailer-language]")?.addEventListener("click", renameTrailerLanguage);
}

async function openTrailerTrackModal() {
  if (!actionModalItem || actionModalItem.kind !== "video" || itemActionBusy) return;
  trailerModalItem = {
    ...actionModalItem,
    parts: [...actionModalItem.parts]
  };
  trailerModalInfo = null;
  trailerModalLoading = true;
  trailerActionBusy = false;
  trailerModalError = "";
  trailerModalStatus = "";
  trailerVideoSelection = "";
  trailerSubtitleSelection = new Set();
  trailerAudioSelection = "";
  trailerBusyMode = "";
  actionModalItem = null;
  deleteConfirmMode = false;
  renderActionModal();
  renderTrailerModal();

  try {
    const response = await fetch(`/api?${trailerItemParams("seguimiento_trailer_info").toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    trailerModalInfo = data.info || {};
    trailerModalStatus = "";
  } catch (error) {
    trailerModalError = error.message || "No pude leer pistas";
  } finally {
    trailerModalLoading = false;
    renderTrailerModal();
  }
}

function startTrailerJobPolling() {
  if (!trailerJobTimer) {
    trailerJobTimer = setInterval(pollTrailerJob, 1000);
  }
  pollTrailerJob();
}

function stopTrailerJobPolling() {
  if (trailerJobTimer) {
    clearInterval(trailerJobTimer);
    trailerJobTimer = null;
  }
}

async function pollTrailerJob() {
  const state = readTrailerJobState();
  if (!state.job) {
    stopTrailerJobPolling();
    renderHeaderWorkshop();
    return;
  }

  try {
    const response = await fetch(`/api?v=seguimiento_trailer_job_status&job=${encodeURIComponent(state.job)}&t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    const nextState = {
      ...state,
      job: data.job || state.job,
      status: data.status || state.status || "running",
      action: data.action || state.action || "",
      label: data.label || state.label || "",
      progress: data.progress || state.progress || null,
      result: data.result || null,
      error: data.error || ""
    };
    saveTrailerJobState(nextState);
    renderHeaderWorkshop();

    if (nextState.status !== "running") {
      stopTrailerJobPolling();
      const ok = nextState.result?.ok !== false && nextState.status !== "error";
      statusText.textContent = ok
        ? (nextState.result?.message || "Proceso terminado")
        : (nextState.result?.error || nextState.error || "Proceso con aviso");
      if (nextState.soundJob && !nextState.soundDone) {
        nextState.soundDone = true;
        saveTrailerJobState(nextState);
        playFinishSound(`${nextState.soundJob}:${nextState.status}`);
      }
      folderChildrenCache.clear();
      await loadStatus({ skipEntrySound: true });
      setTimeout(() => {
        const current = readTrailerJobState();
        if (current.job === nextState.job && current.status !== "running") {
          clearTrailerJobState();
          renderHeaderWorkshop();
        }
      }, 1400);
    }
  } catch (error) {
    const nextState = {
      ...state,
      error: "No se pudo leer el proceso",
      progress: state.progress || { phase: state.phase || "trailer", percent: 0, label: state.label || "Procesando" }
    };
    saveTrailerJobState(nextState);
    renderHeaderWorkshop();
  }
}

function resumeTrailerJobIfNeeded() {
  const state = readTrailerJobState();
  if (state.job && state.status === "running" && !trailerJobTimer) {
    startTrailerJobPolling();
  }
}

async function startTrailerBackgroundJob(kind) {
  if (!trailerModalItem || trailerActionBusy) return;
  const isAudio = kind === "audio";
  if (isAudio && !trailerAudioSelection) return;
  if (!isAudio && !trailerSubtitleSelection.size) return;

  const detail = isAudio ? trailerAudioSelection : [...trailerSubtitleSelection].join(",");
  const soundJob = finishSoundJob(isAudio ? "trailer-audio" : "trailer-subtitles", detail);
  const label = isAudio ? "Convirtiendo" : "Eliminando";
  const phase = isAudio ? "audio" : "subtitle";
  prepareFinishSound();
  trailerActionBusy = true;
  trailerBusyMode = isAudio ? "audio" : "subtitle";
  trailerModalError = "";
  trailerModalStatus = isAudio ? "Preparando conversion..." : "Preparando eliminado...";
  renderTrailerModal();

  try {
    const params = trailerItemParams("seguimiento_trailer_job_start");
    params.set("action", kind);
    if (isAudio) {
      params.set("id", trailerAudioSelection);
    } else {
      [...trailerSubtitleSelection].forEach((id) => params.append("id", id));
    }
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    saveTrailerJobState({
      job: data.job,
      status: data.status || "running",
      action: data.action || kind,
      phase,
      label,
      progress: data.progress || { phase, percent: 0, label },
      result: null,
      error: "",
      soundJob,
      soundDone: false
    });
    trailerActionBusy = false;
    trailerBusyMode = "";
    closeTrailerModal();
    renderHeaderWorkshop();
    statusText.textContent = isAudio ? "Convirtiendo audio" : "Eliminando subtitulos";
    startTrailerJobPolling();
  } catch (error) {
    trailerModalError = error.message || (isAudio ? "No se pudo convertir el audio" : "No se pudieron eliminar subtitulos");
    trailerModalStatus = "";
    trailerActionBusy = false;
    trailerBusyMode = "";
    renderTrailerModal();
  }
}

async function applyTrailerChapters() {
  if (!trailerModalItem || trailerActionBusy || !trailerVideoSelection) return;
  const soundJob = finishSoundJob("trailer-chapters", trailerVideoSelection);
  prepareFinishSound();
  trailerActionBusy = true;
  trailerBusyMode = "chapters";
  trailerModalError = "";
  trailerModalStatus = "Aplicando capitulos cada 10 min...";
  renderTrailerModal();

  try {
    const params = trailerItemParams("seguimiento_trailer_chapters");
    params.set("id", trailerVideoSelection);
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    trailerModalInfo = data.info || trailerModalInfo || {};
    trailerVideoSelection = "";
    trailerModalStatus = data.message || "Capitulos cada 10 min aplicados";
    folderChildrenCache.clear();
    await loadStatus({ skipEntrySound: true });
    playFinishSound(soundJob);
  } catch (error) {
    trailerModalError = error.message || "No se pudieron aplicar capitulos";
    trailerModalStatus = "";
  } finally {
    trailerActionBusy = false;
    trailerBusyMode = "";
    renderTrailerModal();
  }
}

async function convertTrailerAudio() {
  return startTrailerBackgroundJob("audio");
}

async function deleteTrailerSubtitles() {
  return startTrailerBackgroundJob("subtitle");
}

async function renameTrailerLanguage() {
  if (!trailerModalItem || trailerActionBusy || (!trailerVideoSelection && !trailerAudioSelection && !trailerSubtitleSelection.size)) return;
  const selected = [
    trailerVideoSelection ? `video:${trailerVideoSelection}` : "",
    trailerAudioSelection ? `audio:${trailerAudioSelection}` : "",
    [...trailerSubtitleSelection].join(",")
  ].filter(Boolean).join("|");
  const soundJob = finishSoundJob("trailer-language", selected);
  prepareFinishSound();
  trailerActionBusy = true;
  trailerBusyMode = "language";
  trailerModalError = "";
  trailerModalStatus = "Renombrando idioma a ES...";
  renderTrailerModal();

  try {
    const params = trailerItemParams("seguimiento_trailer_language");
    if (trailerVideoSelection) params.set("video_id", trailerVideoSelection);
    if (trailerAudioSelection) params.set("audio_id", trailerAudioSelection);
    [...trailerSubtitleSelection].forEach((id) => params.append("id", id));
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    trailerModalInfo = data.info || trailerModalInfo || {};
    trailerVideoSelection = "";
    trailerAudioSelection = "";
    trailerSubtitleSelection = new Set();
    trailerModalStatus = data.message || "Idioma renombrado a ES";
    folderChildrenCache.clear();
    await loadStatus({ skipEntrySound: true });
    playFinishSound(soundJob);
  } catch (error) {
    trailerModalError = error.message || "No se pudo renombrar el idioma";
    trailerModalStatus = "";
  } finally {
    trailerActionBusy = false;
    trailerBusyMode = "";
    renderTrailerModal();
  }
}

async function runCustomMoveAction() {
  if (!actionModalItem || itemActionBusy) return;
  const soundJob = finishSoundJob("item-move_custom", `${actionModalItem.source}:${actionModalItem.parts.join("/")}`);
  prepareFinishSound();
  itemActionBusy = true;
  itemActionError = "";
  renderActionModal();
  try {
    const params = new URLSearchParams({
      v: "seguimiento_item_action",
      action: "move_custom",
      source: actionModalItem.source,
      t: String(Date.now())
    });
    actionModalItem.parts.forEach((part) => params.append("part", part));
    (customMoveState.parts || []).forEach((part) => params.append("dest_part", part));

    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    const message = data.message || "Movido";
    actionModalItem = null;
    deleteConfirmMode = false;
    resetCustomMoveState();
    folderChildrenCache.clear();
    await loadStatus({ skipEntrySound: true });
    statusText.textContent = message;
    playFinishSound(soundJob);
  } catch (error) {
    itemActionError = error.message || "No se pudo mover";
  } finally {
    itemActionBusy = false;
    renderActionModal();
  }
}

async function runItemAction(action) {
  if (!actionModalItem || itemActionBusy) return;
  const soundJob = finishSoundJob(`item-${action}`, `${actionModalItem.source}:${actionModalItem.parts.join("/")}`);
  prepareFinishSound();
  itemActionBusy = true;
  itemActionError = "";
  renderActionModal();
  try {
    const params = new URLSearchParams({
      v: "seguimiento_item_action",
      action,
      source: actionModalItem.source,
      t: String(Date.now())
    });
    actionModalItem.parts.forEach((part) => params.append("part", part));
    if (action === "delete") params.set("confirm", "1");

    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    const message = data.message || "Hecho";
    actionModalItem = null;
    deleteConfirmMode = false;
    folderChildrenCache.clear();
    await loadStatus({ skipEntrySound: true });
    statusText.textContent = message;
    playFinishSound(soundJob);
  } catch (error) {
    itemActionError = action === "delete" ? "No se pudo eliminar" : "No se pudo mover";
  } finally {
    itemActionBusy = false;
    renderActionModal();
  }
}

function buildSelectedItemParams(version) {
  const params = new URLSearchParams({
    v: version,
    source: actionModalItem.source,
    t: String(Date.now())
  });
  actionModalItem.parts.forEach((part) => params.append("part", part));
  return params;
}

async function selectWorkshopVideo(kind) {
  if (!actionModalItem || actionModalItem.kind !== "video" || itemActionBusy) return;
  if (blockWorkshopMutationWhileRunning()) return;
  itemActionBusy = true;
  itemActionError = "";
  renderActionModal();
  try {
    const response = await fetch(`/api?${buildSelectedItemParams("seguimiento_item_video").toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    const state = readWorkshopState();
    if (blockWorkshopMutationWhileRunning(state)) {
      itemActionBusy = false;
      renderActionModal();
      return;
    }
    const key = workshopSlotKey(kind);
    const streams = Array.isArray(data.streams) ? data.streams : [];
    const streamsReady = Boolean(data.streams_ok);
    state[key] = {
      path: data.path,
      name: data.name,
      size: data.size || "",
      duration: data.duration || "",
      fps: data.fps || "",
      date: data.date || "",
      streams,
      audio: defaultWorkshopTrack(kind, streams),
      loading: !streamsReady,
      error: streamsReady ? "" : (data.streams_error || "")
    };
    state.delayHintMs = 0;
    clearWorkshopResultFields(state);
    saveWorkshopState(state);

    actionModalItem = null;
    deleteConfirmMode = false;
    if (kind === "esp") {
      activeTab = "taller";
      saveActiveTab(activeTab);
    }
    itemActionBusy = false;
    renderActionModal();
    render(lastData);
    statusText.textContent = `${workshopSlotLabel(kind)} preparado`;
    if (!streamsReady) loadWorkshopVideoDetails(kind, data.path);
  } catch (error) {
    itemActionError = "No se pudo enviar al Taller";
    itemActionBusy = false;
    renderActionModal();
  }
}

async function loadWorkshopVideoDetails(kind, path) {
  const key = workshopSlotKey(kind);
  let state = readWorkshopState();
  if (!state[key] || state[key].path !== path) return;
  state[key].loading = true;
  state[key].error = "";
  saveWorkshopState(state);
  if (activeTab === "taller") renderWorkshopOnly();

  try {
    const [infoResponse, streamsResponse] = await Promise.all([
      fetch(`/api?v=delay_audio_file_info&da=file_info&path=${encodeURIComponent(path)}&t=${Date.now()}`, { cache: "no-store" }),
      fetch(`/api?v=delay_audio_streams&da=streams&path=${encodeURIComponent(path)}&t=${Date.now()}`, { cache: "no-store" })
    ]);
    const info = await infoResponse.json();
    const streams = await streamsResponse.json();

    state = readWorkshopState();
    if (!state[key] || state[key].path !== path) return;
    if (info.ok) {
      state[key].size = info.size || state[key].size || "";
      state[key].duration = info.duration || "";
      state[key].fps = info.fps || "";
      state[key].date = info.date || "";
      state[key].name = info.name || state[key].name || "";
    }
    if (!streams.ok) {
      state[key].streams = [];
      state[key].audio = "";
      state[key].error = streams.error || "No pude leer audios";
    } else {
      state[key].streams = Array.isArray(streams.streams) ? streams.streams : [];
      state[key].audio = defaultWorkshopTrack(kind, state[key].streams);
      state[key].error = "";
    }
  } catch (error) {
    state = readWorkshopState();
    if (state[key] && state[key].path === path) {
      state[key].streams = [];
      state[key].audio = "";
      state[key].error = "No pude leer audios";
    }
  } finally {
    state = readWorkshopState();
    if (state[key] && state[key].path === path) {
      state[key].loading = false;
      saveWorkshopState(state);
      if (activeTab === "taller") render(lastData);
    }
  }
}

function setWorkshopTrack(kind, value) {
  const state = readWorkshopState();
  const key = workshopSlotKey(kind);
  if (!state[key]) return;
  if (state.status === "running" || workshopBusy) {
    statusText.textContent = "Espera a que termine Taller para cambiar la pista";
    return;
  }
  const nextValue = String(value);
  if (String(state[key].audio ?? "") === nextValue) return;
  state[key].audio = nextValue;
  clearWorkshopResultFields(state);
  saveWorkshopState(state);
  render(lastData);
}

function clearWorkshopSlot(kind) {
  const state = readWorkshopState();
  if (blockWorkshopMutationWhileRunning(state)) return;
  delete state[workshopSlotKey(kind)];
  state.delayHintMs = 0;
  clearWorkshopResultFields(state);
  saveWorkshopState(state);
  render(lastData);
}

function clearWorkshop() {
  if (blockWorkshopMutationWhileRunning()) return;
  stopWorkshopPolling();
  workshopBusy = false;
  saveWorkshopState({});
  render(lastData);
  statusText.textContent = "Taller limpio";
}

function ensureWorkshopSlotTracks() {
  const state = readWorkshopState();
  ["ref", "esp"].forEach((kind) => {
    const slot = state[workshopSlotKey(kind)];
    const hasStreams = Array.isArray(slot?.streams) && slot.streams.length > 0;
    if (slot?.path && !slot.loading && !slot.error && !hasStreams) {
      loadWorkshopVideoDetails(kind, slot.path);
    }
  });
}

async function openWorkshopPreview() {
  const state = readWorkshopState();
  workshopPreviewModalOpen = true;
  workshopPreviewLoading = false;
  workshopPreviewError = "";
  workshopPreviewData = null;
  workshopPreviewHintMs = workshopDelayHintMs(state);
  workshopPreviewPlaying = false;

  if (!state.ref?.path || !state.esp?.path) {
    renderWorkshopOnly();
    return;
  }

  workshopPreviewLoading = true;
  renderWorkshopOnly();
  try {
    const settings = workshopSettings(state);
    const params = new URLSearchParams({
      v: "delay_audio_preview",
      da: "preview",
      ref: state.ref.path,
      esp: state.esp.path,
      profile: settings.perfil === "trailer" ? "trailer" : "pelicula",
      delay_hint_ms: String(workshopPreviewHintMs),
      t: String(Date.now())
    });
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    if (!workshopPreviewModalOpen) return;
    workshopPreviewData = data;
    workshopPreviewHintMs = normalizeWorkshopDelayHintMs(data.delay_hint_ms || 0, Number(data.max_offset_ms || 60000));
    workshopPreviewError = "";
  } catch (error) {
    if (workshopPreviewModalOpen) {
      workshopPreviewError = error.message || "No pude preparar el preview";
      workshopPreviewData = null;
    }
  } finally {
    if (workshopPreviewModalOpen) {
      workshopPreviewLoading = false;
      renderWorkshopOnly();
    }
  }
}

function closeWorkshopPreview() {
  pauseWorkshopPreviewVideos();
  workshopPreviewModalOpen = false;
  workshopPreviewLoading = false;
  workshopPreviewError = "";
  renderWorkshopOnly();
}

function workshopPreviewVideos() {
  return {
    ref: foldersEl.querySelector('[data-workshop-preview-video="ref"]'),
    esp: foldersEl.querySelector('[data-workshop-preview-video="esp"]')
  };
}

function workshopPreviewWindowSec() {
  const value = Number(workshopPreviewData?.window_sec || 20);
  return Number.isFinite(value) && value > 0 ? value : 20;
}

function workshopPreviewCurrentBase() {
  const videos = workshopPreviewVideos();
  const baseHintMs = Number(workshopPreviewData?.delay_hint_ms || 0);
  const hintSec = (workshopPreviewHintMs - baseHintMs) / 1000;
  if (!videos.ref || !videos.esp) return 0;
  const base = hintSec >= 0 ? Number(videos.ref.currentTime || 0) - hintSec : Number(videos.ref.currentTime || 0);
  return Math.max(0, Math.min(workshopPreviewWindowSec(), base));
}

function workshopPreviewTargetTimes(baseSec) {
  const base = Math.max(0, Math.min(workshopPreviewWindowSec(), Number(baseSec) || 0));
  const baseHintMs = Number(workshopPreviewData?.delay_hint_ms || 0);
  const hintSec = (workshopPreviewHintMs - baseHintMs) / 1000;
  if (hintSec >= 0) {
    return { ref: base + hintSec, esp: base };
  }
  return { ref: base, esp: base - hintSec };
}

function setWorkshopPreviewTime(video, seconds) {
  if (!video) return;
  const duration = Number(video.duration || 0);
  let target = Math.max(0, Number(seconds) || 0);
  if (Number.isFinite(duration) && duration > 0) target = Math.min(Math.max(0, duration - 0.08), target);
  if (Math.abs(Number(video.currentTime || 0) - target) > 0.08) {
    try {
      video.currentTime = target;
    } catch (error) {}
  }
}

function setWorkshopPreviewBase(baseSec) {
  const videos = workshopPreviewVideos();
  const times = workshopPreviewTargetTimes(baseSec);
  setWorkshopPreviewTime(videos.ref, times.ref);
  setWorkshopPreviewTime(videos.esp, times.esp);
}

function pauseWorkshopPreviewVideos() {
  if (workshopPreviewTimer) {
    clearInterval(workshopPreviewTimer);
    workshopPreviewTimer = null;
  }
  workshopPreviewPlaying = false;
  const videos = workshopPreviewVideos();
  [videos.ref, videos.esp].forEach((video) => {
    try {
      video?.pause();
    } catch (error) {}
  });
  updateWorkshopPreviewUi();
}

function playWorkshopPreviewVideos() {
  const videos = workshopPreviewVideos();
  if (!videos.ref || !videos.esp) return;
  setWorkshopPreviewBase(workshopPreviewCurrentBase());
  workshopPreviewPlaying = true;
  [videos.ref, videos.esp].forEach((video) => {
    try {
      const promise = video.play();
      if (promise && typeof promise.catch === "function") promise.catch(() => {});
    } catch (error) {}
  });
  if (workshopPreviewTimer) clearInterval(workshopPreviewTimer);
  workshopPreviewTimer = setInterval(() => {
    if (!workshopPreviewPlaying) return;
    if (workshopPreviewCurrentBase() >= workshopPreviewWindowSec() - 0.05) {
      pauseWorkshopPreviewVideos();
      setWorkshopPreviewBase(0);
    }
  }, 120);
  updateWorkshopPreviewUi();
}

function toggleWorkshopPreviewPlayback() {
  if (workshopPreviewPlaying) {
    pauseWorkshopPreviewVideos();
  } else {
    playWorkshopPreviewVideos();
  }
}

function adjustWorkshopPreviewHint(deltaMs) {
  if (!workshopPreviewData) return;
  const base = workshopPreviewCurrentBase();
  const max = Number(workshopPreviewData.max_offset_ms || 60000);
  const relativeMax = Number(workshopPreviewData.relative_max_offset_ms || max);
  const baseHint = Number(workshopPreviewData.delay_hint_ms || 0);
  const candidate = normalizeWorkshopDelayHintMs(workshopPreviewHintMs + Number(deltaMs || 0), max);
  workshopPreviewHintMs = Math.max(baseHint - relativeMax, Math.min(baseHint + relativeMax, candidate));
  setWorkshopPreviewBase(base);
  updateWorkshopPreviewUi();
}

function resetWorkshopPreviewHint() {
  const base = workshopPreviewCurrentBase();
  workshopPreviewHintMs = 0;
  setWorkshopPreviewBase(base);
  updateWorkshopPreviewUi();
}

function updateWorkshopPreviewUi() {
  const valueEl = foldersEl.querySelector("[data-workshop-preview-value]");
  if (valueEl) valueEl.textContent = formatWorkshopDelayHint(workshopPreviewHintMs);
  const playButton = foldersEl.querySelector("[data-workshop-preview-play]");
  if (playButton) playButton.textContent = workshopPreviewPlaying ? "Pausa" : "Play";
  const max = Number(workshopPreviewData?.max_offset_ms || 60000);
  const visualMax = Math.max(1000, Math.min(max, Number(workshopPreviewData?.relative_max_offset_ms || max)));
  const relativeHint = workshopPreviewHintMs - Number(workshopPreviewData?.delay_hint_ms || 0);
  const pct = visualMax > 0 ? Math.max(-44, Math.min(44, (relativeHint / visualMax) * 44)) : 0;
  const ruler = foldersEl.querySelector("[data-workshop-preview-ruler]");
  if (ruler) ruler.style.setProperty("--preview-shift", `${-pct}%`);
}

function acceptWorkshopPreviewHint() {
  if (!workshopPreviewData) return;
  pauseWorkshopPreviewVideos();
  const state = readWorkshopState();
  if (blockWorkshopMutationWhileRunning(state)) return;
  state.delayHintMs = normalizeWorkshopDelayHintMs(workshopPreviewHintMs, Number(workshopPreviewData.max_offset_ms || 60000));
  clearWorkshopResultFields(state);
  saveWorkshopState(state);
  workshopPreviewModalOpen = false;
  statusText.textContent = "Taller listo";
  render(lastData);
}

function resetWorkshopDelayHintMain() {
  const state = readWorkshopState();
  if (blockWorkshopMutationWhileRunning(state)) return;
  state.delayHintMs = 0;
  clearWorkshopResultFields(state);
  saveWorkshopState(state);
  statusText.textContent = "Taller listo";
  render(lastData);
}

function bindWorkshopPreviewRuntime() {
  if (!workshopPreviewModalOpen || !workshopPreviewData) return;
  const videos = workshopPreviewVideos();
  [videos.ref, videos.esp].forEach((video) => {
    if (!video) return;
    video.addEventListener("loadedmetadata", () => setWorkshopPreviewBase(0), { once: true });
  });
  setWorkshopPreviewBase(0);
  updateWorkshopPreviewUi();
}

function bindWorkshop() {
  ensureWorkshopSettings();
  ensureWorkshopSlotTracks();
  foldersEl.querySelectorAll("[data-workshop-track]").forEach((button) => {
    button.addEventListener("click", () => setWorkshopTrack(button.dataset.workshopTrack, button.dataset.workshopTrackValue));
  });
  foldersEl.querySelectorAll("[data-workshop-reload-tracks]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.workshopReloadTracks;
      const state = readWorkshopState();
      const slot = state[workshopSlotKey(kind)];
      if (slot?.path) loadWorkshopVideoDetails(kind, slot.path);
    });
  });
  foldersEl.querySelectorAll("[data-workshop-clear-slot]").forEach((button) => {
    button.addEventListener("click", () => clearWorkshopSlot(button.dataset.workshopClearSlot));
  });
  foldersEl.querySelectorAll("[data-workshop-preview-open]").forEach((button) => {
    button.addEventListener("click", openWorkshopPreview);
  });
  foldersEl.querySelector("[data-workshop-preview-close]")?.addEventListener("click", closeWorkshopPreview);
  foldersEl.querySelector(".workshop-preview-modal")?.addEventListener("click", (event) => {
    if (event.target.classList.contains("workshop-preview-modal")) {
      closeWorkshopPreview();
    }
  });
  foldersEl.querySelectorAll("[data-workshop-preview-step]").forEach((button) => {
    button.addEventListener("click", () => adjustWorkshopPreviewHint(button.dataset.workshopPreviewStep));
  });
  foldersEl.querySelector("[data-workshop-preview-play]")?.addEventListener("click", toggleWorkshopPreviewPlayback);
  foldersEl.querySelector("[data-workshop-preview-reset]")?.addEventListener("click", resetWorkshopPreviewHint);
  foldersEl.querySelector("[data-workshop-preview-accept]")?.addEventListener("click", acceptWorkshopPreviewHint);
  foldersEl.querySelector("[data-workshop-preview-reset-main]")?.addEventListener("click", resetWorkshopDelayHintMain);
  foldersEl.querySelectorAll("[data-workshop-setting]").forEach((button) => {
    button.addEventListener("click", () => {
      updateWorkshopSettings({ [button.dataset.workshopSetting]: button.dataset.workshopValue }, true);
    });
  });
  foldersEl.querySelectorAll("[data-workshop-input]").forEach((input) => {
    input.addEventListener("input", () => {
      updateWorkshopSettings({ [input.dataset.workshopInput]: input.value }, false, false);
    });
    input.addEventListener("change", () => {
      updateWorkshopSettings({ [input.dataset.workshopInput]: input.value }, true, false);
    });
  });
  foldersEl.querySelector("[data-workshop-output-open]")?.addEventListener("click", () => {
    workshopOutputModalOpen = true;
    renderWorkshopOnly();
  });
  foldersEl.querySelector("[data-workshop-output-close]")?.addEventListener("click", () => {
    workshopOutputModalOpen = false;
    renderWorkshopOnly();
  });
  foldersEl.querySelector(".workshop-output-modal")?.addEventListener("click", (event) => {
    if (event.target.classList.contains("workshop-output-modal")) {
      workshopOutputModalOpen = false;
      renderWorkshopOnly();
    }
  });
  foldersEl.querySelectorAll("[data-workshop-output-path]").forEach((button) => {
    button.addEventListener("click", () => {
      workshopOutputModalOpen = false;
      updateWorkshopSettings({ carpeta_salida: button.dataset.workshopOutputPath }, true);
    });
  });
  foldersEl.querySelector("[data-workshop-run]")?.addEventListener("click", runWorkshop);
  bindWorkshopPreviewRuntime();
}

async function runWorkshop() {
  if (workshopBusy) return;
  const state = readWorkshopState();
  if (blockWorkshopMutationWhileRunning(state)) return;
  if (!workshopReady(state)) {
    statusText.textContent = "Faltan videos o pistas";
    return;
  }
  const needsFpsCorrection = workshopMetaAlerts(state).fpsMismatch;
  const requestedMode = workshopSettings(state).modo === "medir" ? "medir" : "exportar";

  stopWorkshopPolling();
  workshopBusy = true;
  prepareFinishSound();
  delete state.job;
  delete state.soundJob;
  state.soundDone = false;
  state.status = "running";
  state.result = null;
  state.rows = [];
  state.progress = needsFpsCorrection
    ? { phase: "fps", percent: 0, label: "FPS" }
    : { phase: "starting", percent: 0, label: "Inicio" };
  state.requested_mode = requestedMode;
  state.error = "";
  saveWorkshopState(state);
  render(lastData);

  try {
    await flushWorkshopSettingsSave();
    const params = new URLSearchParams({
      v: "delay_audio_start",
      da: "start",
      ref: state.ref.path,
      esp: state.esp.path,
      ref_audio: String(state.ref.audio),
      esp_audio: String(state.esp.audio),
      delay_hint_ms: String(workshopDelayHintMs(state)),
      t: String(Date.now())
    });
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);

    const nextState = readWorkshopState();
    nextState.job = data.job;
    nextState.soundJob = `workshop:${data.job}`;
    nextState.soundDone = false;
    nextState.status = "running";
    nextState.result = null;
    nextState.rows = [];
    nextState.requested_mode = data.requested_mode === "medir" || data.requested_mode === "exportar"
      ? data.requested_mode
      : requestedMode;
    nextState.progress = needsFpsCorrection
      ? { phase: "fps", percent: 0, label: "FPS" }
      : { phase: "measure", percent: 0, label: "Midiendo" };
    saveWorkshopState(nextState);
    statusText.textContent = needsFpsCorrection ? "Taller corrigiendo FPS" : "Taller midiendo";
    startWorkshopPolling();
  } catch (error) {
    const nextState = readWorkshopState();
    nextState.status = "error";
    nextState.error = error.message || "No se pudo ejecutar";
    nextState.result = { ok: false, error: nextState.error };
    nextState.progress = { phase: "error", percent: 100, label: "Aviso" };
    delete nextState.soundJob;
    nextState.soundDone = false;
    saveWorkshopState(nextState);
    statusText.textContent = "No se pudo ejecutar Taller";
  } finally {
    workshopBusy = false;
    render(lastData);
  }
}

function startWorkshopPolling() {
  if (!workshopTimer) {
    const state = readWorkshopState();
    const generation = ++workshopPollGeneration;
    const jobId = state.job || "";
    workshopTimer = setInterval(() => pollWorkshopJob(generation, jobId), 2500);
    pollWorkshopJob(generation, jobId);
  }
}

function stopWorkshopPolling() {
  workshopPollGeneration += 1;
  if (workshopTimer) {
    clearInterval(workshopTimer);
    workshopTimer = null;
  }
}

async function pollWorkshopJob(generation = workshopPollGeneration, expectedJob = "") {
  if (generation !== workshopPollGeneration || workshopPollInFlight) return;
  const state = readWorkshopState();
  if (!state.job) {
    stopWorkshopPolling();
    return;
  }
  const jobId = String(expectedJob || state.job);
  if (String(state.job) !== jobId) return;
  const requestId = ++workshopPollRequestId;
  workshopPollInFlight = requestId;

  try {
    const response = await fetch(`/api?v=delay_audio_status&da=status&job=${encodeURIComponent(jobId)}&t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      const error = new Error(data.error || `HTTP ${response.status}`);
      error.workshopJobMissing = data.ok === false && /no encuentro ese trabajo/i.test(String(data.error || ""));
      throw error;
    }

    const nextState = readWorkshopState();
    if (generation !== workshopPollGeneration || String(nextState.job || "") !== jobId) return;
    nextState.job = data.job || nextState.job;
    nextState.status = data.status || "";
    nextState.rows = Array.isArray(data.rows) ? data.rows : [];
    nextState.result = data.result || null;
    nextState.progress = data.progress || null;
    if (data.requested_mode === "medir" || data.requested_mode === "exportar") {
      nextState.requested_mode = data.requested_mode;
    }
    nextState.log = data.log || "";
    nextState.error = data.error || "";
    saveWorkshopState(nextState);
    renderHeaderWorkshop();

    if (data.status !== "running") {
      stopWorkshopPolling();
      const hybridInfo = hybridWorkshopResultInfo(data.result);
      statusText.textContent = hybridInfo
        ? (hybridInfo.verified ? "Taller verificado" : hybridInfo.technical ? "Taller con error" : "Taller bloqueado por seguridad")
        : data.result?.ok ? "Taller terminado" : "Taller con aviso";
      if (nextState.soundJob && !nextState.soundDone) {
        nextState.soundDone = true;
        saveWorkshopState(nextState);
        playFinishSound(`${nextState.soundJob}:${data.status || "done"}`);
      }
    }
    if (activeTab === "taller") render(lastData);
  } catch (error) {
    const nextState = readWorkshopState();
    if (generation !== workshopPollGeneration || String(nextState.job || "") !== jobId) return;
    if (error.workshopJobMissing) {
      nextState.status = "error";
      nextState.error = "El trabajo ya no está disponible";
      nextState.result = { ok: false, error: nextState.error };
      nextState.progress = { phase: "error", percent: 100, label: "Aviso" };
      stopWorkshopPolling();
      statusText.textContent = "El trabajo de Taller ya no está disponible";
    } else {
      nextState.error = "No se pudo leer el estado";
    }
    saveWorkshopState(nextState);
    renderHeaderWorkshop();
    if (activeTab === "taller") render(lastData);
  } finally {
    if (workshopPollInFlight === requestId) workshopPollInFlight = 0;
  }
}

function resumeWorkshopIfNeeded() {
  const state = readWorkshopState();
  if (state.job && state.status === "running" && !workshopTimer) {
    startWorkshopPolling();
  }
}

function render(data) {
  if (!data) return;
  const sections = getSections(data);
  if (!sections.some((section) => section.id === activeTab)) {
    activeTab = sections[0]?.id || "movies";
    saveActiveTab(activeTab);
  }

  renderHeaderWorkshop();
  resumeWorkshopIfNeeded();
  resumeTrailerJobIfNeeded();
  renderTabs(data);
  const section = getActiveSection(data);
  if (section?.id === "taller") {
    foldersEl.innerHTML = renderWorkshop();
    bindWorkshop();
    return;
  }
  const watchCards = ["movies", "tv"].includes(activeTab)
    ? `${renderArrStatusCard(data.arr_status)}${renderQbitStatusCard(data.qbit_status)}`
    : "";
  foldersEl.innerHTML = `${watchCards}${(section?.folders || []).map(renderFolder).join("")}`;
  bindWatchCardToggles();
  bindQbitActions();
  bindArrWorkersButton();
  bindMediaSearchControls();
  bindFolderDetailToggles();
  bindTextDetailToggles();
  bindItemRenameButtons();
  bindItemActionNames();
}

async function toggleArrWorkers() {
  if (arrWorkersBusy) return;
  const nextEnabled = arrWorkersEnabled() ? "0" : "1";
  const soundJob = finishSoundJob("arr-workers", nextEnabled);
  prepareFinishSound();
  arrWorkersBusy = true;
  render(lastData);
  try {
    const response = await fetch(`/api?v=arr_workers_set&enabled=${nextEnabled}&t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
    if (lastData && data.arr_workers) lastData.arr_workers = data.arr_workers;
    await loadStatus({ skipEntrySound: true });
    playFinishSound(soundJob);
  } catch (error) {
    statusText.textContent = "No se pudo cambiar ON/OFF";
  } finally {
    arrWorkersBusy = false;
    render(lastData);
  }
}

function statusSectionId() {
  if (activeTab === "tv") return "tv";
  if (activeTab === "trailers") return "trailers";
  if (activeTab === "taller") return "taller";
  return "movies";
}

async function loadStatus(options = {}) {
  const automatic = Boolean(options.automatic);
  const skipEntrySound = Boolean(options.skipEntrySound);
  const sectionId = statusSectionId();
  if (automatic && (sectionId === "taller" || document.hidden || anyMediaSearchOpen())) return;
  if (statusLoadInProgress) return;

  statusLoadInProgress = true;
  refreshButton.disabled = true;
  try {
    const params = new URLSearchParams({
      v: "seguimiento_status",
      section: sectionId,
      t: String(Date.now())
    });
    if (["movies", "tv"].includes(sectionId)) {
      params.set("include_arr", "1");
      params.set("include_qbit", "1");
      params.set("qbit_category", sectionId);
    }
    const response = await fetch(`/api?${params.toString()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    updateWatchCardActivity(data, sectionId);
    lastData = data;
    if (sectionId !== "taller" && window.DelayEntrySound) {
      if (skipEntrySound && typeof window.DelayEntrySound.sync === "function") {
        window.DelayEntrySound.sync(data);
      } else if (!skipEntrySound) {
        window.DelayEntrySound.check(data);
      }
    }
    render(data);
    statusText.textContent = sectionId === "taller" ? "Taller listo" : `Actualizado ${ago(data.updated_at)}`;
    if (sectionId !== "taller") {
      await refreshOpenFolderChildren();
    }
  } catch (error) {
    statusText.textContent = "No se pudo actualizar";
  } finally {
    statusLoadInProgress = false;
    refreshButton.disabled = false;
  }
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && renameModalItem) {
    closeRenameModal();
    return;
  }
  if (event.key === "Escape" && trailerModalItem) {
    closeTrailerModal();
    return;
  }
  if (event.key === "Escape" && workshopOutputModalOpen) {
    workshopOutputModalOpen = false;
    renderWorkshopOnly();
    return;
  }
  if (event.key === "Escape" && workshopPreviewModalOpen) {
    closeWorkshopPreview();
    return;
  }
  if (event.key === "Escape" && actionModalItem) closeItemActionModal();
});

renameModeButton?.addEventListener("click", toggleRenameMode);
updateRenameModeButton();
refreshButton.addEventListener("click", loadStatus);
loadStatus();
setInterval(() => loadStatus({ automatic: true }), 5000);
