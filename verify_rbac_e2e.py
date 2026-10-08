"""End-to-end smoke test: RBAC hierarchy + reporting workflow + UI cleanup."""
import logging
logging.disable(logging.WARNING)
import os
os.environ["FLASK_ENV"] = "testing"

from app import create_app
app = create_app()
app.config["WTF_CSRF_ENABLED"] = False
app.config["TESTING"] = True

PASS, FAIL = "[PASS]", "[FAIL]"
results = []

def check(name, cond, detail=""):
    status = PASS if cond else FAIL
    results.append((name, status))
    print(f"{status} {name} {detail}")

with app.app_context():
    from app.services.user_service import UserService
    from app.repositories.user_repo import UserRepository
    from app.database.connection import _open_conn

    admin = UserRepository.find_by_username("admin")
    manager = UserRepository.find_by_username("manager")
    viewer = UserRepository.find_by_username("viewer")
    UserService.set_reporting_manager(viewer.id, manager.id, admin)

    client = app.test_client()

    # -- 1. Viewer submits a report --
    resp = client.post("/auth/login", data={"username": "viewer", "password": "Viewer@123"},
                       follow_redirects=True)
    check("Viewer login", resp.status_code == 200)
    resp = client.get("/reports/submit")
    check("Submit Report page renders (viewer)", resp.status_code == 200)
    html = resp.get_data(as_text=True)
    check("Reporting manager auto-populated", "manager" in html.lower())
    resp = client.post("/reports/submit", data={
        "title": "Weekly stock reconciliation",
        "report_type": "warehouse",
        "priority": "high",
        "description": "Recount of WH-Pune completed",
        "due_date": "2026-10-10",
    }, follow_redirects=True)
    check("Viewer submits report", resp.status_code == 200)

    # -- 2. Manager sees it in My Team --
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "manager", "password": "Manager@123"},
                       follow_redirects=True)
    check("Manager login", resp.status_code == 200)
    resp = client.get("/team")
    check("My Team page renders (manager)", resp.status_code == 200)
    html = resp.get_data(as_text=True)
    check("Team inbox shows the report", "Weekly stock reconciliation" in html)
    check("Direct reports table shows viewer", "viewer" in html and "Direct Reports" in html)

    # -- 3. Manager reviews it --
    with app.app_context():
        from app.services.report_service import ReportService
        reports = ReportService.list_team_reports(manager.id)
        rid = reports[0]["id"]
    resp = client.get(f"/reports/{rid}")
    check("Report detail renders (manager)", resp.status_code == 200)
    resp = client.post(f"/reports/{rid}/status", data={"status": "approved", "comment": "OK"},
                       follow_redirects=True)
    check("Manager approves report", resp.status_code == 200)
    with app.app_context():
        from app.services.report_service import ReportService
        r = ReportService.get_report(rid, manager)
        check("Status = approved", r["status"] == "approved")
        check("Review comment saved", r["review_comment"] == "OK")

    # -- 4. IDOR --
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "viewer", "password": "Viewer@123"},
                follow_redirects=True)
    resp = client.get("/reports/999999")
    check("IDOR: nonexistent report gives 404", resp.status_code == 404)
    resp = client.get("/team")
    check("IDOR: viewer cannot access /team (403)", resp.status_code == 403)

    # -- 5. Viewer cannot self-approve --
    resp = client.post(f"/reports/{rid}/status", data={"status": "completed"},
                       follow_redirects=True)
    with app.app_context():
        from app.services.report_service import ReportService
        r = ReportService.get_report(rid, manager)
        check("Submitter cannot change status", r["status"] == "approved")

    # -- 6. Dashboard layout + 3D/animation cleanup --
    client.post("/auth/logout")
    resp = client.post("/auth/login", data={"username": "manager", "password": "Manager@123"},
                follow_redirects=True)
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    check("Dashboard renders", resp.status_code == 200)
    check("Stock movement + Inventory mix paired", "Stock movement" in html and "Inventory mix" in html)
    check("Slow-moving + Top demand paired", "Slow-moving products" in html and "Top demand" in html)
    check("Top sales + Top suppliers paired", "Top sales" in html and "Top suppliers" in html)
    check("Turnover + ABC paired", "Stock turnover rate" in html and "ABC Analysis" in html)
    js = open("app/static/js/dashboard-3d.js", encoding="utf-8").read()
    check("No 3D transforms in dashboard-3d.js",
          "perspective(" not in js and "rotateY(" not in js and "rotateX(" not in js)
    js2 = open("app/static/js/auth-bg.js", encoding="utf-8").read()
    check("auth-bg.js skips app pages (isNonLanding)", "if (isNonLanding) {" in js2)

    # -- Cleanup --
    with app.app_context():
        conn = _open_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reports WHERE id = %s", (rid,))
            cur.execute("UPDATE users SET reporting_manager_id = NULL")
        conn.commit()

print()
fails = sum(1 for _, s in results if s == FAIL)
print("=" * 60)
print(f"RESULT: {len(results) - fails}/{len(results)} checks passed, {fails} failed")