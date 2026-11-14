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
import { badge, clear, el, setState, showToast } from './ui.js';

const STATUS_VARIANT = { pass: 'status-in', warn: 'status-out', fail: 'status-out' };

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
    // The session cookie is the credential; no device key in the browser.
    const response = await fetch('/api/detection/scan', {
      method: 'POST',
      credentials: 'same-origin',
      body,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error || `Scan failed (${response.status}).`);
    if (plate) plate.textContent = payload.bus_number || 'UNKNOWN';
    if (status) {
      status.textContent = payload.bus_number
        ? `Read ${payload.bus_number} (${Math.round((payload.confidence || 0) * 100)}%)`
        : 'The detector found no sticker in this frame.';
      status.className = `scan-status ${payload.bus_number ? '' : 'text-danger'}`.trim();
    }
    if (meta) {
      meta.textContent = payload.raw_text
        ? `OCR read: ${payload.raw_text}`
        : 'Detector responded; no text was read from this frame.';
    }
    showToast(payload.bus_number ? `Detected ${payload.bus_number}` : 'No plate in this frame.', payload.bus_number ? 'success' : 'error');
  } catch (error) {
    if (status) {
      status.textContent = error.message || 'Scan failed.';
      status.className = 'scan-status text-danger';
    }
    if (meta) {
      meta.textContent = 'If this says the detector is unavailable, the host has no torch/ultralytics/PIL — the free image ships without them.';
    }
    showToast(error.message || 'Scan failed.', 'error');
  }
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
  mountCamera();
  wireEventForm();
  document.getElementById('refreshChecks').addEventListener('click', loadChecks);
  loadChecks();
}

main();
