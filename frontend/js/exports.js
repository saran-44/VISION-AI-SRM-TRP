import { downloadFile, saveBlob, toQuery } from './api.js';
import { showToast } from './ui.js';

const EXPORT_FIELDS = [
  'timestamp', 'bus_number', 'direction', 'gate',
  'camera_id', 'confidence', 'flagged', 'flag_reasons',
];

function safeCell(value) {
  const text = value === undefined || value === null ? '' : String(value);
  return /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
}

function normalizeEvent(event) {
  return {
    timestamp: event.timestamp || '',
    bus_number: event.bus_number || '',
    direction: event.direction || '',
    gate: event.gate || '',
    camera_id: event.camera_id || '',
    confidence: event.confidence ?? '',
    flagged: event.flagged ? 'yes' : 'no',
    flag_reasons: (event.flag_reasons || []).join(', '),
  };
}

function csvText(rows) {
  const escape = (value) => `"${String(value).replaceAll('"', '""')}"`;
  const lines = [EXPORT_FIELDS.map(escape).join(',')];
  rows.forEach((row) => lines.push(EXPORT_FIELDS.map((field) => escape(safeCell(row[field]))).join(',')));
  return `\uFEFF${lines.join('\r\n')}`;
}

function fallbackExport(format, events, filename) {
  const rows = (events || []).map(normalizeEvent);
  if (format === 'csv') {
    saveBlob(new Blob([csvText(rows)], { type: 'text/csv;charset=utf-8' }), filename);
    return true;
  }
  const XLSX = window.XLSX;
  if (!XLSX || format !== 'xlsx') return false;
  const worksheet = XLSX.utils.json_to_sheet(
    rows.map((row) => Object.fromEntries(EXPORT_FIELDS.map((field) => [field, safeCell(row[field])]))),
    { header: EXPORT_FIELDS },
  );
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, 'Bus Events');
  XLSX.writeFile(workbook, filename);
  return true;
}

export async function downloadExport(format, filters = {}, loadedEvents = []) {
  const filename = `bus-events.${format}`;
  const query = toQuery(filters);
  try {
    await downloadFile(`/api/export/events.${format}${query}`, filename);
    showToast(`${format.toUpperCase()} export downloaded.`, 'success');
  } catch (error) {
    if (fallbackExport(format, loadedEvents, filename)) {
      showToast('Server export was unavailable; exported the loaded page data instead.', 'info');
      return;
    }
    showToast(error.message || 'Export failed.', 'error');
    throw error;
  }
}
