from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Header

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.services.auth_service import (
    AuthAlreadyInitializedError,
    AuthInvalidCredentialsError,
    AuthSessionInvalidError,
)


class AuthCredentialsRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)


class AuthLogoutRequest(BaseModel):
    sessionToken: str | None = Field(default=None, max_length=512)


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/auth/bootstrap")
    def bootstrap(request: AuthCredentialsRequest):
        try:
            result = services.auth_service_factory().bootstrap(
                username=request.username,
                password=request.password,
            )
        except AuthAlreadyInitializedError as exc:
            return helpers.error(
                status_code=409,
                code=exc.code,
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="auth_invalid_request",
                message=str(exc),
                user_action_required=True,
            )
        return helpers.success({"session": result.to_dict(include_token=True)})

    @router.post("/api/v1/auth/login")
    def login(request: AuthCredentialsRequest):
        try:
            result = services.auth_service_factory().login(
                username=request.username,
                password=request.password,
            )
        except AuthInvalidCredentialsError as exc:
            return helpers.error(
                status_code=401,
                code=exc.code,
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(
                status_code=400,
                code="auth_invalid_request",
                message=str(exc),
                user_action_required=True,
            )
        return helpers.success({"session": result.to_dict(include_token=True)})

    @router.post("/api/v1/auth/logout")
    def logout(request: AuthLogoutRequest, x_newsroom_session: str | None = Header(default=None)):
        token = request.sessionToken or x_newsroom_session
        revoked = services.auth_service_factory().logout(token)
        return helpers.success({"revoked": revoked})

    @router.get("/api/v1/auth/session")
    def session(x_newsroom_session: str | None = Header(default=None)):
        auth_service = services.auth_service_factory()
        if not x_newsroom_session:
            return helpers.success({"initialized": auth_service.is_initialized(), "session": None})
        try:
            result = auth_service.get_session(x_newsroom_session)
        except AuthSessionInvalidError:
            return helpers.success({"initialized": auth_service.is_initialized(), "session": None})
        return helpers.success({"initialized": True, "session": result.to_dict()})

    return router
