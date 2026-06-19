from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.security import get_current_user
from app.db.supabase_client import SupabaseAPIError, get_supabase_rest_client
from app.schemas.auth import CurrentUser
from app.schemas.payment import CheckoutResponse, PaymentStatusResponse, PayOSWebhookResponse
from app.services.payments.payos import PayOSError, get_payos_client

from app.services.wallets import (
    credit_wallet_topup,
    get_wallet_topup_by_provider_order_code,
)

router = APIRouter(tags=["payments"])

_PAYMENT_STATUS_COLUMNS = (
    "id,user_id,document_id,amount,currency,status,provider_order_code,"
    "checkout_url,qr_code,paid_at,expires_at,metadata,created_at,updated_at"
)


@router.post("/api/v1/documents/{document_id}/checkout", response_model=CheckoutResponse)
async def create_checkout(
    *,
    document_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> CheckoutResponse:
    document_id = str(document_id)
    try:
        supabase = get_supabase_rest_client()
        document = supabase.select_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            columns="id,user_id,document_type,status",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    if document["status"] not in {"analyzed", "pending_payment"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document cannot create checkout from status {document['status']}.",
        )

    try:
        paid_order = supabase.select_one(
            "orders",
            filters={
                "document_id": document_id,
                "user_id": current_user.user_id,
                "status": "paid",
            },
            columns="id,status",
        )
        pending_orders = supabase.select_many(
            "orders",
            filters={
                "document_id": document_id,
                "user_id": current_user.user_id,
                "status": "pending",
            },
            columns=(
                "id,document_id,amount,currency,status,provider_order_code,"
                "checkout_url,qr_code,expires_at,created_at"
            ),
            order="created_at.desc",
            limit=5,
        )
        active_pending_order = _expire_and_find_active_pending_order(
            supabase,
            pending_orders,
            current_user.user_id,
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if paid_order is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document already has a paid order.",
        )

    if active_pending_order is not None:
        if active_pending_order.get("checkout_url"):
            return _checkout_response(active_pending_order, reused=True)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A payment checkout is already being initialized. Please retry shortly.",
        )

    try:
        price_vnd = _resolve_document_price(supabase, document["document_type"])
    except SupabaseAPIError as exc:
        try:
            concurrent_order = supabase.select_one(
                "orders",
                filters={
                    "document_id": document_id,
                    "user_id": current_user.user_id,
                    "status": "pending",
                },
                columns=(
                    "id,document_id,amount,currency,status,provider_order_code,"
                    "checkout_url,qr_code,expires_at"
                ),
            )
        except SupabaseAPIError:
            concurrent_order = None
        if concurrent_order and concurrent_order.get("checkout_url"):
            return _checkout_response(concurrent_order, reused=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    order_code = _generate_order_code()
    provider_order_code = str(order_code)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.payos_link_ttl_minutes)
    return_url = _build_payment_return_url(document_id, provider_order_code)
    cancel_url = _build_payment_cancel_url(document_id, provider_order_code)
    description = _build_payment_description(provider_order_code)

    try:
        order = supabase.insert_one(
            "orders",
            payload={
                "user_id": current_user.user_id,
                "document_id": document_id,
                "amount": price_vnd,
                "currency": "VND",
                "status": "pending",
                "payment_provider": "payos",
                "provider_order_code": provider_order_code,
                "expires_at": expires_at.isoformat(),
                "metadata": {
                    "document_type": document["document_type"],
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                },
            },
            columns="id,document_id,amount,currency,status,provider_order_code,expires_at",
        )
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        payos = get_payos_client()
        payos_response = payos.create_payment_link(
            order_code=order_code,
            amount=price_vnd,
            description=description,
            return_url=return_url,
            cancel_url=cancel_url,
            buyer_email=current_user.email,
            expired_at=int(expires_at.timestamp()),
        )
        payos_data = payos_response["data"]
        updated_order = supabase.update_one(
            "orders",
            filters={"id": order["id"], "user_id": current_user.user_id},
            payload={
                "checkout_url": payos_data["checkoutUrl"],
                "qr_code": payos_data.get("qrCode"),
                "metadata": {
                    "document_type": document["document_type"],
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                    "payos": payos_data,
                },
            },
            columns="id,document_id,amount,currency,status,provider_order_code,checkout_url,qr_code,expires_at",
        )
        supabase.update_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            payload={"status": "pending_payment"},
            columns="id,status",
        )
    except PayOSError as exc:
        _mark_order_failed(supabase, order["id"], current_user.user_id, {"error": str(exc)})
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except SupabaseAPIError as exc:
        _mark_order_failed(supabase, order["id"], current_user.user_id, {"error": str(exc)})
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return _checkout_response(updated_order, reused=False)


@router.get(
    "/api/v1/documents/{document_id}/payment-status",
    response_model=PaymentStatusResponse,
)
async def get_payment_status(
    *,
    document_id: UUID,
    order_code: str | None = Query(default=None, alias="orderCode"),
    current_user: CurrentUser = Depends(get_current_user),
) -> PaymentStatusResponse:
    document_id = str(document_id)
    try:
        supabase = get_supabase_rest_client()
        document = supabase.select_one(
            "documents",
            filters={"id": document_id, "user_id": current_user.user_id},
            columns="id,user_id,status",
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )

        if order_code:
            order = supabase.select_one(
                "orders",
                filters={
                    "document_id": document_id,
                    "user_id": current_user.user_id,
                    "provider_order_code": order_code,
                },
                columns=_PAYMENT_STATUS_COLUMNS,
            )
        else:
            orders = supabase.select_many(
                "orders",
                filters={"document_id": document_id, "user_id": current_user.user_id},
                columns=_PAYMENT_STATUS_COLUMNS,
                order="created_at.desc",
                limit=1,
            )
            order = orders[0] if orders else None
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment order not found.",
        )

    provider_status = _metadata_provider_status(order)
    if order["status"] == "pending":
        try:
            payos_response = get_payos_client().get_payment_link_information(
                order["provider_order_code"]
            )
            order, provider_status = _reconcile_payos_order(
                supabase,
                order=order,
                payos_data=payos_response["data"],
            )
        except PayOSError as exc:
            if _order_is_expired(order):
                order = _set_order_status(
                    supabase,
                    order,
                    new_status="expired",
                    provider_status=provider_status or "EXPIRED",
                )
                provider_status = provider_status or "EXPIRED"
            else:
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except SupabaseAPIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if order["status"] == "paid":
        _mark_document_paid(supabase, document_id, current_user.user_id)

    return _payment_status_response(
        order,
        provider_status=provider_status,
    )


@router.post("/api/v1/payments/payos/webhook", response_model=PayOSWebhookResponse)
async def handle_payos_webhook(request: Request) -> PayOSWebhookResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload.",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be a JSON object.",
        )

    try:
        payos = get_payos_client()
    except PayOSError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not payos.verify_webhook_signature(payload):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payOS webhook signature.",
        )

    data = payload.get("data") or {}
    provider_order_code = str(data.get("orderCode") or "")
    if not provider_order_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload does not include orderCode.",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    event_key = _payos_event_key(payload, provider_order_code)
    try:
        supabase = get_supabase_rest_client()
        webhook_event = supabase.insert_one_if_absent(
            "payment_webhook_events",
            payload={
                "provider": "payos",
                "provider_order_code": provider_order_code,
                "event_type": _payos_event_type(payload),
                "payload": payload,
                "checksum": payload.get("signature"),
                "event_key": event_key,
                "processed": False,
            },
            on_conflict="event_key",
            columns="id,processed,processing_error",
        )
        duplicate = webhook_event is None
        if webhook_event is None:
            webhook_event = supabase.select_one(
                "payment_webhook_events",
                filters={"event_key": event_key},
                columns="id,processed,processing_error",
            )

        order = supabase.select_one(
            "orders",
            filters={"provider_order_code": provider_order_code},
            columns=_PAYMENT_STATUS_COLUMNS,
                 )

        topup = None
        if order is None:
            topup = get_wallet_topup_by_provider_order_code(
                supabase,
                provider_order_code,
            )
        
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if webhook_event is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Webhook event could not be persisted.",
        )

    if duplicate and webhook_event.get("processed"):
        return PayOSWebhookResponse(
            status=(order or topup or {}).get("status", "ignored"),
            processed=True,
            provider_order_code=provider_order_code,
            duplicate=True,
            event_id=webhook_event["id"],
        )

    if order is None and topup is None:
        _mark_webhook_event_processed(
            supabase,
            webhook_event["id"],
            now_iso,
            processing_error="order_not_found",
        )
        return PayOSWebhookResponse(
            status="ignored",
            processed=True,
            provider_order_code=provider_order_code,
            duplicate=duplicate,
            event_id=webhook_event["id"],
        )

    if order is None:
        return _process_wallet_topup_webhook(
            supabase,
            topup=topup,
            payload=payload,
            webhook_event=webhook_event,
            provider_order_code=provider_order_code,
            duplicate=duplicate,
            now_iso=now_iso,
        )

    if int(data.get("amount") or 0) != int(order["amount"]):
        _mark_webhook_event_error(
            supabase,
            webhook_event["id"],
            "Webhook amount does not match order amount.",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook amount does not match order amount.",
        )

    if str(data.get("currency") or "VND") != order["currency"]:
        _mark_webhook_event_error(
            supabase,
            webhook_event["id"],
            "Webhook currency does not match order currency.",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook currency does not match order currency.",
        )

    if _payos_webhook_is_paid(payload):
        if order["status"] == "paid":
            updated_order = order
        else:
            updated_order = _set_order_status(
                supabase,
                order,
                new_status="paid",
                provider_status="PAID",
                paid_at=_parse_payos_paid_at(data) or now_iso,
                extra_metadata={"payos_last_webhook": data},
            )
        _mark_document_paid(supabase, order["document_id"], order["user_id"])
    else:
        next_status = (
            "expired"
            if order["status"] == "pending" and _order_is_expired(order)
            else order["status"]
        )
        updated_order = _set_order_status(
            supabase,
            order,
            new_status=next_status,
            provider_status=str(data.get("status") or data.get("code") or "UNKNOWN"),
            extra_metadata={"payos_last_webhook": data},
        )

    try:
        _mark_webhook_event_processed(supabase, webhook_event["id"], now_iso)
    except SupabaseAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return PayOSWebhookResponse(
        status=updated_order["status"],
        processed=True,
        provider_order_code=provider_order_code,
        duplicate=duplicate,
        event_id=webhook_event["id"],
    )


def _process_wallet_topup_webhook(
    supabase,
    *,
    topup: dict[str, Any] | None,
    payload: dict[str, Any],
    webhook_event: dict[str, Any],
    provider_order_code: str,
    duplicate: bool,
    now_iso: str,
) -> PayOSWebhookResponse:
    if topup is None:
        _mark_webhook_event_processed(
            supabase,
            webhook_event["id"],
            now_iso,
            processing_error="topup_not_found",
        )
        return PayOSWebhookResponse(
            status="ignored",
            processed=True,
            provider_order_code=provider_order_code,
            duplicate=duplicate,
            event_id=webhook_event["id"],
        )

    data = payload.get("data") or {}
    if int(data.get("amount") or 0) != int(topup["amount"]):
        _mark_webhook_event_error(
            supabase,
            webhook_event["id"],
            "Webhook topup amount does not match.",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook topup amount does not match.",
        )

    if str(data.get("currency") or "VND") != topup["currency"]:
        _mark_webhook_event_error(
            supabase,
            webhook_event["id"],
            "Webhook topup currency does not match.",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook topup currency does not match.",
        )

    if _payos_webhook_is_paid(payload):
        try:
            credit_wallet_topup(
                supabase,
                provider_order_code=provider_order_code,
                paid_at=_parse_payos_paid_at(data) or now_iso,
            )
            next_status = "paid"
        except SupabaseAPIError as exc:
            _mark_webhook_event_error(
                supabase,
                webhook_event["id"],
                str(exc),
            )
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc
    else:
        next_status = _next_topup_status_from_webhook(topup, data)
        if next_status != topup.get("status"):
            _set_wallet_topup_status(supabase, topup, next_status)

    _mark_webhook_event_processed(supabase, webhook_event["id"], now_iso)

    return PayOSWebhookResponse(
        status=next_status,
        processed=True,
        provider_order_code=provider_order_code,
        duplicate=duplicate,
        event_id=webhook_event["id"],
    )


def _resolve_document_price(supabase, document_type: str) -> int:
    template = supabase.select_one(
        "document_templates",
        filters={"key": document_type, "is_active": "true"},
        columns="key,price_vnd",
    )
    price_vnd = int((template or {}).get("price_vnd") or settings.price_per_file_vnd)
    if price_vnd <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document price is not configured.",
        )
    return price_vnd


def _checkout_response(order: dict[str, Any], *, reused: bool) -> CheckoutResponse:
    return CheckoutResponse(
        order_id=order["id"],
        document_id=order["document_id"],
        status=order["status"],
        amount=int(order["amount"]),
        currency=order["currency"],
        provider_order_code=order["provider_order_code"],
        checkout_url=order["checkout_url"],
        qr_code=order.get("qr_code"),
        expires_at=order["expires_at"],
        reused=reused,
    )


def _payment_status_response(
    order: dict[str, Any],
    *,
    provider_status: str | None,
) -> PaymentStatusResponse:
    paid = order["status"] == "paid"
    fixed_file_allowed = paid or not settings.fixed_file_payment_required
    return PaymentStatusResponse(
        order_id=order["id"],
        document_id=order["document_id"],
        status=order["status"],
        provider_status=provider_status,
        amount=int(order["amount"]),
        currency=order["currency"],
        provider_order_code=order["provider_order_code"],
        checkout_url=order.get("checkout_url"),
        expires_at=order["expires_at"],
        paid_at=order.get("paid_at"),
        can_fix=fixed_file_allowed,
        can_download=fixed_file_allowed,
        refreshed_at=datetime.now(timezone.utc).isoformat(),
    )


def _expire_and_find_active_pending_order(
    supabase,
    orders: list[dict[str, Any]],
    user_id: str,
) -> dict[str, Any] | None:
    active_order: dict[str, Any] | None = None
    for order in orders:
        if _order_is_expired(order):
            supabase.update_maybe_one(
                "orders",
                filters={"id": order["id"], "user_id": user_id},
                raw_filters={"status": "eq.pending"},
                payload={"status": "expired"},
                columns="id,status",
            )
            continue
        if active_order is None:
            active_order = order
    return active_order


def _reconcile_payos_order(
    supabase,
    *,
    order: dict[str, Any],
    payos_data: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    provider_order_code = str(payos_data.get("orderCode") or "")
    if provider_order_code != str(order["provider_order_code"]):
        raise PayOSError("payOS returned a different orderCode.", status_code=502)

    provider_amount = int(payos_data.get("amount") or 0)
    if provider_amount != int(order["amount"]):
        raise PayOSError("payOS returned a different order amount.", status_code=502)

    provider_status = str(payos_data.get("status") or "UNKNOWN").upper()
    if provider_status == "PAID":
        amount_paid = int(payos_data.get("amountPaid") or 0)
        if amount_paid < int(order["amount"]):
            raise PayOSError(
                "payOS reports PAID but the paid amount is insufficient.",
                status_code=502,
            )
        updated = _set_order_status(
            supabase,
            order,
            new_status="paid",
            provider_status=provider_status,
            paid_at=order.get("paid_at") or datetime.now(timezone.utc).isoformat(),
            extra_metadata={"payos_status_response": payos_data},
        )
        return updated, provider_status

    if provider_status == "CANCELLED":
        updated = _set_order_status(
            supabase,
            order,
            new_status="cancelled",
            provider_status=provider_status,
            extra_metadata={"payos_status_response": payos_data},
        )
        return updated, provider_status

    if provider_status in {"PENDING", "PROCESSING"}:
        new_status = "expired" if _order_is_expired(order) else "pending"
        updated = _set_order_status(
            supabase,
            order,
            new_status=new_status,
            provider_status=provider_status,
            extra_metadata={"payos_status_response": payos_data},
        )
        return updated, provider_status

    updated = _set_order_status(
        supabase,
        order,
        new_status=order["status"],
        provider_status=provider_status,
        extra_metadata={"payos_status_response": payos_data},
    )
    return updated, provider_status


def _set_order_status(
    supabase,
    order: dict[str, Any],
    *,
    new_status: str,
    provider_status: str | None,
    paid_at: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if order["status"] == "paid" and new_status != "paid":
        return order

    metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
    payload: dict[str, Any] = {
        "status": new_status,
        "metadata": {
            **metadata,
            **(extra_metadata or {}),
            "payos_provider_status": provider_status,
            "payos_status_checked_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    if paid_at:
        payload["paid_at"] = paid_at

    return supabase.update_one(
        "orders",
        filters={"id": order["id"]},
        payload=payload,
        columns=_PAYMENT_STATUS_COLUMNS,
    )


def _mark_document_paid(supabase, document_id: str, user_id: str) -> None:
    supabase.update_maybe_one(
        "documents",
        filters={"id": document_id, "user_id": user_id},
        raw_filters={"status": "in.(analyzed,pending_payment)"},
        payload={"status": "paid"},
        columns="id,status",
    )


def _metadata_provider_status(order: dict[str, Any]) -> str | None:
    metadata = order.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("payos_provider_status")
    return str(value) if value else None


def _order_is_expired(order: dict[str, Any]) -> bool:
    expires_at = _parse_timestamp(order.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(timezone.utc)


def _next_topup_status_from_webhook(topup: dict[str, Any], data: dict[str, Any]) -> str:
    if topup.get("status") == "paid":
        return "paid"

    provider_status = str(data.get("status") or data.get("code") or "").upper()
    if provider_status == "CANCELLED":
        return "cancelled"
    if _order_is_expired(topup):
        return "expired"
    return str(topup.get("status") or "pending")


def _set_wallet_topup_status(
    supabase,
    topup: dict[str, Any],
    next_status: str,
) -> dict[str, Any]:
    if topup.get("status") == "paid" and next_status != "paid":
        return topup
    return supabase.update_one(
        "wallet_topups",
        filters={"id": topup["id"]},
        payload={"status": next_status},
        columns="id,status",
    )


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


def _generate_order_code() -> int:
    return int(f"{int(time.time())}{secrets.randbelow(1000):03d}")


def _build_payment_description(provider_order_code: str) -> str:
    return f"THESIS {provider_order_code[-8:]}"


def _build_payment_return_url(document_id: str, provider_order_code: str) -> str:
    return (
        f"{settings.app_public_base_url.rstrip('/')}/documents/{document_id}"
        f"?payment=success&orderCode={provider_order_code}"
    )


def _build_payment_cancel_url(document_id: str, provider_order_code: str) -> str:
    return (
        f"{settings.app_public_base_url.rstrip('/')}/documents/{document_id}"
        f"?payment=cancel&orderCode={provider_order_code}"
    )


def _payos_webhook_is_paid(payload: dict[str, Any]) -> bool:
    data = payload.get("data") or {}
    return (
        payload.get("success") is True
        and payload.get("code") == "00"
        and data.get("code") == "00"
    )


def _payos_event_type(payload: dict[str, Any]) -> str:
    data = payload.get("data") or {}
    if _payos_webhook_is_paid(payload):
        return "payment.paid"
    return f"payment.{data.get('code') or payload.get('code') or 'unknown'}"


def _payos_event_key(payload: dict[str, Any], provider_order_code: str) -> str:
    signature = str(payload.get("signature") or "")
    raw_key = f"payos:{provider_order_code}:{signature}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _mark_webhook_event_processed(
    supabase,
    event_id: str,
    processed_at: str,
    *,
    processing_error: str | None = None,
) -> None:
    supabase.update_one(
        "payment_webhook_events",
        filters={"id": event_id},
        payload={
            "processed": True,
            "processed_at": processed_at,
            "processing_error": processing_error,
        },
        columns="id,processed",
    )


def _mark_webhook_event_error(supabase, event_id: str, error: str) -> None:
    try:
        supabase.update_one(
            "payment_webhook_events",
            filters={"id": event_id},
            payload={"processing_error": error},
            columns="id,processed",
        )
    except SupabaseAPIError:
        pass


def _parse_payos_paid_at(data: dict[str, Any]) -> str | None:
    value = data.get("transactionDateTime")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone(timedelta(hours=7))).astimezone(timezone.utc).isoformat()


def _mark_order_failed(supabase, order_id: str, user_id: str, metadata: dict[str, Any]) -> None:
    try:
        supabase.update_one(
            "orders",
            filters={"id": order_id, "user_id": user_id},
            payload={"status": "failed", "metadata": metadata},
            columns="id,status",
        )
    except SupabaseAPIError:
        pass
