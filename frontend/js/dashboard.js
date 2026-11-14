import { apiGet, toQuery } from './api.js';
import { renderCharts } from './charts.js';
import { downloadExport } from './exports.js';
import { analyticsParams, eventParams, exportParams, readFilters } from './filters.js';
import { mountShell } from './layout.js';
import { connectLive } from './sse.js';
import { renderCameras, renderCameraTile, requestWebcam, stopStream } from './cameras.js';
import {
  STAGES,
  appendStagesToForm,
  currentStageFlags,
  describeScan,
  scanDetail,
  scanFailureText,
  setStageFlag,
} from './detection-stages.js';
import { renderEventsTable } from './tables.js';
import { clear, el, formatDateTime, formatNumber, setState, showToast } from './ui.js';
import { analytics, initFirebase } from './firebase.js';

let currentFilters = {};
let currentEvents = [];
let flagLabels = {};
let live = null;

function setStat(name, value) {
  const node = document.querySelector(`[data-stat="${name}"]`);
  if (node) node.textContent = formatNumber(value);
}

function resetStats() {
  ['total_buses', 'entries_today', 'buses_inside', 'flagged_today', 'unrecognized_today'].forEach((name) => {
    const node = document.querySelector(`[data-stat="${name}"]`);
    if (node) node.textContent = '—';
  });
  const breakdown = document.getElementById('flagBreakdown');
  if (breakdown) breakdown.textContent = 'Waiting for live event data…';
}

function renderStats(stats) {
  setStat('total_buses', stats.total_buses);
  setStat('entries_today', stats.entries_today);
  setStat('buses_inside', stats.buses_inside);
  setStat('flagged_today', stats.flagged_today);
  setStat('unrecognized_today', stats.unrecognized_today);
  flagLabels = stats.flag_labels || {};
  const counts = stats.flagged_reason_counts || {};
  const parts = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .map(([reason, count]) => `${flagLabels[reason] || reason}: ${count}`);
  const breakdown = document.getElementById('flagBreakdown');
  if (breakdown) breakdown.textContent = parts.length ? parts.join(' · ') : 'No flagged events today.';
  const lastUpdated = document.getElementById('lastUpdated');
  if (lastUpdated) lastUpdated.textContent = `Updated ${formatDateTime(stats.generated_at)}`;
  renderLastDetected(stats.last_event);
}

function renderLastDetected(event) {
  const plate = document.getElementById('plateValue');
  const status = document.getElementById('scanStatus');
  const meta = document.getElementById('scanMeta');
  const state = document.getElementById('lastDetectedState');
  if (!state) return;
  if (!event) {
    plate.textContent = '—';
    status.textContent = 'Awaiting first detection';
    meta.textContent = 'No events have been ingested yet.';
    setState(state, 'empty', 'The detection system has not posted any events.');
    return;
  }
  setState(state, 'ok');
  plate.textContent = event.bus_number || 'UNKNOWN';
  const reasons = event.flag_reasons || [];
  status.textContent = reasons.length ? `Flagged: ${reasons.map((reason) => flagLabels[reason] || reason).join(', ')}` : 'Authorized movement';
  status.className = `scan-status ${reasons.length ? 'text-danger' : ''}`.trim();
  meta.textContent = `${event.direction || '—'} · ${event.gate || '—'} · ${Math.round((event.confidence || 0) * 100)}% confidence · ${formatDateTime(event.timestamp)}`;
}

function setChartState(type, message) {
  document.querySelectorAll('.chart-state').forEach((host) => setState(host, type, message));
  document.querySelectorAll('.chart-wrap canvas').forEach((canvas) => { canvas.hidden = type !== 'ok'; });
}

/* ------------------------------------------------------------------ */
/* Live operator camera + plate scanning                               */
/* ------------------------------------------------------------------ */

let browserCameraTile = null;
let camerasMounted = false;

/**
 * Mount a "this device" camera tile that uses the operator's webcam.
 * It is only offered when the browser actually exposes getUserMedia.
 */
function mountBrowserCamera(cameras) {
  const host = document.getElementById('cameraGrid');
  if (!host) return;
  const existing = host.querySelector('[data-camera-id="browser-local"]');
  // Reuse the live tile: removing it dropped the <video> but not its tracks,
  // so the camera stayed open while a second stream was requested.
  if (existing) return;
  host.querySelector('.state-box')?.remove();

  if (!navigator.mediaDevices?.getUserMedia) {
    return; // Browser cannot access a camera; nothing to offer.
  }

  browserCameraTile = renderCameraTile({
    id: 'browser-local',
    label: 'Operator camera (this device)',
    source: 'browser',
    onCapture: scanFrame,
  });
  host.prepend(browserCameraTile);
}

/**
 * Post a captured frame to the detection endpoint and surface the result.
 * The endpoint requires the device API key, so the browser capture is sent
 * through the backend's authenticated session route when available and falls
 * back to the device-scoped route otherwise.
 */
async function scanFrame(blob, meta = {}) {
  const statusNode = document.getElementById('scanStatus');
  if (statusNode) {
    statusNode.textContent = 'Scanning frame…';
    statusNode.className = 'scan-status';
  }
  try {
    const body = new FormData();
    body.append('image', blob, 'frame.jpg');
    body.append('camera_id', meta.cameraId || 'browser-local');
    body.append('gate', 'Gate 1 Entry');
    body.append('direction', 'IN');
    body.append('source', 'browser');
    // The same switches the Test Lab shows: an operator who turned sticker
    // detection off expects the dashboard to leave it off.
    appendStagesToForm(body);

    // The session cookie is the credential here; the device API key must never
    // be shipped to a browser (it would be readable by any script on the page
    // and by anyone with DevTools).
    const response = await fetch('/api/detection/scan', {
      method: 'POST',
      credentials: 'same-origin',
      body,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.error || `Scan failed (${response.status}).`);
    }

    applyScanResult(payload, meta);
  } catch (error) {
    if (statusNode) {
      statusNode.textContent = error.message || 'Scan failed.';
      statusNode.className = 'scan-status text-danger';
    }
    showToast(error.message || 'Scan failed.', 'error');
  }
}

/** Show one scan result in the Last Detected card, whichever path produced it. */
function applyScanResult(payload, meta = {}) {
  const statusNode = document.getElementById('scanStatus');
  const plateNode = document.getElementById('plateValue');
  const metaNode = document.getElementById('scanMeta');
  const busNumber = payload.bus_number;
  if (plateNode) plateNode.textContent = busNumber || 'UNKNOWN';
  if (statusNode) {
    const { good, text } = describeScan(payload);
    statusNode.textContent = text;
    statusNode.className = `scan-status ${good ? '' : 'text-danger'}`.trim();
  }
  if (metaNode) metaNode.textContent = scanDetail(payload);
  renderStageWarning();
  analytics.detectionResult(busNumber, payload.confidence);
  analytics.captureFrame(meta.cameraId || 'gate-camera');
  showToast(
    busNumber ? `Detected bus ${busNumber}` : scanFailureText(payload),
    busNumber ? 'success' : 'error',
  );
  refreshAll();
}

/**
 * Scan the gate camera with no browser camera involved.
 *
 * `capture: true` tells the backend to grab the frame itself from CAMERA_SOURCE
 * (an HTTP snapshot endpoint, an RTSP stream or a USB device) and scan it. This
 * is the only path that works on a gate PC with an IP camera and no webcam,
 * and the only path that can use RTSP at all.
 */
async function scanGateCamera(button) {
  const statusNode = document.getElementById('scanStatus');
  if (statusNode) {
    statusNode.textContent = 'Grabbing a frame from the gate camera…';
    statusNode.className = 'scan-status';
  }
  if (button) button.disabled = true;
  try {
    const response = await fetch('/api/detection/scan', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        capture: true,
        source: 'gate-camera',
        gate: 'Gate 1 Entry',
        direction: 'IN',
        stages: currentStageFlags(),
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(payload?.error || `Scan failed (${response.status}).`);
    applyScanResult(payload, { cameraId: 'gate-camera' });
  } catch (error) {
    if (statusNode) {
      statusNode.textContent = error.message || 'Scan failed.';
      statusNode.className = 'scan-status text-danger';
    }
    showToast(error.message || 'Scan failed.', 'error');
  } finally {
    if (button) button.disabled = false;
  }
}

async function refreshAll() {
  const eventsState = document.getElementById('eventsState');
  const eventsTable = document.getElementById('eventsTable');
  setState(eventsState, 'loading', 'Loading live gate events…', null, eventsTable);
  setChartState('loading', 'Loading charts…');
  try {
    const [config, stats, events, analytics] = await Promise.all([
      apiGet('/api/config'),
      apiGet('/api/stats'),
      apiGet(`/api/events${toQuery(eventParams(currentFilters))}`),
      apiGet(`/api/analytics${toQuery(analyticsParams(currentFilters))}`),
    ]);
    flagLabels = config.flag_labels || stats.flag_labels || {};
    // Mount the cameras once. refreshAll() runs after every scan and on every
    // SSE tick: re-rendering here replaced the operator's <video>, stopped
    // nothing, opened a second getUserMedia stream each time, and left the next
    // capture reading a <video> with readyState 0 — a blank JPEG.
    if (!camerasMounted) {
      renderCameras(document.getElementById('cameraGrid'), config.cameras || [], {
        onCapture: scanFrame,
      });
      mountBrowserCamera(config.cameras || []);
      camerasMounted = true;
    }
    renderStats(stats);
    currentEvents = events.items || [];
    if (currentEvents.length) {
      setState(eventsState, 'ok', '', null, eventsTable);
      renderEventsTable(document.getElementById('eventsBody'), currentEvents, flagLabels);
    } else {
      setState(eventsState, 'empty', 'No events match these filters.', null, eventsTable);
    }
    const summary = document.getElementById('eventsSummary');
    if (summary) summary.textContent = `${formatNumber(events.total)} matching events · page ${events.page}`;
    const mode = document.getElementById('streamMode');
    if (mode) mode.textContent = live?.mode() === 'poll' ? 'API polling' : 'Server-sent events';
    setChartState('ok');
    renderCharts(analytics);
  } catch (error) {
    setState(eventsState, 'error', error.message || 'Could not load live data.', () => refreshAll(), eventsTable);
    setChartState('error', error.message || 'Could not load analytics.');
    resetStats();
    showToast(error.message || 'Live data refresh failed.', 'error');
  }
}

function wire() {
  const form = document.getElementById('dashboardFilters');
  const exportCsv = document.getElementById('exportCsv');
  const exportXlsx = document.getElementById('exportXlsx');
  const refreshButton = document.getElementById('refreshButton');
  currentFilters = readFilters(form);

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    currentFilters = readFilters(form);
    refreshAll();
  });
  form.addEventListener('reset', () => {
    setTimeout(() => {
      currentFilters = readFilters(form);
      refreshAll();
    }, 0);
  });
  refreshButton.addEventListener('click', refreshAll);
  const gateScan = document.getElementById('scanGateCamera');
  if (gateScan) {
    gateScan.addEventListener('click', () => scanGateCamera(gateScan));
    // Offer it only when this PC has a camera configured. The status route
    // returns the masked source, never the camera password.
    apiGet('/api/camera/status')
      .then((status) => {
        if (status && status.configured) {
          gateScan.style.display = '';
          gateScan.title = `Gate camera: ${status.kind} ${status.source}`;
        }
      })
      .catch(() => {
        // No camera on this install: the browser camera tile still works.
      });
  }
  exportCsv.addEventListener('click', () => downloadExport('csv', exportParams(currentFilters), currentEvents));
  exportXlsx.addEventListener('click', () => downloadExport('xlsx', exportParams(currentFilters), currentEvents));

  live = connectLive({
    filters: () => currentFilters,
    onTick: () => refreshAll(),
    onError: (error) => showToast(error.message || 'Live stream failed; retrying.', 'error'),
  });
  window.addEventListener('pagehide', () => live?.stop());
  renderStageWarning();
  refreshAll();
}

mountShell({ active: 'dashboard', allowedRoles: ['head_admin'], pageTitle: 'Live Dashboard' })
  .then(wire)
  .catch((error) => showToast(error.message, 'error'));
