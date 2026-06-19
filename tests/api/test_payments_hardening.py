from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

from app.api.payments import (
    create_checkout,
    get_payment_status,
    handle_payos_webhook,
)
from app.schemas.auth import CurrentUser


DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"


def _future_timestamp() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()


def _base_order(**overrides):
    order = {
        "id": "33333333-3333-4333-8333-333333333333",
        "user_id": USER_ID,
        "document_id": DOCUMENT_ID,
        "amount": 49000,
        "currency": "VND",
        "status": "pending",
        "provider_order_code": "202606120001",
        "checkout_url": "https://pay.example/checkout",
        "qr_code": "QR",
        "paid_at": None,
        "expires_at": _future_timestamp(),
        "metadata": {},
        "created_at": "2026-06-12T08:00:00+00:00",
        "updated_at": "2026-06-12T08:00:00+00:00",
    }
    order.update(overrides)
    return order


class _FakePayOS:
    def __init__(self, status_data=None) -> None:
        self.create_call = None
        self.status_data = status_data

    def create_payment_link(self, **kwargs):
        self.create_call = kwargs
        return {
            "data": {
                "checkoutUrl": "https://pay.example/new-checkout",
                "qrCode": "NEW-QR",
            }
        }

    def get_payment_link_information(self, order_code):
        return {"code": "00", "data": self.status_data}

    def verify_webhook_signature(self, payload):
        return True


class _CheckoutSupabase:
    def __init__(self, pending_orders=None) -> None:
        self.pending_orders = pending_orders or []
        self.inserted_order = None
        self.updated_documents = []

    def select_one(self, table, *, filters, columns):
        if table == "documents":
            return {
                "id": DOCUMENT_ID,
                "user_id": USER_ID,
                "document_type": "do_an_tot_nghiep",
                "status": "analyzed",
            }
        if table == "orders" and filters.get("status") == "paid":
            return None
        if table == "document_templates":
            return {"key": "do_an_tot_nghiep", "price_vnd": 49000}
        return None

    def select_many(self, table, *, filters, columns, order=None, limit=None):
        if table == "orders":
            return self.pending_orders
        return []

    def insert_one(self, table, *, payload, columns):
        self.inserted_order = {**_base_order(), **payload}
        return self.inserted_order

    def update_one(self, table, *, filters, payload, columns):
        if table == "orders":
            self.inserted_order = {**self.inserted_order, **payload}
            return self.inserted_order
        if table == "documents":
            self.updated_documents.append(payload)
            return {"id": DOCUMENT_ID, **payload}
        raise AssertionError(table)

    def update_maybe_one(self, *args, **kwargs):
        return None


class _StatusSupabase:
    def __init__(self, order) -> None:
        self.order = order
        self.document_updates = []

    def select_one(self, table, *, filters, columns):
        if table == "documents":
            return {"id": DOCUMENT_ID, "user_id": USER_ID, "status": "pending_payment"}
        return None

    def select_many(self, table, *, filters, columns, order=None, limit=None):
        return [self.order] if table == "orders" else []

    def update_one(self, table, *, filters, payload, columns):
        if table == "orders":
            self.order = {**self.order, **payload}
            return self.order
        raise AssertionError(table)

    def update_maybe_one(self, table, *, filters, payload, columns, raw_filters=None):
        if table == "documents":
            self.document_updates.append(payload)
            return {"id": DOCUMENT_ID, **payload}
        return None


class _WebhookSupabase:
    def __init__(self, *, order, duplicate=False) -> None:
        self.order = order
        self.duplicate = duplicate
        self.order_updates = []
        self.event_updates = []

    def insert_one_if_absent(self, table, *, payload, on_conflict, columns):
        if self.duplicate:
            return None
        return {
            "id": "44444444-4444-4444-8444-444444444444",
            "processed": False,
            "processing_error": None,
        }

    def select_one(self, table, *, filters, columns):
        if table == "payment_webhook_events":
            return {
                "id": "44444444-4444-4444-8444-444444444444",
                "processed": True,
                "processing_error": None,
            }
        if table == "orders":
            return self.order
        return None

    def update_one(self, table, *, filters, payload, columns):
        if table == "orders":
            self.order_updates.append(payload)
            self.order = {**self.order, **payload}
            return self.order
        if table == "payment_webhook_events":
            self.event_updates.append(payload)
            return {"id": filters["id"], **payload}
        raise AssertionError(table)

    def update_maybe_one(self, *args, **kwargs):
        return {"id": DOCUMENT_ID, "status": "paid"}


class _Request:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def json(self):
        return self.payload


class PaymentHardeningTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.current_user = CurrentUser(
            user_id=USER_ID,
            email="student@example.com",
            role="authenticated",
        )

    async def test_checkout_uses_backend_price_and_provider_urls(self) -> None:
        supabase = _CheckoutSupabase()
        payos = _FakePayOS()

        with (
            patch("app.api.payments.get_supabase_rest_client", return_value=supabase),
            patch("app.api.payments.get_payos_client", return_value=payos),
        ):
            response = await create_checkout(
                document_id=UUID(DOCUMENT_ID),
                current_user=self.current_user,
            )

        self.assertEqual(payos.create_call["amount"], 49000)
        self.assertIn(f"/documents/{DOCUMENT_ID}", payos.create_call["return_url"])
        self.assertEqual(response.checkout_url, "https://pay.example/new-checkout")
        self.assertFalse(response.reused)
        self.assertEqual(supabase.updated_documents[-1]["status"], "pending_payment")

    async def test_checkout_reuses_unexpired_pending_order(self) -> None:
        existing_order = _base_order()
        supabase = _CheckoutSupabase(pending_orders=[existing_order])

        with patch("app.api.payments.get_supabase_rest_client", return_value=supabase):
            response = await create_checkout(
                document_id=UUID(DOCUMENT_ID),
                current_user=self.current_user,
            )

        self.assertTrue(response.reused)
        self.assertEqual(response.order_id, existing_order["id"])
        self.assertIsNone(supabase.inserted_order)

    async def test_payment_status_reconciles_paid_provider_state(self) -> None:
        order = _base_order()
        supabase = _StatusSupabase(order)
        payos = _FakePayOS(
            {
                "orderCode": int(order["provider_order_code"]),
                "amount": order["amount"],
                "amountPaid": order["amount"],
                "status": "PAID",
            }
        )

        with (
            patch("app.api.payments.get_supabase_rest_client", return_value=supabase),
            patch("app.api.payments.get_payos_client", return_value=payos),
        ):
            response = await get_payment_status(
                document_id=UUID(DOCUMENT_ID),
                order_code=None,
                current_user=self.current_user,
            )

        self.assertEqual(response.status, "paid")
        self.assertEqual(response.provider_status, "PAID")
        self.assertTrue(response.can_fix)
        self.assertEqual(supabase.document_updates[-1]["status"], "paid")

    async def test_duplicate_processed_webhook_is_idempotent(self) -> None:
        order = _base_order(status="paid", paid_at="2026-06-12T08:10:00+00:00")
        supabase = _WebhookSupabase(order=order, duplicate=True)
        payload = _paid_webhook_payload(order)

        with (
            patch("app.api.payments.get_supabase_rest_client", return_value=supabase),
            patch("app.api.payments.get_payos_client", return_value=_FakePayOS()),
        ):
            response = await handle_payos_webhook(_Request(payload))

        self.assertTrue(response.duplicate)
        self.assertTrue(response.processed)
        self.assertEqual(response.status, "paid")
        self.assertEqual(supabase.order_updates, [])

    async def test_non_paid_webhook_cannot_downgrade_paid_order(self) -> None:
        order = _base_order(status="paid", paid_at="2026-06-12T08:10:00+00:00")
        supabase = _WebhookSupabase(order=order)
        payload = _paid_webhook_payload(order)
        payload["success"] = False
        payload["data"]["code"] = "01"

        with (
            patch("app.api.payments.get_supabase_rest_client", return_value=supabase),
            patch("app.api.payments.get_payos_client", return_value=_FakePayOS()),
        ):
            response = await handle_payos_webhook(_Request(payload))

        self.assertEqual(response.status, "paid")
        self.assertTrue(all(update["status"] == "paid" for update in supabase.order_updates))


def _paid_webhook_payload(order):
    return {
        "code": "00",
        "desc": "success",
        "success": True,
        "data": {
            "orderCode": int(order["provider_order_code"]),
            "amount": order["amount"],
            "currency": order["currency"],
            "code": "00",
            "transactionDateTime": "2026-06-12 15:10:00",
        },
        "signature": "valid-signature",
    }


if __name__ == "__main__":
    unittest.main()
