/* Apply appearance before styles load to avoid a flash of the wrong theme. */
(() => {
  'use strict';
  const storageKey = 'techneighbor-theme';
  const root = document.documentElement;
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = null;

  try {
    const saved = window.localStorage.getItem(storageKey);
    if (saved === 'light' || saved === 'dark') preference = saved;
  } catch (_) {
    // Appearance still works when the browser blocks persistent storage.
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    const toggle = document.getElementById('theme-switch');
    if (toggle) {
      const dark = theme === 'dark';
      toggle.setAttribute('aria-checked', String(dark));
      toggle.querySelector('.switch-state').textContent = dark ? 'On' : 'Off';
    }
  }

  function applyPreference() {
    applyTheme(preference || (system.matches ? 'dark' : 'light'));
  }

  applyPreference();
  system.addEventListener('change', () => {
    if (!preference) applyPreference();
  });

  // Keep other open app tabs in sync without writing back to storage.
  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey && event.key !== null) return;
    preference = event.newValue === 'dark' || event.newValue === 'light'
      ? event.newValue : null;
    applyPreference();
  });

  document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('theme-switch');
    if (!toggle) return;
    toggle.hidden = false;
    applyPreference();
    toggle.addEventListener('click', () => {
      preference = root.dataset.theme === 'dark' ? 'light' : 'dark';
      try {
        window.localStorage.setItem(storageKey, preference);
      } catch (_) {
        // Keep the current page usable even if a preference cannot be saved.
      }
      applyPreference();
    });
  });
})();
