"""E2E tests for the Movement Ledger UI (Playwright)."""

import re

import pytest
from playwright.sync_api import expect


def _product_with_movements(app):
    """Return (id, sku) for a product that has at least one active movement."""
    from app.database import get_cursor

    with app.app_context():
        with get_cursor() as cur:
            cur.execute(
                "SELECT m.product_id AS id, p.sku AS sku "
                "FROM movements m JOIN products p ON p.id = m.product_id "
                "WHERE m.deleted_at IS NULL ORDER BY m.id DESC LIMIT 1"
            )
            row = cur.fetchone()
    if row is None:
        pytest.skip("no movements in the test database")
    return row["id"], row["sku"]


class TestMovementLedgerPage:
    """Tests for /movements page."""

    def test_movements_page_loads(self, page, auth_page):
        """Movement ledger page loads successfully."""
        page.goto("/movements")
        expect(page).to_have_title("Movement Ledger")
        expect(page.locator("h1")).to_contain_text("Movement Ledger")

    def test_movements_page_has_filter_bar(self, page, auth_page):
        """Filter bar with type, date range, product, user filters."""
        page.goto("/movements")
        expect(page.locator(".filter-bar")).to_be_visible()
        expect(page.locator("#mvTypeButton")).to_be_visible()
        expect(page.locator('input[name="date_from"]')).to_be_visible()
        expect(page.locator('input[name="date_to"]')).to_be_visible()
        expect(page.locator("#productButton")).to_be_visible()
        expect(page.locator("#userButton")).to_be_visible()

    def test_movements_table_renders(self, page, auth_page):
        """Movement table renders with data."""
        page.goto("/movements")
        expect(page.locator(".data-table")).to_be_visible()
        expect(page.locator("thead th")).to_have_count(7)

    def test_movements_table_sortable(self, page, auth_page):
        """Column headers are sortable."""
        page.goto("/movements")
        expect(page.locator("thead a[aria-sort]")).to_have_count(7)

    def test_movements_pagination_works(self, page, auth_page):
        """Pagination controls work."""
        page.goto("/movements")
        expect(page.locator(".pagination")).to_be_visible()

    def test_type_filter_works(self, page, auth_page):
        """Type multi-select filter works."""
        page.goto("/movements")
        page.click("#mvTypeButton")
        page.check('input[value="IN"]')
        page.check('input[value="OUT"]')
        page.click("#mvTypeButton")
        page.click("#mvApplyBtn")
        page.wait_for_url(re.compile(r"type=IN"))
        assert "type=IN" in page.url and "type=OUT" in page.url

    def test_date_range_filter_works(self, page, auth_page):
        """Date range filter works."""
        page.goto("/movements")
        page.fill('input[name="date_from"]', "2024-01-01")
        page.fill('input[name="date_to"]', "2024-12-31")
        page.click("#mvApplyBtn")
        page.wait_for_url(re.compile(r"date_from=2024-01-01"))

    def test_product_search_works(self, page, auth_page):
        """Product dropdown filter works."""
        page.goto("/movements")
        page.click("#productButton")
        page.locator('input[name="product"]').first.check()
        page.click("#productButton")
        page.click("#mvApplyBtn")
        page.wait_for_url(re.compile(r"[?&]product=\d+"))

    def test_user_filter_works(self, page, auth_page):
        """User dropdown filter works."""
        page.goto("/movements")
        page.click("#userButton")
        page.locator('input[name="user"]').first.check()
        page.click("#userButton")
        page.click("#mvApplyBtn")
        page.wait_for_url(re.compile(r"[?&]user=\d+"))

    def test_sort_by_date_works(self, page, auth_page):
        """Sort by date works."""
        page.goto("/movements")
        page.click('a[data-sort="created_at"]')
        expect(
            page.locator('a[aria-sort="ascending"][data-sort="created_at"]')
        ).to_be_visible()

    def test_movements_page_viewer_access(self, page, viewer_page):
        """Viewer can view movement ledger."""
        page.goto("/movements")
        expect(page.locator("h1")).to_contain_text("Movement Ledger")

    def test_movements_page_unauthenticated_redirects(self, page):
        """Unauthenticated user redirected to login."""
        page.goto("/movements")
        expect(page).to_have_url(re.compile(r"/auth/login"))

    def test_movements_page_export_button(self, page, auth_page):
        """Export CSV button present and works."""
        page.goto("/movements")
        expect(page.locator("#exportBtn")).to_be_visible()
        with page.expect_download() as download_info:
            page.click("#exportBtn")
        download = download_info.value
        assert "movements_" in download.suggested_filename
        assert download.suggested_filename.endswith(".csv")


class TestProductDetailViewAllMovements:
    """Tests for 'View all movements' link on product detail page."""

    def test_product_detail_has_view_all_link(self, page, auth_page, app):
        """Product detail page has 'View all movements' link."""
        product_id, _sku = _product_with_movements(app)
        page.goto(f"/products/{product_id}")
        expect(page.locator("a:has-text('View all movements')")).to_be_visible()

    def test_view_all_link_navigates_to_movements(self, page, auth_page, app):
        """'View all movements' link navigates to filtered movements page."""
        product_id, _sku = _product_with_movements(app)
        page.goto(f"/products/{product_id}")
        page.click("a:has-text('View all movements')")
        expect(page).to_have_url(re.compile(rf"/movements\?product_id={product_id}"))

    def test_filtered_page_shows_correct_product(self, page, auth_page, app):
        """Filtered movements page shows only that product's movements."""
        product_id, sku = _product_with_movements(app)
        page.goto(f"/movements?product_id={product_id}")
        rows = page.locator("tbody tr")
        assert rows.count() > 0
        for i in range(rows.count()):
            expect(rows.nth(i)).to_contain_text(sku)
