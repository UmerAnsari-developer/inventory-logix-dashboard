"""Route blueprints."""
from .auth import auth_bp
from .ui import ui_bp
from .api import api_bp
from .ai import ai_bp

__all__ = ["auth_bp", "ui_bp", "api_bp", "ai_bp"]
