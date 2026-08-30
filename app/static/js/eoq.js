window.initEoqCalculator = function (form) {
  function getDlColor() { return document.documentElement.getAttribute('data-theme') === 'dark' ? '#e2e8f0' : '#1e293b'; }
  const resultEOQ = document.getElementById("resEOQ");
  const resultOrders = document.getElementById("resOrders");
  const resultDays = document.getElementById("resDays");
  const resultOrderCost = document.getElementById("resOrderCost");
  const resultHoldCost = document.getElementById("resHoldCost");
  const resultTotalCost = document.getElementById("resTotalCost");
  const resultInvestment = document.getElementById("resInvestment");
  const stockInsight = document.getElementById("stockInsight");
  const chartCanvas = document.getElementById("eoqChart");
  let chart = null;

  function readInput(id) {
    return parseFloat(document.getElementById(id)?.value);
  }

  function calculate() {
    const d = readInput("annualDemand");
    const s = readInput("orderingCost");
    const h = readInput("holdingCost");
    const price = readInput("unitPrice") || null;
    const stock = parseInt(document.getElementById("currentStock")?.value) || null;

    let eoq = null;
    if (d > 0 && s >= 0 && h > 0) {
      eoq = Math.sqrt((2 * d * s) / h);
    }

    if (eoq) {
      const orders = d / eoq;
      const days = 365 / orders;
      const orderCost = orders * s;
      const holdCost = (eoq / 2) * h;
      const totalCost = orderCost + holdCost;
      const investment = price ? eoq * price : null;

      resultEOQ.textContent = Math.round(eoq) + " units";
      resultOrders.textContent = orders.toFixed(2);
      resultDays.textContent = days.toFixed(1);
      resultOrderCost.textContent = "$" + orderCost.toFixed(2);
      resultHoldCost.textContent = "$" + holdCost.toFixed(2);
      resultTotalCost.textContent = "$" + totalCost.toFixed(2);
      resultInvestment.textContent = investment ? "$" + investment.toFixed(2) : "-";

      insight(eoq, stock);
      renderChart(d, s, h, eoq);
    } else {
      resultEOQ.textContent = "— units";
      if (stockInsight) stockInsight.textContent = "Enter valid positive numbers for demand, ordering cost, and holding cost.";
      if (chart) { chart.destroy(); chart = null; }
    }
  }

  function insight(eoq, stock) {
    if (!stockInsight) return;
    if (stock !== null && stock >= 0) {
      if (stock >= eoq) {
        stockInsight.innerHTML = 'Well stocked — current stock (' + formatNumber(stock) + ') exceeds the EOQ (' + Math.round(eoq) + '). No immediate order needed.';
      } else if (stock > 0) {
        stockInsight.innerHTML = 'Below EOQ — current stock (' + formatNumber(stock) + ') is below the recommended ' + Math.round(eoq) + '. Consider ordering ' + Math.round(eoq - stock) + ' units.';
      } else {
        stockInsight.innerHTML = 'Out of stock — order ' + Math.round(eoq) + ' units immediately.';
      }
    } else {
      stockInsight.textContent = "Enter a current stock value to see a recommendation.";
    }
  }

  function renderChart(d, s, h, eoq) {
    chartCanvas.style.display = "block";
    const ctx = chartCanvas.getContext("2d");
    if (chart) chart.destroy();

    const maxQ = Math.max(eoq * 3, 10);
    const step = Math.max(1, Math.floor(maxQ / 40));
    const labels = [], orderCosts = [], holdCosts = [], totalCosts = [];
    for (let q = step; q <= maxQ; q += step) {
      const oc = (d / q) * s;
      const hc = (q / 2) * h;
      labels.push(q);
      orderCosts.push(oc);
      holdCosts.push(hc);
      totalCosts.push(oc + hc);
    }

    const config = {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          { label: "Ordering cost", data: orderCosts, borderColor: "#3c78a5", fill: false, tension: 0.3, pointRadius: 0 },
          { label: "Holding cost", data: holdCosts, borderColor: "#e3a43c", fill: false, tension: 0.3, pointRadius: 0 },
          { label: "Total cost", data: totalCosts, borderColor: "#3d997c", fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } }, datalabels: { display: function(ctx) { var i = ctx.dataIndex; var n = ctx.dataset.data.length; return i === 0 || i === n - 1 || i === Math.floor(n / 2); }, formatter: function(v) { return '$' + Number(v).toLocaleString(); }, anchor: 'end', align: 'top', color: getDlColor, font: { size: 9, weight: '600' } } },
        scales: {
          x: { title: { display: true, text: "Order quantity (Q)" } },
          y: { title: { display: true, text: "Annual cost ($)" }, beginAtZero: true }
        }
      }
    };

    if (window.ChartAnnotation && window.ChartAnnotation.AnnotationPlugin) {
      Chart.register(window.ChartAnnotation.AnnotationPlugin);
      config.plugins.annotation = {
        annotations: {
          eoqLine: {
            type: "line",
            mode: "vertical",
            scaleID: "x",
            value: eoq,
            borderColor: "#c34c4c",
            borderWidth: 2,
            borderDash: [5, 5],
            label: { enabled: true, content: "EOQ " + Math.round(eoq), position: "start", backgroundColor: "#c34c4c" }
          }
        }
      };
    }

    chart = new Chart(ctx, config);
  }

  form.querySelectorAll("input").forEach(function (input) {
    input.addEventListener("input", calculate);
    input.addEventListener("change", calculate);
  });

  const clearBtn = document.getElementById("clearBtn");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      form.reset();
      calculate();
    });
  }

  calculate();
};