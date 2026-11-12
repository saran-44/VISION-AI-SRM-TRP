function value(form, name) {
  const field = form.elements.namedItem(name);
  return field ? String(field.value || '').trim() : '';
}

export function readFilters(form) {
  const flagged = value(form, 'flagged');
  return {
    date: value(form, 'date'),
    bus_number: value(form, 'bus_number'),
    gate: value(form, 'gate'),
    direction: value(form, 'direction'),
    flagged: flagged === '' ? '' : flagged === 'true',
    hours: Number(value(form, 'hours') || 24),
    page: Number(value(form, 'page') || 1),
    page_size: Number(value(form, 'page_size') || 8),
  };
}

export function setFormFilters(form, values = {}) {
  Object.entries(values).forEach(([name, selected]) => {
    const field = form.elements.namedItem(name);
    if (field && selected !== undefined && selected !== null) field.value = String(selected);
  });
}

export function eventParams(filters) {
  return {
    date: filters.date,
    bus_number: filters.bus_number,
    gate: filters.gate,
    direction: filters.direction,
    flagged: filters.flagged,
    page: filters.page,
    page_size: filters.page_size,
  };
}

export function exportParams(filters) {
  return {
    date: filters.date,
    bus_number: filters.bus_number,
    gate: filters.gate,
    direction: filters.direction,
    flagged: filters.flagged,
  };
}

export function analyticsParams(filters) {
  return {
    hours: filters.hours || 24,
    date: filters.date,
    bus_number: filters.bus_number,
    gate: filters.gate,
    direction: filters.direction || 'IN',
  };
}
