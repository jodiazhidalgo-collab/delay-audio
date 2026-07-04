window.DelayAudioSounds = (() => {
  const finishSoundUrl = "/static/sounds/applepay.mp3?v=sonido-final-procesos-20260619";
  const finishSoundVolume = 0.55;
  const notifiedJobs = {};
  let finishSound = null;

  function getFinishSound() {
    if (!finishSound) {
      finishSound = new Audio(finishSoundUrl);
      finishSound.preload = "auto";
      finishSound.volume = finishSoundVolume;
    }
    return finishSound;
  }

  function prepare() {
    try {
      const audio = getFinishSound();
      audio.pause();
      audio.currentTime = 0;
      audio.muted = true;
      const promise = audio.play();
      if (promise && promise.then) {
        promise.then(() => {
          audio.pause();
          audio.currentTime = 0;
          audio.muted = false;
          audio.volume = finishSoundVolume;
        }).catch(() => {
          audio.muted = false;
          audio.volume = finishSoundVolume;
          audio.load();
        });
      } else {
        audio.pause();
        audio.currentTime = 0;
        audio.muted = false;
        audio.volume = finishSoundVolume;
      }
    } catch (error) {}
  }

  function done(jobId) {
    const key = String(jobId || `job:${Date.now()}`);
    if (notifiedJobs[key]) return;
    notifiedJobs[key] = true;
    try {
      const audio = getFinishSound();
      audio.pause();
      audio.currentTime = 0;
      audio.muted = false;
      audio.volume = finishSoundVolume;
      const promise = audio.play();
      if (promise && promise.catch) promise.catch(() => {});
    } catch (error) {}
  }

  ["pointerdown", "touchstart", "keydown", "click"].forEach((eventName) => {
    document.addEventListener(eventName, prepare, { once: true, passive: true });
  });

  return { prepare, done };
})();
