"""Auth HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from auth.deps import get_current_user, get_product, require_csrf
from auth.service import (
    AuthError,
    Product,
    User,
    change_password,
    disable_totp,
    enable_totp,
    login,
    logout,
    register,
    request_password_reset,
    reset_password,
    start_totp_setup,
    verify_email,
)
from auth.sessions import COOKIE_NAME, cookie_max_age, cookie_secure, session_idle_minutes

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
    code: str = ""


class VerifyBody(BaseModel):
    token: str


class TotpBody(BaseModel):
    password: str
    code: str


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


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
        "idle_limit_minutes": session_idle_minutes(),
        "totp_enabled": user.totp_enabled,
    }


@router.post("/register", status_code=201)
def post_register(
    body: RegisterBody, product: Product = Depends(get_product), _: None = Depends(require_csrf)
) -> dict:
    try:
        user = register(
            product,
            body.username,
            body.email,
            body.first_name,
            body.last_name,
            body.password,
            body.tos_accepted,
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
def post_login(
    body: LoginBody,
    request: Request,
    response: Response,
    product: Product = Depends(get_product),
    _: None = Depends(require_csrf),
) -> dict:
    try:
        user, token = login(product, body.email, body.password, body.code, *_client(request))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _set_cookie(response, token)
    return _user_json(user)


@router.post("/totp/setup")
def post_totp_setup(
    product: Product = Depends(get_product),
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf),
) -> dict:
    try:
        return start_totp_setup(product, user)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/totp/enable")
def post_totp_enable(
    body: TotpBody, request: Request, user: User = Depends(get_current_user), _: None = Depends(require_csrf)
) -> dict:
    try:
        return {"recovery_codes": enable_totp(user.id, body.password, body.code, _client(request)[0])}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/totp/disable", status_code=204, response_model=None)
def post_totp_disable(
    body: TotpBody, request: Request, user: User = Depends(get_current_user), _: None = Depends(require_csrf)
) -> None:
    try:
        disable_totp(user.id, body.password, body.code, _client(request)[0])
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/password/forgot", status_code=202)
def post_password_forgot(
    body: ForgotBody,
    background: BackgroundTasks,
    product: Product = Depends(get_product),
    _: None = Depends(require_csrf),
) -> dict:
    background.add_task(request_password_reset, product, body.email)
    return {"sent": True}


@router.post("/password/reset", status_code=204, response_model=None)
def post_password_reset(body: ResetBody, request: Request, _: None = Depends(require_csrf)) -> None:
    try:
        reset_password(body.token, body.password, _client(request)[0])
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


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


@router.post("/password", status_code=204, response_model=None)
def post_password(
    body: PasswordBody,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    _: None = Depends(require_csrf),
) -> None:
    try:
        change_password(user.id, body.current_password, body.new_password, _client(request)[0])
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    _clear_cookie(response)
