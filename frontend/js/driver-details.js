import { apiGet, toQuery } from './api.js';
import { mountShell } from './layout.js';
import { el, formatDate, setState } from './ui.js';

function kv(entries) {
  return el('ul', { class: 'kv-list' }, entries.map(([label, value]) => el('li', {}, [
    el('span', { class: 'label', text: label }),
    el('span', { class: 'value', text: value ?? '—' }),
  ])));
}

async function render(id) {
  const state = document.getElementById('detailState');
  const content = document.getElementById('detailContent');
  setState(state, 'loading', 'Loading driver and bus profile…');
  content.hidden = true;
  try {
    const { driver } = await apiGet(`/api/drivers/${encodeURIComponent(id)}`);
    const busPayload = await apiGet(`/api/buses${toQuery({ q: driver.bus_number, page_size: 1 })}`);
    const bus = (busPayload.items || [])[0] || null;
    content.replaceChildren(el('div', { class: 'detail-grid' }, [
      el('section', { class: 'card' }, [
        el('div', { class: 'card-header' }, [el('h2', { class: 'card-title', text: 'Driver information' })]),
        kv([
          ['Name', driver.name],
          ['Phone', driver.phone],
          ['Assigned bus', driver.bus_number],
          ['Licence', driver.license_number],
          ['Status', driver.active ? 'Active' : 'Inactive'],
          ['Notes', driver.notes],
        ]),
      ]),
      el('section', { class: 'card' }, [
        el('div', { class: 'card-header' }, [el('h2', { class: 'card-title', text: 'Allotted bus' })]),
        bus ? kv([
          ['Bus number', bus.bus_number],
          ['Registration', bus.registration_number],
          ['Route', bus.route],
          ['Capacity', bus.capacity],
          ['Insurance expiry', formatDate(bus.insurance_expiry)],
          ['Status', bus.status],
          ['Notes', bus.notes],
        ]) : el('p', { class: 'muted', text: 'No matching bus record is registered.' }),
      ]),
    ]));
    setState(state, 'ok');
    content.hidden = false;
  } catch (error) {
    setState(state, 'error', error.message || 'Could not load this profile.');
  }
}

function wire() {
  const params = new URLSearchParams(window.location.search);
  const id = params.get('id');
  if (!id) {
    setState(document.getElementById('detailState'), 'empty', 'Choose a driver from the Drivers page first.');
    return;
  }
  render(id);
}

mountShell({ active: 'drivers', allowedRoles: ['head_admin', 'transport_office'], pageTitle: 'Driver Details' })
  .then(wire)
  .catch(() => {});
