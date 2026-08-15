document.addEventListener("DOMContentLoaded", function () {
  const productSelect = document.getElementById("movementProduct");
  const typeSelect = document.getElementById("movementType");
  const qtyInput = document.getElementById("movementQuantity");
  const previewResult = document.getElementById("movementPreview");
  const previewNotice = document.getElementById("movementNotice");

  if (!productSelect || !previewResult) return;

  function refresh() {
    const option = productSelect.options[productSelect.selectedIndex];
    const stock = parseInt(option?.dataset.stock, 10) || 0;
    const qty = parseInt(qtyInput?.value, 10) || 0;
    const type = typeSelect?.value || 'IN';
    let next = stock;
    if (type === 'OUT') next = stock - qty;
    else next = stock + qty;

    previewResult.textContent = next < 0 ? 'Blocked' : formatNumber(next) + ' units';
    previewResult.style.color = next < 0 ? 'var(--red)' : 'var(--ink)';

    if (previewNotice) {
      if (next < 0) {
        previewNotice.textContent = 'This stock-out would create a negative balance. Use an adjustment for corrections.';
      } else if (type === 'OUT') {
        previewNotice.textContent = 'Stock out of ' + formatNumber(qty) + ' units. Balance moves from ' + formatNumber(stock) + ' to ' + formatNumber(next) + '.';
      } else if (qty > 0) {
        previewNotice.textContent = 'Stock in of ' + formatNumber(qty) + ' units. Balance moves from ' + formatNumber(stock) + ' to ' + formatNumber(next) + '.';
      } else {
        previewNotice.textContent = 'Choose a quantity to see the projected balance.';
      }
    }
  }

  [productSelect, typeSelect, qtyInput].forEach(function (el) {
    if (el) {
      el.addEventListener("input", refresh);
      el.addEventListener("change", refresh);
    }
  });
  refresh();
});