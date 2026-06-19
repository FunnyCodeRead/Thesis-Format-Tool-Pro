from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings


EmailState = Literal[
    "available",
    "pending_confirmation",
    "registered",
]


@dataclass
class SupabaseRegistrationError(Exception):
    status_code: int
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


class SupabaseRegistrationGateway:
    def __init__(self) -> None:
        self._base_url = settings.supabase_url.rstrip("/")

        self._anon_key = (
            settings.supabase_anon_key.get_secret_value()
        )

        service_key = settings.supabase_service_role_key

        self._service_key = (
            service_key.get_secret_value()
            if hasattr(service_key, "get_secret_value")
            else service_key
        )

        self._timeout = httpx.Timeout(
            timeout=12,
            connect=5,
        )

    async def get_email_state(
        self,
        email: str,
    ) -> EmailState:
        url = (
            f"{self._base_url}/rest/v1/rpc/"
            "auth_registration_email_state"
        )

        headers = {
            "apikey": self._service_key,
            "Authorization": (
                f"Bearer {self._service_key}"
            ),
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={"input_email": email},
                )
        except httpx.HTTPError as exc:
            raise SupabaseRegistrationError(
                status_code=503,
                code="SUPABASE_UNAVAILABLE",
                message=(
                    "Không thể kết nối hệ thống tài khoản."
                ),
            ) from exc

        if not response.is_success:
            raise self._create_error(response)

        state = response.json()

        if state not in {
            "available",
            "pending_confirmation",
            "registered",
        }:
            raise SupabaseRegistrationError(
                status_code=502,
                code="INVALID_EMAIL_STATE",
                message=(
                    "Hệ thống trả về trạng thái email "
                    "không hợp lệ."
                ),
            )

        return state

    async def sign_up(
        self,
        *,
        email: str,
        password: str,
        captcha_token: str,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/auth/v1/signup"

        headers = {
            "apikey": self._anon_key,
            "Authorization": f"Bearer {self._anon_key}",
            "Content-Type": "application/json",
            "X-Client-Info": (
                "thesis-format-tool-fastapi"
            ),
        }

        body = {
            "email": email,
            "password": password,
            "data": {},
            "gotrue_meta_security": {
                "captcha_token": captcha_token
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout
            ) as client:
                response = await client.post(
                    url,
                    params={
                        "redirect_to": (
                            settings
                            .frontend_auth_callback_url
                        )
                    },
                    headers=headers,
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise SupabaseRegistrationError(
                status_code=503,
                code="SUPABASE_UNAVAILABLE",
                message=(
                    "Không thể kết nối hệ thống tài khoản."
                ),
            ) from exc

        if not response.is_success:
            raise self._create_error(response)

        payload = self._read_payload(response)

        if not isinstance(payload, dict):
            raise SupabaseRegistrationError(
                status_code=502,
                code="INVALID_SIGNUP_RESPONSE",
                message=(
                    "Hệ thống tài khoản trả về dữ liệu "
                    "không hợp lệ."
                ),
            )

        return payload

    @staticmethod
    def _read_payload(
        response: httpx.Response,
    ) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _create_error(
        self,
        response: httpx.Response,
    ) -> SupabaseRegistrationError:
        payload = self._read_payload(response)

        if not isinstance(payload, dict):
            return SupabaseRegistrationError(
                status_code=response.status_code,
                code="SUPABASE_REQUEST_FAILED",
                message="Không thể xử lý đăng ký.",
            )

        code = str(
            payload.get("code")
            or payload.get("error_code")
            or "SUPABASE_REQUEST_FAILED"
        )

        message = str(
            payload.get("message")
            or payload.get("msg")
            or payload.get("error_description")
            or "Không thể xử lý đăng ký."
        )

        return SupabaseRegistrationError(
            status_code=response.status_code,
            code=code,
            message=message,
        )