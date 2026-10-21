"""F-V1: admin CSV export routes must stream without an ambient app context.

The service layer streams generators that call ``get_cursor()`` lazily. A
plain ``Response(generator)`` runs the generator after the request context
is popped → ``RuntimeError: Working outside of application context``. The
routes must wrap the iterator in ``flask.stream_with_context``.

The drain below deliberately happens OUTSIDE any app/request context — an
ambient ``app.app_context()`` would make the pre-fix code silently succeed.
"""
from __future__ import annotations

import pytest

EXPORT_ROUTES = [
    ("/admin/export/products", b"SKU,Product"),
    ("/admin/export/inventory", b"SKU,Product"),
    ("/admin/export/movements", b"ID,SKU"),
    ("/admin/export/suppliers", b"ID,Name"),
    ("/admin/export/purchase_orders", b"ID,PO Number"),
]


@pytest.mark.parametrize("route,header", EXPORT_ROUTES)
def test_export_route_streams_outside_context(auth_client, route, header):
    response = auth_client.get(route, buffered=False)

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert ".csv" in response.headers.get("Content-Disposition", "")

    body = b"".join(response.response)  # no app/request context here
    assert body.startswith(header), f"{route}: unexpected CSV header {body[:40]!r}"


def test_products_export_streams_data_rows(auth_client):
    """Seed data exists, so the stream must contain more than the header line."""
    response = auth_client.get("/admin/export/products", buffered=False)

    assert response.status_code == 200
    body = b"".join(response.response)
    assert body.count(b"\n") >= 2, "expected header + at least one data row"
