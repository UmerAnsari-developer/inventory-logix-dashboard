"""PostgreSQL connection helpers built on psycopg2.

Provides per-request connection pooling, schema bootstrap, and sample-data
seeding so the rest of the application can treat the database as a black box.

Connections are drawn from a small :class:`psycopg2.pool.ThreadedConnectionPool`
keyed by the active database configuration. Reusing connections avoids paying
a fresh TCP + TLS handshake on every request — important when the database is
remote (e.g. Render) rather than localhost.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import current_app, g

LOGGER = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
PROCEDURES_PATH = Path(__file__).with_name("procedures.sql")
WAREHOUSE_PATH = Path(__file__).with_name("warehouse.sql")
ETL_PROCEDURES_PATH = Path(__file__).with_name("etl_procedures.sql")
TRIGGERS_PATH = Path(__file__).with_name("triggers.sql")

# A small per-config pool so requests reuse connections instead of redoing
# the (potentially SSL) handshake for every page load.
_POOLS: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}
_POOL_LOCK = threading.Lock()
_POOL_SIZE = 20


def _pool_key(params: dict) -> str:
    return repr(sorted(params.items()))


def _make_conn(params: dict):
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"],
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=300,
            keepalives_interval=30,
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor,
        connect_timeout=15,
        keepalives=1,
        keepalives_idle=300,
        keepalives_interval=30,
        **params,
    )


def _open_conn():
    """Open a raw psycopg2 connection using app config (for ETL/seed scripts)."""
    from flask import current_app
    params = current_app.config["psycopg2_params"]()
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"], cursor_factory=psycopg2.extras.RealDictCursor
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor, **params
    )


def _get_pool(params: dict):
    key = _pool_key(params)
    with _POOL_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            pool = psycopg2.pool.ThreadedConnectionPool(1, _POOL_SIZE, **_make_conn_kwargs(params))
            _POOLS[key] = pool
        return pool


def _make_conn_kwargs(params: dict) -> dict:
    """Turn the config params into kwargs suitable for pool construction."""
    if "dsn" in params:
        return {
            "dsn": params["dsn"],
            "cursor_factory": psycopg2.extras.RealDictCursor,
            "connect_timeout": 15,
            "keepalives": 1,
            "keepalives_idle": 300,
            "keepalives_interval": 30,
        }
    kwargs = dict(params)
    kwargs["cursor_factory"] = psycopg2.extras.RealDictCursor
    kwargs["connect_timeout"] = 15
    kwargs["keepalives"] = 1
    kwargs["keepalives_idle"] = 300
    kwargs["keepalives_interval"] = 30
    return kwargs


def get_connection():
    """Return a pooled, request-scoped psycopg2 connection.

    Connections are lazily health-checked: the first real query on a stale
    connection will fail, triggering a single reconnect instead of paying
    a ``SELECT 1`` round-trip on every request.
    """
    if "db" not in g:
        params = current_app.config["psycopg2_params"]()
        pool = _get_pool(params)
        g.db = pool.getconn()
        g.db_pool = pool
    return g.db


@contextmanager
def get_cursor(commit: bool = False):
    """Context manager yielding a cursor that commits on success.

    On a stale-connection error the pooled connection is replaced and the
    operation is retried once (handles server idle-timeout disconnects).
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except (psycopg2.InterfaceError, psycopg2.OperationalError):
        conn.rollback()
        cur.close()
        pool = g.get("db_pool")
        if pool:
            try:
                pool.putconn(g.get("db"), close=True)
            except Exception:
                pass
        new_conn = pool.getconn() if pool else get_connection()
        g.db = new_conn
        cur = new_conn.cursor()
        try:
            yield cur
            if commit:
                new_conn.commit()
        except Exception:
            new_conn.rollback()
            raise
        finally:
            cur.close()
        return
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def close_connection(_exc=None):
    db = g.pop("db", None)
    pool = g.pop("db_pool", None)
    if db is not None:
        try:
            if _exc is not None:
                db.rollback()
            pool.putconn(db)
        except Exception:
            LOGGER.debug("Could not return connection to pool.", exc_info=True)
            try:
                db.close()
            except Exception:
                pass


def init_schema() -> None:
    """Apply schema.sql, procedures.sql, warehouse.sql, etl_procedures.sql, triggers.sql."""
    sql_files = [
        ("schema", SCHEMA_PATH),
        ("procedures", PROCEDURES_PATH),
        ("warehouse", WAREHOUSE_PATH),
        ("etl_procedures", ETL_PROCEDURES_PATH),
        ("triggers", TRIGGERS_PATH),
    ]
    params = current_app.config["psycopg2_params"]()
    conn = _make_conn(params)
    try:
        with conn.cursor() as cur:
            for name, path in sql_files:
                if path.exists():
                    sql_text = path.read_text(encoding="utf-8")
                    cur.execute(sql_text)
                    LOGGER.info("Applied %s.sql", name)
        conn.commit()
        LOGGER.info("Database schema initialised (all files).")
    finally:
        conn.close()


def seed_database(force: bool = False) -> None:
    """Populate the database with realistic sample data.

    Imports lazily to avoid circular imports.
    """
    from .seed import run_seed

    run_seed(force=force)


def etl_database(force: bool = False) -> dict:
    """Build the star-schema data warehouse from the operational tables."""
    from .etl import run_etl

    return run_etl(force=force)


_BOOTSTRAPPED = False
_BOOTSTRAP_LOCK = threading.Lock()


def _schema_exists() -> bool:
    """Return True if the core schema tables already exist (1 query)."""
    try:
        conn = _make_conn(current_app.config["psycopg2_params"]())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'products' LIMIT 1"
                )
                return cur.fetchone() is not None
        finally:
            conn.close()
    except Exception:
        return False


def bootstrap_database() -> None:
    """Run schema init, seed and ETL at most once per process.

    Skips the full bootstrap (100+ SQL statements) when the core schema
    already exists — a single ``SELECT`` check saves ~60-120 s on remote DBs.
    """
    global _BOOTSTRAPPED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return
        if _schema_exists():
            _BOOTSTRAPPED = True
            return
        init_schema()
        seed_database()
        if current_app.config.get("RUN_ETL_ON_STARTUP", True):
            etl_database()
        _BOOTSTRAPPED = True
