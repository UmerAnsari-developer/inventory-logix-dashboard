/* Dashboard 3D animations — panels, charts, tables */
(function () {
  if (document.body.classList.contains('landing')) return;

  /* ── 3D Panel Tilt on Hover ──────────────────────────────────── */
  document.querySelectorAll('.panel').forEach(function (panel) {
    panel.style.transformStyle = 'preserve-3d';
    panel.style.transition = 'transform 0.35s cubic-bezier(.22,1,.36,1), box-shadow 0.35s ease';

    panel.addEventListener('mousemove', function (e) {
      var rect = panel.getBoundingClientRect();
      var x = (e.clientX - rect.left) / rect.width - 0.5;
      var y = (e.clientY - rect.top) / rect.height - 0.5;
      panel.style.transform = 'perspective(800px) rotateY(' + (x * 6) + 'deg) rotateX(' + (-y * 6) + 'deg) scale(1.008)';
      panel.style.boxShadow = '0 ' + (12 + Math.abs(y) * 8) + 'px ' + (28 + Math.abs(x) * 12) + 'px rgba(0,0,0,0.25)';
    });

    panel.addEventListener('mouseleave', function () {
      panel.style.transform = 'perspective(800px) rotateY(0) rotateX(0) scale(1)';
      panel.style.boxShadow = '';
    });
  });

  /* ── SVG Chart 3D entrance (Stock movement) ──────────────────── */
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

  /* ── Inventory Mix bars 3D pop ───────────────────────────────── */
  document.querySelectorAll('.cat-fill').forEach(function (bar, i) {
    bar.style.transform = 'scaleX(0) rotateX(40deg)';
    bar.style.transformOrigin = 'left center';
    bar.style.transition = 'transform 0.6s cubic-bezier(.22,1,.36,1) ' + (0.15 + i * 0.08) + 's';
  });
  var catObs = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.style.transform = 'scaleX(1) rotateX(0)';
        catObs.unobserve(e.target);
      }
    });
  }, { threshold: 0.2 });
  document.querySelectorAll('.cat-fill').forEach(function (bar) { catObs.observe(bar); });

  /* ── Chart.js bars 3D entrance (Warehouse profile) ──────────── */
  var whCanvas = document.getElementById('warehouseProfileChart');
  if (whCanvas) {
    whCanvas.style.opacity = '0';
    whCanvas.style.transform = 'perspective(600px) rotateX(15deg) translateY(20px)';
    whCanvas.style.transition = 'opacity 0.7s ease 0.3s, transform 0.7s cubic-bezier(.22,1,.36,1) 0.3s';
    var whObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.style.opacity = '1';
          e.target.style.transform = 'perspective(600px) rotateX(0) translateY(0)';
          whObs.unobserve(e.target);
        }
      });
    }, { threshold: 0.2 });
    whObs.observe(whCanvas);
  }

  /* ── Table rows 3D stagger ──────────────────────────────────── */
  function animateTableRows(container) {
    var rows = container.querySelectorAll('tbody tr');
    rows.forEach(function (row, i) {
      row.style.opacity = '0';
      row.style.transform = 'translateX(-12px) rotateY(4deg)';
      row.style.transition = 'opacity 0.3s ease ' + (i * 0.04) + 's, transform 0.4s cubic-bezier(.22,1,.36,1) ' + (i * 0.04) + 's';
    });
    var tObs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.querySelectorAll('tbody tr').forEach(function (row) {
            row.style.opacity = '1';
            row.style.transform = 'translateX(0) rotateY(0)';
          });
          tObs.unobserve(e.target);
        }
      });
    }, { threshold: 0.15 });
    tObs.observe(container);
  }
  document.querySelectorAll('.table-scroll').forEach(animateTableRows);
})();
