import { apiPost } from './api.js';
import { el, icon, setBusy } from './ui.js';
import { AuthError, authConfig, finishGoogleRedirect, signInWithGoogle, signInWithPassword } from './auth.js';

const form = document.getElementById('loginForm');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const errorBox = document.getElementById('errorMsg');
const submit = document.getElementById('loginSubmit');
const googleButton = document.getElementById('googleSignIn');
const divider = document.getElementById('loginDivider');
const legacySection = document.getElementById('legacyLoginSection');
const firebaseNote = document.getElementById('firebaseNote');
const demoNote = document.getElementById('demoNote');

/** Which password sign-in path this deployment uses. */
let mode = 'password';
let firebaseOn = false;

function showError(message) {
  errorBox.hidden = false;
  errorBox.replaceChildren(icon('bx-error-circle'), document.createTextNode(` ${message}`));
  const container = document.querySelector('.login-container');
  container.classList.remove('shake');
  void container.offsetWidth;
  container.classList.add('shake');
}

function clearError() {
  errorBox.hidden = true;
}

const params = new URLSearchParams(window.location.search);
if (params.get('error') === 'forbidden') showError('You do not have access to that page.');
if (params.get('error') === 'session') showError('Your session expired. Please sign in again.');
if (params.get('error') === 'not-authorised') {
  showError('Your email address is not authorised for the transport portal.');
}

function goToApp(role) {
  window.location.assign(role === 'head_admin' ? '/dashboard' : '/manage');
}

/* ------------------------------------------------------------------ */
/* Password sign-in                                                     */
/* ------------------------------------------------------------------ */

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearError();
  setBusy(submit, true, 'Signing in…');
  try {
    let result;
    if (firebaseOn) {
      result = await signInWithPassword(emailInput.value.trim(), passwordInput.value);
      if (!result) return; // A redirect was started; the page is navigating.
    } else {
      // The deployment has no Firebase sign-in: fall back to the local
      // account store.
      result = await apiPost('/api/auth/login', {
        email: emailInput.value.trim(),
        password: passwordInput.value,
      }, { skipAuthRedirect: true });
    }
    goToApp(result.user?.role);
  } catch (error) {
    const message = error.status === 429
      ? 'Too many sign-in attempts. Please wait and try again.'
      : error.status === 401
        ? 'Invalid email or password.'
        : error instanceof AuthError
          ? error.message
          : (error.message || 'Sign-in failed.');
    showError(message);
    setBusy(submit, false, 'Sign In to Dashboard');
  }
});

/* ------------------------------------------------------------------ */
/* Google sign-in                                                       */
/* ------------------------------------------------------------------ */

if (googleButton) {
  googleButton.addEventListener('click', async () => {
    clearError();
    setBusy(googleButton, true, 'Opening Google…');
    try {
      const result = await signInWithGoogle();
      if (!result) return; // A redirect was started.
      goToApp(result.user?.role);
    } catch (error) {
      showError(error instanceof AuthError ? error.message : (error.message || 'Google sign-in failed.'));
    } finally {
      setBusy(googleButton, false, 'Sign in with Google');
    }
  });
}

/* ------------------------------------------------------------------ */
/* Which sign-in methods to offer                                      */
/* ------------------------------------------------------------------ */

(async function configureLogin() {
  const config = await authConfig();
  firebaseOn = Boolean(config.firebase?.enabled);
  mode = firebaseOn ? 'firebase' : 'password';

  // The test bench signs in with the seeded account "admin" / "admin". This
  // form is shared with production, whose browser validation would reject
  // both: the field is type="email" (bare username) and the password needs
  // eight characters. Only the input constraints change here; the server still
  // validates every credential and demo mode cannot run in production.
  const demoOn = Boolean(config.demo_mode);
  if (demoOn) {
    emailInput.type = 'text';
    emailInput.setAttribute('autocapitalize', 'none');
    emailInput.setAttribute('spellcheck', 'false');
    emailInput.placeholder = 'admin';
    passwordInput.minLength = 1;
    if (demoNote) demoNote.hidden = false;
  }

  const googleAllowed = (config.firebase?.providers || []).includes('google.com');
  if (googleButton) {
    googleButton.hidden = !firebaseOn || !googleAllowed;
  }

  // The divider only makes sense between the form and the Google button.
  if (divider) {
    divider.hidden = !googleButton || googleButton.hidden;
  }

  if (firebaseNote) {
    firebaseNote.hidden = !firebaseOn;
  }

  // The legacy local-password form stays available as a break-glass path
  // unless the deployment disables it explicitly.
  const legacyAllowed = config.legacy_password_login !== false;
  if (legacySection) {
    legacySection.hidden = !legacyAllowed;
  }

  if (!legacyAllowed && !firebaseOn && !demoOn) {
    showError('No sign-in method is enabled on this deployment.');
  }

  // In demo mode the local demo account is always the sign-in path, even when
  // the deployment has local passwords turned off.
  if (demoOn && legacySection) {
    legacySection.hidden = true;
  }

  // A popup-blocked fallback navigates back here. Firebase must consume its
  // redirect result and exchange the returned ID token for the portal cookie.
  if (firebaseOn && googleAllowed) {
    try {
      const result = await finishGoogleRedirect();
      if (result) goToApp(result.user?.role);
    } catch (error) {
      showError(error instanceof AuthError ? error.message : (error.message || 'Google sign-in failed.'));
    }
  }
})();
