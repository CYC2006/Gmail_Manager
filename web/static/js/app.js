'use strict';

import { state, streamFlags, tpdState, VIEW_KEYS, viewBuffer, viewShown, viewBufferedIds, viewStats, sseHandles } from './state.js';
import { initTheme, updateStatsDisplay, VIEW_META, statsBar } from './ui.js';
import { viewListEls, syncLoadingBar, startSharedStream, loadTrash, refreshCurrentView, initStream } from './stream.js';
import { initActions } from './actions.js';
import { buildCard } from './email-card.js';
import { openModal, syncModalStar } from './modal.js';
import { loadCalendar } from './calendar.js';
import { switchSettingsTab, loadPreferenceTab, loadAccountTab, loadApiKeysTab, updateQuotaDots } from './settings.js';

// ─── Wire cross-module dependencies ──────────────────────────────────────────

initStream({ buildCard, onCardClick: openModal });
initActions({ syncModalStar });

// ─── View routing ─────────────────────────────────────────────────────────────

const EMAIL_VIEWS = new Set(['inbox', 'moodle', 'all_mail', 'trash']);

const $ = id => document.getElementById(id);

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

    for (const v of VIEW_KEYS) {
      viewListEls[v].style.display = v === view ? '' : 'none';
    }

    updateStatsDisplay(view);
    syncLoadingBar();

    if (view === 'trash') {
      if (!streamFlags.trashLoaded && !streamFlags.trashLoading) loadTrash();
    } else {
      if (!streamFlags.sharedLoaded && !streamFlags.sharedLoading) startSharedStream();
    }

  } else if (view === 'calendar') {
    $('view-calendar').classList.add('active');
    loadCalendar();
  } else if (view === 'settings') {
    $('view-settings').classList.add('active');
    const activeStab = document.querySelector('.stab.active')?.dataset?.stab;
    if (activeStab === 'preference') loadPreferenceTab();
    else if (activeStab === 'account')  loadAccountTab();
    else if (activeStab === 'api_keys') loadApiKeysTab();
  }
}

document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => switchView(btn.dataset.view));
});

$('refresh-btn').addEventListener('click', () => refreshCurrentView(state.currentView));

// ─── Stream retry / dismiss ───────────────────────────────────────────────────

$('stream-retry-btn').addEventListener('click', () => {
  streamFlags.autoRetried  = false;
  streamFlags.sharedLoaded = false;
  sseHandles.shared?.close();
  sseHandles.shared = null;
  for (const v of VIEW_KEYS.filter(v => v !== 'trash')) {
    viewListEls[v].innerHTML = '';
    viewStats[v] = { total: 0, unread: 0, starred: 0 };
    viewBuffer[v] = []; viewShown[v] = new Set(); viewBufferedIds[v] = new Set();
  }
  updateStatsDisplay(state.currentView);
  startSharedStream();
});
$('stream-error-dismiss').addEventListener('click', () => {
  $('stream-error-banner').hidden = true;
});

// ─── TPD status ───────────────────────────────────────────────────────────────

function loadTpdStatus() {
  fetch('/api/tpd-status')
    .then(r => r.json())
    .then(d => {
      tpdState.exhaustedKeys = new Set(d.exhausted_keys || []);
      tpdState.allExhausted  = !!d.all_exhausted;
      updateQuotaDots();
    })
    .catch(() => {});
}

// ─── Boot ─────────────────────────────────────────────────────────────────────

initTheme();
fetch('/api/user')
  .then(r => r.json())
  .then(d => {
    const raw = d.email || '';
    const local = raw.split('@')[0];
    $('user-email').textContent = local.charAt(0).toUpperCase() + local.slice(1);
  });
loadTpdStatus();
switchView('inbox');
