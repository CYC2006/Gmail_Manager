'use strict';

import { state } from './state.js';
import { openModal } from './modal.js';
import { showToast } from './ui.js';

const $ = id => document.getElementById(id);

// ─── Constants ────────────────────────────────────────────────────────────────

const CAL_COLORS = [
  { id: 'blue',   dot: '#1e88e5' },
  { id: 'teal',   dot: '#00897b' },
  { id: 'green',  dot: '#43a047' },
  { id: 'amber',  dot: '#f9a825' },
  { id: 'red',    dot: '#e53935' },
  { id: 'purple', dot: '#8e24aa' },
  { id: 'grey',   dot: '#757575' },
];

const CAL_MONTH_NAMES = ['January','February','March','April','May','June',
                         'July','August','September','October','November','December'];
const CAL_MONTHS_BEFORE = 6;
const CAL_MONTHS_AFTER  = 12;

// ─── Calendar render ──────────────────────────────────────────────────────────

export function loadCalendar() {
  fetch('/api/calendar/events')
    .then(r => r.json())
    .then(events => { state.calEvents = events; renderCalendar(); })
    .catch(console.error);
}

function renderCalendar() {
  const grid = $('cal-grid');
  grid.innerHTML = '';

  const today = new Date();
  const { calYear, calMonth } = state;

  const byDate = {};
  for (const ev of state.calEvents) {
    const dk = (ev.event_time || '').substring(0, 10);
    if (!byDate[dk]) byDate[dk] = [];
    byDate[dk].push(ev);
  }

  for (let offset = -CAL_MONTHS_BEFORE; offset <= CAL_MONTHS_AFTER; offset++) {
    let m = calMonth + offset;
    let y = calYear;
    while (m < 0)  { m += 12; y--; }
    while (m > 11) { m -= 12; y++; }
    grid.appendChild(renderMonthSection(y, m, byDate, today));
  }

  const todaySection = grid.querySelector(
    `.cal-month-section[data-year="${today.getFullYear()}"][data-month="${today.getMonth()}"]`
  );
  if (todaySection) todaySection.scrollIntoView({ behavior: 'instant', block: 'start' });

  updateCalMonthLabel();
}

function renderMonthSection(year, month, byDate, today) {
  const section = document.createElement('div');
  section.className = 'cal-month-section';
  section.dataset.year  = year;
  section.dataset.month = month;

  const heading = document.createElement('div');
  heading.className = 'cal-month-heading';
  heading.textContent = `${CAL_MONTH_NAMES[month]} ${year}`;
  section.appendChild(heading);

  const mgrid = document.createElement('div');
  mgrid.className = 'cal-month-grid';

  const firstDay    = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const prevDays    = new Date(year, month, 0).getDate();

  for (let i = 0; i < firstDay; i++) {
    mgrid.appendChild(calCell(year, month - 1, prevDays - firstDay + 1 + i, byDate, true));
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = d === today.getDate() && month === today.getMonth() && year === today.getFullYear();
    mgrid.appendChild(calCell(year, month, d, byDate, false, isToday));
  }
  const trailing = (firstDay + daysInMonth) % 7;
  for (let d = 1; d <= (trailing ? 7 - trailing : 0); d++) {
    mgrid.appendChild(calCell(year, month + 1, d, byDate, true));
  }

  for (let i = 0; i < 7; i++) {
    const blank = document.createElement('div');
    blank.className = 'cal-blank-cell';
    mgrid.appendChild(blank);
  }

  section.appendChild(mgrid);
  return section;
}

function updateCalMonthLabel() {
  const grid = $('cal-grid');
  if (!grid) return;
  const gridTop = grid.getBoundingClientRect().top;
  const sections = grid.querySelectorAll('.cal-month-section');
  let current = sections[0];
  for (const s of sections) {
    if (s.getBoundingClientRect().top <= gridTop + 40) current = s;
  }
  if (current) {
    $('cal-month-label').textContent =
      `${CAL_MONTH_NAMES[+current.dataset.month]} ${current.dataset.year}`;
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

  const CATEGORY_COLORS = { '考試時間': '#e53935', '作業死線': '#f57c00' };
  if (!otherMonth) for (const ev of (byDate[dk] || []).slice(0, 2)) {
    const dotColor = CATEGORY_COLORS[ev.category]
      ?? CAL_COLORS.find(c => c.id === ev.color)?.dot
      ?? '#757575';
    const chip = document.createElement('div');
    chip.className = 'cal-event-chip';
    chip.style.background = dotColor;
    chip.title = ev.label;
    if (ev.email_id && !ev.email_id.startsWith('custom_')) {
      chip.style.cursor = 'pointer';
      chip.addEventListener('click', async () => {
        const res = await fetch(`/api/email/${ev.email_id}/meta`);
        if (!res.ok) { showToast('The source email no longer exists.'); return; }
        openModal(await res.json(), 'calendar');
      });
    }

    const titleEl = document.createElement('span');
    titleEl.className = 'cal-chip-title';
    titleEl.textContent = ev.label || ev.event_time;
    chip.appendChild(titleEl);

    const timePart = (ev.event_time || '').substring(11);
    if (timePart) {
      const timeEl = document.createElement('span');
      timeEl.className = 'cal-chip-time';
      timeEl.textContent = ev.end_time ? `${timePart} - ${ev.end_time}` : timePart;
      chip.appendChild(timeEl);
    }

    cell.appendChild(chip);
  }
  if (!otherMonth && (byDate[dk] || []).length > 2) {
    const more = document.createElement('div');
    more.style.cssText = 'font-size:.65rem;color:var(--text-muted);padding:1px 5px';
    more.textContent = `+${byDate[dk].length - 2} more`;
    cell.appendChild(more);
  }

  const addBtn = document.createElement('button');
  addBtn.className = 'cal-add-btn';
  addBtn.textContent = '+ New event';
  addBtn.addEventListener('click', e => { e.stopPropagation(); openCeModal(dk); });
  cell.appendChild(addBtn);

  return cell;
}

$('cal-today').addEventListener('click', () => {
  state.calYear  = new Date().getFullYear();
  state.calMonth = new Date().getMonth();
  renderCalendar();
});

$('cal-grid').addEventListener('scroll', updateCalMonthLabel, { passive: true });

// ─── Create event modal ───────────────────────────────────────────────────────

let selectedCeColor = CAL_COLORS[0].id;
let ceIsAllDay = false;
let ceDateKey  = '';

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
  setCeAllDay(false);
  $('ce-start-h').value = '09'; $('ce-end-h').value = '10';
  $('ce-start-m').value = '00'; $('ce-end-m').value = '00';
  selectedCeColor = CAL_COLORS[0].id;
  document.querySelectorAll('.ce-color-dot').forEach((dot, i) => {
    dot.classList.toggle('selected', i === 0);
  });
  $('ce-backdrop').classList.add('open');
}

function closeCeModal() { $('ce-backdrop').classList.remove('open'); }

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
