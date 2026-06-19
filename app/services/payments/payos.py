from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from typing import Any, Mapping

import requests

from app.core.config import settings


class PayOSError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class PayOSClient:
    def __init__(self) -> None:
        missing = [
            name
            for name, value in [
                ("PAYOS_CLIENT_ID", settings.payos_client_id),
                ("PAYOS_API_KEY", settings.payos_api_key),
                ("PAYOS_CHECKSUM_KEY", settings.payos_checksum_key),
            ]
            if not value
        ]
        if missing:
            raise PayOSError(f"Missing payOS configuration: {', '.join(missing)}", status_code=500)

        self._base_url = settings.payos_api_base_url.rstrip("/")
        self._checksum_key = settings.payos_checksum_key
        self._session = requests.Session()
        self._headers = {
            "Content-Type": "application/json",
            "x-client-id": settings.payos_client_id,
            "x-api-key": settings.payos_api_key,
        }

    def create_payment_link(
        self,
        *,
        order_code: int,
        amount: int,
        description: str,
        return_url: str,
        cancel_url: str,
        buyer_email: str | None = None,
        expired_at: int | None = None,
    ) -> dict[str, Any]:
        signature_fields = {
            "amount": amount,
            "cancelUrl": cancel_url,
            "description": description,
            "orderCode": order_code,
            "returnUrl": return_url,
        }
        payload: dict[str, Any] = {
            **signature_fields,
            "signature": self.create_signature(signature_fields),
        }
        if buyer_email:
            payload["buyerEmail"] = buyer_email
        if expired_at is not None:
            payload["expiredAt"] = expired_at

        body = self._request_json(
            "POST",
            "/v2/payment-requests",
            json=payload,
            operation="create payment link",
        )
        if body.get("code") != "00":
            raise PayOSError(
                f"payOS create payment link failed: {body.get('code')} {body.get('desc')}",
                status_code=502,
            )
        data = body.get("data")
        if not isinstance(data, dict) or not data.get("checkoutUrl"):
            raise PayOSError("payOS response did not include checkoutUrl.", status_code=502)
        return body

    def get_payment_link_information(self, order_code: str | int) -> dict[str, Any]:
        body = self._request_json(
            "GET",
            f"/v2/payment-requests/{order_code}",
            operation="get payment link information",
        )
        if body.get("code") != "00":
            raise PayOSError(
                f"payOS get payment link information failed: "
                f"{body.get('code')} {body.get('desc')}",
                status_code=502,
            )
        data = body.get("data")
        if not isinstance(data, dict):
            raise PayOSError("payOS response did not include payment data.", status_code=502)
        return body

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        operation: str,
    ) -> dict[str, Any]:
        try:
            response = self._session.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                headers=self._headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise PayOSError(f"payOS {operation} request failed: {exc}", status_code=502) from exc

        if not response.ok:
            raise PayOSError(
                f"payOS {operation} failed: {response.status_code} {response.text}",
                status_code=502,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise PayOSError(
                f"payOS {operation} returned invalid JSON.",
                status_code=502,
            ) from exc
        if not isinstance(body, dict):
            raise PayOSError(
                f"payOS {operation} returned an invalid response.",
                status_code=502,
            )
        return body

    def create_signature(self, data: Mapping[str, Any]) -> str:
        signed_content = "&".join(
            f"{key}={_stringify_signature_value(data[key])}"
            for key in sorted(data.keys())
        )
        return hmac.new(
            self._checksum_key.encode("utf-8"),
            signed_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify_webhook_signature(self, payload: Mapping[str, Any]) -> bool:
        signature = payload.get("signature")
        data = payload.get("data")
        if not signature or not isinstance(data, Mapping):
            return False
        expected_signature = self.create_signature(data)
        return hmac.compare_digest(str(signature), expected_signature)


def _stringify_signature_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@lru_cache(maxsize=1)
def get_payos_client() -> PayOSClient:
    return PayOSClient()
