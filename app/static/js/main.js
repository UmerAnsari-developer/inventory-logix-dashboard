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

  const notificationButton = document.getElementById("notificationButton");
  if (notificationButton) {
    const count = notificationButton.dataset.count || "0";
    notificationButton.addEventListener("click", function () {
      toast("Warehouse pulse", count + " products are in the reorder queue right now.");
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

  document.querySelectorAll("[data-toggle-target]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const target = document.getElementById(btn.dataset.toggleTarget);
      if (!target) return;
      target.classList.toggle("hidden");
      const plural = target.classList.contains("hidden") ? 1 : 0;
      btn.classList.toggle("toggled", !plural);
    });
  });

  const eoqForm = document.getElementById("eoqForm");
  if (eoqForm && window.initEoqCalculator) {
    window.initEoqCalculator(eoqForm);
  }
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

function formatCurrency(value, prefix) {
  const n = Number(value || 0);
  return (prefix || "") + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("en-IN");
}

function debounce(fn, wait) {
  let t;
  return function () {
    const args = arguments;
    const ctx = this;
    clearTimeout(t);
    t = setTimeout(function () { fn.apply(ctx, args); }, wait);
  };
}