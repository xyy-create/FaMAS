from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.core.validation import validate_password_strength, validate_username
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse
from app.schemas.user import UserProfile
from app.services.login_rate_limit import (
    LoginRateLimitExceeded,
    assert_login_allowed,
    login_rate_limit_key,
    record_failed_login,
    reset_login_attempts,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    client_host = request.client.host if request.client else "unknown"
    rate_limit_key = login_rate_limit_key(payload.username, client_host)
    try:
        assert_login_allowed(
            rate_limit_key,
            max_attempts=settings.login_rate_limit_max_attempts,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
    except LoginRateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        ) from exc

    statement = select(User).where(User.username == payload.username)
    user = db.scalar(statement)
    if user is None or not verify_password(payload.password, user.password_hash):
        record_failed_login(
            rate_limit_key,
            window_seconds=settings.login_rate_limit_window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if user.approval_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is pending admin approval.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    reset_login_attempts(rate_limit_key)
    expires_in_seconds = settings.access_token_expire_minutes * 60
    token = create_access_token(
        str(user.id),
        secret_key=settings.secret_key,
        expires_in_seconds=expires_in_seconds,
        token_version=user.token_version,
    )
    _set_auth_cookie(response, token, expires_in_seconds)
    return TokenResponse(access_token=token, expires_in=expires_in_seconds)


@router.post("/register", response_model=RegisterResponse)
def register(
    payload: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    username = payload.username.strip()
    username_error = validate_username(username)
    if username_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=username_error,
        )
    password_error = validate_password_strength(payload.password)
    if password_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error,
        )

    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already registered.",
        )

    requires_approval = settings.registration_mode == "approval"
    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        role="user",
        is_active=not requires_approval,
        approval_status="pending" if requires_approval else "approved",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if requires_approval:
        return RegisterResponse(
            status="pending",
            message="Account created and pending admin approval.",
        )

    expires_in_seconds = settings.access_token_expire_minutes * 60
    token = create_access_token(
        str(user.id),
        secret_key=settings.secret_key,
        expires_in_seconds=expires_in_seconds,
        token_version=user.token_version,
    )
    _set_auth_cookie(response, token, expires_in_seconds)
    return RegisterResponse(
        status="active",
        access_token=token,
        expires_in=expires_in_seconds,
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
    )
    return {"message": "Logged out."}


@router.get("/me", response_model=UserProfile)
def current_user(user: User = Depends(get_current_user)) -> UserProfile:
    return UserProfile(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        approval_status=user.approval_status,
    )


def _set_auth_cookie(response: Response, token: str, expires_in_seconds: int) -> None:
    secure_cookie = settings.runtime_mode in {"public", "production"} or settings.public_url.startswith("https://")
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=expires_in_seconds,
        httponly=True,
        samesite="lax",
        secure=secure_cookie,
        path="/",
    )
