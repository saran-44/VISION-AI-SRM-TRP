#!/usr/bin/env node
/** Exercise the real lazy Firebase loader with a small fake browser.
 * Run: node scripts/check_firebase_loader.mjs
 * This is not a live Firebase authentication or Hosting integration test.
 */
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const moduleUrl = pathToFileURL(path.resolve('frontend/js/firebase.js')).href;

function browser({ failOnce = [] } = {}) {
  const scripts = new Map();
  const loads = [];
  const failures = new Set(failOnce);
  let signOuts = 0;
  let fetches = 0;

  global.window = {};
  global.document = {
    querySelector(selector) {
      const name = selector.match(/data-firebase="([^"]+)"/)?.[1];
      return scripts.get(name) || null;
    },
    createElement() {
      const listeners = {};
      return {
        dataset: {},
        addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
        dispatch(type) { (listeners[type] || []).forEach((fn) => fn()); },
        remove() { scripts.delete(this.dataset.firebase); },
      };
    },
    head: {
      append(element) {
        const name = element.dataset.firebase;
        loads.push(name);
        scripts.set(name, element);
        setTimeout(() => {
          if (failures.delete(name)) {
            element.dispatch('error');
            return;
          }
          if (name === 'app') {
            window.firebase = {
              apps: [],
              initializeApp(config) { this.apps.push({ config }); },
            };
          } else if (name === 'auth') {
            window.firebase.auth = () => ({ async signOut() { signOuts += 1; } });
          } else if (name === 'analytics') {
            window.firebase.analytics = () => ({ logEvent() {} });
          } else if (name === 'firestore') {
            window.firebase.firestore = () => ({ test: true });
          }
          element.dispatch('load');
        }, 0);
      },
    },
  };
  global.fetch = async () => {
    fetches += 1;
    return {
      ok: true,
      json: async () => ({
        enabled: true, analytics: true, projectId: 'test-project',
        config: { apiKey: 'test-key', projectId: 'test-project', appId: 'test-app' },
      }),
    };
  };
  return { loads, get signOuts() { return signOuts; }, get fetches() { return fetches; } };
}

// Dashboard initializes analytics; later signing out must load Auth as well.
{
  const mock = browser();
  const firebase = await import(`${moduleUrl}?analytics-first`);
  const first = await firebase.initFirebase({ analytics: true });
  assert.equal(first.analytics, true);
  assert.deepEqual(mock.loads, ['app', 'analytics']);
  assert.equal(await firebase.signOutFirebase(), true, 'Auth must load after Analytics');
  assert.deepEqual(mock.loads, ['app', 'analytics', 'auth']);
  assert.equal(mock.signOuts, 1);
  assert.deepEqual(await firebase.getFirestore(), { test: true }, 'Firestore must also load on demand');
  assert.equal(mock.fetches, 1);
}

// Two simultaneous initializations must share app loading but load both extras.
{
  const mock = browser();
  const firebase = await import(`${moduleUrl}?concurrent`);
  await Promise.all([
    firebase.initFirebase({ auth: true, analytics: false }),
    firebase.initFirebase({ auth: false, analytics: true }),
  ]);
  assert.equal(mock.loads.filter((name) => name === 'app').length, 1);
  assert.equal(mock.loads.filter((name) => name === 'auth').length, 1);
  assert.equal(mock.loads.filter((name) => name === 'analytics').length, 1);
  assert.equal(firebase.firebaseState().auth, true);
  assert.equal(firebase.firebaseState().analytics, true);
}

// A failed bundle should be removed and reloadable on a later sign-out attempt.
{
  const mock = browser({ failOnce: ['auth'] });
  const firebase = await import(`${moduleUrl}?retry`);
  assert.equal(await firebase.signOutFirebase(), false);
  assert.equal(await firebase.signOutFirebase(), true);
  assert.equal(mock.loads.filter((name) => name === 'auth').length, 2);
  assert.equal(mock.signOuts, 1);
}

// Enabling Firebase without requesting extras still initializes the app.
{
  const mock = browser();
  const firebase = await import(`${moduleUrl}?app-only`);
  const state = await firebase.initFirebase({ auth: false, analytics: false });
  assert.equal(state.enabled, true);
  assert.deepEqual(mock.loads, ['app']);
}

console.log('Firebase loader checks passed: lazy extras, concurrency, retries and app-only startup.');
