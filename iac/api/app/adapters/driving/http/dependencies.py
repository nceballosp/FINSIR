"""FastAPI dependency providers resolving use cases from the container.

These providers read the wired use cases off ``app.state``. Tests override them
(or swap the repository on the container) to inject a fake repository with no
AWS calls.
"""

from __future__ import annotations

from fastapi import Request

from app.use_cases.get_client_latest import GetClientLatest
from app.use_cases.get_client_records import GetClientRecords
from app.use_cases.list_month import ListMonth


def get_client_records_use_case(request: Request) -> GetClientRecords:
    """Return the wired :class:`GetClientRecords` use case."""
    return request.app.state.container.get_client_records


def get_client_latest_use_case(request: Request) -> GetClientLatest:
    """Return the wired :class:`GetClientLatest` use case."""
    return request.app.state.container.get_client_latest


def list_month_use_case(request: Request) -> ListMonth:
    """Return the wired :class:`ListMonth` use case."""
    return request.app.state.container.list_month
