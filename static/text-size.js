/* Resize text, not the whole interface; respect the browser's default font size. */
(() => {
  'use strict';
  const key = 'techneighbor-text-size';
  const steps = [90, 100, 125, 150, 175, 200];
  const root = document.documentElement;
  let size = 100;
  try {
    const saved = Number(localStorage.getItem(key));
    if (steps.includes(saved)) size = saved;
  } catch (_) {}

  function apply(announce = false) {
    root.dataset.textSize = String(size);
    root.style.setProperty('--text-scale', String(size / 100));
    const value = document.getElementById('text-size-value');
    if (!value) return;
    value.textContent = size + '%';
    document.getElementById('text-smaller').disabled = size === steps[0];
    document.getElementById('text-bigger').disabled = size === steps[steps.length - 1];
    if (announce) document.getElementById('text-size-status').textContent = 'Text size ' + size + ' percent.';
  }

  function change(next) {
    size = next;
    try { localStorage.setItem(key, String(size)); } catch (_) {}
    apply(true);
  }

  apply();
  document.addEventListener('DOMContentLoaded', () => {
    const controls = document.getElementById('text-size-controls');
    if (!controls) return;
    controls.hidden = false;
    apply();
    document.getElementById('text-smaller').addEventListener('click', () => {
      change(steps[Math.max(0, steps.indexOf(size) - 1)]);
    });
    document.getElementById('text-bigger').addEventListener('click', () => {
      change(steps[Math.min(steps.length - 1, steps.indexOf(size) + 1)]);
    });
    document.getElementById('text-size-reset').addEventListener('click', () => change(100));
  });
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    const saved = Number(event.newValue);
    size = steps.includes(saved) ? saved : 100;
    apply();
  });
})();
