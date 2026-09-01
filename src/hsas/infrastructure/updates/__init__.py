"""Safe Git-based update infrastructure."""

from .update_installation import UpdateError, UpdateResult, update_installation

__all__ = ["UpdateError", "UpdateResult", "update_installation"]
