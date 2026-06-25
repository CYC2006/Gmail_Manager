'use strict';

import { state, viewStats, getUiState } from './state.js';
import { removeCardFromView, adjustStats } from './stream.js';
import { updateStatsDisplay, apiPost } from './ui.js';

// ─── Injected dep: syncModalStar (from modal.js, set by app.js to avoid circular) ──

let _syncModalStar = null;
export function initActions({ syncModalStar }) { _syncModalStar = syncModalStar; }

// ─── Mark as read ─────────────────────────────────────────────────────────────

export function doMarkRead(email) {
  if (!email.is_unread) return;
  email.is_unread = false;
  for (const v of ['inbox', 'moodle', 'all_mail']) {
    const card = getUiState(email.id).cards?.[v];
    if (card) card.classList.remove('unread');
    viewStats[v].unread = Math.max(0, (viewStats[v].unread || 0) - 1);
  }
  if (state.currentView !== 'trash') updateStatsDisplay(state.currentView);
}

// ─── Star ─────────────────────────────────────────────────────────────────────

export function doStar(email, newVal) {
  email.is_starred = newVal;
  for (const btn of getUiState(email.id).starBtns || []) {
    btn.querySelector('.material-icons-round').textContent = newVal ? 'star' : 'star_border';
    btn.classList.toggle('star-active', newVal);
  }
  if (_syncModalStar && state.currentEmail?.id === email.id) _syncModalStar(newVal);
  const delta = newVal ? 1 : -1;
  for (const v of ['inbox', 'moodle', 'all_mail']) {
    if (getUiState(email.id).cards?.[v]) {
      viewStats[v].starred = Math.max(0, (viewStats[v].starred || 0) + delta);
    }
  }
  if (state.currentView !== 'trash') updateStatsDisplay(state.currentView);
}

// ─── Archive (context-aware: archive / restore / unarchive) ──────────────────
// Replaces the duplicated 3-way conditional in buildCard + modal listeners.

export function doArchive(email, view) {
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
    removeCardFromView(email, 'inbox');
    removeCardFromView(email, 'moodle');
    adjustStats('inbox', email, -1);
    if (email.is_moodle) adjustStats('moodle', email, -1);
    updateStatsDisplay(view);
    apiPost(`/api/email/${email.id}/archive`);
  }
}

// ─── Trash (context-aware: move-to-trash / permanent delete) ─────────────────

export function doTrash(email, view) {
  if (view === 'trash') {
    removeCardFromView(email, 'trash');
    adjustStats('trash', email, -1);
    updateStatsDisplay('trash');
    apiPost(`/api/email/${email.id}/delete`);
  } else {
    for (const v of ['inbox', 'moodle', 'all_mail']) {
      adjustStats(v, email, -1);
      removeCardFromView(email, v);
    }
    updateStatsDisplay(view);
    apiPost(`/api/email/${email.id}/trash`);
  }
}
