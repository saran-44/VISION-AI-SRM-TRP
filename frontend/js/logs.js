import { apiGet, toQuery } from './api.js';
import { downloadExport } from './exports.js';
import { eventParams, exportParams, readFilters, setFormFilters } from './filters.js';
import { mountShell } from './layout.js';
import { renderEventsTable, renderPagination } from './tables.js';
import { formatNumber, setState, showToast } from './ui.js';

let filters = {};
let events = [];
let flagLabels = {};
let timer = null;

async function refresh() {
  const state = document.getElementById('logsState');
  const table = document.getElementById('logsTable');
  setState(state, 'loading', 'Loading gate events…', null, table);
  try {
    const [payload, stats] = await Promise.all([
      apiGet(`/api/events${toQuery(eventParams(filters))}`),
      apiGet('/api/stats'),
    ]);
    flagLabels = stats.flag_labels || {};
    events = payload.items || [];
    if (!events.length) {
      setState(state, 'empty', 'No events match these filters.', null, table);
    } else {
      setState(state, 'ok', '', null, table);
      renderEventsTable(document.getElementById('logsBody'), events, flagLabels);
    }
    document.getElementById('logsSummary').textContent = `${formatNumber(payload.total)} matching events`;
    renderPagination(document.getElementById('logsPagination'), payload, (page) => {
      filters.page = page;
      document.querySelector('[name="page"]').value = String(page);
      refresh();
    });
  } catch (error) {
    setState(state, 'error', error.message || 'Could not load events.', () => refresh(), table);
    showToast(error.message || 'Could not load events.', 'error');
  }
}

function wire() {
  const form = document.getElementById('logsFilters');
  const params = new URLSearchParams(window.location.search);
  setFormFilters(form, {
    bus_number: params.get('bus_number'),
    gate: params.get('gate'),
    direction: params.get('direction'),
    date: params.get('date'),
  });
  filters = readFilters(form);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    filters = readFilters(form);
    filters.page = 1;
    form.elements.namedItem('page').value = '1';
    refresh();
  });
  form.addEventListener('reset', () => setTimeout(() => { filters = readFilters(form); refresh(); }, 0));
  document.getElementById('exportCsv').addEventListener('click', () => downloadExport('csv', exportParams(filters), events));
  document.getElementById('exportXlsx').addEventListener('click', () => downloadExport('xlsx', exportParams(filters), events));
  document.getElementById('refreshLogs').addEventListener('click', refresh);
  timer = setInterval(refresh, 15_000);
  window.addEventListener('pagehide', () => clearInterval(timer));
  refresh();
}

mountShell({ active: 'logs', allowedRoles: ['head_admin'], pageTitle: 'Live Logs' })
  .then(wire)
  .catch((error) => showToast(error.message, 'error'));
