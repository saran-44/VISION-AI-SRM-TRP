/**
 * Firebase bootstrap for the SRM TRP Transport console.
 *
 * The web configuration is fetched from the backend (`GET /api/config/firebase`)
 * rather than hard-coded, so the API key never has to live in the repository.
 * The SDK is loaded lazily from the vendored compat bundles; when Firebase is
 * not configured the module resolves to a disabled state and nothing is
 * downloaded.
 *
 * Analytics is optional and is only started when a measurement id exists and
 * the visitor has not opted out.
 */

const SDK_BASE = '/vendor/firebase/';

const SCRIPTS = {
  app: 'firebase-app-compat.js',
  analytics: 'firebase-analytics-compat.js',
  firestore: 'firebase-firestore-compat.js',
};

let loadPromise = null;
let state = {
  enabled: false,
  analytics: false,
  projectId: null,
  app: null,
  analyticsInstance: null,
  firestore: null,
  error: null,
};

function loadScript(name) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-firebase="${name}"]`);
    if (existing) {
      if (existing.dataset.loaded === 'true') {
        resolve();
        return;
      }
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () => reject(new Error(`Failed to load ${name}`)));
      return;
    }
    const script = document.createElement('script');
    script.src = `${SDK_BASE}${SCRIPTS[name]}`;
    script.async = true;
    script.dataset.firebase = name;
    script.addEventListener('load', () => {
      script.dataset.loaded = 'true';
      resolve();
    });
    script.addEventListener('error', () => reject(new Error(`Failed to load ${name}`)));
    document.head.append(script);
  });
}

async function loadSdk(needs) {
  if (!loadPromise) {
    loadPromise = (async () => {
      await loadScript('app');
      const tasks = needs.map((name) => loadScript(name));
      await Promise.all(tasks);
    })().catch((error) => {
      loadPromise = null;
      throw error;
    });
  }
  return loadPromise;
}

export function firebaseState() {
  return { ...state };
}

export function isFirebaseEnabled() {
  return state.enabled;
}

/**
 * Initialise Firebase. Safe to call on every page; it only performs work once.
 *
 * @returns {Promise<object>} the current state
 */
export async function initFirebase() {
  if (state.app) return state;
  try {
    const response = await fetch('/api/config/firebase', { credentials: 'same-origin' });
    if (!response.ok) throw new Error(`Configuration request failed (${response.status}).`);
    const payload = await response.json();
    const config = payload?.config || {};
    state.projectId = payload?.projectId || config.projectId || null;

    if (!payload?.enabled || !config.apiKey) {
      state.enabled = false;
      state.analytics = false;
      return state;
    }

    await loadSdk(payload?.analytics ? ['analytics'] : []);

    if (!window.firebase) throw new Error('The Firebase SDK did not initialise.');

    if (!window.firebase.apps.length) {
      window.firebase.initializeApp(config);
    }
    state.app = window.firebase.apps[0] || null;
    state.enabled = true;

    if (payload?.analytics && window.firebase.analytics) {
      try {
        state.analyticsInstance = window.firebase.analytics();
        state.analytics = true;
      } catch (error) {
        state.analytics = false;
        state.error = `Analytics unavailable: ${error?.message || 'unknown error'}`;
      }
    }
    return state;
  } catch (error) {
    state.enabled = false;
    state.analytics = false;
    state.error = error?.message || 'Firebase initialisation failed.';
    return state;
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
