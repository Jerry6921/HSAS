"""User and AI-facing information-query adapters."""

from .manage_information import information_app
from .manage_changes import changes_app
from .query_materials import materials_app

__all__ = ["changes_app", "information_app", "materials_app"]
