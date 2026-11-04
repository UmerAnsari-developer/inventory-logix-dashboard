"""Test fixtures for the InventoryLogix application."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Read DB_PASSWORD from .env without polluting os.environ.
# load_dotenv() hasn't run yet when this module is imported, so a plain
# os.environ.get("DB_PASSWORD") can resolve to "" when the shell does not
# export it.  dotenv_values() reads .env in isolation.
_env = dotenv_values(PROJECT_ROOT / ".env")

# Forced (not setdefault): a developer shell or .env pointing at a remote
# database must never leak into a test run.
os.environ["FLASK_ENV"] = "testing"
os.environ["WTF_CSRF_ENABLED"] = "0"
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Tests always run against the local PostgreSQL, never the Render database
# configured in .env.  load_dotenv() won't override these.
os.environ["DB_HOST"] = "localhost"
os.environ["DB_PORT"] = "5432"
os.environ["DB_USER"] = "postgres"
os.environ["DB_SSLMODE"] = ""
# .env may carry a Render DATABASE_URL; tests use only the local DB_* fields.
os.environ["DATABASE_URL"] = ""
# An explicit non-empty DB_PASSWORD in the environment wins; otherwise use .env's.
os.environ["DB_PASSWORD"] = os.environ.get("DB_PASSWORD") or _env.get("DB_PASSWORD", "")
# Drop libpq overrides so a developer shell cannot redirect host resolution;
# every app connect path passes host/dbname explicitly.
for _libpq in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
    os.environ.pop(_libpq, None)

# Tests run against a local, dedicated ``*_test`` database — never the dev DB.
test_db = (os.environ.get("TEST_DB_NAME") or "inventory_db_test").strip()


def _guard_error(detail: str) -> RuntimeError:
    # Never interpolate credentials (or the resolved params) into this message.
    return RuntimeError(
        f"Refusing to run tests against database {test_db!r}: "
        f"tests require a dedicated test database. {detail} "
        "Create it first (for example: createdb inventory_db_test)."
    )


if not test_db.endswith("_test"):
    raise _guard_error(
        "Set TEST_DB_NAME to a local database whose name ends with '_test'."
    )

os.environ["DB_NAME"] = test_db
os.environ["TEST_DB_NAME"] = test_db

# Validate the effective config the app will actually connect with, not just
# the raw environment variables.  Importing app.config executes the app package
# (a few seconds at collection) but creates no Flask app and opens no DB.
from app.config.settings import TestingConfig  # noqa: E402  (after env is forced)

# Importing the app package runs load_dotenv(), which can re-add these keys.
for _libpq in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
    os.environ.pop(_libpq, None)

_params = TestingConfig.psycopg2_params()
if (
    "dsn" in _params
    or _params.get("dbname") != test_db
    or _params.get("host") not in {"localhost", "127.0.0.1", "::1"}
):
    raise _guard_error(
        "Resolved database config is not the local test database "
        "(DATABASE_URL must be empty and DB_HOST must be localhost)."
    )


@pytest.fixture(scope="session")
def app():
    from app import create_app
    flask_app = create_app("testing")
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture(autouse=True)
def _reset_rate_limiter(app):
    """Fresh flask-limiter buckets for every test (Issue 04 suite hygiene).

    The app — and the limiter singleton bound to it — are session-scoped, so
    buckets would otherwise leak between tests and make every limit
    assertion order-dependent. Replaces the ad-hoc ``limiter.reset()`` calls
    that used to live in test_auth_lockout.py and test_frontend_mitigations.py.
    Depends on ``app`` so init_app has run before reset() is called.
    """
    from app.extensions import limiter

    def _safe_reset():
        try:
            limiter.reset()
        except AssertionError:
            # flask-limiter's reset() asserts self._storage; a bare test-app
            # fixture (e.g. test_audit_decorator.py) never init_app's the
            # limiter, so there is nothing to reset. Tests relying on real
            # rate-limit buckets are unaffected — reset() works normally
            # whenever the limiter is bound.
            pass

    _safe_reset()
    yield
    _safe_reset()


@pytest.fixture()
def auth_client(client):
    """Returns a logged-in test client."""
    client.post(
        "/auth/login",
        data={"username": "admin", "password": "Admin@123", "remember": "on"},
        follow_redirects=False,
    )
    return client


@pytest.fixture()
def viewer_client(client):
    """Returns a logged-in read-only viewer test client."""
    client.post(
        "/auth/login",
        data={"username": "viewer", "password": "Viewer@123"},
        follow_redirects=False,
    )
    return client



@pytest.fixture()
def auth_page(page, base_url):
    """Returns a Playwright page logged in as admin."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "Admin@123")
    page.click('button[type="submit"]')
    expect(page).to_have_url(f"{base_url}/")
    return page


@pytest.fixture()
def viewer_page(page, base_url):
    """Returns a Playwright page logged in as viewer."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "viewer")
    page.fill('input[name="password"]', "Viewer@123")
    page.click('button[type="submit"]')
    expect(page).to_have_url(f"{base_url}/")
    return page


@pytest.fixture()
def manager_page(page, base_url):
    """Returns a Playwright page logged in as manager."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "manager")
    page.fill('input[name="password"]', "Manager@123")
    page.click('button[type="submit"]')
    expect(page).to_have_url(f"{base_url}/")
    return page



@pytest.fixture()
def manager_client(client):
    """Returns a logged-in manager test client."""
    client.post(
        "/auth/login",
        data={"username": "manager", "password": "Manager@123"},
        follow_redirects=False,
    )
    return client


# ============================================================
# BATCH 1 FIXTURES — Purchase Orders & Goods Receiving
# ============================================================

import pytest
import uuid
from app.database.connection import get_cursor


@pytest.fixture
def db_session(app):
    """Provide a database session for fixtures."""
    with app.app_context():
        with get_cursor(commit=True) as cur:
            yield cur


@pytest.fixture
def sample_supplier(db_session):
    """Create a test supplier with unique name."""
    import uuid
    from app.repositories import SupplierRepository
    token = uuid.uuid4().hex[:8]
    supplier_id = SupplierRepository.create({
        'name': f'Test Supplier {token}',
        'contact_email': f'supplier-{token}@test.com',
        'phone': '555-0100',
        'address': '123 Supply St',
        'payment_terms': 'Net 30',
        'is_active': True
    })
    # Fetch the created supplier object
    from app.repositories import SupplierRepository
    return SupplierRepository.find(supplier_id)


@pytest.fixture
def sample_product(db_session, sample_supplier):
    """Create a test product with stock."""
    import uuid
    from app.repositories import ProductRepository
    product_id = ProductRepository.create({
        'sku': f'TEST-SKU-{uuid.uuid4().hex[:8].upper()}',
        'name': 'Test Product',
        'description': 'Test product for receiving',
        'unit_cost': 10.00,
        'sale_price': 25.00,
        'reorder_point': 10,
        'reorder_quantity': 50,
        'supplier_id': sample_supplier['id'],
        'current_stock': 100,
        'on_order': 0,
        'is_active': True
    })
    return {'id': product_id}


@pytest.fixture
def sample_po_draft(db_session, sample_supplier, sample_product):
    """Create a PO in draft status."""
    import uuid
    from app.repositories import PurchaseOrderRepository
    po_id = PurchaseOrderRepository.create({
        'po_number': f'PO-TEST-{uuid.uuid4().hex[:8].upper()}',
        'supplier_id': sample_supplier['id'],
        'product_id': sample_product['id'],
        'quantity': 10,
        'unit_cost': 10.00,
        'status': 'draft',
        'eta_date': '2026-12-01'
    })
    return po_id


@pytest.fixture
def sample_po_approved(db_session, sample_po_draft):
    """Transition PO to approved."""
    from app.repositories import PurchaseOrderRepository
    PurchaseOrderRepository.transition(sample_po_draft, 'approved')
    po = PurchaseOrderRepository.list_by_status('approved')[0]
    return po['id']


@pytest.fixture
def sample_po_in_transit(db_session, sample_po_approved):
    """Transition PO to in_transit – PRIMARY FIXTURE for receive tests."""
    from app.repositories import PurchaseOrderRepository
    PurchaseOrderRepository.transition(sample_po_approved, 'in_transit')
    return sample_po_approved


@pytest.fixture
def sample_po_received(db_session, sample_po_in_transit):
    """Transition PO to received (full receipt)."""
    from app.repositories import PurchaseOrderRepository
    PurchaseOrderRepository.transition(sample_po_in_transit, 'received')
    po = PurchaseOrderRepository.list_by_status('received')[0]
    return po['id']


@pytest.fixture
def sample_po_cancelled(db_session, sample_po_approved):
    """Transition PO to cancelled."""
    from app.repositories import PurchaseOrderRepository
    PurchaseOrderRepository.transition(sample_po_approved, 'cancelled')
    po = PurchaseOrderRepository.list_by_status('cancelled')[0]
    return po['id']


@pytest.fixture
def sample_po_partial_received(db_session, sample_po_in_transit, admin_user):
    """PO with partial receipt (received_quantity=8 of 10)."""
    from app.repositories import PurchaseOrderRepository
    PurchaseOrderRepository.receive(
        po_id=sample_po_in_transit,
        quantity=8,
        user_id=admin_user['id'],
        notes='Partial delivery',
        location='WH1'
    )
    return sample_po_in_transit


@pytest.fixture
def sample_goods_receipt(db_session, sample_po_in_transit, admin_user):
    """Create a goods receipt via procedure (for list_receipts tests)."""
    with get_cursor(commit=True) as cur:
        cur.execute("""
            SELECT sp_goods_receipt_create(%s, %s, %s, %s, %s, %s)
        """, (sample_po_in_transit, 5, admin_user['id'], 'Test receipt', 'WH1', 'idem-key-1'))
        receipt_id = cur.fetchone()[0]
    
    with get_cursor() as cur:
        cur.execute("SELECT * FROM goods_receipts WHERE id = %s", (receipt_id,))
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row))


@pytest.fixture
def multiple_goods_receipts(db_session, sample_po_in_transit, admin_user, manager_user):
    """Create multiple receipts for query filter tests."""
    from app.database.connection import get_cursor
    receipts = []
    with get_cursor(commit=True) as cur:
        for i, (qty, user, notes, loc, key) in enumerate([
            (3, admin_user['id'], 'First', 'WH1', 'idem-1'),
            (4, manager_user['id'], 'Second', 'WH2', 'idem-2'),
            (3, admin_user['id'], 'Third', 'WH1', 'idem-3'),
        ]):
            cur.execute("""
                SELECT sp_goods_receipt_create(%s, %s, %s, %s, %s, %s)
            """, (sample_po_in_transit, qty, user, notes, loc, key))
            receipt_id = cur.fetchone()[0]
            receipts.append(receipt_id)
    return receipts


@pytest.fixture
def admin_user(db_session):
    """Admin user for receiving."""
    import uuid
    from app.repositories import UserRepository
    token = uuid.uuid4().hex[:8]
    user_id = UserRepository.create(
        f'admin_{token}',
        f'admin_{token}@test.com',
        'Admin@123',
        'admin'
    )
    return {'id': user_id, 'username': f'admin_{token}', 'role': 'admin'}


@pytest.fixture
def manager_user(db_session):
    """Manager user for receiving."""
    import uuid
    from app.repositories import UserRepository
    token = uuid.uuid4().hex[:8]
    user_id = UserRepository.create(
        f'manager_{token}',
        f'manager_{token}@test.com',
        'Manager@123',
        'manager'
    )
    return {'id': user_id, 'username': f'manager_{token}', 'role': 'manager'}


@pytest.fixture
def viewer_user(db_session):
    """Viewer user (should NOT have receive permission)."""
    import uuid
    from app.repositories import UserRepository
    token = uuid.uuid4().hex[:8]
    user_id = UserRepository.create(
        f'viewer_{token}',
        f'viewer_{token}@test.com',
        'Viewer@123',
        'viewer'
    )
    return {'id': user_id, 'username': f'viewer_{token}', 'role': 'viewer'}

@pytest.fixture(scope="session")
def base_url(app):
    """Live server bound to the *test* app/DB.

    Deliberately not ``http://localhost:5000``: that is the dev server, which
    reads ``DATABASE_URL`` from ``.env`` and therefore talks to production.
    E2E must never write to production.
    """
    import threading

    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)

