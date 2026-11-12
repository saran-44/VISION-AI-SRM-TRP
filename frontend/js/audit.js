import { apiGet, toQuery } from './api.js';
import { mountShell } from './layout.js';
import { renderAuditTable, renderPagination } from './tables.js';
import { formatNumber, setState, showToast } from './ui.js';

let filters = { q: '', page: 1, page_size: 25 };

async function refresh() {
  const state = document.getElementById('auditState');
  const table = document.getElementById('auditTable');
  setState(state, 'loading', 'Loading audit entries…', null, table);
  try {
    const payload = await apiGet(`/api/audit${toQuery(filters)}`);
    const logs = payload.items || [];
    if (!logs.length) {
      setState(state, 'empty', 'No audit entries match this search.', null, table);
    } else {
      setState(state, 'ok', '', null, table);
      renderAuditTable(document.getElementById('auditBody'), logs);
    }
    document.getElementById('auditSummary').textContent = `${formatNumber(payload.total)} audit entries`;
    renderPagination(document.getElementById('auditPagination'), payload, (page) => {
      filters.page = page;
      document.querySelector('#auditSearchForm [name="page"]').value = String(page);
      refresh();
    });
  } catch (error) {
    setState(state, 'error', error.message || 'Could not load audit log.', () => refresh(), table);
    showToast(error.message || 'Could not load audit log.', 'error');
  }
}

function wire() {
  const form = document.getElementById('auditSearchForm');
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    filters = { q: form.elements.namedItem('q').value.trim(), page: 1, page_size: 25 };
    form.elements.namedItem('page').value = '1';
    refresh();
  });
  document.getElementById('refreshAudit').addEventListener('click', refresh);
  refresh();
}

mountShell({ active: 'audit', allowedRoles: ['head_admin'], pageTitle: 'Audit Log' })
  .then(wire)
  .catch((error) => showToast(error.message, 'error'));
