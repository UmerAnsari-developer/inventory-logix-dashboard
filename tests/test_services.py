"""Inventory service tests covering validation rules."""
from __future__ import annotations

import pytest

from app.services import ProductService, MovementService
from app.services.product_service import ProductError
from app.services.movement_service import MovementError


def test_validate_payload_normalises_sku():
    payload = {
        "sku": " sku-test-001 ",
        "name": "Test SKU",
        "current_stock": "5",
        "reorder_point": "2",
        "unit_price": "12.50",
        "demand_rate": "100",
        "ordering_cost": "5",
        "holding_cost": "3",
    }
    result = ProductService.validate_payload(payload)
    assert result["sku"] == "SKU-TEST-001"
    assert result["current_stock"] == 5


def test_validate_payload_negative_stock():
    payload = {"sku": "x", "name": "x", "current_stock": -1, "reorder_point": 0, "unit_price": 1}
    with pytest.raises(ProductError):
        ProductService.validate_payload(payload)


def test_movement_service_validates_type():
    with pytest.raises(MovementError):
        MovementService.record(
            product_id=1,
            mtype="INVALID",
            quantity=10,
        )


# ---------------------------------------------------------------------------
# ProductService.validate_payload boundary rules
# ---------------------------------------------------------------------------
def _full_payload(**overrides):
    payload = {
        "sku": "SKU-BND-001",
        "name": "Test Product",
        "current_stock": "10",
        "reorder_point": "2",
        "unit_price": "12.50",
        "demand_rate": "100",
        "ordering_cost": "5",
        "holding_cost": "3",
    }
    payload.update(overrides)
    return payload


def test_validate_payload_name_minimum():
    result = ProductService.validate_payload(_full_payload(name="ab"))
    assert result["name"] == "ab"


def test_validate_payload_name_too_long():
    with pytest.raises(ProductError):
        ProductService.validate_payload(_full_payload(name="x" * 151))


def test_validate_payload_category_optional():
    result = ProductService.validate_payload(_full_payload())
    assert result["category"] is None


def test_validate_payload_warehouse_default():
    result = ProductService.validate_payload(_full_payload(warehouse=""))
    assert result["warehouse"] == "WH-Pune"


def test_validate_payload_zero_stock_and_reorder_ok():
    result = ProductService.validate_payload(
        _full_payload(current_stock="0", reorder_point="0")
    )
    assert result["current_stock"] == 0
    assert result["reorder_point"] == 0


def test_validate_payload_zero_unit_price_ok():
    result = ProductService.validate_payload(_full_payload(unit_price="0"))
    assert result["unit_price"] == 0.0


def test_validate_payload_zero_demand_rate_ok():
    result = ProductService.validate_payload(_full_payload(demand_rate="0"))
    assert result["demand_rate"] == 0.0


def test_validate_payload_empty_reorder_point_defaults_zero():
    result = ProductService.validate_payload(_full_payload(reorder_point=""))
    assert result["reorder_point"] == 0


# ---------------------------------------------------------------------------
# ProductService.list_products pagination math (repository faked, no DB)
# ---------------------------------------------------------------------------
def _fake_product_repo(total=16):
    class FakeRepo:
        captured = {}
        last_limit = None

        @staticmethod
        def list(**kwargs):
            FakeRepo.captured = kwargs
            FakeRepo.last_limit = kwargs["limit"]
            return [{"id": i} for i in range(kwargs["limit"])], total

    return FakeRepo


def test_list_products_clamps_page_and_per_page_lower(monkeypatch):
    repo = _fake_product_repo()
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=0, per_page=4)
    pag = result["pagination"]
    assert pag["page"] == 1
    assert pag["per_page"] == 5
    assert repo.captured["offset"] == 0
    assert repo.captured["limit"] == 5


def test_list_products_clamps_per_page_upper(monkeypatch):
    repo = _fake_product_repo()
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(per_page=9999)
    assert result["pagination"]["per_page"] == 100
    assert repo.captured["limit"] == 100


def test_list_products_default_per_page(monkeypatch):
    repo = _fake_product_repo()
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products()
    assert result["pagination"]["page"] == 1
    assert result["pagination"]["per_page"] == 20
    assert repo.captured["limit"] == 20


def test_list_products_pagination_math(monkeypatch):
    repo = _fake_product_repo(total=16)
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=2, per_page=5)
    pag = result["pagination"]
    assert pag["page"] == 2
    assert pag["per_page"] == 5
    assert pag["total"] == 16
    assert pag["pages"] == 4
    assert pag["has_prev"] is True
    assert pag["has_next"] is True
    assert pag["prev_num"] == 1
    assert pag["next_num"] == 3
    assert repo.captured["offset"] == 5
    assert repo.captured["limit"] == 5


def test_list_products_has_next_boundary(monkeypatch):
    repo = _fake_product_repo(total=10)
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=1, per_page=10)
    pag = result["pagination"]
    assert pag["pages"] == 1
    assert pag["has_next"] is False
    assert pag["has_prev"] is False


def test_list_products_high_page(monkeypatch):
    repo = _fake_product_repo(total=16)
    monkeypatch.setattr("app.services.product_service.ProductRepository", repo)
    result = ProductService.list_products(page=99999, per_page=100)
    pag = result["pagination"]
    assert pag["page"] == 99999
    assert pag["has_next"] is False
    assert pag["prev_num"] == 99998


# ---------------------------------------------------------------------------
# MovementService.record stock math (repositories faked, no DB)
# ---------------------------------------------------------------------------
def _patch_movement(monkeypatch, current_stock=10, sku="SKU-MV-001"):
    class FakeProductRepo:
        last_stock = None

        @staticmethod
        def find(product_id):
            return {"id": product_id, "sku": sku, "current_stock": current_stock}

        @staticmethod
        def find_for_update(product_id):
            return {"id": product_id, "sku": sku, "current_stock": current_stock}

        @staticmethod
        def set_stock(product_id, stock):
            FakeProductRepo.last_stock = stock

    class FakeMovementRepo:
        last_call = None

        @staticmethod
        def record(**kwargs):
            FakeMovementRepo.last_call = kwargs
            return 99

    class FakeAuditRepo:
        @staticmethod
        def record(*args, **kwargs):
            pass

    monkeypatch.setattr("app.services.movement_service.ProductRepository", FakeProductRepo)
    monkeypatch.setattr("app.services.movement_service.MovementRepository", FakeMovementRepo)
    monkeypatch.setattr("app.services.movement_service.AuditRepository", FakeAuditRepo)
    return FakeProductRepo, FakeMovementRepo


def test_movement_record_out_decrements_stock(monkeypatch):
    fake_p, fake_m = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="OUT", quantity=4)
    assert fake_p.last_stock == 6
    assert fake_m.last_call["quantity"] == 4


def test_movement_record_in_increments_stock(monkeypatch):
    fake_p, _ = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="IN", quantity=4)
    assert fake_p.last_stock == 14


def test_movement_record_exact_balance_allowed(monkeypatch):
    fake_p, _ = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="OUT", quantity=10)
    assert fake_p.last_stock == 0


def test_movement_record_rejects_zero_quantity(monkeypatch):
    _patch_movement(monkeypatch)
    with pytest.raises(MovementError):
        MovementService.record(product_id=1, mtype="IN", quantity=0)


def test_movement_record_rejects_missing_quantity(monkeypatch):
    _patch_movement(monkeypatch)
    with pytest.raises(MovementError):
        MovementService.record(product_id=1, mtype="IN", quantity=None)


def test_movement_record_rejects_oversell(monkeypatch):
    _patch_movement(monkeypatch, current_stock=10)
    with pytest.raises(MovementError):
        MovementService.record(product_id=1, mtype="OUT", quantity=11)


def test_movement_record_defaults_reference_and_notes(monkeypatch):
    _, fake_m = _patch_movement(monkeypatch, current_stock=10)
    MovementService.record(product_id=1, mtype="IN", quantity=5)
    assert fake_m.last_call["reference"] is None
    assert fake_m.last_call["notes"] is None


def test_movement_record_null_stock_treated_as_zero(monkeypatch):
    fake_p, _ = _patch_movement(monkeypatch, current_stock=None)
    MovementService.record(product_id=1, mtype="IN", quantity=5)
    assert fake_p.last_stock == 5
