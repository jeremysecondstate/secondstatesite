(() => {
  'use strict';
  const root = document.getElementById('inventory');
  if (!root) return;
  const form = document.getElementById('inventory-form');
  const notice = document.getElementById('inventory-notice');
  const connection = document.getElementById('inventory-connection');
  const labels = { queued: 'Waiting', processing: 'Working', completed: 'Complete', retry: 'Retrying', failed: 'Needs attention', cancelled: 'Stopped' };
  const actionNotices = {
    'trash-case': 'Request moved to Trash. Its pending work has stopped.',
    'restore-case': 'Request restored. Review any unfinished messages before retrying them.',
    'trash-message': 'Message moved to Trash. Any affected work has stopped.',
    'restore-message': 'Message restored. Review any unfinished work before retrying it.',
    retry: 'Retry queued for the next inventory check.',
  };
  let caseId = root.dataset.caseId;
  let messageSignature = '';
  let busy = false;
  let revision = 0;
  const drafts = new Map();
  const node = (tag, text, className) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  };
  const status = value => {
    const item = node('span', labels[value] || value, 'inventory-status');
    item.dataset.status = value;
    return item;
  };
  const inform = text => { notice.textContent = text; notice.hidden = !text; };
  const actionForm = (url, action, label, className = '', ariaLabel = '') => {
    const actionForm = node('form', undefined, className);
    actionForm.method = 'post'; actionForm.action = url; actionForm.dataset.inventoryAction = action;
    const csrf = node('input'); csrf.type = 'hidden'; csrf.name = 'csrfmiddlewaretoken'; csrf.value = form.elements.csrfmiddlewaretoken.value;
    const button = node('button', label, 'inventory-text-button' + (action.startsWith('trash') ? ' inventory-danger-link' : ''));
    button.type = 'submit';
    if (ariaLabel) button.setAttribute('aria-label', ariaLabel);
    actionForm.append(csrf, button);
    return actionForm;
  };
  const linkedText = text => {
    const p = node('p', undefined, 'inventory-message-body');
    const pattern = /https?:\/\/[^\s<>]+/g;
    let from = 0;
    for (const match of text.matchAll(pattern)) {
      p.append(document.createTextNode(text.slice(from, match.index)));
      const a = node('a', match[0]);
      a.href = match[0]; a.target = '_blank'; a.rel = 'noopener noreferrer';
      p.append(a); from = match.index + match[0].length;
    }
    p.append(document.createTextNode(text.slice(from)));
    return p;
  };
  const caseLink = (item, trashed = false) => {
    const link = node('a', undefined, 'inventory-case' + (item.id === caseId ? ' selected' : ''));
    link.href = item.url;
    if (item.id === caseId) link.setAttribute('aria-current', 'page');
    const badge = status(trashed ? 'cancelled' : item.status);
    if (trashed) badge.textContent = 'Request in Trash';
    link.append(node('strong', item.title), badge);
    return link;
  };
  const renderTrash = data => {
    const cases = data.trash_cases || [];
    const messages = data.trash_messages || [];
    const count = data.trash_count ?? cases.length + messages.length;
    document.getElementById('inventory-trash-count').textContent = count;
    const emptyLink = document.getElementById('inventory-empty-trash');
    emptyLink.hidden = !count;
    if (data.empty_trash_url) emptyLink.href = data.empty_trash_url;
    const list = document.getElementById('inventory-trash-items'); list.replaceChildren();
    for (const item of cases) list.append(caseLink(item, true));
    for (const message of messages) {
      const item = node('div', undefined, 'inventory-trash-message');
      const link = node('a'); link.href = message.case_url + '#inventory-removed-messages';
      link.append(node('strong', message.case_title), node('span', message.body.length > 90 ? message.body.slice(0, 89) + '…' : message.body));
      item.append(link, actionForm(message.restore_url, 'restore-message', 'Restore message'));
      list.append(item);
    }
    if (!count) list.append(node('p', 'Trash is empty.', 'inventory-muted'));
  };
  const messageArticle = (message, caseDeleted, removed = false) => {
    const article = node('article', undefined, 'inventory-message' + (removed ? ' inventory-message-removed' : ''));
    article.dataset.role = message.role; article.id = 'inventory-message-' + message.id;
    const meta = node('div', undefined, 'inventory-message-meta');
    const badge = status(removed ? 'cancelled' : message.status);
    if (removed) badge.textContent = 'In Trash';
    meta.append(node('strong', message.author), badge);
    if (!caseDeleted) {
      const action = removed ? 'restore-message' : 'trash-message';
      const url = removed ? message.restore_url : message.delete_url;
      if (url) meta.append(actionForm(url, action, removed ? 'Restore message' : 'Move to Trash', 'inventory-message-action', (removed ? 'Restore message by ' : 'Move message to Trash by ') + message.author));
    }
    article.append(meta, linkedText(message.body));
    if (removed) return article;
    if (message.error) article.append(node('p', message.error, 'inventory-error'));
    const result = message.result || {};
    if (result.workbook) article.append(node('p', `Workbook: ${result.workbook.sheet || 'SUPREME'} · Rows ${(result.workbook.rows || []).join(', ')}`, 'inventory-receipt'));
    if (result.pending_fields?.length) article.append(node('p', 'Pending: ' + result.pending_fields.join('; '), 'inventory-receipt'));
    if (result.sources?.length) {
      const sources = node('ul', undefined, 'inventory-sources');
      for (const source of result.sources) {
        let url;
        try { url = new URL(source.url); } catch { continue; }
        if (!['http:', 'https:'].includes(url.protocol)) continue;
        const a = node('a', source.title || source.url); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer';
        const li = node('li'); li.append(a); sources.append(li);
      }
      article.append(sources);
    }
    if (message.retry_url && !caseDeleted) article.append(actionForm(message.retry_url, 'retry', 'Retry this request', 'inventory-retry-form'));
    return article;
  };
  const render = data => {
    const selected = data.selected_case;
    const changedCase = (selected?.id || '') !== caseId;
    if (changedCase) {
      drafts.set(caseId, { body: form.elements.body.value, title: form.elements.title.value });
      const draft = drafts.get(selected?.id || '');
      form.elements.body.value = draft?.body || '';
      form.elements.title.value = draft?.title || '';
    }
    caseId = selected?.id || ''; root.dataset.caseId = caseId;
    const caseDeleted = Boolean(selected?.deleted_at);
    const list = document.getElementById('inventory-cases'); list.replaceChildren();
    for (const item of data.cases) list.append(caseLink(item));
    if (!data.cases.length) list.append(node('p', 'Your inventory requests will appear here.', 'inventory-muted'));
    renderTrash(data);
    if (caseDeleted) document.getElementById('inventory-trash').open = true;
    const checked = data.worker.last_successful_check;
    document.getElementById('inventory-last-check').textContent = checked ? new Date(checked).toLocaleString() : 'No successful check yet';
    document.getElementById('inventory-conversation-title').textContent = selected?.title || 'What did we win?';
    const actions = document.getElementById('inventory-case-actions'); actions.replaceChildren();
    if (selected) actions.append(actionForm(caseDeleted ? selected.restore_url : selected.delete_url, caseDeleted ? 'restore-case' : 'trash-case', caseDeleted ? 'Restore request' : 'Move request to Trash'));
    document.getElementById('inventory-trashed-notice').hidden = !caseDeleted;
    form.hidden = caseDeleted;
    form.action = selected ? selected.url + 'messages/' : root.dataset.createUrl;
    document.getElementById('inventory-title-field').hidden = Boolean(selected);
    document.getElementById('inventory-body-label').textContent = selected ? 'Add a message' : 'Your inventory request';
    if (changedCase) {
      form.elements.client_message_id.value = data.message_token;
      history.replaceState({}, '', selected?.url || root.dataset.homeUrl + '?new=1');
    }
    const signature = JSON.stringify([selected?.id, caseDeleted, data.messages]);
    if (signature !== messageSignature) {
      const messages = document.getElementById('inventory-messages');
      const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 70;
      const active = data.messages.filter(message => !message.deleted_at);
      const removed = data.messages.filter(message => message.deleted_at);
      messages.replaceChildren();
      for (const message of active) messages.append(messageArticle(message, caseDeleted));
      if (!active.length) {
        const empty = node('div', undefined, 'inventory-empty');
        empty.append(node('span', '↗'), node('h3', selected ? 'No messages here.' : 'A new home for the details.'), node('p', selected ? (removed.length ? 'Messages moved to Trash can be restored below.' : 'Add a message to continue this request.') : '“We won lots 12, 34, and 56 at Tuesday’s sale. Please add them to inventory.”'));
        messages.append(empty);
      }
      const removedPanel = document.getElementById('inventory-removed-messages'); removedPanel.hidden = !removed.length;
      document.getElementById('inventory-removed-count').textContent = removed.length;
      const removedList = document.getElementById('inventory-removed-list'); removedList.replaceChildren();
      for (const message of removed) removedList.append(messageArticle(message, caseDeleted, true));
      if (atBottom || !messageSignature) messages.scrollTop = messages.scrollHeight;
      messageSignature = signature;
    }
  };
  const readResponse = async response => {
    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session needs attention. Reload the page to sign in again.');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The request could not be saved.');
    return data;
  };
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || form.hidden) return;
    busy = true; revision += 1;
    const button = form.querySelector('button[type=submit]'); button.disabled = true; inform('');
    try {
      const data = await readResponse(await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' }, credentials: 'same-origin' }));
      form.elements.client_message_id.value = data.message_token;
      form.elements.body.value = ''; form.elements.title.value = '';
      render(data); inform('Saved. Your request is waiting for the next inventory check.');
    } catch (error) { inform(error.message); }
    finally { busy = false; button.disabled = false; }
  });
  root.addEventListener('submit', async event => {
    const action = event.target.closest('form[data-inventory-action]');
    if (!action) return;
    event.preventDefault(); if (busy) return;
    busy = true; revision += 1;
    const button = action.querySelector('button[type=submit]'); button.disabled = true; inform('');
    try {
      const data = await readResponse(await fetch(action.action, { method: 'POST', body: new FormData(action), headers: { Accept: 'application/json' }, credentials: 'same-origin' }));
      render(data); inform(actionNotices[action.dataset.inventoryAction] || 'Saved.');
      if (action.dataset.inventoryAction.startsWith('trash')) document.getElementById('inventory-trash').open = true;
    } catch (error) { inform(error.message); }
    finally { busy = false; button.disabled = false; }
  });
  const poll = async () => {
    if (document.hidden || busy) return;
    const requestedRevision = revision;
    try {
      const url = new URL(root.dataset.stateUrl, location.origin); if (caseId) url.searchParams.set('case', caseId);
      const options = { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } };
      let response = await fetch(url, options);
      const removed = response.status === 404 && Boolean(caseId);
      if (removed) response = await fetch(root.dataset.stateUrl, options);
      const data = await readResponse(response);
      if (busy || requestedRevision !== revision) return;
      if (removed) {
        form.elements.body.value = ''; form.elements.title.value = '';
        inform('This request was removed from Trash. You can start a new request.');
      }
      render(data);
      connection.textContent = 'Live updates connected';
    } catch { if (requestedRevision === revision) connection.textContent = 'Live updates interrupted. Retrying shortly.'; }
  };
  const revealFragment = () => {
    if (['#inventory-trash', '#inventory-removed-messages'].includes(location.hash)) document.getElementById(location.hash.slice(1)).open = true;
  };
  revealFragment(); window.addEventListener('hashchange', revealFragment);
  poll(); setInterval(poll, 10000);
})();
