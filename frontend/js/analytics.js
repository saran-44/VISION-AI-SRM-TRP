import { apiGet, toQuery } from './api.js';
import { renderCharts } from './charts.js';
import { analyticsParams, readFilters, setFormFilters } from './filters.js';
import { mountShell } from './layout.js';
import { formatNumber, setState, showToast } from './ui.js';

function setChartState(type, message) {
  document.querySelectorAll('.chart-state').forEach((host) => setState(host, type, message));
  document.querySelectorAll('.chart-wrap canvas').forEach((canvas) => { canvas.hidden = type !== 'ok'; });
}

async function refresh() {
  const form = document.getElementById('analyticsFilters');
  const filters = readFilters(form);
  setChartState('loading', 'Loading analytics…');
  try {
    const data = await apiGet(`/api/analytics${toQuery(analyticsParams(filters))}`);
    const totals = data.totals || {};
    document.getElementById('analyticsSummary').textContent =
      `${formatNumber(totals.events)} ${data.direction} events · ${formatNumber(totals.gates)} gates · ${formatNumber(totals.buses)} buses`;
    setChartState('ok');
    renderCharts(data);
  } catch (error) {
    setChartState('error', error.message || 'Could not load analytics.');
    showToast(error.message || 'Could not load analytics.', 'error');
  }
}

function wire() {
  const form = document.getElementById('analyticsFilters');
  const params = new URLSearchParams(window.location.search);
  setFormFilters(form, {
    bus_number: params.get('bus_number'),
    gate: params.get('gate'),
    hours: params.get('hours'),
  });
  form.addEventListener('submit', (event) => { event.preventDefault(); refresh(); });
  form.addEventListener('reset', () => setTimeout(refresh, 0));
  document.getElementById('refreshAnalytics').addEventListener('click', refresh);
  refresh();
}

mountShell({ active: 'analytics', allowedRoles: ['head_admin'], pageTitle: 'Analytics' })
  .then(wire)
  .catch((error) => showToast(error.message, 'error'));
