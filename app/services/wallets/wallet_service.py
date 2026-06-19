from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException, status

from app.core.config import settings
from app.db.supabase_client import SupabaseAPIError
from app.schemas.auth import CurrentUser
from app.schemas.wallet import TopupCheckoutResponse, TopupStatusResponse, WalletResponse
from app.services.payments.payos import PayOSError, get_payos_client


WALLET_TOPUP_COLUMNS = (
    "id,user_id,amount,currency,status,payment_provider,provider_order_code,"
    "checkout_url,qr_code,paid_at,expires_at,metadata,created_at,updated_at"
)


def get_or_create_wallet(supabase, user_id: str) -> dict[str, Any]:
    wallet = supabase.select_one(
        "wallets",
        filters={"user_id": user_id},
        columns="user_id,balance_vnd,currency,updated_at",
    )

    if wallet is not None:
        return wallet

    return supabase.insert_one(
        "wallets",
        payload={
            "user_id": user_id,
            "balance_vnd": 0,
            "currency": "VND",
        },
        columns="user_id,balance_vnd,currency,updated_at",
    )


def wallet_response(wallet: dict[str, Any]) -> WalletResponse:
    return WalletResponse(
        user_id=wallet["user_id"],
        balance_vnd=int(wallet.get("balance_vnd") or 0),
        currency=wallet.get("currency") or "VND",
        last_updated_at=wallet.get("updated_at"),
    )


def create_wallet_topup(
    supabase,
    *,
    current_user: CurrentUser,
    amount: int,
    return_to: str | None = None,
) -> TopupCheckoutResponse:
    if amount < 10000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Số tiền nạp tối thiểu là 10,000đ.",
        )

    normalized_return_to = _normalize_return_to(return_to)
    get_or_create_wallet(supabase, current_user.user_id)

    order_code = _generate_order_code()
    provider_order_code = str(order_code)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.payos_link_ttl_minutes
    )

    return_url = _build_topup_return_url(provider_order_code, normalized_return_to)
    cancel_url = _build_topup_cancel_url(provider_order_code, normalized_return_to)
    description = _build_topup_description(provider_order_code)

    topup = supabase.insert_one(
        "wallet_topups",
        payload={
            "user_id": current_user.user_id,
            "amount": amount,
            "currency": "VND",
            "status": "pending",
            "payment_provider": "payos",
            "provider_order_code": provider_order_code,
            "expires_at": expires_at.isoformat(),
            "metadata": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "return_to": normalized_return_to,
                "description": description,
            },
        },
        columns="id,user_id,amount,currency,status,provider_order_code,expires_at",
    )

    try:
        payos_response = get_payos_client().create_payment_link(
            order_code=order_code,
            amount=amount,
            description=description,
            return_url=return_url,
            cancel_url=cancel_url,
            buyer_email=current_user.email,
            expired_at=int(expires_at.timestamp()),
        )
    except PayOSError:
        _mark_topup_failed(
            supabase,
            topup["id"],
            current_user.user_id,
            {"error": "payos_create_payment_link_failed"},
        )
        raise

    payos_data = payos_response["data"]

    updated = supabase.update_one(
        "wallet_topups",
        filters={"id": topup["id"], "user_id": current_user.user_id},
        payload={
            "checkout_url": payos_data["checkoutUrl"],
            "qr_code": payos_data.get("qrCode"),
            "metadata": {
                "return_url": return_url,
                "cancel_url": cancel_url,
                "return_to": normalized_return_to,
                "description": description,
                "payos": payos_data,
            },
        },
        columns=(
            "id,amount,currency,provider_order_code,"
            "checkout_url,qr_code,expires_at"
        ),
    )

    return TopupCheckoutResponse(
        order_id=updated["id"],
        amount=int(updated["amount"]),
        currency=updated["currency"],
        checkout_url=updated["checkout_url"],
        qr_code=updated.get("qr_code"),
        provider_order_code=updated["provider_order_code"],
        expires_at=updated["expires_at"],
    )


def get_wallet_topup_by_provider_order_code(
    supabase,
    provider_order_code: str,
) -> dict[str, Any] | None:
    return supabase.select_one(
        "wallet_topups",
        filters={"provider_order_code": provider_order_code},
        columns=WALLET_TOPUP_COLUMNS,
    )


def get_wallet_topup_status(
    supabase,
    *,
    current_user: CurrentUser,
    provider_order_code: str,
) -> TopupStatusResponse:
    topup = supabase.select_one(
        "wallet_topups",
        filters={
            "user_id": current_user.user_id,
            "provider_order_code": provider_order_code,
        },
        columns=WALLET_TOPUP_COLUMNS,
    )

    if topup is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy giao dịch nạp tiền.",
        )

    topup = _refresh_topup_status_from_payos(supabase, topup)
    wallet = get_or_create_wallet(supabase, current_user.user_id)

    return TopupStatusResponse(
        order_id=topup["id"],
        amount=int(topup["amount"]),
        currency=topup["currency"],
        status=topup["status"],
        provider_order_code=topup["provider_order_code"],
        paid_at=topup.get("paid_at"),
        balance_vnd=int(wallet.get("balance_vnd") or 0),
    )


def credit_wallet_topup(
    supabase,
    *,
    provider_order_code: str,
    paid_at: str,
) -> dict[str, Any]:
    result = supabase.rpc(
        "credit_wallet_topup",
        {
            "p_provider_order_code": provider_order_code,
            "p_paid_at": paid_at,
        },
    )

    if not isinstance(result, dict) or not result.get("ok"):
        raise SupabaseAPIError(
            f"credit_wallet_topup failed: {result}",
            status_code=502,
        )

    return result


def purchase_document_with_wallet(
    supabase,
    *,
    user_id: str,
    document_id: str,
) -> dict[str, Any]:
    result = supabase.rpc(
        "purchase_document_with_wallet",
        {
            "p_user_id": user_id,
            "p_document_id": document_id,
        },
    )

    if not isinstance(result, dict):
        raise SupabaseAPIError(
            f"purchase_document_with_wallet returned invalid result: {result}",
            status_code=502,
        )

    return result


def _refresh_topup_status_from_payos(supabase, topup: dict[str, Any]) -> dict[str, Any]:
    if topup.get("status") != "pending":
        return topup

    if _topup_is_expired(topup):
        return _set_topup_status(supabase, topup, "expired")

    try:
        payos_response = get_payos_client().get_payment_link_information(
            topup["provider_order_code"]
        )
    except PayOSError:
        return topup

    payos_data = payos_response.get("data") or {}
    provider_order_code = str(payos_data.get("orderCode") or "")
    if provider_order_code and provider_order_code != str(topup["provider_order_code"]):
        return topup

    provider_status = str(payos_data.get("status") or "").upper()
    if provider_status == "PAID":
        provider_amount = int(payos_data.get("amount") or 0)
        amount_paid = int(payos_data.get("amountPaid") or provider_amount)
        expected_amount = int(topup["amount"])
        if provider_amount != expected_amount or amount_paid < expected_amount:
            raise SupabaseAPIError(
                "payOS topup status amount does not match wallet topup.",
                status_code=502,
            )

        credit_wallet_topup(
            supabase,
            provider_order_code=topup["provider_order_code"],
            paid_at=datetime.now(timezone.utc).isoformat(),
        )
        refreshed = get_wallet_topup_by_provider_order_code(
            supabase,
            topup["provider_order_code"],
        )
        return refreshed or topup

    if provider_status == "CANCELLED":
        return _set_topup_status(supabase, topup, "cancelled")

    if _topup_is_expired(topup):
        return _set_topup_status(supabase, topup, "expired")

    return topup


def _set_topup_status(
    supabase,
    topup: dict[str, Any],
    status_value: str,
) -> dict[str, Any]:
    if topup.get("status") == status_value:
        return topup
    return supabase.update_one(
        "wallet_topups",
        filters={"id": topup["id"], "user_id": topup["user_id"]},
        payload={"status": status_value},
        columns=WALLET_TOPUP_COLUMNS,
    )


def _generate_order_code() -> int:
    return int(f"{int(time.time())}{secrets.randbelow(1000):03d}")


def _build_topup_description(provider_order_code: str) -> str:
    return f"NAP {provider_order_code}"


def _build_topup_return_url(provider_order_code: str, return_to: str | None) -> str:
    query = {
        "topup": "success",
        "orderCode": provider_order_code,
    }
    if return_to:
        query["returnTo"] = return_to
    return f"{settings.app_public_base_url.rstrip('/')}/topup?{urlencode(query)}"


def _build_topup_cancel_url(provider_order_code: str, return_to: str | None) -> str:
    query = {
        "topup": "cancel",
        "orderCode": provider_order_code,
    }
    if return_to:
        query["returnTo"] = return_to
    return f"{settings.app_public_base_url.rstrip('/')}/topup?{urlencode(query)}"


def _normalize_return_to(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.startswith("/") or normalized.startswith("//") or "://" in normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="return_to must be a relative app path.",
        )
    return normalized


def _topup_is_expired(topup: dict[str, Any]) -> bool:
    expires_at = _parse_timestamp(topup.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mark_topup_failed(
    supabase,
    topup_id: str,
    user_id: str,
    metadata: dict[str, Any],
) -> None:
    try:
        supabase.update_one(
            "wallet_topups",
            filters={"id": topup_id, "user_id": user_id},
            payload={
                "status": "failed",
                "metadata": metadata,
            },
            columns="id,status",
        )
    except SupabaseAPIError:
        pass
