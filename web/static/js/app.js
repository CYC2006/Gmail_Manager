'use strict';

// ─── State ────────────────────────────────────────────────────────────────────

const state = {
  currentView: 'inbox',
  currentEmail: null,
  calEvents: [],
  calYear: new Date().getFullYear(),
  calMonth: new Date().getMonth(),
};

// ─── Per-view email list containers ──────────────────────────────────────────
// Each view gets its own persistent DOM node.
// Switching views = show/hide only; never re-fetches or re-renders.
//
// PAGE_SIZE: max cards shown at once per view.
// viewBuffer: all fetched emails (sorted order) — the full pool.
// viewShown:  Set of email IDs currently rendered in the DOM.
// When a card is removed, fillNextCard() pulls the next buffered email in.

const PAGE_SIZE = 50;
const VIEW_KEYS = ['inbox', 'moodle', 'all_mail', 'trash'];

const viewStats = {};
for (const v of VIEW_KEYS) viewStats[v] = { total: 0, unread: 0, starred: 0 };

const viewBuffer     = {};
const viewShown      = {};
const viewBufferedIds = {};
for (const v of VIEW_KEYS) { viewBuffer[v] = []; viewShown[v] = new Set(); viewBufferedIds[v] = new Set(); }

const emailListWrapper = document.getElementById('email-list');
const viewListEls = {};
for (const v of VIEW_KEYS) {
  const el = document.createElement('div');
  el.className = 'view-email-list';
  el.style.display = 'none';
  viewListEls[v] = el;
  emailListWrapper.appendChild(el);
}

// Shared SSE for inbox / moodle / all_mail
let sharedSse     = null;
let sharedLoaded  = false;
let sharedLoading = false;

// Trash SSE
let trashSse     = null;
let trashLoaded  = false;
let trashLoading = false;

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const sidebar    = document.getElementById('sidebar');
const loadingBar = $('loading-bar');
const statsBar   = $('stats-bar');

// ─── Theme ───────────────────────────────────────────────────────────────────

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');
let _currentThemeSetting = 'dark';

function resolveTheme(theme) {
  if (theme === 'system') return systemDark.matches ? 'dark' : 'light';
  return theme;
}

function applyTheme(theme) {
  _currentThemeSetting = theme;
  document.documentElement.setAttribute('data-theme', resolveTheme(theme));
  document.querySelectorAll('input[name="theme"]').forEach(r => {
    r.checked = r.value === theme;
  });
}

function initTheme() {
  fetch('/api/settings/theme')
    .then(r => r.json())
    .then(d => applyTheme(d.theme || 'dark'))
    .catch(() => applyTheme('dark'));
}

systemDark.addEventListener('change', () => {
  if (_currentThemeSetting === 'system') applyTheme('system');
});

document.querySelectorAll('input[name="theme"]').forEach(radio => {
  radio.addEventListener('change', () => {
    applyTheme(radio.value);
    fetch('/api/settings/theme', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: radio.value }),
    });
  });
});

// ─── Sidebar collapse ─────────────────────────────────────────────────────────

$('sidebar-toggle').addEventListener('click', () => sidebar.classList.toggle('collapsed'));

// ─── View routing ─────────────────────────────────────────────────────────────

const EMAIL_VIEWS = new Set(['inbox', 'moodle', 'all_mail', 'trash']);

const VIEW_META = {
  inbox:    { icon: 'inbox',        title: 'Inbox',     statsTotal: true  },
  moodle:   { icon: 'school',       title: 'Moodle',    statsTotal: false },
  all_mail: { icon: 'all_inbox',    title: 'All Mails', statsTotal: false },
  trash:    { icon: 'delete',       title: 'Trash',     statsTotal: false },
  calendar: { icon: 'calendar_month', title: 'Calendar' },
  settings: { icon: 'settings',    title: 'Settings'  },
};

function switchView(view) {
  state.currentView = view;

  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === view);
  });

  document.querySelectorAll('.view').forEach(s => s.classList.remove('active'));

  if (EMAIL_VIEWS.has(view)) {
    $('view-emails').classList.add('active');
    const meta = VIEW_META[view];
    $('view-icon').textContent  = meta.icon;
    $('view-title').textContent = meta.title;
    $('stat-total').style.display = meta.statsTotal ? '' : 'none';
    statsBar.classList.toggle('hidden', view === 'trash');

    // Show correct per-view container; hide the rest
    for (const v of VIEW_KEYS) {
      viewListEls[v].style.display = v === view ? '' : 'none';
    }

    updateStatsDisplay(view);
    syncLoadingBar();

    if (view === 'trash') {
      if (!trashLoaded && !trashLoading) loadTrash();
    } else {
      if (!sharedLoaded && !sharedLoading) startSharedStream();
    }

  } else if (view === 'calendar') {
    $('view-calendar').classList.add('active');
    loadCalendar();
  } else if (view === 'settings') {
    $('view-settings').classList.add('active');
    // load whichever tab is currently active
    const activeStab = document.querySelector('.stab.active')?.dataset?.stab;
    if (activeStab === 'preference') loadPreferenceTab();
    else if (activeStab === 'account') loadAccountTab();
    else if (activeStab === 'api_keys') loadApiKeysTab();
  }
}

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => switchView(btn.dataset.view));
});

// ─── Shared SSE stream (inbox / moodle / all_mail) ───────────────────────────

let _autoRetried = false;

function syncLoadingBar() {
  const view = state.currentView;
  // Show bar only when stream is active AND current view has no cards yet
  if ((sharedLoading && view !== 'trash') || (trashLoading && view === 'trash')) {
    if (viewShown[view].size === 0) startLoading();
    else stopLoading();
  } else {
    stopLoading();
  }
}

function startSharedStream() {
  sharedLoading = true;
  syncLoadingBar();
  hideStreamError();

  const source = new EventSource('/api/emails/stream');
  sharedSse = source;

  source.onmessage = e => {
    const email = JSON.parse(e.data);
    distributeEmail(email);
  };

  source.addEventListener('done', () => {
    source.close();
    sharedSse     = null;
    sharedLoaded  = true;
    sharedLoading = false;
    _autoRetried  = false;
    syncLoadingBar();
  });

  source.addEventListener('error', ev => {
    source.close();
    sharedSse     = null;
    sharedLoading = false;
    syncLoadingBar();
    if (ev.data) {
      const msg = JSON.parse(ev.data).error || 'Stream error';
      const isTransient = /ssl|connection|timeout|network/i.test(msg);
      if (isTransient && !_autoRetried) {
        _autoRetried = true;
        setTimeout(() => { sharedLoaded = false; startSharedStream(); }, 2000);
        showStreamError('Connection error — retrying…', false);
      } else {
        showStreamError(msg, true);
      }
    }
  });

  // Browser-level SSE disconnect (not a custom event: error)
  source.onerror = ev => {
    if (!ev.data && source.readyState === EventSource.CLOSED) {
      sharedLoading = false;
      syncLoadingBar();
      if (!_autoRetried) {
        _autoRetried = true;
        setTimeout(() => { sharedLoaded = false; startSharedStream(); }, 2000);
        showStreamError('Connection lost — retrying…', false);
      } else {
        showStreamError('Could not connect to server. Check your network and retry.', true);
      }
    }
  };
}

function distributeEmail(email) {
  // all_mail gets every email
  addToView(email, 'all_mail');

  // inbox: only emails that are in the inbox label
  if (email.is_in_inbox) addToView(email, 'inbox');

  // moodle: emails from moodle
  if (email.sender?.toLowerCase().includes('moodle')) addToView(email, 'moodle');
}

// Sort key: higher value = newer = top of list.
// Uses internalDate timestamp (_ts) when available; falls back to inverted _index.
function _sortKey(email) {
  return (email._ts > 0) ? email._ts : -(email._index ?? Infinity);
}

// Binary-search insert into buffer sorted by _sortKey descending (higher = newer = top)
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

function addToView(email, view) {
  if (viewBufferedIds[view].has(email.id)) return;
  viewBufferedIds[view].add(email.id);
  _insertBufferSorted(view, email);

  viewStats[view].total++;
  if (email.is_unread)  viewStats[view].unread++;
  if (email.is_starred) viewStats[view].starred++;

  // Only render if under PAGE_SIZE; rest stays buffered
  if (viewShown[view].size < PAGE_SIZE) {
    const wasEmpty = viewShown[view].size === 0;
    _renderCardInView(email, view);
    // Hide loading bar once first card appears in the active view
    if (wasEmpty && state.currentView === view) syncLoadingBar();
  }

  if (state.currentView === view) updateStatsDisplay(view);
}

function _renderCardInView(email, view) {
  const card = buildCard(email, view);
  if (!email._cards) email._cards = {};
  email._cards[view] = card;

  // Insert before the first child that is older (lower sort key)
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

function fillNextCard(view) {
  if (viewShown[view].size >= PAGE_SIZE) return;
  // Find the sort key of the current bottom-most shown card (minimum = oldest)
  let bottomKey = Infinity;
  for (const email of viewBuffer[view]) {
    if (viewShown[view].has(email.id)) {
      const k = _sortKey(email);
      if (k < bottomKey) bottomKey = k;
    }
  }
  // Buffer is sorted descending by sort key; first un-shown with key < bottomKey
  // is the next-oldest email and will always append at the bottom
  for (const email of viewBuffer[view]) {
    if (!viewShown[view].has(email.id) && _sortKey(email) < bottomKey) {
      _renderCardInView(email, view);
      return;
    }
  }
}

// ─── Trash SSE ───────────────────────────────────────────────────────────────

function loadTrash() {
  trashLoading = true;
  syncLoadingBar();

  const source = new EventSource('/api/emails/stream?view=trash');
  trashSse = source;

  source.onmessage = e => {
    const email = JSON.parse(e.data);
    viewBuffer['trash'].push(email);
    viewStats['trash'].total++;
    if (viewShown['trash'].size < PAGE_SIZE) _renderCardInView(email, 'trash');
    if (state.currentView === 'trash') updateStatsDisplay('trash');
  };

  source.addEventListener('done', () => {
    source.close();
    trashSse     = null;
    trashLoaded  = true;
    trashLoading = false;
    syncLoadingBar();
  });

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      trashLoading = false;
      syncLoadingBar();
    }
  };
}

// ─── Refresh ──────────────────────────────────────────────────────────────────

function refreshCurrentView() {
  const view = state.currentView;
  if (view === 'trash') {
    if (trashSse) { trashSse.close(); trashSse = null; }
    trashLoaded  = false;
    trashLoading = false;
    viewListEls['trash'].innerHTML = '';
    viewStats['trash'] = { total: 0, unread: 0, starred: 0 };
    viewBuffer['trash'] = []; viewShown['trash'] = new Set(); viewBufferedIds['trash'] = new Set();
    loadTrash();
  } else {
    // refresh shared stream — clears all three views
    if (sharedSse) { sharedSse.close(); sharedSse = null; }
    sharedLoaded  = false;
    sharedLoading = false;
    _autoRetried  = false;
    for (const v of ['inbox', 'moodle', 'all_mail']) {
      viewListEls[v].innerHTML = '';
      viewStats[v] = { total: 0, unread: 0, starred: 0 };
      viewBuffer[v] = []; viewShown[v] = new Set(); viewBufferedIds[v] = new Set();
    }
    updateStatsDisplay(view);
    startSharedStream();
  }
}

$('refresh-btn').addEventListener('click', refreshCurrentView);

// ─── Stats display ────────────────────────────────────────────────────────────

function updateStatsDisplay(view) {
  const s = viewStats[view] || { total: 0, unread: 0, starred: 0 };
  $('stat-total-val').textContent   = s.total;
  $('stat-unread-val').textContent  = s.unread;
  $('stat-starred-val').textContent = s.starred;
}

function startLoading() { loadingBar.classList.add('active'); }
function stopLoading()  { loadingBar.classList.remove('active'); }

// ─── Category badge ───────────────────────────────────────────────────────────

function badgeEl(category) {
  if (!category) return document.createDocumentFragment();
  const span = document.createElement('span');
  span.className = `cat-badge badge-${category}`;
  span.textContent = category;
  return span;
}

// ─── Email card builder ───────────────────────────────────────────────────────

function buildCard(email, view) {
  const isMoodle  = email.sender?.toLowerCase().includes('moodle');
  const isMatched = email.matched_prefs?.length > 0;

  const card = document.createElement('div');
  card.className = ['email-card',
    email.is_unread ? 'unread'  : '',
    isMatched       ? 'matched' : '',
  ].filter(Boolean).join(' ');
  card.dataset.id = email.id;

  // top row
  const top = document.createElement('div');
  top.className = 'card-top';

  const sender = document.createElement('span');
  sender.className = 'card-sender' + (isMoodle ? ' moodle' : '');
  if (isMoodle) {
    sender.innerHTML = '<span class="material-icons-round moodle-icon">school</span> Moodle';
  } else {
    sender.textContent = email.sender || '(Unknown)';
  }

  const actions = document.createElement('div');
  actions.className = 'card-actions';

  const timeSpan = document.createElement('span');
  timeSpan.className = 'card-time';
  timeSpan.textContent = email.time || '';
  actions.appendChild(timeSpan);

  if (view === 'trash') {
    actions.appendChild(cardBtn('restore_from_trash', 'Restore', 'success', () => {
      removeCardFromView(email, 'trash');
      viewStats['trash'].total = Math.max(0, viewStats['trash'].total - 1);
      if (state.currentView === 'trash') updateStatsDisplay('trash');
      apiPost(`/api/email/${email.id}/restore`);
    }));
    actions.appendChild(cardBtn('delete_forever', 'Delete permanently', 'danger', () => {
      removeCardFromView(email, 'trash');
      viewStats['trash'].total = Math.max(0, viewStats['trash'].total - 1);
      if (state.currentView === 'trash') updateStatsDisplay('trash');
      apiPost(`/api/email/${email.id}/delete`);
    }));
  } else {
    // mark read
    actions.appendChild(cardBtn('mark_email_read', 'Mark as read', '', () => {
      if (!email.is_unread) return;
      markEmailRead(email);
      apiPost(`/api/email/${email.id}/mark_read`);
    }));

    // star — store ref for cross-view sync
    const starBtnEl = cardBtn(
      email.is_starred ? 'star' : 'star_border',
      'Star',
      email.is_starred ? 'star-active' : '',
      () => {
        const newVal = !email.is_starred;
        updateEmailStar(email, newVal);
        apiPost(`/api/email/${email.id}/star`, { starred: newVal });
      }
    );
    if (!email._starBtns) email._starBtns = [];
    email._starBtns.push(starBtnEl);
    actions.appendChild(starBtnEl);

    if (view === 'all_mail') {
      actions.appendChild(cardBtn('move_to_inbox', 'Move to Inbox', 'success', () => {
        removeCardFromView(email, 'all_mail');
        adjustStats('all_mail', email, -1);
        if (state.currentView === 'all_mail') updateStatsDisplay('all_mail');
        apiPost(`/api/email/${email.id}/unarchive`);
      }));
    } else {
      actions.appendChild(cardBtn('archive', 'Archive', 'success', () => {
        removeCardFromView(email, 'inbox');
        removeCardFromView(email, 'moodle');
        adjustStats('inbox', email, -1);
        if (isMoodle) adjustStats('moodle', email, -1);
        if (state.currentView === view) updateStatsDisplay(view);
        apiPost(`/api/email/${email.id}/archive`);
      }));
    }

    actions.appendChild(cardBtn('delete', 'Delete', 'danger', () => {
      for (const v of ['inbox', 'moodle', 'all_mail']) {
        adjustStats(v, email, -1);
        removeCardFromView(email, v);
      }
      if (state.currentView === view) updateStatsDisplay(view);
      apiPost(`/api/email/${email.id}/trash`);
    }));
  }

  top.appendChild(sender);
  top.appendChild(actions);

  // bottom row
  const bottom = document.createElement('div');
  bottom.className = 'card-bottom';
  bottom.appendChild(badgeEl(email.category));

  const subject = document.createElement('span');
  subject.className = 'card-subject';
  subject.textContent = email.display_subject || email.subject || '(No Subject)';
  bottom.appendChild(subject);

  card.appendChild(top);
  card.appendChild(bottom);

  card.addEventListener('click', e => {
    if (e.target.closest('.card-btn')) return;
    openModal(email, view);
  });

  return card;
}

function cardBtn(icon, title, extraClass, handler) {
  const btn = document.createElement('button');
  btn.className = `card-btn${extraClass ? ' ' + extraClass : ''}`;
  btn.title = title;
  btn.innerHTML = `<span class="material-icons-round">${icon}</span>`;
  let inFlight = false;
  btn.addEventListener('click', e => {
    e.stopPropagation();
    if (inFlight) return;
    inFlight = true;
    handler();
    setTimeout(() => { inFlight = false; }, 500);
  });
  return btn;
}

// ─── Cross-view helpers ───────────────────────────────────────────────────────

function removeCardFromView(email, view) {
  const card = email._cards?.[view];
  if (card?.parentNode) card.remove();
  viewShown[view].delete(email.id);
  viewBufferedIds[view].delete(email.id);
  // Remove from buffer so it can't be filled back in
  const idx = viewBuffer[view].indexOf(email);
  if (idx !== -1) viewBuffer[view].splice(idx, 1);
  // Pull in the next buffered email
  fillNextCard(view);
}

function adjustStats(view, email, delta) {
  const s = viewStats[view];
  if (!s) return;
  s.total   = Math.max(0, s.total   + delta);
  if (email.is_unread)  s.unread  = Math.max(0, s.unread  + delta);
  if (email.is_starred) s.starred = Math.max(0, s.starred + delta);
}

function markEmailRead(email) {
  if (!email.is_unread) return;
  email.is_unread = false;
  // update card backgrounds in all views
  for (const v of ['inbox', 'moodle', 'all_mail']) {
    const card = email._cards?.[v];
    if (card) card.classList.remove('unread');
    viewStats[v].unread = Math.max(0, (viewStats[v].unread || 0) - 1);
  }
  if (state.currentView !== 'trash') updateStatsDisplay(state.currentView);
}

function updateEmailStar(email, newVal) {
  email.is_starred = newVal;
  // sync all star buttons
  for (const btn of email._starBtns || []) {
    btn.querySelector('.material-icons-round').textContent = newVal ? 'star' : 'star_border';
    btn.classList.toggle('star-active', newVal);
  }
  // sync modal
  if (state.currentEmail?.id === email.id) syncModalStar(newVal);
  // update stats in all views
  const delta = newVal ? 1 : -1;
  for (const v of ['inbox', 'moodle', 'all_mail']) {
    if (email._cards?.[v]) viewStats[v].starred = Math.max(0, (viewStats[v].starred || 0) + delta);
  }
  if (state.currentView !== 'trash') updateStatsDisplay(state.currentView);
}

// ─── Email detail modal ───────────────────────────────────────────────────────

const modalBackdrop   = $('modal-backdrop');
const modalSubject    = $('modal-subject');
const modalSender     = $('modal-sender');
const modalTime       = $('modal-time');
const modalBodyText   = $('modal-body-text');
const bodyLoading     = $('body-loading');
const aiLoadingEl     = $('ai-loading');
const aiResult        = $('ai-result');
const modalStarBtn    = $('modal-star-btn');
const modalArchiveBtn = $('modal-archive-btn');
const modalTrashBtn   = $('modal-trash-btn');
const modalGmailLink  = $('modal-gmail-link');

function openModal(email, view) {
  state.currentEmail = email;

  modalSubject.textContent = email.display_subject || email.subject || '(No Subject)';
  modalSender.textContent  = email.sender  || '';
  modalTime.textContent    = email.time    || '';
  modalGmailLink.href = `https://mail.google.com/mail/u/0/#all/${email.id}`;

  syncModalStar(email.is_starred);

  // Archive / trash button labels
  const archiveIcon = modalArchiveBtn.querySelector('.material-icons-round');
  const trashIcon   = modalTrashBtn.querySelector('.material-icons-round');
  if (view === 'trash') {
    archiveIcon.textContent = 'restore_from_trash'; modalArchiveBtn.title = 'Restore';
    trashIcon.textContent   = 'delete_forever';      modalTrashBtn.title   = 'Delete permanently';
  } else if (view === 'all_mail') {
    archiveIcon.textContent = 'move_to_inbox'; modalArchiveBtn.title = 'Move to Inbox';
    trashIcon.textContent   = 'delete';         modalTrashBtn.title   = 'Delete';
  } else {
    archiveIcon.textContent = 'archive'; modalArchiveBtn.title = 'Archive';
    trashIcon.textContent   = 'delete';   modalTrashBtn.title   = 'Delete';
  }

  switchModalTab('raw');
  modalBackdrop.classList.remove('hidden');

  // Load body
  bodyLoading.classList.remove('hidden');
  modalBodyText.textContent = '';
  fetch(`/api/email/${email.id}/body`)
    .then(r => r.json())
    .then(d => {
      bodyLoading.classList.add('hidden');
      modalBodyText.textContent = d.body || '';
      if (email.is_unread) {
        markEmailRead(email);
        apiPost(`/api/email/${email.id}/mark_read`);
      }
    })
    .catch(() => {
      bodyLoading.classList.add('hidden');
      modalBodyText.textContent = '(Failed to load email body.)';
    });
}

function closeModal() {
  modalBackdrop.classList.add('hidden');
  state.currentEmail = null;
}

function syncModalStar(starred) {
  modalStarBtn.querySelector('.material-icons-round').textContent = starred ? 'star' : 'star_border';
  modalStarBtn.classList.toggle('star-active', starred);
}

function switchModalTab(tab) {
  $('tab-raw').classList.toggle('active', tab === 'raw');
  $('tab-ai').classList.toggle('active', tab === 'ai');
  $('tab-raw-btn').classList.toggle('active', tab === 'raw');
  $('tab-ai-btn').classList.toggle('active', tab === 'ai');
  if (tab === 'ai' && state.currentEmail && !state.currentEmail._aiLoaded) {
    loadAiAnalysis(state.currentEmail);
  }
}

function loadAiAnalysis(email) {
  aiLoadingEl.classList.remove('hidden');
  aiResult.innerHTML = '';
  fetch(`/api/email/${email.id}/analyze`)
    .then(r => r.json())
    .then(d => {
      email._aiLoaded = true;
      aiLoadingEl.classList.add('hidden');
      aiResult.innerHTML = d.error ? `<p>Error: ${escHtml(d.error)}</p>` : renderAiResult(d);
    })
    .catch(() => {
      aiLoadingEl.classList.add('hidden');
      aiResult.textContent = '(Analysis failed. Switch tabs to retry.)';
    });
}

function renderAiResult(data) {
  if (!data || !Object.keys(data).length) return '<p>(No analysis available.)</p>';
  const labels = { summary: 'Summary', category: 'Category', action_required: 'Action Required', event_time: 'Event Time', sender: 'Sender' };
  let html = '';
  for (const [key, label] of Object.entries(labels)) {
    if (data[key]) html += `<h4>${label}</h4><p>${escHtml(String(data[key]))}</p>`;
  }
  for (const [key, val] of Object.entries(data)) {
    if (labels[key] || !val) continue;
    html += `<h4>${escHtml(key)}</h4><p>${escHtml(String(val))}</p>`;
  }
  return html || '<p>(No analysis available.)</p>';
}

function escHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Modal action buttons
modalStarBtn.addEventListener('click', () => {
  const email = state.currentEmail;
  if (!email) return;
  const newVal = !email.is_starred;
  updateEmailStar(email, newVal);
  apiPost(`/api/email/${email.id}/star`, { starred: newVal });
});

modalArchiveBtn.addEventListener('click', () => {
  const email = state.currentEmail;
  if (!email) return;
  const view = state.currentView;
  closeModal();
  if (view === 'trash') {
    removeCardFromView(email, 'trash');
    adjustStats('trash', email, -1);
    updateStatsDisplay('trash');
    apiPost(`/api/email/${email.id}/restore`);
  } else if (view === 'all_mail') {
    removeCardFromView(email, 'all_mail');
    adjustStats('all_mail', email, -1);
    updateStatsDisplay('all_mail');
    apiPost(`/api/email/${email.id}/unarchive`);
  } else {
    const isMoodle = email.sender?.toLowerCase().includes('moodle');
    removeCardFromView(email, 'inbox');
    removeCardFromView(email, 'moodle');
    adjustStats('inbox', email, -1);
    if (isMoodle) adjustStats('moodle', email, -1);
    updateStatsDisplay(view);
    apiPost(`/api/email/${email.id}/archive`);
  }
});

modalTrashBtn.addEventListener('click', () => {
  const email = state.currentEmail;
  if (!email) return;
  const view = state.currentView;
  closeModal();
  if (view === 'trash') {
    removeCardFromView(email, 'trash');
    adjustStats('trash', email, -1);
    updateStatsDisplay('trash');
    apiPost(`/api/email/${email.id}/delete`);
  } else {
    for (const v of ['inbox', 'moodle', 'all_mail']) {
      removeCardFromView(email, v);
      adjustStats(v, email, -1);
    }
    updateStatsDisplay(view);
    apiPost(`/api/email/${email.id}/trash`);
  }
});

$('modal-close-btn').addEventListener('click', closeModal);
modalBackdrop.addEventListener('click', e => { if (e.target === modalBackdrop) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
$('tab-raw-btn').addEventListener('click', () => switchModalTab('raw'));
$('tab-ai-btn').addEventListener('click',  () => switchModalTab('ai'));

// ─── Calendar ─────────────────────────────────────────────────────────────────

const CAL_COLORS = [
  { id: 'blue',   dot: '#1e88e5' },
  { id: 'teal',   dot: '#00897b' },
  { id: 'green',  dot: '#43a047' },
  { id: 'amber',  dot: '#f9a825' },
  { id: 'red',    dot: '#e53935' },
  { id: 'purple', dot: '#8e24aa' },
  { id: 'grey',   dot: '#757575' },
];

let selectedCeColor = CAL_COLORS[0].id;
let ceIsAllDay = false;
let ceDateKey  = '';

function loadCalendar() {
  fetch('/api/calendar/events')
    .then(r => r.json())
    .then(events => { state.calEvents = events; renderCalendar(); })
    .catch(console.error);
}

function renderCalendar() {
  const { calYear: year, calMonth: month } = state;
  const months = ['January','February','March','April','May','June',
                  'July','August','September','October','November','December'];
  $('cal-month-label').textContent = `${months[month]} ${year}`;

  const grid = $('cal-grid');
  grid.innerHTML = '';

  const today        = new Date();
  const firstDay     = new Date(year, month, 1).getDay();
  const daysInMonth  = new Date(year, month + 1, 0).getDate();
  const prevDays     = new Date(year, month, 0).getDate();

  const byDate = {};
  for (const ev of state.calEvents) {
    const dk = (ev.event_time || '').substring(0, 10);
    if (!byDate[dk]) byDate[dk] = [];
    byDate[dk].push(ev);
  }

  for (let i = 0; i < firstDay; i++) {
    grid.appendChild(calCell(year, month - 1, prevDays - firstDay + 1 + i, byDate, true));
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = d === today.getDate() && month === today.getMonth() && year === today.getFullYear();
    grid.appendChild(calCell(year, month, d, byDate, false, isToday));
  }
  const trailing = (firstDay + daysInMonth) % 7;
  for (let d = 1; d <= (trailing ? 7 - trailing : 0); d++) {
    grid.appendChild(calCell(year, month + 1, d, byDate, true));
  }
}

function calCell(year, month, day, byDate, otherMonth, isToday = false) {
  const rd  = new Date(year, month, day);
  const dk  = `${rd.getFullYear()}-${String(rd.getMonth()+1).padStart(2,'0')}-${String(rd.getDate()).padStart(2,'0')}`;
  const dow = rd.getDay();

  const cell = document.createElement('div');
  cell.className = ['cal-cell', otherMonth ? 'other-month' : '', isToday ? 'today' : ''].filter(Boolean).join(' ');

  const dayNum = document.createElement('div');
  dayNum.className = `cal-day-num ${dow===0?'sun':dow===6?'sat':''}`;
  dayNum.textContent = day;
  cell.appendChild(dayNum);

  for (const ev of (byDate[dk] || []).slice(0, 3)) {
    const c = CAL_COLORS.find(c => c.id === ev.color) || { dot: '#757575' };
    const chip = document.createElement('div');
    chip.className = 'cal-event-chip';
    chip.style.background = c.dot;
    chip.textContent = ev.label || ev.event_time;
    chip.title = ev.label;
    cell.appendChild(chip);
  }
  if ((byDate[dk] || []).length > 3) {
    const more = document.createElement('div');
    more.style.cssText = 'font-size:.65rem;color:var(--text-muted);padding:1px 5px';
    more.textContent = `+${byDate[dk].length - 3} more`;
    cell.appendChild(more);
  }

  const addBtn = document.createElement('button');
  addBtn.className = 'cal-add-btn';
  addBtn.textContent = '+ New event';
  addBtn.addEventListener('click', e => { e.stopPropagation(); openCeModal(dk); });
  cell.appendChild(addBtn);

  return cell;
}

$('cal-prev').addEventListener('click', () => {
  state.calMonth--;
  if (state.calMonth < 0) { state.calMonth = 11; state.calYear--; }
  renderCalendar();
});
$('cal-next').addEventListener('click', () => {
  state.calMonth++;
  if (state.calMonth > 11) { state.calMonth = 0; state.calYear++; }
  renderCalendar();
});
$('cal-today').addEventListener('click', () => {
  state.calYear = new Date().getFullYear();
  state.calMonth = new Date().getMonth();
  renderCalendar();
});

// ─── Create event modal ───────────────────────────────────────────────────────

function buildTimeSelects() {
  const hOpts = Array.from({length:24}, (_,i) => String(i).padStart(2,'0'));
  const mOpts = ['00','05','10','15','20','25','30','35','40','45','50','55'];
  for (const id of ['ce-start-h','ce-end-h']) {
    $(id).innerHTML = hOpts.map(h => `<option>${h}</option>`).join('');
  }
  $('ce-start-h').value = '09'; $('ce-end-h').value = '10';
  for (const id of ['ce-start-m','ce-end-m']) {
    $(id).innerHTML = mOpts.map(m => `<option>${m}</option>`).join('');
  }
  const row = $('ce-color-row');
  row.innerHTML = '';
  for (const c of CAL_COLORS) {
    const dot = document.createElement('div');
    dot.className = 'ce-color-dot' + (c.id === selectedCeColor ? ' selected' : '');
    dot.style.background = c.dot;
    dot.addEventListener('click', () => {
      selectedCeColor = c.id;
      document.querySelectorAll('.ce-color-dot').forEach(d => d.classList.remove('selected'));
      dot.classList.add('selected');
    });
    row.appendChild(dot);
  }
}
buildTimeSelects();

function openCeModal(dateKey) {
  ceDateKey = dateKey;
  $('ce-date-label').textContent = dateKey;
  $('ce-title').value = ''; $('ce-notes').value = ''; $('ce-title-error').textContent = '';
  setCeAllDay(false); selectedCeColor = CAL_COLORS[0].id; buildTimeSelects();
  $('ce-backdrop').classList.remove('hidden');
}
function closeCeModal() { $('ce-backdrop').classList.add('hidden'); }

function setCeAllDay(val) {
  ceIsAllDay = val;
  $('ce-time-row').style.display = val ? 'none' : '';
  $('ce-timed-btn').classList.toggle('active', !val);
  $('ce-allday-btn').classList.toggle('active', val);
}

$('ce-timed-btn').addEventListener('click',  () => setCeAllDay(false));
$('ce-allday-btn').addEventListener('click', () => setCeAllDay(true));
$('ce-close-btn').addEventListener('click',  closeCeModal);
$('ce-cancel-btn').addEventListener('click', closeCeModal);
$('ce-backdrop').addEventListener('click', e => { if (e.target === $('ce-backdrop')) closeCeModal(); });

$('ce-save-btn').addEventListener('click', async () => {
  const title = $('ce-title').value.trim();
  if (!title) { $('ce-title-error').textContent = 'Title is required'; return; }
  $('ce-title-error').textContent = '';
  await fetch('/api/calendar/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      date_key: ceDateKey, title,
      is_all_day: ceIsAllDay,
      start_time: ceIsAllDay ? '' : `${$('ce-start-h').value}:${$('ce-start-m').value}`,
      end_time:   ceIsAllDay ? '' : `${$('ce-end-h').value}:${$('ce-end-m').value}`,
      color: selectedCeColor,
      notes: $('ce-notes').value.trim(),
    }),
  });
  closeCeModal(); loadCalendar();
});

// ─── Settings tabs ────────────────────────────────────────────────────────────

document.querySelectorAll('.stab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.stab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $(`stab-${btn.dataset.stab}`).classList.add('active');
  });
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

let _toastTimer = null;
function showToast(msg, durationMs = 3500) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.hidden = true; }, durationMs);
}

async function apiPost(url, body = null) {
  const opts = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  try {
    const data = await (await fetch(url, opts)).json();
    if (data.error) showToast(`Error: ${data.error}`);
    return data;
  } catch (err) {
    console.error('apiPost', url, err);
    showToast('Network error — action may not have saved');
  }
}

const streamErrorBanner = $('stream-error-banner');
const streamErrorMsg    = $('stream-error-msg');
const streamRetryBtn    = $('stream-retry-btn');
const streamDismissBtn  = $('stream-error-dismiss');

streamRetryBtn.addEventListener('click', () => {
  _autoRetried = false;
  sharedLoaded = false;
  sharedSse?.close();
  sharedSse = null;
  for (const v of VIEW_KEYS.filter(v => v !== 'trash')) {
    viewListEls[v].innerHTML = '';
    viewStats[v] = { total: 0, unread: 0, starred: 0 };
    viewBuffer[v] = []; viewShown[v] = new Set(); viewBufferedIds[v] = new Set();
  }
  updateStatsDisplay(state.currentView);
  startSharedStream();
});
streamDismissBtn.addEventListener('click', hideStreamError);

function showStreamError(msg, showRetry = true) {
  streamErrorMsg.textContent = msg;
  streamRetryBtn.hidden = !showRetry;
  streamErrorBanner.hidden = false;
}
function hideStreamError() { streamErrorBanner.hidden = true; }

// ─── CSS fix: email-list wrapper needs to not scroll itself ───────────────────
// The per-view children handle their own scroll.
emailListWrapper.style.overflow = 'hidden';
emailListWrapper.style.display  = 'flex';
emailListWrapper.style.flexDirection = 'column';
emailListWrapper.style.flex     = '1';

// ─── Settings: Preference tab ────────────────────────────────────────────────

let _prefOptions   = null;   // full options JSON (cached)
let _prefSelected  = new Set();
let _prefLoaded    = false;

async function loadPreferenceTab() {
  if (_prefLoaded) return;
  _prefLoaded = true;

  const [optsRes, selRes] = await Promise.all([
    fetch('/api/settings/options').then(r => r.json()),
    fetch('/api/settings/interests').then(r => r.json()),
  ]);
  _prefOptions  = optsRes;
  _prefSelected = new Set(selRes.interests || []);

  renderPrefGrid();
}

function renderPrefGrid() {
  const grid = $('pref-grid');
  grid.innerHTML = '';
  const categories = _prefOptions.categories || [];

  for (const cat of categories) {
    const row = document.createElement('div');
    row.className = 'pref-row';

    // category label column
    const labelCol = document.createElement('div');
    labelCol.className = 'pref-cat-label';
    labelCol.innerHTML = `
      <span class="material-icons-round pref-cat-icon">${(cat.icon || 'label').toLowerCase()}</span>
      <div class="pref-cat-text">
        <span class="pref-cat-name">${cat.label}</span>
        <span class="pref-cat-abbr">${cat.abbr}</span>
      </div>`;

    // chip row
    const chipRow = document.createElement('div');
    chipRow.className = 'pref-chips';

    const interests = cat.interests || [];
    for (let i = 0; i < 5; i++) {
      if (i < interests.length) {
        const int = interests[i];
        const chip = document.createElement('button');
        chip.className = 'pref-chip' + (_prefSelected.has(int.id) ? ' active' : '');
        chip.innerHTML = `<span class="material-icons-round">${(int.icon || 'label').toLowerCase()}</span><span>${int.label}</span>`;
        chip.addEventListener('click', () => toggleInterest(int.id, chip));
        chipRow.appendChild(chip);
      } else {
        // empty slot — keeps layout uniform
        const empty = document.createElement('div');
        empty.style.flex = '1';
        chipRow.appendChild(empty);
      }
    }

    row.appendChild(labelCol);
    row.appendChild(chipRow);
    grid.appendChild(row);
  }
}

function toggleInterest(id, chipEl) {
  if (_prefSelected.has(id)) {
    _prefSelected.delete(id);
    chipEl.classList.remove('active');
  } else {
    _prefSelected.add(id);
    chipEl.classList.add('active');
  }
  // autosave
  fetch('/api/settings/interests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interests: [..._prefSelected] }),
  });
}

// ─── Settings: Account tab ───────────────────────────────────────────────────

let _accSaved   = {};
let _accCurrent = {};
let _accGender  = '';
let _accLoaded  = false;

async function loadAccountTab() {
  if (_accLoaded) return;
  _accLoaded = true;

  const [profileRes, optsRes] = await Promise.all([
    fetch('/api/settings/profile').then(r => r.json()),
    _prefOptions ? Promise.resolve(_prefOptions) : fetch('/api/settings/options').then(r => r.json()),
  ]);
  if (!_prefOptions) _prefOptions = optsRes;

  _accSaved   = { ...profileRes };
  _accCurrent = { ...profileRes };
  _accGender  = profileRes.gender || '';

  // populate name
  $('acc-name').value  = profileRes.name  || '';
  $('acc-gmail').value = profileRes.gmail || '';

  // populate gender chips
  renderGenderChips(_accGender);

  // populate major dropdown
  const sel = $('acc-major');
  sel.innerHTML = '<option value="">Select your Major…</option>';
  for (const m of (_prefOptions.major || [])) {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = `${m.label} (${m.abbr})`;
    if (m.id === profileRes.major) opt.selected = true;
    sel.appendChild(opt);
  }

  updateAccSaveBtn();
}

function renderGenderChips(selected) {
  document.querySelectorAll('.gender-chip').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.value === selected);
  });
}

document.querySelectorAll('.gender-chip').forEach(btn => {
  btn.addEventListener('click', () => {
    _accGender = btn.dataset.value;
    _accCurrent.gender = _accGender;
    renderGenderChips(_accGender);
    updateAccSaveBtn();
  });
});

$('acc-name').addEventListener('input', e => {
  _accCurrent.name = e.target.value;
  updateAccSaveBtn();
});
$('acc-gmail').addEventListener('input', e => {
  _accCurrent.gmail = e.target.value.trim();
  updateAccSaveBtn();
});
$('acc-major').addEventListener('change', e => {
  _accCurrent.major = e.target.value;
  updateAccSaveBtn();
});

function updateAccSaveBtn() {
  const changed = JSON.stringify(_accCurrent) !== JSON.stringify(_accSaved);
  const btn = $('acc-save-btn');
  btn.disabled = !changed;
}

$('acc-save-btn').addEventListener('click', async () => {
  await apiPost('/api/settings/profile', _accCurrent);
  _accSaved = { ..._accCurrent };
  updateAccSaveBtn();
});

// ─── Settings: API Keys tab ───────────────────────────────────────────────────

let _apiKeyCount = 1;
const API_KEY_MAX = 5;
let _apiLoaded = false;

async function loadApiKeysTab() {
  if (_apiLoaded) return;
  _apiLoaded = true;

  const res = await fetch('/api/settings/api-keys').then(r => r.json());
  const keys = res.keys || [''];
  _apiKeyCount = 0;
  $('api-keys-list').innerHTML = '';
  for (const k of keys) addApiKeyRow(k, k ? 'verified' : 'unverified');
  updateApiKeyBtns();
}

function addApiKeyRow(value = '', status = 'unverified') {
  _apiKeyCount++;
  const idx = _apiKeyCount;

  const row = document.createElement('div');
  row.className = 'api-key-row';
  row.id = `api-key-row-${idx}`;

  const field = document.createElement('input');
  field.className = 'api-key-field';
  field.type = 'password';
  field.placeholder = `Key ${idx}`;
  field.value = value;
  field.addEventListener('input', updateApiSaveBtn);

  const revealBtn = document.createElement('button');
  revealBtn.className = 'api-key-reveal';
  revealBtn.title = 'Show/hide key';
  revealBtn.innerHTML = '<span class="material-icons-round">visibility</span>';
  revealBtn.addEventListener('click', () => {
    const showing = field.type === 'text';
    field.type = showing ? 'password' : 'text';
    revealBtn.querySelector('.material-icons-round').textContent = showing ? 'visibility' : 'visibility_off';
  });

  const badge = document.createElement('div');
  badge.className = 'api-badge';
  setApiBadge(badge, status);

  row.appendChild(field);
  row.appendChild(revealBtn);
  row.appendChild(badge);
  $('api-keys-list').appendChild(row);
  updateApiSaveBtn();
}

function setApiBadge(badge, status) {
  badge.className = `api-badge ${status}`;
  const icons = { verified: 'check', invalid: 'close', checking: '', unverified: 'help_outline' };
  badge.innerHTML = icons[status]
    ? `<span class="material-icons-round">${icons[status]}</span>`
    : '<span class="material-icons-round spinning" style="font-size:18px;color:var(--text-muted)">sync</span>';
}

function updateApiKeyBtns() {
  $('api-minus-btn').disabled = _apiKeyCount <= 1;
  $('api-plus-btn').disabled  = _apiKeyCount >= API_KEY_MAX;
}

function updateApiSaveBtn() {
  const anyFilled = [...$('api-keys-list').querySelectorAll('.api-key-field')]
    .some(f => f.value.trim());
  $('api-save-btn').disabled = !anyFilled;
}

$('api-plus-btn').addEventListener('click', () => {
  if (_apiKeyCount < API_KEY_MAX) {
    addApiKeyRow();
    updateApiKeyBtns();
  }
});

$('api-minus-btn').addEventListener('click', () => {
  if (_apiKeyCount > 1) {
    const rows = $('api-keys-list').querySelectorAll('.api-key-row');
    rows[rows.length - 1].remove();
    _apiKeyCount--;
    updateApiKeyBtns();
    updateApiSaveBtn();
  }
});

$('api-save-btn').addEventListener('click', async () => {
  const fields = [...$('api-keys-list').querySelectorAll('.api-key-field')];
  const badges = [...$('api-keys-list').querySelectorAll('.api-badge')];
  const keys   = fields.map(f => f.value.trim()).filter(Boolean);
  if (!keys.length) return;

  // set all to checking
  fields.forEach((f, i) => { if (f.value.trim()) setApiBadge(badges[i], 'checking'); });
  $('api-save-btn').disabled = true;

  const res = await fetch('/api/settings/api-keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keys }),
  }).then(r => r.json());

  if (res.results) {
    let ri = 0;
    fields.forEach((f, i) => {
      if (f.value.trim()) {
        setApiBadge(badges[i], res.results[ri]?.status || 'unverified');
        ri++;
      }
    });
  }
  $('api-save-btn').disabled = false;
});

// ─── Hook tab switching to lazy-load settings data ────────────────────────────

const _origStabClick = document.querySelectorAll('.stab');
_origStabClick.forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.stab;
    if (tab === 'preference') loadPreferenceTab();
    if (tab === 'account')    loadAccountTab();
    if (tab === 'api_keys')   loadApiKeysTab();
  });
});

// Also load preference immediately since it's the default active tab
// (done in boot after switchView)

// ─── Boot ─────────────────────────────────────────────────────────────────────

(function init() {
  initTheme();
  fetch('/api/user')
    .then(r => r.json())
    .then(d => {
      const raw = d.email || '';
      const local = raw.split('@')[0];
      $('user-email').textContent = local.charAt(0).toUpperCase() + local.slice(1);
    });
  switchView('inbox');
})();
