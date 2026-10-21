(() => {
  'use strict';
  const root = document.getElementById('inventory');
  if (!root) return;
  const form = document.getElementById('inventory-form');
  const notice = document.getElementById('inventory-notice');
  const connection = document.getElementById('inventory-connection');
  const labels = { queued: 'Waiting', processing: 'Working', completed: 'Complete', retry: 'Retrying', failed: 'Needs attention' };
  let caseId = root.dataset.caseId;
  let messageSignature = '';
  let busy = false;
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
  const render = data => {
    const list = document.getElementById('inventory-cases');
    list.replaceChildren();
    for (const item of data.cases) {
      const link = node('a', undefined, 'inventory-case' + (item.id === caseId ? ' selected' : ''));
      link.href = item.url;
      if (item.id === caseId) link.setAttribute('aria-current', 'page');
      link.append(node('strong', item.title), status(item.status)); list.append(link);
    }
    if (!data.cases.length) list.append(node('p', 'Your inventory requests will appear here.', 'inventory-muted'));
    const checked = data.worker.last_successful_check;
    document.getElementById('inventory-last-check').textContent = checked ? new Date(checked).toLocaleString() : 'No successful check yet';
    if (data.selected_case) document.getElementById('inventory-conversation-title').textContent = data.selected_case.title;
    const signature = JSON.stringify(data.messages);
    if (signature !== messageSignature && data.messages.length) {
      const messages = document.getElementById('inventory-messages');
      const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 70;
      messages.replaceChildren();
      for (const message of data.messages) {
        const article = node('article', undefined, 'inventory-message'); article.dataset.role = message.role;
        const meta = node('div', undefined, 'inventory-message-meta');
        meta.append(node('strong', message.author), status(message.status));
        article.append(meta, linkedText(message.body));
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
        if (message.retry_url) {
          const button = node('button', 'Retry this request'); button.type = 'button'; button.dataset.retryUrl = message.retry_url;
          const holder = node('div', undefined, 'inventory-retry-form'); holder.append(button); article.append(holder);
        }
        messages.append(article);
      }
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
    event.preventDefault(); if (busy) return;
    busy = true; const button = form.querySelector('button[type=submit]'); button.disabled = true; inform('');
    try {
      const data = await readResponse(await fetch(form.action, { method: 'POST', body: new FormData(form), headers: { Accept: 'application/json' }, credentials: 'same-origin' }));
      caseId = data.selected_case.id; root.dataset.caseId = caseId;
      history.replaceState({}, '', data.selected_case.url);
      form.action = data.selected_case.url + 'messages/';
      form.elements.client_message_id.value = data.message_token;
      form.elements.body.value = ''; form.elements.title.value = '';
      document.getElementById('inventory-title-field').hidden = true;
      render(data); inform('Saved. Your request is waiting for the next inventory check.');
    } catch (error) { inform(error.message); }
    finally { busy = false; button.disabled = false; }
  });
  root.addEventListener('click', async event => {
    const button = event.target.closest('[data-retry-url]'); if (!button) return;
    button.disabled = true;
    try {
      render(await readResponse(await fetch(button.dataset.retryUrl, { method: 'POST', headers: { Accept: 'application/json', 'X-CSRFToken': form.elements.csrfmiddlewaretoken.value }, credentials: 'same-origin' })));
      inform('Retry queued for the next inventory check.');
    } catch (error) { inform(error.message); button.disabled = false; }
  });
  const poll = async () => {
    if (document.hidden || busy) return;
    try {
      const url = new URL(root.dataset.stateUrl, location.origin); if (caseId) url.searchParams.set('case', caseId);
      render(await readResponse(await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } })));
      connection.textContent = 'Live updates connected';
    } catch { connection.textContent = 'Live updates interrupted. Retrying shortly.'; }
  };
  poll(); setInterval(poll, 10000);
})();
