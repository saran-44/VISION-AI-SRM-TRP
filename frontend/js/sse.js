import { apiGet, toQuery } from './api.js';

export function connectLive({ onTick, onError, filters = () => ({}) } = {}) {
  let source = null;
  let pollTimer = null;
  let stopped = false;
  let mode = 'sse';

  const trigger = async (reason) => {
    if (stopped) return;
    try {
      await onTick({ reason, mode, filters: filters() });
    } catch (error) {
      onError?.(error);
    }
  };

  const startPolling = () => {
    if (pollTimer || stopped) return;
    mode = 'poll';
    trigger('poll-start');
    pollTimer = setInterval(() => trigger('poll'), 10_000);
  };

  if ('EventSource' in window) {
    source = new EventSource('/api/stream');
    source.onmessage = () => trigger('sse');
    source.onerror = () => {
      if (source) source.close();
      source = null;
      startPolling();
    };
  } else {
    startPolling();
  }

  return {
    mode: () => mode,
    stop() {
      stopped = true;
      if (source) source.close();
      if (pollTimer) clearInterval(pollTimer);
    },
  };
}

export async function fetchLiveSnapshot(filters = {}) {
  const eventParams = {
    date: filters.date,
    bus_number: filters.bus_number,
    gate: filters.gate,
    direction: filters.direction,
    flagged: filters.flagged,
    page: filters.page,
    page_size: filters.page_size,
  };
  const analyticsParams = {
    hours: filters.hours,
    date: filters.date,
    bus_number: filters.bus_number,
    gate: filters.gate,
    direction: filters.direction || 'IN',
  };
  const [stats, events, analytics] = await Promise.all([
    apiGet('/api/stats'),
    apiGet(`/api/events${toQuery(eventParams)}`),
    apiGet(`/api/analytics${toQuery(analyticsParams)}`),
  ]);
  return { stats, events, analytics };
}
