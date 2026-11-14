/**
 * Test Lab — an isolated bench for the demo environment.
 *
 * Only reachable when the backend runs with DEMO_MODE on; the page route and
 * every /api/test-lab/* endpoint return 404 otherwise. Everything here writes
 * seeded demo records, never real ones.
 */
import { apiGet, apiPost } from './api.js';
import { renderCameraTile } from './cameras.js';
import { mountShell } from './layout.js';
import {
  STAGES,
  appendStagesToForm,
  currentStageFlags,
  describeScan,
  renderStageChips,
  setStageFlag,
} from './detection-stages.js';
import { badge, clear, el, icon, setState, showToast } from './ui.js';

const STATUS_VARIANT = { pass: 'status-in', warn: 'status-out', fail: 'status-out' };

/**
 * The cascade itself (order, switches, storage) lives in detection-stages.js so
 * the dashboard and this bench read the same switch state.
 */
let stageStatus = {};

function stageNote(stage) {
  const notes = [stage.note];
  const info = stageStatus[stage.key];
  if (info && info.model_present === false && !info.required) {
    notes.push('checkpoint not installed yet');
  }
  return notes.join(' \u00b7 ');
}

/** Remember the status rows and re-draw the toggles with the new notes. */
function applyStageStatus(rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  stageStatus = {};
  for (const row of rows) {
    stageStatus[row.name] = row;
    // The panel says "plate", the API says "number_plate": index both.
    stageStatus[String(row.name).replace('number_plate', 'plate')] = row;
  }
  renderStageToggles();
}

/** Last /api/test-lab/checks payload's detection.setup, for the copy button. */
let lastSetup = null;

function statusBadge(status) {
  const label = status === 'pass' ? 'Pass' : status === 'warn' ? 'Warn' : 'Fail';
  return badge(label, STATUS_VARIANT[status] || '');
}

function renderChecks(payload) {
  const body = document.getElementById('checksBody');
  const state = document.getElementById('checksState');
  const table = document.getElementById('checksTable');
  const stamp = document.getElementById('labStamp');
  clear(body);
  const checks = payload.checks || [];
  for (const check of checks) {
    body.append(el('tr', {}, [
      el('td', { text: check.label || check.id }),
      el('td', {}, [statusBadge(check.status)]),
      el('td', { class: 'muted', text: check.detail || '' }),
    ]));
  }
  if (!checks.length) {
    setState(state, 'empty', 'The checks endpoint returned nothing.', null, table);
  } else {
    setState(state, 'ok', '', null, null);
    table.hidden = false;
  }
  const problems = (payload.detection && payload.detection.problems) || [];
  if (stamp) {
    stamp.textContent = payload.demo_mode
      ? `demo · ${payload.environment} · ${problems.length ? 'detector incomplete' : 'detector ready'}`
      : 'demo mode off';
  }
  renderSetup(payload.detection && payload.detection.setup);
  applyStageStatus(payload.detection && payload.detection.stages);
}

/**
 * Show each part of the vision stack separately.
 *
 * A half-installed stack used to surface as one sentence ("Pillow is not
 * installed. Install the vision extras…"), which tells you neither what else is
 * missing nor whether the command is the right one for your machine.
 */
function renderSetup(setup) {
  const host = document.getElementById('visionSetup');
  const stamp = document.getElementById('visionSetupStamp');
  const note = document.getElementById('visionSetupNote');
  const copy = document.getElementById('copySetup');
  if (!host || !setup) return;
  clear(host);
  lastSetup = setup;

  for (const component of setup.components || []) {
    const ok = Boolean(component.present);
    host.append(el('div', { class: `setup-item ${ok ? 'is-ok' : 'is-missing'}` }, [
      el('span', { class: 'setup-state', 'aria-hidden': 'true' }, [icon(ok ? 'bx-check' : 'bx-x')]),
      el('div', { class: 'setup-body' }, [
        el('span', { class: 'setup-label', text: component.label }),
        el('span', {
          class: 'setup-meta',
          text: ok ? `installed · ${component.size}` : `missing · ${component.size}`,
        }),
        ok ? null : el('code', { text: component.command }),
      ]),
    ]));
  }

  const missing = setup.missing || [];
  if (stamp) {
    stamp.textContent = setup.ready
      ? 'all components present'
      : `${missing.length} component${missing.length === 1 ? '' : 's'} missing`;
  }
  if (note) {
    note.textContent = setup.ready
      ? 'Everything the detector needs is installed. A scan should return a plate, or a clear "no sticker in this frame".'
      : setup.note;
  }
  if (copy) copy.disabled = Boolean(setup.ready);
}

async function copySetup() {
  const lines = (lastSetup?.components || [])
    .filter((component) => !component.present)
    .map((component) => component.command);
  if (!lines.length) {
    showToast('Nothing to install — every component is present.', 'success');
    return;
  }
  const text = [
    '# VISION AI - SRM TRP — detector setup (run in the activated venv)',
    ...lines,
    '',
    '# or, all at once:',
    lastSetup.install_all,
  ].join('\n');
  try {
    await navigator.clipboard.writeText(text);
    showToast('Install commands copied.', 'success');
  } catch (_error) {
    // Clipboard needs a secure context; offer the text instead of failing silently.
    window.prompt('Copy these commands:', text);
  }
}

async function loadChecks() {
  const state = document.getElementById('checksState');
  const table = document.getElementById('checksTable');
  setState(state, 'loading', 'Running checks…', null, table);
  try {
    const payload = await apiGet('/api/test-lab/checks');
    renderChecks(payload);
  } catch (error) {
    setState(state, 'error', error.message || 'Checks failed.', loadChecks, table);
  }
}

async function scanFrame(blob) {
  const status = document.getElementById('labScanStatus');
  const plate = document.getElementById('labPlate');
  const meta = document.getElementById('labScanMeta');
  if (status) {
    status.textContent = 'Scanning frame…';
    status.className = 'scan-status';
  }
  try {
    const body = new FormData();
    body.append('image', blob, 'frame.jpg');
    body.append('source', 'test-lab');
    // One switch per stage, exactly as the panel shows them.
    appendStagesToForm(body);
    // The session cookie is the credential; no device key in the browser.
    const response = await fetch('/api/detection/scan', {
      method: 'POST',
      credentials: 'same-origin',
      body,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error || `Scan failed (${response.status}).`);
    if (plate) plate.textContent = payload.bus_number || 'UNKNOWN';
    // The response says *why* it has no number: nothing detected, everything
    // below the confidence threshold, a plate the OCR missed — and which stage
    // answered when one did.
    const detection = payload.detection || {};
    const { good, text } = describeScan(payload);
    if (status) {
      status.textContent = text;
      status.className = `scan-status ${good ? '' : 'text-danger'}`.trim();
    }
    if (meta) {
      meta.textContent = payload.raw_text
        ? `OCR read: ${payload.raw_text}`
        : payload.advice || 'Detector responded; no text was read from this frame.';
    }
    drawStageChips(payload.stages || detection.stages);
    showToast(payload.bus_number ? `Detected ${payload.bus_number}` : 'No plate in this frame.', payload.bus_number ? 'success' : 'error');
  } catch (error) {
    if (status) {
      status.textContent = error.message || 'Scan failed.';
      status.className = 'scan-status text-danger';
    }
    if (meta) {
      meta.textContent = 'The detector needs the optional vision extras. See “Detector setup” above for the exact command; the camera preview itself keeps working.';
    }
    showToast(error.message || 'Scan failed.', 'error');
    loadChecks();
  }
}

/**
 * Draw one switch per stage.
 *
 * The switch is a real checkbox, so keyboard and screen readers get the
 * semantics for free; the visual switch is styling only.
 */
function renderStageToggles() {
  const host = document.getElementById('stageToggles');
  const stamp = document.getElementById('stageStamp');
  if (!host) return;
  clear(host);
  for (const stage of STAGES) {
    const id = `stage-${stage.key}`;
    const input = el('input', {
      type: 'checkbox',
      id,
      class: 'stage-switch-input',
      checked: currentStageFlags()[stage.key],
    });
    // `el()` drops false-valued props, so set the live state explicitly.
    input.checked = Boolean(currentStageFlags()[stage.key]);
    input.addEventListener('change', () => {
      setStageFlag(stage.key, input.checked);
      updateStageStamp(stamp);
    });
    host.append(el('label', { class: 'stage-toggle', for: id }, [
      el('span', { class: 'stage-switch' }, [input, el('span', { class: 'stage-switch-track', 'aria-hidden': 'true' })]),
      el('span', { class: 'stage-toggle-body' }, [
        el('span', { class: 'stage-toggle-label', text: stage.label }),
        el('span', { class: 'stage-toggle-note', text: stageNote(stage) }),
      ]),
    ]));
  }
  updateStageStamp(stamp);
}

function updateStageStamp(stamp) {
  if (!stamp) return;
  const flags = currentStageFlags();
  const on = STAGES.filter((stage) => flags[stage.key]).map((stage) => stage.label);
  stamp.textContent = on.length
    ? `Running: ${on.join(' → ')}`
    : 'Every stage is off — scans will report no detection.';
}

/** Draw the per-stage chips for the last scan into this page's host. */
function drawStageChips(stages) {
  renderStageChips(document.getElementById('labStages'), stages);
}

function mountCamera() {
  const host = document.getElementById('labCameraHost');
  if (!host) return;
  host.append(renderCameraTile({
    id: 'lab-browser-camera',
    label: 'Test Lab camera (this device)',
    source: 'browser',
    onCapture: (blob) => scanFrame(blob),
  }));
}

function wireEventForm() {
  const form = document.getElementById('testEventForm');
  const result = document.getElementById('eventResult');
  const submit = document.getElementById('testEventSubmit');
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const timestamp = new Date().toISOString();
    submit.disabled = true;
    try {
      const response = await apiPost('/api/test-lab/events', {
        bus_number: String(data.get('bus_number') || '').trim(),
        direction: String(data.get('direction') || 'IN'),
        gate: String(data.get('gate') || '').trim(),
        camera_id: String(data.get('camera_id') || 'test-lab').trim(),
        confidence: 0.97,
        timestamp,
      });
      const created = response.event || {};
      result.hidden = false;
      setState(result, 'ok', `Inserted ${created.bus_number || 'event'} · ${created.direction || ''} · ${created.gate || ''}`);
      showToast('Test event inserted.', 'success');
      loadChecks();
    } catch (error) {
      result.hidden = false;
      setState(result, 'error', error.message || 'Could not insert the test event.');
      showToast(error.message || 'Insert failed.', 'error');
    } finally {
      submit.disabled = false;
    }
  });
}

async function main() {
  await mountShell({ active: 'test-lab', allowedRoles: ['head_admin'], pageTitle: 'Test Lab' });
  renderStageToggles();
  mountCamera();
  wireEventForm();
  document.getElementById('refreshChecks').addEventListener('click', loadChecks);
  document.getElementById('copySetup').addEventListener('click', copySetup);
  document.getElementById('recheckSetup').addEventListener('click', loadChecks);
  loadChecks();
}

main();
