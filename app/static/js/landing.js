// ============================================================
// INVENTORYLOGIX — ADAPTIVE INK + 3D SCENE + REVEAL ANIMATIONS
// Ported from NexStock landing1.html with InventoryLogix data
// ============================================================

(() => {
  const $  = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];

  /* ============================================================
     NAV SCROLL + MOBILE MENU
     ============================================================ */
  const nav = $('#nav');
  addEventListener('scroll', () => nav.classList.toggle('scrolled', scrollY > 24), { passive: true });

  $('#menuBtn')?.addEventListener('click', () => nav.classList.toggle('open'));
  $$('#navLinks a').forEach(a => a.addEventListener('click', () => nav.classList.remove('open')));

  /* ============================================================
     PAGE LOAD TRANSITIONS — [data-anim] elements
     ============================================================ */
  requestAnimationFrame(() => $$('[data-anim]').forEach((el, i) => {
    el.style.transitionDelay = (i * 90) + 'ms';
    el.classList.add('loaded');
  }));

  /* ============================================================
     SCROLL REVEAL — .reveal elements (IntersectionObserver)
     ============================================================ */
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }), { threshold: .16, rootMargin: '0px 0px -40px' });
  $$('.reveal').forEach(el => io.observe(el));

  /* ============================================================
     COUNTER ANIMATIONS (IntersectionObserver)
     ============================================================ */
  const count = el => {
    const end = parseFloat(el.dataset.target), dec = +(el.dataset.decimals || 0);
    const suf = el.dataset.suffix || '', pre = el.dataset.prefix || '';
    const t0 = performance.now(), D = 1600;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { 
      el.textContent = pre + end.toFixed(dec) + suf; 
      return; 
    }
    const step = n => {
      const p = Math.min(1, (n - t0) / D), e = 1 - Math.pow(1 - p, 3);
      el.textContent = pre + (end * e).toFixed(dec) + suf;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  const io2 = new IntersectionObserver(es => es.forEach(e => {
    if (e.isIntersecting) { count(e.target); io2.unobserve(e.target); }
  }), { threshold: .6 });
  $$('.m-num').forEach(el => io2.observe(el));

  /* ============================================================
     FEATURE HOVER EFFECT (mouse position for radial gradient)
     ============================================================ */
  $$('.feature').forEach(c => c.addEventListener('mousemove', e => {
    const r = c.getBoundingClientRect();
    c.style.setProperty('--mx', (e.clientX - r.left) + 'px');
    c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  }));

  /* ============================================================
     DASHBOARD STAGE 3D TILT (mouse parallax)
     ============================================================ */
  const stage = $('#stage');
  if (stage && matchMedia('(hover:hover) and (pointer:fine)').matches) {
    stage.addEventListener('mousemove', e => {
      const r = stage.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      stage.style.transform = `perspective(1200px) rotateX(${(-y * 5).toFixed(2)}deg) rotateY(${(x * 7).toFixed(2)}deg)`;
    });
    stage.addEventListener('mouseleave', () => stage.style.transform = '');
  }

  /* ============================================================
     INVENTORY MIX — populate SKU list from categories data
     ============================================================ */
  const catBars = $('#catBars');
  if (catBars && window.LANDING_CATEGORIES) {
    const cats = window.LANDING_CATEGORIES;
    const maxCount = Math.max(...cats.map(c => c.count), 1);
    const colors = ['#34d399', '#fbbf24', '#fb7185', '#38bdf8', '#818cf8', '#c084fc', '#f472b6'];
    catBars.innerHTML = cats.slice(0, 7).map((c, i) => {
      const pct = Math.round((c.count / maxCount) * 100);
      const color = colors[i % colors.length];
      return `<div class="sku">
        <span class="dot" style="background:${color}"></span>
        <div class="s-main">
          <div class="s-name">${c.category}</div>
          <div class="s-sub">${c.count} SKUs</div>
        </div>
        <div class="bar"><i style="--w:${pct}%"></i></div>
      </div>`;
    }).join('');
  }

  /* ============================================================
     BAR ANIMATIONS (SKU velocity bars)
     ============================================================ */
  const barObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.querySelectorAll('.bar i').forEach(bar => {
          bar.style.width = bar.style.getPropertyValue('--w') || '0%';
        });
        barObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });
  
  const skuList = $('.sku-list');
  if (skuList) barObserver.observe(skuList);

  // Fallback for bars
  setTimeout(() => {
    if (skuList) {
      skuList.querySelectorAll('.bar i').forEach(bar => {
        if (bar.style.width === '0px' || bar.style.width === '0%' || !bar.style.width) {
          bar.style.width = bar.style.getPropertyValue('--w') || '0%';
        }
      });
    }
  }, 800);

  /* ============================================================
     CHART ANIMATION (line chart draw-in)
     ============================================================ */
  const chartObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('in');
        chartObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.3 });
  
  const chartPanel = $('.panel.chart');
  if (chartPanel) chartObserver.observe(chartPanel);

  // Fallback for chart
  setTimeout(() => {
    if (chartPanel && !chartPanel.classList.contains('in')) {
      chartPanel.classList.add('in');
    }
  }, 1000);

  /* ============================================================
     TOAST NOTIFICATION SYSTEM
     ============================================================ */
  const toast = $('#toast'), toastMsg = $('#toastMsg');
  let tt;
  const showToast = (msg, ok = true) => {
    if (!toast || !toastMsg) return;
    toastMsg.textContent = msg;
    const svg = toast.querySelector('svg');
    if (svg) svg.style.color = ok ? '#34d399' : '#fb7185';
    toast.classList.add('show');
    clearTimeout(tt); 
    tt = setTimeout(() => toast.classList.remove('show'), 3400);
  };

  /* ============================================================
     CTA FORM HANDLING
     ============================================================ */
  const form = $('#signup'), email = $('#email');
  if (form && email) {
    form.addEventListener('submit', e => {
      e.preventDefault();
      const v = email.value.trim();
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) {
        email.classList.add('err'); email.focus();
        showToast('Please enter a valid work email', false);
        return;
      }
      email.classList.remove('err'); email.value = '';
      showToast("You're on the list — check your inbox 🚀");
    });
    email.addEventListener('input', () => email.classList.remove('err'));
  }

})();