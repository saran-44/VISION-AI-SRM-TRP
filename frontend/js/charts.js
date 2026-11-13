import { clear, setState } from './ui.js';

const charts = new Map();

function palette() {
  const styles = getComputedStyle(document.body);
  return {
    primary: styles.getPropertyValue('--primary').trim() || '#5b21b6',
    primaryLight: styles.getPropertyValue('--primary-light').trim() || 'rgba(91,33,182,.18)',
    muted: styles.getPropertyValue('--text-muted').trim() || '#6e6488',
    border: styles.getPropertyValue('--border').trim() || '#ece2f9',
    // Gold accent for bar series; the line series keeps the purple primary.
    accent: styles.getPropertyValue('--accent').trim() || '#c9a227',
    accentLight: styles.getPropertyValue('--accent-light').trim() || 'rgba(201,162,39,.18)',
  };
}

function chartState(canvas, type, message, onRetry) {
  const wrap = canvas.closest('.chart-wrap');
  const host = wrap?.querySelector('.chart-state');
  canvas.hidden = type !== 'ok';
  if (!host) return;
  clear(host);
  if (type !== 'ok') setState(host, type, message, onRetry);
}

function draw(canvasId, labels, values, label, emptyMessage) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const existing = charts.get(canvasId);
  if (existing) existing.destroy();
  charts.delete(canvasId);

  const Chart = window.Chart;
  if (!Chart) {
    chartState(canvas, 'error', 'The chart library did not load. Check your connection and refresh.');
    return;
  }
  if (!labels.length || values.every((value) => Number(value) === 0)) {
    chartState(canvas, 'empty', emptyMessage);
    return;
  }
  chartState(canvas, 'ok');

  const colors = palette();
  Chart.defaults.color = colors.muted;
  Chart.defaults.font.family = 'Inter, sans-serif';
  const type = canvasId === 'chart-hour' ? 'line' : 'bar';
  charts.set(canvasId, new Chart(canvas.getContext('2d'), {
    type,
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        borderColor: type === 'line' ? colors.primary : colors.accent,
        backgroundColor: type === 'line' ? colors.primaryLight : colors.accent,
        hoverBackgroundColor: colors.accent,
        fill: type === 'line',
        tension: .35,
        borderRadius: type === 'bar' ? 6 : 0,
        pointRadius: type === 'line' ? 3 : 0,
        maxBarThickness: 36,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context) => `${label}: ${context.parsed.y ?? context.parsed}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: colors.muted, maxRotation: 45, minRotation: 0 } },
        y: {
          beginAtZero: true,
          ticks: { precision: 0, color: colors.muted },
          grid: { color: colors.border },
        },
      },
    },
  }));
}

export function renderCharts(data) {
  const perHour = data?.per_hour || [];
  const perGate = data?.per_gate || [];
  const perBus = data?.per_bus || [];
  draw(
    'chart-hour',
    perHour.map((item) => item.label || item.hour),
    perHour.map((item) => item.count),
    'Entries per hour',
    'No entries in the selected range.',
  );
  draw(
    'chart-gate',
    perGate.map((item) => item.gate),
    perGate.map((item) => item.count),
    'Entries per gate',
    'No gate activity in the selected range.',
  );
  draw(
    'chart-bus',
    perBus.map((item) => item.bus_number),
    perBus.map((item) => item.count),
    'Entries per bus',
    'No bus activity in the selected range.',
  );
}
