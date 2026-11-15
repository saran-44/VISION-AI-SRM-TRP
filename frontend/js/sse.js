import { apiGet, toQuery } from './api.js';

/** Failed reconnects in a row before the page gives up on SSE and polls. */
const RECONNECT_LIMIT = 4;
/** Base delay between reconnects; it grows linearly with the failure count. */
const RECONNECT_DELAY = 500;

export function connectLive({ onTick, onError, filters = () => ({}) } = {}) {
  let source = null;
  let pollTimer = null;
  let reconnectTimer = null;
  let stopped = false;
  let failures = 0;
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

  const openStream = () => {
    if (stopped) return;
    source = new EventSource('/api/stream');
    source.onopen = () => {
      failures = 0;
      mode = 'sse';
    };
    source.onmessage = () => {
      failures = 0;
      trigger('sse');
    };
    source.onerror = () => {
      // The server ends this stream itself after a couple of minutes — one open
      // stream holds a worker thread, and a tab that was closed is invisible
      // until the next write. So a dropped stream is expected, not a failure:
      // reconnect, and only drop to polling if the API is really unreachable.
      if (source) source.close();
      source = null;
      if (stopped) return;
      failures += 1;
      if (failures > RECONNECT_LIMIT) {
        startPolling();
        return;
      }
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        openStream();
      }, RECONNECT_DELAY * failures);
    };
  };

  if ('EventSource' in window) {
    openStream();
  } else {
    startPolling();
  }

  return {
    mode: () => mode,
    stop() {
      stopped = true;
      if (source) source.close();
      source = null;
      if (pollTimer) clearInterval(pollTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      pollTimer = null;
      reconnectTimer = null;
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
