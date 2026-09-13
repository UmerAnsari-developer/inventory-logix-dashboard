"""Notification service — real-time monitoring and alert generation."""
from __future__ import annotations

from ..database import get_cursor
from ..repositories import NotificationRepository
from ..utils.cache import global_cache


def _admin_manager_ids() -> list[int]:
    with get_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE role IN ('admin','manager') AND is_active = TRUE")
        return [r["id"] for r in cur.fetchall()]


def clear_stale_notifications() -> int:
    """Delete notifications older than 30 days."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM notifications WHERE created_at < NOW() - INTERVAL '30 days'")
        return cur.rowcount


def check_reorder_alerts() -> int:
    """Check products below reorder point. Batch-creates notifications."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT sku, name, current_stock, reorder_point, warehouse
               FROM products
               WHERE current_stock <= reorder_point AND on_order <= 0"""
        )
        low_items = [dict(r) for r in cur.fetchall()]

    if not low_items:
        return 0

    users = _admin_manager_ids()
    if not users:
        return 0

    count = 0
    for item in low_items:
        title = f"Reorder: {item['sku']}"
        msg = f"{item['name']} ({item['sku']}) — stock {item['current_stock']}, reorder at {item['reorder_point']}."
        icon = "&#9888;" if item["current_stock"] == 0 else "&#9650;"
        for uid in users:
            NotificationRepository.create(uid, title, msg, icon, f"/inventory?search={item['sku']}")
            count += 1
    return count


def check_out_of_stock() -> int:
    """Check products at zero stock."""
    with get_cursor() as cur:
        cur.execute("SELECT sku, name, warehouse FROM products WHERE current_stock = 0")
        items = [dict(r) for r in cur.fetchall()]

    if not items:
        return 0

    users = _admin_manager_ids()
    if not users:
        return 0

    count = 0
    for item in items:
        title = f"Out of stock: {item['sku']}"
        msg = f"{item['name']} ({item['sku']}) in {item['warehouse']} is out of stock."
        for uid in users:
            NotificationRepository.create(uid, title, msg, "&#9888;", f"/inventory?search={item['sku']}")
            count += 1
    return count


def notify_movement(sku: str, product_name: str, movement_type: str, qty: int, warehouse: str) -> None:
    direction = "OUT" if movement_type == "OUT" else "IN"
    icon = "&#8595;" if direction == "OUT" else "&#8593;"
    title = f"Movement {direction}: {sku}"
    message = f"{qty}x {product_name} ({sku}) moved {direction} in {warehouse}."
    link = f"/inventory?search={sku}"
    for uid in _admin_manager_ids():
        NotificationRepository.create(uid, title, message, icon, link)


def notify_po_status(po_number: str, status: str, supplier_name: str) -> None:
    icons = {"approved": "&#10003;", "in_transit": "&#9992;", "received": "&#10004;", "draft": "&#9998;"}
    title = f"PO {status.replace('_', ' ').title()}: {po_number}"
    message = f"PO {po_number} ({supplier_name}) is now {status.replace('_', ' ')}."
    for uid in _admin_manager_ids():
        NotificationRepository.create(uid, title, message, icons.get(status, "&#9675;"), "/purchase-orders")


def notify_anomaly(sku: str, product_name: str, anomaly_type: str, details: str) -> None:
    title = f"Anomaly: {sku}"
    message = f"{product_name} ({sku}) — {anomaly_type}: {details}"
    for uid in _admin_manager_ids():
        NotificationRepository.create(uid, title, message, "&#9888;", "/ai/anomaly")


def run_monitoring_checks() -> dict:
    """Run checks at most once per 10 minutes (global_cache TTL)."""
    last_run = global_cache.get("notif_monitor_last")
    if last_run is not None:
        return {"skipped": True}
    global_cache.set("notif_monitor_last", True)
    clear_stale_notifications()
    return {
        "reorder": check_reorder_alerts(),
        "out_of_stock": check_out_of_stock(),
    }
