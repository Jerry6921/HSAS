"""Safe Git-based updater for HSAS."""

from .service import UpdateError, UpdateResult, update_installation

__all__ = ["UpdateError", "UpdateResult", "update_installation"]
