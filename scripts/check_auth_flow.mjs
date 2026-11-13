/**
 * Runtime checks for Firebase sign-out and Google redirect completion.
 *
 * The real ES module runs against a small fake browser and Firebase SDK. The
 * checks verify both sign-out requests and the redirect ID-token exchange;
 * they do not exercise a live Firebase project or real browser OAuth.
 *
 * Usage:  node scripts/check_auth_flow.mjs
 */
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const calls = { firebaseSignOut: 0, logoutRequests: [], exchanges: [], scripts: [] };
let redirectResult = null;
let rejectExchange = false;

// --- fake DOM ---------------------------------------------------------------
function makeElement() {
  const listeners = {};
  return {
    dataset: {},
    addEventListener(type, fn) {
      (listeners[type] ||= []).push(fn);
    },
    dispatch(type) {
      (listeners[type] || []).forEach((fn) => fn());
    },
  };
}

global.document = {
  querySelector: () => null,
  createElement: () => makeElement(),
  head: {
    append(el) {
      calls.scripts.push(el.dataset.firebase || el.src);
      setTimeout(() => el.dispatch('load'), 0); // the bundle "downloads"
    },
  },
};

// --- fake Firebase SDK ------------------------------------------------------
global.window = {
  firebase: {
    apps: [],
    initializeApp(config) {
      global.window.firebase.apps.push({ config });
    },
    auth() {
      return {
        async signOut() {
          calls.firebaseSignOut += 1;
        },
        async getRedirectResult() {
          return redirectResult;
        },
      };
    },
  },
};

// --- fake fetch -------------------------------------------------------------
global.fetch = async (url, options = {}) => {
  if (String(url).includes('/api/config/firebase')) {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        config: { apiKey: 'test-key', projectId: 'vision-ai-srmtrp', appId: 'app-id' },
        projectId: 'vision-ai-srmtrp',
        enabled: true,
        analytics: false,
      }),
    };
  }
  if (String(url) === '/api/auth/firebase') {
    calls.exchanges.push({ method: options.method, body: JSON.parse(options.body) });
    return rejectExchange
      ? { ok: false, status: 403, json: async () => ({ error: 'Not authorised.' }) }
      : { ok: true, status: 200, json: async () => ({ user: { role: 'head_admin' } }) };
  }
  calls.logoutRequests.push({ url: String(url), method: options.method || 'GET' });
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};

const { signOut, finishGoogleRedirect } = await import(path.join(ROOT, 'frontend/js/auth.js'));

// --- the test ---------------------------------------------------------------
await signOut();

assert.equal(calls.firebaseSignOut, 1, 'signOut() did not end the Firebase session');
assert.equal(calls.logoutRequests.length, 1, 'signOut() did not clear the session cookie');
assert.equal(calls.logoutRequests[0].url, '/api/auth/logout');
assert.equal(calls.logoutRequests[0].method, 'POST');
assert.ok(calls.scripts.includes('auth'), 'the Firebase Auth bundle was never loaded');

assert.equal(await finishGoogleRedirect(), null, 'no redirect should not create a session');
redirectResult = { user: { getIdToken: async () => 'redirect-token' } };
assert.deepEqual(await finishGoogleRedirect(), { user: { role: 'head_admin' } });
assert.deepEqual(calls.exchanges[0], { method: 'POST', body: { id_token: 'redirect-token' } });
rejectExchange = true;
await assert.rejects(finishGoogleRedirect(), (error) => error.code === 'auth/not-authorised');

console.log('Auth flow checks passed: sign-out and Google redirect token exchange.');
