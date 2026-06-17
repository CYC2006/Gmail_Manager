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

const VIEW_KEYS = ['inbox', 'moodle', 'all_mail', 'trash'];

const viewStats = {};
for (const v of VIEW_KEYS) viewStats[v] = { total: 0, unread: 0, starred: 0 };

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

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
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
  }
}

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => switchView(btn.dataset.view));
});

// ─── Shared SSE stream (inbox / moodle / all_mail) ───────────────────────────

function startSharedStream() {
  sharedLoading = true;
  startLoading();

  const source = new EventSource('/api/emails/stream');
  sharedSse = source;

  source.onmessage = e => {
    const email = JSON.parse(e.data);
    distributeEmail(email);
  };

  source.addEventListener('done', () => {
    source.close();
    sharedSse = null;
    sharedLoaded  = true;
    sharedLoading = false;
    stopLoading();
  });

  source.addEventListener('error', ev => {
    if (ev.data) showError(JSON.parse(ev.data).error || 'Stream error');
    source.close();
    sharedSse     = null;
    sharedLoading = false;
    stopLoading();
  });

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      sharedLoading = false;
      stopLoading();
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

function addToView(email, view) {
  const card = buildCard(email, view);

  // store card ref so cross-view actions can remove it later
  if (!email._cards) email._cards = {};
  email._cards[view] = card;

  viewListEls[view].appendChild(card);

  viewStats[view].total++;
  if (email.is_unread)  viewStats[view].unread++;
  if (email.is_starred) viewStats[view].starred++;

  if (state.currentView === view) updateStatsDisplay(view);
}

// ─── Trash SSE ───────────────────────────────────────────────────────────────

function loadTrash() {
  trashLoading = true;
  startLoading();

  const source = new EventSource('/api/emails/stream?view=trash');
  trashSse = source;

  source.onmessage = e => {
    const email = JSON.parse(e.data);
    const card = buildCard(email, 'trash');
    if (!email._cards) email._cards = {};
    email._cards['trash'] = card;
    viewListEls['trash'].appendChild(card);
    viewStats['trash'].total++;
    if (state.currentView === 'trash') updateStatsDisplay('trash');
  };

  source.addEventListener('done', () => {
    source.close();
    trashSse     = null;
    trashLoaded  = true;
    trashLoading = false;
    stopLoading();
  });

  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      trashLoading = false;
      stopLoading();
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
    loadTrash();
  } else {
    // refresh shared stream — clears all three views
    if (sharedSse) { sharedSse.close(); sharedSse = null; }
    sharedLoaded  = false;
    sharedLoading = false;
    for (const v of ['inbox', 'moodle', 'all_mail']) {
      viewListEls[v].innerHTML = '';
      viewStats[v] = { total: 0, unread: 0, starred: 0 };
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
    actions.appendChild(cardBtn('restore_from_trash', 'Restore', 'success', async () => {
      await apiPost(`/api/email/${email.id}/restore`);
      removeCardFromView(email, 'trash');
      viewStats['trash'].total = Math.max(0, viewStats['trash'].total - 1);
      if (state.currentView === 'trash') updateStatsDisplay('trash');
    }));
    actions.appendChild(cardBtn('delete_forever', 'Delete permanently', 'danger', async () => {
      await apiPost(`/api/email/${email.id}/delete`);
      removeCardFromView(email, 'trash');
      viewStats['trash'].total = Math.max(0, viewStats['trash'].total - 1);
      if (state.currentView === 'trash') updateStatsDisplay('trash');
    }));
  } else {
    // mark read
    actions.appendChild(cardBtn('mark_email_read', 'Mark as read', '', async () => {
      if (!email.is_unread) return;
      await apiPost(`/api/email/${email.id}/mark_read`);
      markEmailRead(email);
    }));

    // star — store ref for cross-view sync
    const starBtnEl = cardBtn(
      email.is_starred ? 'star' : 'star_border',
      'Star',
      email.is_starred ? 'star-active' : '',
      async () => {
        const newVal = !email.is_starred;
        await apiPost(`/api/email/${email.id}/star`, { starred: newVal });
        updateEmailStar(email, newVal);
      }
    );
    if (!email._starBtns) email._starBtns = [];
    email._starBtns.push(starBtnEl);
    actions.appendChild(starBtnEl);

    if (view === 'all_mail') {
      actions.appendChild(cardBtn('move_to_inbox', 'Move to Inbox', 'success', async () => {
        await apiPost(`/api/email/${email.id}/unarchive`);
        removeCardFromView(email, 'all_mail');
        adjustStats('all_mail', email, -1);
        if (state.currentView === 'all_mail') updateStatsDisplay('all_mail');
      }));
    } else {
      actions.appendChild(cardBtn('archive', 'Archive', 'success', async () => {
        await apiPost(`/api/email/${email.id}/archive`);
        // Remove from inbox (and moodle if applicable); all_mail keeps it
        removeCardFromView(email, 'inbox');
        removeCardFromView(email, 'moodle');
        adjustStats('inbox', email, -1);
        if (isMoodle) adjustStats('moodle', email, -1);
        if (state.currentView === view) updateStatsDisplay(view);
      }));
    }

    actions.appendChild(cardBtn('delete', 'Delete', 'danger', async () => {
      await apiPost(`/api/email/${email.id}/trash`);
      // Remove from inbox / moodle / all_mail
      for (const v of ['inbox', 'moodle', 'all_mail']) {
        adjustStats(v, email, -1);
        removeCardFromView(email, v);
      }
      if (state.currentView === view) updateStatsDisplay(view);
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
  subject.textContent = email.subject || '(No Subject)';
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
  btn.addEventListener('click', e => { e.stopPropagation(); handler(); });
  return btn;
}

// ─── Cross-view helpers ───────────────────────────────────────────────────────

function removeCardFromView(email, view) {
  const card = email._cards?.[view];
  if (card?.parentNode) card.remove();
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

  modalSubject.textContent = email.subject || '(No Subject)';
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
  email._aiLoaded = true;
  aiLoadingEl.classList.remove('hidden');
  aiResult.innerHTML = '';
  fetch(`/api/email/${email.id}/analyze`)
    .then(r => r.json())
    .then(d => {
      aiLoadingEl.classList.add('hidden');
      aiResult.innerHTML = d.error ? `<p>Error: ${escHtml(d.error)}</p>` : renderAiResult(d);
    })
    .catch(() => {
      aiLoadingEl.classList.add('hidden');
      aiResult.textContent = '(Analysis failed.)';
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
modalStarBtn.addEventListener('click', async () => {
  const email = state.currentEmail;
  if (!email) return;
  const newVal = !email.is_starred;
  await apiPost(`/api/email/${email.id}/star`, { starred: newVal });
  updateEmailStar(email, newVal);
});

modalArchiveBtn.addEventListener('click', async () => {
  const email = state.currentEmail;
  if (!email) return;
  const view = state.currentView;
  closeModal();
  if (view === 'trash') {
    await apiPost(`/api/email/${email.id}/restore`);
    removeCardFromView(email, 'trash');
    adjustStats('trash', email, -1);
    updateStatsDisplay('trash');
  } else if (view === 'all_mail') {
    await apiPost(`/api/email/${email.id}/unarchive`);
    removeCardFromView(email, 'all_mail');
    adjustStats('all_mail', email, -1);
    updateStatsDisplay('all_mail');
  } else {
    await apiPost(`/api/email/${email.id}/archive`);
    const isMoodle = email.sender?.toLowerCase().includes('moodle');
    removeCardFromView(email, 'inbox');
    removeCardFromView(email, 'moodle');
    adjustStats('inbox', email, -1);
    if (isMoodle) adjustStats('moodle', email, -1);
    updateStatsDisplay(view);
  }
});

modalTrashBtn.addEventListener('click', async () => {
  const email = state.currentEmail;
  if (!email) return;
  const view = state.currentView;
  closeModal();
  if (view === 'trash') {
    await apiPost(`/api/email/${email.id}/delete`);
    removeCardFromView(email, 'trash');
    adjustStats('trash', email, -1);
    updateStatsDisplay('trash');
  } else {
    await apiPost(`/api/email/${email.id}/trash`);
    for (const v of ['inbox', 'moodle', 'all_mail']) {
      removeCardFromView(email, v);
      adjustStats(v, email, -1);
    }
    updateStatsDisplay(view);
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

async function apiPost(url, body = null) {
  const opts = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  try { return await (await fetch(url, opts)).json(); }
  catch (err) { console.error('apiPost', url, err); }
}

function showError(msg) {
  const el = document.createElement('div');
  el.style.cssText = 'padding:20px;color:var(--danger);text-align:center';
  el.textContent = msg;
  viewListEls[state.currentView]?.appendChild(el);
}

// ─── CSS fix: email-list wrapper needs to not scroll itself ───────────────────
// The per-view children handle their own scroll.
emailListWrapper.style.overflow = 'hidden';
emailListWrapper.style.display  = 'flex';
emailListWrapper.style.flexDirection = 'column';
emailListWrapper.style.flex     = '1';

// ─── Boot ─────────────────────────────────────────────────────────────────────

(function init() {
  initTheme();
  fetch('/api/user')
    .then(r => r.json())
    .then(d => { $('user-email').textContent = d.email || ''; });
  switchView('inbox');
})();
