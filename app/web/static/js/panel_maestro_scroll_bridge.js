(() => {
  if (window.parent === window) return;

  const MESSAGE_SOURCE = "panel-web-maestro-scroll";
  const REQUEST_SOURCE = "panel-web-maestro";
  let scheduled = false;

  function currentScrollY() {
    const root = document.scrollingElement || document.documentElement;
    return Math.max(0, Number(window.scrollY ?? root?.scrollTop ?? 0) || 0);
  }

  function reportScroll() {
    scheduled = false;
    window.parent.postMessage({
      source: MESSAGE_SOURCE,
      type: "scroll",
      scrollY: currentScrollY()
    }, "*");
  }

  function scheduleReport() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(reportScroll);
  }

  window.addEventListener("scroll", scheduleReport, { passive: true });
  window.addEventListener("resize", scheduleReport, { passive: true });
  window.addEventListener("pageshow", scheduleReport);
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const payload = event.data;
    if (payload?.source === REQUEST_SOURCE && payload.type === "scroll-request") scheduleReport();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scheduleReport, { once: true });
  } else {
    scheduleReport();
  }
})();
