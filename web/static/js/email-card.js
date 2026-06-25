'use strict';

import { getUiState } from './state.js';
import { badgeEl, apiPost } from './ui.js';
import { doMarkRead, doStar, doArchive, doTrash } from './actions.js';

// ─── Card builder ─────────────────────────────────────────────────────────────
// onCardClick is injected by stream.js (which gets it from app.js),
// breaking the email-card ↔ modal circular dependency.

export function buildCard(email, view, onCardClick) {
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
  sender.className = 'card-sender' + (email.is_moodle ? ' moodle' : '');
  if (email.is_moodle) {
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
      doArchive(email, 'trash');
    }));
    actions.appendChild(cardBtn('delete_forever', 'Delete permanently', 'danger', () => {
      doTrash(email, 'trash');
    }));
  } else {
    actions.appendChild(cardBtn('mark_email_read', 'Mark as read', '', () => {
      if (!email.is_unread) return;
      doMarkRead(email);
      apiPost(`/api/email/${email.id}/mark_read`);
    }));

    const starBtnEl = cardBtn(
      email.is_starred ? 'star' : 'star_border',
      'Star',
      email.is_starred ? 'star-active' : '',
      () => {
        const newVal = !email.is_starred;
        doStar(email, newVal);
        apiPost(`/api/email/${email.id}/star`, { starred: newVal });
      }
    );
    getUiState(email.id).starBtns.push(starBtnEl);
    actions.appendChild(starBtnEl);

    if (view === 'all_mail') {
      actions.appendChild(cardBtn('move_to_inbox', 'Move to Inbox', 'success', () => {
        doArchive(email, 'all_mail');
      }));
    } else {
      actions.appendChild(cardBtn('archive', 'Archive', 'success', () => {
        doArchive(email, view);
      }));
    }

    actions.appendChild(cardBtn('delete', 'Delete', 'danger', () => {
      doTrash(email, view);
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
    onCardClick(email, view);
  });

  return card;
}

// ─── Card button factory ──────────────────────────────────────────────────────

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
