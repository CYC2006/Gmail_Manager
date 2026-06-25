'use strict';

import {
  PAGE_SIZE, VIEW_KEYS, state,
  viewBuffer, viewShown, viewBufferedIds, viewStats,
  bodyCache, getUiState,
  sseHandles, streamFlags, tpdState,
} from './state.js';
import { startLoading, stopLoading, updateStatsDisplay, showStreamError, hideStreamError, apiPost } from './ui.js';

// ─── Injected dependency (set by app.js to avoid circular import) ─────────────
// buildCard from email-card.js needs openModal from modal.js, both of which
// depend on stream helpers, so we inject them at init time instead.

let _buildCard   = null;
let _onCardClick = null;

export function initStream({ buildCard, onCardClick }) {
  _buildCard   = buildCard;
  _onCardClick = onCardClick;
}

// ─── Prefetch AI analysis ─────────────────────────────────────────────────────

export function prefetchAiAnalysis(email, onDone) {
  const ui = getUiState(email.id);
  if (ui.aiLoaded || ui.aiQueued || tpdState.allExhausted) { onDone?.(); return; }
  ui.aiQueued = true;
  fetch(`/api/email/${email.id}/analyze`)
    .then(r => r.json())
    .then(d => {
      if (!d._failed && !d.error) {
        ui.aiResult = d;
        ui.aiLoaded = true;
        if (state.currentEmail?.id === email.id) {
          const aiTab = document.getElementById('tab-ai');
          if (aiTab?.classList.contains('active')) {
            document.getElementById('ai-loading')?.classList.add('hidden');
            const aiResultEl = document.getElementById('ai-result');
            if (aiResultEl) aiResultEl.innerHTML = _renderAiResult(d);
          }
        }
      } else {
        ui.aiQueued = false;
      }
    })
    .catch(() => { ui.aiQueued = false; })
    .finally(() => onDone?.());
}

export function startAiPrefetch() {
  const emails = [...viewBuffer['inbox']];
  let idx = 0;
  function next() {
    if (tpdState.allExhausted) return;
    if (idx >= emails.length) return;
    const email = emails[idx++];
    const ui = getUiState(email.id);
    if (ui.aiLoaded || ui.aiQueued) { next(); return; }
    prefetchAiAnalysis(email, () => setTimeout(next, 500));
  }
  next();
}

// Forward reference — assigned by modal.js via initStream (not circular since
// renderAiResult is pure text transformation with no DOM deps on stream).
let _renderAiResult = () => '';
export function setRenderAiResult(fn) { _renderAiResult = fn; }

// ─── Body prefetch ────────────────────────────────────────────────────────────

export function startBodyPrefetch() {
  const emails = [...viewBuffer['inbox']];
  let idx = 0;
  function next() {
    if (idx >= emails.length) return;
    const email = emails[idx++];
    if (bodyCache.has(email.id)) { next(); return; }
    fetch(`/api/email/${email.id}/body`)
      .then(r => r.json())
      .then(d => { if (d.body) bodyCache.set(email.id, d.body); })
      .catch(() => {})
      .finally(() => setTimeout(next, 800));
  }
  next();
}

// ─── Email distribution ───────────────────────────────────────────────────────

export function distributeEmail(email) {
  if (email._detail_analysis) {
    const ui = getUiState(email.id);
    ui.aiResult = email._detail_analysis;
    ui.aiLoaded = true;
    ui.aiQueued = true;
  }
  addToView(email, 'all_mail');
  if (email.is_in_inbox) addToView(email, 'inbox');
  if (email.is_moodle)   addToView(email, 'moodle');
}

// ─── View buffer management ───────────────────────────────────────────────────

function _sortKey(email) {
  return (email._ts > 0) ? email._ts : -(email._index ?? Infinity);
}

function _insertBufferSorted(view, email) {
  const key = _sortKey(email);
  const buf = viewBuffer[view];
  let lo = 0, hi = buf.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (_sortKey(buf[mid]) >= key) lo = mid + 1;
    else hi = mid;
  }
  buf.splice(lo, 0, email);
}

export function addToView(email, view) {
  if (viewBufferedIds[view].has(email.id)) return;
  viewBufferedIds[view].add(email.id);
  _insertBufferSorted(view, email);

  viewStats[view].total++;
  if (email.is_unread)  viewStats[view].unread++;
  if (email.is_starred) viewStats[view].starred++;

  if (viewShown[view].size < PAGE_SIZE) {
    const wasEmpty = viewShown[view].size === 0;
    _renderCardInView(email, view);
    if (wasEmpty && state.currentView === view) syncLoadingBar();
  }

  if (state.currentView === view) updateStatsDisplay(view);
}

export function _renderCardInView(email, view) {
  const card = _buildCard(email, view, _onCardClick);
  getUiState(email.id).cards[view] = card;

  const emailKey = _sortKey(email);
  const container = viewListEls[view];
  let inserted = false;
  for (const child of container.children) {
    if ((child._emailKey ?? -Infinity) < emailKey) {
      container.insertBefore(card, child);
      inserted = true;
      break;
    }
  }
  if (!inserted) container.appendChild(card);
  card._emailKey = emailKey;

  viewShown[view].add(email.id);
}

export function fillNextCard(view) {
  if (viewShown[view].size >= PAGE_SIZE) return;
  let bottomKey = Infinity;
  for (const email of viewBuffer[view]) {
    if (viewShown[view].has(email.id)) {
      const k = _sortKey(email);
      if (k < bottomKey) bottomKey = k;
    }
  }
  for (const email of viewBuffer[view]) {
    if (!viewShown[view].has(email.id) && _sortKey(email) < bottomKey) {
      _renderCardInView(email, view);
      return;
    }
  }
}

export function removeCardFromView(email, view) {
  const card = getUiState(email.id).cards?.[view];
  if (card?.parentNode) {
    card.remove();
  }
  viewShown[view].delete(email.id);
  viewBufferedIds[view].delete(email.id);
  const idx = viewBuffer[view].indexOf(email);
  if (idx !== -1) viewBuffer[view].splice(idx, 1);
  fillNextCard(view);
}

export function adjustStats(view, email, delta) {
  const s = viewStats[view];
  if (!s) return;
  s.total = Math.max(0, s.total + delta);
  if (email.is_unread)  s.unread  = Math.max(0, s.unread  + delta);
  if (email.is_starred) s.starred = Math.max(0, s.starred + delta);
}

// ─── Per-view DOM containers ──────────────────────────────────────────────────

const emailListWrapper = document.getElementById('email-list');
export const viewListEls = {};
for (const v of VIEW_KEYS) {
  const el = document.createElement('div');
  el.className = 'view-email-list';
  el.style.display = 'none';
  viewListEls[v] = el;
  emailListWrapper.appendChild(el);
}
emailListWrapper.style.overflow      = 'hidden';
emailListWrapper.style.display       = 'flex';
emailListWrapper.style.flexDirection = 'column';
emailListWrapper.style.flex          = '1';

// ─── Loading bar sync ─────────────────────────────────────────────────────────

export function syncLoadingBar() {
  const view = state.currentView;
  if ((streamFlags.sharedLoading && view !== 'trash') ||
      (streamFlags.trashLoading  && view === 'trash')) {
    if (viewShown[view].size === 0) startLoading();
    else stopLoading();
  } else {
    stopLoading();
  }
}

// ─── Shared SSE stream ────────────────────────────────────────────────────────

export function startSharedStream() {
  streamFlags.sharedLoading = true;
  syncLoadingBar();
  hideStreamError();

  const source = new EventSource('/api/emails/stream');
  sseHandles.shared = source;

  source.onmessage = e => {
    const email = JSON.parse(e.data);
    if (email._body) { bodyCache.set(email.id, email._body); delete email._body; }
    distributeEmail(email);
  };

  source.addEventListener('done', () => {
    source.close();
    sseHandles.shared         = null;
    streamFlags.sharedLoaded  = true;
    streamFlags.sharedLoading = false;
    streamFlags.autoRetried   = false;
    syncLoadingBar();
    startBodyPrefetch();
    startAiPrefetch();
  });

  source.addEventListener('error', ev => {
    source.close();
    sseHandles.shared         = null;
    streamFlags.sharedLoading = false;
    syncLoadingBar();
    if (ev.data) {
      const msg = JSON.parse(ev.data).error || 'Stream error';
      const isTransient = /ssl|connection|timeout|network/i.test(msg);
      if (isTransient && !streamFlags.autoRetried) {
        streamFlags.autoRetried = true;
        setTimeout(() => { streamFlags.sharedLoaded = false; startSharedStream(); }, 2000);
        showStreamError('Connection error — retrying…', false);
      } else {
        showStreamError(msg, true);
      }
    }
  });

  source.onerror = ev => {
    if (!ev.data && source.readyState === EventSource.CLOSED) {
      streamFlags.sharedLoading = false;
      syncLoadingBar();
      if (!streamFlags.autoRetried) {
        streamFlags.autoRetried = true;
        setTimeout(() => { streamFlags.sharedLoaded = false; startSharedStream(); }, 2000);
        showStreamError('Connection lost — retrying…', false);
      } else {
        showStreamError('Could not connect to server. Check your network and retry.', true);
      }
    }
  };
}

// ─── Trash SSE ───────────────────────────────────────────────────────────────

export function loadTrash() {
  streamFlags.trashLoading = true;
  syncLoadingBar();

  const source = new EventSource('/api/emails/stream?view=trash');
  sseHandles.trash = source;

  source.onmessage = e => {
    const email = JSON.parse(e.data);
    viewBuffer['trash'].push(email);
    viewStats['trash'].total++;
    if (viewShown['trash'].size < PAGE_SIZE) _renderCardInView(email, 'trash');
    if (state.currentView === 'trash') updateStatsDisplay('trash');
  };

  source.addEventListener('done', () => {
    source.close();
    sseHandles.trash         = null;
    streamFlags.trashLoaded  = true;
    streamFlags.trashLoading = false;
    syncLoadingBar();
  });

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      streamFlags.trashLoading = false;
      syncLoadingBar();
    }
  };
}

// ─── Refresh ──────────────────────────────────────────────────────────────────

export function refreshCurrentView(view) {
  if (view === 'trash') {
    if (sseHandles.trash) { sseHandles.trash.close(); sseHandles.trash = null; }
    streamFlags.trashLoaded  = false;
    streamFlags.trashLoading = false;
    viewListEls['trash'].innerHTML = '';
    viewStats['trash'] = { total: 0, unread: 0, starred: 0 };
    viewBuffer['trash'] = []; viewShown['trash'] = new Set(); viewBufferedIds['trash'] = new Set();
    loadTrash();
  } else {
    if (sseHandles.shared) { sseHandles.shared.close(); sseHandles.shared = null; }
    streamFlags.sharedLoaded  = false;
    streamFlags.sharedLoading = false;
    streamFlags.autoRetried   = false;
    for (const v of ['inbox', 'moodle', 'all_mail']) {
      viewListEls[v].innerHTML = '';
      viewStats[v] = { total: 0, unread: 0, starred: 0 };
      viewBuffer[v] = []; viewShown[v] = new Set(); viewBufferedIds[v] = new Set();
    }
    updateStatsDisplay(view);
    startSharedStream();
  }
}
