/**
 * Firebase bootstrap for the VISION AI - SRM TRP console.
 *
 * The web configuration is fetched from the backend (`GET /api/config/firebase`)
 * rather than hard-coded, so the API key never has to live in the repository.
 * The SDK is loaded lazily from the vendored compat bundles; when Firebase is
 * not configured the module resolves to a disabled state and nothing is
 * downloaded.
 *
 * Authentication (email/password and Google) and Analytics are optional. The
 * console works without them.
 */

const SDK_BASE = '/vendor/firebase/';

const SCRIPTS = {
  app: 'firebase-app-compat.js',
  auth: 'firebase-auth-compat.js',
  analytics: 'firebase-analytics-compat.js',
  firestore: 'firebase-firestore-compat.js',
};

// Cache each bundle separately: a dashboard may start Analytics first and
// request Auth only later when the user signs out. One global promise would
// incorrectly treat that later bundle as already loaded.
const scriptPromises = new Map();
let configPromise = null;
let state = {
  enabled: false,
  analytics: false,
  auth: false,
  projectId: null,
  app: null,
  authInstance: null,
  analyticsInstance: null,
  firestore: null,
  error: null,
};

function loadScript(name) {
  if (scriptPromises.has(name)) return scriptPromises.get(name);

  const promise = new Promise((resolve, reject) => {
    let script = document.querySelector(`script[data-firebase="${name}"]`);
    if (script?.dataset.loaded === 'true') {
      resolve();
      return;
    }
    const isNew = !script;
    if (isNew) {
      script = document.createElement('script');
      script.src = `${SDK_BASE}${SCRIPTS[name]}`;
      script.async = true;
      script.dataset.firebase = name;
    }
    script.addEventListener('load', () => {
      script.dataset.loaded = 'true';
      resolve();
    });
    script.addEventListener('error', () => {
      // An errored element cannot emit another load event; remove it so a
      // later attempt can actually download the bundle again.
      script.remove();
      reject(new Error(`Failed to load ${name}`));
    });
    if (isNew) document.head.append(script);
  }).catch((error) => {
    scriptPromises.delete(name);
    throw error;
  });
  scriptPromises.set(name, promise);
  return promise;
}

async function loadSdk(needs) {
  // The compat extras depend on app, but can be loaded in parallel afterward.
  await loadScript('app');
  await Promise.all(needs.map((name) => loadScript(name)));
}

export function firebaseState() {
  return { ...state };
}

export function isFirebaseEnabled() {
  return state.enabled;
}

/**
 * Fetch the deployment's public Firebase configuration.
 *
 * The result is cached: `initFirebase` may run several times on one page
 * (the sign-in flow asks for it on every attempt) and the configuration
 * cannot change while the page is open. A failed request is not cached, so a
 * later call can still retry.
 */
async function fetchConfig() {
  if (!configPromise) {
    configPromise = fetch('/api/config/firebase', { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) throw new Error(`Configuration request failed (${response.status}).`);
        return response.json();
      })
      .catch((error) => {
        configPromise = null;
        throw error;
      });
  }
  return configPromise;
}

/**
 * Initialise Firebase. Safe to call on every page; it only performs work once.
 *
 * @param {object} [options]
 * @param {boolean} [options.auth] load the Authentication bundle as well
 * @param {boolean} [options.analytics] load the Analytics bundle as well
 * @returns {Promise<object>} the current state
 */
export async function initFirebase(options = {}) {
  try {
    const payload = await fetchConfig();
    const config = payload?.config || {};
    state.projectId = payload?.projectId || config.projectId || null;

    if (!payload?.enabled || !config.apiKey) {
      state.enabled = false;
      state.analytics = false;
      state.auth = false;
      return state;
    }

    const wantsAnalytics = options.analytics === undefined ? payload?.analytics : options.analytics;
    const wantsAuth = Boolean(options.auth);
    const extras = [];
    // The console pages start Firebase for analytics only, so the Auth bundle
    // is loaded later — when the sign-in page needs it, or when signing out.
    if (wantsAuth && !state.authInstance) extras.push('auth');
    if (wantsAnalytics && !state.analyticsInstance) extras.push('analytics');
    await loadSdk(extras);

    if (!window.firebase) throw new Error('The Firebase SDK did not initialise.');

    if (!window.firebase.apps.length) {
      window.firebase.initializeApp(config);
    }
    state.app = window.firebase.apps[0] || null;
    state.enabled = true;
    state.error = null;

    if (wantsAuth && !state.authInstance) {
      try {
        if (typeof window.firebase.auth !== 'function') throw new Error('Auth bundle unavailable');
        state.authInstance = window.firebase.auth();
      } catch (error) {
        state.error = `Authentication unavailable: ${error?.message || 'unknown error'}`;
      }
    }
    state.auth = Boolean(state.authInstance);

    if (wantsAnalytics && !state.analyticsInstance) {
      try {
        if (typeof window.firebase.analytics !== 'function') throw new Error('Analytics bundle unavailable');
        state.analyticsInstance = window.firebase.analytics();
      } catch (error) {
        state.error = `Analytics unavailable: ${error?.message || 'unknown error'}`;
      }
    }
    state.analytics = Boolean(state.analyticsInstance);
    return state;
  } catch (error) {
    state.enabled = false;
    state.analytics = false;
    state.auth = false;
    state.error = error?.message || 'Firebase initialisation failed.';
    return state;
  }
}

/**
 * End the Firebase session, if there is one.
 *
 * The console pages initialise Firebase for analytics only, so the Auth
 * bundle is loaded on demand here. Failures are swallowed deliberately: the
 * application session is cleared by the caller either way.
 *
 * @returns {Promise<boolean>} true when a Firebase session was ended
 */
export async function signOutFirebase() {
  try {
    const current = await initFirebase({ auth: true, analytics: false });
    if (!current.authInstance) return false;
    await current.authInstance.signOut();
    return true;
  } catch (_error) {
    return false;
  }
}

/**
 * Load Firestore lazily. Only needed if the deployment stores data there.
 */
export async function getFirestore() {
  if (!state.enabled) return null;
  if (state.firestore) return state.firestore;
  await loadSdk(['firestore']);
  if (!window.firebase?.firestore) return null;
  state.firestore = window.firebase.firestore();
  return state.firestore;
}

/**
 * Record a named analytics event. Silently no-ops when analytics is off.
 */
export function logEvent(name, params = {}) {
  if (!state.analyticsInstance) return false;
  try {
    state.analyticsInstance.logEvent(name, params);
    return true;
  } catch (_error) {
    return false;
  }
}

export function setCurrentScreen(name) {
  if (!state.analyticsInstance) return false;
  try {
    state.analyticsInstance.logEvent('screen_view', { screen_name: name });
    return true;
  } catch (_error) {
    return false;
  }
}

/** Convenience wrappers for the events this app cares about. */
export const analytics = {
  signIn: (method = 'password') => logEvent('login', { method }),
  signOut: () => logEvent('logout'),
  viewPage: (page) => setCurrentScreen(page),
  captureFrame: (cameraId) => logEvent('capture_frame', { camera_id: cameraId }),
  detectionResult: (busNumber, confidence) => logEvent('detection_result', {
    bus_number: busNumber || 'unknown',
    confidence: confidence ?? 0,
  }),
  exportData: (kind) => logEvent('export_data', { kind }),
};
