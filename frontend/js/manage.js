import { apiDelete, apiGet, apiPost, apiPut, toQuery } from './api.js';
import { mountShell } from './layout.js';
import { renderBusesTable, renderDriversTable } from './tables.js';
import { el, setBusy, setState, showToast } from './ui.js';

function nullable(value) {
  const text = String(value || '').trim();
  return text ? text : null;
}

function setSubmitLabel(button, label) {
  if (!button) return;
  button.dataset.originalLabel = label;
  button.textContent = label;
}

function readBusForm(form) {
  const get = (name) => form.elements.namedItem(name)?.value ?? '';
  return {
    bus_number: get('bus_number').trim(),
    registration_number: nullable(get('registration_number')),
    route: nullable(get('route')),
    capacity: Number(get('capacity') || 40),
    insurance_expiry: nullable(get('insurance_expiry')),
    status: get('status') || 'active',
    notes: nullable(get('notes')),
  };
}

function readDriverForm(form) {
  const get = (name) => form.elements.namedItem(name)?.value ?? '';
  return {
    name: get('name').trim(),
    phone: nullable(get('phone')),
    bus_number: get('bus_number'),
    license_number: nullable(get('license_number')),
    notes: nullable(get('notes')),
    active: Boolean(form.elements.namedItem('active')?.checked),
  };
}

function fillBusForm(form, bus) {
  const set = (name, value) => { const field = form.elements.namedItem(name); if (field) field.value = value ?? ''; };
  set('id', bus.id || '');
  set('bus_number', bus.bus_number);
  set('registration_number', bus.registration_number);
  set('route', bus.route);
  set('capacity', bus.capacity ?? 40);
  set('insurance_expiry', bus.insurance_expiry);
  set('status', bus.status || 'active');
  set('notes', bus.notes);
  setSubmitLabel(document.getElementById('busSubmit'), bus.id ? 'Update Bus' : 'Save Bus');
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function fillDriverForm(form, driver) {
  const set = (name, value) => { const field = form.elements.namedItem(name); if (field) field.value = value ?? ''; };
  set('id', driver.id || '');
  set('name', driver.name);
  set('phone', driver.phone);
  set('bus_number', driver.bus_number);
  set('license_number', driver.license_number);
  set('notes', driver.notes);
  const active = form.elements.namedItem('active');
  if (active) active.checked = driver.active !== false;
  setSubmitLabel(document.getElementById('driverSubmit'), driver.id ? 'Update Driver' : 'Save Driver');
  form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function refreshBusOptions(select, buses) {
  const previous = select.value;
  select.replaceChildren(el('option', { value: '', text: 'Select a registered bus' }));
  buses.forEach((bus) => select.append(el('option', { value: bus.bus_number, text: bus.bus_number })));
  select.disabled = buses.length === 0;
  if (buses.some((bus) => bus.bus_number === previous)) select.value = previous;
}

function createRefresher({ busForm, driverForm }) {
  return async function refresh() {
    const busState = document.getElementById('manageBusesState');
    const busTable = document.getElementById('manageBusesTable');
    const driverState = document.getElementById('manageDriversState');
    const driverTable = document.getElementById('manageDriversTable');
    setState(busState, 'loading', 'Loading buses…', null, busTable);
    setState(driverState, 'loading', 'Loading drivers…', null, driverTable);
    try {
      const listQuery = toQuery({ page_size: 100 });
      const [buses, drivers] = await Promise.all([
        apiGet(`/api/buses${listQuery}`),
        apiGet(`/api/drivers${listQuery}`),
      ]);
      const busItems = buses.items || [];
      const driverItems = drivers.items || [];
      if (!busItems.length) setState(busState, 'empty', 'No buses registered yet.', null, busTable);
      else {
        setState(busState, 'ok', '', null, busTable);
        renderBusesTable(document.getElementById('manageBusesBody'), busItems, {
          editable: true,
          onEdit: (bus) => fillBusForm(busForm, bus),
          onDelete: (bus) => deleteBus(bus, refresh),
        });
      }
      if (!driverItems.length) setState(driverState, 'empty', 'No drivers registered yet.', null, driverTable);
      else {
        setState(driverState, 'ok', '', null, driverTable);
        renderDriversTable(document.getElementById('manageDriversBody'), driverItems, {
          editable: true,
          onEdit: (driver) => fillDriverForm(driverForm, driver),
          onDelete: (driver) => deleteDriver(driver, refresh),
        });
      }
      refreshBusOptions(driverForm.elements.namedItem('bus_number'), busItems);
    } catch (error) {
      setState(busState, 'error', error.message || 'Could not load records.', () => refresh(), busTable);
      setState(driverState, 'error', error.message || 'Could not load records.', () => refresh(), driverTable);
      showToast(error.message || 'Could not load records.', 'error');
    }
  };
}

async function deleteBus(bus, refresh) {
  if (!window.confirm(`Delete bus ${bus.bus_number}? This is recorded in the audit log.`)) return;
  try {
    await apiDelete(`/api/buses/${encodeURIComponent(bus.id)}`);
    showToast('Bus deleted and audited.', 'success');
    await refresh();
  } catch (error) {
    showToast(error.message || 'Delete failed.', 'error');
  }
}

async function deleteDriver(driver, refresh) {
  if (!window.confirm(`Delete driver ${driver.name}? This is recorded in the audit log.`)) return;
  try {
    await apiDelete(`/api/drivers/${encodeURIComponent(driver.id)}`);
    showToast('Driver deleted and audited.', 'success');
    await refresh();
  } catch (error) {
    showToast(error.message || 'Delete failed.', 'error');
  }
}

function wire() {
  const busForm = document.getElementById('busForm');
  const driverForm = document.getElementById('driverForm');
  const refresh = createRefresher({ busForm, driverForm });

  busForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const id = busForm.elements.namedItem('id').value;
    const submit = document.getElementById('busSubmit');
    setSubmitLabel(submit, id ? 'Update Bus' : 'Save Bus');
    setBusy(submit, true, 'Saving…');
    try {
      const body = readBusForm(busForm);
      if (id) await apiPut(`/api/buses/${encodeURIComponent(id)}`, body);
      else await apiPost('/api/buses', body);
      showToast(id ? 'Bus updated and audited.' : 'Bus added and audited.', 'success');
      setBusy(submit, false);
      busForm.reset();
      setSubmitLabel(submit, 'Save Bus');
      await refresh();
    } catch (error) {
      setBusy(submit, false);
      showToast(error.message || 'Could not save the bus.', 'error');
    }
  });

  driverForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const id = driverForm.elements.namedItem('id').value;
    const submit = document.getElementById('driverSubmit');
    setSubmitLabel(submit, id ? 'Update Driver' : 'Save Driver');
    setBusy(submit, true, 'Saving…');
    try {
      const body = readDriverForm(driverForm);
      if (id) await apiPut(`/api/drivers/${encodeURIComponent(id)}`, body);
      else await apiPost('/api/drivers', body);
      showToast(id ? 'Driver updated and audited.' : 'Driver added and audited.', 'success');
      setBusy(submit, false);
      driverForm.reset();
      setSubmitLabel(submit, 'Save Driver');
      await refresh();
    } catch (error) {
      setBusy(submit, false);
      showToast(error.message || 'Could not save the driver.', 'error');
    }
  });

  busForm.addEventListener('reset', () => setTimeout(() => {
    busForm.elements.namedItem('id').value = '';
    setSubmitLabel(document.getElementById('busSubmit'), 'Save Bus');
  }, 0));
  driverForm.addEventListener('reset', () => setTimeout(() => {
    driverForm.elements.namedItem('id').value = '';
    setSubmitLabel(document.getElementById('driverSubmit'), 'Save Driver');
  }, 0));

  document.getElementById('refreshManage').addEventListener('click', refresh);

  const params = new URLSearchParams(window.location.search);
  Promise.all([refresh()]).then(async () => {
    const editBus = params.get('edit_bus');
    const editDriver = params.get('edit_driver');
    if (editBus) {
      const { bus } = await apiGet(`/api/buses/${encodeURIComponent(editBus)}`);
      fillBusForm(busForm, bus);
    }
    if (editDriver) {
      const { driver } = await apiGet(`/api/drivers/${encodeURIComponent(editDriver)}`);
      fillDriverForm(driverForm, driver);
    }
  }).catch((error) => showToast(error.message || 'Could not load edit target.', 'error'));
}

mountShell({ active: 'manage', allowedRoles: ['transport_office'], pageTitle: 'Manage Records' })
  .then(wire)
  .catch((error) => showToast(error.message, 'error'));
