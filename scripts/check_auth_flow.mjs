/**
 * Runtime check for the Firebase sign-out path.
 *
 * `frontend/js/auth.js` ends the Firebase session before clearing the
 * application session cookie. Getting this wrong is easy to miss: the
 * browser would keep a signed-in Firebase identity while the server had
 * already rejected the session. This script stubs just enough of the browser
 * (document, window.firebase, fetch) to run the real ES modules under Node
 * and assert the behaviour.
 *
 * Usage:  node scripts/check_auth_flow.mjs
 */
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const calls = { firebaseSignOut: 0, logoutRequests: [], scripts: [] };

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
        config: { apiKey: 'test-key', projectId: 'srmtrpai', appId: 'app-id' },
        projectId: 'srmtrpai',
        enabled: true,
        analytics: false,
      }),
    };
  }
  calls.logoutRequests.push({ url: String(url), method: options.method || 'GET' });
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};

const { signOut } = await import(path.join(ROOT, 'frontend/js/auth.js'));

// --- the test ---------------------------------------------------------------
await signOut();

assert.equal(calls.firebaseSignOut, 1, 'signOut() did not end the Firebase session');
assert.equal(calls.logoutRequests.length, 1, 'signOut() did not clear the session cookie');
assert.equal(calls.logoutRequests[0].url, '/api/auth/logout');
assert.equal(calls.logoutRequests[0].method, 'POST');
assert.ok(calls.scripts.includes('auth'), 'the Firebase Auth bundle was never loaded');

console.log('Auth flow checks passed: sign-out ends the Firebase session and clears the cookie.');
