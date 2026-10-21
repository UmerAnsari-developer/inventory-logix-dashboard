"""System alert module (ETL / backup / pool failure alerts)."""
from .alerts import (
    deduplicate_alerts,
    generate_backup_failure_alert,
    generate_etl_failure_alert,
    generate_pool_exhaustion_alert,
)

__all__ = [
    "deduplicate_alerts",
    "generate_backup_failure_alert",
    "generate_etl_failure_alert",
    "generate_pool_exhaustion_alert",
]
