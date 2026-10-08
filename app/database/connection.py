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
import os
import threading
import time
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

# Connection pool configuration from environment variables with sensible defaults
_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "20"))
_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", "1800"))  # 30 minutes
_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", "30"))  # 30 seconds

# Statement/lock timeouts + UTC timezone applied at connect via libpq options
# (DB-038, DB-048). These survive pool reuse because they're set at backend start,
# outside any transaction, and cannot be rolled back.
# Default statement_timeout increased to 60s to accommodate longer queries
# (e.g., monitoring dashboard queries). Override via DB_STATEMENT_TIMEOUT_MS.
# Note: app.current_user_id GUC is NOT set here — it defaults to empty string.
# The application sets it per-transaction via set_config() in get_cursor().
_DB_OPTIONS = (
    f"-c statement_timeout={int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', '60000'))} "
    f"-c lock_timeout={int(os.environ.get('DB_LOCK_TIMEOUT_MS', '5000'))} "
    "-c TimeZone=UTC"
)

# Track connection checkout times for leak detection
_CHECKOUT_TIMES: dict[int, float] = {}
_CHECKOUT_LOCK = threading.Lock()

# Track connection birth timestamps for real recycle (DB-039)
_CONN_BORN: dict[int, float] = {}
_CONN_BORN_LOCK = threading.Lock()

# A small per-config pool so requests reuse connections instead of redoing
# the (potentially SSL) handshake on every page load.
_POOLS: dict[str, psycopg2.pool.ThreadedConnectionPool] = {}
_POOL_LOCK = threading.Lock()

# Bootstrap guard to ensure schema/seed/ETL runs exactly once per process
_BOOTSTRAPPED = False
_BOOTSTRAP_LOCK = threading.Lock()


def _pool_key(params: dict) -> str:
    return repr(sorted(params.items()))


def _make_conn(params: dict):
    if "dsn" in params:
        conn = psycopg2.connect(
            params["dsn"],
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=300,
            keepalives_interval=30,
            options=_DB_OPTIONS,
        )
    else:
        conn = psycopg2.connect(
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=15,
            keepalives=1,
            keepalives_idle=300,
            keepalives_interval=30,
            options=_DB_OPTIONS,
            **params,
        )

    # Stamp birth time for real recycle (DB-039)
    conn_id = id(conn)
    with _CONN_BORN_LOCK:
        _CONN_BORN[conn_id] = time.time()
    return conn


def _open_conn():
    """Open a raw psycopg2 connection using app config (for ETL/seed scripts).

    Note: ETL/seed scripts run long statements (10-60s) so they use a separate
    connection path WITHOUT statement_timeout/lock_timeout to avoid killing
    legitimate long-running operations. They still get TimeZone=UTC.
    """
    from flask import current_app

    params = current_app.config["psycopg2_params"]()
    etl_options = "-c TimeZone=UTC"
    if "dsn" in params:
        return psycopg2.connect(
            params["dsn"],
            cursor_factory=psycopg2.extras.RealDictCursor,
            options=etl_options,
        )
    return psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor,
        options=etl_options,
        **params,
    )


def _get_pool(params: dict):
    key = _pool_key(params)
    with _POOL_LOCK:
        pool = _POOLS.get(key)
        if pool is None:
            # minconn=_POOL_SIZE stops psycopg2 from closing surplus connections on check-in
            # (DB-039: pool churn). With minconn=1, pool.py:121-122 closes 19/20 check-ins.
            pool = psycopg2.pool.ThreadedConnectionPool(
                _POOL_SIZE, _POOL_SIZE, **_make_conn_kwargs(params)
            )
            _POOLS[key] = pool
        return pool


def _make_conn_kwargs(params: dict) -> dict:
    """Turn the config params into kwargs suitable for pool construction."""
    if "dsn" in params:
        kwargs = {
            "dsn": params["dsn"],
            "cursor_factory": psycopg2.extras.RealDictCursor,
            "connect_timeout": 15,
            "keepalives": 1,
            "keepalives_idle": 300,
            "keepalives_interval": 30,
            "options": _DB_OPTIONS,
        }
    else:
        kwargs = dict(params)
        kwargs["cursor_factory"] = psycopg2.extras.RealDictCursor
        kwargs["connect_timeout"] = 15
        kwargs["keepalives"] = 1
        kwargs["keepalives_idle"] = 300
        kwargs["keepalives_interval"] = 30
        kwargs["options"] = _DB_OPTIONS
    # Honor DB_SSLMODE in both branches (DB-039)
    if params.get("sslmode"):
        kwargs["sslmode"] = params["sslmode"]
    return kwargs


def _record_connection_checkout(conn):
    """Record the time a connection was checked out for leak detection."""
    conn_id = id(conn)
    with _CHECKOUT_LOCK:
        _CHECKOUT_TIMES[conn_id] = time.time()
    # Also ensure birth timestamp exists (for connections created before this fix)
    with _CONN_BORN_LOCK:
        _CONN_BORN.setdefault(conn_id, time.time())


def _record_connection_checkin(conn):
    """Record that a connection was checked back in and remove from leak tracking."""
    conn_id = id(conn)
    with _CHECKOUT_LOCK:
        if conn_id in _CHECKOUT_TIMES:
            checkout_time = _CHECKOUT_TIMES.pop(conn_id)
            # Log if connection was checked out for too long (possible leak)
            duration = time.time() - checkout_time
            if duration > 300:  # 5 minutes
                LOGGER.warning(
                    "Connection was checked out for %.2f seconds (possible leak)",
                    duration,
                )
    # Note: we do NOT pop _CONN_BORN here — the connection stays in the pool
    # and its birth time remains valid. We only pop on permanent close.


def get_connection():
    """Return a pooled, request-scoped psycopg2 connection.

    Connections are validated on checkout to avoid stale connections.
    """
    if "db" not in g:
        params = current_app.config["psycopg2_params"]()
        pool = _get_pool(params)
        conn = pool.getconn()
        
        # Record connection checkout for leak detection
        _record_connection_checkout(conn)
        
        # Validate and potentially recycle connection
        conn = _validate_and_recycle_connection(conn, pool)
        
        g.db = conn
        g.db_pool = pool
    return g.db


def _validate_connection(conn):
    """Validate a connection with SELECT 1. Returns True if valid, False otherwise."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def _validate_and_recycle_connection(conn, pool):
    """Validate a connection and recycle if too old, returning a valid connection."""
    # Check if connection is too old and needs to be recycled (pool_recycle functionality)
    # Use real birth timestamps from _CONN_BORN (DB-039 fix)
    try:
        conn_id = id(conn)
        with _CONN_BORN_LOCK:
            born = _CONN_BORN.get(conn_id)
        if born is not None:
            conn_age = time.time() - born
            if conn_age > _POOL_RECYCLE:
                LOGGER.debug(
                    "Recycling connection due to pool_recycle (age: %.2f s > %d s)",
                    conn_age, _POOL_RECYCLE
                )
                pool.putconn(conn, close=True)
                # Pop birth timestamp for the closed connection
                with _CONN_BORN_LOCK:
                    _CONN_BORN.pop(conn_id, None)
                conn = pool.getconn()
                # Record checkout for the new connection
                _record_connection_checkout(conn)
    except Exception:
        # If we can't check the age, continue with the connection
        pass
    
    # NOTE: Per-checkout SELECT 1 ping removed (DB-039/DB-052).
    # The ping was 1-2 RTT per request and contradicted the lazy-validation
    # design in AGENTS.md. Stale connections are now caught by the
    # first-execute retry proxy in get_cursor (DB-052).
    
    return conn


class _RetryOnceCursor:
    """Cursor wrapper that retries the FIRST execute once on stale connection.

    This implements the documented retry semantics that the old generator-based
    approach could never achieve (a @contextmanager cannot re-yield after throw()).
    """
    __slots__ = ("_conn", "_cur", "_commit", "_executed")

    def __init__(self, conn, commit: bool):
        self._conn = conn
        self._cur = conn.cursor()
        self._commit = commit
        self._executed = False

    def _maybe_retry(self, method_name, *args, **kwargs):
        if self._executed:
            # Already executed once — no retry, just propagate
            return getattr(self._cur, method_name)(*args, **kwargs)
        try:
            self._executed = True
            return getattr(self._cur, method_name)(*args, **kwargs)
        except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
            # Stale connection on first execute — retry once on fresh connection
            if isinstance(e, psycopg2.errors.QueryCanceled):
                raise  # Don't retry cancelled queries
            LOGGER.debug("Stale connection on first execute, retrying once: %s", e)
            # Rollback dirty transaction, evict bad connection
            try:
                self._conn.rollback()
            except Exception:
                pass
            try:
                self._cur.close()
            except Exception:
                pass
            pool = g.get("db_pool")
            if pool:
                try:
                    _record_connection_checkin(g.get("db"))
                    pool.putconn(g.get("db"), close=True)
                except Exception:
                    pass
            # Get fresh connection
            new_conn = pool.getconn() if pool else get_connection()
            g.db = new_conn
            _record_connection_checkout(new_conn)
            self._conn = new_conn
            self._cur = new_conn.cursor()
            # Retry the same call
            return getattr(self._cur, method_name)(*args, **kwargs)

    # Delegate all cursor methods with retry on first execute
    def execute(self, query, vars=None):
        return self._maybe_retry("execute", query, vars)

    def executemany(self, query, vars_list):
        return self._maybe_retry("executemany", query, vars_list)

    def callproc(self, procname, parameters=None):
        return self._maybe_retry("callproc", procname, parameters)

    # Make cursor iterable for streaming exports
    def __iter__(self):
        return iter(self._cur)

    # Passthrough for everything else
    def __getattr__(self, name):
        return getattr(self._cur, name)

    def close(self):
        self._cur.close()


@contextmanager
def get_cursor(commit: bool = False):
    """Context manager yielding a cursor that commits on success.

    Stale connections are handled by _RetryOnceCursor which retries the
    FIRST execute once on a fresh connection (DB-052). This replaces the
    broken generator re-yield approach that could never work.

    Sets app.current_user_id GUC for audit attribution if user is authenticated.
    Uses set_config() for custom GUC (SET LOCAL doesn't work for custom GUCs).
    """
    conn = get_connection()
    proxy = _RetryOnceCursor(conn, commit)
    try:
        # Set app.current_user_id GUC for audit attribution (transaction-local).
        # set_config(..., true) == SET LOCAL for custom GUCs; used because it
        # goes through the retry proxy as the first execute (stale-conn safe).
        if hasattr(g, 'user_id') and g.user_id is not None:
            proxy.execute("SELECT set_config('app.current_user_id', %s, true)", (str(g.user_id),))
        else:
            proxy.execute("SELECT set_config('app.current_user_id', '', true)")
        yield proxy
        if commit:
            proxy._conn.commit()
    except Exception as e:
        # Log unexpected exceptions for debugging
        LOGGER.exception("Unexpected exception in get_cursor: %s", e)
        proxy._conn.rollback()
        raise
    finally:
        proxy.close()
        # Record checkin for the connection
        _record_connection_checkin(proxy._conn)


def close_connection(_exc=None):
    db = g.pop("db", None)
    pool = g.pop("db_pool", None)
    if db is not None:
        try:
            if _exc is not None:
                db.rollback()
            # Record checkin for the connection
            _record_connection_checkin(db)
            pool.putconn(db)
        except Exception:
            LOGGER.debug("Could not return connection to pool.", exc_info=True)
            try:
                # Pop birth timestamp on permanent close
                with _CONN_BORN_LOCK:
                    _CONN_BORN.pop(id(db), None)
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


def get_pool_stats() -> dict:
    """Get statistics about the connection pools for monitoring.

    Pool keys embed full connection params (incl. password) via
    _pool_key() — expose only an ordinal so stats can never leak DSN.
    """
    stats = {}
    with _POOL_LOCK:
        for ordinal, _key in enumerate(_POOLS):
            stats[f"pool_{ordinal}"] = {
                "pool_size": _POOL_SIZE,
                "max_connections": _POOL_SIZE,
                "in_use": len(_CHECKOUT_TIMES),
            }
    return stats


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