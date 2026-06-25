'use strict';

import { tpdState } from './state.js';

const $ = id => document.getElementById(id);

// ─── Tab switching ────────────────────────────────────────────────────────────

export function switchSettingsTab(tabName) {
  document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.stab-panel').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.stab[data-stab="${tabName}"]`);
  if (btn) btn.classList.add('active');
  const panel = $(`stab-${tabName}`);
  if (panel) panel.classList.add('active');
  if (tabName === 'preference') loadPreferenceTab();
  else if (tabName === 'account')  loadAccountTab();
  else if (tabName === 'api_keys') loadApiKeysTab();
}

document.querySelectorAll('.stab').forEach(btn => {
  btn.addEventListener('click', () => switchSettingsTab(btn.dataset.stab));
});

// ─── Preference tab ───────────────────────────────────────────────────────────

let _prefOptions  = null;
let _prefSelected = new Set();
let _prefLoaded   = false;

export async function loadPreferenceTab() {
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

    const labelCol = document.createElement('div');
    labelCol.className = 'pref-cat-label';
    labelCol.innerHTML = `
      <span class="material-icons-round pref-cat-icon">${(cat.icon || 'label').toLowerCase()}</span>
      <div class="pref-cat-text">
        <span class="pref-cat-name">${cat.label}</span>
        <span class="pref-cat-abbr">${cat.abbr}</span>
      </div>`;

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
  fetch('/api/settings/interests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interests: [..._prefSelected] }),
  });
}

// ─── Account tab ─────────────────────────────────────────────────────────────

let _accSaved   = {};
let _accCurrent = {};
let _accGender  = '';
let _accLoaded  = false;

export async function loadAccountTab() {
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

  $('acc-name').value  = profileRes.name  || '';
  $('acc-gmail').value = profileRes.gmail || '';

  renderGenderChips(_accGender);

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

$('acc-name').addEventListener('input', e => { _accCurrent.name = e.target.value; updateAccSaveBtn(); });
$('acc-gmail').addEventListener('input', e => { _accCurrent.gmail = e.target.value.trim(); updateAccSaveBtn(); });
$('acc-major').addEventListener('change', e => { _accCurrent.major = e.target.value; updateAccSaveBtn(); });

function updateAccSaveBtn() {
  const changed = _accCurrent.name   !== _accSaved.name   ||
                  _accCurrent.gender !== _accSaved.gender ||
                  _accCurrent.major  !== _accSaved.major  ||
                  _accCurrent.gmail  !== _accSaved.gmail;
  $('acc-save-btn').disabled = !changed;
}

$('acc-save-btn').addEventListener('click', async () => {
  await fetch('/api/settings/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(_accCurrent),
  });
  _accSaved = { ..._accCurrent };
  updateAccSaveBtn();
});

// ─── API Keys tab ─────────────────────────────────────────────────────────────

const API_KEY_MAX = 10;
let _apiLoaded = false;
let _dragSrc = null;

const _PROVIDERS = [
  { value: 'groq',   label: 'GROQ' },
  { value: 'nvidia', label: 'NVIDIA' },
  { value: 'kimi',   label: 'KIMI' },
];

export async function loadApiKeysTab() {
  if (_apiLoaded) return;
  _apiLoaded = true;

  const res = await fetch('/api/settings/api-keys').then(r => r.json());
  const entries = res.keys || [{ key: '', provider: 'groq' }];
  $('api-keys-list').innerHTML = '';
  for (const e of entries) {
    const key      = typeof e === 'string' ? e : (e.key || '');
    const provider = typeof e === 'string' ? 'groq' : (e.provider || 'groq');
    addApiKeyRow(key, provider, key ? 'verified' : 'unverified');
  }
  _updateAddBtn();
}

function _rowCount() {
  return $('api-keys-list').querySelectorAll('.api-key-row').length;
}

function _updateAddBtn() {
  $('api-add-btn').disabled = _rowCount() >= API_KEY_MAX;
}

function addApiKeyRow(key = '', provider = 'groq', status = 'unverified') {
  if (_rowCount() >= API_KEY_MAX) return;

  const row = document.createElement('div');
  row.className = 'api-key-row';
  row.draggable = true;

  // Drag handle
  const dragHandle = document.createElement('span');
  dragHandle.className = 'material-icons-round api-drag-handle';
  dragHandle.textContent = 'reorder';
  dragHandle.title = '拖曳排序';

  row.addEventListener('dragstart', e => {
    _dragSrc = row;
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => row.classList.add('dragging'), 0);
  });
  row.addEventListener('dragend', () => {
    _dragSrc = null;
    row.classList.remove('dragging');
    document.querySelectorAll('.api-key-row').forEach(r => r.classList.remove('drag-over'));
  });
  row.addEventListener('dragover', e => {
    e.preventDefault();
    if (_dragSrc && _dragSrc !== row) row.classList.add('drag-over');
  });
  row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
  row.addEventListener('drop', e => {
    e.preventDefault();
    row.classList.remove('drag-over');
    if (!_dragSrc || _dragSrc === row) return;
    const list = $('api-keys-list');
    const rows = [...list.querySelectorAll('.api-key-row')];
    const srcIdx = rows.indexOf(_dragSrc);
    const dstIdx = rows.indexOf(row);
    list.insertBefore(_dragSrc, srcIdx < dstIdx ? row.nextSibling : row);
    _updateApiSaveBtn();
  });

  // Battery / quota icon
  const quotaIcon = document.createElement('span');
  const prefix = key ? key.slice(0, 8) : '';
  quotaIcon.dataset.prefix = prefix;
  if (prefix) {
    const exhausted = tpdState.exhaustedKeys.has(prefix);
    quotaIcon.className = 'material-icons-round api-quota-icon ' + (exhausted ? 'exhausted' : 'ok');
    quotaIcon.textContent = exhausted ? 'battery_1_bar' : 'battery_full';
    quotaIcon.title = exhausted ? '今日額度已耗盡' : '可用';
  } else {
    quotaIcon.className = 'material-icons-round api-quota-icon empty';
    quotaIcon.textContent = 'help_outline';
    quotaIcon.title = '尚未輸入金鑰';
  }

  // Provider dropdown
  const sel = document.createElement('select');
  sel.className = 'api-provider-select';
  for (const p of _PROVIDERS) {
    const opt = document.createElement('option');
    opt.value = p.value;
    opt.textContent = p.label;
    if (p.value === provider) opt.selected = true;
    sel.appendChild(opt);
  }

  // Key input
  const field = document.createElement('input');
  field.className = 'api-key-field';
  field.type = 'password';
  field.placeholder = 'Paste your API key…';
  field.value = key;
  field.addEventListener('input', () => {
    const pfx = field.value.slice(0, 8);
    quotaIcon.dataset.prefix = pfx;
    if (pfx) {
      const exhausted = tpdState.exhaustedKeys.has(pfx);
      quotaIcon.className = 'material-icons-round api-quota-icon ' + (exhausted ? 'exhausted' : 'ok');
      quotaIcon.textContent = exhausted ? 'battery_1_bar' : 'battery_full';
      quotaIcon.title = exhausted ? '今日額度已耗盡' : '可用';
    } else {
      quotaIcon.className = 'material-icons-round api-quota-icon empty';
      quotaIcon.textContent = 'help_outline';
      quotaIcon.title = '尚未輸入金鑰';
    }
    _updateApiSaveBtn();
  });

  // Reveal toggle
  const revealBtn = document.createElement('button');
  revealBtn.className = 'api-key-reveal';
  revealBtn.title = 'Show/hide key';
  revealBtn.innerHTML = '<span class="material-icons-round">visibility</span>';
  revealBtn.addEventListener('click', () => {
    const showing = field.type === 'text';
    field.type = showing ? 'password' : 'text';
    revealBtn.querySelector('.material-icons-round').textContent =
      showing ? 'visibility' : 'visibility_off';
  });

  // Verify badge
  const badge = document.createElement('div');
  badge.className = 'api-badge';
  setApiBadge(badge, status);

  // Per-row delete button
  const delBtn = document.createElement('button');
  delBtn.className = 'api-row-del';
  delBtn.title = 'Remove key';
  delBtn.innerHTML = '<span class="material-icons-round">delete_outline</span>';
  delBtn.addEventListener('click', () => {
    row.remove();
    _updateAddBtn();
    _updateApiSaveBtn();
  });

  row.appendChild(dragHandle);
  row.appendChild(quotaIcon);
  row.appendChild(sel);
  row.appendChild(field);
  row.appendChild(revealBtn);
  row.appendChild(badge);
  row.appendChild(delBtn);
  $('api-keys-list').appendChild(row);

  _updateAddBtn();
  _updateApiSaveBtn();
}

function setApiBadge(badge, status) {
  badge.className = `api-badge ${status}`;
  const icons = { verified: 'check', invalid: 'close', checking: '', unverified: 'help_outline' };
  badge.innerHTML = icons[status]
    ? `<span class="material-icons-round">${icons[status]}</span>`
    : '<span class="material-icons-round spinning" style="font-size:18px;color:var(--text-muted)">sync</span>';
}

function _updateApiSaveBtn() {
  const anyFilled = [...$('api-keys-list').querySelectorAll('.api-key-field')]
    .some(f => f.value.trim());
  $('api-save-btn').disabled = !anyFilled;
}

$('api-add-btn').addEventListener('click', () => addApiKeyRow());

$('api-save-btn').addEventListener('click', async () => {
  const rows    = [...$('api-keys-list').querySelectorAll('.api-key-row')];
  const fields  = rows.map(r => r.querySelector('.api-key-field'));
  const selects = rows.map(r => r.querySelector('.api-provider-select'));
  const badges  = rows.map(r => r.querySelector('.api-badge'));

  const entries = rows
    .map((_, i) => ({ key: fields[i].value.trim(), provider: selects[i].value }))
    .filter(e => e.key);

  if (!entries.length) return;

  rows.forEach((_, i) => { if (fields[i].value.trim()) setApiBadge(badges[i], 'checking'); });
  $('api-save-btn').disabled = true;

  const res = await fetch('/api/settings/api-keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keys: entries }),
  }).then(r => r.json());

  if (res.results) {
    let ri = 0;
    rows.forEach((_, i) => {
      if (fields[i].value.trim()) {
        setApiBadge(badges[i], res.results[ri]?.status || 'unverified');
        ri++;
      }
    });
  }
  $('api-save-btn').disabled = false;
});

export function updateQuotaDots() {
  document.querySelectorAll('.api-quota-icon').forEach(el => {
    const prefix = el.dataset.prefix || '';
    if (!prefix) {
      el.className = 'material-icons-round api-quota-icon empty';
      el.textContent = 'help_outline';
      el.title = '尚未輸入金鑰';
      return;
    }
    const exhausted = tpdState.exhaustedKeys.has(prefix);
    el.textContent = exhausted ? 'battery_1_bar' : 'battery_full';
    el.className = 'material-icons-round api-quota-icon ' + (exhausted ? 'exhausted' : 'ok');
    el.title = exhausted ? '今日額度已耗盡' : '可用';
  });
}
