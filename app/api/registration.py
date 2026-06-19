from __future__ import annotations

import hashlib
import hmac
import logging
from uuid import uuid4

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)

from app.core.config import settings
from app.schemas.registration import (
    RegisterRequest,
    RegisterResponse,
)
from app.services.auth.registration_guard import (
    RegistrationGuardUnavailable,
    get_registration_guard,
)
from app.services.auth.supabase_registration import (
    SupabaseRegistrationError,
    SupabaseRegistrationGateway,
)


router = APIRouter(
    prefix="/api/v1/auth",
    tags=["auth"],
)

logger = logging.getLogger(__name__)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def register(
    body: RegisterRequest,
    request: Request,
) -> RegisterResponse:
    email = str(body.email).strip().casefold()
    password = body.password.get_secret_value()

    client_ip = (
        request.client.host
        if request.client is not None
        else "unknown"
    )

    request_id = (
        request.headers.get("x-request-id")
        or uuid4().hex
    )

    email_hash = _secure_hash(email)
    ip_hash = _secure_hash(client_ip)

    guard = get_registration_guard()

    try:
        await _enforce_rate_limit(
            key=f"registration:ip:{ip_hash}",
            limit=settings.registration_ip_limit,
            window_seconds=(
                settings.registration_ip_window_seconds
            ),
        )

        await _enforce_rate_limit(
            key=f"registration:email:{email_hash}",
            limit=settings.registration_email_limit,
            window_seconds=(
                settings.registration_email_window_seconds
            ),
        )
    except RegistrationGuardUnavailable as exc:
        raise _registration_security_unavailable() from exc

    gateway = SupabaseRegistrationGateway()

    result = "failed"
    lock_token: str | None = None

    try:
        # Kiểm tra trạng thái email trước khi lấy khóa Redis.
        email_state = await gateway.get_email_state(email)

        # Email đã tồn tại thì trả lỗi đúng trạng thái.
        # Vẫn gọi signup để Supabase xác minh CAPTCHA trước.
        if email_state in {
            "registered",
            "pending_confirmation",
        }:
            result = _duplicate_result(email_state)

            await _verify_captcha_then_reject_existing_email(
                gateway=gateway,
                email_state=email_state,
                email=email,
                password=password,
                captcha_token=body.captcha_token,
            )

        # Chỉ email chưa tồn tại mới cần khóa Redis.
        try:
            lock_token = await guard.acquire_email_lock(
                email_hash=email_hash,
                expires_seconds=(
                    settings.registration_lock_seconds
                ),
            )
        except RegistrationGuardUnavailable as exc:
            raise _registration_security_unavailable() from exc

        if lock_token is None:
            # Có thể request khác vừa tạo tài khoản.
            # Kiểm tra lại để tránh trả thông báo sai.
            latest_email_state = (
                await gateway.get_email_state(email)
            )

            if latest_email_state in {
                "registered",
                "pending_confirmation",
            }:
                result = _duplicate_result(
                    latest_email_state
                )

                await _verify_captcha_then_reject_existing_email(
                    gateway=gateway,
                    email_state=latest_email_state,
                    email=email,
                    password=password,
                    captcha_token=body.captcha_token,
                )

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": "3"},
                detail={
                    "code": "REGISTRATION_IN_PROGRESS",
                    "message": (
                        "Một yêu cầu đăng ký đang được xử lý. "
                        "Vui lòng chờ vài giây rồi thử lại."
                    ),
                },
            )

        # Kiểm tra lại sau khi giữ khóa để chống race condition.
        latest_email_state = (
            await gateway.get_email_state(email)
        )

        if latest_email_state in {
            "registered",
            "pending_confirmation",
        }:
            result = _duplicate_result(
                latest_email_state
            )

            await _verify_captcha_then_reject_existing_email(
                gateway=gateway,
                email_state=latest_email_state,
                email=email,
                password=password,
                captcha_token=body.captcha_token,
            )

        # Email chưa tồn tại thì mới tạo tài khoản.
        await gateway.sign_up(
            email=email,
            password=password,
            captcha_token=body.captcha_token,
        )

        result = "created"

        return RegisterResponse(
            message=(
                "Đăng ký thành công. Vui lòng kiểm tra "
                "email để xác nhận tài khoản."
            ),
            requires_email_confirmation=True,
        )

    except HTTPException:
        raise

    except SupabaseRegistrationError as exc:
        result = f"supabase_error:{exc.code}"
        raise _map_supabase_error(exc) from exc

    finally:
        if lock_token is not None:
            await guard.release_email_lock(
                email_hash=email_hash,
                token=lock_token,
            )

        logger.info(
            (
                "registration_result "
                "request_id=%s result=%s "
                "email_hash=%s ip_hash=%s"
            ),
            request_id,
            result,
            email_hash,
            ip_hash,
        )


def _duplicate_result(email_state: str) -> str:
    if email_state == "pending_confirmation":
        return "duplicate_unconfirmed"

    return "duplicate_confirmed"


def _email_state_error(
    email_state: str,
) -> HTTPException:
    if email_state == "pending_confirmation":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_AWAITING_CONFIRMATION",
                "message": (
                    "Email này đã được đăng ký nhưng "
                    "chưa xác nhận. Vui lòng kiểm tra "
                    "hộp thư hoặc gửi lại email xác nhận."
                ),
            },
        )

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "EMAIL_ALREADY_REGISTERED",
            "message": (
                "Email này đã có tài khoản. "
                "Vui lòng đăng nhập hoặc sử dụng "
                "Quên mật khẩu."
            ),
        },
    )


async def _verify_captcha_then_reject_existing_email(
    *,
    gateway: SupabaseRegistrationGateway,
    email_state: str,
    email: str,
    password: str,
    captcha_token: str,
) -> None:
    try:
        # Supabase xác minh CAPTCHA trước khi backend
        # trả thông tin email đã tồn tại.
        await gateway.sign_up(
            email=email,
            password=password,
            captcha_token=captcha_token,
        )

    except SupabaseRegistrationError as exc:
        code = exc.code.lower()

        if code in {
            "email_exists",
            "user_already_exists",
        }:
            raise _email_state_error(email_state) from exc

        raise _map_supabase_error(exc) from exc

    # Supabase có thể che giấu email trùng và trả thành công.
    # Backend vẫn dựa vào trạng thái đã đọc từ auth.users.
    raise _email_state_error(email_state)


async def _enforce_rate_limit(
    *,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    guard = get_registration_guard()

    result = await guard.consume(
        key=key,
        limit=limit,
        window_seconds=window_seconds,
    )

    if result.allowed:
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={
            "Retry-After": str(result.retry_after),
        },
        detail={
            "code": "REGISTRATION_RATE_LIMITED",
            "message": (
                "Bạn đã gửi quá nhiều yêu cầu đăng ký. "
                "Vui lòng thử lại sau."
            ),
            "retry_after": result.retry_after,
        },
    )


def _registration_security_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "REGISTRATION_SECURITY_UNAVAILABLE",
            "message": (
                "Hệ thống bảo vệ đăng ký đang "
                "tạm thời chưa sẵn sàng."
            ),
        },
    )


def _secure_hash(value: str) -> str:
    secret = (
        settings
        .auth_rate_limit_hmac_secret
        .get_secret_value()
        .encode("utf-8")
    )

    return hmac.new(
        secret,
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _map_supabase_error(
    exc: SupabaseRegistrationError,
) -> HTTPException:
    code = exc.code.lower()

    if code == "captcha_failed":
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CAPTCHA_FAILED",
                "message": (
                    "Xác minh bảo mật không hợp lệ "
                    "hoặc đã hết hạn."
                ),
            },
        )

    if code == "weak_password":
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "WEAK_PASSWORD",
                "message": (
                    "Mật khẩu chưa đáp ứng yêu cầu "
                    "bảo mật."
                ),
            },
        )

    if code in {
        "email_exists",
        "user_already_exists",
    }:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_ALREADY_REGISTERED",
                "message": (
                    "Email này đã có tài khoản. "
                    "Vui lòng đăng nhập hoặc sử dụng "
                    "Quên mật khẩu."
                ),
            },
        )

    if (
        exc.status_code == 429
        or code
        in {
            "over_email_send_rate_limit",
            "over_request_rate_limit",
        }
    ):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "SUPABASE_RATE_LIMITED",
                "message": (
                    "Hệ thống đã gửi quá nhiều email. "
                    "Vui lòng thử lại sau."
                ),
            },
        )

    if code in {
        "supabase_unavailable",
        "request_timeout",
    }:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_SERVICE_UNAVAILABLE",
                "message": (
                    "Hệ thống tài khoản đang tạm thời "
                    "chưa sẵn sàng."
                ),
            },
        )

    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "REGISTRATION_FAILED",
            "message": (
                "Không thể tạo tài khoản vào lúc này."
            ),
        },
    )
