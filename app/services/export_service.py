"""Data export service with streaming support for large datasets."""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Generator, Iterator

from flask import Response

from ..database import get_cursor


class ExportService:
    """Service for exporting data to CSV with streaming support."""

    @staticmethod
    def _stream_csv(rows_generator: Generator, header: list[str],
                    filename: str | None = None) -> Response:
        """Create a streaming CSV response."""
        # ADM-030: dated, entity-specific filename so downloads don't overwrite
        # each other and are distinguishable.
        download_name = filename or f"export_{date.today().isoformat()}.csv"
        def generate() -> Iterator[str]:
            # Write header
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(header)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
            
            # Write data rows in chunks
            chunk_size = 100
            chunk = []
            has_data = False
            for row in rows_generator:
                has_data = True
                chunk.append(row)
                if len(chunk) >= chunk_size:
                    for r in chunk:
                        writer.writerow(r)
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)
                    chunk = []
            
            # Write remaining rows
            if has_data:
                for r in chunk:
                    writer.writerow(r)
                yield output.getvalue()
        
        return Response(
            generate(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={download_name}"}
        )

    @staticmethod
    def _product_rows_generator(search: str = "", category: str = "", limit: int = 10000):
        """Generator for product rows."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT p.sku, p.name, p.category, p.warehouse, p.current_stock, 
                       p.reorder_point, p.unit_price, s.name AS supplier_name
                FROM products p
                LEFT JOIN suppliers s ON s.id = p.supplier_id
                WHERE p.deleted_at IS NULL
                  AND (%s = '' OR p.sku ILIKE %s OR p.name ILIKE %s OR p.category ILIKE %s)
                  AND (%s = '' OR p.category = %s)
                ORDER BY p.sku
                LIMIT %s
                """,
                (search, f"%{search}%", f"%{search}%", f"%{search}%", category, category, limit),
            )
            rows = cur.fetchall()
            for row in rows:
                yield [
                    row["sku"],
                    row["name"],
                    row["category"] or "",
                    row["warehouse"] or "",
                    row["current_stock"],
                    row["reorder_point"],
                    float(row["unit_price"] or 0),
                    row["supplier_name"] or ""
                ]

    @staticmethod
    def export_products() -> Response:
        """Export all products to CSV with streaming."""
        header = ["SKU", "Product", "Category", "Warehouse", "Stock", "Reorder", "Price", "Supplier"]
        return ExportService._stream_csv(
            ExportService._product_rows_generator(),
            header,
            filename=f"products_{date.today().isoformat()}.csv",
        )

    @staticmethod
    def export_inventory() -> Response:
        """Export inventory status to CSV with streaming."""
        return ExportService.export_products()

    @staticmethod
    def _movement_rows_generator(limit: int = 10000):
        """Generator for movement rows."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT m.id, p.sku, p.name, m.type, m.quantity, m.reference, m.notes,
                       u.username AS user_name, m.created_at
                FROM movements m
                LEFT JOIN products p ON m.product_id = p.id
                LEFT JOIN users u ON m.user_id = u.id
                WHERE m.deleted_at IS NULL
                ORDER BY m.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            for row in rows:
                yield [
                    row["id"],
                    row["sku"] or "",
                    row["name"] or "",
                    row["type"],
                    row["quantity"],
                    row["reference"] or "",
                    row["notes"] or "",
                    row["user_name"] or "",
                    row["created_at"]
                ]

    @staticmethod
    def export_movements(limit: int = 10000) -> Response:
        """Export movements to CSV with streaming."""
        header = ["ID", "SKU", "Product", "Type", "Quantity", "Reference", "Notes", "User", "Date"]
        return ExportService._stream_csv(
            ExportService._movement_rows_generator(limit),
            header,
            filename=f"movements_{date.today().isoformat()}.csv",
        )

    @staticmethod
    def _supplier_rows_generator():
        """Generator for supplier rows."""
        with get_cursor() as cur:
            cur.execute(
                "SELECT id, name, location, lead_days, spend_amount, reliability, tone FROM suppliers WHERE deleted_at IS NULL ORDER BY name"
            )
            rows = cur.fetchall()
            for row in rows:
                yield [
                    row["id"],
                    row["name"],
                    row["location"] or "",
                    row["lead_days"],
                    row["spend_amount"],
                    row["reliability"],
                    row["tone"]
                ]

    @staticmethod
    def export_suppliers() -> Response:
        """Export suppliers to CSV with streaming."""
        header = ["ID", "Name", "Location", "Lead Days", "Spend Amount", "Reliability", "Tone"]
        return ExportService._stream_csv(
            ExportService._supplier_rows_generator(),
            header,
            filename=f"suppliers_{date.today().isoformat()}.csv",
        )

    @staticmethod
    def _po_rows_generator():
        """Generator for purchase order rows."""
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT po.id, po.po_number, s.name AS supplier_name, p.name AS product_name,
                       po.quantity, po.unit_cost, po.status, po.eta_date, po.created_at
                FROM purchase_orders po
                LEFT JOIN suppliers s ON po.supplier_id = s.id
                LEFT JOIN products p ON po.product_id = p.id
                WHERE po.deleted_at IS NULL
                ORDER BY po.created_at DESC
                """
            )
            rows = cur.fetchall()
            for row in rows:
                yield [
                    row["id"],
                    row["po_number"],
                    row["supplier_name"] or "",
                    row["product_name"] or "",
                    row["quantity"],
                    row["unit_cost"],
                    row["status"],
                    row["eta_date"],
                    row["created_at"]
                ]

    @staticmethod
    def export_purchase_orders() -> Response:
        """Export purchase orders to CSV with streaming."""
        header = ["ID", "PO Number", "Supplier", "Product", "Quantity", "Unit Cost", "Status", "ETA Date", "Date"]
        return ExportService._stream_csv(
            ExportService._po_rows_generator(),
            header,
            filename=f"purchase_orders_{date.today().isoformat()}.csv",
        )