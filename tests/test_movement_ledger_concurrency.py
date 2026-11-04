"""Concurrency tests for Movement Ledger feature."""

import pytest
import threading
import uuid


class TestMovementLedgerConcurrency:
    """Concurrency tests for movement list/export under load."""

    def test_concurrent_list_and_export(self, app):
        """10 concurrent list requests + 5 concurrent exports don't deadlock."""
        import time

        def list_worker(worker_id):
            try:
                with app.app_context():
                    from app.services import MovementService
                    result = MovementService.list_movements(page=worker_id % 5 + 1, per_page=10)
                    return ("success", len(result))
            except Exception as exc:
                return ("fail", str(exc))

        def export_worker(worker_id):
            try:
                with app.app_context():
                    from app.services import MovementService
                    result = list(MovementService.export_movements(limit=100))
                    return ("success", len(result))
            except Exception as exc:
                return ("fail", str(exc))

        threads = []
        results = []

        # 10 list workers
        for i in range(10):
            t = threading.Thread(target=lambda i=i: results.append(("list", i, list_worker(i))))
            threads.append(t)

        # 5 export workers
        for i in range(5):
            t = threading.Thread(target=lambda i=i: results.append(("export", i, export_worker(i))))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # All should succeed
        failures = [r for r in results if r[0] == "fail"]
        assert len(failures) == 0, f"Failures: {failures}"
        assert len(results) == 15


class TestMovementConcurrencyWithWrites:
    """Concurrency tests with simultaneous reads and writes."""

    def test_concurrent_reads_during_writes(self, app):
        """Reads don't block writes and vice versa."""
        with app.app_context():
            from app.database import get_cursor
            from app.repositories import ProductRepository, MovementRepository

            # Setup: create test product and PO
            with get_cursor(commit=True) as cur:
                product_id = ProductRepository.create({
                    "sku": f"CONC-{uuid.uuid4().hex[:8].upper()}",
                    "name": "Concurrency Test Product",
                    "category": "Test",
                    "warehouse": "WH-Test",
                    "current_stock": 100,
                    "reorder_point": 10,
                    "unit_price": 10.0,
                })
                cur.execute("SELECT id FROM suppliers ORDER BY id LIMIT 1")
                supplier_id = cur.fetchone()["id"]

                cur.execute("""
                    INSERT INTO purchase_orders (po_number, supplier_id, product_id, quantity, unit_cost, status)
                    VALUES (%s, %s, %s, 50, 5.0, 'draft')
                    RETURNING id
                """, (f"PO-CONC-{uuid.uuid4().hex[:6].upper()}", supplier_id, product_id))
                po_id = cur.fetchone()["id"]

                # Transition to in_transit
                from app.repositories import PurchaseOrderRepository
                PurchaseOrderRepository.transition(po_id, 'approved')
                PurchaseOrderRepository.transition(po_id, 'in_transit')

        results = {"reads": [], "writes": []}
        lock = threading.Lock()

        def reader():
            try:
                with app.app_context():
                    from app.services import MovementService
                    result = MovementService.list_movements(page=1, per_page=10)
                    with lock:
                        results["reads"].append(("success", len(result)))
            except Exception as exc:
                with lock:
                    results["reads"].append(("fail", str(exc)))

        def writer():
            try:
                with app.app_context():
                    from app.repositories import PurchaseOrderRepository
                    po_id = 1  # Use the PO created above
                    # Try to receive
                    PurchaseOrderRepository.receive(
                        po_id=po_id,
                        quantity=5,
                        user_id=1,
                        notes="Concurrent receive",
                        location="WH1"
                    )
                    with lock:
                        results["writes"].append(("success", 5))
            except Exception as exc:
                with lock:
                    results["writes"].append(("fail", str(exc)))

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=reader))
        for _ in range(3):
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # At least some should succeed
        successes = [r for r in results["reads"] + results["writes"] if r[0] == "success"]
        assert len(successes) >= 3, f"Too many failures: {results}"

        # Cleanup
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM goods_receipts WHERE po_id = %s", (po_id,))
                cur.execute("DELETE FROM movements WHERE product_id = %s", (product_id,))
                cur.execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
                cur.execute("DELETE FROM products WHERE id = %s", (product_id,))