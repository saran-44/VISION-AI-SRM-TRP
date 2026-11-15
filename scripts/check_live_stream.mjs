#!/usr/bin/env node
/**
 * Behaviour check for the live dashboard connection (frontend/js/sse.js).
 *
 * `/api/stream` now ends on its own after a couple of minutes: every open
 * stream holds one gunicorn thread, and a tab that was closed is not noticed
 * until the next write — with a free instance that used to take the whole
 * portal down. The browser side therefore has to reconnect rather than treat
 * the close as "the API is down", or every dashboard silently degrades to
 * 10-second polling. That is what this script pins down.
 *
 * Run: node scripts/check_live_stream.mjs
 */
import assert from 'node:assert/strict';

const created = [];

class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.closed = false;
    created.push(this);
  }

  close() {
    this.closed = true;
  }
}

globalThis.window = { EventSource: FakeEventSource };
globalThis.EventSource = FakeEventSource;

const { connectLive } = await import(
  new URL('../frontend/js/sse.js', import.meta.url).href
);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const ticks = [];
const live = connectLive({ onTick: (info) => ticks.push(info) });

assert.equal(created.length, 1, 'the page should open /api/stream on load');
assert.equal(created[0].url, '/api/stream');
assert.equal(live.mode(), 'sse');

created[0].onopen();
created[0].onmessage({ data: '{"type":"tick"}' });
await sleep(0);
assert.equal(ticks.length, 1, 'a message should reach onTick');
assert.equal(ticks[0].mode, 'sse');

// 1. The server ends the stream on purpose: one error, then a reconnect.
created[0].onerror();
assert.equal(created[0].closed, true, 'the dead stream should be closed');
await sleep(800);
assert.equal(created.length, 2, 'the page should reconnect after a stream ends');
assert.equal(live.mode(), 'sse', 'it must stay on SSE, not fall back to polling');

// 2. A reconnect that works resets the failure count.
created[1].onopen();
created[1].onmessage({ data: '{"type":"tick"}' });
await sleep(0);
assert.equal(ticks.length, 2);

// 3. Repeated failures do fall back to polling, so a real outage still shows data.
const beforeOutage = ticks.length;
let delay = 0;
for (let attempt = 0; attempt < 5; attempt += 1) {
  const current = created[created.length - 1];
  current.onerror();
  delay += 500;
  await sleep(delay + 200);
}
assert.equal(live.mode(), 'poll', 'after repeated failures it should poll');
assert.ok(
  ticks.length > beforeOutage,
  'the switch to polling should fetch fresh data straight away',
);

// 4. stop() must leave no timer behind.
live.stop();
const afterStop = ticks.length;
await sleep(1200);
assert.equal(ticks.length, afterStop, 'stop() should silence the connection');

console.log(`live stream: ok (${created.length} connections, ${ticks.length} ticks)`);
