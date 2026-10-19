const tbody = document.getElementById('profile-tbody');
const emptyState = document.getElementById('empty-state');
const tableWrap = document.querySelector('.profile-table');
const countLabel = document.getElementById('profile-count');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const genCountInput = document.getElementById('gen-count');
const searchInput = document.getElementById('search-input');

let allProfiles = [];
let allGroups = [];
let activeGroupFilter = null;  // null = "All Profiles"
let selectedFiles = new Set();

function setStatus(text, mode) {
  statusText.textContent = text;
  statusDot.className = 'status-dot' + (mode ? ' ' + mode : '');
}

// Deterministic colour from canvas_seed, same one launcher.py uses for the
// favicon — keeps the row tag colour consistent with the actual launched window.
function seedToColor(seed) {
  let h = (Math.abs(seed || 1) * 2654435761) & 0xFFFFFF;
  const r = 90 + (h & 0x3F);
  const g = 90 + ((h >> 6) & 0x3F);
  const b = 90 + ((h >> 12) & 0x3F);
  return `rgb(${r},${g},${b})`;
}

function currentlyVisibleProfiles() {
  const q = searchInput.value.trim().toLowerCase();
  return allProfiles.filter(p => {
    if (activeGroupFilter !== null && p.group !== activeGroupFilter) return false;
    if (q && !p.id.toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderRows(profiles) {
  tbody.innerHTML = '';
  if (profiles.length === 0) {
    tableWrap.hidden = true;
    emptyState.hidden = false;
    return;
  }
  tableWrap.hidden = false;
  emptyState.hidden = true;

  profiles.forEach((p, i) => {
    const tr = document.createElement('tr');
    const groupHtml = p.group ? ` · <span class="group-tag">${p.group}</span>` : '';
    tr.innerHTML = `
      <td class="col-checkbox"><input type="checkbox" data-file="${p.file}" ${selectedFiles.has(p.file) ? 'checked' : ''} /></td>
      <td class="col-tag"><span class="row-tag" style="background:${seedToColor(p.canvas_seed)}">${p.number || (i + 1)}</span></td>
      <td>
        <button class="cell-title cell-title-btn" data-rename="${p.file}" title="Click to rename">${p.id} ✎</button>
        <div class="cell-sub">${p.os}${groupHtml}</div>
      </td>
      <td class="cell-detail">${p.gpu || 'GPU unknown'}</td>
      <td class="cell-detail">${p.locale} · ${p.timezone}</td>
      <td>
        <button class="badge ${p.proxy_configured ? 'badge-ok' : 'badge-warn'}" data-edit-proxy="${p.file}">
          ${p.proxy_configured ? 'Configured' : 'No proxy'}
        </button>
      </td>
      <td>
        <div class="row-actions">
          ${p.is_open
            ? `<button class="btn btn-danger btn-small" data-close="${p.file}">Close</button>`
            : `<button class="btn btn-primary btn-small" data-launch="${p.file}">Launch</button>`}
          <button class="btn btn-ghost btn-small" data-check="${p.file}">Check</button>
          <button class="btn btn-ghost btn-small" data-edit-fp="${p.file}" title="Edit fingerprint">⚙</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function applyFilters() {
  renderRows(currentlyVisibleProfiles());
}

async function loadProfiles() {
  setStatus('Loading profiles…', 'busy');
  allProfiles = await window.pywebview.api.list_profiles();
  countLabel.textContent = `${allProfiles.length} profile${allProfiles.length === 1 ? '' : 's'}`;
  applyFilters();
  setStatus('Ready.', '');
}

searchInput.addEventListener('input', applyFilters);

// --- Groups ---
const groupFilterAll = document.getElementById('group-filter-all');
const groupsList = document.getElementById('groups-list');
const bulkActionsBar = document.getElementById('bulk-actions-bar');
const bulkSelectedCount = document.getElementById('bulk-selected-count');
const bulkGroupSelect = document.getElementById('bulk-group-select');
const bulkNewGroupInput = document.getElementById('bulk-new-group-input');
const selectAllCheckbox = document.getElementById('select-all');

async function loadGroups() {
  allGroups = await window.pywebview.api.list_groups();

  groupsList.innerHTML = '';
  allGroups.forEach(g => {
    const row = document.createElement('div');
    row.className = 'group-nav-row';
    row.innerHTML = `
      <a class="nav-item ${activeGroupFilter === g.name ? 'active' : ''}" data-group="${g.name}" href="#">
        ${g.name} <span class="group-count">${g.count}</span>
      </a>
      <button class="group-delete-btn" data-delete-group="${g.name}" title="Delete group (profiles stay, just ungrouped)">×</button>
    `;
    groupsList.appendChild(row);
  });

  // Keep the bulk-assign dropdown's existing-group options in sync too.
  const currentValue = bulkGroupSelect.value;
  bulkGroupSelect.innerHTML = '<option value="">Add to group…</option>' +
    allGroups.map(g => `<option value="${g.name}">${g.name} (${g.count})</option>`).join('') +
    '<option value="__new__">+ New group…</option>';
  if ([...bulkGroupSelect.options].some(o => o.value === currentValue)) {
    bulkGroupSelect.value = currentValue;
  }
}

groupFilterAll.addEventListener('click', (e) => {
  e.preventDefault();
  activeGroupFilter = null;
  groupFilterAll.classList.add('active');
  groupsList.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  applyFilters();
});

groupsList.addEventListener('click', async (e) => {
  const groupLink = e.target.closest('[data-group]');
  if (groupLink) {
    e.preventDefault();
    activeGroupFilter = groupLink.getAttribute('data-group');
    groupFilterAll.classList.remove('active');
    groupsList.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    groupLink.classList.add('active');
    applyFilters();
    return;
  }

  const deleteGroupName = e.target.getAttribute('data-delete-group');
  if (deleteGroupName) {
    if (!confirm(`Delete group "${deleteGroupName}"? Profiles stay — this only removes the grouping.`)) return;
    setStatus(`Deleting group "${deleteGroupName}"…`, 'busy');
    const result = await window.pywebview.api.delete_group(deleteGroupName);
    setStatus(result.message, result.ok ? 'ok' : 'bad');
    if (activeGroupFilter === deleteGroupName) activeGroupFilter = null;
    await loadProfiles();
    await loadGroups();
  }
});

// --- Row selection (checkboxes) ---
function updateBulkBar() {
  const count = selectedFiles.size;
  bulkActionsBar.hidden = count === 0;
  bulkSelectedCount.textContent = `${count} selected`;
  selectAllCheckbox.checked = count > 0 && currentlyVisibleProfiles().every(p => selectedFiles.has(p.file));
}

tbody.addEventListener('change', (e) => {
  const file = e.target.getAttribute('data-file');
  if (!file) return;
  if (e.target.checked) selectedFiles.add(file);
  else selectedFiles.delete(file);
  updateBulkBar();
});

selectAllCheckbox.addEventListener('change', () => {
  const visible = currentlyVisibleProfiles();
  if (selectAllCheckbox.checked) {
    visible.forEach(p => selectedFiles.add(p.file));
  } else {
    visible.forEach(p => selectedFiles.delete(p.file));
  }
  applyFilters();
  updateBulkBar();
});

bulkGroupSelect.addEventListener('change', () => {
  bulkNewGroupInput.hidden = bulkGroupSelect.value !== '__new__';
  if (!bulkNewGroupInput.hidden) bulkNewGroupInput.focus();
});

document.getElementById('btn-bulk-add-to-group').addEventListener('click', async () => {
  const groupName = bulkGroupSelect.value === '__new__' ? bulkNewGroupInput.value.trim() : bulkGroupSelect.value;
  if (!groupName) {
    setStatus('Pick or type a group name first.', 'bad');
    return;
  }
  setStatus(`Adding ${selectedFiles.size} profile(s) to "${groupName}"…`, 'busy');
  const result = await window.pywebview.api.assign_group([...selectedFiles], groupName);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  selectedFiles.clear();
  bulkGroupSelect.value = '';
  bulkNewGroupInput.value = '';
  bulkNewGroupInput.hidden = true;
  await loadProfiles();
  await loadGroups();
  updateBulkBar();
});

document.getElementById('btn-bulk-remove-from-group').addEventListener('click', async () => {
  setStatus(`Removing ${selectedFiles.size} profile(s) from their group…`, 'busy');
  const result = await window.pywebview.api.assign_group([...selectedFiles], '');
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  selectedFiles.clear();
  await loadProfiles();
  await loadGroups();
  updateBulkBar();
});

document.getElementById('btn-bulk-clear').addEventListener('click', () => {
  selectedFiles.clear();
  applyFilters();
  updateBulkBar();
});

tbody.addEventListener('click', async (e) => {
  const editFile = e.target.getAttribute('data-edit-proxy');
  if (editFile) {
    openProxyModal(editFile);
    return;
  }

  const renameFile = e.target.getAttribute('data-rename');
  if (renameFile) {
    openRenameModal(renameFile);
    return;
  }

  const fpFile = e.target.getAttribute('data-edit-fp');
  if (fpFile) {
    openFingerprintModal(fpFile);
    return;
  }

  const closeFile = e.target.getAttribute('data-close');
  if (closeFile) {
    e.target.disabled = true;
    setStatus('Closing…', 'busy');
    const res = await window.pywebview.api.close_profiles([closeFile]);
    setStatus(res.message, res.ok ? 'ok' : 'bad');
    await refreshOpenState();
    return;
  }

  const launchFile = e.target.getAttribute('data-launch');
  const checkFile = e.target.getAttribute('data-check');
  const file = launchFile || checkFile;
  if (!file) return;

  setStatus(`Launching ${file}…`, 'busy');
  const result = await window.pywebview.api.launch_profile(file, Boolean(checkFile));
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  refreshOpenState();
});

// --- Open / close from the main screen ---
let lastOpenKey = '';

async function refreshOpenState() {
  let files;
  try {
    files = await window.pywebview.api.open_files();
  } catch (e) {
    return;
  }
  const openSet = new Set(files);
  const key = [...openSet].sort().join('|');
  document.getElementById('open-count').textContent = openSet.size ? `${openSet.size} open` : '';
  if (key === lastOpenKey) return;
  lastOpenKey = key;
  allProfiles.forEach(p => { p.is_open = openSet.has(p.file); });
  applyFilters();
}
setInterval(refreshOpenState, 2500);

async function openByNumbers() {
  const input = document.getElementById('open-by-no');
  const text = input.value.trim();
  if (!text) {
    setStatus('Type the NO. of the profile(s) to open, like 14 or 3-8.', 'bad');
    return;
  }
  setStatus('Opening…', 'busy');
  const res = await window.pywebview.api.open_profiles(text);
  setStatus(res.message, res.ok ? 'ok' : 'bad');
  if (res.ok) input.value = '';
  refreshOpenState();
}
document.getElementById('btn-open-by-no').addEventListener('click', openByNumbers);
document.getElementById('open-by-no').addEventListener('keydown', (e) => { if (e.key === 'Enter') openByNumbers(); });

document.getElementById('btn-close-all').addEventListener('click', async () => {
  setStatus('Closing everything…', 'busy');
  const res = await window.pywebview.api.close_all_profiles();
  setStatus(res.message, res.ok ? 'ok' : 'bad');
  refreshOpenState();
});

document.getElementById('btn-bulk-open').addEventListener('click', async () => {
  if (!selectedFiles.size) return;
  const nums = allProfiles.filter(p => selectedFiles.has(p.file)).map(p => p.number).join(',');
  setStatus('Opening…', 'busy');
  const res = await window.pywebview.api.open_profiles(nums);
  setStatus(res.message, res.ok ? 'ok' : 'bad');
  refreshOpenState();
});

document.getElementById('btn-bulk-close').addEventListener('click', async () => {
  if (!selectedFiles.size) return;
  setStatus('Closing…', 'busy');
  const res = await window.pywebview.api.close_profiles([...selectedFiles]);
  setStatus(res.message, res.ok ? 'ok' : 'bad');
  refreshOpenState();
});

// --- Timed plan ---
const planModal = document.getElementById('plan-modal');
const planRows = document.getElementById('plan-rows');
const planStatus = document.getElementById('plan-status');
let planTimer = null;

const PLAN_KEYS = ['Down arrow', 'Up arrow', 'Page Down', 'Page Up', 'Space', 'Home', 'End',
  'Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Left arrow', 'Right arrow'];

function addActionLine(box, vals = {}) {
  const line = document.createElement('div');
  line.className = 'act-line';
  const keyOpts = PLAN_KEYS.map(k => `<option>${k}</option>`).join('');
  line.innerHTML = `
    <span>At</span>
    <input type="number" data-a="at" min="0" placeholder="10" class="act-sec" />
    <span>seconds</span>
    <select data-a="type"><option value="key">press a key</option><option value="text">type text</option></select>
    <select data-a="key">${keyOpts}</select>
    <input type="number" data-a="repeat" min="1" max="50" value="1" class="act-rep" title="How many times" />
    <span data-a="times" title="times">times</span>
    <input type="text" data-a="text" maxlength="300" placeholder="text to type" class="act-text" />
    <button class="plan-x" title="Remove this action">&times;</button>`;
  const sync = () => {
    const isKey = line.querySelector('[data-a=type]').value === 'key';
    line.querySelector('[data-a=key]').hidden = !isKey;
    line.querySelector('[data-a=repeat]').hidden = !isKey;
    line.querySelector('[data-a=times]').hidden = !isKey;
    line.querySelector('[data-a=text]').hidden = isKey;
  };
  line.querySelector('[data-a=at]').value = vals.at ?? '';
  line.querySelector('[data-a=type]').value = vals.type || 'key';
  if (vals.type === 'key' && vals.value) line.querySelector('[data-a=key]').value = vals.value;
  line.querySelector('[data-a=repeat]').value = vals.repeat || 1;
  if (vals.type === 'text') line.querySelector('[data-a=text]').value = vals.value || '';
  line.querySelector('[data-a=type]').addEventListener('change', sync);
  line.querySelector('.plan-x').addEventListener('click', () => { line.remove(); refreshActCount(box); savePlan(); });
  sync();
  box.querySelector('.act-list').appendChild(line);
  refreshActCount(box);
}

function readActions(box) {
  return [...box.querySelectorAll('.act-line')].map(l => {
    const type = l.querySelector('[data-a=type]').value;
    return {
      at: l.querySelector('[data-a=at]').value.trim(),
      type,
      value: type === 'key' ? l.querySelector('[data-a=key]').value : l.querySelector('[data-a=text]').value,
      repeat: type === 'key' ? l.querySelector('[data-a=repeat]').value : 1,
    };
  });
}

function refreshActCount(box) {
  const n = box.querySelectorAll('.act-line').length;
  const btn = box._btn;
  btn.textContent = n ? `Actions (${n})` : 'Actions';
}

function addPlanRow(vals = {}) {
  const tr = document.createElement('tr');
  tr.className = 'step-row';
  tr.innerHTML = `
    <td><input type="text" data-f="no" placeholder="e.g. 14" /></td>
    <td><input type="text" data-f="url" placeholder="e.g. example.com" /></td>
    <td><input type="number" data-f="seconds" min="5" placeholder="30" /></td>
    <td><input type="checkbox" data-f="scroll" title="Scroll the page down during this time" /></td>
    <td><button class="btn btn-ghost btn-small act-btn" title="Press keys or type text at set seconds">Actions</button></td>
    <td><button class="plan-x" title="Remove this step">&times;</button></td>`;
  tr.querySelector('[data-f=no]').value = vals.no || '';
  tr.querySelector('[data-f=url]').value = vals.url || '';
  tr.querySelector('[data-f=seconds]').value = vals.seconds || '';
  tr.querySelector('[data-f=scroll]').checked = Boolean(vals.scroll);

  const sub = document.createElement('tr');
  sub.className = 'act-row';
  sub.hidden = true;
  sub.innerHTML = `<td colspan="6"><div class="act-box">
      <div class="act-help">Happens automatically while this page is open. Seconds count from when the page finished loading.</div>
      <div class="act-list"></div>
      <button class="btn btn-ghost btn-small act-add">+ Add action</button></div></td>`;
  const box = sub.querySelector('.act-box');
  box._btn = tr.querySelector('.act-btn');
  (vals.actions || []).forEach(a => addActionLine(box, a));
  sub.hidden = !(vals.actions && vals.actions.length);

  tr.querySelector('.act-btn').addEventListener('click', () => { sub.hidden = !sub.hidden; });
  sub.querySelector('.act-add').addEventListener('click', () => { addActionLine(box, { at: '', type: 'key' }); savePlan(); });
  tr.querySelector('.plan-x').addEventListener('click', () => { tr.remove(); sub.remove(); savePlan(); });
  sub.addEventListener('input', savePlan);
  sub.addEventListener('change', savePlan);
  tr.addEventListener('input', savePlan);
  planRows.appendChild(tr);
  planRows.appendChild(sub);
  refreshActCount(box);
}

function readPlanRows() {
  return [...planRows.querySelectorAll('tr.step-row')].map(tr => ({
    no: tr.querySelector('[data-f=no]').value.trim(),
    url: tr.querySelector('[data-f=url]').value.trim(),
    seconds: tr.querySelector('[data-f=seconds]').value.trim(),
    scroll: tr.querySelector('[data-f=scroll]').checked,
    actions: readActions(tr.nextElementSibling.querySelector('.act-box')),
  }));
}

function planMode() {
  return document.querySelector('input[name=plan-mode]:checked').value;
}

function savePlan() {
  try { localStorage.setItem('planSteps', JSON.stringify({ rows: readPlanRows(), mode: planMode() })); } catch (e) {}
}

function loadPlan() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem('planSteps') || 'null'); } catch (e) {}
  planRows.innerHTML = '';
  const rows = saved && saved.rows && saved.rows.length ? saved.rows : [{}, {}];
  rows.forEach(addPlanRow);
  if (saved && saved.mode) {
    const r = document.querySelector(`input[name=plan-mode][value=${saved.mode}]`);
    if (r) r.checked = true;
  }
}

const STATE_TEXT = {
  waiting: 'waiting', opening: 'opening...', running: 'running', closing: 'closing...',
  done: 'done', failed: 'FAILED', stopped: 'stopped',
};

async function pollPlan() {
  let st;
  try { st = await window.pywebview.api.plan_status(); } catch (e) { return; }
  if (!st.items.length) { planStatus.hidden = true; return; }
  planStatus.hidden = false;
  const lines = st.items.map(i => {
    let t = `NO. ${i.no}  ${i.url.replace(/^https?:\/\//, '')}`;
    if (i.pages_total > 1) t += `  (site ${i.page_index + 1} of ${i.pages_total})`;
    t += `  -  ${STATE_TEXT[i.state] || i.state}`;
    if (i.state === 'running') t += `  (${i.left}s left${i.scroll ? ', scrolling' : ''})`;
    if (i.note) t += `  - ${i.note}`;
    return t;
  });
  if (!st.active) lines.push('', 'Plan finished.');
  planStatus.textContent = lines.join('\n');
  document.getElementById('plan-run').disabled = st.active;
  document.getElementById('open-count').dataset.plan = st.active ? '1' : '';
  if (!st.active && planTimer) { clearInterval(planTimer); planTimer = null; refreshOpenState(); }
}

function startPlanPolling() {
  if (planTimer) clearInterval(planTimer);
  planTimer = setInterval(pollPlan, 1000);
  pollPlan();
}

document.getElementById('nav-plan').addEventListener('click', (e) => {
  e.preventDefault();
  if (!planRows.children.length) loadPlan();
  planModal.hidden = false;
  startPlanPolling();
});
document.getElementById('plan-close').addEventListener('click', () => { planModal.hidden = true; });
document.getElementById('plan-add-row').addEventListener('click', () => { addPlanRow(); });
document.querySelectorAll('input[name=plan-mode]').forEach(r => r.addEventListener('change', savePlan));
document.getElementById('plan-run').addEventListener('click', async () => {
  savePlan();
  const res = await window.pywebview.api.plan_run(readPlanRows(), planMode());
  setStatus(res.message, res.ok ? 'ok' : 'bad');
  if (!res.ok) {
    planStatus.hidden = false;
    planStatus.textContent = (res.problems || [res.message]).join('\n');
    return;
  }
  startPlanPolling();
});
document.getElementById('plan-stop').addEventListener('click', async () => {
  const res = await window.pywebview.api.plan_stop();
  setStatus(res.message, 'ok');
});

// --- Rename modal ---
const renameModal = document.getElementById('rename-modal');
const renameNameInput = document.getElementById('rename-name');
let currentRenameFile = null;

function openRenameModal(filename) {
  currentRenameFile = filename;
  const profile = allProfiles.find(p => p.file === filename);
  renameNameInput.value = profile ? profile.id : '';
  renameModal.hidden = false;
  renameNameInput.focus();
  renameNameInput.select();
}

function closeRenameModal() {
  renameModal.hidden = true;
  currentRenameFile = null;
}

document.getElementById('rename-cancel').addEventListener('click', closeRenameModal);
renameModal.addEventListener('click', (e) => { if (e.target === renameModal) closeRenameModal(); });

document.getElementById('rename-save').addEventListener('click', async () => {
  if (!currentRenameFile) return;
  setStatus('Renaming…', 'busy');
  const result = await window.pywebview.api.rename_profile(currentRenameFile, renameNameInput.value);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  closeRenameModal();
  if (result.ok) await loadProfiles();
});

// --- Fingerprint edit modal ---
const fpModal = document.getElementById('fp-modal');
const fpSub = document.getElementById('fp-modal-sub');
const fpPlatform = document.getElementById('fp-platform');
const fpGpuField = document.getElementById('fp-gpu-field');
const fpGpu = document.getElementById('fp-gpu');
const fpDeviceClass = document.getElementById('fp-device-class');
const fpHardwareLabel = document.getElementById('fp-hardware-label');
const fpHardware = document.getElementById('fp-hardware');
const fpLocale = document.getElementById('fp-locale');
const fpSeed = document.getElementById('fp-seed');
const fpUaPreview = document.getElementById('fp-user-agent-preview');
const fpFontsPreview = document.getElementById('fp-fonts-preview');
const fpIosCaveat = document.getElementById('fp-ios-caveat');

let fpOptions = null;      // fetched once, cached — the pools rarely change mid-session
let currentFpFile = null;

function fillSelect(select, options) {
  select.innerHTML = options.map(o => `<option value="${o.value}">${o.label}</option>`).join('');
}

function currentPlatformMeta() {
  return fpOptions.platforms.find(p => p.value === fpPlatform.value);
}

// Desktop (Windows/macOS): GPU picked independently of hardware/screen —
// any GPU legitimately pairs with any monitor/RAM on a real PC.
// Mobile (Android/iOS): GPU is hidden — a phone's chip/GPU/screen come as
// one fixed real-device bundle, so the "hardware" dropdown becomes the
// device picker instead, and there's nothing separate to choose for GPU.
function refreshForPlatformKind() {
  const meta = currentPlatformMeta();
  const isMobile = meta.kind === 'mobile';
  fpGpuField.hidden = isMobile;
  fpHardwareLabel.textContent = isMobile ? 'Device' : 'Hardware / screen';
  fpIosCaveat.hidden = fpPlatform.value !== 'ios';

  fillSelect(fpDeviceClass, meta.device_classes);
  if (!isMobile) fillSelect(fpGpu, fpOptions.gpus[fpPlatform.value]);
  refreshHardwareOptions();
  updatePreview();
}

function refreshHardwareOptions() {
  const meta = currentPlatformMeta();
  const source = meta.kind === 'mobile'
    ? fpOptions.devices[fpPlatform.value][fpDeviceClass.value]
    : fpOptions.hardware[fpDeviceClass.value];
  fillSelect(fpHardware, source);
  updatePreview();
}

// Live UA/fonts preview — recomputed client-side from cached fpOptions on
// every relevant change, no server round trip needed. This is what was
// broken before (switching Platform didn't update the preview text).
function updatePreview() {
  const meta = currentPlatformMeta();
  fpFontsPreview.textContent = meta.fonts_preview || '';
  if (meta.kind === 'mobile') {
    const devices = fpOptions.devices[fpPlatform.value][fpDeviceClass.value];
    const chosen = devices[fpHardware.value] || devices[0];
    fpUaPreview.textContent = chosen ? chosen.ua_preview : '';
  } else {
    fpUaPreview.textContent = meta.ua_preview || '';
  }
}

fpPlatform.addEventListener('change', refreshForPlatformKind);
fpDeviceClass.addEventListener('change', refreshHardwareOptions);
fpHardware.addEventListener('change', updatePreview);

document.getElementById('fp-randomize-seed').addEventListener('click', () => {
  fpSeed.value = Math.floor(100000 + Math.random() * 900000);
});

async function openFingerprintModal(filename) {
  currentFpFile = filename;
  fpSub.textContent = filename;

  if (!fpOptions) {
    fpOptions = await window.pywebview.api.get_fingerprint_options();
    fillSelect(fpPlatform, fpOptions.platforms);
    fillSelect(fpLocale, fpOptions.locales);
  }

  const config = await window.pywebview.api.get_profile_config(filename);
  if (!config.ok) {
    setStatus(config.message, 'bad');
    return;
  }

  fpPlatform.value = config.platform;
  const meta = currentPlatformMeta();
  const isMobile = meta.kind === 'mobile';
  fpGpuField.hidden = isMobile;
  fpHardwareLabel.textContent = isMobile ? 'Device' : 'Hardware / screen';
  fpIosCaveat.hidden = config.platform !== 'ios';

  fillSelect(fpDeviceClass, meta.device_classes);
  fpDeviceClass.value = config.device_class;

  if (!isMobile) {
    fillSelect(fpGpu, fpOptions.gpus[config.platform]);
    fpGpu.value = config.gpu_index;
    fillSelect(fpHardware, fpOptions.hardware[config.device_class]);
    fpHardware.value = config.hardware_index;
  } else {
    fillSelect(fpHardware, fpOptions.devices[config.platform][config.device_class]);
    fpHardware.value = config.device_index;
  }

  fpLocale.value = config.locale_index;
  fpSeed.value = config.canvas_seed;
  updatePreview();

  fpModal.hidden = false;
}

function closeFpModal() {
  fpModal.hidden = true;
  currentFpFile = null;
}

document.getElementById('fp-cancel').addEventListener('click', closeFpModal);
fpModal.addEventListener('click', (e) => { if (e.target === fpModal) closeFpModal(); });

document.getElementById('fp-save').addEventListener('click', async () => {
  if (!currentFpFile) return;
  const meta = currentPlatformMeta();
  const isMobile = meta.kind === 'mobile';
  const config = {
    platform: fpPlatform.value,
    device_class: fpDeviceClass.value,
    locale_index: fpLocale.value,
    canvas_seed: fpSeed.value,
  };
  if (isMobile) {
    config.device_index = fpHardware.value;
  } else {
    config.gpu_index = fpGpu.value;
    config.hardware_index = fpHardware.value;
  }
  setStatus('Saving fingerprint…', 'busy');
  const result = await window.pywebview.api.save_profile_config(currentFpFile, config);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  closeFpModal();
  if (result.ok) await loadProfiles();
});

document.getElementById('btn-generate').addEventListener('click', async () => {
  const count = genCountInput.value;
  setStatus(`Generating ${count} profiles…`, 'busy');
  const result = await window.pywebview.api.generate_profiles(count);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadProfiles();
});

document.getElementById('nav-open-folder').addEventListener('click', async (e) => {
  e.preventDefault();
  await window.pywebview.api.open_profiles_folder();
});

// --- Single-profile proxy modal ---
const proxyModal = document.getElementById('proxy-modal');
const proxyModalSub = document.getElementById('proxy-modal-sub');
const proxyPasteInput = document.getElementById('proxy-paste');
const proxyServerInput = document.getElementById('proxy-server');
const proxyUsernameInput = document.getElementById('proxy-username');
const proxyPasswordInput = document.getElementById('proxy-password');
let currentEditFile = null;

// Splits a pasted proxy into server/username/password, accepting either
// "server,username,password" (comma-separated, server can already include
// http://) or "host:port:username:password" (colon-separated — the format
// providers like Decodo export directly).
function parseProxyPaste(text) {
  text = text.trim();
  if (text.includes(',')) {
    const parts = text.split(',');
    if (parts.length < 2) return null;
    let server = parts[0].trim();
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(server)) server = 'http://' + server;
    return {
      server,
      username: (parts[1] || '').trim(),
      password: parts.slice(2).join(',').trim(),
    };
  }
  const colonParts = text.split(':');
  if (colonParts.length >= 4 && !/^https?:/i.test(text)) {
    const [host, port, username, ...rest] = colonParts;
    return { server: `http://${host}:${port}`, username, password: rest.join(':') };
  }
  return null;
}

proxyPasteInput.addEventListener('input', () => {
  const parsed = parseProxyPaste(proxyPasteInput.value);
  if (parsed) {
    proxyServerInput.value = parsed.server;
    proxyUsernameInput.value = parsed.username;
    proxyPasswordInput.value = parsed.password;
  }
});

async function openProxyModal(filename) {
  currentEditFile = filename;
  proxyModalSub.textContent = filename;
  proxyPasteInput.value = '';
  const current = await window.pywebview.api.get_profile_proxy(filename);
  proxyServerInput.value = current.ok ? current.server : '';
  proxyUsernameInput.value = current.ok ? current.username : '';
  proxyPasswordInput.value = current.ok ? current.password : '';
  document.getElementById('proxy-start-url').value = current.ok ? (current.start_url || '') : '';
  proxyModal.hidden = false;
  proxyPasteInput.focus();
}

function closeProxyModal() {
  proxyModal.hidden = true;
  currentEditFile = null;
}

document.getElementById('proxy-cancel').addEventListener('click', closeProxyModal);
proxyModal.addEventListener('click', (e) => { if (e.target === proxyModal) closeProxyModal(); });

document.getElementById('proxy-save').addEventListener('click', async () => {
  if (!currentEditFile) return;
  setStatus(`Saving proxy for ${currentEditFile}…`, 'busy');
  const result = await window.pywebview.api.save_profile_proxy(
    currentEditFile,
    proxyServerInput.value,
    proxyUsernameInput.value,
    proxyPasswordInput.value,
    document.getElementById('proxy-start-url').value
  );
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  closeProxyModal();
  if (result.ok) await loadProfiles();
});

// --- Bulk proxy modal ---
const bulkModal = document.getElementById('bulk-modal');
const bulkProxiesInput = document.getElementById('bulk-proxies');

document.getElementById('nav-bulk-proxy').addEventListener('click', (e) => {
  e.preventDefault();
  const rb = document.getElementById('bulk-result');
  if (rb) rb.hidden = true;
  bulkModal.hidden = false;
  bulkProxiesInput.focus();
});

function closeBulkModal() {
  bulkModal.hidden = true;
}

document.getElementById('bulk-cancel').addEventListener('click', closeBulkModal);
bulkModal.addEventListener('click', (e) => { if (e.target === bulkModal) closeBulkModal(); });

document.getElementById('bulk-save').addEventListener('click', async () => {
  const text = bulkProxiesInput.value;
  const resultBox = document.getElementById('bulk-result');
  resultBox.hidden = true;
  setStatus('Assigning proxies…', 'busy');
  const result = await window.pywebview.api.bulk_assign_proxies(text);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  const lines = [].concat(result.details || [], (result.skipped || []).map((s) => 'SKIPPED — ' + s));
  if (result.ok) await loadProfiles();
  if (result.ok && !(result.skipped && result.skipped.length)) {
    closeBulkModal();
    bulkProxiesInput.value = '';
  } else if (lines.length) {
    // Keep the box open so the user can see exactly which lines were
    // assigned and which weren't, instead of the result vanishing.
    resultBox.textContent = lines.join('\n');
    resultBox.hidden = false;
  }
});

// --- Built-in local API panel ---
const apiModal = document.getElementById('api-modal');

function apiExampleText(st) {
  return `# pip install patchright requests   (or playwright)
import requests
from patchright.sync_api import sync_playwright

BASE = "${st.url}"
HEAD = {"Authorization": "Bearer ${st.token}"}

def call(route, **body):
    r = requests.post(BASE + route, json=body, headers=HEAD).json()
    if r["error"]["code"] != 0:
        raise RuntimeError(r["error"]["message"])
    return r["data"]

print(call("profile-list", limit=5))                 # NO., name, group, is_open...
info = call("profile-open", profile_id=14)           # the profile in row NO. 14
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(info["ws"])
    page = browser.contexts[0].pages[0]
    page.goto("https://example.com")
call("profile-close", profile_id=14)

# also: profile-open-batch {"profiles": ["1-5", 14]}, profile-opened-list,
# profile-close-all, profile-update-proxy, proxy-bulk-assign {"text": "..."}`;
}

function renderApiStatus(st) {
  document.getElementById('api-enabled').checked = st.enabled;
  document.getElementById('api-port').value = st.port;
  document.getElementById('api-token').value = st.token;
  document.getElementById('api-example').value = apiExampleText(st);
  const line = document.getElementById('api-status-line');
  if (st.error) {
    line.textContent = st.error;
  } else if (st.running) {
    line.textContent = `Running at ${st.url}  -  ${st.open_profiles} profile(s) open right now.`;
  } else {
    line.textContent = 'Off.';
  }
}

async function copyText(text, okMsg) {
  try {
    await navigator.clipboard.writeText(text);
    setStatus(okMsg, 'ok');
  } catch (e) {
    setStatus('Couldn\'t copy automatically - select the text and press Ctrl+C.', 'bad');
  }
}

document.getElementById('nav-api').addEventListener('click', async (e) => {
  e.preventDefault();
  renderApiStatus(await window.pywebview.api.api_status());
  apiModal.hidden = false;
});
document.getElementById('api-close').addEventListener('click', () => { apiModal.hidden = true; });
apiModal.addEventListener('click', (e) => { if (e.target === apiModal) apiModal.hidden = true; });
document.getElementById('api-enabled').addEventListener('change', async (e) => {
  renderApiStatus(await window.pywebview.api.api_set_enabled(e.target.checked));
});
document.getElementById('api-save-port').addEventListener('click', async () => {
  const res = await window.pywebview.api.api_set_port(document.getElementById('api-port').value);
  renderApiStatus(res);
  setStatus(res.message, res.ok ? 'ok' : 'bad');
});
document.getElementById('api-new-token').addEventListener('click', async () => {
  renderApiStatus(await window.pywebview.api.api_regenerate_token());
  setStatus('New token created - update any scripts using the old one.', 'ok');
});
document.getElementById('api-copy-token').addEventListener('click', () =>
  copyText(document.getElementById('api-token').value, 'Token copied.'));
document.getElementById('api-copy-example').addEventListener('click', () =>
  copyText(document.getElementById('api-example').value, 'Example copied.'));

// Profiles only load once authenticated — see the auth gate logic below,
// which calls loadProfiles() itself after a successful sign-in or restore.

// --- Auth gate ---
const authGate = document.getElementById('auth-gate');
const appShell = document.getElementById('app-shell');
const authEmailInput = document.getElementById('auth-email');
const authPasswordInput = document.getElementById('auth-password');
const authNote = document.getElementById('auth-note');
const cloudSignedInAs = document.getElementById('cloud-signed-in-as');

function setAuthNote(text, mode) {
  authNote.textContent = text;
  authNote.className = 'auth-note' + (mode ? ' ' + mode : '');
}

async function enterApp(email) {
  authGate.hidden = true;
  appShell.hidden = false;
  cloudSignedInAs.textContent = email;

  // Automatically load whatever's already in your account, so profiles
  // are there the moment you sign in — no manual Pull needed on first load.
  setStatus('Loading your profiles from the cloud…', 'busy');
  const pullResult = await window.pywebview.api.cloud_pull();
  if (!pullResult.ok) {
    setStatus(pullResult.message, 'bad');
  }
  await loadProfiles();
  await loadGroups();
}

document.getElementById('auth-signup').addEventListener('click', async () => {
  setAuthNote('Creating account…');
  const result = await window.pywebview.api.cloud_sign_up(authEmailInput.value, authPasswordInput.value);
  setAuthNote(result.message, result.ok ? 'ok' : 'bad');
});

document.getElementById('auth-signin').addEventListener('click', async () => {
  setAuthNote('Signing in…');
  const result = await window.pywebview.api.cloud_sign_in(authEmailInput.value, authPasswordInput.value);
  if (result.ok) {
    await enterApp(authEmailInput.value);
  } else {
    setAuthNote(result.message, 'bad');
  }
});

document.getElementById('btn-cloud-pull').addEventListener('click', async () => {
  setStatus('Pulling profiles from the cloud…', 'busy');
  const result = await window.pywebview.api.cloud_pull();
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadProfiles();
});

document.getElementById('btn-cloud-push').addEventListener('click', async () => {
  setStatus('Pushing profiles to the cloud…', 'busy');
  const result = await window.pywebview.api.cloud_push();
  setStatus(result.message, result.ok ? 'ok' : 'bad');
});

document.getElementById('btn-cloud-signout').addEventListener('click', async () => {
  await window.pywebview.api.cloud_sign_out();
  appShell.hidden = true;
  authGate.hidden = false;
  authEmailInput.value = '';
  authPasswordInput.value = '';
  setAuthNote('');
});

// On startup: make sure Chromium is actually installed before showing
// anything else — no point letting someone sign in and pick a profile if
// Launch would just fail moments later because the browser engine isn't
// there yet. The setup gate stays up (with a retry option on failure)
// until this resolves; only then do we move on to the normal auth-gate /
// session-restore flow (which itself keeps the gate up until THAT
// resolves, so there's no flash of the profile table before we know
// whether you're actually signed in).
window.addEventListener('pywebviewready', async () => {
  const setupGate = document.getElementById('setup-gate');
  const setupStatus = document.getElementById('setup-status');
  const setupSpinner = document.getElementById('setup-spinner');
  const setupRetry = document.getElementById('setup-retry');

  async function runChromiumSetup() {
    setupStatus.textContent = 'Setting up the browser engine — this can take a minute on first run.';
    setupSpinner.hidden = false;
    setupRetry.hidden = true;
    const result = await window.pywebview.api.ensure_chromium();
    if (result.ok) {
      setupGate.hidden = true;
      authGate.hidden = false;
      const restored = await window.pywebview.api.cloud_try_restore();
      if (restored.signed_in) {
        await enterApp(restored.email);
      }
      // else: gate just stays visible, waiting for sign-in — nothing else to do.
    } else {
      setupSpinner.hidden = true;
      setupStatus.textContent = result.message || 'Browser engine setup failed.';
      setupRetry.hidden = false;
    }
  }

  setupRetry.addEventListener('click', runChromiumSetup);
  await runChromiumSetup();
});

// --- Team management ---
const teamModal = document.getElementById('team-modal');
const teamMembersList = document.getElementById('team-members-list');
const teamInviteRow = document.getElementById('team-invite-row');
const teamInviteLabel = document.getElementById('team-invite-label');
const teamInviteRole = document.getElementById('team-invite-role');
const teamInviteResult = document.getElementById('team-invite-result');
const teamJoinCode = document.getElementById('team-join-code');

async function loadTeamMembers() {
  const roleResult = await window.pywebview.api.cloud_get_role();
  const canManage = roleResult.role === 'owner' || roleResult.role === 'admin';

  teamInviteRow.hidden = !canManage;
  teamInviteLabel.hidden = !canManage;

  const result = await window.pywebview.api.cloud_list_members();
  if (!result.ok) {
    teamMembersList.innerHTML = `<p class="modal-sub">${result.message}</p>`;
    return;
  }

  teamMembersList.innerHTML = result.members.map(m => `
    <div class="team-member-row">
      <span class="team-member-email">${m.email}</span>
      ${m.is_you ? '<span class="team-member-you">YOU</span>' : ''}
      ${canManage && !m.is_you && m.role !== 'owner' ? `
        <select data-role-user="${m.user_id}">
          <option value="staff" ${m.role === 'staff' ? 'selected' : ''}>Staff</option>
          <option value="admin" ${m.role === 'admin' ? 'selected' : ''}>Admin</option>
        </select>
        <button class="btn btn-ghost btn-small" data-remove-user="${m.user_id}">Remove</button>
      ` : `<span class="cell-sub">${m.role}</span>`}
    </div>
  `).join('');
}

document.getElementById('nav-team').addEventListener('click', async (e) => {
  e.preventDefault();
  teamInviteResult.hidden = true;
  teamJoinCode.value = '';
  teamModal.hidden = false;
  await loadTeamMembers();
});

document.getElementById('team-close').addEventListener('click', () => { teamModal.hidden = true; });
teamModal.addEventListener('click', (e) => { if (e.target === teamModal) teamModal.hidden = true; });

teamMembersList.addEventListener('change', async (e) => {
  const userId = e.target.getAttribute('data-role-user');
  if (!userId) return;
  setStatus('Updating role…', 'busy');
  const result = await window.pywebview.api.cloud_update_member_role(userId, e.target.value);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
});

teamMembersList.addEventListener('click', async (e) => {
  const userId = e.target.getAttribute('data-remove-user');
  if (!userId) return;
  setStatus('Removing member…', 'busy');
  const result = await window.pywebview.api.cloud_remove_member(userId);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadTeamMembers();
});

document.getElementById('team-create-invite').addEventListener('click', async () => {
  setStatus('Creating invite…', 'busy');
  const result = await window.pywebview.api.cloud_create_invite(teamInviteRole.value);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) {
    teamInviteResult.textContent = `Code: ${result.code} — share this with your teammate`;
    teamInviteResult.hidden = false;
  }
});

document.getElementById('team-join-btn').addEventListener('click', async () => {
  const code = teamJoinCode.value.trim();
  if (!code) return;
  setStatus('Joining team…', 'busy');
  const result = await window.pywebview.api.cloud_redeem_invite(code);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) {
    teamJoinCode.value = '';
    await loadTeamMembers();
    await window.pywebview.api.cloud_pull();
    await loadProfiles();
  }
});

// --- Extension management ---
const extModal = document.getElementById('ext-modal');
const extList = document.getElementById('ext-list');

async function loadExtensions() {
  const lockStatus = await window.pywebview.api.get_extension_lock_status();
  const lockLabel = document.getElementById('ext-lock-status');
  if (lockStatus.unlocked) {
    lockLabel.textContent = lockStatus.unlock_at
      ? `Unlocked (unlock time ${lockStatus.unlock_at} has passed) — removal is available below.`
      : 'Unlocked.';
  } else if (lockStatus.unlock_at) {
    lockLabel.textContent = `Locked — unlocks at ${lockStatus.unlock_at}.`;
  } else {
    lockLabel.textContent = 'Locked — no unlock time set. Extensions cannot be removed.';
  }

  const extensions = await window.pywebview.api.list_extensions();
  if (extensions.length === 0) {
    extList.innerHTML = '<p class="modal-sub">No extensions added yet.</p>';
    return;
  }
  extList.innerHTML = extensions.map(e => `
    <div class="team-member-row">
      <span class="team-member-email">${e.name}</span>
      <span class="cell-sub">v${e.version}</span>
      ${lockStatus.unlocked
        ? `<button class="btn btn-ghost btn-small" data-remove-ext="${e.folder}">Remove</button>`
        : `<span class="cell-sub">🔒 locked</span>`}
    </div>
  `).join('');
}

extList.addEventListener('click', async (e) => {
  const folder = e.target.getAttribute('data-remove-ext');
  if (!folder) return;
  setStatus(`Removing ${folder}…`, 'busy');
  const result = await window.pywebview.api.remove_extension(folder);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadExtensions();
});

document.getElementById('ext-set-unlock').addEventListener('click', async () => {
  const value = document.getElementById('ext-unlock-input').value;
  if (!value) return;
  setStatus('Setting unlock time…', 'busy');
  const result = await window.pywebview.api.set_extension_unlock_time(value);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadExtensions();
});

document.getElementById('nav-extensions').addEventListener('click', async (e) => {
  e.preventDefault();
  extModal.hidden = false;
  await loadExtensions();
});

document.getElementById('ext-close').addEventListener('click', () => { extModal.hidden = true; });
extModal.addEventListener('click', (e) => { if (e.target === extModal) extModal.hidden = true; });

document.getElementById('ext-add-folder').addEventListener('click', async () => {
  setStatus('Waiting for folder selection…', 'busy');
  const result = await window.pywebview.api.add_extension_from_folder();
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadExtensions();
});

document.getElementById('ext-add-zip').addEventListener('click', async () => {
  setStatus('Waiting for file selection…', 'busy');
  const result = await window.pywebview.api.add_extension_from_zip();
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) await loadExtensions();
});

document.getElementById('ext-add-webstore').addEventListener('click', async () => {
  const input = document.getElementById('ext-webstore-url');
  const value = input.value.trim();
  if (!value) return;
  setStatus('Downloading extension from Chrome Web Store…', 'busy');
  const result = await window.pywebview.api.add_extension_from_webstore(value);
  setStatus(result.message, result.ok ? 'ok' : 'bad');
  if (result.ok) {
    input.value = '';
    await loadExtensions();
  }
});
