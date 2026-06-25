'use strict';

import { state, viewStats } from './state.js';

// ─── DOM shortcuts ────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

export const loadingBar = $('loading-bar');
export const statsBar   = $('stats-bar');
export const sidebar    = document.getElementById('sidebar');

// ─── Theme ───────────────────────────────────────────────────────────────────

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');
let _currentThemeSetting = 'dark';

function resolveTheme(theme) {
  if (theme === 'system') return systemDark.matches ? 'dark' : 'light';
  return theme;
}

export function applyTheme(theme) {
  _currentThemeSetting = theme;
  document.documentElement.setAttribute('data-theme', resolveTheme(theme));
  document.querySelectorAll('input[name="theme"]').forEach(r => {
    r.checked = r.value === theme;
  });
}

export function initTheme() {
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

// ─── Loading bar ──────────────────────────────────────────────────────────────

export function startLoading() { loadingBar.classList.add('active'); }
export function stopLoading()  { loadingBar.classList.remove('active'); }

// ─── Stats display ────────────────────────────────────────────────────────────

export function updateStatsDisplay(view) {
  const s = viewStats[view] || { total: 0, unread: 0, starred: 0 };
  $('stat-total-val').textContent   = s.total;
  $('stat-unread-val').textContent  = s.unread;
  $('stat-starred-val').textContent = s.starred;
}

// ─── Stream error banner ──────────────────────────────────────────────────────

const streamErrorBanner = $('stream-error-banner');
const streamErrorMsg    = $('stream-error-msg');

export function showStreamError(msg, showRetry = true) {
  streamErrorMsg.textContent = msg;
  $('stream-retry-btn').hidden = !showRetry;
  streamErrorBanner.hidden = false;
}
export function hideStreamError() { streamErrorBanner.hidden = true; }

// ─── Toast ────────────────────────────────────────────────────────────────────

let _toastTimer = null;

export function showToast(msg, durationMs = 3500) {
  const el = $('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.hidden = true; }, durationMs);
}

// ─── apiPost helper ───────────────────────────────────────────────────────────

export async function apiPost(url, body = null) {
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

// ─── Category badge ───────────────────────────────────────────────────────────

export function badgeEl(category) {
  if (!category) return document.createDocumentFragment();
  const span = document.createElement('span');
  span.className = `cat-badge badge-${category}`;
  span.textContent = category;
  return span;
}

// ─── View META (used by switchView in app.js) ─────────────────────────────────

export const VIEW_META = {
  inbox:    { icon: 'inbox',         title: 'Inbox',     statsTotal: true  },
  moodle:   { icon: 'school',        title: 'Moodle',    statsTotal: false },
  all_mail: { icon: 'all_inbox',     title: 'All Mails', statsTotal: false },
  trash:    { icon: 'delete',        title: 'Trash',     statsTotal: false },
  calendar: { icon: 'calendar_month', title: 'Calendar' },
  settings: { icon: 'settings',      title: 'Settings'  },
};
