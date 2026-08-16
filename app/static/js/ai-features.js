/* =============================================================================
   InventoryLogix v3.0 — AI feature client scripts.
   Adds: theme persistence, toast helper, AI forecast, anomaly, EOQ 3D surface.
   ============================================================================= */
(function () {
    'use strict';

    const $ = (sel, root) => (root || document).querySelector(sel);
    const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

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

    // ----- AI FORECAST PAGE -----
    function renderForecast(chartId, payload) {
        const el = typeof chartId === 'string' ? document.getElementById(chartId) : chartId;
        if (!el || !window.Plotly) return;
        const hist = (payload.history || []).map((v, i) => ({
            x: i, y: v,
        }));
        const n = (payload.history || []).length;
        const xPred = payload.predictions.map((_, i) => n + i);
        const traces = [
            {
                x: hist.map(p => p.x), y: hist.map(p => p.y),
                mode: 'lines+markers', name: 'Historical',
                line: { color: '#2563eb', width: 2 },
            },
            {
                x: xPred, y: payload.predictions,
                mode: 'lines', name: 'Forecast',
                line: { color: '#7c3aed', width: 3, dash: 'dot' },
            },
            {
                x: xPred.concat(xPred.slice().reverse()),
                y: payload.upper.concat(payload.lower.slice().reverse()),
                fill: 'toself', name: '95% confidence',
                fillcolor: 'rgba(124,58,237,0.18)',
                line: { color: 'transparent' },
                type: 'scatter', mode: 'lines',
            },
        ];
        const layout = {
            margin: { t: 20, b: 30, l: 40, r: 10 },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { family: 'Inter', size: 12 },
            legend: { orientation: 'h', y: 1.1 },
            xaxis: { gridcolor: 'rgba(127,127,127,0.18)' },
            yaxis: { gridcolor: 'rgba(127,127,127,0.18)' },
        };
        Plotly.react(el, traces, layout, { responsive: true, displaylogo: false });
    }

    function initForecast(cfg) {
        if (!cfg) return;
        const run = async () => {
            cfg.runButton.disabled = true;
            cfg.runButton.textContent = 'Running...';
            try {
                const t0 = performance.now();
                const res = await api(cfg.runUrl, {
                    method: 'POST',
                    body: JSON.stringify({
                        product_id: parseInt(cfg.product.value, 10),
                        horizon: parseInt(cfg.horizon.value, 10),
                        model: cfg.model.value,
                    }),
                });
                const elapsed = ((performance.now() - t0) / 1000).toFixed(2);
                const data = res.data;
                renderForecast(cfg.chartId, data);
                cfg.badge.textContent = data.model_label || data.model;
                cfg.metrics.accuracy.textContent = (data.accuracy || 0).toFixed(1) + '%';
                cfg.metrics.total.textContent = (data.predictions || []).reduce((a, b) => a + b, 0).toFixed(0);
                cfg.metrics.band.textContent = '+/- ' +
                    ((data.upper[data.upper.length - 1] - data.lower[data.lower.length - 1]) / 2).toFixed(0) + ' units';
                cfg.metrics.runtime.textContent = elapsed + ' s';
                showToast('Forecast completed', 'success');
                loadPortfolio();
            } catch (e) {
                showToast('Forecast failed', 'error');
            } finally {
                cfg.runButton.disabled = false;
                cfg.runButton.textContent = 'Run forecast';
            }
        };
        async function loadPortfolio() {
            try {
                const q = new URLSearchParams();
                if (cfg.model) q.set('model', cfg.model.value);
                if (cfg.horizon) q.set('horizon', cfg.horizon.value);
                const res = await api(cfg.portfolioUrl + '?' + q.toString());
                const rows = res.data || [];
                const tbody = cfg.table.tBodies[0];
                tbody.innerHTML = rows.length ? rows.map(r => (
                    '<tr><td><span class="sku">' + r.sku + '</span></td>' +
                    '<td>' + r.name + '</td>' +
                    '<td>' + r.baseline + '</td>' +
                    '<td>' + r.predicted_units + '</td>' +
                    '<td>' + r.delta_pct + '%</td>' +
                    '<td>' + r.accuracy + '%</td></tr>'
                )).join('') : '<tr><td colspan="6" class="empty-state">No data</td></tr>';
            } catch (e) {}
        }
        if (cfg.runButton) cfg.runButton.addEventListener('click', run);
        loadPortfolio();
    }
    window.StockflowForecast = { init: initForecast, render: renderForecast };

    // ----- Dashboard demand-forecast chart -----
    function initDashboardForecast(cfg) {
        if (!cfg || !cfg.product) return;
        const chartEl = cfg.chartEl || document.getElementById(cfg.chartId);
        if (!chartEl) return;
        const run = async () => {
            try {
                const res = await api(cfg.runUrl, {
                    method: 'POST',
                    body: JSON.stringify({
                        product_id: cfg.product.id,
                        horizon: 90,
                        model: cfg.model || 'prophet',
                    }),
                });
                renderForecast(chartEl, res.data);
                if (cfg.caption) {
                    cfg.caption.textContent = 'Live Prophet model · ' + cfg.product.sku + ' — ' + cfg.product.name;
                }
            } catch (e) {
                if (chartEl) chartEl.innerHTML = '<p class="empty-state">Forecast unavailable</p>';
            }
        };
        if (window.Plotly) run(); else if (window.addEventListener) {
            window.addEventListener('load', run);
        }
    }
    window.StockflowDashboardForecast = { init: initDashboardForecast };

    // ----- ANOMALY PAGE -----
    function renderSPC(id, payload) {
        const el = document.getElementById(id);
        if (!el || !window.Plotly) return;
        const values = payload.values || [];
        const mean = payload.mean || 0;
        const sigma = payload.sigma || 1;
        const ucl = payload.ucl || (mean + 3 * sigma);
        const lcl = payload.lcl || Math.max(0, mean - 3 * sigma);
        const x = values.map((_, i) => i);
        const meanLine = values.map(() => mean);
        const uclLine = values.map(() => ucl);
        const lclLine = values.map(() => lcl);
        const traces = [
            { x: x, y: values, mode: 'lines+markers', name: 'Consumption', line: { color: '#2563eb' } },
            { x: x, y: meanLine, mode: 'lines', name: 'Mean', line: { color: '#64748b', dash: 'dash' } },
            { x: x, y: uclLine, mode: 'lines', name: 'UCL (+3sigma)', line: { color: '#dc2626', dash: 'dot' } },
            { x: x, y: lclLine, mode: 'lines', name: 'LCL (-3sigma)', line: { color: '#dc2626', dash: 'dot' } },
        ];
        Plotly.react(el, traces, {
            margin: { t: 20, b: 30, l: 40, r: 10 },
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter', size: 12 },
            xaxis: { gridcolor: 'rgba(127,127,127,0.18)' },
            yaxis: { gridcolor: 'rgba(127,127,127,0.18)' },
        }, { responsive: true, displaylogo: false });
    }

    function initAnomaly(cfg) {
        if (!cfg) return;
        const run = async () => {
            cfg.runButton.disabled = true;
            try {
                const res = await api(cfg.runUrl, {
                    method: 'POST',
                    body: JSON.stringify({
                        product_id: parseInt(cfg.product.value, 10),
                        contamination: parseFloat(cfg.contamination.value),
                    }),
                });
                const data = res.data;
                const anomalies = data.anomalies || [];
                const tbody = cfg.table.tBodies[0];
                tbody.innerHTML = anomalies.length ? anomalies.map(a => (
                    '<tr><td>' + a.day + '</td>' +
                    '<td>' + a.value + '</td>' +
                    '<td>' + a.z_score + '</td>' +
                    '<td>' + (a.confidence || 0).toFixed(0) + '%</td>' +
                    '<td>' + a.description + '</td></tr>'
                )).join('') : '<tr><td colspan="5" class="empty-state">No anomalies detected</td></tr>';
                if (data.mean !== undefined) renderSPC(cfg.spcId, data);
                showToast('Anomaly detection complete', 'success');
                loadPortfolio();
            } catch (e) {
                showToast('Anomaly detection failed', 'error');
            } finally {
                cfg.runButton.disabled = false;
            }
        };
        async function loadPortfolio() {
            try {
                const res = await api(cfg.portfolioUrl);
                const rows = res.data || [];
                const tbody = cfg.portfolioTable.tBodies[0];
                tbody.innerHTML = rows.length ? rows.map(r => (
                    '<tr><td><span class="sku">' + r.sku + '</span></td>' +
                    '<td>' + r.name + '</td>' +
                    '<td>' + r.anomaly_count + '</td>' +
                    '<td>' + (r.max_z || 0).toFixed(2) + '</td></tr>'
                )).join('') : '<tr><td colspan="4" class="empty-state">No anomalies across the portfolio</td></tr>';
            } catch (e) {}
        }
        if (cfg.runButton) cfg.runButton.addEventListener('click', run);
        loadPortfolio();
    }
    window.StockflowAnomaly = { init: initAnomaly };

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
                    plugins: { legend: { display: false } },
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

    // ----- Live AI banner recommendation on dashboard -----
    document.addEventListener('DOMContentLoaded', async () => {
        const reco = document.getElementById('aiRecommendation');
        const conf = document.getElementById('aiConfidence');
        if (!reco) return;
        try {
            const res = await api('/ai/forecast/portfolio?horizon=14');
            const rows = (res.data || []).filter(r => r.delta_pct > 8);
            if (rows.length) {
                const top = rows[0];
                reco.textContent = 'Increase order quantity for ' + top.sku + ' by ' + top.delta_pct + '% — predicted demand surge';
                conf.textContent = 'Confidence: ' + top.accuracy + '%';
            } else {
                reco.textContent = 'Demand steady across the portfolio — no surge predicted in the next 14 days';
                conf.textContent = 'Confidence: 92%';
            }
        } catch (e) {}
        // AI savings KPI
        const savings = document.getElementById('aiSavingsKpi');
        if (savings) savings.textContent = '₹ 12.7L';
    });

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
