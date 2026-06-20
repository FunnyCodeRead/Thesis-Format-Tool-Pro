from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException

from app.api.documents import (
    _ensure_fixed_document_purchased,
    create_download_token,
)
from app.api.payments import handle_payos_webhook
from app.schemas.auth import CurrentUser


DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"


def _future_timestamp() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()


class _DownloadTokenSupabase:
    def __init__(self) -> None:
        self.inserted_download_token = None
        self.select_one_calls = []

    def select_one(self, table, *, filters, columns):
        self.select_one_calls.append(
            {"table": table, "filters": filters, "columns": columns}
        )
        if table == "documents":
            return {
                "id": DOCUMENT_ID,
                "user_id": USER_ID,
                "status": "fixed",
                "fixed_file_key": f"users/{USER_ID}/documents/{DOCUMENT_ID}/fixed.docx",
                "original_filename": "do-an.docx",
            }
        return None

    def insert_one(self, table, *, payload, columns):
        if table != "download_tokens":
            raise AssertionError(table)
        self.inserted_download_token = payload
        return {"id": "token-id"}


class _PurchaseSupabase:
    def __init__(self, purchase=None) -> None:
        self.purchase = purchase

    def select_one(self, table, *, filters, columns):
        if table == "document_purchases":
            return self.purchase
        return None


class _TopupWebhookSupabase:
    def __init__(self) -> None:
        self.topup = {
            "id": "33333333-3333-4333-8333-333333333333",
            "user_id": USER_ID,
            "amount": 100000,
            "currency": "VND",
            "status": "pending",
            "payment_provider": "payos",
            "provider_order_code": "202606200001",
            "checkout_url": "https://pay.example/topup",
            "qr_code": None,
            "paid_at": None,
            "expires_at": _future_timestamp(),
            "metadata": {},
            "created_at": "2026-06-20T08:00:00+00:00",
            "updated_at": "2026-06-20T08:00:00+00:00",
        }
        self.event_updates = []
        self.rpc_calls = []

    def insert_one_if_absent(self, table, *, payload, on_conflict, columns):
        if table != "payment_webhook_events":
            raise AssertionError(table)
        return {
            "id": "44444444-4444-4444-8444-444444444444",
            "processed": False,
            "processing_error": None,
        }

    def select_one(self, table, *, filters, columns):
        if table == "orders":
            return None
        if table == "wallet_topups":
            return self.topup
        if table == "payment_webhook_events":
            return {
                "id": "44444444-4444-4444-8444-444444444444",
                "processed": True,
                "processing_error": None,
            }
        return None

    def update_one(self, table, *, filters, payload, columns):
        if table == "payment_webhook_events":
            self.event_updates.append(payload)
            return {"id": filters["id"], **payload}
        if table == "wallet_topups":
            self.topup = {**self.topup, **payload}
            return self.topup
        raise AssertionError(table)

    def rpc(self, function_name, payload):
        self.rpc_calls.append({"function_name": function_name, "payload": payload})
        return {
            "ok": True,
            "duplicate": False,
            "credited_vnd": self.topup["amount"],
            "balance_vnd": self.topup["amount"],
        }


class _FakePayOS:
    def verify_webhook_signature(self, payload):
        return True


class _Request:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def json(self):
        return self.payload


class WalletPurchaseFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.current_user = CurrentUser(
            user_id=USER_ID,
            email="student@example.com",
            role="authenticated",
        )

    async def test_download_token_charges_wallet_before_token_creation(self) -> None:
        supabase = _DownloadTokenSupabase()

        with (
            patch("app.api.documents.get_supabase_rest_client", return_value=supabase),
            patch(
                "app.api.documents.purchase_document_with_wallet",
                return_value={
                    "ok": True,
                    "already_purchased": False,
                    "charged_vnd": 19000,
                    "balance_vnd": 81000,
                },
            ) as purchase,
        ):
            response = await create_download_token(
                document_id=UUID(DOCUMENT_ID),
                current_user=self.current_user,
            )

        purchase.assert_called_once()
        self.assertEqual(response.document_id, DOCUMENT_ID)
        self.assertEqual(supabase.inserted_download_token["kind"], "fixed")
        self.assertNotIn("token", supabase.inserted_download_token)
        self.assertIn("token_hash", supabase.inserted_download_token)

    async def test_download_token_returns_402_when_wallet_balance_is_insufficient(self) -> None:
        supabase = _DownloadTokenSupabase()

        with (
            patch("app.api.documents.get_supabase_rest_client", return_value=supabase),
            patch(
                "app.api.documents.purchase_document_with_wallet",
                return_value={
                    "ok": False,
                    "reason": "insufficient_funds",
                    "balance_vnd": 10000,
                    "required_amount": 19000,
                    "deficit_vnd": 9000,
                },
            ),
        ):
            response = await create_download_token(
                document_id=UUID(DOCUMENT_ID),
                current_user=self.current_user,
            )

        self.assertEqual(response.status_code, 402)
        body = json.loads(response.body)
        self.assertEqual(body["reason"], "insufficient_wallet_balance")
        self.assertEqual(body["deficit_vnd"], 9000)
        self.assertIn("/topup?returnTo=", body["topup_url"])
        self.assertIsNone(supabase.inserted_download_token)

    def test_download_rejects_when_document_purchase_is_missing(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _ensure_fixed_document_purchased(
                _PurchaseSupabase(),
                document_id=DOCUMENT_ID,
                user_id=USER_ID,
            )

        self.assertEqual(raised.exception.status_code, 402)

    async def test_payos_webhook_credits_wallet_topup_when_no_document_order_exists(self) -> None:
        supabase = _TopupWebhookSupabase()
        payload = {
            "code": "00",
            "desc": "success",
            "success": True,
            "data": {
                "orderCode": int(supabase.topup["provider_order_code"]),
                "amount": supabase.topup["amount"],
                "currency": "VND",
                "code": "00",
                "transactionDateTime": "2026-06-20 15:10:00",
            },
            "signature": "valid-signature",
        }

        with (
            patch("app.api.payments.get_supabase_rest_client", return_value=supabase),
            patch("app.api.payments.get_payos_client", return_value=_FakePayOS()),
        ):
            response = await handle_payos_webhook(_Request(payload))

        self.assertEqual(response.status, "paid")
        self.assertTrue(response.processed)
        self.assertEqual(supabase.rpc_calls[0]["function_name"], "credit_wallet_topup")
        self.assertTrue(supabase.event_updates[-1]["processed"])


if __name__ == "__main__":
    unittest.main()
