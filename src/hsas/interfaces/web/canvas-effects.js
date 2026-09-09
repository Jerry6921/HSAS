/* HIQS adapter for the vendored Canvas UI Ripple component. */
(function initializeCanvasEffects() {
  const api = window.CanvasUIRipple;
  const content = document.getElementById("canvas-ui-content");
  const source = document.getElementById("canvas-ui-source");
  const output = document.getElementById("canvas-ui-output");
  const toggle = document.getElementById("canvas-effect-toggle");
  if (!api || !content || !source || !output || !toggle) return;

  let enabled = window.localStorage.getItem("hiqs-canvas-effects") !== "off";
  let instance = null;
  let pointerFrame = 0;
  let activeSurface = null;

  const tiltSelectors = [
    ".next-up-card",
    ".application-card",
    ".metrics article",
    ".status-grid article",
    ".status-details > section",
    ".compact-status",
    ".search-result",
    ".inbox-entry",
    ".change-card",
    ".event-chip",
    ".agenda-item",
    ".unscheduled-item",
    ".course-manager-row",
  ];
  const surfaceSelector = [
    ...tiltSelectors,
    ".home-command-center",
    ".status-card",
    ".local-search-card",
    ".inbox-card",
    ".updates-card",
    ".update-course",
    ".calendar-card",
    ".unscheduled-card",
    ".course-hero",
    ".overview-card",
    ".course-materials-card",
    ".material-card",
  ].join(",");
  const tiltSelector = tiltSelectors.join(",");
  const revealSelector = [
    ".next-up-card",
    ".home-command-center",
    ".home-intelligence-grid",
    ".updates-card",
    ".calendar-card",
    ".unscheduled-card",
    ".course-hero",
    ".overview-upper",
    ".course-materials-card",
  ].join(",");

  const revealObserver = "IntersectionObserver" in window
    ? new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("motion-visible");
        revealObserver.unobserve(entry.target);
      }
    }, { threshold: 0.08, rootMargin: "0px 0px -4%" })
    : null;

  function registerMotionElements(scope = document) {
    const surfaces = [...(scope.querySelectorAll?.(surfaceSelector) || [])];
    const tilts = [...(scope.querySelectorAll?.(tiltSelector) || [])];
    const reveals = [...(scope.querySelectorAll?.(revealSelector) || [])];
    if (scope.matches?.(surfaceSelector)) surfaces.unshift(scope);
    if (scope.matches?.(tiltSelector)) tilts.unshift(scope);
    if (scope.matches?.(revealSelector)) reveals.unshift(scope);
    for (const node of surfaces) {
      node.classList.add("motion-surface");
    }
    for (const node of tilts) {
      node.classList.add("motion-tilt");
    }
    for (const node of reveals) {
      if (node.classList.contains("motion-reveal")) continue;
      node.classList.add("motion-reveal");
      if (revealObserver) revealObserver.observe(node);
      else node.classList.add("motion-visible");
    }
  }

  function resetSurface(surface) {
    if (!surface) return;
    surface.classList.remove("motion-active");
    surface.style.removeProperty("--motion-tilt-x");
    surface.style.removeProperty("--motion-tilt-y");
  }

  function updatePointer(event) {
    if (!enabled || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (pointerFrame) cancelAnimationFrame(pointerFrame);
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      const root = document.documentElement;
      root.style.setProperty("--motion-pointer-x", `${event.clientX}px`);
      root.style.setProperty("--motion-pointer-y", `${event.clientY}px`);

      const surface = event.target.closest?.(`${surfaceSelector},${tiltSelector}`);
      if (surface !== activeSurface) {
        resetSurface(activeSurface);
        activeSurface = surface;
      }
      if (!surface) return;
      const rect = surface.getBoundingClientRect();
      const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
      const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
      surface.style.setProperty("--motion-x", `${x}px`);
      surface.style.setProperty("--motion-y", `${y}px`);
      surface.classList.add("motion-active");
      if (surface.matches(tiltSelector) && rect.width && rect.height) {
        surface.style.setProperty("--motion-tilt-x", `${((x / rect.width) - 0.5) * 1.7}deg`);
        surface.style.setProperty("--motion-tilt-y", `${((y / rect.height) - 0.5) * -1.4}deg`);
      }
    });
  }

  function mount() {
    if (!enabled || instance) return;
    instance = api.createRipple(
      { source, content, output },
      {
        amplitude: 0.32,
        speed: 0.72,
        wavelength: 92,
        rings: 2,
        decay: 1.35,
        refraction: 54,
        dispersion: 0.16,
        shine: 0.32,
        trigger: "click",
        interval: 0,
      },
    );
    output.classList.toggle("unavailable", !instance);
  }

  function unmount() {
    instance?.destroy();
    instance = null;
    output.width = 1;
    output.height = 1;
  }

  function renderToggle() {
    document.documentElement.classList.toggle("motion-enabled", enabled);
    toggle.setAttribute("aria-pressed", String(enabled));
    toggle.textContent = enabled ? "动态质感 · 开" : "动态质感 · 关";
    toggle.title = enabled ? "关闭 Canvas UI 水波折射" : "开启 Canvas UI 水波折射";
  }

  toggle.addEventListener("click", () => {
    enabled = !enabled;
    window.localStorage.setItem("hiqs-canvas-effects", enabled ? "on" : "off");
    if (enabled) mount();
    else {
      unmount();
      resetSurface(activeSurface);
      activeSurface = null;
    }
    renderToggle();
  });

  document.addEventListener("pointermove", updatePointer, { passive: true });
  document.addEventListener("pointerleave", () => {
    resetSurface(activeSurface);
    activeSurface = null;
  });
  const mutationObserver = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) registerMotionElements(node);
      }
    }
  });
  mutationObserver.observe(document.body, { childList: true, subtree: true });
  registerMotionElements();
  renderToggle();
  mount();
  window.addEventListener("pagehide", () => {
    unmount();
    mutationObserver.disconnect();
    revealObserver?.disconnect();
  }, { once: true });
})();
