"""AI feature routes — EOQ sensitivity surface."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import login_required

from ..utils import api_error, api_response

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")


@ai_bp.route("/eoq/sensitivity")
@login_required
def eoq_sensitivity():
    payload = request.args
    try:
        demand = float(payload.get("demand") or 0)
        ordering = float(payload.get("ordering_cost") or 0)
        holding = float(payload.get("holding_cost") or 0)
    except ValueError:
        return api_error("INVALID_INPUT", "Provide numeric demand, ordering_cost, holding_cost.",
                         status=422)
    from ..services import EOQService
    return api_response(EOQService.sensitivity_surface(demand, ordering, holding))
