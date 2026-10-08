/* Dashboard animations — 3D hover/tilt effects REMOVED per spec §20.
   Kept: non-3D entrance fades (opacity/translate), SVG stroke draw.
   Tooltips, hover highlighting, click, zoom are CSS/Chart.js native — untouched. */
(function () {
  if (document.body.classList.contains('landing')) return;
  /* Skip on mobile — no hover, saves GPU */
  if (window.innerWidth < 768 || matchMedia('(hover: none)').matches) return;

  /* ── SVG Chart entrance (Stock movement) — stroke draw, no 3D ── */
  var chartLine = document.querySelector('.chart-line');
  var chartArea = document.querySelector('.chart-area');
  var chartPoints = document.querySelectorAll('.chart-point');

  if (chartLine) {
    var len = chartLine.getTotalLength ? chartLine.getTotalLength() : 800;
    chartLine.style.strokeDasharray = len;
    chartLine.style.strokeDashoffset = len;
    chartLine.style.transition = 'stroke-dashoffset 1.2s cubic-bezier(.22,1,.36,1)';
    requestAnimationFrame(function () { chartLine.style.strokeDashoffset = '0'; });
  }
  if (chartArea) {
    chartArea.style.opacity = '0';
    chartArea.style.transform = 'scaleY(0)';
    chartArea.style.transformOrigin = 'bottom center';
    chartArea.style.transition = 'opacity 0.8s ease 0.4s, transform 0.8s cubic-bezier(.22,1,.36,1) 0.4s';
    requestAnimationFrame(function () {
      chartArea.style.opacity = '0.6';
      chartArea.style.transform = 'scaleY(1)';
    });
  }
  chartPoints.forEach(function (pt, i) {
    pt.style.opacity = '0';
    pt.style.transform = 'scale(0)';
    pt.style.transformOrigin = 'center';
    pt.style.transition = 'opacity 0.3s ease ' + (0.6 + i * 0.06) + 's, transform 0.4s cubic-bezier(.34,1.56,.64,1) ' + (0.6 + i * 0.06) + 's';
    requestAnimationFrame(function () {
      pt.style.opacity = '1';
      pt.style.transform = 'scale(1)';
    });
  });

  /* ── Inventory Mix bars — scaleX fade only (rotateX removed) ── */
  document.querySelectorAll('.cat-fill').forEach(function (bar, i) {
    bar.style.transform = 'scaleX(0)';
    bar.style.transformOrigin = 'left center';
    bar.style.transition = 'transform 0.6s cubic-bezier(.22,1,.36,1) ' + (0.15 + i * 0.08) + 's';
  });
  var catObs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.style.transform = 'scaleX(1)';
        catObs.unobserve(e.target);
      }
    });
  }, { threshold: 0.2 });
  document.querySelectorAll('.cat-fill').forEach(function (bar) { catObs.observe(bar); });

  /* ── Warehouse chart canvas — opacity fade only (perspective/rotateX removed) ── */
  var whCanvas = document.getElementById('warehouseProfileChart');
  if (whCanvas) {
    whCanvas.style.opacity = '0';
    whCanvas.style.transition = 'opacity 0.7s ease 0.3s';
    var whObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.style.opacity = '1';
          whObs.unobserve(e.target);
        }
      });
    }, { threshold: 0.2 });
    whObs.observe(whCanvas);
  }

  /* ── Table rows — translateX fade only (rotateY removed) ── */
  function animateTableRows(container) {
    var rows = container.querySelectorAll('tbody tr');
    rows.forEach(function (row, i) {
      row.style.opacity = '0';
      row.style.transform = 'translateX(-12px)';
      row.style.transition = 'opacity 0.3s ease ' + (i * 0.04) + 's, transform 0.4s cubic-bezier(.22,1,.36,1) ' + (i * 0.04) + 's';
    });
    var tObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.querySelectorAll('tbody tr').forEach(function (row) {
            row.style.opacity = '1';
            row.style.transform = 'translateX(0)';
          });
          tObs.unobserve(e.target);
        }
      });
    }, { threshold: 0.15 });
    tObs.observe(container);
  }
  document.querySelectorAll('.table-scroll').forEach(animateTableRows);
})();