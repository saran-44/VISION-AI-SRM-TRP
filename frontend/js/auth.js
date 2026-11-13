/**
 * Sign-in for the SRM TRP Transport console.
 *
 * The browser authenticates with Firebase (email/password or Google) and then
 * exchanges the resulting **Firebase ID token** for this application's own
 * session cookie via `POST /api/auth/firebase`. The application does not
 * persist the exchanged ID token; Firebase manages its own browser auth state.
 * The backend-issued session cookie is HttpOnly and not readable by JavaScript.
 *
 * Firebase validates the credential; the backend requires a verified email
 * and enforces the access list. An unknown password user additionally needs
 * an administrator-set approval claim for optional auto-provisioning. Google
 * users must already be on the access list.
 */

import { initFirebase, signOutFirebase } from './firebase.js';

export class AuthError extends Error {
  constructor(message, code = 'auth/unknown') {
    super(message);
    this.name = 'AuthError';
    this.code = code;
  }
}

const FIREBASE_ERRORS = {
  'auth/invalid-email': 'That email address is not valid.',
  'auth/user-disabled': 'This account has been disabled.',
  'auth/user-not-found': 'No account exists for that email address.',
  'auth/wrong-password': 'That email or password is incorrect.',
  'auth/invalid-credential': 'That email or password is incorrect.',
  'auth/invalid-login-credentials': 'That email or password is incorrect.',
  'auth/too-many-requests': 'Too many attempts. Please wait a moment and try again.',
  'auth/network-request-failed': 'Could not reach the authentication service. Check your connection.',
  'auth/popup-closed-by-user': 'The Google sign-in window was closed before finishing.',
  'auth/popup-blocked': 'The Google sign-in window was blocked. Allow pop-ups and try again.',
  'auth/operation-not-allowed': 'This sign-in method is not enabled in the Firebase console.',
  'auth/account-exists-with-different-credential': 'That email is registered with a different sign-in method.',
  'auth/unauthorized-domain': 'This domain is not authorised for sign-in in the Firebase console.',
};

function friendlyError(error) {
  const code = error?.code || 'auth/unknown';
  if (FIREBASE_ERRORS[code]) return new AuthError(FIREBASE_ERRORS[code], code);
  if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') {
    return new AuthError('The Google sign-in window was closed before finishing.', code);
  }
  return new AuthError(
    error?.message || 'Sign-in failed. Please try again.',
    code,
  );
}

async function getAuth() {
  const state = await initFirebase({ auth: true, analytics: false });
  if (!state.enabled || !state.authInstance) {
    throw new AuthError(
      'Sign-in with Firebase is not available on this deployment.',
      'auth/disabled',
    );
  }
  return state.authInstance;
}

/** Exchange a Firebase ID token for the application's session cookie. */
async function exchangeToken(idToken) {
  const response = await fetch('/api/auth/firebase', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id_token: idToken }),
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }

  if (!response.ok) {
    const message = payload?.error || 'Sign-in was refused.';
    throw new AuthError(message, response.status === 403 ? 'auth/not-authorised' : 'auth/rejected');
  }
  return payload;
}

/**
 * Sign in with an email address and password.
 *
 * @param {string} email
 * @param {string} password
 */
export async function signInWithPassword(email, password) {
  const auth = await getAuth();
  let credential;
  try {
    credential = await auth.signInWithEmailAndPassword(email.trim(), password);
  } catch (error) {
    throw friendlyError(error);
  }
  return exchangeToken(await credential.user.getIdToken());
}

/**
 * Sign in with a Google account.
 *
 * The popup is opened directly from the click handler so browsers do not
 * block it. A redirect fallback is used if the popup is unavailable.
 */
export async function signInWithGoogle() {
  const auth = await getAuth();
  const provider = new window.firebase.auth.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: 'select_account' });

  try {
    const credential = await auth.signInWithPopup(provider);
    return exchangeToken(await credential.user.getIdToken());
  } catch (error) {
    const friendly = friendlyError(error);
    // A popup that could not be opened at all is worth one retry through the
    // redirect flow, which never gets blocked.
    if (friendly.code === 'auth/popup-blocked') {
      await auth.signInWithRedirect(provider);
      return null; // The page navigates away; the session is set on return.
    }
    throw friendly;
  }
}

/** Sign out of Firebase and clear the application session cookie. */
export async function signOut() {
  // The Firebase session is ended first so the browser does not keep a
  // signed-in identity that the server has already rejected.
  await signOutFirebase();
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      credentials: 'same-origin',
    });
  } catch (_error) {
    // Nothing more to do — the cookie expires on its own.
  }
}

/**
 * Read the deployment's sign-in capabilities.
 *
 * @returns {Promise<{mode:string, firebase:object, legacy_password_login:boolean}>}
 */
export async function authConfig() {
  const fallback = {
    mode: 'password',
    firebase: { enabled: false, providers: [], auto_provision: false },
    legacy_password_login: true,
  };
  try {
    const response = await fetch('/api/auth/config', { credentials: 'same-origin' });
    if (!response.ok) return fallback;
    return { ...fallback, ...(await response.json()) };
  } catch (_error) {
    return fallback;
  }
}
