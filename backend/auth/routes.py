"""Auth HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from auth.deps import get_current_user, require_csrf
from auth.service import AuthError, User, login, logout, register, verify_email
from auth.sessions import COOKIE_NAME, cookie_max_age, cookie_secure

router = APIRouter()


class RegisterBody(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str
    password: str
    tos_accepted: bool


class LoginBody(BaseModel):
    email: str
    password: str


class VerifyBody(BaseModel):
    token: str


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=cookie_max_age(),
        secure=cookie_secure(),
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


def _user_json(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "status": user.status,
        "last_signed_in_ts": user.last_signed_in_ts.isoformat() if user.last_signed_in_ts else None,
        "subscription_status": user.subscription_status,
        "registered_product": user.registered_product,
        "features": list(user.features),
    }


@router.post("/register", status_code=201)
def post_register(body: RegisterBody, request: Request, _: None = Depends(require_csrf)) -> dict:
    try:
        user = register(
            body.username,
            body.email,
            body.first_name,
            body.last_name,
            body.password,
            body.tos_accepted,
            *_client(request),
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return _user_json(user)


@router.post("/verify")
def post_verify(body: VerifyBody, _: None = Depends(require_csrf)) -> dict:
    try:
        verify_email(body.token)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    return {"verified": True}


@router.post("/login")
def post_login(body: LoginBody, request: Request, response: Response, _: None = Depends(require_csrf)) -> dict:
    try:
        user, token = login(body.email, body.password, *_client(request))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _set_cookie(response, token)
    return _user_json(user)


@router.post("/logout", status_code=204, response_model=None)
def post_logout(request: Request, response: Response, _: None = Depends(require_csrf)) -> None:
    try:
        logout(request.cookies.get(COOKIE_NAME))
    except RuntimeError:
        pass
    _clear_cookie(response)


@router.get("/me")
def get_me(user: User = Depends(get_current_user)) -> dict:
    return _user_json(user)
