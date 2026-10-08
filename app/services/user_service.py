"""User service — organizational hierarchy safeguards.

Reporting Manager is an ORGANIZATIONAL relationship (visibility into
subordinate submissions), separate from RBAC permissions. Only admins
may modify reporting relationships; cycles and self-reference rejected.
"""
from __future__ import annotations

import logging

from ..repositories.user_repo import UserRepository

LOGGER = logging.getLogger(__name__)


class UserService:

    @staticmethod
    def set_reporting_manager(user_id: int, manager_id: int, actor) -> None:
        """Assign a reporting manager with hierarchy safeguards.

        Rules (spec §8):
        1. A user cannot report to themselves.
        2. Circular hierarchy (A→B→C→A) is rejected.
        3. The manager must be an active user.
        4. Only authorized users (admin route) may modify relationships.
        """
        if user_id == manager_id:
            raise ValueError("A user cannot report to themselves.")

        manager = UserRepository.find_by_id(manager_id)
        if manager is None:
            raise ValueError("Reporting manager not found.")
        if not manager.is_active:
            raise ValueError("Reporting manager must be an active user.")

        # Cycle detection: walk up the chain from the proposed manager;
        # if it reaches the user, the assignment would create a loop.
        chain = UserRepository.manager_chain(manager_id)
        if user_id in chain:
            raise ValueError(
                "Invalid reporting relationship: this assignment would create "
                "a circular hierarchy."
            )

        UserRepository.set_reporting_manager(user_id, manager_id)
        LOGGER.info(
            "Reporting manager set: user %s -> manager %s (by %s)",
            user_id, manager_id, getattr(actor, "id", None),
        )