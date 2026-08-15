/* =============================================================================
   InventoryLogix AI — Landing page animations.
   Count-up KPIs, SVG line-chart draw, animated category bars, scroll reveals.
   ============================================================================= */
(function () {
  'use strict';

  var data = window.landingData || {};
  var series = Array.isArray(data.series) ? data.series : [];
  var dates = Array.isArray(data.dates) ? data.dates : [];
  var categories = Array.isArray(data.categories) ? data.categories : [];

  var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ----- Reveal on scroll -----
  function initReveals() {
    var els = document.querySelectorAll('.reveal');
    if (!('IntersectionObserver' in window) || prefersReduced) {
      els.forEach(function (el) { el.classList.add('in-view'); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    els.forEach(function (el) { io.observe(el); });
  }

  // ----- Number formatting -----
  function formatNumber(n, prefix) {
    n = Math.round(n || 0);
    var out;
    if (n >= 10000000) out = (n / 10000000).toFixed(1).replace(/\.0$/, '') + 'Cr';
    else if (n >= 100000) out = (n / 100000).toFixed(1).replace(/\.0$/, '') + 'L';
    else out = n.toLocaleString('en-IN');
    return (prefix || '') + out;
  }

  // ----- Count-up animation -----
  function animateCount(el) {
    var target = parseFloat(el.dataset.count || '0');
    var prefix = el.dataset.prefix || '';
    var suffix = el.dataset.suffix || '';
    if (prefersReduced) {
      el.textContent = formatNumber(target, prefix) + suffix;
      return;
    }
    var duration = 1400;
    var start = null;
    function frame(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      el.textContent = formatNumber(target * eased, prefix) + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function initCountUps() {
    var els = document.querySelectorAll('[data-count]');
    if (!('IntersectionObserver' in window) || prefersReduced) {
      els.forEach(animateCount);
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCount(entry.target);
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.4 });
    els.forEach(function (el) { io.observe(el); });
  }

  // ----- SVG line chart (draw-on animation) -----
  function initLineChart() {
    var svg = document.getElementById('lineChart');
    if (!svg) return;
    var W = 556, H = 210, padL = 20, padR = 540, padT = 20, padB = 186;
    var values = series.length ? series : [0];
    var max = Math.max.apply(null, values) || 1;
    var stepX = values.length > 1 ? (padR - padL) / (values.length - 1) : 0;

    var points = values.map(function (v, i) {
      var x = padL + i * stepX;
      var y = padB - (v / max) * (padB - padT);
      return { x: x, y: y };
    });

    var line = points.map(function (p, i) {
      return (i === 0 ? 'M' : 'L') + p.x.toFixed(1) + ' ' + p.y.toFixed(1);
    }).join(' ');

    var area = 'M' + padL + ' ' + padB + ' ' + line.slice(1) + ' L' + padR + ' ' + padB + ' Z';

    var defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML =
      '<linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="#7ed0af" stop-opacity="0.45"/>' +
        '<stop offset="100%" stop-color="#7ed0af" stop-opacity="0"/>' +
      '</linearGradient>';
    svg.appendChild(defs);

    var areaPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    areaPath.setAttribute('d', area);
    areaPath.setAttribute('fill', 'url(#chartFill)');
    areaPath.setAttribute('opacity', '0');

    var linePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    linePath.setAttribute('d', line);
    linePath.setAttribute('fill', 'none');
    linePath.setAttribute('stroke', '#7ed0af');
    linePath.setAttribute('stroke-width', '2.5');
    linePath.setAttribute('stroke-linecap', 'round');
    linePath.setAttribute('stroke-linejoin', 'round');

    var len = linePath.getTotalLength ? linePath.getTotalLength() : 600;
    if (!prefersReduced) {
      linePath.style.strokeDasharray = len;
      linePath.style.strokeDashoffset = len;
    }

    svg.appendChild(areaPath);
    svg.appendChild(linePath);

    points.forEach(function (p, i) {
      var c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('cx', p.x.toFixed(1));
      c.setAttribute('cy', p.y.toFixed(1));
      c.setAttribute('r', values[i] > 0 ? 3 : 1.8);
      c.setAttribute('fill', '#0a1115');
      c.setAttribute('stroke', '#7ed0af');
      c.setAttribute('stroke-width', '2');
      c.setAttribute('opacity', '0');
      c.style.transition = 'opacity 400ms ease ' + (200 + i * 40) + 'ms';
      svg.appendChild(c);
      requestAnimationFrame(function () { c.setAttribute('opacity', '1'); });
    });

    if (!prefersReduced) {
      setTimeout(function () {
        linePath.style.transition = 'stroke-dashoffset 1500ms ease';
        linePath.style.strokeDashoffset = '0';
        areaPath.style.transition = 'opacity 900ms ease 600ms';
        areaPath.setAttribute('opacity', '1');
      }, 250);
    } else {
      areaPath.setAttribute('opacity', '1');
    }

    // X-axis labels (first, middle, last)
    var tags = document.getElementById('chartTags');
    if (tags && dates.length) {
      var picks = [];
      if (dates.length <= 6) picks = dates;
      else picks = [dates[0], dates[Math.floor(dates.length / 2)], dates[dates.length - 1]];
      picks.forEach(function (d) {
        var span = document.createElement('span');
        span.textContent = d;
        tags.appendChild(span);
      });
    }
  }

  // ----- Category bars -----
  function initCatBars() {
    var wrap = document.getElementById('catBars');
    if (!wrap || !categories.length) {
      if (wrap) wrap.innerHTML = '<p style="color:var(--lp-muted);font-size:0.8rem;">No category data yet.</p>';
      return;
    }
    var max = Math.max.apply(null, categories.map(function (c) { return c.count; })) || 1;
    var bars = [];
    categories.forEach(function (c) {
      var row = document.createElement('div');
      row.className = 'cat-row';
      row.innerHTML =
        '<span class="cat-name"></span>' +
        '<div class="cat-track"><div class="cat-fill"></div></div>' +
        '<span class="cat-val"></span>';
      row.querySelector('.cat-name').textContent = c.category;
      row.querySelector('.cat-val').textContent = c.count;
      wrap.appendChild(row);
      bars.push(row.querySelector('.cat-fill'));
    });
    var t = 150;
    bars.forEach(function (fill, i) {
      setTimeout(function () {
        fill.style.width = (categories[i].count / max) * 100 + '%';
      }, t + i * 90);
    });
  }

  function init() {
    initReveals();
    initCountUps();
    initLineChart();
    initCatBars();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();