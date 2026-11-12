import { apiPost } from './api.js';
import { el, icon, setBusy } from './ui.js';

const form = document.getElementById('loginForm');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const errorBox = document.getElementById('errorMsg');
const submit = document.getElementById('loginSubmit');

function showError(message) {
  errorBox.hidden = false;
  errorBox.replaceChildren(icon('bx-error-circle'), document.createTextNode(` ${message}`));
  const container = document.querySelector('.login-container');
  container.classList.remove('shake');
  void container.offsetWidth;
  container.classList.add('shake');
}

const params = new URLSearchParams(window.location.search);
if (params.get('error') === 'forbidden') showError('You do not have access to that page.');
if (params.get('error') === 'session') showError('Your session expired. Please sign in again.');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  setBusy(submit, true, 'Signing in…');
  try {
    const result = await apiPost('/api/auth/login', {
      email: emailInput.value.trim(),
      password: passwordInput.value,
    }, { skipAuthRedirect: true });
    const role = result.user?.role;
    window.location.assign(role === 'head_admin' ? '/dashboard' : '/manage');
  } catch (error) {
    const message = error.status === 429
      ? 'Too many sign-in attempts. Please wait and try again.'
      : error.status === 401
        ? 'Invalid email or password.'
        : error.message || 'Sign-in failed.';
    showError(message);
    setBusy(submit, false, 'Sign In to Dashboard');
  }
});
