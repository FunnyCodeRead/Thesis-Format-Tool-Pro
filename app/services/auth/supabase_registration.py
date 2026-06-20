from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)

_ALLOWED_EMAIL_STATES = {
    "available",
    "pending_confirmation",
    "registered",
}


class SupabaseRegistrationError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@lru_cache
def get_supabase_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.supabase_url.rstrip("/"),
        timeout=httpx.Timeout(
            connect=4.0,
            read=10.0,
            write=10.0,
            pool=4.0,
        ),
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        ),
        http2=True,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )


class SupabaseRegistrationGateway:
    def __init__(self) -> None:
        self._client = get_supabase_http_client()

    async def get_email_state(
        self,
        email: str,
    ) -> str:
        service_role_key = (
            settings.supabase_service_role_key
        )

        try:
            response = await self._client.post(
                (
                    "/rest/v1/rpc/"
                    "auth_registration_email_state"
                ),
                headers={
                    "apikey": service_role_key,
                    "Authorization": (
                        f"Bearer {service_role_key}"
                    ),
                },
                json={
                    "input_email": email,
                },
            )
        except httpx.TimeoutException as exc:
            raise SupabaseRegistrationError(
                code="request_timeout",
                message=(
                    "Supabase email lookup timed out."
                ),
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise SupabaseRegistrationError(
                code="supabase_unavailable",
                message=(
                    "Cannot connect to Supabase."
                ),
                status_code=503,
            ) from exc

        if not response.is_success:
            raise self._error_from_response(
                response,
                fallback_code=(
                    "email_state_lookup_failed"
                ),
            )

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise SupabaseRegistrationError(
                code="invalid_supabase_response",
                message=(
                    "Supabase returned invalid JSON."
                ),
                status_code=502,
            ) from exc

        if (
            isinstance(payload, str)
            and payload in _ALLOWED_EMAIL_STATES
        ):
            return payload

        raise SupabaseRegistrationError(
            code="invalid_email_state",
            message=(
                "Supabase returned an invalid email state."
            ),
            status_code=502,
        )

    async def sign_up(
        self,
        *,
        email: str,
        password: str,
        captcha_token: str,
    ) -> dict[str, Any]:
        anon_key = (
            settings
            .supabase_anon_key
            .get_secret_value()
        )

        params: dict[str, str] = {}

        if settings.frontend_auth_callback_url:
            params["redirect_to"] = (
                settings.frontend_auth_callback_url
            )

        try:
            response = await self._client.post(
                "/auth/v1/signup",
                params=params,
                headers={
                    "apikey": anon_key,
                    "Authorization": (
                        f"Bearer {anon_key}"
                    ),
                },
                json={
                    "email": email,
                    "password": password,
                    "gotrue_meta_security": {
                        "captcha_token": captcha_token,
                    },
                },
            )
        except httpx.TimeoutException as exc:
            raise SupabaseRegistrationError(
                code="request_timeout",
                message=(
                    "Supabase signup timed out."
                ),
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise SupabaseRegistrationError(
                code="supabase_unavailable",
                message=(
                    "Cannot connect to Supabase."
                ),
                status_code=503,
            ) from exc

        if not response.is_success:
            raise self._error_from_response(
                response,
                fallback_code="signup_failed",
            )

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise SupabaseRegistrationError(
                code="invalid_supabase_response",
                message=(
                    "Supabase returned invalid JSON."
                ),
                status_code=502,
            ) from exc

        if isinstance(payload, dict):
            return payload

        return {}

    @staticmethod
    def _error_from_response(
        response: httpx.Response,
        *,
        fallback_code: str,
    ) -> SupabaseRegistrationError:
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        raw_code = (
            payload.get("code")
            or payload.get("error_code")
            or fallback_code
        )

        raw_message = (
            payload.get("msg")
            or payload.get("message")
            or payload.get("error_description")
            or response.text
            or "Supabase request failed."
        )

        code = str(raw_code).strip().lower()
        message = str(raw_message).strip()
        combined = f"{code} {message}".lower()

        if "captcha" in combined:
            code = "captcha_failed"
        elif (
            "weak_password" in combined
            or "password should be" in combined
            or "password must" in combined
        ):
            code = "weak_password"
        elif (
            "user_already_exists" in combined
            or "email_exists" in combined
            or "already registered" in combined
            or "already exists" in combined
        ):
            code = "user_already_exists"
        elif (
            "over_email_send_rate_limit"
            in combined
        ):
            code = "over_email_send_rate_limit"
        elif (
            "over_request_rate_limit"
            in combined
            or response.status_code == 429
        ):
            code = "over_request_rate_limit"
        elif response.status_code >= 500:
            code = "supabase_unavailable"

        return SupabaseRegistrationError(
            code=code,
            message=message,
            status_code=response.status_code,
        )
