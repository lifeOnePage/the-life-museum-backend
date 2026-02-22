from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.schemas.auth import (
    Token,
    LoginRequest,
    PhoneVerificationRequest,
    PhoneVerificationConfirm,
    RefreshTokenRequest,
    AuthResponse,
    AuthUserInfo,
    EmailVerificationRequest,
    EmailVerificationConfirm,
    CompleteSignupRequest,
)
from app.schemas.user import UserCreate, UserResponse
from app.schemas.common import ApiResponse, success_response
from app.services.auth import AuthService
from app.services.sms import get_sms_service
from app.services.email import get_email_service
from app.services.oauth import GoogleOAuth, KakaoOAuth
from app.models.user import User, OAuthAccount, OAuthProvider
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.exceptions import BadRequestException, UnauthorizedException
from app.api.deps import get_current_user

router = APIRouter()


def _build_auth_response(user: User, is_new_user: bool) -> AuthResponse:
    return AuthResponse(
        accessToken=create_access_token(user.id),
        refreshToken=create_refresh_token(user.id),
        isNewUser=is_new_user,
        user=AuthUserInfo(
            id=user.id,
            name=user.name,
            phone=user.phone,
            email=user.email,
        ),
    )


@router.post("/register")
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    auth_service = AuthService(db)
    user = await auth_service.create_user(user_data)
    return success_response(UserResponse.model_validate(user))


@router.post("/login")
async def login(login_data: LoginRequest, db: AsyncSession = Depends(get_db)):
    auth_service = AuthService(db)
    user = await auth_service.authenticate(
        email=login_data.email,
        phone=login_data.phone,
        password=login_data.password,
    )
    if not user:
        raise UnauthorizedException("Invalid credentials")

    token = Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
    return success_response(token)


@router.post("/refresh")
async def refresh_token(data: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise UnauthorizedException("Invalid refresh token")

    user_id = payload.get("sub")
    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if not user or not user.is_active:
        raise UnauthorizedException("User not found or inactive")

    token = Token(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
    return success_response(token)


# Phone verification endpoints
@router.post("/phone/send-code")
async def send_phone_verification(
    data: PhoneVerificationRequest, db: AsyncSession = Depends(get_db)
):
    sms_service = get_sms_service()
    auth_service = AuthService(db)

    code = sms_service.generate_verification_code()
    await auth_service.create_phone_verification(data.phone, code)
    await sms_service.send_verification_code(data.phone, code)

    return success_response(message="Verification code sent")


@router.post("/phone/verify")
async def verify_phone(
    data: PhoneVerificationConfirm, db: AsyncSession = Depends(get_db)
):
    auth_service = AuthService(db)
    await auth_service.verify_phone_code(data.phone, data.code)
    user, is_new_user = await auth_service.get_or_create_user_by_phone(data.phone)
    return success_response(_build_auth_response(user, is_new_user))


# Email verification endpoints
@router.post("/email/send-code")
async def send_email_verification(
    data: EmailVerificationRequest, db: AsyncSession = Depends(get_db)
):
    email_service = get_email_service()
    auth_service = AuthService(db)

    code = email_service.generate_verification_code()
    await auth_service.create_email_verification(data.email, code)
    await email_service.send_verification_code(data.email, code)

    return success_response(message="Verification code sent")


@router.post("/email/verify")
async def verify_email(
    data: EmailVerificationConfirm, db: AsyncSession = Depends(get_db)
):
    auth_service = AuthService(db)
    await auth_service.verify_email_code(data.email, data.code)
    user, is_new_user = await auth_service.get_or_create_user_by_email(data.email)
    return success_response(_build_auth_response(user, is_new_user))


@router.post("/complete-signup")
async def complete_signup(
    data: CompleteSignupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    auth_service = AuthService(db)
    user = await auth_service.complete_signup(current_user.id, data.name)
    return success_response(
        AuthUserInfo(
            id=user.id,
            name=user.name,
            phone=user.phone,
            email=user.email,
        )
    )


# Google OAuth endpoints
@router.get("/google/login")
async def google_login():
    oauth = GoogleOAuth()
    auth_url = oauth.get_authorization_url()
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_db)):
    oauth = GoogleOAuth()

    try:
        token_data = await oauth.get_access_token(code)
        user_info = await oauth.get_user_info(token_data["access_token"])
    except Exception as e:
        raise BadRequestException(f"OAuth failed: {str(e)}")

    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == OAuthProvider.GOOGLE,
            OAuthAccount.provider_user_id == user_info.id,
        )
    )
    oauth_account = result.scalar_one_or_none()

    if oauth_account:
        user = oauth_account.user
        is_new_user = False
    else:
        auth_service = AuthService(db)
        user = await auth_service.get_user_by_email(user_info.email)
        is_new_user = user is None

        if not user:
            user = User(
                email=user_info.email,
                name=user_info.name,
                profile_image=user_info.picture,
                is_verified=True,
            )
            db.add(user)
            await db.flush()

        oauth_account = OAuthAccount(
            user_id=user.id,
            provider=OAuthProvider.GOOGLE,
            provider_user_id=user_info.id,
            access_token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
        )
        db.add(oauth_account)
        await db.commit()

    return success_response(_build_auth_response(user, is_new_user))


# Kakao OAuth endpoints
@router.get("/kakao/login")
async def kakao_login():
    oauth = KakaoOAuth()
    auth_url = oauth.get_authorization_url()
    return RedirectResponse(url=auth_url)


@router.get("/kakao/callback")
async def kakao_callback(code: str, db: AsyncSession = Depends(get_db)):
    oauth = KakaoOAuth()

    try:
        token_data = await oauth.get_access_token(code)
        user_info = await oauth.get_user_info(token_data["access_token"])
    except Exception as e:
        raise BadRequestException(f"OAuth failed: {str(e)}")

    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == OAuthProvider.KAKAO,
            OAuthAccount.provider_user_id == user_info.id,
        )
    )
    oauth_account = result.scalar_one_or_none()

    if oauth_account:
        user = oauth_account.user
        is_new_user = False
    else:
        user = None
        is_new_user = True

        if user_info.email:
            auth_service = AuthService(db)
            user = await auth_service.get_user_by_email(user_info.email)
            if user:
                is_new_user = False

        if not user:
            user = User(
                email=user_info.email,
                name=user_info.nickname,
                profile_image=user_info.profile_image,
                is_verified=True,
            )
            db.add(user)
            await db.flush()

        oauth_account = OAuthAccount(
            user_id=user.id,
            provider=OAuthProvider.KAKAO,
            provider_user_id=user_info.id,
            access_token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
        )
        db.add(oauth_account)
        await db.commit()

    return success_response(_build_auth_response(user, is_new_user))
