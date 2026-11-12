import { apiGet, toQuery } from './api.js';
import { mountShell } from './layout.js';
import { renderDriversTable, renderPagination } from './tables.js';
import { formatNumber, setState, showToast } from './ui.js';

let filters = { q: '', page: 1, page_size: 25 };

async function refresh() {
  const state = document.getElementById('driversState');
  const table = document.getElementById('driversTable');
  setState(state, 'loading', 'Loading driver records…', null, table);
  try {
    const payload = await apiGet(`/api/drivers${toQuery(filters)}`);
    const drivers = payload.items || [];
    if (!drivers.length) {
      setState(state, 'empty', 'No driver records match this search.', null, table);
    } else {
      setState(state, 'ok', '', null, table);
      renderDriversTable(document.getElementById('driversBody'), drivers);
    }
    document.getElementById('driversSummary').textContent = `${formatNumber(payload.total)} drivers`;
    renderPagination(document.getElementById('driversPagination'), payload, (page) => {
      filters.page = page;
      document.querySelector('#driverSearchForm [name="page"]').value = String(page);
      refresh();
    });
  } catch (error) {
    setState(state, 'error', error.message || 'Could not load drivers.', () => refresh(), table);
    showToast(error.message || 'Could not load drivers.', 'error');
  }
}

function wire(user) {
  const form = document.getElementById('driverSearchForm');
  const params = new URLSearchParams(window.location.search);
  const initial = params.get('q') || params.get('bus_number') || '';
  form.elements.namedItem('q').value = initial;
  filters.q = initial;
  if (user.role === 'transport_office') document.getElementById('manageLink').hidden = false;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    filters = { q: form.elements.namedItem('q').value.trim(), page: 1, page_size: 25 };
    form.elements.namedItem('page').value = '1';
    refresh();
  });
  document.getElementById('refreshDrivers').addEventListener('click', refresh);
  refresh();
}

mountShell({ active: 'drivers', allowedRoles: ['head_admin', 'transport_office'], pageTitle: 'Drivers' })
  .then(({ user }) => wire(user))
  .catch((error) => showToast(error.message, 'error'));
