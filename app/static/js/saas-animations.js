/* ═══════════════════════════════════════════════════════════════════
   SaaS Dashboard Animations — GSAP-powered entrance effects
   KPIs stagger in, tables fade up, charts scale in
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  /* ── Bail on reduced motion ────────────────────────────────────── */
  var mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (mq && mq.matches) return;

  /* ── Wait for GSAP ────────────────────────────────────────────── */
  function whenReady(fn) {
    if (typeof gsap !== "undefined" && typeof ScrollTrigger !== "undefined") {
      fn();
    } else {
      var tries = 0;
      var id = setInterval(function () {
        tries++;
        if (typeof gsap !== "undefined" && typeof ScrollTrigger !== "undefined") {
          clearInterval(id);
          fn();
        }
        if (tries > 40) {
          clearInterval(id); /* 2s timeout */
        }
      }, 50);
    }
  }

  whenReady(function () {
    gsap.registerPlugin(ScrollTrigger);

    /* ── KPI Cards — stagger from bottom with 3D pop ────────────── */
    var kpiCards = document.querySelectorAll(".metric-grid .metric-card");
    if (kpiCards.length) {
      gsap.set(kpiCards, { opacity: 0, y: 30, rotateX: 8 });
      gsap.to(kpiCards, {
        opacity: 1,
        y: 0,
        rotateX: 0,
        duration: 0.55,
        stagger: 0.09,
        ease: "back.out(1.4)",
        delay: 0.15,
      });
    }

    /* ── Alert Strip — slide down ────────────────────────────────── */
    var alertStrip = document.querySelector(".alert-strip");
    if (alertStrip) {
      gsap.from(alertStrip, {
        opacity: 0,
        y: -16,
        duration: 0.4,
        ease: "power2.out",
        delay: 0.05,
      });
    }

    /* ── AI Banner — fade in ─────────────────────────────────────── */
    var aiBanner = document.querySelector(".ai-banner");
    if (aiBanner) {
      gsap.from(aiBanner, {
        opacity: 0,
        y: -10,
        duration: 0.4,
        ease: "power2.out",
        delay: 0.08,
      });
    }

    /* ── Panels — scroll-triggered fade up ───────────────────────── */
    var panels = document.querySelectorAll(".panel");
    panels.forEach(function (panel) {
      gsap.from(panel, {
        scrollTrigger: {
          trigger: panel,
          start: "top 92%",
          toggleActions: "play none none none",
        },
        opacity: 0,
        y: 28,
        duration: 0.5,
        ease: "power2.out",
      });
    });

    /* ── Table Rows — stagger fade up on scroll ──────────────────── */
    var tables = document.querySelectorAll(".table-scroll table tbody, table.table-scroll tbody");
    tables.forEach(function (tbody) {
      var rows = tbody.querySelectorAll("tr");
      if (rows.length === 0) return;
      gsap.set(rows, { opacity: 0, y: 12 });
      ScrollTrigger.create({
        trigger: tbody.closest("table"),
        start: "top 88%",
        onEnter: function () {
          gsap.to(rows, {
            opacity: 1,
            y: 0,
            duration: 0.35,
            stagger: 0.04,
            ease: "power2.out",
          });
        },
        once: true,
      });
    });

    /* ── Charts — scale in on scroll ─────────────────────────────── */
    var chartContainers = document.querySelectorAll(
      ".chart-wrap, .report-chart, .ai-forecast-chart, .warehouse-chart-wrap"
    );
    chartContainers.forEach(function (chart) {
      gsap.from(chart, {
        scrollTrigger: {
          trigger: chart,
          start: "top 90%",
          toggleActions: "play none none none",
        },
        opacity: 0,
        scale: 0.95,
        duration: 0.5,
        ease: "power2.out",
      });
    });

    /* ── Kanban Cards — stagger in ───────────────────────────────── */
    var kanbanCards = document.querySelectorAll(".kanban-card");
    if (kanbanCards.length) {
      ScrollTrigger.create({
        trigger: document.querySelector(".kanban-grid"),
        start: "top 88%",
        onEnter: function () {
          gsap.from(kanbanCards, {
            opacity: 0,
            y: 18,
            duration: 0.35,
            stagger: 0.05,
            ease: "power2.out",
          });
        },
        once: true,
      });
    }

    /* ── Supplier Cards — stagger in ─────────────────────────────── */
    var supplierCards = document.querySelectorAll(".supplier-card");
    if (supplierCards.length) {
      ScrollTrigger.create({
        trigger: document.querySelector(".supplier-grid"),
        start: "top 88%",
        onEnter: function () {
          gsap.from(supplierCards, {
            opacity: 0,
            y: 22,
            scale: 0.96,
            duration: 0.4,
            stagger: 0.06,
            ease: "back.out(1.2)",
          });
        },
        once: true,
      });
    }

    /* ── Warehouse Cards — stagger in ────────────────────────────── */
    var whCards = document.querySelectorAll(".warehouse-card-detail");
    if (whCards.length) {
      ScrollTrigger.create({
        trigger: document.querySelector(".warehouse-grid"),
        start: "top 88%",
        onEnter: function () {
          gsap.from(whCards, {
            opacity: 0,
            y: 22,
            scale: 0.96,
            duration: 0.4,
            stagger: 0.06,
            ease: "back.out(1.2)",
          });
        },
        once: true,
      });
    }

    /* ── Report Tabs — slide in ──────────────────────────────────── */
    var tabs = document.querySelectorAll(".report-tab");
    if (tabs.length) {
      gsap.from(tabs, {
        opacity: 0,
        y: 8,
        duration: 0.3,
        stagger: 0.05,
        ease: "power2.out",
        delay: 0.2,
      });
    }

    /* ── KPI Groups (Reports) — stagger ──────────────────────────── */
    var kpiGroups = document.querySelectorAll(".kpi-group .metric-card");
    if (kpiGroups.length) {
      ScrollTrigger.create({
        trigger: document.querySelector(".kpi-group"),
        start: "top 90%",
        onEnter: function () {
          gsap.from(kpiGroups, {
            opacity: 0,
            y: 20,
            duration: 0.4,
            stagger: 0.07,
            ease: "back.out(1.3)",
          });
        },
        once: true,
      });
    }

    /* ── Filter Bars — fade in ───────────────────────────────────── */
    var filterBars = document.querySelectorAll(".filter-bar");
    filterBars.forEach(function (bar) {
      gsap.from(bar, {
        opacity: 0,
        y: 10,
        duration: 0.35,
        ease: "power2.out",
        delay: 0.1,
      });
    });

    /* ── Page Headings — fade in ─────────────────────────────────── */
    var headings = document.querySelectorAll(".page-heading");
    headings.forEach(function (h) {
      gsap.from(h, {
        opacity: 0,
        y: 12,
        duration: 0.4,
        ease: "power2.out",
      });
    });
  });
})();
