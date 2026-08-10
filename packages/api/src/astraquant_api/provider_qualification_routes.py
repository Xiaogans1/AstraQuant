"""Authenticated single-writer routes for provider qualification."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from fastapi.params import Depends

from astraquant_api.capture_repository import QualificationConflictError
from astraquant_api.provider_qualification_schemas import (
    ProviderApprovalCommand,
    ProviderRevocationCommand,
    QualificationCommandResponse,
    QualificationReportCommand,
)
from astraquant_api.provider_qualification_service import (
    ProviderQualificationService,
    QualificationNotFoundError,
)
from astraquant_data.provider_qualification import QualificationError


def _execute[CommandT](
    command: CommandT,
    operation: Callable[[CommandT], QualificationCommandResponse],
) -> QualificationCommandResponse:
    try:
        return operation(command)
    except QualificationNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except QualificationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (QualificationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def build_provider_qualification_router(
    service: ProviderQualificationService,
    authenticated: Depends,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/provider-qualifications",
        dependencies=[authenticated],
    )

    @router.post("/reports", response_model=QualificationCommandResponse)
    def submit_report(
        command: QualificationReportCommand,
    ) -> QualificationCommandResponse:
        return _execute(command, service.submit_report)

    @router.post("/approvals", response_model=QualificationCommandResponse)
    def approve(command: ProviderApprovalCommand) -> QualificationCommandResponse:
        return _execute(command, service.approve)

    @router.post("/revocations", response_model=QualificationCommandResponse)
    def revoke(command: ProviderRevocationCommand) -> QualificationCommandResponse:
        return _execute(command, service.revoke)

    return router
