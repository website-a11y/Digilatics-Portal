/**
 * Punch Portal — real-time clock, elapsed timer, shift-end enforcement.
 */

(function () {
  "use strict";

  // ── Helpers ────────────────────────────────────────────────────────────────

  /** Parse "HH:MM" → total minutes since midnight */
  function hhmm(str) {
    if (!str) return null;
    var parts = str.split(":");
    return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
  }

  /** Current local time → total minutes since midnight */
  function nowMinutes() {
    var n = new Date();
    return n.getHours() * 60 + n.getMinutes();
  }

  /** Format seconds → "HH:MM:SS" */
  function fmtDuration(totalSec) {
    var h = Math.floor(totalSec / 3600);
    var m = Math.floor((totalSec % 3600) / 60);
    var s = totalSec % 60;
    return pad(h) + ":" + pad(m) + ":" + pad(s);
  }

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  // ── Shift-end detection ────────────────────────────────────────────────────

  /**
   * Returns true if the current moment is past the shift's checkout time.
   * Handles overnight shifts (schedIn > schedOut in minute values).
   * Adds a 30-minute grace window after checkout before locking.
   */
  function shiftEnded() {
    var schedIn  = hhmm(PUNCH_DATA.schedIn);
    var schedOut = hhmm(PUNCH_DATA.schedOut);
    if (schedOut === null) return false; // no schedule → never lock

    var GRACE = 30; // minutes after checkout before buttons lock
    var now   = nowMinutes();

    // Overnight shift: checkout is next calendar day
    if (schedIn !== null && schedOut < schedIn) {
      // Normalise to a 48-h window
      var normOut = schedOut + 1440;
      var normNow = now < schedIn ? now + 1440 : now;
      return normNow > normOut + GRACE;
    }

    return now > schedOut + GRACE;
  }

  // ── DOM refs ───────────────────────────────────────────────────────────────

  var clockEl   = document.getElementById("pp-clock");
  var elapsedEl = document.getElementById("pp-elapsed");
  var btnIn     = document.getElementById("pp-btn-in");
  var btnOut    = document.getElementById("pp-btn-out");
  var endedBanner = document.getElementById("pp-shift-ended");

  // ── Live clock ─────────────────────────────────────────────────────────────

  function updateClock() {
    var n = new Date();
    if (clockEl) {
      clockEl.textContent =
        pad(n.getHours()) + ":" + pad(n.getMinutes()) + ":" + pad(n.getSeconds());
    }
  }

  // ── Elapsed / duration timer ───────────────────────────────────────────────

  var checkInSec  = null;
  var checkOutSec = null;

  function timeToSec(str) {
    if (!str) return null;
    var parts = str.split(":");
    return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60;
  }

  function updateElapsed() {
    if (!elapsedEl) return;

    if (checkInSec === null) return;

    if (checkOutSec !== null) {
      // Duration is fixed
      var dur = checkOutSec - checkInSec;
      if (dur < 0) dur += 86400; // overnight
      elapsedEl.textContent = fmtDuration(dur);
      return;
    }

    // Live elapsed since check-in
    var n   = new Date();
    var nowSec = n.getHours() * 3600 + n.getMinutes() * 60 + n.getSeconds();
    var elapsed = nowSec - checkInSec;
    if (elapsed < 0) elapsed += 86400; // past midnight
    elapsedEl.textContent = fmtDuration(elapsed);
  }

  // ── Shift-end enforcement ──────────────────────────────────────────────────

  function enforceShiftEnd() {
    if (!shiftEnded()) return;

    // Hide check-in / check-out buttons
    if (btnIn)  { btnIn.disabled  = true; btnIn.classList.add("pp-btn-locked");  }
    if (btnOut) { btnOut.disabled = true; btnOut.classList.add("pp-btn-locked"); }

    // Stop elapsed timer
    if (elapsedEl && !PUNCH_DATA.checkOut) {
      elapsedEl.classList.add("pp-elapsed-stopped");
    }

    // Show shift-ended banner
    if (endedBanner) endedBanner.style.display = "flex";
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  checkInSec  = timeToSec(PUNCH_DATA.checkIn);
  checkOutSec = timeToSec(PUNCH_DATA.checkOut);

  function tick() {
    updateClock();
    updateElapsed();
    enforceShiftEnd();
  }

  tick();
  setInterval(tick, 1000);

}());
