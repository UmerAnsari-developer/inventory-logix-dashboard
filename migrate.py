"""Migration helper — create and apply SQL migrations.

Usage:
    python migrate.py create "add Index to products"
    python migrate.py upgrade
    python migrate.py downgrade
    python migrate.py current
    python migrate.py history
"""
import sys
import os
from pathlib import Path
from datetime import datetime

MIGRATIONS_DIR = Path("migrations/versions")


def get_migration_files():
    """Return sorted list of migration files."""
    files = sorted(MIGRATIONS_DIR.glob("*.py"))
    return [f for f in files if f.name != "__pycache__"]


def create_migration(description: str):
    """Create a new empty migration file."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    slug = "".join(c if c.isalnum() else "_" for c in description)[:50]
    filename = f"{timestamp}_{slug}.py"
    filepath = MIGRATIONS_DIR / filename

    template = f'''"""{description}

Revision ID: {timestamp}
Revises:
Create Date: {datetime.now().isoformat()}
"""
from alembic import op
import sqlalchemy as sa

revision = "{timestamp}"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Write your SQL migration here
    pass


def downgrade() -> None:
    # Write your rollback SQL here
    pass
'''
    filepath.write_text(template, encoding="utf-8")
    print(f"Created: {filepath}")
    return filepath


def apply_upgrade():
    """Apply all pending migrations."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
    return result.returncode


def apply_downgrade():
    """Rollback one migration."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "-1"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
    return result.returncode


def show_current():
    """Show current migration state."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        capture_output=True, text=True
    )
    print(result.stdout)


def show_history():
    """Show migration history."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "history", "--verbose"],
        capture_output=True, text=True
    )
    print(result.stdout)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "create":
        if len(sys.argv) < 3:
            print("Usage: python migrate.py create 'description'")
            sys.exit(1)
        create_migration(sys.argv[2])
    elif cmd == "upgrade":
        apply_upgrade()
    elif cmd == "downgrade":
        apply_downgrade()
    elif cmd == "current":
        show_current()
    elif cmd == "history":
        show_history()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
