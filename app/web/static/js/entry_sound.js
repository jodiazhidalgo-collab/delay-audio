window.DelayEntrySound = (() => {
  const soundUrl = "/static/sounds/applepay.mp3?v=seguimiento-base-20260618";
  const soundVolume = 0.55;
  const watchedFolderIds = new Set(["media_movies", "media_tv"]);
  const baselines = {};
  let sound = null;

  function getSound() {
    if (!sound) {
      sound = new Audio(soundUrl);
      sound.preload = "auto";
      sound.volume = soundVolume;
    }
    return sound;
  }

  function prepare() {
    try {
      const audio = getSound();
      audio.pause();
      audio.currentTime = 0;
      audio.muted = true;
      const promise = audio.play();
      if (promise && promise.then) {
        promise.then(() => {
          audio.pause();
          audio.currentTime = 0;
          audio.muted = false;
          audio.volume = soundVolume;
        }).catch(() => {
          audio.muted = false;
          audio.volume = soundVolume;
          audio.load();
        });
      } else {
        audio.pause();
        audio.currentTime = 0;
        audio.muted = false;
        audio.volume = soundVolume;
      }
    } catch (e) {}
  }

  function play() {
    try {
      const audio = getSound();
      audio.pause();
      audio.currentTime = 0;
      audio.muted = false;
      audio.volume = soundVolume;
      const promise = audio.play();
      if (promise && promise.catch) promise.catch(() => {});
    } catch (e) {}
  }

  function folderSnapshot(folder) {
    const items = Array.isArray(folder?.items) ? folder.items : [];
    const names = items.map((item) => String(item?.name || "")).filter(Boolean);
    return {
      count: Number(folder?.count || 0),
      names: new Set(names),
    };
  }

  function hasNewEntry(previous, current) {
    if (!previous) return false;
    if (current.count > previous.count) return true;
    return [...current.names].some((name) => !previous.names.has(name));
  }

  function watchedFolders(data) {
    const folders = Array.isArray(data?.folders) ? data.folders : [];
    return folders.filter((folder) => watchedFolderIds.has(folder?.id));
  }

  function check(data, options = {}) {
    const silent = Boolean(options.silent);
    let shouldPlay = false;
    watchedFolders(data).forEach((folder) => {
      const id = folder.id;
      const current = folderSnapshot(folder);
      if (hasNewEntry(baselines[id], current)) shouldPlay = true;
      baselines[id] = current;
    });
    if (shouldPlay && !silent) play();
    return shouldPlay;
  }

  function sync(data) {
    return check(data, { silent: true });
  }

  ["pointerdown", "touchstart", "keydown", "click"].forEach((eventName) => {
    document.addEventListener(eventName, prepare, { once: true, passive: true });
  });

  return { check, prepare, play, sync };
})();
