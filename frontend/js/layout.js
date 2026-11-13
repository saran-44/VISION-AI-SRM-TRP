import { apiGet, apiPost, toQuery } from './api.js';
import { actionButton, clear, el, icon, iconButton, initials, setState, showToast } from './ui.js';
import { initFirebase, logEvent, signOutFirebase } from './firebase.js';

const NAV = {
  head_admin: [
    { id: 'dashboard', label: 'Dashboard', href: '/dashboard', icon: 'bx-grid-alt' },
    { id: 'logs', label: 'Live Logs', href: '/logs', icon: 'bx-list-ul' },
    { id: 'analytics', label: 'Analytics', href: '/analytics', icon: 'bx-bar-chart-alt-2' },
    { id: 'drivers', label: 'Drivers', href: '/drivers', icon: 'bx-group' },
    { id: 'buses', label: 'Buses', href: '/buses', icon: 'bx-bus-school' },
    { id: 'audit', label: 'Audit Log', href: '/audit', icon: 'bx-history' },
  ],
  transport_office: [
    { id: 'manage', label: 'Manage Records', href: '/manage', icon: 'bx-plus-circle' },
    { id: 'drivers', label: 'Drivers', href: '/drivers', icon: 'bx-group' },
    { id: 'buses', label: 'Buses', href: '/buses', icon: 'bx-bus-school' },
  ],
};

const ROLE_LABELS = {
  head_admin: 'Head Admin',
  transport_office: 'Transport Office',
};

function applyTheme() {
  const saved = localStorage.getItem('transport-theme');
  // The golden glass look is the primary experience, so light is the default.
  const dark = saved ? saved === 'dark' : false;
  document.body.classList.toggle('dark-theme', dark);
  return dark;
}

function themeButton(dark) {
  return iconButton(
    dark ? 'Switch to light theme' : 'Switch to dark theme',
    dark ? 'bx-sun' : 'bx-moon',
    null,
    'theme-toggle',
  );
}

function syncThemeButton(button, dark) {
  button.replaceChildren(icon(dark ? 'bx-sun' : 'bx-moon'));
  button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  button.setAttribute('title', dark ? 'Switch to light theme' : 'Switch to dark theme');
  button.setAttribute('aria-pressed', String(dark));
}

function buildSidebar(user, active) {
  const items = (NAV[user.role] || []).map((item) => el('li', {
    class: `nav-item ${item.id === active ? 'active' : ''}`.trim(),
  }, [el('a', {
    class: 'nav-link',
    href: item.href,
    'aria-current': item.id === active ? 'page' : undefined,
  }, [icon(item.icon), el('span', { text: item.label })])]));

  const logout = el('li', { class: 'nav-item' }, [el('button', {
    class: 'nav-link logout-button',
    type: 'button',
    style: 'color: var(--danger); width: 100%; border: 0; background: transparent; cursor: pointer; text-align: left;',
    'aria-label': 'Log out',
  }, [icon('bx-log-out'), el('span', { text: 'Log Out' })])]);

  return el('aside', { class: 'sidebar', 'aria-label': 'Primary navigation' }, [
    el('div', { class: 'logo' }, [el('img', {
      class: 'app-logo',
      src: '/assets/logo-wordmark.png',
      alt: 'SRM TRP Engineering College',
    })]),
    el('ul', { class: 'nav-menu' }, items),
    el('div', { class: 'bottom-nav' }, [logout]),
  ]);
}

function buildTopbar(user, pageTitle) {
  const clock = el('div', { class: 'live-clock', 'aria-label': 'Current time' }, [
    icon('bx-time'),
    el('span', { class: 'clock-time', text: '—' }),
    el('span', { class: 'clock-date', text: '' }),
  ]);
  const searchInput = el('input', {
    id: 'globalSearchInput',
    type: 'search',
    placeholder: 'Search drivers or buses…',
    'aria-label': 'Search drivers or buses',
    autocomplete: 'off',
  });
  const searchBar = el('div', { class: 'search-bar', id: 'searchBar' }, [
    el('button', {
      class: 'close-search-btn hide-on-desktop',
      type: 'button',
      'aria-label': 'Close search',
      onclick: () => searchBar.classList.remove('active'),
    }, [icon('bx-arrow-back')]),
    icon('bx-search'),
    searchInput,
  ]);
  const theme = themeButton(document.body.classList.contains('dark-theme'));
  syncThemeButton(theme, document.body.classList.contains('dark-theme'));

  return el('header', { class: 'topbar' }, [
    iconButton('Open navigation menu', 'bx-menu', null, 'menu-toggle'),
    searchBar,
    el('div', { class: 'topbar-right' }, [
      clock,
      iconButton('Open search', 'bx-search', () => {
        searchBar.classList.add('active');
        searchInput.focus();
      }, 'mobile-search-toggle hide-on-desktop'),
      theme,
      el('div', { class: 'user-profile', title: `${ROLE_LABELS[user.role] || user.role}: ${user.email}` }, [
        el('div', { class: 'profile-avatar', 'aria-hidden': 'true', text: initials(user.email) }),
        el('div', { class: 'profile-info' }, [
          el('h4', { text: ROLE_LABELS[user.role] || user.role }),
          el('p', { text: user.email }),
        ]),
        icon('bx-chevron-down'),
      ]),
    ]),
  ]);
}

function buildSearchModal() {
  const body = el('div', { class: 'modal-body', id: 'searchResults' });
  const close = iconButton('Close search results', 'bx-x', () => overlay.classList.remove('active'));
  const overlay = el('div', {
    class: 'modal-overlay',
    id: 'searchModal',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': 'Search results',
    onclick: (event) => { if (event.target === overlay) overlay.classList.remove('active'); },
  }, [
    el('div', { class: 'modal-content' }, [
      el('div', { class: 'modal-header' }, [
        el('h2', { class: 'modal-title' }, [icon('bx-search'), el('span', { text: 'Search results' })]),
        close,
      ]),
      body,
    ]),
  ]);
  return { overlay, body };
}

function renderSearchResults(body, query, data) {
  clear(body);
  const driverSection = el('section', { class: 'result-section' }, [
    el('h4', { text: 'Drivers' }),
    el('div', { class: 'result-list' }),
  ]);
  const busSection = el('section', { class: 'result-section' }, [
    el('h4', { text: 'Buses' }),
    el('div', { class: 'result-list' }),
  ]);
  const driverList = driverSection.querySelector('.result-list');
  const busList = busSection.querySelector('.result-list');

  if (!data.drivers.length) driverList.append(el('p', { class: 'muted', text: 'No matching drivers.' }));
  data.drivers.forEach((driver) => {
    driverList.append(el('button', {
      class: 'result-item',
      type: 'button',
      onclick: () => window.location.assign(`/driver-details?id=${encodeURIComponent(driver.id)}`),
    }, [
      el('strong', { text: driver.name || 'Unnamed driver' }),
      el('span', { text: `Bus ${driver.bus_number || '—'} · ${driver.license_number || 'No licence on file'}` }),
    ]));
  });

  if (!data.buses.length) busList.append(el('p', { class: 'muted', text: 'No matching buses.' }));
  data.buses.forEach((bus) => {
    busList.append(el('button', {
      class: 'result-item',
      type: 'button',
      onclick: () => window.location.assign(`/buses?bus_number=${encodeURIComponent(bus.bus_number)}`),
    }, [
      el('strong', { text: bus.bus_number || 'Unknown bus' }),
      el('span', { text: `${bus.registration_number || 'No registration'} · ${bus.route || 'No route'}` }),
    ]));
  });

  body.append(el('p', { class: 'muted', text: `Results for “${query}”` }), el('div', { class: 'search-results' }, [driverSection, busSection]));
}

function wireShell({ sidebar, topbar, theme, searchInput, searchBar, overlay, searchBody, logoutButton, menuButton }) {
  const clockTime = topbar.querySelector('.clock-time');
  const clockDate = topbar.querySelector('.clock-date');
  const updateClock = () => {
    const now = new Date();
    clockTime.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    clockDate.textContent = now.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
  };
  updateClock();
  setInterval(updateClock, 1000);

  theme.setAttribute('aria-pressed', String(document.body.classList.contains('dark-theme')));
  theme.addEventListener('click', () => {
    const dark = !document.body.classList.contains('dark-theme');
    document.body.classList.toggle('dark-theme', dark);
    localStorage.setItem('transport-theme', dark ? 'dark' : 'light');
    syncThemeButton(theme, dark);
  });

  const closeOverlay = () => {
    const existing = document.querySelector('.sidebar-overlay');
    if (existing) existing.remove();
    sidebar.classList.remove('active');
    menuButton.setAttribute('aria-expanded', 'false');
  };
  menuButton.setAttribute('aria-expanded', 'false');
  menuButton.addEventListener('click', () => {
    const open = !sidebar.classList.contains('active');
    sidebar.classList.toggle('active', open);
    menuButton.setAttribute('aria-expanded', String(open));
    if (open) {
      const backdrop = el('div', { class: 'sidebar-overlay', onclick: closeOverlay });
      document.body.append(backdrop);
    } else closeOverlay();
  });

  const openSearch = async () => {
    const query = searchInput.value.trim();
    if (!query) return;
    overlay.classList.add('active');
    setState(searchBody, 'loading', 'Searching drivers and buses…');
    try {
      const data = await apiGet(`/api/search${toQuery({ q: query })}`);
      renderSearchResults(searchBody, query, data);
    } catch (error) {
      setState(searchBody, 'error', error.message || 'Search failed.');
    }
  };
  searchInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      openSearch();
      searchBar.classList.remove('active');
    }
    if (event.key === 'Escape') searchBar.classList.remove('active');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      overlay.classList.remove('active');
      closeOverlay();
      searchBar.classList.remove('active');
    }
  });

  logoutButton.addEventListener('click', async () => {
    // End the Firebase session as well, so the browser keeps no signed-in
    // identity that the server has already rejected.
    await signOutFirebase();
    try {
      await apiPost('/api/auth/logout', {}, { skipAuthRedirect: true });
    } catch (_error) {
      showToast('Signed out locally; the server session may have already expired.', 'info');
    }
    window.location.assign('/');
  });
}

export async function mountShell({ active, allowedRoles = [], pageTitle = 'VISION AI - SRM TRP' }) {
  let user;
  try {
    ({ user } = await apiGet('/api/auth/me'));
  } catch (_error) {
    window.location.assign('/');
    throw new Error('Authentication required');
  }
  if (allowedRoles.length && !allowedRoles.includes(user.role)) {
    window.location.assign('/?error=forbidden');
    throw new Error('Forbidden role');
  }

  document.title = `${pageTitle} · VISION AI - SRM TRP`;
  applyTheme();
  const shell = document.getElementById('app-shell');
  if (!shell) throw new Error('Missing #app-shell');

  const sidebar = buildSidebar(user, active);
  const topbar = buildTopbar(user, pageTitle);
  const { overlay, body: searchBody } = buildSearchModal();
  const root = el('div', { class: 'dashboard-content', id: 'page-root' });
  const main = el('main', { class: 'main-content' }, [topbar, root]);
  const container = el('div', { class: 'app-container' }, [sidebar, main]);

  shell.replaceChildren(container);
  document.body.append(overlay);
  const template = document.getElementById('page-template');
  if (template) root.append(template.content.cloneNode(true));

  wireShell({
    sidebar,
    topbar,
    theme: topbar.querySelector('.theme-toggle'),
    searchInput: topbar.querySelector('#globalSearchInput'),
    searchBar: topbar.querySelector('#searchBar'),
    overlay,
    searchBody,
    logoutButton: sidebar.querySelector('.logout-button'),
    menuButton: topbar.querySelector('.menu-toggle'),
  });

  // Firebase is optional: it only loads when the deployment is configured.
  initFirebase()
    .then((state) => {
      if (state.enabled) logEvent('app_open', { page: active });
    })
    .catch(() => { /* analytics is never allowed to break the console */ });

  return { user, root };
}
