import {
  actionButton, badge, busBadge, clear, directionBadge, el, flagList, formatConfidence,
  formatDate, formatDateTime, setState,
} from './ui.js';

export function showDetailsModal(title, entries = [], rawText = '') {
  const overlay = el('div', {
    class: 'modal-overlay active',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': title,
    onclick: (event) => { if (event.target === overlay) overlay.remove(); },
  });
  const close = actionButton('Close details', 'bx-x', () => overlay.remove(), 'modal-close');
  const list = el('ul', { class: 'kv-list' }, entries.map(([label, value]) => el('li', {}, [
    el('span', { class: 'label', text: label }),
    el('span', { class: 'value', text: value ?? '—' }),
  ])));
  const children = [
    el('div', { class: 'modal-header' }, [
      el('h2', { class: 'modal-title' }, [el('span', { text: title })]),
      close,
    ]),
    list,
  ];
  if (rawText) children.push(el('pre', {
    class: 'input-group',
    style: 'white-space: pre-wrap; overflow: auto; max-height: 320px; text-align: left;',
    text: rawText,
  }));
  overlay.append(el('div', { class: 'modal-content' }, children));
  document.body.append(overlay);
  const onKey = (event) => {
    if (event.key === 'Escape') {
      overlay.remove();
      document.removeEventListener('keydown', onKey);
    }
  };
  document.addEventListener('keydown', onKey);
}

export function renderEventsTable(tbody, events, flagLabels = {}) {
  clear(tbody);
  events.forEach((event) => {
    const view = actionButton(
      `View event for ${event.bus_number || 'unknown bus'}`,
      'bx-show',
      () => showDetailsModal('Event details', [
        ['Event ID', event.id],
        ['Timestamp', formatDateTime(event.timestamp)],
        ['Bus number', event.bus_number],
        ['Direction', event.direction],
        ['Gate', event.gate],
        ['Camera', event.camera_id],
        ['Confidence', formatConfidence(event.confidence)],
        ['Flagged', event.flagged ? 'Yes' : 'No'],
        ['Reasons', (event.flag_reasons || []).map((reason) => flagLabels[reason] || reason).join(', ') || 'None'],
        ['Source', event.source],
      ]),
    );
    tbody.append(el('tr', {}, [
      el('td', { text: formatDateTime(event.timestamp) }),
      el('td', {}, [busBadge(event.bus_number)]),
      el('td', {}, [directionBadge(event.direction)]),
      el('td', { text: event.gate || '—' }),
      el('td', { text: event.camera_id || '—' }),
      el('td', { text: formatConfidence(event.confidence) }),
      el('td', {}, [flagList(event.flag_reasons || [], flagLabels)]),
      el('td', {}, [view]),
    ]));
  });
}

export function renderDriversTable(tbody, drivers, options = {}) {
  clear(tbody);
  const { editable = false, onEdit, onDelete } = options;
  drivers.forEach((driver) => {
    const buttons = [];
    if (editable) {
      buttons.push(actionButton(`Edit ${driver.name}`, 'bx-edit-alt', () => onEdit?.(driver)));
      buttons.push(actionButton(`Delete ${driver.name}`, 'bx-trash', () => onDelete?.(driver), 'btn-danger'));
    } else {
      buttons.push(actionButton(`View ${driver.name}`, 'bx-show', () => showDetailsModal('Driver details', [
        ['Name', driver.name],
        ['Phone', driver.phone],
        ['Bus number', driver.bus_number],
        ['Licence', driver.license_number],
        ['Status', driver.active ? 'Active' : 'Inactive'],
        ['Notes', driver.notes],
      ])));
      buttons.push(el('a', {
        class: 'action-btn',
        href: `/driver-details?id=${encodeURIComponent(driver.id)}`,
        'aria-label': `Open full profile for ${driver.name}`,
        title: 'Open full profile',
      }, [el('i', { class: 'bx bx-link-external', 'aria-hidden': 'true' })]));
    }
    tbody.append(el('tr', {}, [
      el('td', {}, [el('div', { class: 'driver-cell' }, [
        el('div', { class: 'profile-avatar', 'aria-hidden': 'true', text: (driver.name || 'DD').slice(0, 2).toUpperCase() }),
        el('span', { text: driver.name || '—' }),
      ])]),
      el('td', { text: driver.phone || '—' }),
      el('td', {}, [busBadge(driver.bus_number)]),
      el('td', { text: driver.license_number || '—' }),
      el('td', {}, [badge(driver.active ? 'Active' : 'Inactive', driver.active ? 'status-in' : 'status-out')]),
      el('td', {}, [el('div', { class: 'table-actions' }, buttons)]),
    ]));
  });
}

export function renderBusesTable(tbody, buses, options = {}) {
  clear(tbody);
  const { editable = false, onEdit, onDelete } = options;
  buses.forEach((bus) => {
    const buttons = [];
    if (editable) {
      buttons.push(actionButton(`Edit bus ${bus.bus_number}`, 'bx-edit-alt', () => onEdit?.(bus)));
      buttons.push(actionButton(`Delete bus ${bus.bus_number}`, 'bx-trash', () => onDelete?.(bus), 'btn-danger'));
    } else {
      buttons.push(actionButton(`View bus ${bus.bus_number}`, 'bx-show', () => showDetailsModal('Bus details', [
        ['Bus number', bus.bus_number],
        ['Registration', bus.registration_number],
        ['Route', bus.route],
        ['Capacity', bus.capacity],
        ['Insurance expiry', formatDate(bus.insurance_expiry)],
        ['Status', bus.status],
        ['Notes', bus.notes],
      ])));
    }
    tbody.append(el('tr', {}, [
      el('td', {}, [busBadge(bus.bus_number)]),
      el('td', { text: bus.registration_number || '—' }),
      el('td', { text: bus.route || '—' }),
      el('td', { text: bus.capacity ?? '—' }),
      el('td', { text: formatDate(bus.insurance_expiry) }),
      el('td', {}, [badge(bus.status || 'active', bus.status === 'active' ? 'status-in' : 'status-out')]),
      el('td', {}, [el('div', { class: 'table-actions' }, buttons)]),
    ]));
  });
}

export function renderAuditTable(tbody, logs) {
  clear(tbody);
  logs.forEach((log) => {
    const details = actionButton(`View audit entry ${log.id}`, 'bx-show', () => showDetailsModal(
      'Audit entry',
      [
        ['Time', formatDateTime(log.timestamp)],
        ['Actor', log.actor],
        ['Role', log.role],
        ['Action', log.action],
        ['Collection', log.collection],
        ['Record ID', log.record_id],
        ['IP address', log.ip],
      ],
      JSON.stringify({ before: log.before || null, after: log.after || null }, null, 2),
    ));
    tbody.append(el('tr', {}, [
      el('td', { text: formatDateTime(log.timestamp) }),
      el('td', { text: log.actor || '—' }),
      el('td', { text: log.role || '—' }),
      el('td', {}, [badge(log.action || '—')]),
      el('td', { text: log.collection || '—' }),
      el('td', { text: log.record_id || '—' }),
      el('td', {}, [details]),
    ]));
  });
}

export function renderPagination(host, meta, onPage) {
  clear(host);
  if (!meta || !meta.total) return;
  const prev = el('button', {
    class: 'btn btn-outline btn-sm',
    type: 'button',
    'aria-label': 'Previous page',
    disabled: meta.page <= 1,
    onclick: () => onPage(meta.page - 1),
  }, ['Previous']);
  const next = el('button', {
    class: 'btn btn-outline btn-sm',
    type: 'button',
    'aria-label': 'Next page',
    disabled: meta.page >= meta.pages,
    onclick: () => onPage(meta.page + 1),
  }, ['Next']);
  host.append(el('div', { class: 'pagination' }, [
    prev,
    el('span', { text: `Page ${meta.page} of ${meta.pages} · ${meta.total} records` }),
    next,
  ]));
}
