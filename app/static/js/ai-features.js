/* =============================================================================
   InventoryLogix v3.0 — shared client scripts.
   Adds: theme persistence, toast helper, EOQ calculator (Chart.js + 3D surface).
   ============================================================================= */
(function () {
    'use strict';

    // ----- THEME (applied from settings/localStorage; sidebar toggle removed) -----
    document.addEventListener('DOMContentLoaded', () => {
        const saved = (() => { try { return localStorage.getItem('stockflow-theme'); } catch (e) { return null; } })();
        if (saved) document.documentElement.setAttribute('data-theme', saved);
    });

    // ----- TOAST -----
    function soundEnabled() {
        return !!(window.appSettings && window.appSettings.sound_alerts === 'on');
    }
    function playBeep(freq) {
        try {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            const ctx = new Ctx();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = freq || 880;
            gain.gain.setValueAtTime(0.001, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.5);
        } catch (e) {}
    }
    function showToast(message, type) {
        type = type || 'info';
        if (soundEnabled()) playBeep(type === 'error' ? 320 : 880);
        const region = document.getElementById('toastRegion');
        if (!region) return;
        const t = document.createElement('div');
        t.className = 'toast toast-' + type;
        t.setAttribute('role', 'status');
        t.textContent = message;
        region.appendChild(t);
        setTimeout(() => { t.classList.add('toast-out'); setTimeout(() => t.remove(), 320); }, 3200);
    }
    window.showToast = showToast;

    // ----- CSRF helper -----
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }
    async function api(url, options) {
        options = options || {};
        options.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
        if (csrfToken()) options.headers['X-CSRFToken'] = csrfToken();
        const resp = await fetch(url, options);
        let data;
        try { data = await resp.json(); } catch (e) { data = { success: resp.ok, data: null }; }
        if (!resp.ok) {
            showToast((data && data.error && data.error.message) || ('Request failed (' + resp.status + ')'), 'error');
            throw new Error('API error');
        }
        return data;
    }
    window.StockflowAPI = { api, csrfToken };

    // ----- EOQ calculator -----
    function eoqCalc(d, s, h) { return Math.sqrt((2 * d * s) / h); }
    function initEOQ(cfg) {
        if (!cfg) return;

        // Wait for Chart.js and Plotly to be available
        function waitForLibs() {
            return new Promise(resolve => {
                if (window.Chart && window.Plotly) {
                    resolve();
                    return;
                }
                const check = setInterval(() => {
                    if (window.Chart && window.Plotly) {
                        clearInterval(check);
                        resolve();
                    }
                }, 100);
            });
        }

        const compute = () => {
            const d = parseFloat(cfg.demand?.value || 0);
            const s = parseFloat(cfg.ordering?.value || 0);
            const h = parseFloat(cfg.holding?.value || 0);
            const lead = parseFloat(cfg.lead?.value || 0);
            const safety = parseFloat(cfg.safety?.value || 0);

            // Update result elements safely
            const safeSet = (el, val) => { if (el) el.textContent = val; };

            if (!(d > 0 && s >= 0 && h > 0)) {
                safeSet(cfg.out.eoq, '—');
                safeSet(cfg.out.orders, '—');
                safeSet(cfg.out.rop, '—');
                safeSet(cfg.out.total, '—');
                return;
            }
            const eoq = eoqCalc(d, s, h);
            const orders = d / eoq;
            const daily = d / 365;
            const rop = daily * lead + safety;
            const total = (orders * s) + (eoq / 2) * h;
            safeSet(cfg.out.eoq, Math.round(eoq));
            safeSet(cfg.out.orders, orders.toFixed(1));
            safeSet(cfg.out.rop, Math.round(rop));
            safeSet(cfg.out.total, '₹ ' + total.toLocaleString('en-IN', {maximumFractionDigits: 0}));
            drawCurve(cfg.chartId, eoq, d, s, h);
        };

        function drawCurve(id, eoq, d, s, h) {
            const el = document.getElementById(id);
            if (!el || !window.Chart) return;
            const points = [];
            const maxQ = Math.max(eoq * 2.2, 50);
            for (let q = 1; q <= maxQ; q += Math.max(1, Math.round(maxQ / 60))) {
                const total = (d / q) * s + (q / 2) * h;
                points.push({ x: q, y: total });
            }
            if (window.__eoqChart) window.__eoqChart.destroy();
            window.__eoqChart = new Chart(el, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Total cost',
                        data: points,
                        borderColor: '#2563eb',
                        backgroundColor: 'rgba(37,99,235,0.18)',
                        fill: true,
                        pointRadius: 0,
                        parsing: false,
                        tension: 0.2,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, datalabels: { display: function(ctx) { var i = ctx.dataIndex; var n = ctx.dataset.data.length; return i === 0 || i === n - 1 || i === Math.floor(n / 2); }, formatter: function(v) { return '₹' + Number(v.y).toLocaleString('en-IN'); }, anchor: 'end', align: 'top', font: { size: 9, weight: '600' }, color: getDlColor } },
                    scales: {
                        x: { type: 'linear', title: { display: true, text: 'Order quantity' } },
                        y: { title: { display: true, text: 'Annual cost (₹)' } },
                    },
                },
            });
        }

        // Event listeners
        [cfg.demand, cfg.ordering, cfg.holding, cfg.lead, cfg.safety].forEach(el => {
            if (el) el.addEventListener('input', compute);
        });

        // Initial compute
        compute();

        // Wait for libraries then draw chart and 3D surface
        waitForLibs().then(() => {
            drawCurve(cfg.chartId, eoqCalc(
                parseFloat(cfg.demand?.value || 0),
                parseFloat(cfg.ordering?.value || 0),
                parseFloat(cfg.holding?.value || 0)
            ),
            parseFloat(cfg.demand?.value || 0),
            parseFloat(cfg.ordering?.value || 0),
            parseFloat(cfg.holding?.value || 0));

            // 3D surface
            api(cfg.sensitivityUrl + '?demand=' + (cfg.demand?.value || 0) +
                '&ordering_cost=' + (cfg.ordering?.value || 0) +
                '&holding_cost=' + (cfg.holding?.value || 0))
                .then(res => {
                    const el = document.getElementById(cfg.surfaceId);
                    if (!el || !window.Plotly) return;
                    const data = [{
                        x: res.data.x, y: res.data.y, z: res.data.z,
                        type: 'surface', colorscale: 'Viridis',
                    }];
                    Plotly.react(el, data, {
                        margin: { t: 0, l: 0, r: 0, b: 0 },
                        paper_bgcolor: 'transparent',
                        scene: {
                            xaxis: { title: 'Ordering cost' },
                            yaxis: { title: 'Demand' },
                            zaxis: { title: 'Total cost' },
                        },
                    }, { responsive: true, displaylogo: false });
                })
                .catch(err => console.error('3D surface error:', err));
        });
    }
    window.StockflowEOQ = { init: initEOQ };

    // ----- Search quick navigation -----
    document.addEventListener('DOMContentLoaded', () => {
        const search = document.getElementById('searchInput');
        if (!search) return;
        search.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                window.location = '/inventory?search=' + encodeURIComponent(search.value);
            }
        });
    });
})();
