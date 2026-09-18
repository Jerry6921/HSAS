"""Backward-compatible imports for the relocated CORE and UI modules."""

from hsas.core import HIQSPortError as DashboardError
from hsas.core.implement_port import HIQSCore as DashboardService
from hsas.ui.run_dashboard import (
    ASSET_ROOT,
    DashboardRequestHandler,
    DashboardServer,
    _load_dashboard_assets,
    build_dashboard_server,
    serve_dashboard,
)

__all__ = [
    "ASSET_ROOT",
    "DashboardError",
    "DashboardRequestHandler",
    "DashboardServer",
    "DashboardService",
    "_load_dashboard_assets",
    "build_dashboard_server",
    "serve_dashboard",
]
