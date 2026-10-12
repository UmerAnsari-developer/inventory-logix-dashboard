"""Tests for forecast model monitoring module."""
from __future__ import annotations

import math
import pytest


# ── Forecast Error ────────────────────────────────────────────────────────

from app.monitoring.metrics import (
    forecast_error, absolute_error, percentage_error,
    absolute_percentage_error, calculate_mae, calculate_mape,
    calculate_rmse, calculate_bias, calculate_error_std, evaluate_all,
)


class TestForecastError:
    def test_positive_error_underestimate(self):
        assert forecast_error(145, 120) == 25

    def test_negative_error_overestimate(self):
        assert forecast_error(100, 130) == -30

    def test_zero_error(self):
        assert forecast_error(50, 50) == 0

    def test_absolute_error(self):
        assert absolute_error(100, 130) == 30
        assert absolute_error(145, 120) == 25

    def test_percentage_error(self):
        r = percentage_error(100, 80)
        assert abs(r - 20.0) < 0.01

    def test_percentage_error_negative(self):
        r = percentage_error(100, 120)
        assert abs(r - (-20.0)) < 0.01

    def test_percentage_error_zero_actual(self):
        assert percentage_error(0, 20) == 0.0

    def test_absolute_percentage_error(self):
        r = absolute_percentage_error(100, 80)
        assert abs(r - 20.0) < 0.01

    def test_absolute_percentage_error_zero_actual(self):
        assert absolute_percentage_error(0, 20) == 0.0


# ── MAE ──────────────────────────────────────────────────────────────────

class TestMAE:
    def test_normal_values(self):
        assert calculate_mae([10, 10, 10]) == 10.0

    def test_mixed_errors(self):
        assert calculate_mae([5, -3, 8]) == pytest.approx(16 / 3)

    def test_empty(self):
        assert calculate_mae([]) is None

    def test_single(self):
        assert calculate_mae([7]) == 7.0

    def test_all_zero(self):
        assert calculate_mae([0, 0, 0]) == 0.0


# ── MAPE ─────────────────────────────────────────────────────────────────

class TestMAPE:
    def test_normal_values(self):
        actuals = [100, 120, 150]
        predicted = [90, 130, 140]
        mape, valid, zero = calculate_mape(actuals, predicted)
        assert mape is not None
        assert mape == pytest.approx(((10/100 + 10/120 + 10/150) / 3) * 100)
        assert valid == 3
        assert zero == 0

    def test_zero_actual_excluded(self):
        actuals = [100, 0, 150]
        predicted = [90, 20, 140]
        mape, valid, zero = calculate_mape(actuals, predicted)
        assert zero == 1
        assert valid == 2
        assert mape is not None

    def test_all_zero_actuals(self):
        mape, valid, zero = calculate_mape([0, 0], [10, 20])
        assert mape is None
        assert valid == 0
        assert zero == 2

    def test_empty(self):
        mape, valid, zero = calculate_mape([], [])
        assert mape is None
        assert valid == 0
        assert zero == 0

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            calculate_mape([1, 2], [1])

    def test_single_observation(self):
        mape, valid, zero = calculate_mape([100], [110])
        assert mape == pytest.approx(10.0)
        assert valid == 1


# ── RMSE ─────────────────────────────────────────────────────────────────

class TestRMSE:
    def test_known_values(self):
        errors = [3, -4]
        # sqrt((9 + 16) / 2) = sqrt(12.5) ≈ 3.5355
        assert calculate_rmse(errors) == pytest.approx(3.5355, abs=0.01)

    def test_empty(self):
        assert calculate_rmse([]) is None

    def test_single(self):
        assert calculate_rmse([5]) == 5.0


# ── Bias ─────────────────────────────────────────────────────────────────

class TestBias:
    def test_positive_bias(self):
        assert calculate_bias([10, 20, 30]) == 20.0

    def test_negative_bias(self):
        assert calculate_bias([-10, -20]) == -15.0

    def test_zero_bias(self):
        assert calculate_bias([5, -5]) == 0.0

    def test_empty(self):
        assert calculate_bias([]) is None


# ── Error Std ────────────────────────────────────────────────────────────

class TestErrorStd:
    def test_known_values(self):
        std = calculate_error_std([2, 4, 4, 4, 5, 5, 7, 9])
        assert std == pytest.approx(2.138, abs=0.01)

    def test_single(self):
        assert calculate_error_std([5]) is None

    def test_empty(self):
        assert calculate_error_std([]) is None


# ── Evaluate All ─────────────────────────────────────────────────────────

class TestEvaluateAll:
    def test_returns_all_keys(self):
        result = evaluate_all([100, 120], [90, 130])
        assert "mae" in result
        assert "mape" in result
        assert "rmse" in result
        assert "mean_error" in result
        assert "error_std" in result
        assert "observation_count" in result
        assert "zero_demand_count" in result

    def test_observation_count(self):
        result = evaluate_all([1, 2, 3], [1, 2, 3])
        assert result["observation_count"] == 3
        assert result["mae"] == 0.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            evaluate_all([1, 2], [1])


# ── Degradation Detection ────────────────────────────────────────────────

from app.monitoring.degradation import detect_degradation, sustained_degradation, model_health_status


class TestDegradation:
    def test_healthy(self):
        r = detect_degradation(20, 22)
        assert r["status"] == "healthy"
        assert r["change_percent"] < 0

    def test_warning(self):
        r = detect_degradation(25, 22)
        assert r["status"] == "warning"

    def test_degraded(self):
        # (28-22)/22 * 100 = 27.27%, above 25% degraded threshold
        r = detect_degradation(28, 22)
        assert r["status"] == "degraded"

    def test_critical(self):
        r = detect_degradation(50, 22)
        assert r["status"] == "critical"

    def test_no_baseline(self):
        r = detect_degradation(20, None)
        assert r["status"] == "healthy"

    def test_zero_baseline(self):
        r = detect_degradation(20, 0)
        assert r["status"] == "healthy"

    def test_no_current(self):
        r = detect_degradation(None, 20)
        assert r["status"] == "healthy"

    def test_sustained_degradation(self):
        statuses = ["healthy"] * 5 + ["degraded"] * 7
        assert sustained_degradation(statuses, window=7) is True

    def test_sustained_not_enough(self):
        statuses = ["healthy"] * 5 + ["degraded"] * 3
        assert sustained_degradation(statuses, window=7) is False

    def test_sustained_mixed(self):
        statuses = ["degraded", "healthy", "degraded", "degraded", "degraded", "degraded", "degraded"]
        assert sustained_degradation(statuses, window=7) is False

    def test_model_health_status(self):
        s = model_health_status(35, 20, 20, 10)
        assert s in ("degraded", "critical", "warning", "healthy")

    def test_model_health_healthy(self):
        s = model_health_status(10, 5, 12, 6)
        assert s == "healthy"


# ── Alert Generation ─────────────────────────────────────────────────────

from app.monitoring.alerts import generate_alert, deduplicate_alerts


class TestAlerts:
    def test_generate_alert_info(self):
        # 5% change < 10% warning threshold = info
        a = generate_alert(sku="SKU-1", model_name="prophet",
                           alert_date="2026-01-01", alert_type="mae_degradation",
                           metric="mae", baseline_value=20, current_value=21,
                           change_percent=5)
        assert a["severity"] == "info"
        assert a["sku"] == "SKU-1"

    def test_generate_alert_warning(self):
        # 10% change >= 10% warning threshold = warning
        a = generate_alert(sku="SKU-1", model_name="prophet",
                           alert_date="2026-01-01", alert_type="mae_degradation",
                           metric="mae", baseline_value=20, current_value=22,
                           change_percent=10)
        assert a["severity"] == "warning"

    def test_generate_alert_critical(self):
        a = generate_alert(sku="SKU-1", model_name="prophet",
                           alert_date="2026-01-01", alert_type="mae_degradation",
                           metric="mae", baseline_value=20, current_value=50,
                           change_percent=150)
        assert a["severity"] == "critical"

    def test_deduplicate_no_existing(self):
        new = {"sku": "A", "model_name": "p", "alert_type": "x"}
        assert deduplicate_alerts([], new) is True

    def test_deduplicate_existing_unresolved(self):
        existing = [{"sku": "A", "model_name": "p", "alert_type": "x", "status": "new"}]
        new = {"sku": "A", "model_name": "p", "alert_type": "x"}
        assert deduplicate_alerts(existing, new) is False

    def test_deduplicate_existing_resolved(self):
        existing = [{"sku": "A", "model_name": "p", "alert_type": "x", "status": "resolved"}]
        new = {"sku": "A", "model_name": "p", "alert_type": "x"}
        assert deduplicate_alerts(existing, new) is True

    def test_deduplicate_different_sku(self):
        existing = [{"sku": "B", "model_name": "p", "alert_type": "x", "status": "new"}]
        new = {"sku": "A", "model_name": "p", "alert_type": "x"}
        assert deduplicate_alerts(existing, new) is True


# ── API Smoke Tests ──────────────────────────────────────────────────────

class TestMonitoringAPI:
    def test_monitoring_page_renders(self, auth_client):
        resp = auth_client.get("/ai/monitoring")
        assert resp.status_code in (200, 302)

    def test_monitoring_summary(self, auth_client):
        resp = auth_client.get("/ai/monitoring/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_monitoring_health(self, auth_client):
        resp = auth_client.get("/ai/monitoring/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_monitoring_metrics(self, auth_client):
        resp = auth_client.get("/ai/monitoring/metrics")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_monitoring_avp(self, auth_client):
        resp = auth_client.get("/ai/monitoring/actual-vs-predicted")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_monitoring_alerts(self, auth_client):
        resp = auth_client.get("/ai/monitoring/alerts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True

    def test_monitoring_predictions(self, auth_client):
        resp = auth_client.get("/ai/monitoring/predictions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


# ── GAP-016: Pinned Model Baselines ──────────────────────────────────────

import uuid
from datetime import date

from app.database import get_cursor
from app.repositories import UserRepository
from app.repositories.monitoring_repo import MonitoringRepository
from app.services import MonitoringService


def _session_client(app, username: str):
    """Authenticated client without hitting the /auth/login rate limiter.

    Mirrors the proven pattern from tests/test_batch3_phase2.py.
    """
    from flask_login.utils import _create_identifier

    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture)
    try:
        resp = c.get("/static/img/favicon.svg")
        assert resp.status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


@pytest.fixture()
def _baseline_sku(app):
    """Unique SKU with two metrics windows (Jan old, Feb new); cleans up after."""
    sku = f"BL-{uuid.uuid4().hex[:8].upper()}"
    with app.app_context():
        MonitoringRepository.save_metrics(
            sku=sku, model_name="prophet",
            monitoring_date=date(2026, 1, 1), aggregation_period="daily",
            observation_count=10, mae=10.0, mape=10.0, rmse=12.0,
            mean_error=0.0, error_std=1.0, zero_demand_count=0,
            baseline_mae=None, baseline_mape=None,
            mae_change_percent=0.0, mape_change_percent=0.0,
            model_status="healthy",
        )
        MonitoringRepository.save_metrics(
            sku=sku, model_name="prophet",
            monitoring_date=date(2026, 2, 1), aggregation_period="daily",
            observation_count=10, mae=20.0, mape=20.0, rmse=22.0,
            mean_error=0.0, error_std=1.0, zero_demand_count=0,
            baseline_mae=10.0, baseline_mape=10.0,
            mae_change_percent=100.0, mape_change_percent=100.0,
            model_status="degraded",
        )
    yield sku
    with app.app_context():
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM model_baselines WHERE sku = %s", (sku,))
            cur.execute("DELETE FROM forecast_monitoring_metrics WHERE sku = %s", (sku,))


class TestPinnedBaselines:
    def test_baseline_fallback_without_promotion(self, app, _baseline_sku):
        """No pinned row → oldest-window behavior preserved (pre-GAP-016)."""
        sku = _baseline_sku
        with app.app_context():
            baseline = MonitoringRepository.baseline_metrics(sku, "prophet")
            assert baseline is not None
            assert float(baseline["mae"]) == 10.0  # oldest window, not the latest
            assert float(baseline["mape"]) == 10.0

    def test_promote_baseline_pins_metrics(self, app, _baseline_sku):
        """Promotion → baseline_metrics returns the pinned (latest) values."""
        sku = _baseline_sku
        with app.app_context():
            MonitoringService.promote_baseline(
                sku, model_name="prophet", promoted_by="tester"
            )
            baseline = MonitoringRepository.baseline_metrics(sku, "prophet")
            assert float(baseline["mae"]) == 20.0
            assert float(baseline["mape"]) == 20.0
            assert baseline["source"] == "promotion"
            assert baseline["promoted_by"] == "tester"

    def test_promote_upsert_overwrites(self, app, _baseline_sku):
        """Re-promotion overwrites the pinned row — never a duplicate."""
        sku = _baseline_sku
        with app.app_context():
            MonitoringService.promote_baseline(sku, model_name="prophet")
            MonitoringService.promote_baseline(
                sku, model_name="prophet", promoted_by="second"
            )
            pinned = MonitoringRepository.get_pinned_baseline(sku, "prophet")
            assert pinned["promoted_by"] == "second"
            with get_cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM model_baselines WHERE sku = %s",
                    (sku,),
                )
                assert cur.fetchone()["c"] == 1

    def test_promote_endpoint_rbac(self, app, _baseline_sku):
        """viewer → 403; manager and admin → 200 with pinned values."""
        sku = _baseline_sku
        viewer_resp = _session_client(app, "viewer").post(
            "/ai/monitoring/promote-baseline", json={"sku": sku}
        )
        assert viewer_resp.status_code == 403

        manager_resp = _session_client(app, "manager").post(
            "/ai/monitoring/promote-baseline", json={"sku": sku}
        )
        assert manager_resp.status_code == 200

        admin_resp = _session_client(app, "admin").post(
            "/ai/monitoring/promote-baseline", json={"sku": sku}
        )
        assert admin_resp.status_code == 200
        data = admin_resp.get_json()
        assert data["success"] is True
        with app.app_context():
            pinned = MonitoringRepository.get_pinned_baseline(sku, "prophet")
            assert pinned is not None
            assert float(pinned["mae"]) == 20.0
