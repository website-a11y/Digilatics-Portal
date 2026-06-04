/* Employee Registration Form — Progress + Tab Badges */
(function () {
  'use strict';

  // ── Inject 2px orange progress bar below the breadcrumb/header ───
  function injectProgressBar() {
    if (document.getElementById('ef-progress-fill')) return;
    const bar = document.createElement('div');
    bar.style.cssText = 'height:2px;background:#E5E7EB;width:100%;margin-bottom:16px;border-radius:1px;overflow:hidden;';
    const fill = document.createElement('div');
    fill.id = 'ef-progress-fill';
    fill.style.cssText = 'height:100%;background:#F58400;width:0%;transition:width 0.4s ease;';
    bar.appendChild(fill);

    // Insert before the first form or main content area
    const target = document.querySelector('#content-main form, #content-main > div');
    if (target) target.insertAdjacentElement('beforebegin', bar);
  }

  // ── Check if field has a value ────────────────────────────────────
  function hasValue(el) {
    if (!el) return false;
    if (el.type === 'checkbox' || el.type === 'radio') return el.checked;
    return (el.value || '').trim() !== '';
  }

  // ── Count filled vs total inputs in a container ───────────────────
  function countFields(container) {
    const inputs = Array.from(
      container.querySelectorAll('input, select, textarea')
    ).filter(el =>
      !el.disabled &&
      el.type !== 'hidden' &&
      el.type !== 'file' &&
      el.type !== 'submit' &&
      el.offsetParent !== null
    );
    const filled = inputs.filter(hasValue).length;
    return { filled, total: inputs.length };
  }

  // ── Overall progress across whole form ───────────────────────────
  function calcProgress() {
    const form = document.querySelector('#content-main form');
    if (!form) return 0;
    const { filled, total } = countFields(form);
    if (total === 0) return 0;
    return Math.round((filled / total) * 100);
  }

  // ── Update progress bar + footer label ───────────────────────────
  function updateProgress() {
    const pct = calcProgress();
    const fill = document.getElementById('ef-progress-fill');
    if (fill) fill.style.width = pct + '%';
    const label = document.getElementById('ef-footer-pct');
    if (label) label.textContent = 'Progress ' + pct + '%';
  }

  // ── Tab badge injection ───────────────────────────────────────────
  // Unfold renders tab <a> elements inside a <nav> in fieldsets_tabs.html
  function updateTabBadges() {
    // Find Unfold's tab nav links
    const tabLinks = Array.from(
      document.querySelectorAll(
        '[id="content-main"] nav a, .tab-wrapper ~ * nav a, ' +
        'nav[class*="bg-base-100"] a, nav[class*="cursor-pointer"] a'
      )
    );

    // Match tab wrappers (each fieldset shown in tabs)
    const tabWrappers = Array.from(document.querySelectorAll('.tab-wrapper'));

    tabLinks.forEach((link, i) => {
      // Remove existing badge
      const old = link.querySelector('.ef-tab-badge');
      if (old) old.remove();

      const badge = document.createElement('span');
      badge.className = 'ef-tab-badge';

      const isActive = link.classList.contains('active');
      const wrapper = tabWrappers[i];
      const completion = wrapper ? (() => {
        const { filled, total } = countFields(wrapper);
        return total === 0 ? 1 : filled / total;
      })() : 0;

      if (isActive) {
        badge.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;' +
          'width:16px;height:16px;border-radius:50%;background:#F58400;color:#fff;' +
          'font-size:9px;font-weight:500;margin-right:5px;flex-shrink:0;';
        badge.textContent = String(i + 1);
      } else if (completion >= 1) {
        badge.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;' +
          'width:16px;height:16px;border-radius:50%;background:#DCFCE7;color:#15803D;' +
          'font-size:9px;font-weight:500;margin-right:5px;flex-shrink:0;';
        badge.textContent = '✓';
      } else {
        badge.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;' +
          'width:16px;height:16px;border-radius:50%;background:#E5E7EB;color:#6B7280;' +
          'font-size:9px;font-weight:500;margin-right:5px;flex-shrink:0;';
        badge.textContent = String(i + 1);
      }

      link.insertAdjacentElement('afterbegin', badge);
    });
  }

  // ── Account number verified state ────────────────────────────────
  function applyVerifiedStates() {
    const accInput = document.querySelector('input[name="account_number"]');
    if (accInput && hasValue(accInput)) {
      accInput.style.borderColor = '#16A34A';
      accInput.style.background = '#F0FDF4';
      let hint = accInput.parentElement.querySelector('.ef-verified-hint');
      if (!hint) {
        hint = document.createElement('div');
        hint.className = 'ef-verified-hint';
        hint.innerHTML = '✓ Verified and saved.';
        hint.style.cssText = 'font-size:11px;color:#16A34A;font-weight:500;margin-top:4px;';
        accInput.insertAdjacentElement('afterend', hint);
      }
    }
  }

  // ── Info note for System Access section ──────────────────────────
  function injectInfoNote() {
    const roleSelect = document.querySelector('select[name="role"]');
    if (!roleSelect || roleSelect.dataset.noteAdded) return;
    roleSelect.dataset.noteAdded = '1';

    const note = document.createElement('div');
    note.className = 'ef-info-note';
    note.innerHTML = 'ⓘ Employees stay outside the admin panel by default. Promote to Manager or Administrator to grant staff access.';
    const row = roleSelect.closest('.form-row, [class*="field-"], .fieldBox');
    if (row) row.insertAdjacentElement('afterend', note);
  }

  // ── Full update ───────────────────────────────────────────────────
  function update() {
    updateProgress();
    updateTabBadges();
  }

  // ── Bootstrap ─────────────────────────────────────────────────────
  function init() {
    injectProgressBar();
    applyVerifiedStates();
    injectInfoNote();
    update();

    document.addEventListener('input', update);
    document.addEventListener('change', () => { applyVerifiedStates(); update(); });

    // Re-run after Alpine.js tab switches (with a small delay for DOM update)
    document.addEventListener('click', e => {
      if (e.target.closest('nav a')) setTimeout(update, 80);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
