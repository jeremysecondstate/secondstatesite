(() => {
  'use strict';

  const gallery = document.querySelector('[data-gallery]');
  if (!gallery) return;

  const works = Array.from(gallery.querySelectorAll('[data-artwork-id]'));
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const motionButton = gallery.querySelector('[data-motion]');
  let motionEnabled = !reducedMotion.matches;

  const resetArtwork = (visual) => {
    visual.style.removeProperty('--art-rx');
    visual.style.removeProperty('--art-ry');
  };

  function updateMotion() {
    gallery.dataset.motionEnabled = String(motionEnabled);
    if (motionButton) {
      motionButton.disabled = reducedMotion.matches || gallery.dataset.orderActive === 'true';
      motionButton.title = reducedMotion.matches ? 'Reduced motion is enabled in your device settings.' : 'Toggle artwork motion';
      motionButton.setAttribute('aria-pressed', String(motionEnabled));
      motionButton.querySelector('[data-motion-label]').textContent = motionEnabled ? 'Motion on' : 'Motion off';
    }
    if (!motionEnabled) works.forEach((work) => {
      work.classList.remove('is-entering');
      resetArtwork(work.querySelector('.gallery-work__visual'));
    });
  }
  updateMotion();
  motionButton?.addEventListener('click', () => {
    // The OS preference always takes priority over decorative animation.
    motionEnabled = !motionEnabled && !reducedMotion.matches;
    updateMotion();
  });
  reducedMotion.addEventListener('change', (event) => {
    motionEnabled = !event.matches;
    updateMotion();
  });

  const controls = gallery.querySelector('[data-gallery-controls]');
  if (controls) controls.hidden = false;

  const filters = Array.from(gallery.querySelectorAll('[data-filter]'));
  gallery.addEventListener('order:start', () => {
    filters.find((button) => button.dataset.filter === 'all')?.click();
    works.forEach((work) => {
      work.classList.remove('is-entering');
      resetArtwork(work.querySelector('.gallery-work__visual'));
    });
  });
  gallery.addEventListener('order:change', () => {
    gallery.querySelectorAll('[data-artwork-id]').forEach((work, index) => {
      work.querySelector('.gallery-work__number').textContent = String(index + 1).padStart(2, '0');
    });
  });
  gallery.addEventListener('order:finish', updateMotion);
  filters.forEach((button) => button.addEventListener('click', () => {
    const category = button.dataset.filter;
    let count = 0;
    works.forEach((work) => {
      work.hidden = category !== 'all' && work.dataset.category !== category;
      work.classList.remove('is-entering');
      if (!work.hidden) count += 1;
    });
    filters.forEach((filter) => filter.setAttribute('aria-pressed', String(filter === button)));
    gallery.querySelector('[data-filter-description]').textContent = button.dataset.description;
    gallery.querySelector('[data-gallery-count]').textContent = `${count} ${count === 1 ? 'work' : 'works'}`;
  }));

  works.forEach((work) => {
    const visual = work.querySelector('.gallery-work__visual');
    let frame = 0;
    visual.addEventListener('pointermove', (event) => {
      if (!motionEnabled || gallery.dataset.orderActive === 'true' || !finePointer.matches || event.pointerType === 'touch') return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const bounds = visual.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width - 0.5;
        const y = (event.clientY - bounds.top) / bounds.height - 0.5;
        visual.style.setProperty('--art-rx', `${-y * 5}deg`);
        visual.style.setProperty('--art-ry', `${x * 5}deg`);
      });
    });
    visual.addEventListener('pointerleave', () => {
      cancelAnimationFrame(frame);
      resetArtwork(visual);
    });
    work.addEventListener('animationend', () => work.classList.remove('is-entering'));
  });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        if (motionEnabled) entry.target.classList.add('is-entering');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.08 });
    works.forEach((work) => observer.observe(work));
  }

  const viewer = gallery.querySelector('[data-viewer]');
  if (!viewer || typeof viewer.showModal !== 'function') return;

  const viewerImage = viewer.querySelector('[data-viewer-image]');
  const viewerCounter = viewer.querySelector('[data-viewer-counter]');
  let imageSources = [];
  let imageIndex = 0;
  let imageTitle = '';
  let opener = null;
  let previousOverflow = '';

  function showImage(index) {
    imageIndex = (index + imageSources.length) % imageSources.length;
    viewerImage.src = imageSources[imageIndex];
    viewerImage.alt = `${imageTitle} — image ${imageIndex + 1} of ${imageSources.length}`;
    viewerCounter.textContent = `${imageIndex + 1} / ${imageSources.length}`;
  }

  gallery.querySelectorAll('[data-quick-look]').forEach((button) => {
    const work = button.closest('[data-artwork-id]');
    const sources = Array.from(work.querySelector('[data-work-images]').content.querySelectorAll('[data-src]'), (image) => image.dataset.src);
    if (!sources.length) return;
    button.hidden = false;
    button.addEventListener('click', () => {
      opener = button;
      imageSources = sources;
      imageTitle = work.querySelector('[data-work-title]').textContent;
      viewer.querySelector('#viewer-title').textContent = imageTitle;
      viewer.querySelector('[data-viewer-artist]').textContent = work.querySelector('[data-work-artist]').textContent;
      viewer.querySelector('[data-viewer-medium]').textContent = work.querySelector('[data-work-medium]').textContent;
      viewer.querySelector('[data-viewer-details]').href = work.querySelector('[data-work-details]').href;
      viewer.querySelector('[data-viewer-navigation]').hidden = sources.length < 2;
      showImage(0);
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      viewer.showModal();
    });
  });

  viewer.querySelector('[data-viewer-previous]').addEventListener('click', () => showImage(imageIndex - 1));
  viewer.querySelector('[data-viewer-next]').addEventListener('click', () => showImage(imageIndex + 1));
  viewer.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      showImage(imageIndex + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  });
  viewer.addEventListener('click', (event) => {
    if (event.target !== viewer) return;
    const bounds = viewer.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) viewer.close();
  });
  viewer.addEventListener('close', () => {
    document.body.style.overflow = previousOverflow;
    viewerImage.removeAttribute('src');
    opener?.focus({ preventScroll: true });
  });
})();
