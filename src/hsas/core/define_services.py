"""Composition boundary for HIQSCore's application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CoreServices:
    """Named service graph owned by the CORE facade.

    Delivery adapters depend on the facade/port; this registry keeps wiring out
    of individual endpoint methods and makes the remaining migration explicit.
    """

    records: Any
    reviews: Any
    inbox: Any
    materials: Any
    dashboard: Any
    sync: Any
    attention: Any
    information: Any
    status: Any
