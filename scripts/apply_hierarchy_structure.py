"""Apply the new role naming + hierarchy to the LOCAL inventory_db.

- Migrate roles table: old job_role keys -> new industry-standard keys
- Rename/create users per the target structure
- Set the 4-level reporting hierarchy
"""
import logging
logging.disable(logging.WARNING)
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["FLASK_ENV"] = "development"

from app import create_app
app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

with app.app_context():
    from app.database.connection import _open_conn
    from app.repositories.user_repo import UserRepository
    from app.services.user_service import UserService
    from werkzeug.security import generate_password_hash

    conn = _open_conn()
    try:
        with conn.cursor() as cur:
            # ── 1. Roles table: seed new keys + labels ──
            cur.execute("""
INSERT INTO roles (job_role, label, department, sort_order) VALUES
    ('inventory_director',      'Inventory & Supply Chain Director', 'Leadership', 1),
    ('vp_operations',           'VP of Operations',                  'Leadership', 2),
    ('procurement_manager',     'Procurement Manager',               'Procurement', 3),
    ('warehouse_manager',       'Warehouse Operations Manager',      'Warehouse', 3),
    ('demand_planning_analyst', 'Demand Planning Analyst',           'Analytics', 3),
    ('procurement_buyer',       'Procurement Buyer',                 'Procurement', 4),
    ('procurement_coordinator', 'Procurement Coordinator',           'Procurement', 4),
    ('supplier_coordinator',    'Supplier Relationship Coordinator', 'Procurement', 4),
    ('receiving_associate',     'Receiving Associate',               'Warehouse', 4),
    ('inventory_analyst',       'Inventory Control Analyst',         'Warehouse', 4)
ON CONFLICT (job_role) DO UPDATE SET label = EXCLUDED.label,
    department = EXCLUDED.department, sort_order = EXCLUDED.sort_order
            """)
            # Migrate permissions from old keys to new keys
            cur.execute("""
INSERT INTO job_role_permissions (job_role, permission)
SELECT 'procurement_buyer', permission FROM job_role_permissions WHERE job_role = 'buyer'
ON CONFLICT DO NOTHING
            """)
            cur.execute("""
INSERT INTO job_role_permissions (job_role, permission)
SELECT 'procurement_coordinator', permission FROM job_role_permissions WHERE job_role = 'purchasing_clerk'
ON CONFLICT DO NOTHING
            """)
            cur.execute("""
INSERT INTO job_role_permissions (job_role, permission)
SELECT 'receiving_associate', permission FROM job_role_permissions WHERE job_role = 'receiving_clerk'
ON CONFLICT DO NOTHING
            """)
            cur.execute("""
INSERT INTO job_role_permissions (job_role, permission)
SELECT 'demand_planning_analyst', permission FROM job_role_permissions WHERE job_role = 'forecast_specialist'
ON CONFLICT DO NOTHING
            """)
            # Drop old keys
            cur.execute("DELETE FROM job_role_permissions WHERE job_role IN ('buyer','purchasing_clerk','receiving_clerk','forecast_specialist')")
            cur.execute("DELETE FROM roles WHERE job_role IN ('buyer','purchasing_clerk','receiving_clerk','forecast_specialist')")
            print("Roles migrated to industry-standard keys")

            # ── 2. Users: rename + create per target structure ──
            # (username, password, role_tier, job_role, full_name)
            USERS = [
                ("inventory.director",      "Director@123",    "admin",   "inventory_director",      "Devansh Rao"),
                ("vp.operations",           "Operations@123",  "manager", "vp_operations",           "Meera Kapoor"),
                ("procurement.manager",     "Procurement@123", "manager", "procurement_manager",     "Sarah Khan"),
                ("warehouse.manager",       "Warehouse@123",   "manager", "warehouse_manager",       "Ravi Sharma"),
                ("demand.planning.analyst", "Forecast@123",    "manager", "demand_planning_analyst", "Arjun Mehta"),
                ("procurement.buyer",       "Buyer@123",       "manager", "procurement_buyer",       "John Smith"),
                ("procurement.coordinator", "Purchasing@123",  "manager", "procurement_coordinator", "Ali Khan"),
                ("supplier.coordinator",    "Coordinator@123", "viewer",  "supplier_coordinator",    "Sara Ahmed"),
                ("receiving.associate",     "Receiving@123",   "manager", "receiving_associate",     "Priya Patel"),
                ("inventory.analyst",       "Analyst@123",     "viewer",  "inventory_analyst",       "Neha Gupta"),
            ]
            # Rename old users where they exist
            RENAMES = [
                ("buyer", "procurement.buyer"),
                ("clerk", "procurement.coordinator"),
                ("receiving.clerk", "receiving.associate"),
                ("forecast.specialist", "demand.planning.analyst"),
            ]
            for old, new in RENAMES:
                cur.execute("SELECT id FROM users WHERE username = %s", (old,))
                if cur.fetchone():
                    cur.execute("UPDATE users SET username = %s WHERE username = %s", (new, old))
                    print(f"  renamed: {old} -> {new}")
            # Create missing users
            for username, password, role, job_role, full_name in USERS:
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                if row:
                    uid = row["id"]
                    cur.execute(
                        "UPDATE users SET password_hash = %s, role = %s, job_role = %s, "
                        "full_name = %s, department = %s WHERE id = %s",
                        (generate_password_hash(password), role, job_role, full_name,
                         {"inventory_director": "Leadership", "vp_operations": "Leadership",
                          "procurement_manager": "Procurement", "warehouse_manager": "Warehouse",
                          "demand_planning_analyst": "Analytics", "procurement_buyer": "Procurement",
                          "procurement_coordinator": "Procurement", "supplier_coordinator": "Procurement",
                          "receiving_associate": "Warehouse", "inventory_analyst": "Warehouse"}[job_role],
                         uid),
                    )
                    print(f"  updated: {username} ({role}/{job_role})")
                else:
                    cur.execute(
                        "INSERT INTO users (username, email, password_hash, role, job_role, full_name, department) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                        (username, f"{username}@inventorylogix.local", generate_password_hash(password),
                         role, job_role, full_name,
                         {"inventory_director": "Leadership", "vp_operations": "Leadership",
                          "procurement_manager": "Procurement", "warehouse_manager": "Warehouse",
                          "demand_planning_analyst": "Analytics", "procurement_buyer": "Procurement",
                          "procurement_coordinator": "Procurement", "supplier_coordinator": "Procurement",
                          "receiving_associate": "Warehouse", "inventory_analyst": "Warehouse"}[job_role]),
                    )
                    print(f"  created: {username} / {password} ({role}/{job_role})")

            # ── 3. Reporting hierarchy (4 levels) ──
            cur.execute("SELECT id, username FROM users WHERE username = ANY(%s)",
                        ([u[0] for u in USERS],))
            ids = {r["username"]: r["id"] for r in cur.fetchall()}
            HIERARCHY = [
                ("vp.operations",           "inventory.director"),
                ("procurement.manager",     "vp.operations"),
                ("warehouse.manager",       "vp.operations"),
                ("demand.planning.analyst", "vp.operations"),
                ("procurement.buyer",       "procurement.manager"),
                ("procurement.coordinator", "procurement.manager"),
                ("supplier.coordinator",    "procurement.manager"),
                ("receiving.associate",     "warehouse.manager"),
                ("inventory.analyst",       "warehouse.manager"),
            ]
            # Reset first to avoid cycle errors on re-run
            cur.execute("UPDATE users SET reporting_manager_id = NULL WHERE username = ANY(%s)",
                        ([u[0] for u in USERS],))
            for subordinate, manager in HIERARCHY:
                cur.execute(
                    "UPDATE users SET reporting_manager_id = %s WHERE id = %s",
                    (ids[manager], ids[subordinate]),
                )
                print(f"  hierarchy: {subordinate} -> {manager}")
        conn.commit()
        print("\nAll applied.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()