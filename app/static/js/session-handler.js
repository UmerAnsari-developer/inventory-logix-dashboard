/* =============================================================================
   InventoryLogix — session handler.
   Idle warning (20 min) + session-liveness via fetch pass-through.
   No-ops unless window.LOGIN_URL is set (authenticated pages only).
   ============================================================================= */
(function () {
  'use strict';

  var IDLE_TIMEOUT = 1200000; // 20 minutes — client-side idle prompt only; server has no idle expiry
  var idleTimer = null;
  var redirecting = false;

  function redirectToLogin() {
    if (redirecting) return;
    redirecting = true;
    window.location.href = window.LOGIN_URL;
  }

  function resetIdleTimer() {
    if (redirecting) return;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(onIdle, IDLE_TIMEOUT);
  }

  function onIdle() {
    if (redirecting) return;
    var stay = window.confirm("You've been inactive for a while. Stay signed in?");
    if (stay) {
      resetIdleTimer();
    } else {
      redirectToLogin();
    }
  }

  // Pass-through wrapper: detect expired sessions (401 or redirect to login).
  function wrapFetch() {
    var original = window.fetch;
    if (typeof original !== 'function') return;
    window.fetch = function () {
      return original.apply(this, arguments).then(function (response) {
        var expired = response.status === 401 ||
          (response.redirected && response.url.indexOf('/auth/login') !== -1);
        if (expired && !redirecting) {
          if (typeof window.showToast === 'function') {
            window.showToast('Session expired', 'error');
          }
          redirectToLogin();
        }
        return response;
      });
    };
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!window.LOGIN_URL) return;
    ['mousedown', 'keydown', 'scroll', 'touchstart'].forEach(function (evt) {
      window.addEventListener(evt, resetIdleTimer, { capture: true, passive: true });
    });
    resetIdleTimer();
    wrapFetch();
  });
})();
