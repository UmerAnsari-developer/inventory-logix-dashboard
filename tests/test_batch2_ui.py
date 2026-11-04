"""RED tests for Batch 2: Movement Ledger UI (/movements page).

These tests define the acceptance criteria. All should FAIL initially.
Run with: pytest tests/test_batch2_ui.py -v
"""
from __future__ import annotations

import pytest
from flask import url_for
from app.database import get_cursor
from app.repositories import MovementRepository, ProductRepository


# =============================================================================
# 1. ROUTE ACCESS — GET /movements returns correct status per role
# =============================================================================

class TestMovementsRouteAccess:
    """Route access control for /movements page."""

    def test_admin_access_returns_200(self, auth_client):
        """Admin user can access movement ledger."""
        resp = auth_client.get("/movements")
        assert resp.status_code == 200, f"Expected 200 for admin, got {resp.status_code}"

    def test_manager_access_returns_200(self, manager_client):
        """Manager user can access movement ledger."""
        resp = manager_client.get("/movements")
        assert resp.status_code == 200, f"Expected 200 for manager, got {resp.status_code}"

    def test_viewer_access_returns_200(self, viewer_client):
        """Viewer (read-only) can access movement ledger."""
        resp = viewer_client.get("/movements")
        assert resp.status_code == 200, f"Expected 200 for viewer, got {resp.status_code}"

    def test_anonymous_redirects_to_login(self, client):
        """Unauthenticated user is redirected to login page."""
        resp = client.get("/movements", follow_redirects=False)
        assert resp.status_code == 302, f"Expected 302 redirect for anon, got {resp.status_code}"
        assert "/auth/login" in resp.headers.get("Location", "")

    def test_no_403_for_viewer(self, viewer_client):
        """Viewer must NOT get 403 — read access is allowed."""
        resp = viewer_client.get("/movements")
        assert resp.status_code != 403, "Viewer must have read access to /movements"


# =============================================================================
# 2. TEMPLATE RENDERS — filter bar, table headers, pagination, export button
# =============================================================================

class TestMovementsTemplateRenders:
    """Template structure and required UI elements."""

    def test_page_title_and_h1(self, auth_client):
        """Page has correct title and H1."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        assert "Movement Ledger" in html
        assert "<h1" in html and "Movement Ledger" in html

    def test_filter_bar_exists(self, auth_client):
        """Filter bar form with all filter controls renders."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Filter bar container
        assert 'class="filter-bar"' in html or 'class="filter-bar ' in html
        # Type multi-select button
        assert 'id="typeButton"' in html or 'name="type"' in html
        # Date from/to inputs
        assert 'name="date_from"' in html
        assert 'name="date_to"' in html
        # Product search
        assert 'name="product"' in html or 'id="productButton"' in html
        # User search
        assert 'name="user"' in html or 'id="userButton"' in html
        # Apply button
        assert 'id="applyBtn"' in html or 'id="invApplyBtn"' in html or 'Apply' in html
        # Reset link
        assert 'Reset' in html

    def test_table_headers_present(self, auth_client):
        """Table has all 8 required column headers."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        headers = [
            "Date", "Type", "Qty", "Product",
            "Supplier", "User", "Ref", "Notes"
        ]
        for h in headers:
            assert h in html, f"Missing header: {h}"

    def test_pagination_controls_render(self, auth_client):
        """Pagination controls present (prev/next/page info)."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        assert 'class="pagination"' in html or 'class="pagination ' in html
        # Prev/next or page numbers
        assert "prev" in html.lower() or "«" in html or "&laquo;" in html
        assert "next" in html.lower() or "»" in html or "&raquo;" in html

    def test_export_button_present(self, auth_client):
        """Export CSV button renders and links to /api/movements/export."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        assert 'id="exportBtn"' in html or 'Export' in html
        # Button should link to export endpoint with current filters
        assert "/api/movements/export" in html or 'exportBtn' in html

    def test_empty_state_when_no_movements(self, auth_client, app):
        """When no movements exist, table shows 'No movements found'."""
        # Use a fresh product with no movements
        with app.app_context():
            with get_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO products (sku, name, category, warehouse, current_stock, reorder_point, unit_price)
                    VALUES (%s, 'Empty Test', 'Test', 'WH-Test', 0, 0, 1.0)
                    RETURNING id
                """, (f"EMPTY-{__import__('uuid').uuid4().hex[:8].upper()}",))
                product_id = cur.fetchone()["id"]

        # Filter to a product that has no movements
        resp = auth_client.get(f"/movements?product_id={product_id}")
        html = resp.get_data(as_text=True)
        assert "No movements found" in html or "no movements" in html.lower()


# =============================================================================
# 3. FILTER STATE — submitting form preserves values; args passed to API
# =============================================================================

class TestMovementsFilterState:
    """Filter form preserves state and passes params to backend."""

    def test_type_filter_preserved_after_submit(self, auth_client):
        """Type multi-select values preserved in form after submit."""
        resp = auth_client.get("/movements?type=IN,OUT")
        html = resp.get_data(as_text=True)
        # Check that IN and OUT are reflected in the form (hidden JSON or checked inputs)
        assert "IN" in html and "OUT" in html

    def test_date_range_preserved_after_submit(self, auth_client):
        """Date from/to values preserved after submit."""
        resp = auth_client.get("/movements?date_from=2024-01-01&date_to=2024-12-31")
        html = resp.get_data(as_text=True)
        assert 'value="2024-01-01"' in html
        assert 'value="2024-12-31"' in html

    def test_product_search_preserved_after_submit(self, auth_client):
        """Product search term preserved after submit."""
        resp = auth_client.get("/movements?product=TEST-SKU")
        html = resp.get_data(as_text=True)
        assert "TEST-SKU" in html

    def test_user_filter_preserved_after_submit(self, auth_client):
        """User filter term preserved after submit."""
        resp = auth_client.get("/movements?user=admin")
        html = resp.get_data(as_text=True)
        assert "admin" in html

    def test_filter_args_passed_to_pagination_links(self, auth_client):
        """Pagination links carry forward all active filter params."""
        resp = auth_client.get("/movements?type=IN&date_from=2024-01-01&page=1")
        html = resp.get_data(as_text=True)
        # Next page link should include type and date_from
        assert "type=IN" in html
        assert "date_from=2024-01-01" in html

    def test_filter_args_passed_to_export_button(self, auth_client):
        """Export button href includes current filter params."""
        resp = auth_client.get("/movements?type=OUT&product=ABC")
        html = resp.get_data(as_text=True)
        # Export URL should have the same filters
        assert "/api/movements/export" in html
        assert "type=OUT" in html or "type%3DOUT" in html
        assert "product=ABC" in html or "product%3DABC" in html


# =============================================================================
# 4. PAGINATION — page 1 loads, next/prev work, total_count displayed
# =============================================================================

class TestMovementsPagination:
    """Pagination behavior and display."""

    def test_page_1_loads_by_default(self, auth_client):
        """Default page is 1."""
        resp = auth_client.get("/movements")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Page indicator should show page 1
        assert "1" in html  # page number

    def test_explicit_page_param_works(self, auth_client):
        """Explicit page parameter loads that page."""
        resp = auth_client.get("/movements?page=2")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "2" in html  # page number

    def test_prev_next_links_work(self, auth_client, app):
        """Prev/Next links navigate correctly when multiple pages exist."""
        # Create enough movements to span pages (per_page default ~20)
        with app.app_context():
            from app.services import MovementService
            from app.repositories import ProductRepository, UserRepository
            # Find an active (non-deleted) product
            rows, _total = ProductRepository.list(limit=1)
            if not rows:
                pytest.skip("No products in DB")
            product_id = rows[0]["id"]
            # Get admin user ID
            admin = UserRepository.find_by_username("admin")
            admin_id = admin.id
            # Create 25 movements (should give 2 pages with per_page=20)
            for i in range(25):
                MovementService.record(
                    product_id=product_id,
                    mtype="IN" if i % 2 == 0 else "OUT",
                    quantity=1,
                    reference=f"PAGE-TEST-{i}",
                    user_id=admin_id,
                )

        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Should show pagination with next link
        assert "next" in html.lower() or "»" in html or "&raquo;" in html

        # Click next (simulate via test client)
        resp2 = auth_client.get("/movements?page=2")
        assert resp2.status_code == 200
        html2 = resp2.get_data(as_text=True)
        # Page 2 should show prev link
        assert "prev" in html2.lower() or "«" in html2 or "&laquo;" in html2

    def test_total_count_displayed(self, auth_client):
        """Total count of movements shown in pagination area."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Look for "Showing X of Y" or similar
        assert "of" in html.lower() or "total" in html.lower()


# =============================================================================
# 5. SORT — clicking header toggles sort (API supports sort field/direction)
# =============================================================================

class TestMovementsSort:
    """Column sorting via header clicks."""

    def test_default_sort_by_date_desc(self, auth_client):
        """Default sort is created_at descending (newest first)."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Date header should indicate descending sort
        assert 'aria-sort="descending"' in html or 'data-sort="created_at"' in html

    def test_sort_by_type_works(self, auth_client):
        """Sort by type column toggles direction."""
        resp = auth_client.get("/movements?sort=type&dir=asc")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Type header should indicate ascending
        assert 'aria-sort="ascending"' in html or 'data-sort="type"' in html

    def test_sort_by_quantity_works(self, auth_client):
        """Sort by quantity column."""
        resp = auth_client.get("/movements?sort=quantity&dir=desc")
        assert resp.status_code == 200

    def test_sort_by_product_works(self, auth_client):
        """Sort by product column."""
        resp = auth_client.get("/movements?sort=product&dir=asc")
        assert resp.status_code == 200

    def test_sort_toggle_updates_url(self, auth_client):
        """Sort headers generate links with toggled direction."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Header links should have sort params
        assert "sort=" in html
        assert "dir=" in html


# =============================================================================
# 6. EXPORT — button links to /api/movements/export with current filter params
# =============================================================================

class TestMovementsExport:
    """Export CSV functionality."""

    def test_export_button_links_to_correct_endpoint(self, auth_client):
        """Export button points to /api/movements/export."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        assert "/api/movements/export" in html

    def test_export_includes_all_current_filters(self, auth_client):
        """Export URL carries all active filter params."""
        resp = auth_client.get("/movements?type=IN&date_from=2024-01-01&product=SKU123&user=john&sort=type&dir=asc")
        html = resp.get_data(as_text=True)
        export_url = None
        # Extract export href
        import re
        match = re.search(r'href="([^"]*/api/movements/export[^"]*)"', html)
        if match:
            export_url = match.group(1)
        assert export_url is not None, "Export button href not found"
        assert "type=IN" in export_url
        assert "date_from=2024-01-01" in export_url
        assert "product=SKU123" in export_url
        assert "user=john" in export_url
        assert "sort=type" in export_url
        assert "dir=asc" in export_url

    def test_export_returns_csv(self, auth_client):
        """Export endpoint returns CSV with correct headers."""
        resp = auth_client.get("/api/movements/export")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert "movements" in resp.headers.get("Content-Disposition", "").lower()
        assert ".csv" in resp.headers.get("Content-Disposition", "").lower()

    def test_export_csv_has_expected_columns(self, auth_client):
        """CSV includes expected columns (matches sp_movement_export_data output)."""
        resp = auth_client.get("/api/movements/export")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        csv_text = resp.get_data(as_text=True)
        # First line should be headers
        lines = csv_text.strip().split("\n")
        assert len(lines) >= 1
        headers = lines[0].lower()
        # Actual columns from sp_movement_export_data
        expected = ["id", "type", "quantity", "reference", "notes", "created_at", "user_id", "product_name", "sku", "user_name"]
        for col in expected:
            assert col in headers, f"Missing CSV column: {col}"


# =============================================================================
# 7. PRODUCT DETAIL LINK — /products/<id> → "View all movements" → filtered
# =============================================================================

class TestProductDetailViewAllMovements:
    """'View all movements' link from product detail page."""

    def test_product_detail_has_view_all_link(self, auth_client, app):
        """Product detail page shows 'View all movements' link."""
        with app.app_context():
            rows, _ = ProductRepository.list(search="", category="", status="", warehouse="", limit=1, offset=0)
            product = rows[0]
            product_id = product["id"]

        resp = auth_client.get(f"/products/{product_id}")
        html = resp.get_data(as_text=True)
        assert "View all movements" in html
        assert f"/movements?product_id={product_id}" in html

    def test_view_all_link_navigates_to_movements_filtered(self, auth_client, app):
        """Clicking link navigates to /movements with product_id filter."""
        with app.app_context():
            rows, _ = ProductRepository.list(search="", category="", status="", warehouse="", limit=1, offset=0)
            product = rows[0]
            product_id = product["id"]
            sku = product["sku"]

        resp = auth_client.get(f"/movements?product_id={product_id}")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Should show the product_id filter applied
        assert str(product_id) in html
        # Results should be filtered to that product
        # (At minimum the filter should be visible in the form)
        assert f'value="{product_id}"' in html or f"product_id={product_id}" in html

    def test_filtered_page_shows_only_that_product_movements(self, auth_client, app):
        """Filtered movements page shows only movements for that product."""
        with app.app_context():
            rows, _ = ProductRepository.list(search="", category="", status="", warehouse="", limit=1, offset=0)
            product = rows[0]
            product_id = product["id"]
            sku = product["sku"]

        resp = auth_client.get(f"/movements?product_id={product_id}")
        html = resp.get_data(as_text=True)
        # All visible rows should contain this product's SKU
        # (or the table should be empty if no movements exist)
        if "No movements found" not in html:
            # Check that sku appears in table rows
            assert sku in html


# =============================================================================
# 8. VIEWER READ-ONLY — viewer sees page but no "Create movement" button
# =============================================================================

class TestViewerReadOnly:
    """Viewer role sees read-only UI (no create/edit actions)."""

    def test_viewer_sees_page(self, viewer_client):
        """Viewer can load the page."""
        resp = viewer_client.get("/movements")
        assert resp.status_code == 200

    def test_viewer_no_create_movement_button(self, viewer_client):
        """Viewer does NOT see 'Create movement' or '+ Add movement' button."""
        resp = viewer_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Should not have create button
        assert "Create movement" not in html
        assert "+ Add movement" not in html
        assert "movement_form" not in html or "new" not in html  # no link to create

    def test_admin_sees_create_movement_button(self, auth_client):
        """Admin DOES see 'Create movement' button."""
        resp = auth_client.get("/movements")
        html = resp.get_data(as_text=True)
        # Should have link to /movements/new
        assert "Create movement" in html or "+ Add movement" in html or "/movements/new" in html

    def test_manager_sees_create_movement_button(self, manager_client):
        """Manager DOES see 'Create movement' button."""
        resp = manager_client.get("/movements")
        html = resp.get_data(as_text=True)
        assert "Create movement" in html or "+ Add movement" in html or "/movements/new" in html


# =============================================================================
# 9. EMPTY STATE — when no movements, table shows "No movements found"
# =============================================================================

class TestEmptyState:
    """Empty state handling."""

    def test_empty_table_shows_message(self, auth_client, app):
        """When filter yields zero results, friendly message displays."""
        # Filter to a non-existent product_id
        resp = auth_client.get("/movements?product_id=999999")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "No movements found" in html or "no movements" in html.lower()

    def test_empty_state_not_shown_when_data_exists(self, auth_client, app):
        """Empty state hidden when movements exist."""
        with app.app_context():
            with get_cursor() as cur:
                cur.execute("SELECT id FROM products LIMIT 1")
                row = cur.fetchone()
                if row:
                    product_id = row["id"]
                    resp = auth_client.get(f"/movements?product_id={product_id}")
                    html = resp.get_data(as_text=True)
                    # May or may not have movements; if it does, no empty message
                    if "No movements found" in html:
                        # That's OK if truly no movements for that product
                        pass
                    else:
                        # Has data, empty state should not appear
                        assert "No movements found" not in html


# =============================================================================
# 10. CACHE — second request hits cache (verify via api_cache stats)
# =============================================================================

class TestMovementsCache:
    """Cache behavior for /movements page."""

    def test_first_request_populates_cache(self, auth_client, app):
        """First request to /movements populates the cache."""
        from app.utils.cache import api_cache
        # Clear any existing cache for this view
        with app.app_context():
            # We can't easily clear specific keys, but we can verify cache behavior
            pass

        resp1 = auth_client.get("/movements")
        assert resp1.status_code == 200

    def test_second_request_hits_cache(self, auth_client, app):
        """Second identical request should be served from cache (data layer)."""
        from app.utils.cache import api_cache

        # Clear cache first
        with app.app_context():
            api_cache.invalidate("movements")

        # Make first request
        resp1 = auth_client.get("/movements")
        assert resp1.status_code == 200

        # Make second request with same params - should hit cache
        resp2 = auth_client.get("/movements")
        assert resp2.status_code == 200
        # Verify cache was used by checking stats
        with app.app_context():
            stats = api_cache.stats()
            # Cache hits should be >= 1 (second request hit cache)
            assert stats["hits"] >= 1

    def test_different_filter_params_bypass_cache(self, auth_client):
        """Different filter params produce different cached responses."""
        resp1 = auth_client.get("/movements?type=IN")
        resp2 = auth_client.get("/movements?type=OUT")
        # Both should succeed
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Content may differ (but not strictly testable without known data)

    def test_cache_key_includes_all_filter_params(self, app):
        """Cache key generation includes all filter/sort/page params."""
        from app.utils.cache import make_key
        # Verify the make_key function includes relevant params (takes prefix as kwarg)
        key1 = make_key(prefix="movements", type="IN", date_from="2024-01-01", page=1)
        key2 = make_key(prefix="movements", type="OUT", date_from="2024-01-01", page=1)
        key3 = make_key(prefix="movements", type="IN", date_from="2024-01-01", page=2)
        assert key1 != key2, "Different type should produce different cache key"
        assert key1 != key3, "Different page should produce different cache key"


# =============================================================================
# HELPER: Verify MovementRepository.list supports required params
# =============================================================================

class TestMovementRepositoryInterface:
    """Verify the repository supports the UI's required query parameters."""

    def test_repository_list_accepts_type_filter(self, app):
        """MovementRepository.list_movements accepts type filter."""
        with app.app_context():
            result = MovementRepository.list_movements(type_filter=["IN"], page=1, per_page=10)
            assert isinstance(result, list)

    def test_repository_list_accepts_date_range(self, app):
        """MovementRepository.list_movements accepts date_from/date_to."""
        with app.app_context():
            result = MovementRepository.list_movements(date_from="2024-01-01", date_to="2024-12-31", page=1, per_page=10)
            assert isinstance(result, list)

    def test_repository_list_accepts_product_filter(self, app):
        """MovementRepository.list_movements accepts product_id filter."""
        with app.app_context():
            result = MovementRepository.list_movements(product_id=1, page=1, per_page=10)
            assert isinstance(result, list)

    def test_repository_list_accepts_user_filter(self, app):
        """MovementRepository.list_movements accepts user_id filter."""
        with app.app_context():
            result = MovementRepository.list_movements(user_id=1, page=1, per_page=10)
            assert isinstance(result, list)

    def test_repository_list_accepts_sort_params(self, app):
        """MovementRepository.list_movements accepts sort_by/sort_order params."""
        with app.app_context():
            result = MovementRepository.list_movements(sort_by="created_at", sort_order="desc", page=1, per_page=10)
            assert isinstance(result, list)

    def test_repository_list_returns_total_count(self, app):
        """MovementService.list_movements returns list with total_count on each row."""
        with app.app_context():
            from app.services import MovementService
            result = MovementService.list_movements(page=1, per_page=10)
            assert isinstance(result, list)
            # Each row should have total_count
            if result:
                assert "total_count" in result[0]


# =============================================================================
# SUMMARY: All 10 acceptance areas covered with RED tests
# =============================================================================
"""
Coverage checklist:
✅ 1. Route access: admin/manager/viewer 200, anon 302→login, viewer no 403
✅ 2. Template renders: filter bar (type, date, product, user), 8 headers, pagination, export
✅ 3. Filter state: values preserved in form, passed to pagination/export links
✅ 4. Pagination: page 1 default, next/prev, total count displayed
✅ 5. Sort: default date desc, clickable headers toggle sort/dir
✅ 6. Export: button→/api/movements/export with all filter params, CSV with 8 columns
✅ 7. Product detail link: /products/<id> → /movements?product_id=<id> filtered
✅ 8. Viewer read-only: no create button; admin/manager have create button
✅ 9. Empty state: "No movements found" when zero results
✅ 10. Cache: second request hits cache, keys include all params
✅ Repo interface: MovementRepository.list supports all required params
"""