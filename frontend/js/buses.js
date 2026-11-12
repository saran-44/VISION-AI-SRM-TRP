import { apiGet, toQuery } from './api.js';
import { mountShell } from './layout.js';
import { renderBusesTable, renderPagination } from './tables.js';
import { formatNumber, setState, showToast } from './ui.js';

let filters = { q: '', page: 1, page_size: 25 };

async function refresh() {
  const state = document.getElementById('busesState');
  const table = document.getElementById('busesTable');
  setState(state, 'loading', 'Loading bus records…', null, table);
  try {
    const payload = await apiGet(`/api/buses${toQuery(filters)}`);
    const buses = payload.items || [];
    if (!buses.length) {
      setState(state, 'empty', 'No bus records match this search.', null, table);
    } else {
      setState(state, 'ok', '', null, table);
      renderBusesTable(document.getElementById('busesBody'), buses);
    }
    document.getElementById('busesSummary').textContent = `${formatNumber(payload.total)} buses`;
    renderPagination(document.getElementById('busesPagination'), payload, (page) => {
      filters.page = page;
      document.querySelector('#busSearchForm [name="page"]').value = String(page);
      refresh();
    });
  } catch (error) {
    setState(state, 'error', error.message || 'Could not load buses.', () => refresh(), table);
    showToast(error.message || 'Could not load buses.', 'error');
  }
}

function wire(user) {
  const form = document.getElementById('busSearchForm');
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
  document.getElementById('refreshBuses').addEventListener('click', refresh);
  refresh();
}

mountShell({ active: 'buses', allowedRoles: ['head_admin', 'transport_office'], pageTitle: 'Buses' })
  .then(({ user }) => wire(user))
  .catch((error) => showToast(error.message, 'error'));
