"""Data export service."""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import Response

from ..repositories import (
    ProductRepository,
    MovementRepository,
    SupplierRepository,
    PurchaseOrderRepository,
)
from ..services import ProductService, MovementService


class ExportService:
    """Service for exporting data to CSV."""

    @staticmethod
    def export_products() -> Response:
        """Export all products to CSV."""
        rows, _ = ProductRepository.list(search="", category="", limit=10000)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["SKU", "Product", "Category", "Warehouse", "Stock", "Reorder", "Price", "Supplier"])
        for r in rows:
            writer.writerow([r["sku"], r["name"], r["category"] or "", r.get("warehouse") or "",
                             r["current_stock"], r["reorder_point"], float(r.get("unit_price") or 0),
                             r.get("supplier_name") or ""])
        buf.seek(0)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=products.csv"}
        )

    @staticmethod
    def export_inventory() -> Response:
        """Export inventory status to CSV."""
        # We can reuse the products export but maybe add more fields
        return ExportService.export_products()

    @staticmethod
    def export_movements(limit: int = 10000) -> Response:
        """Export movements to CSV."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT m.id, p.sku, p.name, m.type, m.quantity, m.reference, m.notes,
                       u.username AS user_name, m.created_at
                FROM movements m
                LEFT JOIN products p ON m.product_id = p.id
                LEFT JOIN users u ON m.user_id = u.id
                ORDER BY m.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ID", "SKU", "Product", "Type", "Quantity", "Reference", "Notes", "User", "Date"])
            for r in rows:
                writer.writerow([r["id"], r["sku"] or "", r["name"] or "", r["type"], r["quantity"],
                                 r["reference"] or "", r["notes"] or "", r["user_name"] or "",
                                 r["created_at"]])
            buf.seek(0)
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=movements.csv"}
            )

    @staticmethod
    def export_suppliers() -> Response:
        """Export suppliers to CSV."""
        with get_cursor() as cur:
            cur.execute("SELECT id, name, location, lead_days, spend_amount, reliability, tone FROM suppliers ORDER BY name")
            rows = cur.fetchall()
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ID", "Name", "Location", "Lead Days", "Spend Amount", "Reliability", "Tone"])
            for r in rows:
                writer.writerow([r["id"], r["name"], r["location"] or "", r["lead_days"], r["spend_amount"],
                                 r["reliability"], r["tone"]])
            buf.seek(0)
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=suppliers.csv"}
            )

    @staticmethod
    def export_purchase_orders() -> Response:
        """Export purchase orders to CSV."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT po.id, po.po_number, s.name AS supplier_name, p.name AS product_name,
                       po.quantity, po.unit_cost, po.status, po.eta_date, po.created_at
                FROM purchase_orders po
                LEFT JOIN suppliers s ON po.supplier_id = s.id
                LEFT JOIN products p ON po.product_id = p.id
                ORDER BY po.created_at DESC
                """
            )
            rows = cur.fetchall()
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["ID", "PO Number", "Supplier", "Product", "Quantity", "Unit Cost", "Status", "ETA Date", "Date"])
            for r in rows:
                writer.writerow([r["id"], r["po_number"], r["supplier_name"] or "", r["product_name"] or "",
                                 r["quantity"], r["unit_cost"], r["status"], r["eta_date"], r["created_at"]])
            buf.seek(0)
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=purchase_orders.csv"}
            )