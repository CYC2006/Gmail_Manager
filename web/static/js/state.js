'use strict';

export const PAGE_SIZE = 50;
export const VIEW_KEYS = ['inbox', 'moodle', 'all_mail', 'trash'];

// ─── App state ────────────────────────────────────────────────────────────────

export const state = {
  currentView:  'inbox',
  currentEmail: null,
  calEvents:    [],
  calYear:      new Date().getFullYear(),
  calMonth:     new Date().getMonth(),
};

// ─── Per-view email containers ────────────────────────────────────────────────

export const viewBuffer      = {};
export const viewShown       = {};
export const viewBufferedIds = {};
export const viewStats       = {};

for (const v of VIEW_KEYS) {
  viewBuffer[v]      = [];
  viewShown[v]       = new Set();
  viewBufferedIds[v] = new Set();
  viewStats[v]       = { total: 0, unread: 0, starred: 0 };
}

// ─── Caches ───────────────────────────────────────────────────────────────────

export const bodyCache = new Map();   // email id → body string

// ─── #7: UI state separated from email data ───────────────────────────────────
// Replaces monkey-patching email._cards, email._starBtns, email._aiResult, etc.
// email objects from SSE remain pure data; DOM refs and async flags live here.

export const emailUiState = new Map();

export function getUiState(id) {
  if (!emailUiState.has(id)) emailUiState.set(id, { starBtns: [], cards: {} });
  return emailUiState.get(id);
}

// ─── SSE handles ──────────────────────────────────────────────────────────────
// Wrapped in objects so all modules share the same mutable reference.

export const sseHandles = { shared: null, trash: null };

export const streamFlags = {
  sharedLoaded:  false,
  sharedLoading: false,
  trashLoaded:   false,
  trashLoading:  false,
  autoRetried:   false,
};

// ─── TPD state ────────────────────────────────────────────────────────────────

export const tpdState = {
  exhaustedKeys: new Set(),
  allExhausted:  false,
};
