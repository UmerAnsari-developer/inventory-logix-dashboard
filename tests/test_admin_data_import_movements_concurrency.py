"""TDD Concurrency Tests for ADM-001: Movement import via _import_movements.

These tests mirror test_d1_concurrent_out_movements_cannot_go_negative but via the import path.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.routes.admin.data_import_routes import _import_movements
from app.database import get_cursor


def _mk_product(cur, *, stock: int = 0, sku_suffix: str = "") -> int:
    """Create a test product and return its ID."""
    sku = f"ADM001-CONC-{sku_suffix or uuid.uuid4().hex[:6].upper()}"
    cur.execute(
        """
        INSERT INTO products (sku, name, category, warehouse, current_stock,
                              reorder_point, unit_price, on_order)
        VALUES (%s, %s, 'Test', 'WH-Test', %s, 5, 10.0, 0)
        RETURNING id
        """,
        (sku, f"Test Product {sku}", stock),
    )
    return cur.fetchone()["id"]


def _cleanup_product(product_id: int) -> None:
    """Clean up test product."""
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM movements WHERE product_id = %s", (product_id,))
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))


class TestImportMovementsConcurrency:
    """Concurrency tests for movement import."""

    @pytest.fixture(autouse=True)
    def setup_db(self, app):
        """Set up test database."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-CONC-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-CONC-%')")
            yield
            with get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM products WHERE sku LIKE 'ADM001-CONC-%'")
                cur.execute("DELETE FROM movements WHERE product_id IN (SELECT id FROM products WHERE sku LIKE 'ADM001-CONC-%')")

    def test_concurrent_out_imports_cannot_go_negative(self, app):
        """Stock=10, 5 threads each import OUT 3 -> exactly 3 succeed, stock=1.

        Mirrors test_d1_concurrent_out_movements_cannot_go_negative but via import path.
        """
        successes = []
        failures = []

        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=10, sku_suffix="OUT01")

        def worker():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "3",
                    "movement_type": "OUT",
                    "reason": "Concurrent import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    if count == 1:
                        successes.append(1)
                    else:
                        failures.append("No rows imported (insufficient stock)")
                except Exception as exc:
                    failures.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
                movements = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id)
            except Exception:
                pass

        # Exactly 3 should succeed (10 / 3 = 3 with remainder 1)
        assert len(successes) == 3, (
            f"expected exactly 3 winning OUTs (stock 10 / qty 3), got {len(successes)}; "
            f"failures={failures}"
        )
        assert stock == 1, f"final stock must be 1, got {stock}"
        assert movements == 3, f"expected 3 movement rows, got {movements}"
        # Failures should indicate insufficient stock (either via exception or zero count)
        assert all("stock" in f.lower() or "insufficient" in f.lower() for f in failures), (
            f"losers must fail on the stock guard: {failures}"
        )

    def test_concurrent_out_imports_stock_15_qty_4(self, app):
        """Stock=15, 5 threads each import OUT 4 -> exactly 3 succeed, stock=3."""
        successes = []
        failures = []

        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=15, sku_suffix="OUT02")

        def worker():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "4",
                    "movement_type": "OUT",
                    "reason": "Concurrent import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    if count == 1:
                        successes.append(1)
                    else:
                        failures.append("No rows imported")
                except Exception as exc:
                    failures.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
                movements = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id)
            except Exception:
                pass

        # Exactly 3 should succeed (15 / 4 = 3 with remainder 3)
        assert len(successes) == 3, (
            f"expected exactly 3 winning OUTs (stock 15 / qty 4), got {len(successes)}; "
            f"failures={failures}"
        )
        assert stock == 3, f"final stock must be 3, got {stock}"
        assert movements == 3, f"expected 3 movement rows, got {movements}"

    def test_mixed_concurrency_import_out_plus_ui_out(self, app):
        """Mixed concurrency: Import OUT + UI OUT concurrent -> no lost updates.

        Simulates: 2 threads importing OUT 3 each, 2 threads calling MovementService.record OUT 3 each.
        Stock=20, total 4 threads * 3 = 12, all should succeed, stock=8.
        """
        from app.services.movement_service import MovementService

        import_results = []
        service_results = []
        import_errors = []
        service_errors = []

        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=20, sku_suffix="MIXED01")

        def import_worker():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "3",
                    "movement_type": "OUT",
                    "reason": "Import concurrent"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    import_results.append(count)
                except Exception as exc:
                    import_errors.append(str(exc))

        def service_worker():
            with app.app_context():
                try:
                    MovementService.record(
                        product_id=product_id,
                        mtype="OUT",
                        quantity=3,
                        reference="Service concurrent",
                        user_id=None
                    )
                    service_results.append(1)
                except Exception as exc:
                    service_errors.append(str(exc))

        # Run 2 import threads + 2 service threads concurrently
        threads = []
        for _ in range(2):
            threads.append(threading.Thread(target=import_worker))
            threads.append(threading.Thread(target=service_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
                movements = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id)
            except Exception:
                pass

        # All 4 should succeed (20 - 4*3 = 8)
        assert len(import_results) == 2, f"Expected 2 import successes, got {len(import_results)}"
        assert len(service_results) == 2, f"Expected 2 service successes, got {len(service_results)}"
        assert len(import_errors) == 0, f"Import errors: {import_errors}"
        assert len(service_errors) == 0, f"Service errors: {service_errors}"
        assert stock == 8, f"final stock must be 8, got {stock}"
        assert movements == 4, f"expected 4 movement rows, got {movements}"

    def test_concurrent_imports_different_products_no_interference(self, app):
        """Concurrent imports: 2 threads importing different products -> no interference."""
        results = []
        errors = []

        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id_1 = _mk_product(cur, stock=100, sku_suffix="DIFF01")
                product_id_2 = _mk_product(cur, stock=100, sku_suffix="DIFF02")

        def import_product_1():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id_1),
                    "quantity": "10",
                    "movement_type": "IN",
                    "reason": "Product 1 import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    results.append(("product_1", count))
                except Exception as exc:
                    errors.append(("product_1", str(exc)))

        def import_product_2():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id_2),
                    "quantity": "20",
                    "movement_type": "OUT",
                    "reason": "Product 2 import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    results.append(("product_2", count))
                except Exception as exc:
                    errors.append(("product_2", str(exc)))

        # Run multiple threads for each product
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=import_product_1))
            threads.append(threading.Thread(target=import_product_2))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id_1,))
                stock_1 = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id_1,))
                movements_1 = cur.fetchone()["c"]

                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id_2,))
                stock_2 = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id_2,))
                movements_2 = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id_1)
                _cleanup_product(product_id_2)
            except Exception:
                pass

        # All should succeed
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 6

        # Product 1: 3 threads * 10 IN = +30, stock = 130
        assert stock_1 == 130, f"Product 1 stock must be 130, got {stock_1}"
        assert movements_1 == 3, f"Product 1 expected 3 movements, got {movements_1}"

        # Product 2: 3 threads * 20 OUT = -60, stock = 40
        assert stock_2 == 40, f"Product 2 stock must be 40, got {stock_2}"
        assert movements_2 == 3, f"Product 2 expected 3 movements, got {movements_2}"

    def test_concurrent_imports_same_product_mixed_types(self, app):
        """Concurrent imports: mixed IN/OUT/ADJUSTMENT on same product."""
        results = []
        errors = []

        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=50, sku_suffix="MIXED02")

        def import_in():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "10",
                    "movement_type": "IN",
                    "reason": "IN import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    results.append(("IN", count))
                except Exception as exc:
                    errors.append(("IN", str(exc)))

        def import_out():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "5",
                    "movement_type": "OUT",
                    "reason": "OUT import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    results.append(("OUT", count))
                except Exception as exc:
                    errors.append(("OUT", str(exc)))

        def import_adj():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "3",
                    "movement_type": "ADJUSTMENT",
                    "reason": "ADJ import"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    results.append(("ADJ", count))
                except Exception as exc:
                    errors.append(("ADJ", str(exc)))

        # Run 2 of each type concurrently
        threads = []
        for _ in range(2):
            threads.append(threading.Thread(target=import_in))
            threads.append(threading.Thread(target=import_out))
            threads.append(threading.Thread(target=import_adj))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
                movements = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id)
            except Exception:
                pass

        # All 6 should succeed
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 6

        # Net change: 2*10 IN + 2*3 ADJ - 2*5 OUT = 20 + 6 - 10 = +16
        # Final stock: 50 + 16 = 66
        assert stock == 66, f"final stock must be 66, got {stock}"
        assert movements == 6, f"expected 6 movement rows, got {movements}"

    def test_high_concurrency_many_threads(self, app):
        """High concurrency: 20 threads importing OUT 1 each, stock=10 -> exactly 10 succeed."""
        successes = []
        failures = []

        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=10, sku_suffix="HIGH01")

        def worker():
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": "1",
                    "movement_type": "OUT",
                    "reason": "High concurrency"
                }]
                try:
                    count = _import_movements(rows, lock_key=0x6D6F7665)
                    if count == 1:
                        successes.append(1)
                    else:
                        failures.append("No rows imported")
                except Exception as exc:
                    failures.append(str(exc))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
                movements = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id)
            except Exception:
                pass

        # Exactly 10 should succeed
        assert len(successes) == 10, (
            f"expected exactly 10 winning OUTs (stock 10 / qty 1), got {len(successes)}; "
            f"failures={failures}"
        )
        assert stock == 0, f"final stock must be 0, got {stock}"
        assert movements == 10, f"expected 10 movement rows, got {movements}"

    def test_concurrent_imports_with_thread_pool_executor(self, app):
        """Test using ThreadPoolExecutor for concurrent imports."""
        with app.app_context():
            with get_cursor(commit=True) as cur:
                product_id = _mk_product(cur, stock=20, sku_suffix="POOL01")

        def import_task(qty):
            with app.app_context():
                rows = [{
                    "product_id": str(product_id),
                    "quantity": str(qty),
                    "movement_type": "OUT",
                    "reason": f"Pool import {qty}"
                }]
                return _import_movements(rows, lock_key=0x6D6F7665)

        # Submit 10 tasks of OUT 2 each (total 20, stock=20)
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(import_task, 2) for _ in range(10)]
            results = [f.result() for f in as_completed(futures)]

        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT current_stock FROM products WHERE id = %s", (product_id,))
                stock = cur.fetchone()["current_stock"]
                cur.execute("SELECT COUNT(*) AS c FROM movements WHERE product_id = %s", (product_id,))
                movements = cur.fetchone()["c"]
            try:
                _cleanup_product(product_id)
            except Exception:
                pass

        # All 10 should succeed
        assert all(r == 1 for r in results), f"All should succeed: {results}"
        assert stock == 0, f"final stock must be 0, got {stock}"
        assert movements == 10, f"expected 10 movement rows, got {movements}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])