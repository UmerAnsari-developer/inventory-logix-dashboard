"""Alembic environment for raw SQL migrations."""
import os
import sys
from pathlib import Path
from logging.config import fileConfig
from urllib.parse import quote

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

# Add project root to path and load the project .env so `python migrate.py`
# works without exporting DATABASE_URL/DB_* in the shell.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

# libpq host overrides would bypass the target check below.
for _libpq in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
    os.environ.pop(_libpq, None)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override URL from environment if available; otherwise build it from the
# local DB_* fields. NOTE: never print the URL — it embeds the DB password.
db_url = os.environ.get("DATABASE_URL")
source = "DATABASE_URL"
if not db_url:
    source = "local DB_* environment"
    raw_host = os.environ.get("DB_HOST", "localhost").strip()
    if not raw_host or any(ch in raw_host for ch in "/@?#"):
        raise RuntimeError(
            "Refusing to run migrations: invalid DB_HOST (value redacted)."
        )
    try:
        port = int(os.environ.get("DB_PORT", "5432").strip())
    except ValueError:
        raise RuntimeError(
            "Refusing to run migrations: invalid DB_PORT (value redacted)."
        ) from None
    if not 1 <= port <= 65535:
        raise RuntimeError(
            "Refusing to run migrations: invalid DB_PORT (value redacted)."
        )
    raw_name = os.environ.get("DB_NAME", "inventory_db").strip()
    if not raw_name or any(ch in raw_name for ch in "/?#"):
        raise RuntimeError(
            "Refusing to run migrations: invalid DB_NAME (value redacted)."
        )
    host = f"[{raw_host}]" if ":" in raw_host and not raw_host.startswith("[") else raw_host
    db_url = "postgresql://{user}:{password}@{host}:{port}/{name}".format(
        user=quote(os.environ.get("DB_USER", "postgres"), safe=""),
        password=quote(os.environ.get("DB_PASSWORD", ""), safe=""),
        host=host,
        port=port,
        name=quote(raw_name, safe=""),
    )
    sslmode = os.environ.get("DB_SSLMODE", "").strip()
    if sslmode:
        db_url += f"?sslmode={quote(sslmode, safe='')}"

try:
    target = make_url(db_url)
except Exception:
    raise RuntimeError(
        "Could not parse the migration database URL (value redacted)."
    ) from None
host = target.host or ""
port = target.port or 5432
name = target.database or ""
allow_remote = os.environ.get("ALLOW_REMOTE_MIGRATIONS") == "1"
forbidden_query = {"host", "hostaddr", "service", "dbname", "port"} & set(target.query)
if forbidden_query and not allow_remote:
    raise RuntimeError(
        "Refusing to run migrations: target-overriding query parameter(s) "
        f"{', '.join(sorted(forbidden_query))}. Set ALLOW_REMOTE_MIGRATIONS=1 only "
        "when you intend to migrate a remote database."
    )
if host not in {"localhost", "127.0.0.1", "::1"} and not allow_remote:
    raise RuntimeError(
        f"Refusing to run migrations against non-local database host {host!r}. "
        "Set ALLOW_REMOTE_MIGRATIONS=1 only when you intend to migrate a remote database."
    )
# ConfigParser interpolates ``%`` in set_main_option values — escape it so an
# url-encoded password survives the round-trip.
config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
print(
    f"sqlalchemy.url set from {source}; target {host}:{port}/{name} "
    "(credentials redacted)",
    file=sys.stderr,
)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
