document.addEventListener("DOMContentLoaded", function () {
  const searchWrap = document.getElementById("globalSearch");
  const searchInput = document.getElementById("searchInput");
  const searchToggle = document.getElementById("searchToggle");

  if (searchToggle && searchWrap) {
    searchToggle.addEventListener("click", function () {
      const open = searchWrap.classList.toggle("open");
      searchToggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (searchInput) searchInput.focus();
    });
    document.addEventListener("click", function (e) {
      if (searchWrap.classList.contains("open") &&
          !searchWrap.contains(e.target)) {
        searchWrap.classList.remove("open");
        searchToggle.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && searchWrap.classList.contains("open")) {
        searchWrap.classList.remove("open");
        searchToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  if (searchInput) {
    let timer;
    function runSearch() {
      const term = searchInput.value.trim();
      if (!term) return;
      window.location.href = "/inventory?search=" + encodeURIComponent(term);
    }
    searchInput.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(runSearch, 650);
    });
    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        clearTimeout(timer);
        runSearch();
      }
    });
  }

  const navToggle = document.getElementById("navToggle");
  const topNav = document.querySelector(".top-nav");
  if (navToggle && topNav) {
    navToggle.addEventListener("click", function (e) {
      e.stopPropagation();
      const open = topNav.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (topNav.classList.contains("open") &&
          !topNav.contains(e.target) && !navToggle.contains(e.target)) {
        topNav.classList.remove("open");
        navToggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.querySelectorAll(".nav-drop-btn").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      const drop = btn.closest(".nav-drop");
      if (!drop) return;
      const wasOpen = drop.classList.contains("open");
      document.querySelectorAll(".nav-drop.open").forEach(function (d) {
        d.classList.remove("open");
        const b = d.querySelector(".nav-drop-btn");
        if (b) b.setAttribute("aria-expanded", "false");
      });
      if (!wasOpen) {
        drop.classList.add("open");
        btn.setAttribute("aria-expanded", "true");
      }
    });
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".nav-drop")) {
      document.querySelectorAll(".nav-drop.open").forEach(function (d) {
        d.classList.remove("open");
        const b = d.querySelector(".nav-drop-btn");
        if (b) b.setAttribute("aria-expanded", "false");
      });
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll(".nav-drop.open").forEach(function (d) {
        d.classList.remove("open");
        const b = d.querySelector(".nav-drop-btn");
        if (b) b.setAttribute("aria-expanded", "false");
      });
    }
  });

  const userMenuButton = document.getElementById("userMenuButton");
  const userDropdown = document.getElementById("userDropdown");
  if (userMenuButton && userDropdown) {
    userMenuButton.addEventListener("click", function (e) {
      e.stopPropagation();
      const open = userDropdown.classList.toggle("open");
      userMenuButton.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!userMenuButton.contains(e.target) && !userDropdown.contains(e.target)) {
        userDropdown.classList.remove("open");
        userMenuButton.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        userDropdown.classList.remove("open");
        userMenuButton.setAttribute("aria-expanded", "false");
      }
    });
  }

  const flashStack = document.querySelector(".flash-stack");
  if (flashStack) {
    flashStack.querySelectorAll(".flash-close").forEach(function (btn) {
      btn.addEventListener("click", function () {
        this.closest(".flash").remove();
      });
    });
    setTimeout(function () {
      flashStack.querySelectorAll(".flash").forEach(function (f) { f.remove(); });
    }, 6000);
  }

  const categoryFilter = document.getElementById("categoryFilter");
  if (categoryFilter) {
    categoryFilter.addEventListener("change", function () {
      const params = new URLSearchParams(window.location.search);
      const value = this.value;
      if (value && value !== "all") params.set("category", value);
      else params.delete("category");
      params.delete("page");
      const qs = params.toString();
      window.location.href = qs ? "/inventory?" + qs : "/inventory";
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      const msg = form.dataset.confirm;
      if (msg && !confirm(msg)) e.preventDefault();
    });
  });

  // Select dropdowns that confirm a destructive value then auto-submit
  // (CSP blocks inline onchange; declarative data-* + this listener instead)
  document.querySelectorAll("select[data-confirm-value]").forEach(function (sel) {
    var original = sel.value;
    sel.addEventListener("change", function () {
      var msg = sel.dataset.confirm;
      if (sel.value === sel.dataset.confirmValue && msg && !confirm(msg)) {
        sel.value = original;
        return;
      }
      if (sel.form) {
        if (typeof sel.form.requestSubmit === "function") sel.form.requestSubmit();
        else sel.form.submit();
      }
    });
  });

  // ── Batch 2: duplicate-submit guard + novalidate validation + aria-invalid ──
  var submitting = new WeakSet();

  function fieldErrorId(field) {
    if (field.id) return field.id + "-error";
    return (field.name || "field") + "-error";
  }

  function setFieldError(field, message) {
    var errId = fieldErrorId(field);
    var err = document.getElementById(errId);
    if (!err) {
      err = document.createElement("span");
      err.className = "field-error";
      err.id = errId;
      err.setAttribute("role", "alert");
      var anchor = field.closest("label") || field.parentNode;
      anchor.appendChild(err);
    }
    err.textContent = message;
    err.hidden = false;
    field.setAttribute("aria-invalid", "true");
    var ids = (field.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    if (ids.indexOf(errId) === -1) ids.push(errId);
    field.setAttribute("aria-describedby", ids.join(" "));
  }

  function clearFieldError(field) {
    field.removeAttribute("aria-invalid");
    var err = document.getElementById(fieldErrorId(field));
    if (err) { err.textContent = ""; err.hidden = true; }
    var ids = (field.getAttribute("aria-describedby") || "").split(/\s+/)
      .filter(function (id) { return id && id !== fieldErrorId(field); });
    if (ids.length) field.setAttribute("aria-describedby", ids.join(" "));
    else field.removeAttribute("aria-describedby");
  }

  function validateNovalidateForm(form) {
    var firstBad = null;
    form.querySelectorAll("input, select, textarea").forEach(function (field) {
      if (field.disabled || field.type === "hidden" || field.type === "submit" || field.type === "button") return;
      if (field.readOnly) { clearFieldError(field); return; }
      if (field.checkValidity()) clearFieldError(field);
      else {
        setFieldError(field, field.validationMessage || "Invalid value");
        if (!firstBad) firstBad = field;
      }
    });
    // Register-style password match (opt-in via data-match form attribute)
    var matchSel = form.getAttribute("data-match");
    if (matchSel) {
      var a = form.querySelector(matchSel.split("=>")[0].trim());
      var b = form.querySelector(matchSel.split("=>")[1].trim());
      if (a && b && a.value && b.value && a.value !== b.value) {
        setFieldError(b, "Passwords don't match");
        if (!firstBad) firstBad = b;
      }
    }
    if (firstBad) { firstBad.focus(); return false; }
    return true;
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    // T8: validate novalidate forms (checkValidity still works with novalidate)
    if (form.hasAttribute("novalidate")) {
      if (!validateNovalidateForm(form)) { e.preventDefault(); return; }
    }
    // T7: duplicate-submit guard
    if (submitting.has(form)) { e.preventDefault(); return; }
    submitting.add(form);
    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (btn) {
      if (btn.dataset.origText === undefined) btn.dataset.origText = btn.textContent || btn.value;
      btn.disabled = true;
      if (btn.tagName === "BUTTON") btn.textContent = "Submitting\u2026";
      else btn.value = "Submitting\u2026";
    });
  });

  // T9: clear error state as user fixes fields
  document.addEventListener("input", function (e) {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement || e.target instanceof HTMLTextAreaElement) {
      if (e.target.checkValidity()) clearFieldError(e.target);
    }
  });

  document.querySelectorAll("[data-toggle-target]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const target = document.getElementById(btn.dataset.toggleTarget);
      if (!target) return;
      target.classList.toggle("hidden");
      const plural = target.classList.contains("hidden") ? 1 : 0;
      btn.classList.toggle("toggled", !plural);
    });
  });

  // Password show/hide toggle
  // Eye open (aria-pressed=false) → password hidden
  // Eye closed (aria-pressed=true) → password shown
  document.querySelectorAll(".password-toggle").forEach(function (btn) {
    const target = document.getElementById(btn.dataset.target);
    if (!target) return;
    // Set initial: password hidden, eye open
    btn.setAttribute("aria-pressed", "false");
    btn.addEventListener("click", function () {
      const isHidden = target.type === "password";
      target.type = isHidden ? "text" : "password";
      // aria-pressed="true" when password is SHOWN (eye closed)
      btn.setAttribute("aria-pressed", target.type === "text");
    });
  });

  const eoqForm = document.getElementById("eoqForm");
  if (eoqForm && window.initEoqCalculator) {
    window.initEoqCalculator(eoqForm);
  }

  // Scroll reveal — matches landing page animation style
  if ("IntersectionObserver" in window) {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.16, rootMargin: "0px 0px -40px 0px" });
    document.querySelectorAll(".reveal").forEach(function (el) {
      revealObserver.observe(el);
    });
  } else {
    document.querySelectorAll(".reveal").forEach(function (el) {
      el.classList.add("in");
    });
  }

  // Connectivity toasts (guarded — showToast lives in ai-features.js)
  window.addEventListener("offline", function () {
    if (typeof window.showToast === "function") {
      window.showToast("You are offline. Changes may fail until connection returns.", "error");
    }
  });
  window.addEventListener("online", function () {
    if (typeof window.showToast === "function") {
      window.showToast("Back online.", "success");
    }
  });
});

// ── GAP-018: UI idempotency keys ──
// Set-once-if-empty: a fresh UUID per submit event would give a double-click
// two different keys → two rows → defeats the purpose. Both submits of the
// same form instance carry the same key → the server replays the first
// response instead of executing twice.
// crypto.randomUUID needs a secure context (HTTPS/localhost) — on plain-HTTP
// LAN demos fall back to manual hex so idempotency still engages.
function _idempotencyUuid() {
  if (window.crypto && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}
document.addEventListener('submit', e => {
  const k = e.target.querySelector('input[name="idempotency_key"]');
  if (k && !k.value) k.value = _idempotencyUuid();
});

function toast(title, message) {
  const region = document.getElementById("toastRegion");
  if (!region) return;
  const item = document.createElement("div");
  item.className = "toast";
  item.innerHTML = '<span class="toast-icon">✓</span><div class="toast-copy"><strong>' + title + "</strong>" + (message || "") + '</div><button class="toast-close" aria-label="Dismiss">&times;</button>';
  region.appendChild(item);
  item.querySelector(".toast-close").addEventListener("click", function() { item.remove(); });
  setTimeout(function () { item.remove(); }, 4000);
}

function getDlColor() { return document.documentElement.getAttribute('data-theme') === 'dark' ? '#e2e8f0' : '#1e293b'; }