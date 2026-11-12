import { apiGet, toQuery } from './api.js';
import { renderCharts } from './charts.js';
import { downloadExport } from './exports.js';
import { analyticsParams, eventParams, exportParams, readFilters } from './filters.js';
import { mountShell } from './layout.js';
import { connectLive } from './sse.js';
import { renderCameras } from './streams.js';
import { renderEventsTable } from './tables.js';
import { clear, el, formatDateTime, formatNumber, setState, showToast } from './ui.js';

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
    renderCameras(document.getElementById('cameraGrid'), config.cameras || []);
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
  exportCsv.addEventListener('click', () => downloadExport('csv', exportParams(currentFilters), currentEvents));
  exportXlsx.addEventListener('click', () => downloadExport('xlsx', exportParams(currentFilters), currentEvents));

  live = connectLive({
    filters: () => currentFilters,
    onTick: () => refreshAll(),
    onError: (error) => showToast(error.message || 'Live stream failed; retrying.', 'error'),
  });
  window.addEventListener('pagehide', () => live?.stop());
  refreshAll();
}

mountShell({ active: 'dashboard', allowedRoles: ['head_admin'], pageTitle: 'Live Dashboard' })
  .then(wire)
  .catch((error) => showToast(error.message, 'error'));
