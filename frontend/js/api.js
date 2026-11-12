export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

export function toQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, item));
    } else {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

async function request(path, options = {}) {
  const init = { credentials: 'same-origin', ...options };
  const headers = new Headers(options.headers || {});
  if (options.body && typeof options.body !== 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  init.headers = headers;
  if (options.body && typeof options.body !== 'string') {
    init.body = JSON.stringify(options.body);
  }

  let response;
  try {
    response = await fetch(path, init);
  } catch (_error) {
    throw new ApiError('Could not reach the transport service.', 0, null);
  }

  let payload = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
  }

  const isLogin = path.includes('/api/auth/login');
  if (response.status === 401 && !isLogin && !options.skipAuthRedirect) {
    window.location.assign('/?error=session');
  }
  if (!response.ok) {
    const message = payload?.error || `Request failed with status ${response.status}.`;
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

export const apiGet = (path, options = {}) => request(path, { method: 'GET', ...options });
export const apiPost = (path, body, options = {}) => request(path, { method: 'POST', body, ...options });
export const apiPut = (path, body, options = {}) => request(path, { method: 'PUT', body, ...options });
export const apiPatch = (path, body, options = {}) => request(path, { method: 'PATCH', body, ...options });
export const apiDelete = (path, options = {}) => request(path, { method: 'DELETE', ...options });

export async function downloadFile(path, fallbackName) {
  let response;
  try {
    response = await fetch(path, { credentials: 'same-origin' });
  } catch (_error) {
    throw new ApiError('Could not reach the transport service.', 0, null);
  }
  if (!response.ok) {
    throw new ApiError(`Export failed with status ${response.status}.`, response.status, null);
  }
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
