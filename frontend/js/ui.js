export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(props).forEach(([key, value]) => {
    if (value === undefined || value === null || value === false) return;
    if (key === 'class') node.className = String(value);
    else if (key === 'text') node.textContent = String(value ?? '');
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'aria' && typeof value === 'object') {
      Object.entries(value).forEach(([ariaKey, ariaValue]) => node.setAttribute(`aria-${ariaKey}`, String(ariaValue)));
    } else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, String(value));
  });
  const list = Array.isArray(children) ? children : [children];
  list.forEach((child) => {
    if (child === undefined || child === null || child === false) return;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return node;
}

export function icon(className) {
  return el('i', { class: `bx ${className}`, 'aria-hidden': 'true' });
}

export function iconButton(label, iconClass, onClick, extraClass = '') {
  return el(
    'button',
    {
      class: `icon-btn ${extraClass}`.trim(),
      type: 'button',
      'aria-label': label,
      title: label,
      onclick: onClick,
    },
    [icon(iconClass)],
  );
}

export function actionButton(label, iconClass, onClick, extraClass = '') {
  return el(
    'button',
    {
      class: `action-btn ${extraClass}`.trim(),
      type: 'button',
      'aria-label': label,
      title: label,
      onclick: onClick,
    },
    [icon(iconClass)],
  );
}

export function clear(node) {
  if (node) node.replaceChildren();
}

export function setState(host, type, message, onRetry, tableToHide) {
  if (!host) return;
  clear(host);
  if (tableToHide) tableToHide.hidden = type !== 'ok';
  if (type === 'ok') return;
  const config = {
    loading: { icon: 'bx-loader-alt bx-spin', label: 'Loading' },
    empty: { icon: 'bx-inbox', label: 'No data' },
    error: { icon: 'bx-error-circle', label: 'Error' },
  }[type] || { icon: 'bx-info-circle', label: 'Notice' };
  const children = [
    icon(config.icon),
    el('p', { text: message, role: type === 'error' ? 'alert' : 'status' }),
  ];
  if (onRetry) {
    children.push(el('button', {
      class: 'btn btn-outline btn-sm',
      type: 'button',
      onclick: onRetry,
    }, [icon('bx-refresh'), 'Try again']));
  }
  host.append(el('div', {
    class: `state-box state-${type}`,
    'aria-label': config.label,
  }, children));
}

export function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: '2-digit' });
}

export function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : '—';
}

export function formatConfidence(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : '—';
}

export function badge(text, variant = '') {
  return el('span', { class: `status-badge ${variant}`.trim(), text: String(text ?? '—') });
}

export function busBadge(busNumber) {
  return el('div', { class: 'bus-badge' }, [icon('bx-bus'), el('span', { text: busNumber || '—' })]);
}

export function directionBadge(direction) {
  const isOut = String(direction).toUpperCase() === 'OUT';
  return el('span', { class: `status-badge ${isOut ? 'status-out' : 'status-in'}`.trim() }, [
    icon(isOut ? 'bx-up-arrow-alt' : 'bx-down-arrow-alt'),
    el('span', { text: isOut ? 'OUT' : 'IN' }),
  ]);
}

export function flagList(reasons = [], labels = {}) {
  if (!reasons.length) {
    return el('span', { class: 'flag-chip ok', text: 'Clear' });
  }
  return el('div', { class: 'flag-list' }, reasons.map((reason) => el('span', {
    class: 'flag-chip',
    title: reason,
    text: labels[reason] || reason,
  })));
}

export function showToast(message, kind = 'info') {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const toast = el('div', {
    class: `toast ${kind}`.trim(),
    role: kind === 'error' ? 'alert' : 'status',
  }, [icon(kind === 'error' ? 'bx-error-circle' : kind === 'success' ? 'bx-check-circle' : 'bx-info-circle'), el('span', { text: message })]);
  document.body.append(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 3200);
}

export function setBusy(button, busy, busyLabel = 'Working…') {
  if (!button) return;
  if (busy) {
    if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent.trim();
    button.disabled = true;
    button.replaceChildren(icon('bx-loader-alt bx-spin'), document.createTextNode(` ${busyLabel}`));
  } else {
    button.disabled = false;
    button.textContent = button.dataset.originalLabel || 'Submit';
  }
}

export function debounce(fn, delay = 250) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

export function initials(value = '') {
  return String(value)
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('') || 'TR';
}
