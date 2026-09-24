"""Data export hub routes."""
from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.security import write_roles_required
from app.services import ExportService

admin_export_bp = Blueprint("admin_export", __name__, url_prefix="/admin/export")


@admin_export_bp.route("/")
@login_required
@write_roles_required
def index():
    """Data export hub."""
    return render_template("admin/export/index.html", active_page="export")


@admin_export_bp.route("/products")
@login_required
@write_roles_required
def export_products():
    """Export products to CSV."""
    try:
        return ExportService.export_products()
    except Exception as e:
        flash(f"Error exporting products: {str(e)}", "error")
        return redirect(url_for("admin_export.index"))


@admin_export_bp.route("/inventory")
@login_required
@write_roles_required
def export_inventory():
    """Export inventory to CSV."""
    try:
        return ExportService.export_inventory()
    except Exception as e:
        flash(f"Error exporting inventory: {str(e)}", "error")
        return redirect(url_for("admin_export.index"))


@admin_export_bp.route("/movements")
@login_required
@write_roles_required
def export_movements():
    """Export movements to CSV."""
    try:
        return ExportService.export_movements()
    except Exception as e:
        flash(f"Error exporting movements: {str(e)}", "error")
        return redirect(url_for("admin_export.index"))


@admin_export_bp.route("/suppliers")
@login_required
@write_roles_required
def export_suppliers():
    """Export suppliers to CSV."""
    try:
        return ExportService.export_suppliers()
    except Exception as e:
        flash(f"Error exporting suppliers: {str(e)}", "error")
        return redirect(url_for("admin_export.index"))


@admin_export_bp.route("/purchase_orders")
@login_required
@write_roles_required
def export_purchase_orders():
    """Export purchase orders to CSV."""
    try:
        return ExportService.export_purchase_orders()
    except Exception as e:
        flash(f"Error exporting purchase orders: {str(e)}", "error")
        return redirect(url_for("admin_export.index"))