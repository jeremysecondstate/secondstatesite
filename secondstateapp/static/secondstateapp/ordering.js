(() => {
  'use strict';

  document.querySelectorAll('[data-order-editor]').forEach((editor) => {
    const list = editor.querySelector('[data-order-list]');
    const controls = editor.querySelector('[data-order-controls]');
    if (!list || !controls) return;
    const items = () => Array.from(list.children).filter((item) => item.hasAttribute('data-order-item'));
    if (items().length < 2) return;

    const startButton = editor.querySelector('[data-order-start]');
    const saveButton = editor.querySelector('[data-order-save]');
    const cancelButton = editor.querySelector('[data-order-cancel]');
    const status = editor.querySelector('[data-order-status]');
    const token = editor.querySelector('[name=csrfmiddlewaretoken]');
    const disabledControls = new Map();
    const tabStops = new Map();
    let originalItems = items();
    let active = false;
    let saving = false;
    let drag = null;
    let scrollFrame = 0;

    const order = () => items().map((item) => Number(item.dataset.orderItem));
    const emit = (name, detail = {}) => editor.dispatchEvent(new CustomEvent(`order:${name}`, { detail, bubbles: true }));
    const tell = (message, error = false) => {
      status.textContent = message;
      status.dataset.error = String(error);
    };
    const updateStickyPosition = () => {
      const nav = document.querySelector('header.nav');
      editor.style.setProperty('--order-toolbar-top', `${(nav?.getBoundingClientRect().height || 0) + 8}px`);
    };
    updateStickyPosition();
    window.addEventListener('resize', updateStickyPosition);
    controls.hidden = false;

    function setActive(value) {
      active = value;
      editor.dataset.orderActive = String(value);
      startButton.hidden = value;
      editor.querySelectorAll('[data-order-edit-only], [data-order-handle]').forEach((element) => { element.hidden = !value; });
      if (value) {
        editor.querySelectorAll('button[data-order-lock], [data-order-lock] button').forEach((button) => {
          disabledControls.set(button, button.disabled);
          button.disabled = true;
        });
        list.querySelectorAll('a, button:not([data-order-handle])').forEach((element) => {
          tabStops.set(element, element.getAttribute('tabindex'));
          element.setAttribute('tabindex', '-1');
        });
      } else {
        disabledControls.forEach((disabled, button) => { button.disabled = disabled; });
        disabledControls.clear();
        tabStops.forEach((value, element) => {
          if (value === null) element.removeAttribute('tabindex');
          else element.setAttribute('tabindex', value);
        });
        tabStops.clear();
      }
    }

    function announceMove(item) {
      tell(`${item.dataset.orderLabel} moved to position ${items().indexOf(item) + 1} of ${items().length}. Save order to keep changes.`);
    }

    startButton.addEventListener('click', () => {
      originalItems = items();
      // Gallery restores All works before its filters are locked.
      emit('start');
      setActive(true);
      tell('Arrange the items, then save your order.');
      list.querySelector('[data-order-handle]')?.focus({ preventScroll: true });
    });

    function stopDrag(cancelled = false) {
      if (!drag) return;
      const completedDrag = drag;
      drag = null;
      cancelAnimationFrame(scrollFrame);
      if (cancelled) {
        completedDrag.original.forEach((item) => list.append(item));
        emit('change');
      }
      completedDrag.item.classList.remove('is-dragging');
      if (list.hasPointerCapture(completedDrag.pointerId)) list.releasePointerCapture(completedDrag.pointerId);
      if (completedDrag.moved && !cancelled) announceMove(completedDrag.item);
    }

    cancelButton.addEventListener('click', () => {
      if (saving) return;
      stopDrag();
      originalItems.forEach((item) => list.append(item));
      emit('change');
      setActive(false);
      emit('finish', { saved: false });
      tell('Changes cancelled.');
      startButton.focus({ preventScroll: true });
    });

    saveButton.addEventListener('click', async () => {
      if (saving) return;
      stopDrag();
      saving = true;
      editor.setAttribute('aria-busy', 'true');
      saveButton.disabled = true;
      cancelButton.disabled = true;
      tell('Saving order…');
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20000);
      try {
        const response = await fetch(editor.dataset.orderUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token.value },
          body: JSON.stringify({ order: order(), original_order: originalItems.map((item) => Number(item.dataset.orderItem)) }),
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Could not save the order. Refresh the page and check that you are signed in as staff.');
        originalItems = items();
        setActive(false);
        emit('finish', { saved: true });
        tell('Order saved.');
        startButton.focus({ preventScroll: true });
      } catch (error) {
        tell(error.name === 'AbortError' ? 'The save could not be confirmed. Reload to check the saved order before trying again.' : error.message, true);
      } finally {
        clearTimeout(timeout);
        saving = false;
        editor.removeAttribute('aria-busy');
        saveButton.disabled = false;
        cancelButton.disabled = false;
      }
    });

    list.addEventListener('click', (event) => {
      if (active && !event.target.closest('[data-order-handle]')) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
    list.addEventListener('dragstart', (event) => { if (active) event.preventDefault(); });

    list.addEventListener('keydown', (event) => {
      if (!active || saving || !event.target.closest('[data-order-handle]')) return;
      const delta = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[event.key];
      if (!delta) return;
      event.preventDefault();
      const item = event.target.closest('[data-order-item]');
      const siblings = items();
      const target = siblings[siblings.indexOf(item) + delta];
      if (!target) return;
      list.insertBefore(item, delta > 0 ? target.nextSibling : target);
      emit('change');
      item.querySelector('[data-order-handle]').focus({ preventScroll: true });
      item.scrollIntoView({ block: 'nearest', behavior: 'instant' });
      announceMove(item);
    });

    function moveAtPointer() {
      if (!drag?.moved) return;
      const target = document.elementFromPoint(drag.x, drag.y)?.closest('[data-order-item]');
      if (!target || target === drag.item || target.parentElement !== list) return;
      const siblings = items();
      list.insertBefore(drag.item, siblings.indexOf(drag.item) < siblings.indexOf(target) ? target.nextSibling : target);
      emit('change');
    }

    function scrollWhileDragging() {
      if (!drag?.moved) return;
      const top = controls.getBoundingClientRect().bottom + 35;
      const bottom = window.innerHeight - 70;
      const delta = drag.y < top ? -14 : drag.y > bottom ? 14 : 0;
      if (delta) {
        window.scrollBy(0, delta);
        moveAtPointer();
      }
      scrollFrame = requestAnimationFrame(scrollWhileDragging);
    }

    list.addEventListener('pointerdown', (event) => {
      if (!active || saving || drag || !event.isPrimary || event.button !== 0 || !event.target.closest('[data-order-handle], [data-order-drag]')) return;
      const item = event.target.closest('[data-order-item]');
      if (!item) return;
      event.preventDefault();
      drag = { item, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, x: event.clientX, y: event.clientY, moved: false, original: items() };
      list.setPointerCapture(event.pointerId);
    });
    list.addEventListener('pointermove', (event) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      drag.x = event.clientX;
      drag.y = event.clientY;
      if (!drag.moved && Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > 6) {
        drag.moved = true;
        drag.item.classList.add('is-dragging');
        scrollFrame = requestAnimationFrame(scrollWhileDragging);
      }
      moveAtPointer();
    });
    list.addEventListener('pointerup', (event) => { if (event.pointerId === drag?.pointerId) stopDrag(); });
    list.addEventListener('pointercancel', (event) => { if (event.pointerId === drag?.pointerId) stopDrag(true); });
    list.addEventListener('lostpointercapture', (event) => { if (event.pointerId === drag?.pointerId) stopDrag(true); });
    window.addEventListener('beforeunload', (event) => {
      if (active && order().join(',') !== originalItems.map((item) => item.dataset.orderItem).join(',')) event.preventDefault();
    });
  });
})();
