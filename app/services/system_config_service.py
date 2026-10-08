"""System configuration override service."""
from __future__ import annotations

from flask import g
from flask_login import current_user

from ..database import get_cursor
from ..repositories import SystemConfigRepository


class SystemConfigService:
    """Service for managing system configuration overrides."""

    # Allowlist of valid configuration keys that can be overridden via admin UI
    ALLOWED_KEYS = {
        # Anomaly detection thresholds
        "ANOMALY_ZWARNING": {"type": "float", "min": 0.1, "max": 10.0, "description": "Z-score warning threshold"},
        "ANOMALY_ZHIGH": {"type": "float", "min": 0.1, "max": 10.0, "description": "Z-score high threshold"},
        "ANOMALY_ZCRITICAL": {"type": "float", "min": 0.1, "max": 10.0, "description": "Z-score critical threshold"},
        "ANOMALY_CONTAMINATION": {"type": "float", "min": 0.001, "max": 0.5, "description": "Isolation Forest contamination"},
        "ANOMALY_RULE_MULTIPLIER": {"type": "float", "min": 0.1, "max": 10.0, "description": "Rule-based anomaly multiplier"},
        "ANOMALY_FORECAST_DEVIATION": {"type": "float", "min": 0.01, "max": 1.0, "description": "Forecast deviation threshold"},
        
        # Model monitoring thresholds
        "MODEL_WARNING_THRESHOLD": {"type": "float", "min": 1, "max": 100, "description": "Model warning threshold %"},
        "MODEL_DEGRADATION_THRESHOLD": {"type": "float", "min": 1, "max": 100, "description": "Model degradation threshold %"},
        "MODEL_CRITICAL_THRESHOLD": {"type": "float", "min": 1, "max": 100, "description": "Model critical threshold %"},
        "MODEL_MONITORING_WINDOW": {"type": "int", "min": 1, "max": 90, "description": "Model monitoring window days"},
        
        # Other settings
        "RUN_ETL_ON_STARTUP": {"type": "bool", "description": "Run ETL on startup"},
    }

    # Sensitive key patterns that should be masked in UI
    SENSITIVE_KEY_PATTERNS = [
        "SECRET_KEY",
        "PASSWORD",
        "TOKEN",
        "KEY",
        "SECRET",
        "API_KEY",
        "PRIVATE",
        "DB_PASSWORD",
        "DATABASE_URL",
        "SMTP_PASSWORD",
        "SENDGRID_API_KEY",
        "NVIDIA_API_KEY",
    ]

    @staticmethod
    def is_sensitive_key(key: str) -> bool:
        """Check if a config key is sensitive and should be masked."""
        key_upper = key.upper()
        for pattern in SystemConfigService.SENSITIVE_KEY_PATTERNS:
            if pattern in key_upper:
                return True
        return False

    @staticmethod
    def validate_key(key: str) -> None:
        """Validate that a key is in the allowlist."""
        if key not in SystemConfigService.ALLOWED_KEYS:
            raise ValueError(f"Configuration key '{key}' is not allowed. Only predefined keys can be overridden.")

    @staticmethod
    def validate_value(key: str, value: str) -> bool:
        """Validate a value for a given key. Returns True if valid, raises ValueError if invalid."""
        if key not in SystemConfigService.ALLOWED_KEYS:
            raise ValueError(f"Unknown configuration key: {key}")
        
        key_info = SystemConfigService.ALLOWED_KEYS[key]
        value_type = key_info["type"]
        
        if value_type == "bool":
            if value.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                raise ValueError(f"Key '{key}' requires a boolean value (true/false)")
        elif value_type == "int":
            try:
                int_val = int(value)
                if "min" in key_info and int_val < key_info["min"]:
                    raise ValueError(f"Key '{key}' value must be >= {key_info['min']}")
                if "max" in key_info and int_val > key_info["max"]:
                    raise ValueError(f"Key '{key}' value must be <= {key_info['max']}")
            except ValueError as e:
                if "must be" in str(e):
                    raise
                raise ValueError(f"Key '{key}' requires an integer value")
        elif value_type == "float":
            try:
                float_val = float(value)
                if "min" in key_info and float_val < key_info["min"]:
                    raise ValueError(f"Key '{key}' value must be >= {key_info['min']}")
                if "max" in key_info and float_val > key_info["max"]:
                    raise ValueError(f"Key '{key}' value must be <= {key_info['max']}")
            except ValueError as e:
                if "must be" in str(e):
                    raise
                raise ValueError(f"Key '{key}' requires a numeric value")
        return True

    @staticmethod
    def get_all() -> list[dict]:
        """Get all overrides as a list of dictionaries."""
        overrides = SystemConfigRepository.get_all()
        # ADM-012/ADM-027: compute sensitivity at READ time so pattern changes
        # apply to existing rows without a re-save or backfill migration.
        for override in overrides:
            override["is_sensitive"] = SystemConfigService.is_sensitive_key(override.get("key", ""))
            override["display_value"] = "********" if override["is_sensitive"] else override["value"]
        return overrides

    @staticmethod
    def get_by_key(key: str) -> dict | None:
        """Get an override by key as a dictionary."""
        override = SystemConfigRepository.get_by_key(key)
        if override:
            override["is_sensitive"] = SystemConfigService.is_sensitive_key(override.get("key", ""))
            override["display_value"] = "********" if override["is_sensitive"] else override["value"]
        return override

    @staticmethod
    def set_override(key: str, value: str, description: str | None = None) -> None:
        """Set an override for the current user."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        SystemConfigRepository.set_override(
            key=key,
            value=value,
            description=description,
            updated_by=current_user.id
        )

    @staticmethod
    def delete_override(key: str) -> None:
        """Delete an override."""
        if not current_user.is_authenticated:
            raise ValueError("Authentication required")
        SystemConfigRepository.delete_override(key)