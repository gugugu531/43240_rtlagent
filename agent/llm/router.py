"""Compatibility import for the single role map in `agent.roles`."""

from agent.roles import ROLE_PROFILES, profile_for_stage, role_for_stage

__all__ = ["ROLE_PROFILES", "profile_for_stage", "role_for_stage"]
