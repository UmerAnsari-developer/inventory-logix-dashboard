"""API CSV exports must stream with the request context (both /api and /api/v1)."""
from __future__ import annotations

import pytest

EXPORT_ROUTES = [
    ("/export/products", b"SKU,Product"),
    ("/export/inventory", b"SKU,Product"),
    ("/export/suppliers", b"ID,Name"),
    ("/export/purchase_orders", b"ID,PO Number"),
]


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
@pytest.mark.parametrize("path,header", EXPORT_ROUTES)
def test_api_export_streams_csv(auth_client, prefix, path, header):
    response = auth_client.get(prefix + path, buffered=False)

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert ".csv" in response.headers.get("Content-Disposition", "")

    body = b"".join(response.response)  # drained outside app/request context
    assert body.startswith(header)
