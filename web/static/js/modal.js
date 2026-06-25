'use strict';

import { state, bodyCache, getUiState } from './state.js';
import { apiPost } from './ui.js';
import { doMarkRead, doStar, doArchive, doTrash } from './actions.js';

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

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

// ─── Open / close ─────────────────────────────────────────────────────────────

export function openModal(email, view) {
  state.currentEmail = email;

  modalSubject.textContent = email.display_subject || email.subject || '(No Subject)';
  modalSender.textContent  = email.sender  || '';
  modalTime.textContent    = email.time    || '';
  modalGmailLink.href = `https://mail.google.com/mail/u/0/#all/${email.id}`;

  syncModalStar(email.is_starred);

  // Contextual archive / trash button icons
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
  modalBackdrop.classList.add('open');

  // Load body — check in-session cache first, then API
  bodyLoading.classList.remove('hidden');
  modalBodyText.textContent = '';

  if (bodyCache.has(email.id)) {
    bodyLoading.classList.add('hidden');
    modalBodyText.textContent = bodyCache.get(email.id);
    if (email.is_unread) { doMarkRead(email); apiPost(`/api/email/${email.id}/mark_read`); }
  } else {
    fetch(`/api/email/${email.id}/body`)
      .then(r => r.json())
      .then(d => {
        bodyLoading.classList.add('hidden');
        const body = d.body || '';
        modalBodyText.textContent = body;
        if (body) bodyCache.set(email.id, body);
        if (email.is_unread) { doMarkRead(email); apiPost(`/api/email/${email.id}/mark_read`); }
      })
      .catch(() => {
        bodyLoading.classList.add('hidden');
        modalBodyText.textContent = '(Failed to load email body.)';
      });
  }

  // Trigger AI prefetch in background
  import('./stream.js').then(({ prefetchAiAnalysis }) => prefetchAiAnalysis(email));
}

export function closeModal() {
  modalBackdrop.classList.remove('open');
  state.currentEmail = null;
}

export function syncModalStar(starred) {
  modalStarBtn.querySelector('.material-icons-round').textContent = starred ? 'star' : 'star_border';
  modalStarBtn.classList.toggle('star-active', starred);
}

// ─── Tab switching ────────────────────────────────────────────────────────────

export function switchModalTab(tab) {
  $('tab-raw').classList.toggle('active', tab === 'raw');
  $('tab-ai').classList.toggle('active', tab === 'ai');
  $('tab-raw-btn').classList.toggle('active', tab === 'raw');
  $('tab-ai-btn').classList.toggle('active', tab === 'ai');
  $('modal-glow-wrap').classList.toggle('ai-mode', tab === 'ai');
  if (tab === 'ai' && state.currentEmail) {
    loadAiAnalysis(state.currentEmail);
  }
}

// ─── AI analysis ─────────────────────────────────────────────────────────────

function loadAiAnalysis(email) {
  const ui = getUiState(email.id);

  if (ui.aiResult) {
    aiLoadingEl.classList.add('hidden');
    aiResult.innerHTML = renderAiResult(ui.aiResult);
    return;
  }
  if (ui.aiQueued) {
    aiLoadingEl.classList.remove('hidden');
    aiResult.innerHTML = '';
    return;
  }

  ui.aiQueued = true;
  aiLoadingEl.classList.remove('hidden');
  aiResult.innerHTML = '';

  const _showError = () => {
    ui.aiQueued = false;
    aiLoadingEl.classList.add('hidden');
    aiResult.innerHTML =
      '<p style="color:var(--text-muted)">Analysis unavailable.</p>' +
      '<button id="ai-retry-btn" style="margin-top:8px;padding:4px 12px;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--text-primary);cursor:pointer">Retry</button>';
    const retryBtn = document.getElementById('ai-retry-btn');
    if (retryBtn) retryBtn.addEventListener('click', () => {
      ui.aiLoaded = false;
      ui.aiQueued = false;
      loadAiAnalysis(email);
    });
  };

  fetch(`/api/email/${email.id}/analyze`)
    .then(r => r.json())
    .then(d => {
      if (d.error || d._failed) { _showError(); return; }
      ui.aiResult = d;
      ui.aiLoaded = true;
      aiLoadingEl.classList.add('hidden');
      aiResult.innerHTML = renderAiResult(d);
    })
    .catch(_showError);
}

export function renderAiResult(data) {
  if (!data || !Object.keys(data).length) return '<p style="color:var(--text-muted)">(No analysis available.)</p>';
  let html = '';

  if (data.summary) {
    html += `<h4>Summary</h4><p>${escHtml(data.summary)}</p>`;
  }
  if (data.action_required) {
    html += `<h4>Action Required</h4><p style="color:#f9a825">${escHtml(data.action_required)}</p>`;
  }
  if (data.event_times?.length) {
    html += '<h4>Key Dates</h4>';
    for (const ev of data.event_times) {
      html += `<p style="color:#ffb74d">${escHtml(ev.label || '')}: ${escHtml(ev.time || '')}</p>`;
    }
  }
  if (data.key_points?.length) {
    html += '<h4>Key Points</h4><ul style="margin:0 0 6px 1.2em;padding:0">';
    for (const pt of data.key_points) {
      html += `<li style="margin-bottom:4px">${escHtml(pt)}</li>`;
    }
    html += '</ul>';
  }
  if (data.urls?.length) {
    html += '<h4>Related Links</h4>';
    for (const u of data.urls) {
      // Only allow http/https URLs to prevent javascript: XSS (#1 on smell list)
      if (!/^https?:\/\//i.test(u.url || '')) continue;
      const label = escHtml(u.label || u.url || '');
      const href  = escHtml(u.url);
      html += `<p><a href="${href}" target="_blank" rel="noopener" style="color:var(--accent-blue,#1e88e5)">${label}</a></p>`;
    }
  }

  return html || '<p style="color:var(--text-muted)">(No analysis available.)</p>';
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ─── Modal action buttons ─────────────────────────────────────────────────────

modalStarBtn.addEventListener('click', () => {
  const email = state.currentEmail;
  if (!email) return;
  doStar(email, !email.is_starred);
  apiPost(`/api/email/${email.id}/star`, { starred: email.is_starred });
});

modalArchiveBtn.addEventListener('click', () => {
  const email = state.currentEmail;
  if (!email) return;
  const view = state.currentView;
  closeModal();
  doArchive(email, view);
});

modalTrashBtn.addEventListener('click', () => {
  const email = state.currentEmail;
  if (!email) return;
  const view = state.currentView;
  closeModal();
  doTrash(email, view);
});

$('modal-close-btn').addEventListener('click', closeModal);
modalBackdrop.addEventListener('click', e => { if (e.target === modalBackdrop) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
$('tab-raw-btn').addEventListener('click', () => switchModalTab('raw'));
$('tab-ai-btn').addEventListener('click',  () => switchModalTab('ai'));

// Register renderAiResult with stream.js so prefetchAiAnalysis can call it
// when the AI tab is open (avoids stream → modal import cycle).
import('./stream.js').then(({ setRenderAiResult }) => setRenderAiResult(renderAiResult));
