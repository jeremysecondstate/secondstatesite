(() => {
  const scene = document.querySelector('.etching-scene');
  const video = scene?.querySelector('video');
  if (!video) return;

  const windows = Array.from(document.querySelectorAll('[data-etching-window]'), (mask) => ({
    mask,
    hero: document.getElementById(mask.dataset.etchingWindow),
  }));
  const toggles = document.querySelectorAll('[data-motion-toggle]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const connection = navigator.connection;
  let paused = false;
  let failed = false;
  let visible = false;
  let frame = 0;
  let playbackRequest = 0;

  const motionAllowed = () => !reducedMotion.matches && !connection?.saveData && !failed;

  function updateControls() {
    toggles.forEach((toggle) => {
      toggle.hidden = !motionAllowed();
      toggle.textContent = paused ? 'Resume animation' : 'Pause animation';
    });
  }

  function stopPlayback() {
    playbackRequest += 1;
    video.pause();
  }

  function play() {
    const request = ++playbackRequest;
    video.play().catch((error) => {
      // Pause requests and tab changes deliberately abort pending playback.
      if (request !== playbackRequest || error.name === 'AbortError') return;
      paused = true;
      updateControls();
    });
  }

  function update() {
    frame = 0;
    visible = false;
    windows.forEach(({ mask, hero }) => {
      const rect = hero.getBoundingClientRect();
      // Clip inside the border, preserving its rounded outline.
      mask.setAttribute('x', rect.left + 1);
      mask.setAttribute('y', rect.top + 1);
      mask.setAttribute('width', Math.max(0, rect.width - 2));
      mask.setAttribute('height', Math.max(0, rect.height - 2));
      mask.setAttribute('rx', Math.max(0, parseFloat(getComputedStyle(hero).borderRadius) - 1));
      if (rect.bottom > 0 && rect.top < window.innerHeight) visible = true;
    });

    if (motionAllowed() && !paused && visible && !document.hidden) {
      if (video.paused && video.readyState >= 2) {
        play();
      }
    } else {
      stopPlayback();
    }
  }

  function scheduleUpdate() {
    if (!frame) frame = requestAnimationFrame(update);
  }

  function configureMotion() {
    scene.classList.toggle('is-ready', motionAllowed() && video.readyState >= 2);
    if (motionAllowed() && !video.getAttribute('src')) {
      video.muted = true;
      video.src = video.dataset.src;
      video.preload = 'auto';
      video.load();
    } else if (!motionAllowed()) {
      stopPlayback();
    }
    updateControls();
    scheduleUpdate();
  }

  toggles.forEach((toggle) => toggle.addEventListener('click', () => {
    paused = !paused;
    if (!paused && motionAllowed()) {
      // Direct user gesture also allows retrying blocked autoplay.
      play();
    }
    updateControls();
    scheduleUpdate();
  }));

  video.addEventListener('loadeddata', configureMotion);
  video.addEventListener('canplay', scheduleUpdate);
  video.addEventListener('error', () => { failed = true; configureMotion(); });
  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate, { passive: true });
  window.addEventListener('pageshow', scheduleUpdate);
  document.addEventListener('visibilitychange', () => {
    // Animation frames are suspended in hidden tabs, so pause immediately.
    if (document.hidden) stopPlayback();
    else scheduleUpdate();
  });
  reducedMotion.addEventListener('change', configureMotion);
  connection?.addEventListener('change', configureMotion);
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(scheduleUpdate);
    observer.observe(document.body);
    windows.forEach(({ hero }) => observer.observe(hero));
  }
  configureMotion();
})();
